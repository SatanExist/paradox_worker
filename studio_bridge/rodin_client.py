"""Rodin / Hyper3D API v2 (server-side only).

  POST https://api.hyper3d.com/api/v2/rodin     multipart images + tier
  POST https://api.hyper3d.com/api/v2/status    {subscription_key}
  POST https://api.hyper3d.com/api/v2/download  {task_uuid}

Authorization: Bearer $RODIN_API_KEY (or HYPER3D_API_KEY).
Concurrent on Business = 1. Do not send the key to the browser.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from studio_bridge.hitem_client import _multipart, fetch_image

API_BASE = "https://api.hyper3d.com/api/v2"
DEFAULT_TIMEOUT_SEC = 60


class RodinNotConfiguredError(RuntimeError):
    pass


class RodinHttpError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"Rodin HTTP {status}: {body[:300]}")


@dataclass(frozen=True)
class RodinPreset:
    tier: str
    list_usd: float
    eta_sec: int
    label: str
    blurb: str
    quality_override: str = "500000"


RODIN_PRESETS: dict[str, RodinPreset] = {
    "rodin": RodinPreset(
        tier="Gen-2.5-High",
        list_usd=0.30,
        eta_sec=240,
        label="Rodin Gen-2.5 High",
        blurb="Органика / hero. 1 concurrent. PBR GLB.",
    ),
    "rodin_extreme": RodinPreset(
        tier="Gen-2.5-Extreme-High",
        list_usd=0.60,
        eta_sec=360,
        label="Rodin Extreme-High",
        blurb="Жирный тир Rodin. Дороже. 1 concurrent.",
        quality_override="1000000",
    ),
}


def api_key() -> str:
    key = (
        os.getenv("RODIN_API_KEY", "").strip()
        or os.getenv("HYPER3D_API_KEY", "").strip()
    )
    if not key:
        raise RodinNotConfiguredError("RODIN_API_KEY is not set")
    return key


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: bytes | None = None,
    timeout: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            status = getattr(resp, "status", 200)
    except HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise RodinHttpError(exc.code, err) from exc
    except URLError as exc:
        raise RodinHttpError(502, str(exc.reason or exc)) from exc
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RodinHttpError(status, f"expected object, got {type(parsed).__name__}")
    if parsed.get("error"):
        raise RodinHttpError(status, str(parsed.get("error"))[:300])
    return parsed


def submit_image_to_3d(
    engine_id: str,
    *,
    image_urls: list[str],
    view_slots: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    preset = RODIN_PRESETS.get(engine_id)
    if preset is None:
        raise ValueError(f"{engine_id} is not a Rodin engine")
    urls = list(image_urls)
    if view_slots:
        ordered = [
            (view_slots.get(k) or "").strip()
            for k in ("front", "side", "back", "extra")
        ]
        urls = [u for u in ordered if u] or urls
    if not urls:
        raise ValueError("image URL required")
    files: list[tuple[str, str, bytes, str]] = []
    for i, url in enumerate(urls[:5]):
        name, payload, mime = fetch_image(url)
        files.append(("images", f"{i}_{name}", payload, mime))
    fields = {
        "tier": preset.tier,
        "mesh_mode": "Raw",
        "quality_override": preset.quality_override,
        "material": "PBR",
        "geometry_file_format": "glb",
    }
    body, content_type = _multipart(fields, files)
    parsed = _request(
        "POST",
        f"{API_BASE}/rodin",
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": content_type,
            "Accept": "application/json",
        },
        body=body,
        timeout=120,
    )
    task_uuid = str(parsed.get("uuid") or "").strip()
    jobs = parsed.get("jobs")
    sub = ""
    if isinstance(jobs, dict):
        sub = str(jobs.get("subscription_key") or "").strip()
    elif isinstance(jobs, list) and jobs and isinstance(jobs[0], dict):
        sub = str(jobs[0].get("subscription_key") or "").strip()
    if not task_uuid or not sub:
        raise RodinHttpError(502, f"rodin submit missing uuid/subscription_key: {list(parsed)}")
    return {"uuid": task_uuid, "subscription_key": sub, "tier": preset.tier}


def query_status(subscription_key: str) -> dict[str, Any]:
    payload = json.dumps({"subscription_key": subscription_key}).encode("utf-8")
    return _request(
        "POST",
        f"{API_BASE}/status",
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        body=payload,
    )


def download_urls(task_uuid: str) -> list[dict[str, Any]]:
    payload = json.dumps({"task_uuid": task_uuid}).encode("utf-8")
    parsed = _request(
        "POST",
        f"{API_BASE}/download",
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        body=payload,
    )
    items = parsed.get("list")
    return items if isinstance(items, list) else []


def pick_glb(items: list[dict[str, Any]]) -> str | None:
    fallback = None
    for node in items:
        if not isinstance(node, dict):
            continue
        url = str(node.get("url") or "")
        name = str(node.get("name") or "")
        if not url.startswith("https://"):
            continue
        if url.lower().endswith(".glb") or name.lower().endswith(".glb"):
            return url
        if fallback is None:
            fallback = url
    return fallback


def map_rodin_jobs(status_body: dict[str, Any]) -> str:
    jobs = status_body.get("jobs")
    rows = jobs if isinstance(jobs, list) else []
    if not rows:
        return "queued"
    states = [str(j.get("status") or "") for j in rows if isinstance(j, dict)]
    if any(s == "Failed" for s in states):
        return "failed"
    if states and all(s == "Done" for s in states):
        return "ready"
    if any(s == "Generating" for s in states):
        return "running"
    return "queued"


def is_configured() -> bool:
    return bool(
        os.getenv("RODIN_API_KEY", "").strip()
        or os.getenv("HYPER3D_API_KEY", "").strip()
    )
