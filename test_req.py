import argparse
import os
import requests
import time
from dotenv import load_dotenv

from runpod_billing import estimate_from_status_payload

# Эта команда заставит Python найти файл .env и загрузить из него данные
load_dotenv()

# --- RUNPOD CONFIG ---
# Prefer env vars so we can use multiple endpoints (multi-region fallback).
ENDPOINT_ID_PRIMARY = os.getenv("RUNPOD_ENDPOINT_ID_PRIMARY", "splmm6w2rblqkp")
ENDPOINT_ID_SECONDARY = os.getenv("RUNPOD_ENDPOINT_ID_SECONDARY")

# Теперь скрипт сам подтянет настоящий ключ из безопасного места!
API_KEY = os.getenv("RUNPOD_API_KEY")

DEFAULT_IMAGE_URL = (
    "https://raw.githubusercontent.com/microsoft/TRELLIS/main/assets/example_image/T.png"
)

# Небольшая проверка, чтобы сразу понять, если что-то пошло не так
if not API_KEY:
    raise ValueError("❌ Ключ API не найден! Проверь, создал ли ты файл .env")

def post_run(endpoint_id: str, payload: dict) -> dict:
    url = f"https://api.runpod.ai/v2/{endpoint_id}/run"
    r = requests.post(url, json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

def get_status(endpoint_id: str, job_id: str) -> dict:
    status_url = f"https://api.runpod.ai/v2/{endpoint_id}/status/{job_id}"
    r = requests.get(status_url, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()

def sanitize_status_payload(payload: dict) -> dict:
    """
    Avoid printing huge model_base64 blobs to stdout.
    Keeps the shape but replaces the value with a short placeholder.
    """
    try:
        out = payload.get("output")
        if isinstance(out, dict) and isinstance(out.get("model_base64"), str):
            b64_len = len(out["model_base64"])
            out = dict(out)
            out["model_base64"] = f"<omitted base64, len={b64_len}>"
            payload = dict(payload)
            payload["output"] = out
    except Exception:
        pass
    return payload

def wait_for_terminal_status(endpoint_id: str, job_id: str, *, poll_interval_s: float = 5.0, max_wait_s: float = 15 * 60) -> dict:
    deadline = time.time() + max_wait_s

    while True:
        if time.time() > deadline:
            raise TimeoutError(
                f"Timed out waiting for job result after {int(max_wait_s)}s (endpoint={endpoint_id}, id={job_id})"
            )

        payload = get_status(endpoint_id, job_id)

        status = payload.get("status")
        if status in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            return payload

        time.sleep(poll_interval_s)

def wait_until_not_in_queue(endpoint_id: str, job_id: str, *, poll_interval_s: float = 5.0, max_wait_s: float = 10 * 60) -> bool:
    """
    Returns True if job leaves IN_QUEUE before timeout, else False.
    """
    deadline = time.time() + max_wait_s
    while True:
        payload = get_status(endpoint_id, job_id)
        status = payload.get("status")
        if status != "IN_QUEUE":
            return True
        if time.time() > deadline:
            return False
        time.sleep(poll_interval_s)

def print_cost_estimate(endpoint_id: str, status_payload: dict) -> None:
    """Print estimated USD cost from completed RunPod status payload."""
    try:
        estimate = estimate_from_status_payload(
            status_payload,
            endpoint_id=endpoint_id,
            api_key=API_KEY,
        )
        print("💰 Оценка стоимости генерации:")
        print(f"   {estimate['cost_usd_formatted']} USD")
        print(f"   GPU: {estimate.get('gpu_type') or estimate.get('gpu_pool') or 'unknown'}")
        print(
            f"   Billed ~{estimate['billable_sec']}s "
            f"(delay {estimate['delay_sec']}s + exec {estimate['execution_sec']}s + idle {estimate['idle_timeout_sec']}s)"
        )
        print(f"   Rate: ${estimate['rate_usd_per_sec']}/s ({estimate['rate_source']})")
        if estimate.get("handler_timing_ms"):
            print(f"   Handler breakdown (ms): {estimate['handler_timing_ms']}")
        if status_payload.get("output", {}).get("generation"):
            print(f"   Generation params: {status_payload['output']['generation']}")
        print(f"   Note: {estimate['note']}")
    except Exception as exc:
        print(f"⚠️ Не удалось оценить стоимость: {exc}")


def cancel_job(endpoint_id: str, job_id: str) -> None:
    url = f"https://api.runpod.ai/v2/{endpoint_id}/cancel/{job_id}"
    try:
        requests.post(url, headers=headers, timeout=60)
    except Exception:
        pass


def build_job_input(args: argparse.Namespace) -> dict:
    job_input = {"image_url": args.image_url}
    if args.simplify is not None:
        job_input["simplify"] = args.simplify
    if args.texture_size is not None:
        job_input["texture_size"] = args.texture_size
    if args.seed is not None:
        job_input["seed"] = args.seed
    return job_input


def run_test(args: argparse.Namespace) -> int:
    data = {"input": build_job_input(args)}
    print(f"📦 Job input: {data['input']}")

    print(f"🚀 Submit async job to primary endpoint: {ENDPOINT_ID_PRIMARY}")
    result = post_run(ENDPOINT_ID_PRIMARY, data)
    print("✅ Ответ от облака получен:")
    print(result)

    job_id = result.get("id")
    if not job_id:
        raise RuntimeError("RunPod response missing job id")

    status = result.get("status")
    if status == "IN_QUEUE" and ENDPOINT_ID_SECONDARY:
        print("⏳ Primary is IN_QUEUE. Waiting a bit for GPU capacity...")
        left_queue = wait_until_not_in_queue(ENDPOINT_ID_PRIMARY, job_id, max_wait_s=10 * 60)
        if not left_queue:
            print("⚠️ Still IN_QUEUE on primary. Cancelling and falling back to secondary endpoint...")
            cancel_job(ENDPOINT_ID_PRIMARY, job_id)

            print(f"🚀 Submit async job to secondary endpoint: {ENDPOINT_ID_SECONDARY}")
            result2 = post_run(ENDPOINT_ID_SECONDARY, data)
            print("✅ Ответ от облака (secondary) получен:")
            print(result2)

            job_id2 = result2.get("id")
            if not job_id2:
                raise RuntimeError("Secondary RunPod response missing job id")

            print(f"⏳ Waiting for completion (secondary job {job_id2})...")
            final_payload = wait_for_terminal_status(ENDPOINT_ID_SECONDARY, job_id2, max_wait_s=20 * 60)
            print("✅ Финальный статус получен:")
            print(sanitize_status_payload(final_payload))
            print_cost_estimate(ENDPOINT_ID_SECONDARY, final_payload)
            return 0 if final_payload.get("status") == "COMPLETED" else 1

    print(f"⏳ Waiting for completion (job {job_id})...")
    final_payload = wait_for_terminal_status(ENDPOINT_ID_PRIMARY, job_id, max_wait_s=20 * 60)
    print("✅ Финальный статус получен:")
    print(sanitize_status_payload(final_payload))
    print_cost_estimate(ENDPOINT_ID_PRIMARY, final_payload)
    return 0 if final_payload.get("status") == "COMPLETED" else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RunPod TRELLIS smoke test (async + fallback).")
    parser.add_argument("--image-url", default=DEFAULT_IMAGE_URL, help="Public image URL for image-to-3D.")
    parser.add_argument(
        "--simplify",
        type=float,
        default=0.98,
        help="GLB mesh simplify ratio (default: 0.98, higher = more detail).",
    )
    parser.add_argument(
        "--texture-size",
        type=int,
        default=2048,
        choices=[512, 1024, 2048],
        help="Texture bake resolution (default: 2048).",
    )
    parser.add_argument("--seed", type=int, default=1, help="Random seed (default: 1).")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(run_test(parse_args()))
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        raise SystemExit(1)
