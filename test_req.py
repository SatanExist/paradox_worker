import requests
import time

# --- ТВОИ ДАННЫЕ ОТ RUNPOD ---
ENDPOINT_ID = "z44fok853g0e14"
API_KEY = "API_KEY_RUNPOD"

# Используем runsync, чтобы скрипт ждал ответа (модель может генерироваться пару минут)
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