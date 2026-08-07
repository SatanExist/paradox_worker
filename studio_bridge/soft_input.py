"""Soft-norm input preprocess for mid-prop holes gate (G1d).

Lifts dark grooves / deep shadows toward local neighborhood color so TRELLIS.2
does not read plank slits as see-through holes. Large intentional openings
(lattice cells) are mostly unchanged — soft targets thin dark lines.

Product: job_input soft_input=true (+ soft_input_strength, default 0.75).
"""

from __future__ import annotations

from typing import Union

import numpy as np
from PIL import Image, ImageFilter

ImageLike = Union[Image.Image, np.ndarray]

DEFAULT_SOFT_STRENGTH = 0.75


def soften(
    im: ImageLike,
    *,
    strength: float = DEFAULT_SOFT_STRENGTH,
    blur_radius: float = 2.5,
    mask_blur: float = 1.2,
    dark_scale: float = 40.0,
) -> Image.Image:
    """Lift dark grooves toward local neighborhood color (wood-like fill)."""
    if not isinstance(im, Image.Image):
        im = Image.fromarray(np.asarray(im))
    strength = float(np.clip(strength, 0.0, 1.0))
    if strength <= 0.0:
        return im.convert("RGB")

    rgb = np.asarray(im.convert("RGB"), dtype=np.float32)
    gray = rgb.mean(axis=2)
    blurred = np.asarray(
        Image.fromarray(gray.astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(radius=blur_radius)
        ),
        dtype=np.float32,
    )
    dark = blurred - gray
    mask = np.clip(dark / float(dark_scale), 0.0, 1.0)
    mask_img = Image.fromarray((mask * 255).astype(np.uint8))
    mask = (
        np.asarray(
            mask_img.filter(ImageFilter.GaussianBlur(radius=mask_blur)),
            dtype=np.float32,
        )
        / 255.0
    )
    mask = mask[..., None] * strength

    blur_rgb = np.stack(
        [
            np.asarray(
                Image.fromarray(rgb[:, :, c].astype(np.uint8)).filter(
                    ImageFilter.GaussianBlur(radius=blur_radius)
                ),
                dtype=np.float32,
            )
            for c in range(3)
        ],
        axis=2,
    )
    out = rgb * (1.0 - mask) + blur_rgb * mask
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def soften_images(
    images: list,
    *,
    strength: float = DEFAULT_SOFT_STRENGTH,
) -> list:
    """Apply soften to a list of PIL images; returns new list."""
    return [soften(img, strength=strength) for img in images]
