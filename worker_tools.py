"""
RunPod handler: tools on a finished model (print prep, …) → new GLB in R2.

CPU only, no weights. The lab submits {operation, model_url, params, output_key};
the work itself lives in studio_bridge/tools_ops.py so the lab can run it locally too.
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

sys.path.insert(0, "/app")

from studio_bridge.r2_public import upload_public_file  # noqa: E402
from studio_bridge.tools_ops import OPERATIONS, run_operation  # noqa: E402

MAX_INPUT_BYTES = 200 * 1024 * 1024


def _download(url: str) -> Path:
    if not url.startswith("https://"):
        raise ValueError("model_url must be https")
    fd, path = tempfile.mkstemp(suffix=".glb", prefix="tools_in_")
    os.close(fd)
    req = urllib.request.Request(url, headers={"User-Agent": "paradox_worker/tools"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("model is too large")
    Path(path).write_bytes(data)
    return Path(path)


def handler(job: dict) -> dict:
    job_input = job.get("input", {}) or {}
    operation = str(job_input.get("operation") or "").strip()
    model_url = str(job_input.get("model_url") or "").strip()
    output_key = str(job_input.get("output_key") or "").strip()
    params = job_input.get("params") if isinstance(job_input.get("params"), dict) else {}
    if operation not in OPERATIONS:
        return {"error": f"unknown operation: {operation}"}
    if not model_url or not output_key.startswith("tools/") or ".." in output_key:
        return {"error": "Missing model_url or bad output_key"}

    in_path = out_path = None
    try:
        t0 = time.perf_counter()
        in_path = _download(model_url)
        out_path, report = run_operation(operation, in_path, params)
        url = upload_public_file(out_path, output_key)
        return {
            "model_url": url,
            "report": report,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "variant": "tools",
        }
    except Exception as exc:
        tb = traceback.format_exc()
        print(f"TOOLS ERROR: {exc}")
        print(tb)
        return {"error": str(exc)[:500], "traceback": tb}
    finally:
        for path in (in_path, out_path):
            if path is not None:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
