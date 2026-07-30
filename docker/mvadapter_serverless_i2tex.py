"""Serverless-friendly texture_i2tex: lower UV size, no view upscale, fewer steps."""
from __future__ import annotations

import argparse
import os
import time

import torch
from torchvision import transforms
from transformers import AutoModelForImageSegmentation

from mvadapter.pipelines.pipeline_texture import ModProcessConfig, TexturePipeline
from mvadapter.utils import make_image_grid


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _phase(msg: str, t0: float | None = None) -> float:
    now = time.perf_counter()
    if t0 is None:
        print(f"[i2tex] {msg}", flush=True)
    else:
        print(f"[i2tex] {msg} (+{now - t0:.1f}s)", flush=True)
    return now


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=str, default="cuda")
    parser.add_argument("--variant", type=str, default="sdxl", choices=["sdxl", "sd21"])
    parser.add_argument("--mesh", type=str, required=True)
    parser.add_argument("--image", type=str, required=True)
    parser.add_argument("--text", type=str, default="high quality")
    parser.add_argument("--seed", type=int, default=-1)
    parser.add_argument("--save_dir", type=str, default="./output")
    parser.add_argument("--save_name", type=str, default="i2tex_sample")
    parser.add_argument("--reference_conditioning_scale", type=float, default=1.0)
    parser.add_argument("--preprocess_mesh", action="store_true")
    parser.add_argument("--remove_bg", action="store_true")
    args = parser.parse_args()

    t_job = _phase(
        f"start variant={args.variant} mesh={args.mesh} image={args.image} "
        f"remove_bg={args.remove_bg} preprocess_mesh={args.preprocess_mesh} "
        f"HF_HOME={os.environ.get('HF_HOME')} "
        f"TORCH_EXTENSIONS_DIR={os.environ.get('TORCH_EXTENSIONS_DIR')}"
    )

    tex_steps = _env_int("MVADAPTER_TEX_STEPS", 30)
    uv_size = _env_int("MVADAPTER_UV_SIZE", 2048)

    if args.variant == "sdxl":
        from scripts.inference_ig2mv_sdxl import prepare_pipeline, remove_bg, run_pipeline

        base_model = "stabilityai/stable-diffusion-xl-base-1.0"
        vae_model = "madebyollin/sdxl-vae-fp16-fix"
        height = width = 768
        if uv_size <= 0:
            uv_size = 2048
    elif args.variant == "sd21":
        from scripts.inference_ig2mv_sd import prepare_pipeline, remove_bg, run_pipeline

        base_model = "stabilityai/stable-diffusion-2-1-base"
        vae_model = None
        height = width = 512
        if uv_size <= 0:
            uv_size = 2048
    else:
        raise ValueError(f"Invalid variant: {args.variant}")

    device = args.device
    num_views = 6

    t0 = _phase(f"prepare_pipeline begin base={base_model} adapter=huanngzh/mv-adapter")
    pipe = prepare_pipeline(
        base_model=base_model,
        vae_model=vae_model,
        unet_model=None,
        lora_model=None,
        adapter_path="huanngzh/mv-adapter",
        scheduler=None,
        num_views=num_views,
        device=device,
        dtype=torch.float16,
    )
    _phase("prepare_pipeline done", t0)

    birefnet = None
    if args.remove_bg:
        t0 = _phase("BiRefNet load begin")
        birefnet = AutoModelForImageSegmentation.from_pretrained(
            "ZhengPeng7/BiRefNet", trust_remote_code=True
        )
        birefnet.to(args.device)
        transform_image = transforms.Compose(
            [
                transforms.Resize((1024, 1024)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )
        remove_bg_fn = lambda x: remove_bg(x, birefnet, transform_image, args.device)
        _phase("BiRefNet load done", t0)
    else:
        remove_bg_fn = None

    t0 = _phase("TexturePipeline init begin")
    texture_pipe = TexturePipeline(
        upscaler_ckpt_path="./checkpoints/RealESRGAN_x2plus.pth",
        inpaint_ckpt_path="./checkpoints/big-lama.pt",
        device=device,
    )
    _phase("TexturePipeline init done", t0)
    print(
        f"[i2tex] config steps={tex_steps} uv_size={uv_size} "
        f"view_upscale=False inpaint_mode=uv",
        flush=True,
    )

    os.makedirs(args.save_dir, exist_ok=True)

    t0 = _phase(f"diffusion begin steps={tex_steps}")
    images, _, _, _ = run_pipeline(
        pipe,
        mesh_path=args.mesh,
        num_views=num_views,
        text=args.text,
        image=args.image,
        height=height,
        width=width,
        num_inference_steps=tex_steps,
        guidance_scale=3.0,
        seed=args.seed,
        reference_conditioning_scale=args.reference_conditioning_scale,
        negative_prompt="watermark, ugly, deformed, noisy, blurry, low contrast",
        device=device,
        remove_bg_fn=remove_bg_fn,
    )
    mv_path = os.path.join(args.save_dir, f"{args.save_name}.png")
    make_image_grid(images, rows=1).save(mv_path)
    _phase(f"diffusion done saved={mv_path}", t0)

    del pipe
    if birefnet is not None:
        del birefnet
    torch.cuda.empty_cache()
    _phase("VRAM freed before UV bake")

    t0 = _phase(
        f"UV bake begin uv_size={uv_size} preprocess_mesh={args.preprocess_mesh}"
    )
    out = texture_pipe(
        mesh_path=args.mesh,
        save_dir=args.save_dir,
        save_name=args.save_name,
        uv_unwarp=True,
        preprocess_mesh=args.preprocess_mesh,
        uv_size=uv_size,
        rgb_path=mv_path,
        rgb_process_config=ModProcessConfig(view_upscale=False, inpaint_mode="uv"),
        camera_azimuth_deg=[x - 90 for x in [0, 90, 180, 270, 180, 180]],
    )
    _phase(f"UV bake done shaded={out.shaded_model_save_path}", t0)
    _phase("job complete", t_job)
    print(f"Output saved to {out.shaded_model_save_path}", flush=True)
