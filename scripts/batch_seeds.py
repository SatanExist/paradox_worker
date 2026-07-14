"""Run multiple seeds and save GLB files (RO endpoint by default)."""

from __future__ import annotations

import argparse
import base64
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

DEFAULT_ENDPOINT = os.getenv("RUNPOD_ENDPOINT_ID_SECONDARY", "88djlbwtw4sjlv")


def run_job(
    endpoint: str,
    api_key: str,
    image_url: str,
    seed: int,
    out_path: Path,
    *,
    simplify: float = 0.98,
    texture_size: int = 2048,
    poll_s: float = 5.0,
    max_wait_s: float = 20 * 60,
) -> bool:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "input": {
            "image_url": image_url,
            "simplify": simplify,
            "texture_size": texture_size,
            "seed": seed,
        }
    }
    print(f"\n=== {out_path.name} seed={seed} ===", flush=True)
    response = requests.post(
        f"https://api.runpod.ai/v2/{endpoint}/run",
        json=payload,
        headers=headers,
        timeout=60,
    )
    response.raise_for_status()
    job = response.json()
    job_id = job["id"]
    print(f"job {job_id} status={job.get('status')}", flush=True)

    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        status_response = requests.get(
            f"https://api.runpod.ai/v2/{endpoint}/status/{job_id}",
            headers=headers,
            timeout=60,
        )
        status_response.raise_for_status()
        data = status_response.json()
        status = data.get("status")
        if status in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            print(f"final: {status}", flush=True)
            if status != "COMPLETED":
                print(data.get("error") or data, flush=True)
                return False
            output = data.get("output") or {}
            b64 = output.get("model_base64")
            if not isinstance(b64, str) or not b64:
                print("model_base64 missing", flush=True)
                return False
            raw = base64.b64decode(b64)
            out_path.write_bytes(raw)
            handler_ms = (output.get("billing") or {}).get("handler_ms") or {}
            print(f"saved {out_path.resolve()} bytes={len(raw)}", flush=True)
            print(f"handler_ms: {handler_ms}", flush=True)
            return True
        time.sleep(poll_s)

    print("timeout waiting for job", flush=True)
    return False


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Batch RunPod jobs with multiple seeds.")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--image-url", required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 7, 123])
    parser.add_argument("--out-prefix", default="model")
    parser.add_argument("--simplify", type=float, default=0.98)
    parser.add_argument("--texture-size", type=int, default=2048)
    args = parser.parse_args()

    api_key = os.getenv("RUNPOD_API_KEY")
    if not api_key:
        print("RUNPOD_API_KEY not set")
        return 1

    ok_count = 0
    for seed in args.seeds:
        out = Path(f"{args.out_prefix}-seed{seed}.glb")
        if run_job(
            args.endpoint,
            api_key,
            args.image_url,
            seed,
            out,
            simplify=args.simplify,
            texture_size=args.texture_size,
        ):
            ok_count += 1

    print(f"\nDone: {ok_count}/{len(args.seeds)} succeeded")
    return 0 if ok_count == len(args.seeds) else 1


if __name__ == "__main__":
    raise SystemExit(main())
