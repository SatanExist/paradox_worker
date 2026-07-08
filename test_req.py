import os
import requests
import time
from dotenv import load_dotenv

# Эта команда заставит Python найти файл .env и загрузить из него данные
load_dotenv()

# --- ТВОИ ДАННЫЕ ОТ RUNPOD ---
ENDPOINT_ID = "splmm6w2rblqkp"

# Теперь скрипт сам подтянет настоящий ключ из безопасного места!
API_KEY = os.getenv("RUNPOD_API_KEY")

# Небольшая проверка, чтобы сразу понять, если что-то пошло не так
if not API_KEY:
    raise ValueError("❌ Ключ API не найден! Проверь, создал ли ты файл .env")

url = f"https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

def wait_for_result(job_id: str, *, poll_interval_s: float = 5.0, max_wait_s: float = 15 * 60) -> dict:
    status_url = f"https://api.runpod.ai/v2/{ENDPOINT_ID}/status/{job_id}"
    deadline = time.time() + max_wait_s

    while True:
        if time.time() > deadline:
            raise TimeoutError(f"Timed out waiting for job result after {int(max_wait_s)}s (id={job_id})")

        r = requests.get(status_url, headers=headers, timeout=60)
        r.raise_for_status()
        payload = r.json()

        status = payload.get("status")
        if status in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            return payload

        time.sleep(poll_interval_s)

# Отправляем тестовую картинку лисы (стандартный тест TRELLIS)
data = {
    "input": {
        "image_url": "https://raw.githubusercontent.com/microsoft/TRELLIS/main/assets/example_images/fox.png"
    }
}

print("🚀 Отправляем картинку на боевой сервер RunPod (ожидайте, это может занять время)...")
try:
    # Указываем timeout=600 (10 минут), чтобы скрипт не отвалился, пока скачиваются 15 ГБ весов
    response = requests.post(url, json=data, headers=headers, timeout=600)
    result = response.json()

    print("✅ Ответ от облака получен:")
    print(result)

    job_id = result.get("id")
    if job_id and result.get("status") in ("IN_QUEUE", "IN_PROGRESS"):
        print(f"⏳ Job {job_id} is {result.get('status')}. Waiting for completion...")
        final_payload = wait_for_result(job_id)
        print("✅ Финальный статус получен:")
        print(final_payload)

except Exception as e:
    print(f"❌ Ошибка: {e}")