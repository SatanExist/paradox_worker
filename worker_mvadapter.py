"""
RunPod handler: clay mesh + reference image → MV-Adapter textured GLB.

MV-Adapter texture tier (wow quality). Separate from worker_texture.py (TRELLIS.2 paint).
Deploy via Dockerfile.mvadapter on a dedicated endpoint (torch 2.4.1, CUDA 12.4).

Upstream: https://github.com/huanngzh/MV-Adapter — scripts.texture_i2tex
"""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from pathlib import Path

import runpod

MVADAPTER_DIR = Path(os.environ.get("MVADAPTER_DIR", "/app/MV-Adapter"))

DEFAULT_SEED = 1
DEFAULT_OUTPUT_DIR = "/runpod-volume/outputs"
DEFAULT_BASE64_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_TEXTURE_TIMEOUT_S = int(os.environ.get("MVADAPTER_TEXTURE_TIMEOUT_S", "1800"))
DEFAULT_FAST_TEXTURE = os.environ.get("MVADAPTER_FAST_TEXTURE", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)


def _coerce_int(value, default: int, *, min_val: int, max_val: int) -> int:
    if value is None:
        return default
    try:
        out = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_val, min(max_val, out))


def _coerce_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def _download(url: str, suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=300) as resp, open(path, "wb") as out:
        shutil.copyfileobj(resp, out)
    return path


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _upload_r2(local_path: str, object_key: str) -> tuple[str | None, str | None]:
    """Upload to R2. Returns (public_url, skip_or_error_reason)."""
    endpoint = os.environ.get("R2_ENDPOINT_URL", "").strip()
    bucket = os.environ.get("R2_BUCKET", "").strip()
    access_key = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
    public_base = os.environ.get("R2_PUBLIC_BASE_URL", "").strip().rstrip("/")
    required = {
        "R2_ENDPOINT_URL": endpoint,
        "R2_BUCKET": bucket,
        "R2_ACCESS_KEY_ID": access_key,
        "R2_SECRET_ACCESS_KEY": secret_key,
        "R2_PUBLIC_BASE_URL": public_base,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        reason = f"missing env: {', '.join(missing)}"
        print(f"R2 skip: {reason}")
        return None, reason

    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        reason = "boto3 not installed"
        print(f"R2 skip: {reason}")
        return None, reason

    try:
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
        return url, None
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        print(f"R2 upload failed: {reason}")
        return None, reason


def _deliver_glb(temp_glb_path: str, job_id: str, *, return_base64: bool) -> dict:
    output_dir = Path(os.environ.get("MVADAPTER_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in job_id) or "job"
    dest = output_dir / f"{safe_id}-mvtex.glb"
    shutil.copy2(temp_glb_path, dest)

    size = dest.stat().st_size
    sha = _sha256_file(str(dest))
    object_key = f"mvadapter/{safe_id}.glb"
    model_url, r2_error = _upload_r2(str(dest), object_key)

    delivery = {
        "model_path": str(dest),
        "model_bytes": size,
        "model_sha256": sha,
        "model_url": model_url,
        "delivery": "r2" if model_url else "volume",
        "worker_variant": "mvadapter",
    }
    if r2_error:
        delivery["r2_error"] = r2_error

    max_b64 = int(os.environ.get("MVADAPTER_BASE64_MAX_BYTES", str(DEFAULT_BASE64_MAX_BYTES)))
    include_b64 = return_base64 or (model_url is None and size <= max_b64)
    if include_b64 and size <= max_b64:
        with open(dest, "rb") as f:
            delivery["model_base64"] = base64.b64encode(f.read()).decode("utf-8")
    elif return_base64 and size > max_b64:
        delivery["base64_omitted"] = (
            f"GLB is {size} bytes; exceeds base64 cap. Use model_url or model_path."
        )

    return delivery


def _run_texture_i2tex(
    image_path: str,
    mesh_path: str,
    save_dir: str,
    save_name: str,
    *,
    seed: int,
    remove_bg: bool,
    preprocess_mesh: bool,
    fast_texture: bool,
) -> Path:
    """Run MV-Adapter texture_i2tex as subprocess and return the shaded GLB path."""
    module = (
        "scripts.mvadapter_serverless_i2tex"
        if fast_texture
        else "scripts.texture_i2tex"
    )
    cmd = [
        sys.executable, "-m", module,
        "--image", image_path,
        "--mesh", mesh_path,
        "--save_dir", save_dir,
        "--save_name", save_name,
        "--seed", str(seed),
    ]
    if remove_bg:
        cmd.append("--remove_bg")
    if preprocess_mesh:
        cmd.append("--preprocess_mesh")

    print(f"texture_i2tex cmd: {' '.join(cmd)} (fast_texture={fast_texture})")
    # Do not use capture_output=True: texture_i2tex tqdm can fill the pipe
    # buffer and block until the subprocess timeout (looks like a 30min hang).
    log_path = Path(save_dir) / f"{save_name}_texture_i2tex.log"
    vol = Path(os.environ.get("MVADAPTER_VOLUME_ROOT", "/runpod-volume"))
    torch_cache = vol / "torch_cache"
    torch_ext = vol / "torch_extensions"
    hf_home = vol / "huggingface_cache"
    for d in (torch_cache, torch_ext, hf_home):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"volume cache mkdir skip {d}: {exc}")

    child_env = os.environ.copy()
    child_env.setdefault("PYTHONUNBUFFERED", "1")
    # Keep HF/tqdm progress visible in the log file (do NOT set TQDM_DISABLE).
    child_env.setdefault("HF_HOME", str(hf_home))
    child_env.setdefault("TORCH_HOME", str(torch_cache))
    child_env.setdefault("TORCH_EXTENSIONS_DIR", str(torch_ext))
    print(
        f"texture_i2tex caches: HF_HOME={child_env.get('HF_HOME')} "
        f"TORCH_HOME={child_env.get('TORCH_HOME')} "
        f"TORCH_EXTENSIONS_DIR={child_env.get('TORCH_EXTENSIONS_DIR')}"
    )

    def _dump_log_tail(prefix: str) -> str:
        if not log_path.is_file():
            print(f"{prefix}: log file missing ({log_path})")
            return ""
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-8000:]
        if tail:
            print(f"{prefix} ({log_path}, {log_path.stat().st_size} bytes):\n{tail}")
        else:
            print(f"{prefix}: log file empty ({log_path})")
        return tail

    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            result = subprocess.run(
                cmd,
                cwd=str(MVADAPTER_DIR),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                timeout=DEFAULT_TEXTURE_TIMEOUT_S,
                env=child_env,
            )
    except subprocess.TimeoutExpired as exc:
        log_tail = _dump_log_tail("texture_i2tex TIMEOUT log tail")
        raise TimeoutError(
            f"texture_i2tex timed out after {DEFAULT_TEXTURE_TIMEOUT_S}s; "
            f"log_tail={log_tail[-1500:]!r}"
        ) from exc

    log_tail = _dump_log_tail("texture_i2tex log tail")
    if result.returncode != 0:
        raise RuntimeError(
            f"texture_i2tex exited {result.returncode}: {log_tail[-2000:]}"
        )

    shaded = Path(save_dir) / f"{save_name}_shaded.glb"
    if not shaded.is_file():
        candidates = list(Path(save_dir).glob(f"{save_name}*.glb"))
        if candidates:
            shaded = candidates[0]
        else:
            raise FileNotFoundError(
                f"No GLB output found in {save_dir} for {save_name}"
            )
    return shaded


def handler(job):
    job_input = job.get("input", {})
    mesh_url = job_input.get("mesh_url") or job_input.get("glb_url")
    image_url = job_input.get("image_url")
    job_id = str(job.get("id") or f"mv-{int(time.time())}")
    return_base64 = _coerce_bool(job_input.get("return_base64"), False)

    seed = _coerce_int(job_input.get("seed"), DEFAULT_SEED, min_val=0, max_val=2**31 - 1)
    remove_bg = _coerce_bool(job_input.get("remove_bg"), True)
    preprocess_mesh = _coerce_bool(job_input.get("preprocess_mesh"), True)
    fast_texture = _coerce_bool(job_input.get("fast_texture"), DEFAULT_FAST_TEXTURE)

    if not mesh_url:
        return {"error": "Missing mesh_url (clay GLB) in job input"}
    if not image_url:
        return {"error": "Missing image_url (reference texture image) in job input"}

    mesh_path = None
    img_path = None
    tmp_dir = None

    try:
        t0 = time.perf_counter()
        handler_ms = {}

        build_sha = os.environ.get("PARADOX_BUILD_SHA", "unknown")
        print(f"paradox_worker mvadapter build: {build_sha}")
        print(f"mesh_url={mesh_url}")
        print(f"image_url={image_url}")
        print(f"seed={seed}, remove_bg={remove_bg}, preprocess_mesh={preprocess_mesh}, fast_texture={fast_texture}")

        t_dl = time.perf_counter()
        mesh_path = _download(str(mesh_url), ".glb")
        img_path = _download(str(image_url), ".png")
        handler_ms["download_ms"] = int((time.perf_counter() - t_dl) * 1000)

        tmp_dir = tempfile.mkdtemp(prefix="mvadapter_")
        save_name = f"job_{job_id}"

        t_infer = time.perf_counter()
        shaded_glb = _run_texture_i2tex(
            img_path,
            mesh_path,
            tmp_dir,
            save_name,
            seed=seed,
            remove_bg=remove_bg,
            preprocess_mesh=preprocess_mesh,
            fast_texture=fast_texture,
        )
        handler_ms["inference_ms"] = int((time.perf_counter() - t_infer) * 1000)

        t_del = time.perf_counter()
        delivery = _deliver_glb(str(shaded_glb), job_id, return_base64=return_base64)
        handler_ms["deliver_ms"] = int((time.perf_counter() - t_del) * 1000)
        handler_ms["total_ms"] = int((time.perf_counter() - t0) * 1000)

        return {
            **delivery,
            "generation": {
                "task_type": "mvadapter_texture",
                "seed": seed,
                "remove_bg": remove_bg,
                "preprocess_mesh": preprocess_mesh,
                "fast_texture": fast_texture,
            },
            "billing": {
                "worker_variant": "mvadapter",
                "handler_ms": handler_ms,
                "gpu_type": None,
            },
        }
    except Exception as exc:
        traceback.print_exc()
        return {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        for p in (mesh_path, img_path):
            if p and os.path.isfile(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        if tmp_dir and os.path.isdir(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)


runpod.serverless.start({"handler": handler})
