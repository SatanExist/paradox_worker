"""Studio quality presets → TRELLIS.2 RunPod job input.

Canonical UI: low / medium / high / realistic (Meshy-style ladder).
Legacy aliases: preview→low, quality→medium, ultra→high.

All presets use official T2 native PBR (texture_mode=textured). Clay is an
opt-in override for debug, not the product default. High/Realistic also set
material_polish (CPU delight+bump after bake).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

# Worker quality_tier (rt6 lives on "ultra")
WorkerTier = Literal["preview", "quality", "ultra"]
CanonicalPreset = Literal["low", "medium", "high", "realistic"]
TierName = Literal[
    "low",
    "medium",
    "high",
    "realistic",
    "preview",
    "quality",
    "ultra",
]
TextureMode = Literal["clay", "textured"]
MultiImageMode = Literal["stochastic", "multidiffusion"]

DEFAULT_MULTI_IMAGE_MODE: MultiImageMode = "stochastic"
DEFAULT_PRESET: CanonicalPreset = "medium"
MIN_MULTI_IMAGES = 2
MAX_MULTI_IMAGES = 4

LEGACY_ALIASES: dict[str, CanonicalPreset] = {
    "preview": "low",
    "quality": "medium",
    "ultra": "high",
}


@dataclass(frozen=True)
class TierConfig:
    name: CanonicalPreset
    endpoint_id: str
    quality_tier: WorkerTier
    pipeline_type: str
    texture_size: int
    decimation_target: int
    eta_cold_sec: int
    eta_warm_sec: int
    texture_mode: TextureMode = "textured"
    remesh: bool = True
    soft_input_default: bool = False
    max_hole_perimeter: float | None = None
    material_polish: bool = False
    label: str = ""
    blurb: str = ""


def _endpoint_t2() -> str:
    endpoint = os.getenv("RUNPOD_ENDPOINT_ID_TRELLIS2", "").strip()
    if not endpoint:
        raise ValueError("RUNPOD_ENDPOINT_ID_TRELLIS2 is not set")
    return endpoint


# Product copy: honest T2, not Meshy Solid.
_PRESET_SPECS: dict[CanonicalPreset, dict] = {
    "low": {
        "quality_tier": "preview",
        "pipeline_type": "512",
        "texture_size": 1024,
        "decimation_target": 300_000,
        "eta_cold_sec": 360,
        "eta_warm_sec": 45,
        "soft_input_default": False,
        "max_hole_perimeter": None,
        "material_polish": False,
        "label": "Low",
        "blurb": "Быстрый превью: силуэт и цвет. Не для крупного плана.",
    },
    "medium": {
        "quality_tier": "quality",
        "pipeline_type": "1024_cascade",
        "texture_size": 2048,
        "decimation_target": 500_000,
        "eta_cold_sec": 480,
        "eta_warm_sec": 240,
        "soft_input_default": True,
        "max_hole_perimeter": 0.1,
        "material_polish": False,
        "label": "Medium",
        "blurb": "Стандарт для предметов. Перед ближе к фото; бок и зад — догадка модели.",
    },
    "high": {
        "quality_tier": "ultra",
        "pipeline_type": "1536_cascade",
        "texture_size": 2048,
        "decimation_target": 700_000,
        "eta_cold_sec": 600,
        "eta_warm_sec": 300,
        "soft_input_default": False,
        "max_hole_perimeter": None,
        "material_polish": True,
        "label": "High",
        "blurb": "Лучший фронт персонажа / сложного объекта. Дольше и дороже.",
    },
    "realistic": {
        "quality_tier": "ultra",
        "pipeline_type": "1536_cascade",
        "texture_size": 4096,
        "decimation_target": 700_000,
        "eta_cold_sec": 720,
        "eta_warm_sec": 360,
        "soft_input_default": False,
        "max_hole_perimeter": None,
        "material_polish": True,
        "label": "Realistic",
        "blurb": "Максимум TRELLIS.2: нативный PBR 4K. Не Meshy-герой и не гарантия зада с 1 фото.",
    },
}


def resolve_preset_id(name: str) -> CanonicalPreset:
    key = (name or "").strip().lower()
    if key in LEGACY_ALIASES:
        return LEGACY_ALIASES[key]
    if key in _PRESET_SPECS:
        return key  # type: ignore[return-value]
    allowed = "low, medium, high, realistic (aliases: preview, quality, ultra)"
    raise ValueError(f"unknown quality preset {name!r}; expected {allowed}")


def preset_tier(name: str, *, endpoint_id: str = "") -> TierConfig:
    """Build a preset without requiring RunPod env (tests / dry-run)."""
    preset = resolve_preset_id(str(name))
    spec = _PRESET_SPECS[preset]
    return TierConfig(
        name=preset,
        endpoint_id=endpoint_id,
        quality_tier=spec["quality_tier"],
        pipeline_type=spec["pipeline_type"],
        texture_size=spec["texture_size"],
        decimation_target=spec["decimation_target"],
        eta_cold_sec=spec["eta_cold_sec"],
        eta_warm_sec=spec["eta_warm_sec"],
        texture_mode="textured",
        remesh=True,
        soft_input_default=bool(spec["soft_input_default"]),
        max_hole_perimeter=spec["max_hole_perimeter"],
        material_polish=bool(spec["material_polish"]),
        label=str(spec["label"]),
        blurb=str(spec["blurb"]),
    )


def get_tier(name: TierName | str) -> TierConfig:
    return preset_tier(str(name), endpoint_id=_endpoint_t2())


def quality_preset_catalog() -> list[dict]:
    """JSON for Studio selector. No GPU."""
    out: list[dict] = []
    for preset_id in ("low", "medium", "high", "realistic"):
        spec = _PRESET_SPECS[preset_id]  # type: ignore[index]
        aliases = [k for k, v in LEGACY_ALIASES.items() if v == preset_id]
        out.append(
            {
                "id": preset_id,
                "label": spec["label"],
                "blurb": spec["blurb"],
                "default": preset_id == DEFAULT_PRESET,
                "legacyAliases": aliases,
                "workerQualityTier": spec["quality_tier"],
                "pipelineType": spec["pipeline_type"],
                "textureMode": "textured",
                "textureSize": spec["texture_size"],
                "softInputDefault": spec["soft_input_default"],
                "materialPolish": spec["material_polish"],
                "etaSecondsCold": spec["eta_cold_sec"],
                "etaSecondsWarm": spec["eta_warm_sec"],
            }
        )
    return out


def build_runpod_input(
    tier: TierConfig,
    *,
    image_url: str | None = None,
    image_urls: list[str] | None = None,
    seed: int = 1,
    texture_mode: TextureMode | None = None,
    soft_input: bool | None = None,
    soft_input_strength: float = 0.75,
    multi_image_mode: MultiImageMode = DEFAULT_MULTI_IMAGE_MODE,
) -> dict:
    """Build RunPod job input. Multi (2–4 URLs) sets image_urls + multi_image_mode."""
    urls = _normalize_image_urls(image_url=image_url, image_urls=image_urls)
    primary = urls[0]
    mode = texture_mode or tier.texture_mode
    use_soft = tier.soft_input_default if soft_input is None else bool(soft_input)
    payload: dict = {
        "image_url": primary,
        "quality_tier": tier.quality_tier,
        "pipeline_type": tier.pipeline_type,
        "texture_mode": mode,
        "seed": seed,
        "decimation_target": tier.decimation_target,
        "remesh": tier.remesh,
        "return_base64": False,
    }
    if len(urls) >= MIN_MULTI_IMAGES:
        payload["image_urls"] = urls
        payload["multi_image_mode"] = multi_image_mode
    if mode == "textured":
        payload["texture_size"] = tier.texture_size
    if tier.max_hole_perimeter is not None:
        payload["max_hole_perimeter"] = float(tier.max_hole_perimeter)
    if use_soft:
        payload["soft_input"] = True
        payload["soft_input_strength"] = float(soft_input_strength)
    if mode == "textured":
        payload["material_polish"] = bool(tier.material_polish)
    return payload


def _normalize_image_urls(
    *,
    image_url: str | None,
    image_urls: list[str] | None,
) -> list[str]:
    """Dedup preserving order. Prefer image_urls when provided."""
    raw: list[str] = []
    if image_urls:
        raw.extend(image_urls)
    elif image_url:
        raw.append(image_url)
    out: list[str] = []
    seen: set[str] = set()
    for u in raw:
        s = (u or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    if not out:
        raise ValueError("image_url or image_urls required")
    if len(out) > MAX_MULTI_IMAGES:
        raise ValueError(f"at most {MAX_MULTI_IMAGES} image URLs allowed")
    return out
