"""Audit and optionally fix RunPod serverless endpoint GPU list + idleTimeout."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runpod_billing import fetch_endpoint_config

REST_BASE = "https://rest.runpod.io/v1"

# CUDA 11.8 image: 24GB Ampere/Ada only. Order = rent priority.
RECOMMENDED_GPU_TYPE_IDS = [
    "NVIDIA GeForce RTX 4090",
    "NVIDIA RTX A5000",
    "NVIDIA GeForce RTX 3090",
    "NVIDIA L4",
]

BLOCKED_GPU_TYPE_IDS = {
    "NVIDIA GeForce RTX 5090",
    "NVIDIA B200",
    "NVIDIA RTX PRO 6000 Blackwell Server Edition",
    "NVIDIA RTX PRO 6000 Blackwell Workstation Edition",
    "NVIDIA RTX PRO 6000 Blackwell Max-Q Workstation Edition",
    "NVIDIA A40",
    "NVIDIA RTX A6000",
    "NVIDIA H100 80GB HBM3",
    "NVIDIA H100 PCIe",
    "NVIDIA H100 NVL",
    "NVIDIA H200",
    "NVIDIA H200 NVL",
}

DEFAULT_IDLE_TIMEOUT_SEC = 10


def patch_endpoint(endpoint_id: str, api_key: str, payload: dict) -> dict:
    url = f"{REST_BASE}/endpoints/{endpoint_id}"
    response = requests.patch(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def audit_config(name: str, endpoint_id: str, cfg: dict) -> dict:
    gpu_ids = list(cfg.get("gpuTypeIds") or [])
    idle = cfg.get("idleTimeout")
    blocked = [g for g in gpu_ids if g in BLOCKED_GPU_TYPE_IDS]
    issues = []
    if blocked:
        issues.append(f"blocked GPUs present: {blocked}")
    if idle is None or int(idle) > DEFAULT_IDLE_TIMEOUT_SEC:
        issues.append(f"idleTimeout={idle} (target <={DEFAULT_IDLE_TIMEOUT_SEC})")
    if set(gpu_ids) != set(RECOMMENDED_GPU_TYPE_IDS):
        extra = sorted(set(gpu_ids) - set(RECOMMENDED_GPU_TYPE_IDS))
        missing = sorted(set(RECOMMENDED_GPU_TYPE_IDS) - set(gpu_ids))
        if extra:
            issues.append(f"extra GPUs: {extra}")
        if missing:
            issues.append(f"missing recommended GPUs: {missing}")
    return {
        "name": name,
        "endpoint_id": endpoint_id,
        "endpoint_name": cfg.get("name"),
        "version": cfg.get("version"),
        "gpuTypeIds": gpu_ids,
        "idleTimeout": idle,
        "issues": issues,
        "ok": not issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit/fix RunPod endpoint GPU list and idleTimeout.")
    parser.add_argument("--apply", action="store_true", help="PATCH endpoints that fail audit.")
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=DEFAULT_IDLE_TIMEOUT_SEC,
        help=f"Target idleTimeout seconds (default: {DEFAULT_IDLE_TIMEOUT_SEC}).",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("RUNPOD_API_KEY")
    if not api_key:
        print("RUNPOD_API_KEY not found in .env", file=sys.stderr)
        return 1

    endpoints = {
        "CZ": os.getenv("RUNPOD_ENDPOINT_ID_PRIMARY", "splmm6w2rblqkp"),
        "RO": os.getenv("RUNPOD_ENDPOINT_ID_SECONDARY", "88djlbwtw4sjlv"),
    }

    reports = []
    for name, endpoint_id in endpoints.items():
        if not endpoint_id:
            continue
        cfg = fetch_endpoint_config(endpoint_id, api_key)
        report = audit_config(name, endpoint_id, cfg)
        reports.append(report)

        if args.apply and report["issues"]:
            payload = {
                "gpuTypeIds": RECOMMENDED_GPU_TYPE_IDS,
                "idleTimeout": args.idle_timeout,
            }
            print(f"Applying cleanup to {name} ({endpoint_id})...")
            updated = patch_endpoint(endpoint_id, api_key, payload)
            report["applied"] = True
            report["gpuTypeIds"] = updated.get("gpuTypeIds", payload["gpuTypeIds"])
            report["idleTimeout"] = updated.get("idleTimeout", payload["idleTimeout"])
            report["issues"] = audit_config(name, endpoint_id, updated)["issues"]
            report["ok"] = not report["issues"]

    if args.json:
        print(json.dumps(reports, indent=2, ensure_ascii=False))
    else:
        for report in reports:
            status = "OK" if report["ok"] else "NEEDS FIX"
            print(f"[{status}] {report['name']} {report['endpoint_id']} ({report.get('endpoint_name')}) v{report.get('version')}")
            print(f"  gpuTypeIds: {report['gpuTypeIds']}")
            print(f"  idleTimeout: {report['idleTimeout']}")
            for issue in report["issues"]:
                print(f"  - {issue}")
            if report.get("applied"):
                print("  -> PATCH applied")
            print()

    if any(not r["ok"] for r in reports):
        if not args.apply:
            print("Run with --apply to PATCH gpuTypeIds + idleTimeout.", file=sys.stderr)
            return 2
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
