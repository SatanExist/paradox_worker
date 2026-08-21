"""Create the Direct3D-S2 serverless template + endpoint on RunPod.

Refuses to fork if a template/endpoint with the same name already exists.
R2 + GHCR auth are copied from the Hi3DGen template.
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

DONOR_TEMPLATE = os.getenv("RUNPOD_HI3DGEN_TEMPLATE_ID", "s15aqi9lxs").strip()
VOLUME_ID = os.getenv("RUNPOD_T2_VOLUME_ID", "netu72a8j2").strip()

NAME = "paradox-direct3ds2"
IMAGE = os.getenv(
    "DIRECT3DS2_IMAGE", "ghcr.io/satanexist/paradox_worker:direct3ds2-latest"
)
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
    parser.add_argument("--template-id", help="reuse an already created template")
    parser.add_argument("--image", help="override image tag")
    args = parser.parse_args()
    image = args.image or IMAGE

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
        "DIRECT3DS2_OUTPUT_DIR": "/runpod-volume/outputs",
        "HF_HOME": "/runpod-volume/huggingface_cache",
        "TORCH_HOME": "/runpod-volume/torch_hub",
        "SPARSE_BACKEND": "torchsparse",
        "SPARSE_ATTN_BACKEND": "xformers",
        "ATTN_BACKEND": "xformers",
    }

    template_body = {
        "name": NAME,
        "imageName": image,
        "containerDiskInGb": 40,
        "containerRegistryAuthId": donor.get("containerRegistryAuthId"),
        "isServerless": True,
        "volumeMountPath": "/runpod-volume",
        "readme": "Direct3D-S2 N3 worker: sparse SDF image-to-3D at sdf_resolution=1024.",
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
        "executionTimeoutMs": 45 * 60 * 1000,
    }

    print(f"template: {NAME} <- {image}")
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
    print(f"add to .env:  RUNPOD_ENDPOINT_ID_DIRECT3DS2={endpoint_id}")
    print(f"add to .env:  RUNPOD_DIRECT3DS2_TEMPLATE_ID={template_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
