#!/usr/bin/env python3
"""MV2: Wonder3D 1 image → 6 RGB (+ optional normals grid).

Run on a CUDA pod. Saves individual views + overview grid.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch
from PIL import Image
from torchvision.utils import make_grid, save_image


def load_pipeline(device: str):
    from diffusers import DiffusionPipeline

    pipe = DiffusionPipeline.from_pretrained(
        "flamehaze1115/wonder3d-v1.0",
        custom_pipeline="flamehaze1115/wonder3d-pipeline",
        torch_dtype=torch.float16,
    )
    try:
        pipe.unet.enable_xformers_memory_efficient_attention()
        print("xformers: on")
    except Exception as exc:
        print(f"xformers: skip ({exc})")
    pipe.to(device)
    return pipe


def prepare_image(path: Path) -> Image.Image:
    img = Image.open(path).convert("RGB")
    # Wonder3D expects object roughly centered; keep RGB only.
    return img


def save_views(images: torch.Tensor, out_dir: Path, stem: str) -> None:
    """images: (N, C, H, W) in [0,1] — Wonder3D returns 12 tiles (6 RGB + 6 normal) or 6."""
    out_dir.mkdir(parents=True, exist_ok=True)
    n = images.shape[0]
    print(f"pipeline returned {n} tiles shape={tuple(images.shape)}")

    # Official demo: make_grid nrow=6 → typically 12 images (2 rows: color + normal).
    grid = make_grid(images, nrow=min(6, n), padding=0, value_range=(0, 1))
    save_image(grid, out_dir / f"{stem}_grid.png")

    # First 6 = RGB views (azimuth order per README); next 6 = normals if present.
    rgb_n = min(6, n)
    for i in range(rgb_n):
        save_image(images[i], out_dir / f"{stem}_rgb_{i:02d}.png")
    if n > 6:
        for i in range(6, min(12, n)):
            save_image(images[i], out_dir / f"{stem}_normal_{i - 6:02d}.png")
    print(f"saved under {out_dir}")


def main() -> int:
    p = argparse.ArgumentParser(description="Wonder3D MV2 multi-view infer")
    p.add_argument("--image", required=True, type=Path)
    p.add_argument("--out-dir", type=Path, default=Path("./mv2_out"))
    p.add_argument("--stem", default="")
    p.add_argument("--steps", type=int, default=20)
    p.add_argument("--guidance", type=float, default=1.0)
    p.add_argument("--device", default="cuda:0")
    args = p.parse_args()

    if not args.image.is_file():
        print(f"missing image: {args.image}", file=sys.stderr)
        return 1
    if not torch.cuda.is_available():
        print("CUDA required", file=sys.stderr)
        return 1

    stem = args.stem or args.image.stem
    print(f"loading Wonder3D pipeline on {args.device}…")
    pipe = load_pipeline(args.device)
    cond = prepare_image(args.image)
    print(f"infer {args.image} size={cond.size} steps={args.steps}")
    with torch.inference_mode():
        out = pipe(
            cond,
            num_inference_steps=args.steps,
            output_type="pt",
            guidance_scale=args.guidance,
        )
    images = out.images
    if not isinstance(images, torch.Tensor):
        # list of PIL → stack
        from torchvision import transforms

        to_t = transforms.ToTensor()
        images = torch.stack([to_t(im) for im in images], dim=0)
    save_views(images.float().cpu(), args.out_dir, stem)
    print("DONE", stem)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
