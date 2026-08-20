"""Check which candidate Spaces are actually alive before spending time on them."""

from __future__ import annotations

import json
import urllib.request

SPACES = [
    "VAST-AI/TripoSG",
    "wushuang98/Direct3D-S2-v1.0-demo",
    "stepfun-ai/Step1X-3D",
    "TencentARC/Pixal3D",
    "stabilityai/stable-fast-3d",
    "stabilityai/TripoSR",
    "VAST-AI/SkinTokens",
]


def main() -> None:
    for space in SPACES:
        url = f"https://huggingface.co/api/spaces/{space}/runtime"
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                data = json.load(resp)
        except Exception as exc:
            print(f"{space:36} ERR {exc}")
            continue
        hardware = (data.get("hardware") or {}).get("current")
        print(f"{space:36} stage={data.get('stage')} hw={hardware}")


if __name__ == "__main__":
    main()
