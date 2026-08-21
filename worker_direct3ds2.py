"""RunPod handler: image URL → Direct3D-S2 sparse SDF mesh → GLB.

Geometry only (no PBR). Default sdf_resolution=1024 — that is the gate, not 512.
Separate stack from worker_trellis2.py / worker_pixal3d.py.
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

# Must be set before importing direct3d_s2.modules.sparse.
# xformers covers TRELLIS-style sparse attn. SSA still needs flash-attn in the image.
os.environ.setdefault("SPARSE_BACKEND", "torchsparse")
os.environ.setdefault("SPARSE_ATTN_BACKEND", "xformers")
os.environ.setdefault("ATTN_BACKEND", "xformers")
os.environ.setdefault("HF_HOME", "/runpod-volume/huggingface_cache")
os.environ.setdefault("TORCH_HOME", "/runpod-volume/torch_hub")
os.environ.setdefault("PYTHONUNBUFFERED", "1")

MODEL_ID = os.environ.get("DIRECT3DS2_MODEL_ID", "wushuang98/Direct3D-S2")
MODEL_SUBFOLDER = os.environ.get("DIRECT3DS2_SUBFOLDER", "direct3d-s2-v-1-1")
DEFAULT_OUTPUT_DIR = os.environ.get("DIRECT3DS2_OUTPUT_DIR", "/runpod-volume/outputs")
DEFAULT_BASE64_MAX_BYTES = 8 * 1024 * 1024
VALID_RESOLUTIONS = (512, 1024)

_PIPELINE = None


def _download_image(image_url: str) -> str:
    req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_img:
        with urllib.request.urlopen(req, timeout=120) as response:
            temp_img.write(response.read())
        return temp_img.name


def _upload_r2(local_path: Path, key: str) -> str | None:
    endpoint = os.environ.get("R2_ENDPOINT_URL", "").strip()
    bucket = os.environ.get("R2_BUCKET", "").strip()
    access_key = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
    public_base = os.environ.get("R2_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not all((endpoint, bucket, access_key, secret_key, public_base)):
        return None

    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=os.environ.get("R2_REGION", "auto"),
    )
    client.upload_file(
        str(local_path), bucket, key, ExtraArgs={"ContentType": "model/gltf-binary"}
    )
    return f"{public_base}/{key}"


def _load_pipeline():
    global _PIPELINE
    if _PIPELINE is not None:
        return _PIPELINE

    import torch
    from direct3d_s2.pipeline import Direct3DS2Pipeline

    print(f"paradox_worker direct3ds2 build: {os.environ.get('PARADOX_BUILD_SHA', 'dev')}")
    token = os.environ.get("HF_TOKEN") or None
    if token:
        os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", token)

    print(f"Loading Direct3D-S2 {MODEL_ID}/{MODEL_SUBFOLDER}...")
    pipeline = Direct3DS2Pipeline.from_pretrained(
        MODEL_ID, subfolder=MODEL_SUBFOLDER
    ).to("cuda:0")
    pipeline.dtype = torch.float16
    print("Direct3D-S2 pipeline ready.")
    _PIPELINE = pipeline
    return pipeline


def handler(job):
    started = time.time()
    job_input = job.get("input") or {}
    image_url = job_input.get("image_url")
    if not image_url:
        return {"error": "image_url is required"}

    resolution = int(job_input.get("sdf_resolution") or job_input.get("resolution") or 1024)
    if resolution not in VALID_RESOLUTIONS:
        return {
            "error": f"sdf_resolution must be one of {VALID_RESOLUTIONS}, got {resolution}"
        }

    seed = int(job_input.get("seed", 42))
    remesh = bool(job_input.get("remesh", False))
    simplify_ratio = float(job_input.get("simplify_ratio", 0.95))
    remove_interior = bool(job_input.get("remove_interior", True))
    mc_threshold = float(job_input.get("mc_threshold", 0.2))

    image_path = None
    try:
        import torch

        pipeline = _load_pipeline()
        load_done = time.time()

        image_path = _download_image(image_url)
        generator = torch.Generator(device="cuda").manual_seed(seed)
        print(f"Running Direct3D-S2 sdf_resolution={resolution} seed={seed} remesh={remesh}")
        mesh = pipeline(
            image_path,
            sdf_resolution=resolution,
            generator=generator,
            remesh=remesh,
            simplify_ratio=simplify_ratio,
            remove_interior=remove_interior,
            mc_threshold=mc_threshold,
        )["mesh"]
        infer_done = time.time()

        output_dir = Path(DEFAULT_OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        name = f"direct3ds2_{int(time.time())}_{seed}_{resolution}.glb"
        dest = output_dir / name
        mesh.export(str(dest), file_type="glb")
        size = dest.stat().st_size
        verts = int(getattr(mesh, "vertices", []).shape[0]) if hasattr(mesh, "vertices") else 0
        faces = int(getattr(mesh, "faces", []).shape[0]) if hasattr(mesh, "faces") else 0
        print(f"GLB saved: {dest} ({size / 2**20:.1f} MB, {verts} v / {faces} f)")

        result = {
            "model_path": str(dest),
            "size_bytes": size,
            "sdf_resolution": resolution,
            "seed": seed,
            "verts": verts,
            "faces": faces,
            "remesh": remesh,
            "worker_variant": "direct3ds2",
            "build_sha": os.environ.get("PARADOX_BUILD_SHA", "dev"),
            "timings_s": {
                "load": round(load_done - started, 1),
                "inference": round(infer_done - load_done, 1),
                "export": round(time.time() - infer_done, 1),
                "total": round(time.time() - started, 1),
            },
        }

        model_url = _upload_r2(dest, f"direct3ds2/{name}")
        if model_url:
            result["model_url"] = model_url
        elif size <= int(
            os.environ.get("DIRECT3DS2_BASE64_MAX_BYTES", str(DEFAULT_BASE64_MAX_BYTES))
        ):
            result["model_base64"] = base64.b64encode(dest.read_bytes()).decode()
        else:
            result["note"] = (
                "GLB too large for base64 and R2_* env is not configured; "
                "read model_path from the network volume."
            )
        return result

    except Exception as exc:
        traceback.print_exc()
        return {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        if image_path and os.path.exists(image_path):
            os.remove(image_path)


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
