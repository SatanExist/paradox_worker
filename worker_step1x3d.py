"""RunPod handler: image URL → Step1X-3D geometry → clay GLB.

Geometry stage only. Texture bake is a second image after the identity gate.
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

os.environ.setdefault("HF_HOME", "/runpod-volume/huggingface_cache")
os.environ.setdefault("TORCH_HOME", "/runpod-volume/torch_hub")
os.environ.setdefault("PYTHONUNBUFFERED", "1")

MODEL_ID = os.environ.get("STEP1X3D_MODEL_ID", "stepfun-ai/Step1X-3D")
MODEL_SUBFOLDER = os.environ.get(
    "STEP1X3D_SUBFOLDER", "Step1X-3D-Geometry-1300m"
)
DEFAULT_OUTPUT_DIR = os.environ.get("STEP1X3D_OUTPUT_DIR", "/runpod-volume/outputs")
DEFAULT_BASE64_MAX_BYTES = 8 * 1024 * 1024

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
    from step1x3d_geometry.models.pipelines.pipeline import Step1X3DGeometryPipeline

    print(f"paradox_worker step1x3d build: {os.environ.get('PARADOX_BUILD_SHA', 'dev')}")
    token = os.environ.get("HF_TOKEN") or None
    if token:
        os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", token)

    print(f"Loading Step1X-3D {MODEL_ID}/{MODEL_SUBFOLDER}...")
    pipeline = Step1X3DGeometryPipeline.from_pretrained(
        MODEL_ID, subfolder=MODEL_SUBFOLDER
    )
    pipeline.to("cuda")
    print("Step1X-3D geometry ready.")
    _PIPELINE = pipeline
    return pipeline


def handler(job):
    started = time.time()
    job_input = job.get("input") or {}
    image_url = job_input.get("image_url")
    if not image_url:
        return {"error": "image_url is required"}

    seed = int(job_input.get("seed", 42))
    steps = int(job_input.get("num_inference_steps", 50))
    guidance = float(job_input.get("guidance_scale", 7.5))
    octree = int(job_input.get("octree_resolution", 384))

    image_path = None
    try:
        import torch

        pipeline = _load_pipeline()
        load_done = time.time()

        image_path = _download_image(image_url)
        generator = torch.Generator(device="cuda").manual_seed(seed)
        print(
            f"Running Step1X-3D geometry steps={steps} guidance={guidance} "
            f"octree={octree} seed={seed}"
        )
        # RGBA cutouts skip rembg; do not force bria/RMBG.
        out = pipeline(
            image_path,
            guidance_scale=guidance,
            num_inference_steps=steps,
            generator=generator,
            octree_resolution=octree,
            force_remove_background=False,
        )
        mesh = out.mesh[0]
        infer_done = time.time()

        output_dir = Path(DEFAULT_OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        name = f"step1x3d_{int(time.time())}_{seed}_{octree}.glb"
        dest = output_dir / name
        mesh.export(str(dest))
        size = dest.stat().st_size
        verts = int(getattr(mesh, "vertices", []).shape[0]) if hasattr(mesh, "vertices") else 0
        faces = int(getattr(mesh, "faces", []).shape[0]) if hasattr(mesh, "faces") else 0
        print(f"GLB saved: {dest} ({size / 2**20:.1f} MB, {verts} v / {faces} f)")

        result = {
            "model_path": str(dest),
            "size_bytes": size,
            "octree_resolution": octree,
            "num_inference_steps": steps,
            "guidance_scale": guidance,
            "seed": seed,
            "verts": verts,
            "faces": faces,
            "worker_variant": "step1x3d",
            "stage": "geometry",
            "build_sha": os.environ.get("PARADOX_BUILD_SHA", "dev"),
            "timings_s": {
                "load": round(load_done - started, 1),
                "inference": round(infer_done - load_done, 1),
                "export": round(time.time() - infer_done, 1),
                "total": round(time.time() - started, 1),
            },
        }

        model_url = _upload_r2(dest, f"step1x3d/{name}")
        if model_url:
            result["model_url"] = model_url
        elif size <= int(
            os.environ.get("STEP1X3D_BASE64_MAX_BYTES", str(DEFAULT_BASE64_MAX_BYTES))
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
        return {
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc()[-2500:],
        }
    finally:
        if image_path and os.path.exists(image_path):
            os.remove(image_path)


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
