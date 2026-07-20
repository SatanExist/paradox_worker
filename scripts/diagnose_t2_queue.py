#!/usr/bin/env python3
"""Live diagnose TRELLIS.2 endpoint queue / workers."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

EID = os.getenv("RUNPOD_ENDPOINT_ID_TRELLIS2", "")
KEY = os.getenv("RUNPOD_API_KEY", "")
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}


def main() -> int:
    if not EID or not KEY:
        print("missing endpoint/key", file=sys.stderr)
        return 1

    print("=== health ===")
    health = requests.get(f"https://api.runpod.ai/v2/{EID}/health", headers=H, timeout=30)
    print(health.status_code, health.text)

    print("\n=== REST config (key fields) ===")
    rest = requests.get(f"https://rest.runpod.io/v1/endpoints/{EID}", headers=H, timeout=30)
    data = rest.json() if rest.ok else {}
    for k in (
        "id",
        "name",
        "workersMin",
        "workersMax",
        "workersStandby",
        "idleTimeout",
        "flashboot",
        "executionTimeoutMs",
        "scalerType",
        "scalerValue",
        "gpuTypeIds",
        "networkVolumeId",
    ):
        print(f"  {k}: {data.get(k)}")

    print("\n=== GraphQL myself.endpoints snippet ===")
    gql = {
        "query": "{ myself { endpoints { id name workersMin workersMax workersStandby idleTimeout } } }"
    }
    g = requests.post("https://api.runpod.io/graphql", headers=H, json=gql, timeout=60)
    print(g.status_code)
    try:
        body = g.json()
        eps = (((body.get("data") or {}).get("myself") or {}).get("endpoints")) or []
        for ep in eps:
            if ep.get("id") == EID:
                print(json.dumps(ep, indent=2))
                break
        else:
            print(g.text[:1500])
    except Exception as exc:
        print(exc, g.text[:800])

    # Submit a tiny probe job and watch 30s
    print("\n=== probe submit (512 / quick) ===")
    payload = {
        "input": {
            "image_url": (
                "https://raw.githubusercontent.com/microsoft/TRELLIS/main/assets/example_image/"
                "typical_misc_monster_chest.png"
            ),
            "pipeline_type": "512",
            "texture_size": 1024,
            "seed": 1,
            "decimation_target": 100000,
            "return_base64": False,
        }
    }
    sub = requests.post(f"https://api.runpod.ai/v2/{EID}/run", headers=H, json=payload, timeout=60)
    print("submit", sub.status_code, sub.text[:300])
    job = sub.json() if sub.ok else {}
    jid = job.get("id")
    if not jid:
        return 1

    for i in range(12):
        time.sleep(5)
        st = requests.get(f"https://api.runpod.ai/v2/{EID}/status/{jid}", headers=H, timeout=30)
        status = (st.json() or {}).get("status")
        h2 = requests.get(f"https://api.runpod.ai/v2/{EID}/health", headers=H, timeout=30).json()
        w = h2.get("workers") or {}
        j = h2.get("jobs") or {}
        print(
            f"t+{(i+1)*5}s status={status} "
            f"ready={w.get('ready')} idle={w.get('idle')} run={w.get('running')} "
            f"throt={w.get('throttled')} inQ={j.get('inQueue')} inP={j.get('inProgress')}"
        )
        if status in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT", "IN_PROGRESS"):
            print("payload keys:", list((st.json() or {}).keys()))
            if status != "IN_PROGRESS":
                break

    # leave cancel if still queued
    final = requests.get(f"https://api.runpod.ai/v2/{EID}/status/{jid}", headers=H, timeout=30).json()
    if final.get("status") == "IN_QUEUE":
        print("still IN_QUEUE -> cancel probe")
        requests.post(f"https://api.runpod.ai/v2/{EID}/cancel/{jid}", headers=H, timeout=30)
    else:
        print("final:", final.get("status"), "workerId=", final.get("workerId"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
