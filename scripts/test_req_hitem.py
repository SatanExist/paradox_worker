"""Hitem Open Platform: dry-run payload or --auth (token + balance, no generate).

  python scripts/test_req_hitem.py
  python scripts/test_req_hitem.py --auth
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
from studio_bridge.hitem_client import (  # noqa: E402
    HITEM_PRESETS,
    HitemHttpError,
    HitemNotConfiguredError,
    access_token,
    query_balance,
    view_plan,
)

KNIGHT = (
    "https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/ref_gold_armor.png"
)


def _auth_check() -> int:
    try:
        token = access_token()
    except HitemNotConfiguredError as exc:
        print("auth: not configured —", exc)
        for name in ("HITEM_CLIENT_ID", "HITEM_CLIENT_SECRET", "HITEM_API_KEY"):
            val = os.getenv(name, "").strip()
            print(f"  {name}: {'set' if val else 'empty'} (len {len(val)})")
        return 1
    except HitemHttpError as exc:
        print("auth: FAIL HTTP", exc.status)
        print("hint: Create Key on platform.hi3d.ai; ID+SECRET, never paste keys here")
        return 1
    if not token:
        print("auth: FAIL empty token")
        return 1
    print("auth: token OK (not printed)")
    try:
        bal = query_balance()
    except HitemHttpError as exc:
        print("balance: FAIL HTTP", exc.status)
        return 1
    raw = bal.get("totalBalance")
    print("balance: totalBalance =", raw)
    try:
        credits = float(raw)
    except (TypeError, ValueError):
        credits = None
    if credits is not None:
        print(f"  ~${credits * 0.02:.2f} at $0.02/cr; v2.1 fast needs 25 cr")
        if credits < 25:
            print("  pack is below one fast gen — buy/activate Resource Package")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="hitem3d", choices=sorted(HITEM_PRESETS))
    ap.add_argument("--image-url", default=KNIGHT)
    ap.add_argument(
        "--auth",
        action="store_true",
        help="Call token + balance only (no image, no generate spend)",
    )
    args = ap.parse_args()
    if args.auth:
        return _auth_check()

    spec = get_engine(args.engine)
    preset = HITEM_PRESETS[args.engine]
    quote = quote_engine(args.engine)
    bit, ordered = view_plan(image_urls=[args.image_url])
    print("engine:", spec.id, spec.provider)
    print("docs:  ", spec.docs_url)
    print("model: ", preset.model, preset.resolution, "faces", preset.face)
    print(
        f"credits: {quote.credits}  cogs ${quote.usd_cogs}  "
        f"user >= ${quote.credits * CREDIT_USD:.2f}"
    )
    print("POST https://api.hitem3d.ai/open-api/v1/submit-task")
    print("  request_type=3  pbr=1  format=2 (glb)")
    print("  images field:" if bit is None else f"  multi_images_bit={bit}")
    for slot, url in ordered:
        print(f"    {slot}: {url}")
    print("dry-run: not submitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
