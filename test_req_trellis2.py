"""Smoke test for TRELLIS.2 RunPod endpoint (quality tier)."""

import argparse
import base64
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from runpod_billing import estimate_from_status_payload

load_dotenv()

ENDPOINT_ID = os.getenv("RUNPOD_ENDPOINT_ID_TRELLIS2", "")
API_KEY = os.getenv("RUNPOD_API_KEY")

DEFAULT_IMAGE_URL = (
    "https://raw.githubusercontent.com/microsoft/TRELLIS/main/assets/example_image/"
    "typical_misc_monster_chest.png"
)

if not API_KEY:
    raise ValueError("RUNPOD_API_KEY not found in .env")
if not ENDPOINT_ID:
    raise ValueError("Set RUNPOD_ENDPOINT_ID_TRELLIS2 in .env (dedicated quality endpoint)")

HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def sanitize(payload: dict) -> dict:
    out = dict(payload)
    job_out = out.get("output")
    if isinstance(job_out, dict) and isinstance(job_out.get("model_base64"), str):
        job_out = dict(job_out)
        job_out["model_base64"] = f"<omitted base64, len={len(job_out['model_base64'])}>"
        out["output"] = job_out
    return out


def wait_for_job(endpoint_id: str, job_id: str, *, poll_s: float = 5.0, max_wait_s: float = 30 * 60) -> dict:
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        response = requests.get(
            f"https://api.runpod.ai/v2/{endpoint_id}/status/{job_id}",
            headers=HEADERS,
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        status = payload.get("status")
        if status in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            return payload
        time.sleep(poll_s)
    raise TimeoutError(f"Timed out waiting for job {job_id}")


def build_input(args: argparse.Namespace) -> dict:
    job_input = {
        "image_url": args.image_url,
        "pipeline_type": args.pipeline_type,
        "texture_size": args.texture_size,
        "seed": args.seed,
        "decimation_target": args.decimation_target,
        "return_base64": args.return_base64,
    }
    if args.no_preprocess:
        job_input["preprocess_image"] = False
    if args.no_remesh:
        job_input["remesh"] = False
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

    model_path = output.get("model_path")
    omitted = output.get("base64_omitted")
    raise RuntimeError(
        "No downloadable artifact in output. "
        f"model_path={model_path!r} model_url={model_url!r} "
        f"hint={omitted!r}. Configure R2_* on the endpoint or pass --return-base64 for small GLBs."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="RunPod TRELLIS.2 smoke test.")
    parser.add_argument("--image-url", default=DEFAULT_IMAGE_URL)
    parser.add_argument(
        "--pipeline-type",
        default="1024_cascade",
        choices=["512", "1024", "1024_cascade", "1536_cascade"],
    )
    parser.add_argument("--texture-size", type=int, default=2048, choices=[1024, 2048, 4096])
    parser.add_argument("--decimation-target", type=int, default=500_000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--save", help="Save GLB to this path on COMPLETED")
    parser.add_argument(
        "--return-base64",
        action="store_true",
        help="Ask worker to include model_base64 when under size limit",
    )
    parser.add_argument("--no-preprocess", action="store_true")
    parser.add_argument("--no-remesh", action="store_true")
    args = parser.parse_args()

    payload = {"input": build_input(args)}
    print(f"Endpoint: {ENDPOINT_ID}")
    print(f"Job input: {payload['input']}")

    response = requests.post(
        f"https://api.runpod.ai/v2/{ENDPOINT_ID}/run",
        json=payload,
        headers=HEADERS,
        timeout=60,
    )
    response.raise_for_status()
    job = response.json()
    job_id = job["id"]
    print(f"Submitted job {job_id} status={job.get('status')}")

    final = wait_for_job(ENDPOINT_ID, job_id)
    print("Final status:")
    print(sanitize(final))

    if final.get("status") == "COMPLETED":
        estimate = estimate_from_status_payload(final, endpoint_id=ENDPOINT_ID, api_key=API_KEY)
        print(f"Cost estimate: {estimate['cost_usd_formatted']} USD")
        output = final.get("output") or {}
        if isinstance(output, dict):
            print(
                "delivery=",
                output.get("delivery"),
                "bytes=",
                output.get("model_bytes"),
                "path=",
                output.get("model_path"),
                "url=",
                output.get("model_url"),
            )
        if args.save:
            save_output(final, Path(args.save))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
