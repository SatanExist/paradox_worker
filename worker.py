import os
import urllib.request
import tempfile
import base64
import runpod
import torch
from PIL import Image

# ПРО-ФИШКА: Перенаправляем кэш нейросетей на наш примонтированный сетевой диск.
# Теперь Hugging Face скачает веса один раз и сохранит их на /runpod-volume.
# При следующих запусках они будут грузиться моментально!
os.environ["HF_HOME"] = "/runpod-volume/huggingface_cache"

# Ленивая инициализация (чтобы загружать модель только один раз при старте воркера)
pipeline = None


def load_model():
    global pipeline
    if pipeline is None:
        print("Инициализация TRELLIS. Проверка весов на сетевом диске...")
        # Импортируем локально, чтобы ошибки импорта не валили воркер до старта
        from trellis.pipelines import TrellisImageTo3DPipeline

        # Скачиваем/загружаем веса (всё кэшируется на /runpod-volume)
        pipeline = TrellisImageTo3DPipeline.from_pretrained("JeffreyXiang/TRELLIS-image-large")
        pipeline.cuda()
        print("Нейросеть успешно загружена в VRAM!")


def handler(job):
    """
    Основная функция, которая обрабатывает входящие запросы.
    """
    job_input = job.get('input', {})
    image_url = job_input.get('image_url')

    if not image_url:
        return {"error": "Вы не передали ссылку на картинку (image_url)"}

    try:
        # 1. Загружаем модель в память GPU (если еще не загружена)
        load_model()

        # 2. Скачиваем картинку во временный файл
        print(f"Скачиваем изображение: {image_url}")
        req = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_img:
            with urllib.request.urlopen(req) as response:
                temp_img.write(response.read())
            img_path = temp_img.name

        # Открываем через PIL для нейросети
        image = Image.open(img_path).convert("RGB")

        # 3. ГЕНЕРАЦИЯ 3D-МОДЕЛИ (Магия TRELLIS)
        print("Начинаем генерацию 3D (это может занять время)...")
        # Здесь мы запускаем пайплайн. В реальном TRELLIS это возвращает внутренний объект.
        outputs = pipeline.run(
            image,
            # Можно вынести параметры в job_input, чтобы крутить их прямо из Unreal
            seed=1,
        )

        # 4. Сохраняем результат в .glb
        from trellis.utils import render_utils

        # Создаем временный файл для 3D модели
        glb_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".glb")
        glb_path = glb_temp.name
        glb_temp.close()

        # Экспортируем результат в GLB формат
        # (Синтаксис экспорта зависит от точной версии TRELLIS, обычно это метод объекта)
        render_utils.render_glb(outputs, glb_path)

        # 5. Кодируем GLB в Base64, чтобы безопасно передать обратно по API
        with open(glb_path, "rb") as glb_file:
            glb_base64 = base64.b64encode(glb_file.read()).decode('utf-8')

        # Очищаем временные файлы
        os.remove(img_path)
        os.remove(glb_path)

        return {
            "status": "success",
            "message": "3D-модель успешно сгенерирована!",
            "model_base64": glb_base64
        }

    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
        return {"error": f"Ошибка при генерации: {str(e)}"}


# Запускаем Serverless-слушатель RunPod
runpod.serverless.start({"handler": handler})