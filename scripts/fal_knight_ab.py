"""A/B knight gate for FAL vitrine engines — eyes before the slot is prod.

Default is dry-run: print official FAL payloads for the knight cutout.
Does not submit. Live submit only with --live (needs FAL_KEY; spends money).

Same input as T2 park gate: knight cutout URL.
If a FAL slot is worse than T2 Realistic on the knight, UI role stays "other",
not "quality".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from studio_bridge.credits import CREDIT_USD, quote_engine  # noqa: E402
from studio_bridge.engines import (  # noqa: E402
    KNIGHT_GATE_STATUS,
    build_fal_arguments,
    get_engine,
)
from studio_bridge.fal_client import FalNotConfiguredError, submit  # noqa: E402

KNIGHT_URL = os.getenv(
    "STUDIO_KNIGHT_URL",
    "https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/ref_gold_armor.png",
)

FAL_ENGINES = ("meshy",)
# Off-shelf FAL builders still exist; do not --live them as product slots.
FAL_OFFSHELF = ("hunyuan", "hunyuan_pro", "hitem3d", "rodin", "tripo")

GATE_CHECKLIST = (
    "Same knight cutout URL as T2 Realistic baseline",
    "Eyes: lions / helmet / silhouette vs T2 - not polycount",
    "If worse than T2 on character -> slot stays 'other', never default quality",
    "Hunyuan live only from a non-EU/UK/KR country (geo gate)",
    "Do not mark knightGate=pass in engines.py until eyes sign off",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image-url", default=KNIGHT_URL)
    ap.add_argument("--engine", action="append", dest="engines", help="Repeatable. Default: meshy only")
    ap.add_argument("--live", action="store_true", help="Actually POST queue.fal.run (costs money)")
    ap.add_argument("--country", default="RU", help="ISO country for Hunyuan note")
    args = ap.parse_args()
    engines = tuple(args.engines) if args.engines else FAL_ENGINES

    print("knight URL:", args.image_url)
    print("gate status in catalog:", KNIGHT_GATE_STATUS)
    print("FAL shelf:", ", ".join(FAL_ENGINES))
    print("off-shelf (do not --live as product):", ", ".join(FAL_OFFSHELF))
    print("checklist:")
    for line in GATE_CHECKLIST:
        print(" -", line)
    print()

    for eid in engines:
        spec = get_engine(eid)
        quote = quote_engine(eid)
        payload = build_fal_arguments(eid, image_urls=[args.image_url], seed=1)
        print(f"## {spec.label}  ({spec.fal_model})")
        print(f"docs: {spec.docs_url}")
        print(f"credits: {quote.credits}  cogs ${quote.usd_cogs}  user >= {quote.credits * CREDIT_USD:.2f}")
        print("POST https://queue.fal.run/" + spec.fal_model)
        print("Authorization: Key $FAL_KEY")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if spec.geo_gated:
            print(f"geo: Hunyuan blocked for EU/UK/KR; this run country={args.country}")
        if not args.live:
            print("dry-run: not submitted")
            print()
            continue
        try:
            queued = submit(spec.fal_model or "", payload)
        except FalNotConfiguredError as exc:
            print("LIVE SKIP:", exc)
            print()
            continue
        request_id = queued.get("request_id")
        print("submitted", request_id)
        print("poll: GET https://queue.fal.run/" + spec.fal_model + f"/requests/{request_id}/status")
        print()

    if not args.live:
        print("No GPU/FAL spend. Re-run with --live after FAL_KEY is set.")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
