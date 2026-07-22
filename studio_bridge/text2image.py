from __future__ import annotations

import os
import urllib.request
from typing import Any


class Text2ImageNotConfiguredError(RuntimeError):
    """Raised when text mode is requested but no image provider is configured."""


def _openai_image_url(prompt: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise Text2ImageNotConfiguredError(
            "Set OPENAI_API_KEY for text→image, or use mode=image with imageUrl."
        )

    import json

    body = json.dumps(
        {
            "model": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
            "prompt": prompt,
            "size": os.getenv("OPENAI_IMAGE_SIZE", "1024x1024"),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload: dict[str, Any] = json.loads(resp.read().decode("utf-8"))

    data = payload.get("data") or []
    if not data:
        raise RuntimeError(f"OpenAI image response empty: {payload}")

    item = data[0]
    if isinstance(item.get("url"), str):
        return item["url"]

    b64 = item.get("b64_json")
    if not isinstance(b64, str) or not b64:
        raise RuntimeError(f"OpenAI image response missing url/b64_json: {payload}")

    # POC fallback: data URL for downstream download in service layer.
    return f"data:image/png;base64,{b64}"


def generate_image_url(prompt: str) -> str:
    provider = os.getenv("TEXT2IMAGE_PROVIDER", "openai").strip().lower()
    if provider in ("openai", "gpt", "dalle"):
        return _openai_image_url(prompt)
    if provider == "none":
        raise Text2ImageNotConfiguredError(
            "TEXT2IMAGE_PROVIDER=none. Use mode=image or configure OPENAI_API_KEY."
        )
    raise Text2ImageNotConfiguredError(f"Unsupported TEXT2IMAGE_PROVIDER={provider!r}")


def materialize_image_url(image_url: str) -> str:
    """Return a public http(s) URL. Upload data URLs to R2 later; for POC use as-is if http."""
    if image_url.startswith("http://") or image_url.startswith("https://"):
        return image_url
    if not image_url.startswith("data:image"):
        raise ValueError(f"Unsupported image URL scheme: {image_url[:32]}...")
    # RunPod worker needs a fetchable URL; data URLs won't work on GPU pod.
    raise RuntimeError(
        "Text2image returned inline image. Configure provider with public URL output "
        "or add R2 upload for intermediate images (TODO)."
    )
