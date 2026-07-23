"""
RunPod handler: clay/textured mesh URL + reference image → TRELLIS.2 texturing → GLB.

Texture v1 (mesh paint). Separate from worker_trellis2.py (image→3D generate).
Deploy via Dockerfile.texture on a dedicated endpoint (same CUDA 12.4 stack).

Upstream: Trellis2TexturingPipeline (texturing_pipeline.json).
"""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import tempfile
import time
import traceback
import urllib.request
from pathlib import Path

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

DEFAULT_RESOLUTION = 1024
DEFAULT_TEXTURE_SIZE = 2048
DEFAULT_SEED = 1
DEFAULT_OUTPUT_DIR = "/runpod-volume/outputs"
DEFAULT_BASE64_MAX_BYTES = 5 * 1024 * 1024
VALID_RESOLUTIONS = frozenset({512, 1024, 1536})
VALID_TEXTURE_SIZES = frozenset({1024, 2048, 4096})


def _coerce_int(value, default: int, *, min_val: int, max_val: int) -> int:
    if value is None:
        return default
    try:
        out = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_val, min(max_val, out))


def _params(job_input: dict) -> dict:
    resolution = _coerce_int(
        job_input.get("resolution"),
        DEFAULT_RESOLUTION,
        min_val=512,
        max_val=1536,
    )
    if resolution not in VALID_RESOLUTIONS:
        resolution = min(VALID_RESOLUTIONS, key=lambda x: abs(x - resolution))

    texture_size = _coerce_int(
        job_input.get("texture_size"),
        DEFAULT_TEXTURE_SIZE,
        min_val=1024,
        max_val=4096,
    )
    if texture_size not in VALID_TEXTURE_SIZES:
        texture_size = min(VALID_TEXTURE_SIZES, key=lambda x: abs(x - texture_size))

    seed = _coerce_int(job_input.get("seed"), DEFAULT_SEED, min_val=0, max_val=2**31 - 1)
    return {
        "resolution": resolution,
        "texture_size": texture_size,
        "seed": seed,
        "preprocess_image": bool(job_input.get("preprocess_image", True)),
    }


def _rewrite_texturing_pipeline_json(model_path: str) -> None:
    """Same DINOv3 / rembg rewrites as generate worker, for texturing_pipeline.json."""
    import json

    pipeline_json = Path(model_path) / "texturing_pipeline.json"
    if not pipeline_json.is_file():
        print(f"texturing_pipeline.json not found under {model_path}; skip rewrites")
        return

    data = json.loads(pipeline_json.read_text(encoding="utf-8"))
    args = data.get("args") or data
    changed = False

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
        print(f"texturing DINOv3 model_name: {old!r} -> {root}")
        changed = True
    elif isinstance(image_cond, dict):
        print(f"texturing DINOv3 local path missing or incomplete: {root}")

    rembg_model = args.get("rembg_model")
    rembg_id = os.environ.get("TRELLIS2_REMBG_MODEL", "ZhengPeng7/BiRefNet")
    if isinstance(rembg_model, dict):
        rembg_args = rembg_model.setdefault("args", {})
        old_rembg = rembg_args.get("model_name")
        if old_rembg != rembg_id:
            rembg_args["model_name"] = rembg_id
            print(f"texturing rembg model_name: {old_rembg!r} -> {rembg_id!r}")
            changed = True

    if changed:
        pipeline_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_model():
    global pipeline
    build_sha = os.environ.get("PARADOX_BUILD_SHA", "unknown")
    print(f"paradox_worker texture image build: {build_sha}")

    if pipeline is not None:
        return

    from huggingface_hub import snapshot_download
    from trellis2.pipelines import Trellis2TexturingPipeline

    model_id = os.environ.get("TRELLIS2_MODEL_ID", "microsoft/TRELLIS.2-4B")
    print(f"Loading TRELLIS.2 texturing from {model_id} (volume cache)")
    model_path = snapshot_download(
        model_id,
        local_dir="/runpod-volume/trellis2-weights",
    )
    _rewrite_texturing_pipeline_json(model_path)
    pipeline = Trellis2TexturingPipeline.from_pretrained(
        model_path,
        config_file="texturing_pipeline.json",
    )
    pipeline.cuda()
    print("TRELLIS.2 texturing pipeline ready")


def _download(url: str, suffix: str) -> str:
    # R2 (and some CDNs) return 403 for urllib's default User-Agent.
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as response, open(path, "wb") as out:
        shutil.copyfileobj(response, out)
    return path


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _upload_r2(local_path: str, object_key: str) -> str | None:
    endpoint = os.environ.get("R2_ENDPOINT_URL", "").strip()
    bucket = os.environ.get("R2_BUCKET", "").strip()
    access_key = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
    public_base = os.environ.get("R2_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not all([endpoint, bucket, access_key, secret_key, public_base]):
        return None
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        print("boto3 not installed; skip R2 upload")
        return None

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=os.environ.get("R2_REGION", "auto"),
        config=Config(signature_version="s3v4"),
    )
    client.upload_file(
        local_path,
        bucket,
        object_key,
        ExtraArgs={"ContentType": "model/gltf-binary"},
    )
    url = f"{public_base}/{object_key}"
    print(f"Uploaded textured GLB to R2: {url}")
    return url


