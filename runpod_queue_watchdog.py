"""RunPod queue watchdog: detect zombie idle/ready workers and remediate.

Observed failure mode (TRELLIS.2, 2026-07):
  health shows ready/idle >= 1, inProgress = 0, jobs stay IN_QUEUE forever.
  REST includeWorkers can show desiredStatus=EXITED while health still counts
  a ready/idle slot (FlashBoot / standby ghost).

Client-side defenses (no always-on GPU required):
  1) Detect zombie health pattern while job is IN_QUEUE
  2) Cancel stuck job
  3) DELETE ghost pods (EXITED / non-running) via REST
  4) Optional purge-queue
  5) Resubmit (optionally on a secondary endpoint)

Reusable from test_req_trellis2.py and later AI_MESH Studio backend.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import requests

REST_BASE = "https://rest.runpod.io/v1"
API_BASE = "https://api.runpod.ai/v2"

TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"})


class ZombieQueueError(RuntimeError):
    """Job stuck IN_QUEUE while health reports idle/ready workers."""


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def get_health(endpoint_id: str, api_key: str) -> dict[str, Any]:
    response = requests.get(
        f"{API_BASE}/{endpoint_id}/health",
        headers=_headers(api_key),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_status(endpoint_id: str, job_id: str, api_key: str) -> dict[str, Any]:
    response = requests.get(
        f"{API_BASE}/{endpoint_id}/status/{job_id}",
        headers=_headers(api_key),
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def cancel_job(endpoint_id: str, job_id: str, api_key: str) -> None:
    try:
        requests.post(
            f"{API_BASE}/{endpoint_id}/cancel/{job_id}",
            headers=_headers(api_key),
            timeout=60,
        )
    except Exception as exc:
        print(f"cancel warning: {exc}")


def purge_queue(endpoint_id: str, api_key: str) -> dict[str, Any]:
    response = requests.post(
        f"{API_BASE}/{endpoint_id}/purge-queue",
        headers=_headers(api_key),
        timeout=60,
    )
    return {"status_code": response.status_code, "body": response.text[:500]}


def list_endpoint_workers(endpoint_id: str, api_key: str) -> list[dict[str, Any]]:
    response = requests.get(
        f"{REST_BASE}/endpoints/{endpoint_id}?includeWorkers=true",
        headers=_headers(api_key),
        timeout=60,
    )
    response.raise_for_status()
    data = response.json() or {}
    workers = data.get("workers") or []
    return workers if isinstance(workers, list) else []


def is_zombie_health(health: dict[str, Any]) -> bool:
    """True when queue is blocked by a false-ready worker (not capacity/throttle)."""
    jobs = health.get("jobs") or {}
    workers = health.get("workers") or {}
    in_queue = int(jobs.get("inQueue") or 0)
    in_progress = int(jobs.get("inProgress") or 0)
    ready = int(workers.get("ready") or 0)
    idle = int(workers.get("idle") or 0)
    throttled = int(workers.get("throttled") or 0)
    initializing = int(workers.get("initializing") or 0)
    unhealthy = int(workers.get("unhealthy") or 0)

    if in_queue < 1 or in_progress > 0:
        return False
    if throttled > 0 or initializing > 0 or unhealthy > 0:
        return False
    return (ready + idle) > 0


def _worker_pod_id(worker: dict[str, Any]) -> str | None:
    for key in ("id", "podId", "pod_id"):
        value = worker.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def ghost_workers(workers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Workers that occupy slots but are not actually running jobs."""
    ghosts: list[dict[str, Any]] = []
    for worker in workers:
        status = str(worker.get("desiredStatus") or worker.get("desired_status") or "").upper()
        # EXITED / FAILED / TERMINATED ghosts; also empty status with no machine.
        if status in {"EXITED", "FAILED", "TERMINATED", "DEAD"}:
            ghosts.append(worker)
            continue
        if status in {"RUNNING", "IN_PROGRESS"}:
            continue
        # FlashBoot standby sometimes leaves odd statuses while health says ready.
        if status in {"", "UNKNOWN", "EXITED"} or worker.get("machineId") in (None, ""):
            if status != "RUNNING":
                ghosts.append(worker)
    return ghosts


def delete_pod(pod_id: str, api_key: str) -> tuple[int, str]:
    response = requests.delete(
        f"{REST_BASE}/pods/{pod_id}",
        headers=_headers(api_key),
        timeout=60,
    )
    return response.status_code, response.text[:300]


