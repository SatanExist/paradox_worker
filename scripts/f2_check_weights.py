"""Can we actually download the weights we plan to integrate?

Gated repos and region flags only show up at access time, so check before
building an image around a net.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / ".env")

REPOS = [
    "TencentARC/Pixal3D",
    "wushuang98/Direct3D-S2",
    "stepfun-ai/Step1X-3D",
    "VAST-AI/TripoSG",
    "VAST-AI/SkinTokens",
]


def main() -> None:
    from huggingface_hub import HfApi
    from huggingface_hub.utils import HfHubHTTPError

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    api = HfApi(token=token)
    print(f"token: {'yes' if token else 'no'}\n")

    for repo_id in REPOS:
        try:
            info = api.model_info(repo_id, files_metadata=True)
        except HfHubHTTPError as exc:
            print(f"{repo_id:26} DENIED  {exc.response.status_code} {exc.response.reason_phrase}")
            continue
        except Exception as exc:
            print(f"{repo_id:26} ERROR   {type(exc).__name__}: {exc}")
            continue

        gated = getattr(info, "gated", None)
        siblings = info.siblings or []
        total = sum(s.size or 0 for s in siblings)
        weights = [s for s in siblings if s.rfilename.endswith((".safetensors", ".bin", ".ckpt", ".pt"))]
        print(
            f"{repo_id:26} OK  gated={gated} files={len(siblings):>3} "
            f"weights={len(weights):>2} total={total / 2**30:6.1f} GB"
        )


if __name__ == "__main__":
    main()
