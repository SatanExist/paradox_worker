"""Headless Hi3DGen: same call path as the HF Space app.py.

RGB → rembg u2net (Space preprocess) → YOSO normal → TRELLIS-normal mesh GLB.

Not TRELLIS.2. Run with HI3DGEN_REPO on PYTHONPATH (Docker: /app/Hi3DGen).
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
from huggingface_hub import snapshot_download
from PIL import Image


def patch_xformers_block_diagonal_mask() -> None:
    """Sparse attn may import BlockDiagonalMask from xops.fmha; newer xformers moved it."""
    try:
        import xformers.ops as xops
    except ImportError:
        return
    if hasattr(xops.fmha, "BlockDiagonalMask"):
        return
    from xformers.ops.fmha.attn_bias import BlockDiagonalMask

    xops.fmha.BlockDiagonalMask = BlockDiagonalMask


patch_xformers_block_diagonal_mask()


def cache_dir(volume_dir: Path | None, repo: Path) -> Path:
    if volume_dir is not None:
        volume_dir.mkdir(parents=True, exist_ok=True)
        return volume_dir
    dest = repo / "weights"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


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
    """T2 pattern: snapshot_download onto the volume, then from_pretrained(local_dir)."""
    repo = repo.resolve()
    os.chdir(repo)
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    weights_root = cache_dir(volume_dir, repo)
    os.environ.setdefault("U2NET_HOME", str(weights_root / "u2net"))
    Path(os.environ["U2NET_HOME"]).mkdir(parents=True, exist_ok=True)

    model_dir = snapshot_download(
        "Stable-X/trellis-normal-v0-1",
        local_dir=str(weights_root / "trellis-normal-v0-1"),
    )
    print(f"load TrellisImageTo3DPipeline {model_dir}", flush=True)
    from trellis.pipelines.trellis_image_to_3d import TrellisImageTo3DPipeline

    pipe = TrellisImageTo3DPipeline.from_pretrained(model_dir)
    pipe.cuda()
    print("load StableNormal", flush=True)
    normal_predictor = load_normal_predictor(weights_root)
    return pipe, normal_predictor


def infer_mesh(
    pipe,
    normal_predictor,
    image: Image.Image,
    out: Path,
    *,
    seed: int,
    normal_out: Path | None = None,
    ss_steps: int = 50,
    slat_steps: int = 6,
    ss_cfg: float = 3.0,
    slat_cfg: float = 3.0,
    normal_resolution: int = 768,
    preprocess_resolution: int = 1024,
) -> Path:
    # Space app.py: preprocess_image(image, resolution=1024) then YOSO then run(preprocess_image=False).
    print(f"preprocess rembg size={image.size} res={preprocess_resolution}", flush=True)
    image = pipe.preprocess_image(image, resolution=preprocess_resolution)
    print(f"normal bridge {normal_resolution}", flush=True)
    normal_image = as_pil(
        normal_predictor(
            image,
            resolution=normal_resolution,
            match_input_resolution=True,
            data_type="object",
        )
    )
    if normal_out:
        normal_out.parent.mkdir(parents=True, exist_ok=True)
        normal_image.save(normal_out)
        print(f"wrote {normal_out}", flush=True)

    ss_steps = max(1, min(50, int(ss_steps)))
    slat_steps = max(1, min(50, int(slat_steps)))
    print(f"run mesh seed={seed} ss={ss_steps} slat={slat_steps} extract=space-flexicubes", flush=True)
    outputs = pipe.run(
        normal_image,
        seed=seed,
        formats=["mesh"],
        preprocess_image=False,
        sparse_structure_sampler_params={"steps": ss_steps, "cfg_strength": float(ss_cfg)},
        slat_sampler_params={"steps": slat_steps, "cfg_strength": float(slat_cfg)},
    )
    mesh = outputs["mesh"][0]
    trimesh_mesh = mesh.to_trimesh(transform_pose=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    trimesh_mesh.export(str(out))
    print(f"wrote {out} bytes={out.stat().st_size}", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Hi3DGen H0 headless infer (HF Space stack)")
    ap.add_argument("--image", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--normal-out", type=Path, default=None)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--repo", type=Path, default=Path(os.environ.get("HI3DGEN_REPO", ".")))
    ap.add_argument("--volume-weights", type=Path, default=None)
    ap.add_argument("--ss-steps", type=int, default=50)
    ap.add_argument("--slat-steps", type=int, default=6)
    args = ap.parse_args()

    pipe, predictor = load_models(args.repo, args.volume_weights)
    infer_mesh(
        pipe,
        predictor,
        Image.open(args.image),
        args.out,
        seed=args.seed,
        normal_out=args.normal_out,
        ss_steps=args.ss_steps,
        slat_steps=args.slat_steps,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
