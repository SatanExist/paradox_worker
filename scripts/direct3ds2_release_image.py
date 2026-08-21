"""Point the Direct3D-S2 template at a new image tag. Refuses to touch other templates."""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

KEY = os.environ["RUNPOD_API_KEY"].strip()
EID = os.environ["RUNPOD_ENDPOINT_ID_DIRECT3DS2"].strip()
TID = os.environ["RUNPOD_DIRECT3DS2_TEMPLATE_ID"].strip()
OTHER_TEMPLATES = {"fclhts02av", "s15aqi9lxs", "pwcli28kc9"}  # T2, Hi3DGen, Pixal3D


def req(method: str, url: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sha", help="short sha of the image tag, e.g. abcdef1")
    args = parser.parse_args()
    image = f"ghcr.io/satanexist/paradox_worker:direct3ds2-sha-{args.sha}"

    if TID in OTHER_TEMPLATES:
        print(f"REFUSE: {TID} belongs to another worker")
        return 2

    status, endpoint = req(
        "GET", f"https://rest.runpod.io/v1/endpoints/{EID}?includeTemplate=true"
    )
    if status != 200 or not isinstance(endpoint, dict):
        print(f"endpoint read failed: {status} {str(endpoint)[:300]}")
        return 1
    if endpoint.get("templateId") != TID:
        print(f"REFUSE: endpoint uses template {endpoint.get('templateId')}, not {TID}")
        return 2
    template = endpoint.get("template") or {}
    print(f"old image: {template.get('imageName')}")

    status, out = req(
        "PATCH", f"https://rest.runpod.io/v1/templates/{TID}", {"imageName": image}
    )
    if status not in (200, 201):
        print(f"patch failed: {status} {str(out)[:500]}")
        return 1
    print(f"new image: {image}")

    status, after = req("GET", f"https://rest.runpod.io/v1/endpoints/{EID}")
    if isinstance(after, dict):
        print(f"endpoint version: {after.get('version')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
