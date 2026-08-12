#!/usr/bin/env python3
"""Headless ReconViaGen v0.5 inference (no Gradio).

Run inside the cloned ReconViaGen repo (cwd = repo root) with the
reconviagen_v05 conda env activated.

Example:
  python /workspace/scripts/reconviagen_infer.py \\
    --image /workspace/data/front.png \\
    --image /workspace/data/back.png \\
    --seed 42 --pipeline 1024_cascade \\
    --save /workspace/outputs/r_pod_armor_fb.glb
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import torch
from PIL import Image


def _boot_paths(repo: Path) -> None:
    trellis2 = repo / "wheels" / "TRELLIS.2"
    if trellis2.is_dir() and str(trellis2) not in sys.path:
        sys.path.insert(0, str(trellis2))
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    os.environ.setdefault("SPCONV_ALGO", "native")
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    os.environ.setdefault("XFORMERS_DISABLED", "1")


def main() -> int:
    p = argparse.ArgumentParser(description="ReconViaGen v0.5 headless → GLB")
    p.add_argument("--repo", type=Path, default=Path(os.environ.get("RVG_REPO", "/app/ReconViaGen")))
    p.add_argument("--image", action="append", required=True, help="RGBA/RGB path (repeat)")
    p.add_argument("--strategy", default="adaptive_guidance_weight")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--pipeline",
        default="1024_cascade",
        choices=["512", "1024", "1024_cascade", "1536_cascade"],
    )
    p.add_argument("--ss-source", default="mesh", choices=["direct", "mesh", "mvtrellis2"])
    p.add_argument("--decimation", type=int, default=700_000)
    p.add_argument("--texture-size", type=int, default=2048)
    p.add_argument("--save", type=Path, required=True)
    p.add_argument("--low-vram", action="store_true", default=True)
    args = p.parse_args()

    repo = args.repo.resolve()
    if not repo.is_dir():
        print(f"Repo missing: {repo}", file=sys.stderr)
        return 1
    _boot_paths(repo)
    os.chdir(repo)

    print(f"[{datetime.utcnow().isoformat()}Z] Loading pipelines…", flush=True)
    from trellis.pipelines import TrellisVGGTTo3DPipeline
    from trellis2.pipelines import Trellis2ImageTo3DPipeline
    from trellis.pipelines.trellis_hybrid_pipeline import TrellisHybridPipeline
    import o_voxel

    vggt = TrellisVGGTTo3DPipeline.from_pretrained("Stable-X/trellis-vggt-v0-2")
    vggt.cuda()
    vggt.VGGT_model.cuda()
    vggt.birefnet_model.cuda()
    if "slat_decoder_gs" in vggt.models:
        del vggt.models["slat_decoder_gs"]
    if "slat_decoder_rf" in getattr(vggt, "models", {}):
        # optional; ignore if absent
        try:
            del vggt.models["slat_decoder_rf"]
        except KeyError:
            pass
    vggt.VGGT_model.cpu()
    for model in vggt.models.values():
        model.cpu()

    t2 = Trellis2ImageTo3DPipeline.from_pretrained("microsoft/TRELLIS.2-4B")
    t2.cuda()
    t2.low_vram = True

    pipeline = TrellisHybridPipeline(vggt, t2, low_vram=bool(args.low_vram))
    print(f"[{datetime.utcnow().isoformat()}Z] Pipelines ready", flush=True)

    images: list[Image.Image] = []
    for path in args.image:
        img = Image.open(path)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        images.append(img)
        print(f"  image {path} size={img.size}", flush=True)

    ss_params = {
        "steps": 12,
        "cfg_strength": 7.5,
        "cfg_interval": [0.6, 1.0],
        "guidance_rescale": 0.7,
        "rescale_t": 5.0,
    }
    slat_params = {
        "steps": 12,
        "cfg_strength": 7.5,
        "cfg_interval": [0.6, 1.0],
        "guidance_rescale": 0.5,
        "rescale_t": 3.0,
    }
    shape_slat_params = {
        "steps": 8,
        "guidance_strength": 7.5,
        "guidance_rescale": 0.5,
        "rescale_t": 3.0,
    }
    tex_slat_params = {
        "steps": 8,
        "guidance_strength": 1.0,
        "guidance_rescale": 0.0,
        "rescale_t": 3.0,
    }

    print(
        f"[{datetime.utcnow().isoformat()}Z] run "
        f"n={len(images)} strategy={args.strategy} pipeline={args.pipeline} seed={args.seed}",
        flush=True,
    )
    if len(images) == 1:
        out_mesh_list, latents = pipeline.run(
            images,
            seed=args.seed,
            ss_sampler_params=ss_params,
            slat_sampler_params=slat_params,
            shape_slat_sampler_params=shape_slat_params,
            tex_slat_sampler_params=tex_slat_params,
            pipeline_type=args.pipeline,
            preprocess_image=True,
            return_latent=True,
            ss_source=args.ss_source,
        )
    else:
        out_mesh_list, latents = pipeline.run_multi_image(
            images,
            strategy=args.strategy,
            seed=args.seed,
            ss_sampler_params=ss_params,
            slat_sampler_params=slat_params,
            shape_slat_sampler_params=shape_slat_params,
            tex_slat_sampler_params=tex_slat_params,
            pipeline_type=args.pipeline,
            preprocess_image=True,
            return_latent=True,
            ss_source=args.ss_source,
        )

    shape_slat, tex_slat, res = latents
    print(f"[{datetime.utcnow().isoformat()}Z] decode latent res={res}", flush=True)
    mesh = pipeline.trellis2_pipeline.decode_latent(shape_slat, tex_slat, res)[0]

    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices,
        faces=mesh.faces,
        attr_volume=mesh.attrs,
        coords=mesh.coords,
        attr_layout=pipeline.pbr_attr_layout,
        grid_size=res,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=args.decimation,
        texture_size=args.texture_size,
        remesh=True,
        remesh_band=1,
        remesh_project=0,
        use_tqdm=True,
    )

    args.save.parent.mkdir(parents=True, exist_ok=True)
    glb.export(str(args.save), extension_webp=True)
    size = args.save.stat().st_size
    print(f"[{datetime.utcnow().isoformat()}Z] Saved {args.save} ({size} bytes)", flush=True)
    torch.cuda.empty_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
