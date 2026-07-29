"""Fetch RunPod pod details (SSH / ports)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def main() -> int:
    pod_id = sys.argv[1] if len(sys.argv) > 1 else ""
    if not pod_id:
        print("Usage: pod_info.py <pod_id>", file=sys.stderr)
        return 1
    key = os.getenv("RUNPOD_API_KEY", "").strip()
    r = requests.get(
        f"https://rest.runpod.io/v1/pods/{pod_id}",
        headers={"Authorization": f"Bearer {key}"},
        timeout=60,
    )
    print(f"HTTP {r.status_code}")
    try:
        data = r.json()
    except Exception:
        print(r.text[:2000])
        return 1
    print(json.dumps(data, indent=2)[:5000])
    return 0 if r.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
