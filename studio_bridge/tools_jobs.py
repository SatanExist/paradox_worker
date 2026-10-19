"""Tool jobs on finished models: where they run and how their status reads.

The lab is a small CPU box and must stay responsive for the site, so mesh work goes to the
tools worker on RunPod (worker_tools.py, Dockerfile.tools) — the same hookup as TRELLIS.2.
With no endpoint set and STUDIO_TOOLS_LOCAL=1 the lab runs tools itself, one at a time
(development on this PC). Job ids:

  tool:rp:<runpod-uuid>   on the tools worker
  tool:local:<uuid>       in this process (lost if the lab restarts)
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from studio_bridge.normalize import map_runpod_status

TOOL_PREFIX = "tool:"
RP_PREFIX = "tool:rp:"
LOCAL_PREFIX = "tool:local:"

OPERATIONS = {"print_prep"}
OUTPUT_KEY = re.compile(r"^tools/[A-Za-z0-9_.:-]{6,120}\.glb$")
MAX_INPUT_BYTES = 200 * 1024 * 1024


class ToolsNotConfiguredError(RuntimeError):
    """Neither a RunPod tools endpoint nor local tools are set up."""


def is_tool_job(job_id: str) -> bool:
    return (job_id or "").startswith(TOOL_PREFIX)


def _endpoint() -> str:
    return os.getenv("RUNPOD_ENDPOINT_ID_TOOLS", "").strip()


def _local_enabled() -> bool:
    return os.getenv("STUDIO_TOOLS_LOCAL", "").strip() in {"1", "true", "yes"}


def _check_url(url: str) -> None:
    """Only public https files: the lab must not be talked into fetching from its own network."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("modelUrl must be https")
    for info in socket.getaddrinfo(parsed.hostname, 443):
        addr = ipaddress.ip_address(info[4][0])
        if not addr.is_global:
            raise ValueError("modelUrl must be a public address")


def _check(operation: str, model_url: str, output_key: str) -> None:
    if operation not in OPERATIONS:
        raise ValueError(f"unknown operation: {operation}")
    if not OUTPUT_KEY.match(output_key or ""):
        raise ValueError("bad outputKey")
    _check_url(model_url)


# ---------------------------------------------------------------- local runs

_local_jobs: dict[str, dict[str, Any]] = {}
_local_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tools")


def _download(url: str) -> Path:
    import tempfile
    from urllib.request import Request, urlopen

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".glb")
    with urlopen(Request(url, headers={"User-Agent": "paradox-studio-tools"}), timeout=60) as resp:
        data = resp.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("model is too large")
    tmp.write(data)
    tmp.close()
    return Path(tmp.name)


def _run_local(job_id: str, operation: str, model_url: str, params: dict, output_key: str) -> None:
    from studio_bridge.r2_public import upload_public_file
    from studio_bridge.tools_ops import run_operation

    def update(**fields: Any) -> None:
        with _local_lock:
            _local_jobs[job_id].update(fields)

    update(status="running")
    in_path = out_path = None
    try:
        in_path = _download(model_url)
        out_path, report = run_operation(operation, in_path, params)
        url = upload_public_file(out_path, output_key)
        update(status="ready", modelUrl=url, report=report)
    except Exception as exc:  # the page shows this as the reason
        update(status="failed", error=str(exc)[:500])
    finally:
        for path in (in_path, out_path):
            if path is not None:
                path.unlink(missing_ok=True)


# ---------------------------------------------------------------- API


def create_tool_job(*, operation: str, model_url: str, params: dict[str, Any], output_key: str) -> dict[str, Any]:
    _check(operation, model_url, output_key)
    job_input = {"operation": operation, "model_url": model_url, "params": params or {}, "output_key": output_key}

    endpoint = _endpoint()
    if endpoint:
        from studio_bridge.gateway import _runpod_key
        from runpod_queue_watchdog import submit_job

        runpod_id = submit_job(endpoint, _runpod_key(), job_input)
        return {"jobId": f"{RP_PREFIX}{runpod_id}", "status": "queued", "provider": "runpod"}

    if _local_enabled():
        job_id = f"{LOCAL_PREFIX}{uuid.uuid4().hex}"
        with _local_lock:
            _local_jobs[job_id] = {"status": "queued"}
        _pool.submit(_run_local, job_id, operation, model_url, params or {}, output_key)
        return {"jobId": job_id, "status": "queued", "provider": "local"}

    raise ToolsNotConfiguredError("RUNPOD_ENDPOINT_ID_TOOLS is not set")


def get_tool_job(job_id: str) -> dict[str, Any]:
    if job_id.startswith(LOCAL_PREFIX):
        with _local_lock:
            job = dict(_local_jobs.get(job_id) or {})
        if not job:
            # The lab restarted and forgot it; the site marks the version failed.
            return {"jobId": job_id, "status": "failed", "error": "The tool was interrupted. Try again."}
        return {"jobId": job_id, "provider": "local", **job}

    if job_id.startswith(RP_PREFIX):
        endpoint = _endpoint()
        if not endpoint:
            raise ToolsNotConfiguredError("RUNPOD_ENDPOINT_ID_TOOLS is not set")
        from studio_bridge.gateway import _runpod_key
        from runpod_queue_watchdog import get_status

        raw = get_status(endpoint, job_id[len(RP_PREFIX) :], _runpod_key())
        status = map_runpod_status(raw.get("status"))
        output = raw.get("output") if isinstance(raw.get("output"), dict) else {}
        error = raw.get("error") or output.get("error")
        model_url = output.get("model_url")
        if status == "ready" and not model_url:
            status, error = "failed", error or "The tool finished without a model"
        return {
            "jobId": job_id,
            "provider": "runpod",
            "status": status,
            "runpodStatus": raw.get("status"),
            "modelUrl": model_url if isinstance(model_url, str) else None,
            "report": output.get("report") if isinstance(output.get("report"), dict) else None,
            "error": str(error)[:500] if error else None,
        }

    raise ValueError("malformed tool job id")
