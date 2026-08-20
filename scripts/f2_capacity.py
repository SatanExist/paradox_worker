"""How much room is left for a park of nets: volumes, their size, endpoints.

Weights live on network volumes, so volume capacity is the real ceiling on how
many nets we can host at once.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GRAPHQL = "https://api.runpod.io/graphql"

QUERY = """
query {
  myself {
    networkVolumes { id name size dataCenterId }
    endpoints { id name templateId workersMin workersMax gpuIds networkVolumeId }
  }
}
"""


def main() -> None:
    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        raise SystemExit("RUNPOD_API_KEY missing in .env")

    resp = requests.post(
        GRAPHQL,
        json={"query": QUERY},
        headers={"Authorization": f"Bearer {key}"},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise SystemExit(json.dumps(data["errors"], indent=2))

    me = data["data"]["myself"]

    print("== network volumes ==")
    for vol in me.get("networkVolumes") or []:
        print(f"  {vol['name']:24} {vol['size']:>5} GB  {vol['dataCenterId']}  id={vol['id']}")

    print("\n== endpoints ==")
    for ep in me.get("endpoints") or []:
        gpus = (ep.get("gpuIds") or "")[:40]
        print(
            f"  {ep['name']:28} min={ep.get('workersMin')} max={ep.get('workersMax')} "
            f"vol={ep.get('networkVolumeId')} gpu={gpus}"
        )


if __name__ == "__main__":
    main()
