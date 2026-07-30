"""Smoke test for MV-Adapter texture RunPod endpoint.

Contract:
  input:  mesh_url, image_url, seed?, remove_bg?, preprocess_mesh?, fast_texture?, return_base64?
  output: model_url | model_base64 | model_path (+ billing)

Requires RUNPOD_ENDPOINT_ID_MVADAPTER env var.

Ops: keep endpoint workersMin=0 (no always-on GPU). This script does NOT bump
workersMin. Expect throttled / cold start before IN_PROGRESS (often 5–15 min).
Only heal on zombie queue (idle/ready + stuck IN_QUEUE), not before every submit.
"""

from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from runpod_billing import estimate_from_status_payload
from runpod_queue_watchdog import run_with_zombie_retries

load_dotenv()

ENDPOINT_ID = os.getenv("RUNPOD_ENDPOINT_ID_MVADAPTER", "").strip()
API_KEY = os.getenv("RUNPOD_API_KEY")

DEFAULT_ZOMBIE_AFTER_S = float(os.getenv("MVADAPTER_ZOMBIE_AFTER_S", "300"))
DEFAULT_ZOMBIE_RETRIES = int(os.getenv("MVADAPTER_ZOMBIE_RETRIES", "2"))
DEFAULT_MAX_WAIT_S = float(os.getenv("MVADAPTER_MAX_WAIT_S", str(45 * 60)))


def sanitize(payload: dict) -> dict:
    out = dict(payload)
    job_out = out.get("output")
    if isinstance(job_out, dict) and isinstance(job_out.get("model_base64"), str):
        job_out = dict(job_out)
        job_out["model_base64"] = f"<omitted base64, len={len(job_out['model_base64'])}>"
        out["output"] = job_out
    return out


def build_input(args: argparse.Namespace) -> dict:
    return {
        "mesh_url": args.mesh_url,
        "image_url": args.image_url,
        "seed": args.seed,
        "remove_bg": args.remove_bg,
        "preprocess_mesh": args.preprocess_mesh,
        "fast_texture": args.fast_texture,
        "return_base64": args.return_base64,
    }


def save_output(final: dict, save_path: Path) -> None:
    output = final.get("output") or {}
    if not isinstance(output, dict):
        raise RuntimeError(f"COMPLETED without output dict: {final}")

    model_url = output.get("model_url")
    if isinstance(model_url, str) and model_url.startswith("http"):
        resp = requests.get(model_url, timeout=120)
        resp.raise_for_status()
        save_path.write_bytes(resp.content)
        print(f"Saved from model_url -> {save_path.resolve()} bytes={save_path.stat().st_size}")
        return

    b64 = output.get("model_base64")
    if isinstance(b64, str) and b64:
        save_path.write_bytes(base64.b64decode(b64))
        print(f"Saved from model_base64 -> {save_path.resolve()} bytes={save_path.stat().st_size}")
        return

    raise RuntimeError(
        "No downloadable artifact in output. "
        f"model_url={model_url!r} r2_error={output.get('r2_error')!r} "
        f"hint={output.get('base64_omitted')!r}."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="RunPod MV-Adapter texture smoke test.")
    parser.add_argument("--mesh-url", required=True, help="Public URL to clay GLB")
    parser.add_argument("--image-url", required=True, help="Public URL to reference image")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--remove-bg", action="store_true", default=True)
    parser.add_argument("--no-remove-bg", dest="remove_bg", action="store_false")
    parser.add_argument("--preprocess-mesh", action="store_true", default=True)
    parser.add_argument("--no-preprocess-mesh", dest="preprocess_mesh", action="store_false")
    parser.add_argument("--fast-texture", action="store_true", default=True)
    parser.add_argument("--no-fast-texture", dest="fast_texture", action="store_false")
    parser.add_argument("--return-base64", action="store_true")
    parser.add_argument("--save", type=Path, default=Path("model-mvadapter.glb"))
    parser.add_argument("--zombie-after", type=float, default=DEFAULT_ZOMBIE_AFTER_S)
    parser.add_argument("--zombie-retries", type=int, default=DEFAULT_ZOMBIE_RETRIES)
    parser.add_argument("--no-zombie-watch", action="store_true")
    args = parser.parse_args()

    if not ENDPOINT_ID:
        print(
            "RUNPOD_ENDPOINT_ID_MVADAPTER is not set.\n"
            "Deploy worker_mvadapter.py via Dockerfile.mvadapter first."
        )
        return 2
    if not API_KEY:
        raise ValueError("RUNPOD_API_KEY not found in .env")

    job_input = build_input(args)
    print(f"Endpoint: {ENDPOINT_ID}")
    print("Ops: workersMin=0 expected — cold/throttled wait before GPU (no always-on billing).")
    print(f"Job input: {job_input}")

    if args.no_zombie_watch:
        from runpod_queue_watchdog import submit_job, wait_for_job

        job_id = submit_job(ENDPOINT_ID, API_KEY, job_input)
        final = wait_for_job(
            ENDPOINT_ID, job_id, API_KEY,
            zombie_after_s=1e9, max_wait_s=DEFAULT_MAX_WAIT_S,
        )
        endpoint_used = ENDPOINT_ID
    else:
        endpoint_used, final = run_with_zombie_retries(
            ENDPOINT_ID, API_KEY, job_input,
            zombie_after_s=args.zombie_after,
            zombie_retries=args.zombie_retries,
            max_wait_s=DEFAULT_MAX_WAIT_S,
            heal=True,
        )

    print(f"Final endpoint: {endpoint_used}")
    print("Final status:")
    print(sanitize(final))

    if final.get("status") != "COMPLETED":
        return 1

    estimate = estimate_from_status_payload(
        final, endpoint_id=endpoint_used, api_key=API_KEY
    )
    print(f"Cost estimate: {estimate['cost_usd_formatted']} USD")
    output = final.get("output") or {}
    if isinstance(output, dict):
        print(
            "delivery=", output.get("delivery"),
            "bytes=", output.get("model_bytes"),
            "url=", output.get("model_url"),
        )
    save_output(final, args.save)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
