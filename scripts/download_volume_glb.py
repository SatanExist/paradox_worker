#!/usr/bin/env python3
"""Download a GLB from RunPod network volume via S3 API (no GPU pod).

Requires in .env (or environment):
  RUNPOD_S3_ACCESS_KEY=user_...
  RUNPOD_S3_SECRET_KEY=rps_...

Optional:
  RUNPOD_S3_SOCKS=socks4://127.0.0.1:10808   # if direct GET stalls

Usage:
  python scripts/download_volume_glb.py
  python scripts/download_volume_glb.py --socks socks4://127.0.0.1:10808
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUCKET = "netu72a8j2"  # paradox-trellis2 network volume ID
DEFAULT_KEY = "outputs/b01c51fc-997a-488b-8788-0ac18c656590-e2.glb"
DEFAULT_OUT = ROOT / "model-v2-full.glb"
ENDPOINT_HOST = "s3api-eu-ro-1.runpod.io"
REGION = "eu-ro-1"


def _clear_env_proxies() -> None:
    for var in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ.pop(var, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"


def _signed_get_headers(access: str, secret: str, url: str) -> dict[str, str]:
    creds = Credentials(access, secret)
    headers = {
        "Host": ENDPOINT_HOST,
        "x-amz-content-sha256": "UNSIGNED-PAYLOAD",
    }
    req = AWSRequest(method="GET", url=url, headers=headers)
    SigV4Auth(creds, "s3", REGION).add_auth(req)
    return dict(req.headers.items())


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Download GLB from RunPod volume S3")
    parser.add_argument("--bucket", default=os.getenv("RUNPOD_VOLUME_S3_BUCKET", DEFAULT_BUCKET))
    parser.add_argument("--key", default=DEFAULT_KEY)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--socks",
        default=os.getenv("RUNPOD_S3_SOCKS", ""),
        help="e.g. socks4://127.0.0.1:10808 (use if direct download stalls)",
    )
    args = parser.parse_args()

    access = os.getenv("RUNPOD_S3_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID")
    secret = os.getenv("RUNPOD_S3_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")
    if not access or not secret:
        print(
            "Missing RUNPOD_S3_ACCESS_KEY / RUNPOD_S3_SECRET_KEY in .env\n"
            "Add them from RunPod → Settings → S3 API Keys\n"
            "(do not paste secrets into chat)",
            file=sys.stderr,
        )
        return 1

    _clear_env_proxies()
    url = f"https://{ENDPOINT_HOST}/{args.bucket}/{args.key}"
    signed = _signed_get_headers(access, secret, url)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists() and args.out.stat().st_size == 0:
        args.out.unlink()

    cmd = [
        "curl.exe",
        "-L",
        "--http1.1",
        "--fail",
        "--show-error",
        "--connect-timeout",
        "30",
        "-m",
        "600",
        "-o",
        str(args.out),
        url,
    ]
    if args.socks:
        # curl --socks4 host:port
        socks = args.socks.replace("socks4://", "").replace("socks5://", "")
        proto = "socks5" if args.socks.startswith("socks5") else "socks4"
        cmd[2:2] = [f"--{proto}", socks]
        print(f"Using {proto} proxy {socks}")
    else:
        cmd[2:2] = ["--noproxy", "*"]

    for k, v in signed.items():
        if k.lower() == "host":
            continue
        cmd.extend(["-H", f"{k}: {v}"])

    print(f"Downloading {url}")
    print(f"  -> {args.out}")
    p = subprocess.run(cmd)
    if p.returncode != 0:
        print(
            f"curl failed (rc={p.returncode}).\n"
            "If it stalls after a few KB, retry with VPN/SOCKS:\n"
            "  python scripts/download_volume_glb.py --socks socks4://127.0.0.1:10808",
            file=sys.stderr,
        )
        return p.returncode

    size = args.out.stat().st_size
    print(f"OK: {args.out} ({size / (1024 * 1024):.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
