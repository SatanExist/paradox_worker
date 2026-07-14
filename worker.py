import os
import time
import urllib.request
import tempfile
import base64
import runpod
import torch
from PIL import Image
import traceback

# TRELLIS can try to import flash_attn by default. We ship xformers in Docker,
# so force the attention backend to xformers to avoid ModuleNotFoundError.
os.environ.setdefault("ATTN_BACKEND", "xformers")

# ПРО-ФИШКА: Перенаправляем кэш нейросетей на наш примонтированный сетевой диск.
os.environ["HF_HOME"] = "/runpod-volume/huggingface_cache"

# Ленивая инициализация
pipeline = None


def _runpod_billing_metadata(handler_ms: dict) -> dict:
    """GPU info for downstream cost estimation (parsed from RunPod worker env)."""
    gpu_pool = os.environ.get("RUNPOD_GPU_SIZE")
    gpu_type = None
    for key in (
        "RUNPOD_WEBHOOK_POST_OUTPUT",
        "RUNPOD_WEBHOOK_GET_JOB",
        "RUNPOD_WEBHOOK_PING",
    ):
        url = os.environ.get(key, "")
        if "?gpu=" in url:
            gpu_type = url.split("?gpu=", 1)[1].split("&", 1)[0].replace("+", " ")
            break
    return {
        "gpu_type": gpu_type,
        "gpu_pool": gpu_pool,
        "datacenter": os.environ.get("RUNPOD_DC_ID"),
        "worker_id": os.environ.get("RUNPOD_POD_ID"),
        "handler_ms": handler_ms,
    }


DEFAULT_SIMPLIFY = 0.98
DEFAULT_TEXTURE_SIZE = 2048
DEFAULT_SEED = 1


def _coerce_float(value, default: float, *, min_val: float, max_val: float) -> float:
    if value is None:
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return max(min_val, min(max_val, out))


def _coerce_int(value, default: int, *, min_val: int, max_val: int) -> int:
    if value is None:
        return default
    try:
        out = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_val, min(max_val, out))


def _generation_params(job_input: dict) -> dict:
    """Parse optional tuning knobs from RunPod job input."""
    simplify = _coerce_float(
        job_input.get("simplify"),
        DEFAULT_SIMPLIFY,
        min_val=0.90,
        max_val=0.999,
    )
    texture_size = _coerce_int(
        job_input.get("texture_size"),
        DEFAULT_TEXTURE_SIZE,
        min_val=512,
        max_val=2048,
    )
    # TRELLIS to_glb uses 512-step slider in app; snap to supported sizes.
    if texture_size not in (512, 1024, 2048):
        texture_size = min((512, 1024, 2048), key=lambda x: abs(x - texture_size))

    seed = _coerce_int(job_input.get("seed"), DEFAULT_SEED, min_val=0, max_val=2**31 - 1)
    verbose = bool(job_input.get("verbose", True))
    return {
        "simplify": simplify,
        "texture_size": texture_size,
        "seed": seed,
        "verbose": verbose,
    }


def load_model():
    global pipeline
    build_sha = os.environ.get("PARADOX_BUILD_SHA", "unknown")
    print(f"paradox_worker image build: {build_sha}")
    try:
        import diff_gaussian_rasterization  # noqa: F401
        print("diff_gaussian_rasterization: OK")
    except ImportError as exc:
        print(f"diff_gaussian_rasterization: MISSING ({exc})")
        raise RuntimeError(
            "diff_gaussian_rasterization not installed — update RunPod image to a fresh "
            "ghcr.io/satanexist/paradox_worker:sha-<commit> tag and New Release"
        ) from exc
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
    gen_params = _generation_params(job_input)

    if not image_url:
        return {"error": "Вы не передали ссылку на картинку (image_url)"}

    try:
        t0 = time.perf_counter()
        handler_ms = {}

        t_load = time.perf_counter()
        load_model()
        handler_ms["model_load_ms"] = int((time.perf_counter() - t_load) * 1000)

        print(
            "Generation params: "
            f"simplify={gen_params['simplify']}, "
            f"texture_size={gen_params['texture_size']}, "
            f"seed={gen_params['seed']}"
        )

        print(f"Скачиваем изображение: {image_url}")
        req = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_img:
            with urllib.request.urlopen(req) as response:
                temp_img.write(response.read())
            img_path = temp_img.name

        image = Image.open(img_path).convert("RGB")

        print("Начинаем генерацию 3D (это может занять время)...")
        t_infer = time.perf_counter()
        outputs = pipeline.run(
            image,
            seed=gen_params["seed"],
        )
        handler_ms["inference_ms"] = int((time.perf_counter() - t_infer) * 1000)

        from trellis.utils import postprocessing_utils

        glb_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".glb")
        glb_path = glb_temp.name
        glb_temp.close()

        t_glb = time.perf_counter()
        glb = postprocessing_utils.to_glb(
            outputs['gaussian'][0],
            outputs['mesh'][0],
            simplify=gen_params["simplify"],
            texture_size=gen_params["texture_size"],
            verbose=gen_params["verbose"],
        )
        glb.export(glb_path)
        handler_ms["glb_export_ms"] = int((time.perf_counter() - t_glb) * 1000)
        handler_ms["total_ms"] = int((time.perf_counter() - t0) * 1000)

        with open(glb_path, "rb") as glb_file:
            glb_base64 = base64.b64encode(glb_file.read()).decode('utf-8')

        os.remove(img_path)
        os.remove(glb_path)

        return {
            "status": "success",
            "message": "3D-модель успешно сгенерирована!",
            "model_base64": glb_base64,
            "generation": gen_params,
            "billing": _runpod_billing_metadata(handler_ms),
        }

    except Exception as e:
        tb = traceback.format_exc()
        print(f"КРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
        print(tb)
        return {"error": f"Ошибка при генерации: {str(e)}"}


runpod.serverless.start({"handler": handler})