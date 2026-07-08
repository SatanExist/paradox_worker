import os
import urllib.request
import tempfile
import base64
import runpod
import torch
from PIL import Image

# TRELLIS can try to import flash_attn by default. We ship xformers in Docker,
# so force the attention backend to xformers to avoid ModuleNotFoundError.
os.environ.setdefault("ATTN_BACKEND", "xformers")

# ПРО-ФИШКА: Перенаправляем кэш нейросетей на наш примонтированный сетевой диск.
os.environ["HF_HOME"] = "/runpod-volume/huggingface_cache"

# Ленивая инициализация
pipeline = None


def load_model():
    global pipeline
    if pipeline is None:
        print("Инициализация TRELLIS. Загрузка весов на сетевой диск...")
        from trellis.pipelines import TrellisImageTo3DPipeline
        from huggingface_hub import snapshot_download

        # 1. Принудительно качаем веса на примонтированный диск RunPod
        model_path = snapshot_download(
            "JeffreyXiang/TRELLIS-image-large",
            local_dir="/runpod-volume/trellis-weights"
        )

        # 2. Главный хак: создаем символическую ссылку (ярлык) для бага TRELLIS
        local_ckpts_link = "/app/ckpts"
        real_ckpts_path = os.path.join(model_path, "ckpts")

        if not os.path.exists(local_ckpts_link):
            os.symlink(real_ckpts_path, local_ckpts_link)

        # 3. Инициализируем пайплайн
        pipeline = TrellisImageTo3DPipeline.from_pretrained(model_path)
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
        load_model()

        print(f"Скачиваем изображение: {image_url}")
        req = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_img:
            with urllib.request.urlopen(req) as response:
                temp_img.write(response.read())
            img_path = temp_img.name

        image = Image.open(img_path).convert("RGB")

        print("Начинаем генерацию 3D (это может занять время)...")
        outputs = pipeline.run(
            image,
            seed=1,
        )

        from trellis.utils import render_utils

        glb_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".glb")
        glb_path = glb_temp.name
        glb_temp.close()

        render_utils.render_glb(outputs, glb_path)

        with open(glb_path, "rb") as glb_file:
            glb_base64 = base64.b64encode(glb_file.read()).decode('utf-8')

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


runpod.serverless.start({"handler": handler})