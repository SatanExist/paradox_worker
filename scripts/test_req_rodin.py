"""Rodin / Hyper3D API: dry-run payload or --auth (key present, no generate).

  python scripts/test_req_rodin.py
  python scripts/test_req_rodin.py --auth
"""

from __future__ import annotations

import argparse
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
from studio_bridge.engines import get_engine  # noqa: E402
from studio_bridge.rodin_client import (  # noqa: E402
    RODIN_PRESETS,
    RodinNotConfiguredError,
    api_key,
)

KNIGHT = (
    "https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/ref_gold_armor.png"
)


def _auth_check() -> int:
    try:
        key = api_key()
    except RodinNotConfiguredError as exc:
        print("auth: not configured —", exc)
        for name in ("RODIN_API_KEY", "HYPER3D_API_KEY"):
            val = os.getenv(name, "").strip()
            print(f"  {name}: {'set' if val else 'empty'} (len {len(val)})")
        return 1
    print("auth: key OK (not printed, len", len(key), ")")
    print("no balance endpoint — Generate later, concurrent=1")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="rodin", choices=sorted(RODIN_PRESETS))
    ap.add_argument("--image-url", default=KNIGHT)
    ap.add_argument(
        "--auth",
        action="store_true",
        help="Check key is set only (no image, no generate spend)",
    )
    args = ap.parse_args()
    if args.auth:
        return _auth_check()

    spec = get_engine(args.engine)
    preset = RODIN_PRESETS[args.engine]
    quote = quote_engine(args.engine)
    print("engine:", spec.id, spec.provider)
    print("docs:  ", spec.docs_url)
    print("tier:  ", preset.tier, "quality_override", preset.quality_override)
    print(
        f"credits: {quote.credits}  cogs ${quote.usd_cogs}  "
        f"user >= ${quote.credits * CREDIT_USD:.2f}"
    )
    print("POST https://api.hyper3d.com/api/v2/rodin")
    print(f"  images={args.image_url}")
    print("  material=PBR  geometry_file_format=glb")
    print("dry-run: not submitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
