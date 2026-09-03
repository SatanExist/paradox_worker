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
    # P2-20260801 only — native quad mesh (API docs).
    quad: bool = False


TRIPO_PRESETS: dict[str, TripoPreset] = {
    "tripo": TripoPreset(
        model="v3.1-20260211",
        list_usd=0.30,
        eta_sec=180,
        label="Tripo H3.1",
        blurb="Fast image→3D (H-series). PBR. Not the default.",
        texture_quality="standard",
    ),
    "tripo_p1": TripoPreset(
        model="P1-20260311",
        list_usd=0.50,
        eta_sec=240,
        label="Tripo P1",
        blurb="P-series low-poly / game mesh. Do not confuse with H3.1.",
        texture_quality="detailed",
    ),
    "tripo_p2": TripoPreset(
        model="P2-20260801",
        list_usd=0.70,
        eta_sec=150,
        label="Tripo P2",
        blurb="P2 Preview — game-ready mesh with native quad topology.",
        texture_quality="detailed",
        quad=True,
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
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    preset = TRIPO_PRESETS.get(engine_id)
    if preset is None:
        raise ValueError(f"{engine_id} is not a Tripo engine")
    if not image_urls:
        raise ValueError("image URL required")

    opts = options or {}
    material = str(opts.get("material") or "PBR").strip()
    if material not in {"PBR", "Shaded", "None"}:
        material = "PBR"
    texture = material != "None"
    pbr = material == "PBR"

    topology = str(opts.get("topology") or ("quads" if preset.quad else "triangles")).strip().lower()
    use_quad = preset.quad and topology in {"quads", "quad", "true", "1"}

    tq = str(
        opts.get("textureQuality") or opts.get("texture_quality") or preset.texture_quality
    ).strip().lower()
    if tq not in {"standard", "detailed"}:
        tq = preset.texture_quality

    body: dict[str, Any] = {
        "input": image_urls[0],
        "model": preset.model,
        "texture": texture,
        "pbr": pbr if texture else False,
        "texture_quality": tq,
        "model_seed": int(seed),
    }

    raw_seed = opts.get("seed")
    if raw_seed is not None and str(raw_seed).strip() != "":
        try:
            body["model_seed"] = int(str(raw_seed).strip())
        except ValueError as exc:
            raise ValueError(f"invalid Tripo seed {raw_seed!r}") from exc

    if preset.quad:
        body["quad"] = bool(use_quad)

    face_limits_by_engine: dict[str, dict[str, tuple[int, int] | int]] = {
        "tripo_p2": {
            "low": (5_000, 8_000),
            "medium": (12_000, 20_000),
            "high": (25_000, 50_000),
        },
        "tripo_p1": {
            "low": 5_000,
            "medium": 12_000,
            "high": 20_000,
        },
        "tripo": {
            "low": 50_000,
            "medium": 100_000,
            "high": 500_000,
        },
    }
    face_limits = face_limits_by_engine.get(engine_id, face_limits_by_engine["tripo_p2"])

    face_preset = str(opts.get("facePreset") or opts.get("face_preset") or "auto").strip().lower()
    if face_preset in face_limits:
        limit = face_limits[face_preset]
        if isinstance(limit, tuple):
            quad_n, tri_n = limit
            body["face_limit"] = quad_n if body.get("quad") else tri_n
        else:
            body["face_limit"] = int(limit)
    override = opts.get("faceLimit") or opts.get("face_limit")
    if override is not None and str(override).strip():
        try:
            body["face_limit"] = int(str(override).strip())
        except ValueError as exc:
            raise ValueError(f"invalid face_limit {override!r}") from exc

    align = str(
        opts.get("textureAlign") or opts.get("texture_alignment") or "original_image"
    ).strip()
    if align in {"original_image", "geometry"}:
        body["texture_alignment"] = align

    orient = str(opts.get("orientation") or "default").strip()
    if orient in {"default", "align_image"}:
        body["orientation"] = orient

    if bool(opts.get("autofix") if "autofix" in opts else opts.get("enable_image_autofix")):
        body["enable_image_autofix"] = True

    if engine_id == "tripo":
        gq = str(
            opts.get("geometryQuality") or opts.get("geometry_quality") or "standard"
        ).strip().lower()
        if gq in {"standard", "detailed"}:
            body["geometry_quality"] = gq
        if bool(opts.get("smartLowPoly") or opts.get("smart_low_poly")):
            body["smart_low_poly"] = True

    data = _unwrap(
        _request("POST", f"{API_BASE}/generation/image-to-model", payload=body),
        "image-to-model",
    )
    task_id = str(data.get("task_id") or "").strip()
    if not task_id:
        raise TripoHttpError(502, f"missing task_id: {data}")
    return {"task_id": task_id, "model": preset.model, "options": body}


def query_task(task_id: str) -> dict[str, Any]:
    tid = quote((task_id or "").strip(), safe="")
    if not tid:
        raise ValueError("task_id required")
    return _unwrap(_request("GET", f"{API_BASE}/tasks/{tid}"), "task")


def query_balance() -> dict[str, Any]:
    return _unwrap(_request("GET", f"{API_BASE}/account/balance"), "balance")


def pick_glb(task: dict[str, Any]) -> tuple[str | None, str | None]:
    """Pick a downloadable model URL + poster.

    Prefers GLB; falls back to FBX if P2 quad (or convert) returns FBX only.
    """
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
    fbx = None
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
        lower = url.lower()
        if lower.endswith(".fbx"):
            fbx = fbx or url
            continue
        glb = url
        if lower.endswith(".glb") or key in {"pbr_model", "model_url"}:
            break
    return glb or fbx, poster


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
