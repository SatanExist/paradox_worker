"""Headless Hi3DGen: RGB → normal bridge → mesh GLB.

H0 spike only. Not TRELLIS.2. Run from the Stable3DGen repo root (weights/ relative).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("SPCONV_ALGO", "native")
os.environ.setdefault("PYTHONUNBUFFERED", "1")

import numpy as np
import torch
from PIL import Image


def patch_xformers_block_diagonal_mask() -> None:
    """Hi3DGen sparse attn imports BlockDiagonalMask from xops.fmha; newer xformers moved it."""
    import xformers.ops as xops

    if hasattr(xops.fmha, "BlockDiagonalMask"):
        return
    from xformers.ops.fmha.attn_bias import BlockDiagonalMask

    xops.fmha.BlockDiagonalMask = BlockDiagonalMask


patch_xformers_block_diagonal_mask()


def cache_weights(weights_dir: Path) -> None:
    from huggingface_hub import snapshot_download

    weights_dir.mkdir(parents=True, exist_ok=True)
    for model_id, folder in (
        ("Stable-X/trellis-normal-v0-1", "trellis-normal-v0-1"),
        ("Stable-X/yoso-normal-v1-8-1", "yoso-normal-v1-8-1"),
        ("ZhengPeng7/BiRefNet", "BiRefNet"),
    ):
        dest = weights_dir / folder
        if dest.exists() and any(dest.iterdir()):
            print(f"cached {model_id} -> {dest}", flush=True)
            continue
        print(f"download {model_id} -> {dest}", flush=True)
        snapshot_download(repo_id=model_id, local_dir=str(dest), force_download=False)


def link_repo_weights(repo: Path, volume_dir: Path) -> Path:
    """Put Stable3DGen weights/ on the network volume (HF cache lives across jobs)."""
    repo_weights = repo / "weights"
    repo_weights.mkdir(parents=True, exist_ok=True)
    cache_weights(volume_dir)
    for folder in ("trellis-normal-v0-1", "yoso-normal-v1-8-1", "BiRefNet"):
        src = (volume_dir / folder).resolve()
        dst = repo_weights / folder
        if dst.exists() or dst.is_symlink():
            continue
        os.symlink(str(src), str(dst), target_is_directory=True)
    return repo_weights


def load_normal_predictor(weights_dir: Path):
    hub_local = Path(torch.hub.get_dir()) / "hugoycj_StableNormal_main"
    kwargs = dict(
        yoso_version="yoso-normal-v1-8-1",
        local_cache_dir=str(weights_dir),
        pretrained=True,
    )
    try:
        return torch.hub.load(str(hub_local), "StableNormal_turbo", source="local", **kwargs)
    except Exception as exc:
        print(f"local StableNormal hub miss ({exc}); trust_repo download", flush=True)
        return torch.hub.load(
            "hugoycj/StableNormal",
            "StableNormal_turbo",
            trust_repo=True,
            yoso_version="yoso-normal-v1-8-1",
            local_cache_dir=str(weights_dir),
        )


def as_pil(image) -> Image.Image:
    if isinstance(image, Image.Image):
        return image
    if isinstance(image, np.ndarray):
        arr = image
        if arr.dtype != np.uint8:
            arr = np.clip(arr * 255.0 if arr.max() <= 1.0 else arr, 0, 255).astype(np.uint8)
        return Image.fromarray(arr)
    raise TypeError(f"unsupported normal image type: {type(image)}")


def load_models(repo: Path, volume_dir: Path | None = None):
    repo = repo.resolve()
    os.chdir(repo)
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    weights_dir = link_repo_weights(repo, volume_dir.resolve()) if volume_dir else (repo / "weights")
    if volume_dir is None:
        cache_weights(weights_dir)

    from hi3dgen.pipelines import Hi3DGenPipeline
    import hi3dgen.pipelines.hi3dgen as _h0_pipe

    # Upstream _init_image_cond_model uses os.path without importing os.
    _h0_pipe.os = os

    print("load Hi3DGenPipeline", flush=True)
    pipe = Hi3DGenPipeline.from_pretrained(str(weights_dir / "trellis-normal-v0-1"))
    pipe.cuda()
    print("load StableNormal", flush=True)
    normal_predictor = load_normal_predictor(weights_dir)
    return pipe, normal_predictor


def infer_mesh(pipe, normal_predictor, image: Image.Image, out: Path, *, seed: int, normal_out: Path | None = None) -> Path:
    print(f"preprocess size={image.size}", flush=True)
    image = pipe.preprocess_image(image.convert("RGBA"), resolution=1024)
    print("normal bridge 768", flush=True)
    normal_image = as_pil(
        normal_predictor(image, resolution=768, match_input_resolution=True, data_type="object")
    )
    if normal_out:
        normal_out.parent.mkdir(parents=True, exist_ok=True)
        normal_image.save(normal_out)
        print(f"wrote {normal_out}", flush=True)

    print(f"run mesh seed={seed}", flush=True)
    outputs = pipe.run(
        normal_image,
        seed=seed,
        formats=["mesh"],
        preprocess_image=False,
        sparse_structure_sampler_params={"steps": 50, "cfg_strength": 3},
        slat_sampler_params={"steps": 6, "cfg_strength": 3},
    )
    mesh = outputs["mesh"][0]
    trimesh_mesh = mesh.to_trimesh(transform_pose=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    trimesh_mesh.export(str(out))
    print(f"wrote {out} bytes={out.stat().st_size}", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Hi3DGen H0 headless infer")
    ap.add_argument("--image", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--normal-out", type=Path, default=None)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--volume-weights", type=Path, default=None)
    args = ap.parse_args()

    pipe, predictor = load_models(args.repo, args.volume_weights)
    infer_mesh(
        pipe,
        predictor,
        Image.open(args.image),
        args.out,
        seed=args.seed,
        normal_out=args.normal_out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
