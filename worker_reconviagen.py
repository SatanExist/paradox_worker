"""
RunPod handler: multi-view images -> ReconViaGen v0.5 hybrid -> GLB.

Deploy via Dockerfile.reconviagen on a dedicated 24GB+ endpoint.
Weights: Stable-X/trellis-vggt-v0-2 + microsoft/TRELLIS.2-4B (HF cache on volume).
"""

from __future__ import annotations

import base64
import os
import tempfile
import time
import traceback
import urllib.request
from pathlib import Path

import runpod
from PIL import Image

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("SPCONV_ALGO", "native")
os.environ.setdefault("XFORMERS_DISABLED", "1")
os.environ.setdefault("ATTN_BACKEND", "sdpa")
os.environ.setdefault("SPARSE_ATTN_BACKEND", "xformers")
os.environ.setdefault("SPARSE_CONV_BACKEND", "flex_gemm")
os.environ.setdefault("HF_HOME", "/runpod-volume/huggingface_cache")

RVG_REPO = Path(os.environ.get("RVG_REPO", "/app/ReconViaGen"))
DEFAULT_OUTPUT_DIR = "/runpod-volume/outputs"
DEFAULT_BASE64_MAX_BYTES = 5 * 1024 * 1024

_pipeline = None


def _download_image(url: str) -> str:
    suffix = ".png"
    if "." in url.rsplit("/", 1)[-1]:
        suffix = "." + url.rsplit(".", 1)[-1].split("?")[0]
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="rvg_img_")
    os.close(fd)
    req = urllib.request.Request(url, headers={"User-Agent": "paradox_worker/reconviagen"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        Path(path).write_bytes(resp.read())
    return path


def _resolve_image_urls(job_input: dict) -> list[str]:
    urls = job_input.get("image_urls")
    if isinstance(urls, list) and urls:
        return [str(u).strip() for u in urls if str(u).strip()]
    one = job_input.get("image_url")
    if one:
        return [str(one).strip()]
    return []


def load_pipeline() -> None:
    global _pipeline
    if _pipeline is not None:
        return

    import torch

    trellis2 = RVG_REPO / "wheels" / "TRELLIS.2"
    if trellis2.is_dir():
        import sys

        for p in (str(trellis2), str(RVG_REPO)):
            if p not in sys.path:
                sys.path.insert(0, p)

    from trellis.pipelines import TrellisVGGTTo3DPipeline
    from trellis2.pipelines import Trellis2ImageTo3DPipeline
    from trellis.pipelines.trellis_hybrid_pipeline import TrellisHybridPipeline

    print("Loading ReconViaGen VGGT pipeline (Stable-X/trellis-vggt-v0-2) ...")
    vggt = TrellisVGGTTo3DPipeline.from_pretrained("Stable-X/trellis-vggt-v0-2")
    vggt.cuda()
    vggt.VGGT_model.cuda()
    vggt.birefnet_model.cuda()
    if "slat_decoder_gs" in vggt.models:
        del vggt.models["slat_decoder_gs"]
    vggt.VGGT_model.cpu()
    for model in vggt.models.values():
        model.cpu()

    print("Loading TRELLIS.2 pipeline (microsoft/TRELLIS.2-4B) ...")
    t2 = Trellis2ImageTo3DPipeline.from_pretrained("microsoft/TRELLIS.2-4B")
    t2.cuda()
    t2.low_vram = True

    _pipeline = TrellisHybridPipeline(vggt, t2, low_vram=True)
    print(f"ReconViaGen hybrid pipeline ready (cuda={torch.cuda.is_available()})")


def handler(job: dict) -> dict:
    job_input = job.get("input", {}) or {}
    image_urls = _resolve_image_urls(job_input)
    if not image_urls:
        return {"error": "Missing image_url or image_urls in job input"}

    seed = int(job_input.get("seed", 42))
    strategy = str(job_input.get("multi_image_strategy", "adaptive_guidance_weight"))
    pipeline_type = str(job_input.get("pipeline_type", "1024_cascade"))
    ss_source = str(job_input.get("ss_source", "mesh"))
    decimation = int(job_input.get("decimation_target", 700_000))
    texture_size = int(job_input.get("texture_size", 2048))
    return_base64 = bool(job_input.get("return_base64", False))
    job_id = str(job.get("id") or f"local-{int(time.time())}")

    img_paths: list[str] = []
    out_path: str | None = None

    try:
        t0 = time.perf_counter()
        load_pipeline()

        images: list[Image.Image] = []
        for i, url in enumerate(image_urls):
            print(f"Downloading image[{i}]: {url}")
            path = _download_image(url)
            img_paths.append(path)
            img = Image.open(path)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            images.append(img)

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
            f"ReconViaGen infer: n={len(images)} strategy={strategy} "
            f"pipeline={pipeline_type} seed={seed}"
        )

        if len(images) == 1:
            _, latents = _pipeline.run(
                images,
                seed=seed,
                ss_sampler_params=ss_params,
                slat_sampler_params=slat_params,
                shape_slat_sampler_params=shape_slat_params,
                tex_slat_sampler_params=tex_slat_params,
                pipeline_type=pipeline_type,
                preprocess_image=True,
                return_latent=True,
                ss_source=ss_source,
            )
        else:
            _, latents = _pipeline.run_multi_image(
                images,
                strategy=strategy,
                seed=seed,
                ss_sampler_params=ss_params,
                slat_sampler_params=slat_params,
                shape_slat_sampler_params=shape_slat_params,
                tex_slat_sampler_params=tex_slat_params,
                pipeline_type=pipeline_type,
                preprocess_image=True,
                return_latent=True,
                ss_source=ss_source,
            )

        shape_slat, tex_slat, res = latents
        mesh = _pipeline.trellis2_pipeline.decode_latent(shape_slat, tex_slat, res)[0]

        import o_voxel

        glb = o_voxel.postprocess.to_glb(
            vertices=mesh.vertices,
            faces=mesh.faces,
            attr_volume=mesh.attrs,
            coords=mesh.coords,
            attr_layout=_pipeline.pbr_attr_layout,
            grid_size=res,
            aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target=decimation,
            texture_size=texture_size,
            remesh=True,
            remesh_band=1,
            remesh_project=0,
            use_tqdm=True,
        )

        os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
        out_path = os.path.join(DEFAULT_OUTPUT_DIR, f"{job_id}.glb")
        glb.export(out_path, extension_webp=True)
        size = os.path.getsize(out_path)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        result: dict = {
            "job_id": job_id,
            "glb_path": out_path,
            "glb_bytes": size,
            "elapsed_ms": elapsed_ms,
            "num_images": len(images),
            "strategy": strategy,
            "pipeline_type": pipeline_type,
            "seed": seed,
        }

        if return_base64 and size <= DEFAULT_BASE64_MAX_BYTES:
            result["glb_base64"] = base64.b64encode(Path(out_path).read_bytes()).decode("ascii")

        return result
    except Exception as exc:
        tb = traceback.format_exc()
        print(f"RECONVIAGEN ERROR: {exc}")
        print(tb)
        return {"error": str(exc), "traceback": tb}
    finally:
        for p in img_paths:
            try:
                os.remove(p)
            except OSError:
                pass


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
