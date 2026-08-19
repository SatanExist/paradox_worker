"""
RunPod handler: image URL → Hi3DGen (normal bridge) → mesh GLB.

H0 geometry spike. Separate from worker_trellis2.py.
Weights on network volume: /runpod-volume/hi3dgen/weights
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback
import urllib.request
from pathlib import Path

import runpod
from PIL import Image

os.environ.setdefault("SPCONV_ALGO", "native")
os.environ.setdefault("PYTHONUNBUFFERED", "1")
os.environ.setdefault("HF_HOME", "/runpod-volume/huggingface_cache")
os.environ.setdefault("TORCH_HOME", "/runpod-volume/torch_hub")
os.environ.setdefault("ATTN_BACKEND", "xformers")
os.environ.setdefault("SPARSE_ATTN_BACKEND", "xformers")

REPO = Path(os.environ.get("HI3DGEN_REPO", "/app/Stable3DGen"))
VOLUME_WEIGHTS = Path(os.environ.get("HI3DGEN_WEIGHTS", "/runpod-volume/hi3dgen/weights"))
DEFAULT_OUTPUT_DIR = os.environ.get("HI3DGEN_OUTPUT_DIR", "/runpod-volume/outputs")

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/scripts")
sys.path.insert(0, str(REPO))

from hi3dgen_h0_infer import infer_mesh, load_models  # noqa: E402

_pipe = None
_normal = None


def _download_image(url: str) -> str:
    suffix = ".png"
    tail = url.rsplit("/", 1)[-1].split("?")[0]
    if "." in tail:
        suffix = "." + tail.rsplit(".", 1)[-1]
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="h0_img_")
    os.close(fd)
    req = urllib.request.Request(url, headers={"User-Agent": "paradox_worker/hi3dgen"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        Path(path).write_bytes(resp.read())
    return path


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
        print("boto3 missing; skip R2")
        return None
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=os.environ.get("R2_REGION", "auto"),
        config=Config(signature_version="s3v4"),
    )
    content_type = "model/gltf-binary"
    if object_key.lower().endswith(".png"):
        content_type = "image/png"
    elif object_key.lower().endswith(".jpg") or object_key.lower().endswith(".jpeg"):
        content_type = "image/jpeg"
    client.upload_file(
        local_path,
        bucket,
        object_key,
        ExtraArgs={"ContentType": content_type},
    )
    url = f"{public_base}/{object_key}"
    print(f"Uploaded to R2: {url}")
    return url


def load_pipeline() -> None:
    global _pipe, _normal
    if _pipe is not None:
        return
    _pipe, _normal = load_models(REPO, VOLUME_WEIGHTS)


def handler(job: dict) -> dict:
    job_input = job.get("input", {}) or {}
    image_url = str(job_input.get("image_url") or "").strip()
    if not image_url:
        return {"error": "Missing image_url"}
    seed = int(job_input.get("seed", 42))
    ss_steps = int(job_input.get("ss_steps", 50))
    slat_steps = int(job_input.get("slat_steps", 6))
    job_id = str(job.get("id") or f"h0-{int(time.time())}")
    img_path = None
    try:
        t0 = time.perf_counter()
        load_pipeline()
        img_path = _download_image(image_url)
        os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
        out_path = Path(DEFAULT_OUTPUT_DIR) / f"{job_id}.glb"
        nrm_path = Path(DEFAULT_OUTPUT_DIR) / f"{job_id}_normal.png"
        infer_mesh(
            _pipe,
            _normal,
            Image.open(img_path),
            out_path,
            seed=seed,
            normal_out=nrm_path,
            ss_steps=ss_steps,
            slat_steps=slat_steps,
        )
        size = out_path.stat().st_size
        model_url = _upload_r2(str(out_path), f"hi3dgen/{job_id}.glb")
        normal_url = None
        if nrm_path.is_file():
            normal_url = _upload_r2(str(nrm_path), f"hi3dgen/{job_id}_normal.png")
        extract = os.environ.get("HI3DGEN_MESH_EXTRACT", "flexicubes")
        return {
            "job_id": job_id,
            "glb_path": str(out_path),
            "glb_bytes": size,
            "model_url": model_url,
            "normal_url": normal_url,
            "mesh_extract": extract,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "seed": seed,
            "ss_steps": ss_steps,
            "slat_steps": slat_steps,
            "variant": "hi3dgen",
        }
    except Exception as exc:
        tb = traceback.format_exc()
        print(f"HI3DGEN ERROR: {exc}")
        print(tb)
        return {"error": str(exc), "traceback": tb}
    finally:
        if img_path:
            try:
                os.remove(img_path)
            except OSError:
                pass


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
