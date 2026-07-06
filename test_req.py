import os
import requests
import time
from dotenv import load_dotenv

# Эта команда заставит Python найти файл .env и загрузить из него данные
load_dotenv()

# --- ТВОИ ДАННЫЕ ОТ RUNPOD ---
ENDPOINT_ID = "z44fok853g0e14"

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

except Exception as e:
    print(f"❌ Ошибка: {e}")