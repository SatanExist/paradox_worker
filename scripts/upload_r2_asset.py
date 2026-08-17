"""Upload a local file to R2 and print public URL (Track A smoke helper)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from studio_bridge.r2_public import R2NotConfiguredError, upload_public_file


def main() -> int:
    p = argparse.ArgumentParser(description="Upload file to R2 public bucket")
    p.add_argument("path", type=Path, help="Local file to upload")
    p.add_argument("--key", help="R2 object key (default: smoke/<filename>)")
    args = p.parse_args()

    local = args.path.resolve()
    if not local.is_file():
        print(f"Not found: {local}", file=sys.stderr)
        return 1

    load_dotenv(ROOT / ".env")
    object_key = args.key or f"smoke/{local.name}"
    try:
        print(upload_public_file(local, object_key))
    except R2NotConfiguredError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
