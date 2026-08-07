"""Patch T2 serverless template image and print endpoint version."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

KEY = os.environ["RUNPOD_API_KEY"]
EID = os.environ.get("RUNPOD_ENDPOINT_ID_TRELLIS2", "ynzpzjvcbfl656")
TID = os.environ.get("RUNPOD_T2_TEMPLATE_ID", "fclhts02av")
IMAGE = os.environ.get(
    "T2_IMAGE",
    "ghcr.io/satanexist/paradox_worker:trellis2-sha-42d302c",
)


def req(method: str, url: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        return e.code, text


def main() -> int:
    st, ep = req("GET", f"https://rest.runpod.io/v1/endpoints/{EID}?includeTemplate=true")
    print("GET endpoint", st)
    if isinstance(ep, dict):
        print("  version", ep.get("version"), "templateId", ep.get("templateId"))
        t = ep.get("template") or {}
        if isinstance(t, dict):
            print("  old image", t.get("imageName"))

    st, out = req("PATCH", f"https://rest.runpod.io/v1/templates/{TID}", {"imageName": IMAGE})
    print("PATCH template", st)
    if isinstance(out, dict):
        print("  new image", out.get("imageName") or IMAGE)
    else:
        print("  body", str(out)[:500])
        return 1

    st, ep2 = req("GET", f"https://rest.runpod.io/v1/endpoints/{EID}?includeTemplate=true")
    print("GET endpoint after", st)
    if isinstance(ep2, dict):
        print("  version", ep2.get("version"))
        t = ep2.get("template") or {}
        if isinstance(t, dict):
            print("  image", t.get("imageName"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
