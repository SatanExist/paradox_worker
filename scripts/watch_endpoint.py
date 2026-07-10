"""Poll RunPod serverless /health for endpoint worker and queue status."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

DEFAULT_ENDPOINTS = {
    "CZ": os.getenv("RUNPOD_ENDPOINT_ID_PRIMARY", "splmm6w2rblqkp"),
    "RO": os.getenv("RUNPOD_ENDPOINT_ID_SECONDARY", "88djlbwtw4sjlv"),
}


def fetch_health(api_key: str, endpoint_id: str) -> dict:
    url = f"https://api.runpod.ai/v2/{endpoint_id}/health"
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def format_snapshot(name: str, endpoint_id: str, payload: dict) -> str:
    jobs = payload.get("jobs", {})
    workers = payload.get("workers", {})
    parts = [
        f"{name} ({endpoint_id})",
        f"queue={jobs.get('inQueue', 0)}",
        f"in_progress={jobs.get('inProgress', 0)}",
        f"running={workers.get('running', 0)}",
        f"ready={workers.get('ready', 0)}",
        f"idle={workers.get('idle', 0)}",
        f"initializing={workers.get('initializing', 0)}",
        f"throttled={workers.get('throttled', 0)}",
    ]
    return " | ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch RunPod endpoint health.")
    parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="Poll interval in seconds (default: 60).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print one snapshot and exit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON per endpoint.",
    )
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("RUNPOD_API_KEY")
    if not api_key:
        print("RUNPOD_API_KEY not found in .env", file=sys.stderr)
        return 1

    last_line = ""

    while True:
        now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        lines: list[str] = [f"[{now}]"]

        for name, endpoint_id in DEFAULT_ENDPOINTS.items():
            if not endpoint_id:
                continue
            try:
                payload = fetch_health(api_key, endpoint_id)
            except Exception as exc:
                lines.append(f"{name} ({endpoint_id}) | ERROR: {exc}")
                continue

            if args.json:
                lines.append(json.dumps({"name": name, "endpoint_id": endpoint_id, **payload}))
            else:
                lines.append(format_snapshot(name, endpoint_id, payload))

        block = "\n".join(lines)
        if block != last_line or args.once:
            print(block, flush=True)
            last_line = block

        if args.once:
            return 0

        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
