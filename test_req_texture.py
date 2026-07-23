"""Smoke test for TRELLIS.2 mesh-texturing RunPod endpoint (Texture v1).

Contract:
  input:  mesh_url, image_url, seed?, resolution?, texture_size?, return_base64?
  output: model_url | model_base64 | model_path (+ billing)

Requires RUNPOD_ENDPOINT_ID_TEXTURE (dedicated texture worker).
Until that endpoint exists, this script exits with a clear error.
"""

from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from runpod_billing import estimate_from_status_payload
from runpod_queue_watchdog import run_with_zombie_retries

load_dotenv()

ENDPOINT_ID = os.getenv("RUNPOD_ENDPOINT_ID_TEXTURE", "").strip()
API_KEY = os.getenv("RUNPOD_API_KEY")

DEFAULT_IMAGE_URL = (
    "https://raw.githubusercontent.com/microsoft/TRELLIS/main/assets/example_image/"
    "typical_misc_monster_chest.png"
)
DEFAULT_ZOMBIE_AFTER_S = float(os.getenv("TEXTURE_ZOMBIE_AFTER_S", "90"))
DEFAULT_ZOMBIE_RETRIES = int(os.getenv("TEXTURE_ZOMBIE_RETRIES", "2"))

if not API_KEY:
    raise ValueError("RUNPOD_API_KEY not found in .env")


def sanitize(payload: dict) -> dict:
    out = dict(payload)
    job_out = out.get("output")
    if isinstance(job_out, dict) and isinstance(job_out.get("model_base64"), str):
        job_out = dict(job_out)
        job_out["model_base64"] = f"<omitted base64, len={len(job_out['model_base64'])}>"
        out["output"] = job_out
    return out


def build_input(args: argparse.Namespace) -> dict:
    job_input = {
        "mesh_url": args.mesh_url,
        "image_url": args.image_url,
        "seed": args.seed,
        "resolution": args.resolution,
        "texture_size": args.texture_size,
        "return_base64": args.return_base64,
    }
    if args.no_preprocess:
        job_input["preprocess_image"] = False
    return job_input


def save_output(final: dict, save_path: Path) -> None:
    output = final.get("output") or {}
    if not isinstance(output, dict):
        raise RuntimeError(f"COMPLETED without output dict: {final}")

    model_url = output.get("model_url")
    if isinstance(model_url, str) and model_url.startswith("http"):
        response = requests.get(model_url, timeout=120)
        response.raise_for_status()
        save_path.write_bytes(response.content)
        print(f"Saved from model_url -> {save_path.resolve()} bytes={save_path.stat().st_size}")
        return

    b64 = output.get("model_base64")
    if isinstance(b64, str) and b64:
        save_path.write_bytes(base64.b64decode(b64))
        print(f"Saved from model_base64 -> {save_path.resolve()} bytes={save_path.stat().st_size}")
        return

    raise RuntimeError(
        "No downloadable artifact in output. "
        f"model_path={output.get('model_path')!r} model_url={model_url!r} "
        f"hint={output.get('base64_omitted')!r}."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="RunPod TRELLIS.2 texture (mesh paint) smoke.")
    parser.add_argument(
        "--mesh-url",
        required=True,
        help="Public URL to clay (or any) GLB to re-texture",
    )
    parser.add_argument("--image-url", default=DEFAULT_IMAGE_URL)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--resolution", type=int, default=1024, choices=[512, 1024, 1536])
    parser.add_argument("--texture-size", type=int, default=2048, choices=[1024, 2048, 4096])
    parser.add_argument("--return-base64", action="store_true")
    parser.add_argument("--no-preprocess", action="store_true")
    parser.add_argument("--save", type=Path, default=Path("model-textured.glb"))
    parser.add_argument("--zombie-after-s", type=float, default=DEFAULT_ZOMBIE_AFTER_S)
    parser.add_argument("--zombie-retries", type=int, default=DEFAULT_ZOMBIE_RETRIES)
    parser.add_argument("--no-zombie-watch", action="store_true")
    parser.add_argument("--no-heal", action="store_true")
    args = parser.parse_args()

    if not ENDPOINT_ID:
        print(
            "RUNPOD_ENDPOINT_ID_TEXTURE is not set.\n"
            "Texture v1 needs a dedicated endpoint running worker_texture.py "
            "(Dockerfile.texture). Until then Studio uses Texture v0 legacy bake "
            "on the generate endpoint (texture_mode=textured)."
        )
        return 2

    job_input = build_input(args)
    print(f"Endpoint: {ENDPOINT_ID}")
    print(f"Input: mesh_url={args.mesh_url[:80]}... image_url={args.image_url[:80]}...")

    final = run_with_zombie_retries(
        endpoint_id=ENDPOINT_ID,
        api_key=API_KEY,
        job_input=job_input,
        zombie_after_s=None if args.no_zombie_watch else args.zombie_after_s,
        max_retries=0 if args.no_zombie_watch else args.zombie_retries,
        heal=not args.no_heal,
        sanitize=sanitize,
    )

    print("Final:", sanitize(final))
    if final.get("status") != "COMPLETED":
        return 1

    estimate_from_status_payload(final)
    save_output(final, args.save)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
