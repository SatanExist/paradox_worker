"""Set idleTimeout on T2 / texture endpoints (warm chaining without workersMin).

Example:
  python scripts/set_endpoint_idle.py --seconds 60
  python scripts/set_endpoint_idle.py --seconds 60 --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runpod_billing import fetch_endpoint_config

REST_BASE = "https://rest.runpod.io/v1"


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="PATCH idleTimeout on generate/texture endpoints.")
    parser.add_argument("--seconds", type=int, default=60, help="idleTimeout seconds (default 60)")
    parser.add_argument("--apply", action="store_true", help="Actually PATCH (otherwise dry-run)")
    args = parser.parse_args()

    api_key = os.getenv("RUNPOD_API_KEY")
    if not api_key:
        print("RUNPOD_API_KEY missing", file=sys.stderr)
        return 1

    endpoints = {
        "T2 generate": os.getenv("RUNPOD_ENDPOINT_ID_TRELLIS2", "").strip(),
        "texture": os.getenv("RUNPOD_ENDPOINT_ID_TEXTURE", "").strip(),
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for name, endpoint_id in endpoints.items():
        if not endpoint_id:
            print(f"[skip] {name}: id not in .env")
            continue
        cfg = fetch_endpoint_config(endpoint_id, api_key)
        current = cfg.get("idleTimeout")
        print(f"{name} {endpoint_id}: idleTimeout={current} -> {args.seconds}")
        if not args.apply:
            continue
        res = requests.patch(
            f"{REST_BASE}/endpoints/{endpoint_id}",
            headers=headers,
            json={"idleTimeout": args.seconds},
            timeout=60,
        )
        if res.status_code >= 400:
            print(f"  PATCH failed HTTP {res.status_code}: {res.text[:200]}", file=sys.stderr)
            return 1
        updated = res.json() if res.content else {}
        print(f"  applied idleTimeout={updated.get('idleTimeout', args.seconds)}")

    if not args.apply:
        print("Dry-run only. Re-run with --apply to PATCH.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
