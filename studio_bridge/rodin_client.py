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
DEFAULT_RODIN_QUALITY = "medium"
RODIN_ENGINE_IDS = frozenset({"rodin", "rodin_extreme"})
RODIN_MATERIALS = frozenset({"PBR", "Shaded", "None"})
RODIN_TEXTURE_MODES = frozenset(
    {"legacy", "extreme-low", "low", "medium", "high"}
)
RODIN_GEOMETRY_MODES = frozenset({"faithful", "creative"})
RODIN_MESH_MODES = frozenset({"Raw", "Quad"})
RODIN_FACE_PRESETS = frozenset({"auto", "extra-low", "low", "medium", "high"})
RODIN_FACE_OVERRIDE = {
    "extra-low": "20000",
    "low": "60000",
    "medium": "500000",
    "high": "1000000",
}
CREATIVE_TIERS = frozenset({"medium", "high", "ultra"})


class RodinNotConfiguredError(RuntimeError):
    pass


class RodinHttpError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"Rodin HTTP {status}: {body[:300]}")


@dataclass(frozen=True)
class RodinQualityTier:
    id: str
    api_tier: str
    quality_override: str
    list_usd: float
    eta_sec: int
    label: str


RODIN_QUALITY_TIERS: dict[str, RodinQualityTier] = {
    "lowest": RodinQualityTier(
        "lowest",
        "Gen-2.5-Extreme-Low",
        "20000",
        0.15,
        120,
        "Lowest",
    ),
    "low": RodinQualityTier(
        "low",
        "Gen-2.5-Low",
        "60000",
        0.20,
        150,
        "Low",
    ),
    "medium": RodinQualityTier(
        "medium",
        "Gen-2.5-Medium",
        "500000",
        0.25,
        210,
        "Medium",
    ),
    "high": RodinQualityTier(
        "high",
        "Gen-2.5-High",
        "500000",
        0.30,
        240,
        "High",
    ),
    "ultra": RodinQualityTier(
        "ultra",
        "Gen-2.5-Extreme-High",
        "1000000",
        0.60,
        360,
        "Ultra",
    ),
}


@dataclass(frozen=True)
class RodinEngineMeta:
    label: str
    blurb: str
    eta_sec: int


RODIN_ENGINE = RodinEngineMeta(
    label="Rodin 2.5",
    blurb="Hyper3D Gen-2.5 — hard-surface, PBR GLB, 1–5 photos. Quality tier in params.",
    eta_sec=RODIN_QUALITY_TIERS[DEFAULT_RODIN_QUALITY].eta_sec,
)


def resolve_rodin_quality(engine_id: str, quality_tier: str | None) -> RodinQualityTier:
    if engine_id == "rodin_extreme":
        return RODIN_QUALITY_TIERS["ultra"]
    q = (quality_tier or DEFAULT_RODIN_QUALITY).strip().lower()
    tier = RODIN_QUALITY_TIERS.get(q)
    if tier is None:
        raise ValueError(f"unknown Rodin quality tier {quality_tier!r}")
    return tier


def is_rodin_engine(engine_id: str) -> bool:
    return engine_id in RODIN_ENGINE_IDS


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


def _norm_choice(raw: str | None, allowed: frozenset[str], *, label: str, default: str) -> str:
    if raw is None or not str(raw).strip():
        return default
    value = str(raw).strip()
    if value in allowed:
        return value
    lowered = {a.lower(): a for a in allowed}
    hit = lowered.get(value.lower())
    if hit is not None:
        return hit
    raise ValueError(f"unknown Rodin {label} {raw!r}")


def resolve_rodin_options(
    quality_tier_id: str,
    options: dict[str, Any] | None,
) -> dict[str, Any]:
    """Normalize Studio / API knobs for multipart submit."""
    opts = options or {}
    material = _norm_choice(
        opts.get("material"), RODIN_MATERIALS, label="material", default="PBR"
    )

    raw_tex = opts.get("textureMode")
    if raw_tex is None:
        raw_tex = opts.get("texture_mode")
    texture_mode: str | None = None
    if raw_tex is not None and str(raw_tex).strip():
        texture_mode = _norm_choice(
            str(raw_tex),
            RODIN_TEXTURE_MODES,
            label="texture_mode",
            default="medium",
        )

    geometry_mode = _norm_choice(
        opts.get("geometryMode") or opts.get("geometry_instruct_mode"),
        RODIN_GEOMETRY_MODES,
        label="geometry_instruct_mode",
        default="faithful",
    )
    if geometry_mode == "creative" and quality_tier_id not in CREATIVE_TIERS:
        raise ValueError("Rodin Creative geometry requires Medium, High, or Ultra tier")

    mesh_mode = _norm_choice(
        opts.get("meshMode") or opts.get("mesh_mode"),
        RODIN_MESH_MODES,
        label="mesh_mode",
        default="Raw",
    )

    face_raw = opts.get("facePreset") or opts.get("face_preset") or "auto"
    face_preset = _norm_choice(
        str(face_raw), RODIN_FACE_PRESETS, label="face_preset", default="auto"
    )
    override = opts.get("qualityOverride") or opts.get("quality_override")
    if override is not None and str(override).strip():
        quality_override = str(override).strip()
    elif face_preset != "auto":
        quality_override = RODIN_FACE_OVERRIDE[face_preset]
    else:
        quality_override = None

    high_pack = bool(
        opts.get("highPack") if "highPack" in opts else opts.get("high_pack", False)
    )
    hd_texture = bool(
        opts.get("hdTexture") if "hdTexture" in opts else opts.get("hd_texture", False)
    )

    seed_val: int | None = None
    raw_seed = opts.get("seed")
    if raw_seed is not None and str(raw_seed).strip() != "":
        try:
            seed_val = int(str(raw_seed).strip())
        except ValueError as exc:
            raise ValueError(f"invalid Rodin seed {raw_seed!r}") from exc
        if seed_val < 0 or seed_val > 65535:
            raise ValueError("Rodin seed must be 0–65535")

    return {
        "material": material,
        "texture_mode": texture_mode,
        "geometry_instruct_mode": geometry_mode,
        "mesh_mode": mesh_mode,
        "face_preset": face_preset,
        "quality_override": quality_override,
        "high_pack": high_pack,
        "hd_texture": hd_texture,
        "seed": seed_val,
    }


def submit_image_to_3d(
    engine_id: str,
    *,
    image_urls: list[str],
    view_slots: dict[str, str | None] | None = None,
    quality_tier: str | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not is_rodin_engine(engine_id):
        raise ValueError(f"{engine_id} is not a Rodin engine")
    tier = resolve_rodin_quality(engine_id, quality_tier)
    knobs = resolve_rodin_options(tier.id, options)
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
    quality_override = knobs["quality_override"] or tier.quality_override
    fields: dict[str, str] = {
        "tier": tier.api_tier,
        "mesh_mode": knobs["mesh_mode"],
        "quality_override": str(quality_override),
        "material": knobs["material"],
        "geometry_file_format": "glb",
        "geometry_instruct_mode": knobs["geometry_instruct_mode"],
        "hd_texture": "true" if knobs["hd_texture"] else "false",
    }
    if knobs["texture_mode"]:
        fields["texture_mode"] = knobs["texture_mode"]
    if knobs["high_pack"]:
        fields["addons"] = "HighPack"
    if knobs["seed"] is not None:
        fields["seed"] = str(knobs["seed"])
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
    return {
        "uuid": task_uuid,
        "subscription_key": sub,
        "tier": tier.api_tier,
        "qualityTier": tier.id,
        "options": knobs,
    }


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
