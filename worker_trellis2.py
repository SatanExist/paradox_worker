"""
RunPod handler: image URL -> TRELLIS.2 -> GLB base64 (quality tier).

Separate from worker.py (TRELLIS v1 / CUDA 11.8).
Deploy via Dockerfile.trellis2 on a dedicated 24GB+ endpoint.
"""

from __future__ import annotations

import base64
import os
import tempfile
import time
import traceback
import urllib.request

import runpod
import torch
from PIL import Image

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("ATTN_BACKEND", "sdpa")
os.environ.setdefault("SPARSE_ATTN_BACKEND", "xformers")
os.environ.setdefault("SPARSE_CONV_BACKEND", "flex_gemm")
os.environ.setdefault("HF_HOME", "/runpod-volume/huggingface_cache")

pipeline = None

DEFAULT_PIPELINE_TYPE = "1024_cascade"
DEFAULT_TEXTURE_SIZE = 2048
DEFAULT_DECIMATION_TARGET = 500_000
DEFAULT_SEED = 1
NVDIFFRAST_FACE_LIMIT = 16_777_216

VALID_PIPELINE_TYPES = frozenset({"512", "1024", "1024_cascade", "1536_cascade"})
VALID_TEXTURE_SIZES = frozenset({1024, 2048, 4096})


def _runpod_billing_metadata(handler_ms: dict) -> dict:
    gpu_type = None
    for key in (
        "RUNPOD_WEBHOOK_POST_OUTPUT",
        "RUNPOD_WEBHOOK_GET_JOB",
        "RUNPOD_WEBHOOK_PING",
    ):
        url = os.environ.get(key, "")
        if "?gpu=" in url:
            gpu_type = url.split("?gpu=", 1)[1].split("&", 1)[0].replace("+", " ")
            break
    return {
        "gpu_type": gpu_type,
        "gpu_pool": os.environ.get("RUNPOD_GPU_SIZE"),
        "datacenter": os.environ.get("RUNPOD_DC_ID"),
        "worker_id": os.environ.get("RUNPOD_POD_ID"),
        "handler_ms": handler_ms,
        "worker_variant": "trellis2",
    }


def _coerce_int(value, default: int, *, min_val: int, max_val: int) -> int:
    if value is None:
        return default
    try:
        out = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_val, min(max_val, out))


def _generation_params(job_input: dict) -> dict:
    pipeline_type = job_input.get("pipeline_type") or DEFAULT_PIPELINE_TYPE
    if pipeline_type not in VALID_PIPELINE_TYPES:
        pipeline_type = DEFAULT_PIPELINE_TYPE

    texture_size = _coerce_int(
        job_input.get("texture_size"),
        DEFAULT_TEXTURE_SIZE,
        min_val=1024,
        max_val=4096,
    )
    if texture_size not in VALID_TEXTURE_SIZES:
        texture_size = min(VALID_TEXTURE_SIZES, key=lambda x: abs(x - texture_size))

    decimation_target = _coerce_int(
        job_input.get("decimation_target"),
        DEFAULT_DECIMATION_TARGET,
        min_val=50_000,
        max_val=1_000_000,
    )
    seed = _coerce_int(job_input.get("seed"), DEFAULT_SEED, min_val=0, max_val=2**31 - 1)
    preprocess_image = bool(job_input.get("preprocess_image", True))
    remesh = bool(job_input.get("remesh", True))
    verbose = bool(job_input.get("verbose", True))

    return {
        "pipeline_type": pipeline_type,
        "texture_size": texture_size,
        "decimation_target": decimation_target,
        "seed": seed,
        "preprocess_image": preprocess_image,
        "remesh": remesh,
        "verbose": verbose,
    }


