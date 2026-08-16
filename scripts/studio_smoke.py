#!/usr/bin/env python3
"""Smoke test for studio_bridge without HTTP server."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from studio_bridge.service import create_job, get_job  # noqa: E402
from studio_bridge.tiers import DEFAULT_MULTI_IMAGE_MODE  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Studio bridge smoke test")
    parser.add_argument("--mode", choices=["image", "text"], default="image")
    parser.add_argument(
        "--tier",
        default="medium",
        help="low|medium|high|realistic (aliases: preview, quality, ultra)",
    )
    parser.add_argument(
        "--image-url",
        default=(
            "https://raw.githubusercontent.com/microsoft/TRELLIS/main/assets/"
            "example_image/typical_misc_monster_chest.png"
        ),
    )
    parser.add_argument(
        "--image-urls",
        nargs="+",
        default=None,
        help="Multi-view public URLs (2–4). Overrides --image-url when set.",
    )
    parser.add_argument(
        "--multi-image-mode",
        choices=["stochastic", "multidiffusion"],
        default=DEFAULT_MULTI_IMAGE_MODE,
    )
    parser.add_argument("--soft-input", action="store_true")
    parser.add_argument("--prompt", default="fantasy treasure chest with gold corners")
    parser.add_argument("--poll", type=float, default=5.0)
    parser.add_argument("--max-wait", type=float, default=20 * 60)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build payload only (print create_job args / no RunPod submit).",
    )
    args = parser.parse_args()

    if args.dry_run:
        from studio_bridge.tiers import build_runpod_input, preset_tier

        try:
            cfg = preset_tier(args.tier, endpoint_id="dry")
        except ValueError as exc:
            print(exc)
            return 1
        urls = args.image_urls
        payload = build_runpod_input(
            cfg,
            image_url=None if urls else args.image_url,
            image_urls=urls,
            multi_image_mode=args.multi_image_mode,
            soft_input=True if args.soft_input else None,
        )
        print("dry-run payload:", json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    created = create_job(
        mode=args.mode,
        tier=args.tier,
        image_url=args.image_url if args.mode == "image" and not args.image_urls else None,
        image_urls=args.image_urls if args.mode == "image" else None,
        multi_image_mode=args.multi_image_mode,
        soft_input=args.soft_input,
        prompt=args.prompt if args.mode == "text" else None,
    )
    print("created:", json.dumps(created, ensure_ascii=False, indent=2))

    job_id = created["jobId"]
    deadline = time.time() + args.max_wait
    while time.time() < deadline:
        status = get_job(job_id, tier=args.tier)
        print("status:", status["status"], "modelUrl:", status.get("modelUrl"))
        if status["status"] in ("ready", "failed"):
            print(json.dumps(status, ensure_ascii=False, indent=2))
            return 0 if status["status"] == "ready" else 1
        time.sleep(args.poll)

    print("timeout")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
