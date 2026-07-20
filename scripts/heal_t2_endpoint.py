#!/usr/bin/env python3
"""Heal TRELLIS.2 endpoint: delete EXITED/ghost workers, optional purge-queue.

Usage:
  python scripts/heal_t2_endpoint.py
  python scripts/heal_t2_endpoint.py --purge
  python scripts/heal_t2_endpoint.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from runpod_queue_watchdog import (  # noqa: E402
    get_health,
    ghost_workers,
    heal_endpoint,
    is_zombie_health,
    list_endpoint_workers,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Heal T2 zombie / ghost workers")
    parser.add_argument(
        "--endpoint",
        default=os.getenv("RUNPOD_ENDPOINT_ID_TRELLIS2", ""),
        help="Endpoint id (default RUNPOD_ENDPOINT_ID_TRELLIS2)",
    )
    parser.add_argument("--purge", action="store_true", help="Also purge job queue")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print health + ghost workers, do not delete",
    )
    args = parser.parse_args()

    api_key = os.getenv("RUNPOD_API_KEY", "")
    if not api_key or not args.endpoint:
        print("Need RUNPOD_API_KEY and endpoint id", file=sys.stderr)
        return 1

    health = get_health(args.endpoint, api_key)
    print("health:", json.dumps(health))
    print("zombie_pattern:", is_zombie_health(health))

    workers = list_endpoint_workers(args.endpoint, api_key)
    print(f"workers listed: {len(workers)}")
    for w in workers:
        print(
            "  ",
            w.get("id") or w.get("podId"),
            "desiredStatus=",
            w.get("desiredStatus"),
            "machineId=",
            w.get("machineId"),
        )
    ghosts = ghost_workers(workers)
    print(f"ghosts: {len(ghosts)}")

    if args.dry_run:
        print("dry-run: no deletes")
        return 0

    report = heal_endpoint(
        args.endpoint,
        api_key,
        purge=args.purge,
        delete_ghosts=True,
    )
    print("deleted:", report.get("deleted"))
    print("delete_errors:", report.get("delete_errors"))
    print("health_after:", json.dumps(report.get("health_after")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
