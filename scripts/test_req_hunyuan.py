"""Hunyuan / Tencent HY 3D: dry-run quote or --auth (keys present).

  python scripts/test_req_hunyuan.py
  python scripts/test_req_hunyuan.py --lane express
  python scripts/test_req_hunyuan.py --lane lowpoly --pbr
  python scripts/test_req_hunyuan.py --auth
  python scripts/test_req_hunyuan.py --live --lane express --image-url "<url>"
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from studio_bridge.credits import CREDIT_USD, quote_engine  # noqa: E402
from studio_bridge.engines import get_engine  # noqa: E402
from studio_bridge.hunyuan_client import (  # noqa: E402
    HunyuanNotConfiguredError,
    credentials,
    map_status,
    pick_glb,
    query_job,
    resolve_options,
    submit_job,
)

KNIGHT = (
    "https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/ref_gold_armor.png"
)


def _auth_check() -> int:
    try:
        sid, sk = credentials()
    except HunyuanNotConfiguredError as exc:
        print("auth: not configured —", exc)
        for name in ("TENCENTCLOUD_SECRET_ID", "TENCENTCLOUD_SECRET_KEY"):
            val = os.getenv(name, "").strip()
            print(f"  {name}: {'set' if val else 'empty'} (len {len(val)})")
        return 1
    print("auth: SecretId/SecretKey OK (not printed)")
    print(
        f"  id_len={len(sid)} key_len={len(sk)} "
        f"region={os.getenv('TENCENTCLOUD_REGION') or 'ap-singapore'}"
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image-url", default=KNIGHT)
    ap.add_argument(
        "--lane",
        default="pro",
        choices=("pro", "express", "lowpoly"),
        help="Pro 3.1 / Express Rapid / LowPoly Model 3.0",
    )
    ap.add_argument(
        "--generate-type",
        default="Normal",
        choices=("Normal", "Geometry", "Sketch", "LowPoly"),
    )
    ap.add_argument("--pbr", action="store_true", help="EnablePBR (+10 vendor cr)")
    ap.add_argument("--face-count", type=int, default=500_000)
    ap.add_argument("--auth", action="store_true")
    ap.add_argument(
        "--live",
        action="store_true",
        help="Submit a real job (spends free/package credits)",
    )
    args = ap.parse_args()
    if args.auth:
        return _auth_check()

    opts = {
        "lane": args.lane,
        "generateType": args.generate_type,
        "enablePbr": bool(args.pbr),
        "faceCount": args.face_count,
    }
    knobs = resolve_options(opts)
    spec = get_engine("hunyuan")
    quote = quote_engine("hunyuan", hunyuan_options=opts)
    print("engine:", spec.id, spec.provider, spec.label)
    print("docs:  ", spec.docs_url)
    print("opts:  ", knobs)
    print(
        f"credits: {quote.credits} user  vendor={quote.vendor_credits}  "
        f"cogs ${quote.usd_cogs}  user>=${quote.credits * CREDIT_USD:.2f}"
    )
    print("breakdown:", " · ".join(quote.breakdown))
    if not args.live:
        print("dry-run only (pass --live to submit)")
        return 0

    queued = submit_job(image_url=args.image_url, options=opts)
    job_id = queued["jobId"]
    api = queued.get("api") or knobs["api"]
    print("submitted JobId:", job_id, "api:", api)
    # Pro/LowPoly often 7–15+ min; Express usually faster.
    # 240 * 5s ≈ 20 min wall clock before client gives up.
    poll_every_sec = 5
    max_polls = 240
    for i in range(max_polls):
        time.sleep(poll_every_sec)
        data = query_job(job_id, api=api)
        status = map_status(str(data.get("Status") or ""))
        print(f"  [{i}] {data.get('Status')} → {status}")
        if status == "failed":
            print("error:", data.get("ErrorCode"), data.get("ErrorMessage"))
            return 1
        if status == "completed":
            glb, poster = pick_glb(data.get("ResultFile3Ds"))
            print("glb:", glb)
            print("poster:", poster)
            return 0 if glb else 1
    mins = (max_polls * poll_every_sec) // 60
    print(f"timeout waiting for DONE after ~{mins} min (JobId still valid ~24h)")
    print(f"  re-check: query_job({job_id!r}, api={api!r})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
