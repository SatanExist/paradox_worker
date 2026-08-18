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
    args = ap.parse_args()
    key = os.getenv("RUNPOD_API_KEY", "").strip()
    if not key or not args.endpoint:
        raise SystemExit("Need RUNPOD_API_KEY and --endpoint / RUNPOD_ENDPOINT_ID_HI3DGEN")
    url = f"https://api.runpod.ai/v2/{args.endpoint}/run"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"input": {"image_url": args.image_url, "seed": args.seed}},
        timeout=60,
    )
    r.raise_for_status()
    job_id = r.json().get("id")
    print("submitted", job_id)
    status_url = f"https://api.runpod.ai/v2/{args.endpoint}/status/{job_id}"
    for _ in range(180):
        time.sleep(10)
        s = requests.get(status_url, headers={"Authorization": f"Bearer {key}"}, timeout=60)
        body = s.json()
        st = body.get("status")
        print("status", st)
        if st in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            print(body)
            return 0 if st == "COMPLETED" else 1
    print("poll timeout")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
