import runpod


def generate_3d_model(job):
    """
    Это главная функция, которая будет просыпаться, когда мы отправляем запрос.
    """
    job_input = job["input"]
    image_url = job_input.get("image_url")

    if not image_url:
        return {"error": "Вы не передали ссылку на картинку (image_url)"}

    # Логируем начало работы в консоль сервера
    print(f"🚀 Запущена генерация 3D для картинки: {image_url}")
    print("🧠 Нейросеть TRELLIS загружается с диска /runpod-volume...")

    # Здесь позже будет настоящий код генерации через TRELLIS
    # Пока мы делаем заглушку, чтобы проверить связь с RunPod

    return {
        "status": "success",
        "message": "Модель успешно сгенерирована (пока это заглушка!)",
        "original_image": image_url
    }


# Сообщаем RunPod, что этот скрипт готов принимать задачи
runpod.serverless.start({"handler": generate_3d_model})