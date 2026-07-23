"""Texture v1 RunPod input helpers (mesh paint).

Separate from generate tiers — dedicated endpoint when configured.
"""

from __future__ import annotations

import os
from typing import Any


def texture_endpoint_id() -> str | None:
    endpoint = os.getenv("RUNPOD_ENDPOINT_ID_TEXTURE", "").strip()
    return endpoint or None


def build_texture_input(
    *,
    mesh_url: str,
    image_url: str,
    seed: int = 1,
    resolution: int = 1024,
    texture_size: int = 2048,
    return_base64: bool = False,
    preprocess_image: bool = True,
) -> dict[str, Any]:
    """Contract for worker_texture.py / Trellis2TexturingPipeline."""
    payload: dict[str, Any] = {
        "mesh_url": mesh_url,
        "image_url": image_url,
        "seed": seed,
        "resolution": resolution,
        "texture_size": texture_size,
        "return_base64": return_base64,
        "preprocess_image": preprocess_image,
    }
    return payload
