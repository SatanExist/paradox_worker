"""Upload a local file to R2 and print public URL (Track A smoke helper)."""

from __future__ import annotations

import argparse
import mimetypes
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    p = argparse.ArgumentParser(description="Upload file to R2 public bucket")
    p.add_argument("path", type=Path, help="Local file to upload")
    p.add_argument("--key", help="R2 object key (default: smoke/<filename>)")
    args = p.parse_args()

    local = args.path.resolve()
    if not local.is_file():
        print(f"Not found: {local}", file=sys.stderr)
        return 1

    _load_env_file(ROOT / ".env")
    endpoint = os.getenv("R2_ENDPOINT_URL", "").strip()
    bucket = os.getenv("R2_BUCKET", "").strip()
    access_key = os.getenv("R2_ACCESS_KEY_ID", "").strip()
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
    public_base = os.getenv("R2_PUBLIC_BASE_URL", "").strip().rstrip("/")
    required = {
        "R2_ENDPOINT_URL": endpoint,
        "R2_BUCKET": bucket,
        "R2_ACCESS_KEY_ID": access_key,
        "R2_SECRET_ACCESS_KEY": secret_key,
        "R2_PUBLIC_BASE_URL": public_base,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"Missing env: {', '.join(missing)}", file=sys.stderr)
        return 1

    object_key = args.key or f"smoke/{local.name}"
    content_type = mimetypes.guess_type(local.name)[0] or "application/octet-stream"

    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        print("boto3 not installed", file=sys.stderr)
        return 1

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=os.getenv("R2_REGION", "auto"),
        config=Config(signature_version="s3v4"),
    )
    client.upload_file(
        str(local),
        bucket,
        object_key,
        ExtraArgs={"ContentType": content_type},
    )
    print(f"{public_base}/{object_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
