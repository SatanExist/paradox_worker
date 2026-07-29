"""Check that a public image URL returns bytes and opens as PNG."""

from __future__ import annotations

import argparse
import sys
import urllib.request


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("url")
    args = p.parse_args()

    req = urllib.request.Request(args.url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    print(f"bytes={len(data)} content-type={resp.headers.get('Content-Type')}")

    if len(data) < 1000:
        print("WARN: suspiciously small — worker will fail PIL open", file=sys.stderr)
        return 1

    from PIL import Image
    import io

    Image.open(io.BytesIO(data)).verify()
    print("PIL verify OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
