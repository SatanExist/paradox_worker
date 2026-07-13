import argparse
import base64
import os
from pathlib import Path

import requests
from dotenv import load_dotenv


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Download RunPod status JSON and save output.model_base64 as GLB.")
    parser.add_argument("--endpoint", required=True, help="RunPod endpoint id (e.g. 88djlbwtw4sjlv)")
    parser.add_argument("--id", required=True, dest="job_id", help="RunPod request id")
    parser.add_argument("--out", default="model.glb", help="Output .glb path (default: model.glb)")
    args = parser.parse_args()

    api_key = os.environ.get("RUNPOD_API_KEY")
    if not api_key:
        raise SystemExit("RUNPOD_API_KEY not found in environment/.env")

    url = f"https://api.runpod.ai/v2/{args.endpoint}/status/{args.job_id}"
    r = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=60)
    r.raise_for_status()
    data = r.json()

    status = data.get("status")
    if status != "COMPLETED":
        raise SystemExit(f"Job not COMPLETED: {status} (id={data.get('id')})")

    out = data.get("output") or {}
    b64 = out.get("model_base64")
    if not isinstance(b64, str) or not b64:
        raise SystemExit("model_base64 missing in output")

    raw = base64.b64decode(b64)
    out_path = Path(args.out)
    out_path.write_bytes(raw)
    print(f"Saved {out_path.resolve()} bytes={len(raw)} magic={raw[:4]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