def _deliver_glb(temp_glb_path: str, job_id: str, *, return_base64: bool) -> dict:
    output_dir = Path(os.environ.get("TRELLIS2_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in job_id) or "job"
    dest = output_dir / f"{safe_id}-tex.glb"
    shutil.copy2(temp_glb_path, dest)

    size = dest.stat().st_size
    sha = _sha256_file(str(dest))
    object_key = f"trellis2-texture/{safe_id}.glb"
    model_url = _upload_r2(str(dest), object_key)

    delivery = {
        "model_path": str(dest),
        "model_bytes": size,
        "model_sha256": sha,
        "model_url": model_url,
        "delivery": "r2" if model_url else "volume",
        "worker_variant": "trellis2-texture",
    }

    max_b64 = int(os.environ.get("TRELLIS2_BASE64_MAX_BYTES", str(DEFAULT_BASE64_MAX_BYTES)))
    include_b64 = return_base64 or (model_url is None and size <= max_b64)
    if include_b64 and size <= max_b64:
        with open(dest, "rb") as handle:
            delivery["model_base64"] = base64.b64encode(handle.read()).decode("utf-8")
    elif return_base64 and size > max_b64:
        delivery["base64_omitted"] = (
            f"GLB is {size} bytes; exceeds base64 cap. Use model_url or model_path."
        )

    return delivery


def handler(job):
    job_input = job.get("input", {})
    mesh_url = job_input.get("mesh_url") or job_input.get("glb_url")
    image_url = job_input.get("image_url")
    params = _params(job_input)
    return_base64 = bool(job_input.get("return_base64", False))
    job_id = str(job.get("id") or f"tex-{int(time.time())}")

    if not mesh_url:
        return {"error": "Missing mesh_url (clay/textured GLB) in job input"}
    if not image_url:
        return {"error": "Missing image_url (texture reference) in job input"}

    mesh_path = None
    img_path = None
    glb_path = None

    try:
        t0 = time.perf_counter()
        handler_ms = {}

        t_load = time.perf_counter()
        load_model()
        handler_ms["model_load_ms"] = int((time.perf_counter() - t_load) * 1000)

        print(
            "TRELLIS.2 texture params: "
            f"resolution={params['resolution']}, "
            f"texture_size={params['texture_size']}, "
            f"seed={params['seed']}"
        )

        mesh_path = _download(str(mesh_url), ".glb")
        img_path = _download(str(image_url), ".png")
        # Upstream prefers alpha-masked RGBA; keep alpha when present.
        image = Image.open(img_path)
        if image.mode not in ("RGBA", "RGB"):
            image = image.convert("RGBA")

        import trimesh

        mesh = trimesh.load(mesh_path)
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.to_mesh() if hasattr(mesh, "to_mesh") else mesh.dump(concatenate=True)

        t_infer = time.perf_counter()
        # Upstream: example_texturing.py / app_texturing.py
        result = pipeline.run(
            mesh,
            image,
            seed=params["seed"],
            preprocess_image=params["preprocess_image"],
            resolution=params["resolution"],
            texture_size=params["texture_size"],
        )
        handler_ms["inference_ms"] = int((time.perf_counter() - t_infer) * 1000)

        fd, glb_path = tempfile.mkstemp(suffix=".glb")
        os.close(fd)
        t_export = time.perf_counter()
        if hasattr(result, "export"):
            result.export(glb_path, extension_webp=True)
        elif isinstance(result, (str, Path)):
            shutil.copy2(str(result), glb_path)
        else:
            return {"error": f"Unexpected texturing result type: {type(result)!r}"}
        handler_ms["glb_export_ms"] = int((time.perf_counter() - t_export) * 1000)

        t_del = time.perf_counter()
        delivery = _deliver_glb(glb_path, job_id, return_base64=return_base64)
        handler_ms["deliver_ms"] = int((time.perf_counter() - t_del) * 1000)
        handler_ms["total_ms"] = int((time.perf_counter() - t0) * 1000)

        out = {
            **delivery,
            "generation": {
                "task_type": "texture",
                "resolution": params["resolution"],
                "texture_size": params["texture_size"],
                "seed": params["seed"],
            },
            "billing": {
                "worker_variant": "trellis2-texture",
                "handler_ms": handler_ms,
                "gpu_type": None,
            },
        }
        return out
    except Exception as exc:
        traceback.print_exc()
        return {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        for path in (mesh_path, img_path, glb_path):
            if path and os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


runpod.serverless.start({"handler": handler})