def _rewrite_pipeline_json(model_path: str) -> None:
    """Rewrite TRELLIS.2 pipeline.json for RunPod: local DINOv3 + non-gated rembg."""
    import json
    from pathlib import Path

    pipeline_json = Path(model_path) / "pipeline.json"
    if not pipeline_json.is_file():
        print(f"pipeline.json not found under {model_path}; skip rewrites")
        return

    data = json.loads(pipeline_json.read_text(encoding="utf-8"))
    args = data.get("args") or data
    changed = False

    # DINOv3: Meta/HF gated — use converted local weights on the network volume.
    dinov3_path = os.environ.get(
        "TRELLIS2_DINOV3_PATH",
        "/runpod-volume/dinov3-vitl16-pretrain-lvd1689m",
    )
    root = Path(dinov3_path)
    image_cond = args.get("image_cond_model")
    if isinstance(image_cond, dict) and (root / "config.json").is_file():
        image_args = image_cond.setdefault("args", {})
        old = image_args.get("model_name")
        image_args["model_name"] = str(root)
        print(f"DINOv3 model_name: {old!r} -> {root}")
        changed = True
    elif isinstance(image_cond, dict):
        print(f"DINOv3 local path missing or incomplete: {root}")

    # rembg: briaai/RMBG-2.0 is gated + CC BY-NC — prefer public BiRefNet for POC/commercial.
    rembg_model = args.get("rembg_model")
    rembg_id = os.environ.get("TRELLIS2_REMBG_MODEL", "ZhengPeng7/BiRefNet")
    if isinstance(rembg_model, dict):
        rembg_args = rembg_model.setdefault("args", {})
        old_rembg = rembg_args.get("model_name")
        if old_rembg != rembg_id:
            rembg_args["model_name"] = rembg_id
            print(f"rembg model_name: {old_rembg!r} -> {rembg_id!r}")
            changed = True

    if changed:
        pipeline_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_model():
    global pipeline
    build_sha = os.environ.get("PARADOX_BUILD_SHA", "unknown")
    print(f"paradox_worker trellis2 image build: {build_sha}")

    if pipeline is not None:
        return

    print("Loading TRELLIS.2-4B onto network volume cache...")
    from huggingface_hub import snapshot_download
    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    model_id = os.environ.get("TRELLIS2_MODEL_ID", "microsoft/TRELLIS.2-4B")
    model_path = snapshot_download(
        model_id,
        local_dir="/runpod-volume/trellis2-weights",
    )
    _rewrite_pipeline_json(model_path)

    pipeline = Trellis2ImageTo3DPipeline.from_pretrained(model_path)
    pipeline.cuda()
    print("TRELLIS.2 pipeline ready in VRAM.")


def _download_image(image_url: str) -> str:
    req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_img:
        with urllib.request.urlopen(req) as response:
            temp_img.write(response.read())
        return temp_img.name


def _mesh_to_glb(mesh, gen_params: dict):
    import o_voxel

    mesh.simplify(NVDIFFRAST_FACE_LIMIT)

    return o_voxel.postprocess.to_glb(
        vertices=mesh.vertices,
        faces=mesh.faces,
        attr_volume=mesh.attrs,
        coords=mesh.coords,
        attr_layout=mesh.layout,
        voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=gen_params["decimation_target"],
        texture_size=gen_params["texture_size"],
        remesh=gen_params["remesh"],
        remesh_band=1,
        remesh_project=0,
        verbose=gen_params["verbose"],
    )


def handler(job):
    job_input = job.get("input", {})
    image_url = job_input.get("image_url")
    gen_params = _generation_params(job_input)

    if not image_url:
        return {"error": "Missing image_url in job input"}

    img_path = None
    glb_path = None

    try:
        t0 = time.perf_counter()
        handler_ms = {}

        t_load = time.perf_counter()
        load_model()
        handler_ms["model_load_ms"] = int((time.perf_counter() - t_load) * 1000)

        print(
            "TRELLIS.2 params: "
            f"pipeline_type={gen_params['pipeline_type']}, "
            f"texture_size={gen_params['texture_size']}, "
            f"decimation_target={gen_params['decimation_target']}, "
            f"seed={gen_params['seed']}"
        )

        print(f"Downloading image: {image_url}")
        img_path = _download_image(image_url)
        image = Image.open(img_path)

        t_infer = time.perf_counter()
        meshes = pipeline.run(
            image,
            seed=gen_params["seed"],
            preprocess_image=gen_params["preprocess_image"],
            pipeline_type=gen_params["pipeline_type"],
        )
        handler_ms["inference_ms"] = int((time.perf_counter() - t_infer) * 1000)

        mesh = meshes[0]

        t_glb = time.perf_counter()
        glb = _mesh_to_glb(mesh, gen_params)

        glb_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".glb")
        glb_path = glb_temp.name
        glb_temp.close()
        glb.export(glb_path, extension_webp=True)
        handler_ms["glb_export_ms"] = int((time.perf_counter() - t_glb) * 1000)
        handler_ms["total_ms"] = int((time.perf_counter() - t0) * 1000)

        with open(glb_path, "rb") as glb_file:
            glb_base64 = base64.b64encode(glb_file.read()).decode("utf-8")

        return {
            "status": "success",
            "message": "TRELLIS.2 model generated successfully",
            "model_base64": glb_base64,
            "generation": gen_params,
            "billing": _runpod_billing_metadata(handler_ms),
        }

    except Exception as exc:
        tb = traceback.format_exc()
        print(f"CRITICAL ERROR: {exc}")
        print(tb)
        return {"error": f"Generation failed: {exc}"}

    finally:
        if img_path and os.path.exists(img_path):
            os.remove(img_path)
        if glb_path and os.path.exists(glb_path):
            os.remove(glb_path)


runpod.serverless.start({"handler": handler})
