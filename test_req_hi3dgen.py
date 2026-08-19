"""Smoke Hi3DGen serverless endpoint (image_url → mesh GLB). Needs ENDPOINT after CI+Release."""

from __future__ import annotations

import argparse
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_IMAGE = "https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/ref_gold_armor.png"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default=os.getenv("RUNPOD_ENDPOINT_ID_HI3DGEN", "").strip())
    ap.add_argument("--image-url", default=DEFAULT_IMAGE)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ss-steps", type=int, default=50)
    ap.add_argument("--slat-steps", type=int, default=6)
    ap.add_argument("--normal-model", default="yoso", help="yoso (Space) or nirne (paper)")
    args = ap.parse_args()
    key = os.getenv("RUNPOD_API_KEY", "").strip()
    if not key or not args.endpoint:
        raise SystemExit("Need RUNPOD_API_KEY and --endpoint / RUNPOD_ENDPOINT_ID_HI3DGEN")
    url = f"https://api.runpod.ai/v2/{args.endpoint}/run"
    payload = {
        "input": {
            "image_url": args.image_url,
            "seed": args.seed,
            "ss_steps": args.ss_steps,
            "slat_steps": args.slat_steps,
            "normal_model": args.normal_model,
        }
    }
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    r.raise_for_status()
    job_id = r.json().get("id")
    print("submitted", job_id, "ss", args.ss_steps, "slat", args.slat_steps, "normal", args.normal_model)
    status_url = f"https://api.runpod.ai/v2/{args.endpoint}/status/{job_id}"
    for _ in range(180):
        time.sleep(10)
        try:
            s = requests.get(status_url, headers={"Authorization": f"Bearer {key}"}, timeout=60)
            body = s.json()
        except requests.RequestException as exc:
            print("poll retry", exc)
            continue
        st = body.get("status")
        print("status", st)
        if st in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            print(body)
            return 0 if st == "COMPLETED" else 1
    print("poll timeout")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
