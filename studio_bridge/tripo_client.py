"""Tripo Developers API v3 (server-side only).

  POST https://openapi.tripo3d.ai/v3/generation/image-to-model
  GET  https://openapi.tripo3d.ai/v3/tasks/{task_id}
  Authorization: Bearer $TRIPO_API_KEY

Not the consumer Studio wallet. Do not send the key to the browser.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

API_BASE = "https://openapi.tripo3d.ai/v3"
DEFAULT_TIMEOUT_SEC = 60


class TripoNotConfiguredError(RuntimeError):
    pass


class TripoHttpError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"Tripo HTTP {status}: {body[:300]}")


@dataclass(frozen=True)
class TripoPreset:
    model: str
    list_usd: float
    eta_sec: int
    label: str
    blurb: str
    texture_quality: str = "standard"


TRIPO_PRESETS: dict[str, TripoPreset] = {
    "tripo": TripoPreset(
        model="v3.1-20260211",
        list_usd=0.30,
        eta_sec=180,
        label="Tripo H3.1",
        blurb="Быстрый чужой image→3D. PBR. Не default.",
        texture_quality="standard",
    ),
    "tripo_p1": TripoPreset(
        model="P1-20260311",
        list_usd=0.50,
        eta_sec=240,
        label="Tripo P1",
        blurb="Выше качество Tripo (P1). Не путать с H3.1.",
        texture_quality="detailed",
    ),
}


def api_key() -> str:
    key = os.getenv("TRIPO_API_KEY", "").strip()
    if not key:
        raise TripoNotConfiguredError("TRIPO_API_KEY is not set")
    return key


def _ok_code(code: Any) -> bool:
    return code in (0, "0", 200, "200")


def _request(method: str, url: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key()}",
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=DEFAULT_TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8")
            status = getattr(resp, "status", 200)
    except HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise TripoHttpError(exc.code, err) from exc
    except URLError as exc:
        raise TripoHttpError(502, str(exc.reason or exc)) from exc
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise TripoHttpError(status, f"expected object, got {type(parsed).__name__}")
    return parsed


def _unwrap(body: dict[str, Any], context: str) -> dict[str, Any]:
    if not _ok_code(body.get("code")):
        msg = str(body.get("message") or body.get("msg") or body)[:300]
        raise TripoHttpError(502, f"{context}: {msg}")
    data = body.get("data")
    if not isinstance(data, dict):
        raise TripoHttpError(502, f"{context}: missing data")
    return data


def submit_image_to_3d(
    engine_id: str,
    *,
    image_urls: list[str],
    seed: int = 1,
) -> dict[str, Any]:
    preset = TRIPO_PRESETS.get(engine_id)
    if preset is None:
        raise ValueError(f"{engine_id} is not a Tripo engine")
    if not image_urls:
        raise ValueError("image URL required")
    body = {
        "input": image_urls[0],
        "model": preset.model,
        "texture": True,
        "pbr": True,
        "texture_quality": preset.texture_quality,
        "model_seed": int(seed),
    }
    data = _unwrap(
        _request("POST", f"{API_BASE}/generation/image-to-model", payload=body),
        "image-to-model",
    )
    task_id = str(data.get("task_id") or "").strip()
    if not task_id:
        raise TripoHttpError(502, f"missing task_id: {data}")
    return {"task_id": task_id, "model": preset.model}


def query_task(task_id: str) -> dict[str, Any]:
    tid = quote((task_id or "").strip(), safe="")
    if not tid:
        raise ValueError("task_id required")
    return _unwrap(_request("GET", f"{API_BASE}/tasks/{tid}"), "task")


def query_balance() -> dict[str, Any]:
    return _unwrap(_request("GET", f"{API_BASE}/account/balance"), "balance")


def pick_glb(task: dict[str, Any]) -> tuple[str | None, str | None]:
    output = task.get("output") if isinstance(task.get("output"), dict) else {}
    poster = None
    for key in ("rendered_image_url", "rendered_image", "preview"):
        val = output.get(key)
        if isinstance(val, str) and val.startswith("https://"):
            poster = val
            break
        if isinstance(val, dict):
            url = val.get("url")
            if isinstance(url, str) and url.startswith("https://"):
                poster = url
                break
    glb = None
    for key in ("pbr_model", "model_url", "model", "base_model"):
        val = output.get(key)
        url = None
        if isinstance(val, str):
            url = val
        elif isinstance(val, dict):
            maybe = val.get("url")
            if isinstance(maybe, str):
                url = maybe
        if not url or not url.startswith("https://"):
            continue
        glb = url
        if url.lower().endswith(".glb") or key in {"pbr_model", "model_url"}:
            break
    return glb, poster


def map_tripo_status(raw: str | None) -> str:
    status = (raw or "").strip().lower()
    if status in {"queued", "pending", "waiting"}:
        return "queued"
    if status in {"running", "processing", "in_progress"}:
        return "running"
    if status == "success":
        return "ready"
    return "failed"


def is_configured() -> bool:
    return bool(os.getenv("TRIPO_API_KEY", "").strip())