def ensure_no_ghost_workers(
    endpoint_id: str,
    api_key: str,
    *,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Delete EXITED/non-RUNNING workers before submit. Returns deleted pod records."""
    deleted: list[dict[str, Any]] = []
    try:
        workers = list_endpoint_workers(endpoint_id, api_key)
    except Exception as exc:
        log(f"proactive heal: list workers failed: {exc}")
        return deleted

    for worker in ghost_workers(workers):
        pod_id = _worker_pod_id(worker)
        status = worker.get("desiredStatus")
        if not pod_id:
            continue
        code, body = delete_pod(pod_id, api_key)
        if code in (200, 204):
            entry = {"pod_id": pod_id, "desiredStatus": status}
            deleted.append(entry)
            log(f"proactive heal: deleted ghost pod {pod_id} (was {status})")
        else:
            log(f"proactive heal: delete {pod_id} failed http={code} {body[:120]}")
    return deleted


def heal_endpoint(
    endpoint_id: str,
    api_key: str,
    *,
    purge: bool = False,
    delete_ghosts: bool = True,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """
    Best-effort remediation when zombie queue is detected.
    Safe for scale-to-zero: only deletes non-running / EXITED workers.
    """
    report: dict[str, Any] = {
        "endpoint_id": endpoint_id,
        "deleted": [],
        "delete_errors": [],
        "purged": None,
        "health_before": None,
        "health_after": None,
    }
    try:
        report["health_before"] = get_health(endpoint_id, api_key)
    except Exception as exc:
        log(f"heal: health_before failed: {exc}")

    if purge:
        report["purged"] = purge_queue(endpoint_id, api_key)
        log(f"heal: purge-queue -> {report['purged']}")

    if delete_ghosts:
        try:
            workers = list_endpoint_workers(endpoint_id, api_key)
        except Exception as exc:
            log(f"heal: list workers failed: {exc}")
            workers = []

        ghosts = ghost_workers(workers)
        if not ghosts and workers:
            # If health is zombie but no EXITED tag, still try deleting idle-looking pods.
            # Prefer not to kill a truly RUNNING worker.
            for worker in workers:
                status = str(worker.get("desiredStatus") or "").upper()
                if status != "RUNNING":
                    ghosts.append(worker)

        for worker in ghosts:
            pod_id = _worker_pod_id(worker)
            status = worker.get("desiredStatus")
            if not pod_id:
                report["delete_errors"].append({"worker": status, "error": "missing pod id"})
                continue
            code, body = delete_pod(pod_id, api_key)
            entry = {"pod_id": pod_id, "desiredStatus": status, "http": code}
            if code in (200, 204):
                report["deleted"].append(entry)
                log(f"heal: deleted ghost pod {pod_id} (was {status})")
            else:
                entry["body"] = body
                report["delete_errors"].append(entry)
                log(f"heal: delete {pod_id} failed http={code} {body}")

    time.sleep(2)
    try:
        report["health_after"] = get_health(endpoint_id, api_key)
    except Exception as exc:
        log(f"heal: health_after failed: {exc}")
    return report


def submit_job(endpoint_id: str, api_key: str, job_input: dict[str, Any]) -> str:
    response = requests.post(
        f"{API_BASE}/{endpoint_id}/run",
        headers=_headers(api_key),
        json={"input": job_input},
        timeout=60,
    )
    response.raise_for_status()
    job = response.json()
    job_id = job.get("id")
    if not job_id:
        raise RuntimeError(f"RunPod response missing job id: {job}")
    print(f"Submitted job {job_id} status={job.get('status')} endpoint={endpoint_id}")
    return str(job_id)


def wait_for_job(
    endpoint_id: str,
    job_id: str,
    api_key: str,
    *,
    poll_s: float = 5.0,
    max_wait_s: float = 30 * 60,
    zombie_after_s: float = 90.0,
) -> dict[str, Any]:
    deadline = time.time() + max_wait_s
    zombie_since: float | None = None

    while time.time() < deadline:
        payload = get_status(endpoint_id, job_id, api_key)
        status = payload.get("status")
        if status in TERMINAL:
            return payload

        if status == "IN_QUEUE":
            try:
                health = get_health(endpoint_id, api_key)
            except Exception as exc:
                print(f"health poll warning: {exc}")
                health = {}

            if is_zombie_health(health):
                now = time.time()
                if zombie_since is None:
                    zombie_since = now
                    workers = health.get("workers") or {}
                    print(
                        "Zombie queue suspected: "
                        f"ready={workers.get('ready')} idle={workers.get('idle')} "
                        f"inProgress=0 inQueue>=1 (watching {zombie_after_s:.0f}s)"
                    )
                elif now - zombie_since >= zombie_after_s:
                    raise ZombieQueueError(
                        f"ZOMBIE_QUEUE job={job_id} endpoint={endpoint_id} "
                        f"stuck IN_QUEUE with idle/ready workers for >={zombie_after_s:.0f}s"
                    )
            else:
                zombie_since = None
        else:
            zombie_since = None

        time.sleep(poll_s)

    raise TimeoutError(f"Timed out waiting for job {job_id}")


def run_with_zombie_retries(
    endpoint_id: str,
    api_key: str,
    job_input: dict[str, Any],
    *,
    secondary_endpoint_id: str | None = None,
    zombie_after_s: float = 90.0,
    zombie_retries: int = 2,
    max_wait_s: float = 30 * 60,
    heal: bool = True,
    purge_on_heal: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Submit + wait; on zombie: cancel, heal ghosts, resubmit (optional secondary)."""
    endpoints = [endpoint_id]
    if secondary_endpoint_id and secondary_endpoint_id != endpoint_id:
        endpoints.append(secondary_endpoint_id)

    attempt = 0
    last_error: Exception | None = None
    for ep in endpoints:
        for _ in range(zombie_retries + 1):
            attempt += 1
            print(f"\n--- attempt {attempt} on {ep} ---")
            if heal:
                ensure_no_ghost_workers(ep, api_key)
            job_id = submit_job(ep, api_key, job_input)
            try:
                final = wait_for_job(
                    ep,
                    job_id,
                    api_key,
                    zombie_after_s=zombie_after_s,
                    max_wait_s=max_wait_s,
                )
                return ep, final
            except ZombieQueueError as exc:
                last_error = exc
                print(str(exc))
                print("Cancelling stuck job...")
                cancel_job(ep, job_id, api_key)
                if heal:
                    print("Healing endpoint (delete ghost workers)...")
                    heal_endpoint(ep, api_key, purge=purge_on_heal, delete_ghosts=True)
                time.sleep(5)
                continue
        print(
            f"Exhausted zombie retries on {ep}. "
            "Consider FlashBoot off, workersStandby=0, workersMax>=2."
        )

    assert last_error is not None
    raise last_error
