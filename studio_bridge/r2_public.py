"""Upload a local file to the public R2 bucket (lab + smoke CLI)."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path


class R2NotConfiguredError(RuntimeError):
    """Missing R2_* env vars."""


def r2_settings() -> dict[str, str]:
    required = {
        "R2_ENDPOINT_URL": os.getenv("R2_ENDPOINT_URL", "").strip(),
        "R2_BUCKET": os.getenv("R2_BUCKET", "").strip(),
        "R2_ACCESS_KEY_ID": os.getenv("R2_ACCESS_KEY_ID", "").strip(),
        "R2_SECRET_ACCESS_KEY": os.getenv("R2_SECRET_ACCESS_KEY", "").strip(),
        "R2_PUBLIC_BASE_URL": os.getenv("R2_PUBLIC_BASE_URL", "").strip().rstrip("/"),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise R2NotConfiguredError(f"Missing env: {', '.join(missing)}")
    required["R2_REGION"] = os.getenv("R2_REGION", "auto").strip() or "auto"
    return required


def upload_public_file(local: Path, object_key: str) -> str:
    """Upload ``local`` and return the public https URL."""
    path = Path(local)
    if not path.is_file():
        raise FileNotFoundError(path)

    settings = r2_settings()
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError("boto3 is not installed (pip install boto3)") from exc

    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    client = boto3.client(
        "s3",
        endpoint_url=settings["R2_ENDPOINT_URL"],
        aws_access_key_id=settings["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=settings["R2_SECRET_ACCESS_KEY"],
        region_name=settings["R2_REGION"],
        config=Config(signature_version="s3v4"),
    )
    client.upload_file(
        str(path),
        settings["R2_BUCKET"],
        object_key,
        ExtraArgs={"ContentType": content_type},
    )
    return f"{settings['R2_PUBLIC_BASE_URL']}/{object_key}"
