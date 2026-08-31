"""Tripo Developers API: dry-run payload or --auth (balance, no generate).

  python scripts/test_req_tripo.py
  python scripts/test_req_tripo.py --auth
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
from studio_bridge.tripo_client import (  # noqa: E402
    TRIPO_PRESETS,
    TripoHttpError,
    TripoNotConfiguredError,
    query_balance,
)

KNIGHT = (
    "https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/ref_gold_armor.png"
)


def _auth_check() -> int:
    try:
        bal = query_balance()
    except TripoNotConfiguredError as exc:
        print("auth: not configured —", exc)
        val = os.getenv("TRIPO_API_KEY", "").strip()
        print(f"  TRIPO_API_KEY: {'set' if val else 'empty'} (len {len(val)})")
        return 1
    except TripoHttpError as exc:
        print("auth: FAIL HTTP", exc.status)
        return 1
    print("auth: key OK (not printed)")
    print("balance:", bal.get("balance"), "frozen:", bal.get("frozen"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="tripo", choices=sorted(TRIPO_PRESETS))
    ap.add_argument("--image-url", default=KNIGHT)
    ap.add_argument(
        "--auth",
        action="store_true",
        help="Call account/balance only (no image, no generate spend)",
    )
    args = ap.parse_args()
    if args.auth:
        return _auth_check()

    spec = get_engine(args.engine)
    preset = TRIPO_PRESETS[args.engine]
    quote = quote_engine(args.engine)
    print("engine:", spec.id, spec.provider)
    print("docs:  ", spec.docs_url)
    print("model: ", preset.model, "texture_quality", preset.texture_quality)
    print(
        f"credits: {quote.credits}  cogs ${quote.usd_cogs}  "
        f"user >= ${quote.credits * CREDIT_USD:.2f}"
    )
    print("POST https://openapi.tripo3d.ai/v3/generation/image-to-model")
    print(f"  input={args.image_url}")
    print("  texture=true  pbr=true")
    print("dry-run: not submitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
