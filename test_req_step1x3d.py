"""Smoke test for the Step1X-3D geometry RunPod endpoint.

    python test_req_step1x3d.py --image-url "<url>" \
        --save preview_textures/n4_step1x3d_knight.glb
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.request
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

ENDPOINT_ID = os.getenv("RUNPOD_ENDPOINT_ID_STEP1X3D", "").strip()
API_KEY = os.getenv("RUNPOD_API_KEY", "").strip()

POLL_SECONDS = 10
DEFAULT_TIMEOUT = 45 * 60


def build_input(args: argparse.Namespace) -> dict:
    return {
        "image_url": args.image_url,
        "seed": args.seed,
        "num_inference_steps": args.steps,
        "guidance_scale": args.guidance,
        "octree_resolution": args.octree_resolution,
    }


def submit(job_input: dict) -> str:
    resp = requests.post(
        f"https://api.runpod.ai/v2/{ENDPOINT_ID}/run",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"input": job_input},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def poll(job_id: str, timeout: int) -> dict:
    started = time.time()
    last_status = ""
    while time.time() - started < timeout:
        resp = requests.get(
            f"https://api.runpod.ai/v2/{ENDPOINT_ID}/status/{job_id}",
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status", "?")
        if status != last_status:
            print(f"  [{int(time.time() - started):>4}s] {status}")
            last_status = status
        if status in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            return data
        time.sleep(POLL_SECONDS)
    raise TimeoutError(f"job {job_id} still running after {timeout}s")


def save_glb(output: dict, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if output.get("model_url"):
        print(f"  downloading {output['model_url']}")
        req = urllib.request.Request(
            output["model_url"], headers={"User-Agent": "paradox"}
        )
        with urllib.request.urlopen(req, timeout=600) as resp, target.open("wb") as handle:
            handle.write(resp.read())
    elif output.get("model_base64"):
        target.write_bytes(base64.b64decode(output["model_base64"]))
    else:
        print(
            "  no model_url / model_base64 in output; "
            f"read it from the volume: {output.get('model_path')}"
        )
        return
    print(f"  saved {target} ({target.stat().st_size / 2**20:.1f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser(description="RunPod Step1X-3D geometry smoke.")
    parser.add_argument("--image-url", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--guidance", type=float, default=7.5)
    parser.add_argument("--octree-resolution", type=int, default=384)
    parser.add_argument("--save", type=Path)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()

    if not API_KEY:
        raise SystemExit("RUNPOD_API_KEY not found in .env")
    if not ENDPOINT_ID:
        raise SystemExit("Set RUNPOD_ENDPOINT_ID_STEP1X3D in .env")

    job_input = build_input(args)
    print(f"Endpoint: {ENDPOINT_ID}")
    print(f"Input: {json.dumps(job_input, indent=2)}")

    job_id = submit(job_input)
    print(f"Job: {job_id}")
    final = poll(job_id, args.timeout)

    if final.get("status") != "COMPLETED":
        print(json.dumps(final, indent=2)[:4000])
        return 1

    output = final.get("output") or {}
    if output.get("error"):
        print(f"worker error: {output['error']}")
        return 1

    printable = {k: v for k, v in output.items() if k != "model_base64"}
    print(json.dumps(printable, indent=2, ensure_ascii=False))
    if args.save:
        save_glb(output, args.save)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
