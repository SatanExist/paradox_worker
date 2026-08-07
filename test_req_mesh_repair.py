"""Smoke test: T2 endpoint mesh repair (no TRELLIS infer).

Example:
  .venv314\\Scripts\\python.exe test_req_mesh_repair.py --mode voxel --resolution 256
"""

from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

ENDPOINT_ID = os.getenv("RUNPOD_ENDPOINT_ID_TRELLIS2", "").strip()
API_KEY = os.getenv("RUNPOD_API_KEY", "").strip()
DEFAULT_MESH = (
    "https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/model-chest-p2b-ultra.glb"
)


def main() -> int:
    p = argparse.ArgumentParser(description="T2 mesh repair endpoint smoke")
    p.add_argument("--mesh-url", default=DEFAULT_MESH)
    p.add_argument("--mode", default="voxel", choices=["voxel", "pymeshlab", "trimesh"])
    p.add_argument("--resolution", type=int, default=256)
    p.add_argument("--max-hole-size", type=int, default=5000)
    p.add_argument("-o", "--output", type=Path, help="Save GLB locally")
    args = p.parse_args()

    if not API_KEY or not ENDPOINT_ID:
        print("Need RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID_TRELLIS2 in .env")
        return 1

    payload = {
        "input": {
            "repair_mode": args.mode,
            "mesh_url": args.mesh_url,
            "repair_resolution": args.resolution,
            "max_hole_size": args.max_hole_size,
            "return_base64": True,
        }
    }
    url = f"https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync"
    print(f"POST {url} mode={args.mode} res={args.resolution}")
    r = requests.post(url, json=payload, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=600)
    print("HTTP", r.status_code)
    data = r.json()
    if r.status_code >= 400:
        print(data)
        return 1
    out = data.get("output") or data
    if isinstance(out, dict) and out.get("error"):
        print("ERROR:", out["error"])
        return 1
    meta = out.get("repair_meta") if isinstance(out, dict) else None
    if meta:
        print("repair_meta:", meta)
    b64 = out.get("model_base64") if isinstance(out, dict) else None
    if not b64:
        print(out)
        return 1
    out_path = args.output or Path(f"model-chest-repair-{args.mode}{args.resolution}.glb")
    out_path.write_bytes(base64.b64decode(b64))
    print(f"saved {out_path} ({out_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
