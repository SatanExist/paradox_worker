"""Create / list / terminate a RunPod GPU pod for MV-Adapter W2 spike.

Uses GraphQL with api_key query param (Serverless REST Bearer key often works here too).

Examples:
  python scripts/mvadapter_create_pod.py --create
  python scripts/mvadapter_create_pod.py --list
  python scripts/mvadapter_create_pod.py --terminate <pod_id>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

GQL = "https://api.runpod.io/graphql"
REST_PODS = "https://rest.runpod.io/v1/pods"

# Prefer 4090; fall back list if unavailable
GPU_CANDIDATES = [
    "NVIDIA GeForce RTX 4090",
    "NVIDIA RTX A6000",
    "NVIDIA RTX A5000",
    "NVIDIA GeForce RTX 3090",
]

DEFAULT_IMAGE = "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"


def _api_key() -> str:
    key = os.getenv("RUNPOD_API_KEY", "").strip()
    if not key:
        raise SystemExit("RUNPOD_API_KEY missing in .env")
    return key


def gql(query: str, variables: dict | None = None) -> dict:
    key = _api_key()
    url = f"{GQL}?api_key={key}"
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables
    r = requests.post(url, json=payload, timeout=120)
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        raise SystemExit(f"GraphQL HTTP {r.status_code}: {data}")
    if data.get("errors"):
        raise SystemExit(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
    return data.get("data") or {}


def rest_list_pods() -> list:
    key = _api_key()
    r = requests.get(
        REST_PODS,
        headers={"Authorization": f"Bearer {key}"},
        timeout=60,
    )
    r.raise_for_status()
    body = r.json()
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        return body.get("pods") or body.get("data") or []
    return []


def create_pod(*, name: str, gpu: str, disk_gb: int, volume_gb: int) -> dict:
    # Inline mutation matches RunPod docs (typed variables can be flaky across schema versions).
    mutation = f"""
    mutation {{
      podFindAndDeployOnDemand(
        input: {{
          cloudType: ALL
          gpuCount: 1
          volumeInGb: {volume_gb}
          containerDiskInGb: {disk_gb}
          minVcpuCount: 4
          minMemoryInGb: 24
          gpuTypeId: "{gpu}"
          name: "{name}"
          imageName: "{DEFAULT_IMAGE}"
          dockerArgs: ""
          ports: "8888/http,22/tcp"
          volumeMountPath: "/workspace"
        }}
      ) {{
        id
        name
        imageName
        machineId
        desiredStatus
        costPerHr
        machine {{ podHostId }}
      }}
    }}
    """
    return gql(mutation)


def terminate_pod(pod_id: str) -> dict:
    mutation = """
    mutation($input: PodTerminateInput!) {
      podTerminate(input: $input)
    }
    """
    return gql(mutation, {"input": {"podId": pod_id}})


def resume_pod(pod_id: str) -> dict:
    mutation = f"""
    mutation {{
      podResume(input: {{ podId: "{pod_id}" }}) {{
        id
        desiredStatus
        imageName
        machine {{ podHostId }}
      }}
    }}
    """
    return gql(mutation)


def main() -> int:
    p = argparse.ArgumentParser(description="MV-Adapter W2 RunPod pod helper")
    p.add_argument("--create", action="store_true")
    p.add_argument("--list", action="store_true")
    p.add_argument("--resume", metavar="POD_ID")
    p.add_argument("--terminate", metavar="POD_ID")
    p.add_argument("--name", default="paradox-mvadapter-w2")
    p.add_argument("--gpu", default="", help="Exact gpuTypeId; else try candidates")
    p.add_argument("--disk-gb", type=int, default=60)
    p.add_argument("--volume-gb", type=int, default=80)
    args = p.parse_args()

    if args.list or (not args.create and not args.terminate and not args.resume):
        pods = rest_list_pods()
        print(f"Pods ({len(pods)}):")
        for pod in pods:
            if not isinstance(pod, dict):
                print(" ", pod)
                continue
            print(
                f"  id={pod.get('id')} name={pod.get('name')} "
                f"status={pod.get('desiredStatus') or pod.get('runtime', {}).get('uptimeInSeconds')} "
                f"gpu={pod.get('machine', {}).get('gpuDisplayName') or pod.get('gpuTypeId')}"
            )
        if not args.create and not args.terminate and not args.resume:
            return 0

    if args.resume:
        out = resume_pod(args.resume)
        print(json.dumps(out, indent=2))
        return 0

    if args.terminate:
        out = terminate_pod(args.terminate)
        print(json.dumps(out, indent=2))
        return 0

    if args.create:
        gpus = [args.gpu] if args.gpu else GPU_CANDIDATES
        last_err: Exception | None = None
        for gpu in gpus:
            print(f"Trying gpuTypeId={gpu!r} ...")
            try:
                data = create_pod(
                    name=args.name,
                    gpu=gpu,
                    disk_gb=args.disk_gb,
                    volume_gb=args.volume_gb,
                )
                pod = data.get("podFindAndDeployOnDemand") or data
                print(json.dumps(pod, indent=2))
                print("\nNext (Phase 1 FAST baseline):")
                print("  1. Open Pod -> Connect -> Start Web Terminal")
                print("  2. One-liner:")
                print(
                    "     cd /workspace && wget -q -O /tmp/w2.zip "
                    "https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/mvadapter_w2_upload.zip "
                    "&& unzip -o /tmp/w2.zip -d /workspace "
                    "&& wget -q -O /workspace/mvadapter_w2_fast_oneshot.sh "
                    "https://raw.githubusercontent.com/SatanExist/paradox_worker/feat/trellis2-poc/scripts/mvadapter_w2_fast_oneshot.sh "
                    "&& bash /workspace/mvadapter_w2_fast_oneshot.sh"
                )
                print("  3. After DONE_OK: download outputs/knight_fast_shaded.glb + knight_fast_timings.txt")
                print("  4. Terminate pod when finished (billing!).")
                return 0
            except SystemExit as exc:
                last_err = exc
                print(f"  failed: {exc}")
                continue
        raise SystemExit(f"All GPU types failed. Last: {last_err}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
