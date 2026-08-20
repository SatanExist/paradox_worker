"""Create the Pixal3D serverless template + endpoint on RunPod.

Idempotent enough to re-run: it refuses if a template or endpoint with the
same name already exists, so a second run cannot silently fork the park.

R2 credentials and the GHCR registry auth are copied from the Hi3DGen
template rather than read from .env, so no secret is printed or retyped.
"""
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

API = "https://rest.runpod.io/v1"
KEY = os.environ["RUNPOD_API_KEY"].strip()

# Source of the shared bits: same GHCR repo, same R2 bucket.
DONOR_TEMPLATE = os.getenv("RUNPOD_HI3DGEN_TEMPLATE_ID", "s15aqi9lxs").strip()
# paradox-trellis2, EU-RO-1, 80 GB: ~50 GB free and already holds the shared
# DINOv3 weights and HF cache that Pixal3D reuses.
VOLUME_ID = os.getenv("RUNPOD_T2_VOLUME_ID", "netu72a8j2").strip()

NAME = "paradox-pixal3d"
IMAGE = os.getenv(
    "PIXAL3D_IMAGE", "ghcr.io/satanexist/paradox_worker:pixal3d-sha-376f791"
)
# Priority order: 24 GB first for the 1024 cascade, 48 GB behind it so a 1536
# run has somewhere to land. REST wants full display names, not group ids.
GPU_TYPE_IDS = [
    "NVIDIA GeForce RTX 4090",
    "NVIDIA RTX A6000",
    "NVIDIA A40",
    "NVIDIA L40S",
]


def call(method: str, path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="actually create")
    parser.add_argument(
        "--template-id", help="reuse an already created template instead of a new one"
    )
    args = parser.parse_args()

    status, donor = call("GET", f"/templates/{DONOR_TEMPLATE}")
    if status != 200 or not isinstance(donor, dict):
        print(f"donor template read failed: {status} {str(donor)[:300]}")
        return 1
    donor_env = donor.get("env") or {}
    shared = {k: v for k, v in donor_env.items() if k.startswith("R2_")}
    if not shared:
        print("donor template has no R2_* env; refusing to create a half-configured worker")
        return 1

    env = {
        **shared,
        "PIXAL3D_OUTPUT_DIR": "/runpod-volume/outputs",
        "TORCH_HOME": "/runpod-volume/torch_hub",
    }

    template_body = {
        "name": NAME,
        "imageName": IMAGE,
        "containerDiskInGb": 40,
        "containerRegistryAuthId": donor.get("containerRegistryAuthId"),
        "isServerless": True,
        "volumeMountPath": "/workspace",
        "readme": "Pixal3D N2 worker: pixel-aligned image-to-3D on the TRELLIS.2 backbone.",
        "env": env,
    }
    endpoint_body = {
        "name": NAME,
        "computeType": "GPU",
        "gpuTypeIds": GPU_TYPE_IDS,
        "gpuCount": 1,
        "workersMin": 0,
        "workersMax": 1,
        "idleTimeout": 5,
        "networkVolumeId": VOLUME_ID,
        "executionTimeoutMs": 30 * 60 * 1000,
    }

    print(f"template: {NAME} <- {IMAGE}")
    print(f"  env keys: {sorted(env)}")
    print(f"endpoint: {NAME} vol={VOLUME_ID} gpu={GPU_TYPE_IDS} min=0 max=1")
    if not args.apply:
        print("dry run; pass --apply to create")
        return 0

    status, existing = call("GET", "/endpoints")
    if status == 200 and isinstance(existing, list):
        if any(e.get("name") == NAME for e in existing):
            print(f"endpoint {NAME} already exists; refusing to create a second one")
            return 1

    if args.template_id:
        template_id = args.template_id
        print(f"reusing template: {template_id}")
    else:
        status, template = call("POST", "/templates", template_body)
        if status not in (200, 201) or not isinstance(template, dict):
            print(f"template create failed: {status} {str(template)[:500]}")
            return 1
        template_id = template.get("id")
        print(f"template created: {template_id}")

    endpoint_body["templateId"] = template_id
    status, endpoint = call("POST", "/endpoints", endpoint_body)
    if status not in (200, 201) or not isinstance(endpoint, dict):
        print(f"endpoint create failed: {status} {str(endpoint)[:4000]}")
        print(f"template {template_id} was created; delete it or reuse on retry")
        return 1

    endpoint_id = endpoint.get("id")
    print(f"endpoint created: {endpoint_id}")
    print(f"add to .env:  RUNPOD_ENDPOINT_ID_PIXAL3D={endpoint_id}")
    print(f"add to .env:  RUNPOD_PIXAL3D_TEMPLATE_ID={template_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
