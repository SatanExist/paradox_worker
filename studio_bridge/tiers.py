from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

TierName = Literal["preview", "quality"]
TextureMode = Literal["clay", "textured"]


@dataclass(frozen=True)
class TierConfig:
    name: TierName
    endpoint_id: str
    pipeline_type: str
    texture_size: int
    decimation_target: int
    eta_cold_sec: int
    eta_warm_sec: int
    texture_mode: TextureMode = "clay"


def _endpoint_t2() -> str:
    endpoint = os.getenv("RUNPOD_ENDPOINT_ID_TRELLIS2", "").strip()
    if not endpoint:
        raise ValueError("RUNPOD_ENDPOINT_ID_TRELLIS2 is not set")
    return endpoint


TIER_PREVIEW = TierConfig(
    name="preview",
    endpoint_id="",  # resolved at runtime
    pipeline_type="512",
    texture_size=1024,
    decimation_target=500_000,
    eta_cold_sec=360,
    eta_warm_sec=45,
)

TIER_QUALITY = TierConfig(
    name="quality",
    endpoint_id="",
    pipeline_type="1024_cascade",
    texture_size=2048,
    decimation_target=500_000,
    eta_cold_sec=480,
    eta_warm_sec=240,
)

_TIERS: dict[TierName, TierConfig] = {
    "preview": TIER_PREVIEW,
    "quality": TIER_QUALITY,
}


def get_tier(name: TierName) -> TierConfig:
    base = _TIERS[name]
    return TierConfig(
        name=base.name,
        endpoint_id=_endpoint_t2(),
        pipeline_type=base.pipeline_type,
        texture_size=base.texture_size,
        decimation_target=base.decimation_target,
        eta_cold_sec=base.eta_cold_sec,
        eta_warm_sec=base.eta_warm_sec,
        texture_mode=base.texture_mode,
    )


def build_runpod_input(
    tier: TierConfig,
    *,
    image_url: str,
    seed: int = 1,
    texture_mode: TextureMode | None = None,
) -> dict:
    mode = texture_mode or tier.texture_mode
    payload: dict = {
        "image_url": image_url,
        "pipeline_type": tier.pipeline_type,
        "texture_mode": mode,
        "seed": seed,
        "decimation_target": tier.decimation_target,
        "return_base64": False,
    }
    if mode == "textured":
        payload["texture_size"] = tier.texture_size
    return payload
