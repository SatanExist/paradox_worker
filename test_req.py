import os
import requests
import time
from dotenv import load_dotenv

# Эта команда заставит Python найти файл .env и загрузить из него данные
load_dotenv()

# --- RUNPOD CONFIG ---
# Prefer env vars so we can use multiple endpoints (multi-region fallback).
ENDPOINT_ID_PRIMARY = os.getenv("RUNPOD_ENDPOINT_ID_PRIMARY", "splmm6w2rblqkp")
ENDPOINT_ID_SECONDARY = os.getenv("RUNPOD_ENDPOINT_ID_SECONDARY")

# Теперь скрипт сам подтянет настоящий ключ из безопасного места!
API_KEY = os.getenv("RUNPOD_API_KEY")

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

def cancel_job(endpoint_id: str, job_id: str) -> None:
    url = f"https://api.runpod.ai/v2/{endpoint_id}/cancel/{job_id}"
    try:
        requests.post(url, headers=headers, timeout=60)
    except Exception:
        pass

# Отправляем тестовую картинку лисы (стандартный тест TRELLIS)
data = {
    "input": {
        "image_url": "https://raw.githubusercontent.com/microsoft/TRELLIS/main/assets/example_images/fox.png"
    }
}

try:
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
            print(final_payload)
            raise SystemExit(0)

    print(f"⏳ Waiting for completion (job {job_id})...")
    final_payload = wait_for_terminal_status(ENDPOINT_ID_PRIMARY, job_id, max_wait_s=20 * 60)
    print("✅ Финальный статус получен:")
    print(final_payload)

except Exception as e:
    print(f"❌ Ошибка: {e}")