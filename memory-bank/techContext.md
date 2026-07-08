# Технический контекст

## Стек

| Компонент | Технология |
|-----------|------------|
| GPU runtime | RunPod Serverless |
| Базовый образ | `runpod/pytorch:2.0.1-py3.10-cuda11.8.0-devel-ubuntu22.04` |
| 3D-модель | TRELLIS-image-large (`JeffreyXiang/TRELLIS-image-large`) |
| Worker SDK | `runpod` Python SDK |
| Inference | PyTorch + CUDA, ленивая загрузка pipeline |
| Формат выхода | GLB (base64 в JSON) |

## Ключевые файлы

| Файл | Назначение |
|------|------------|
| `worker.py` | RunPod handler: скачать картинку → TRELLIS → GLB → base64 |
| `Dockerfile` | Сборка контейнера: deps, копия TRELLIS, фикс FlexiCubes |
| `test_req.py` | Локальный тест RunPod API `/runsync` |
| `TRELLIS/` | Исходники TRELLIS в репо (`PYTHONPATH=/app/TRELLIS`) |

## Настройка RunPod

- **Endpoint**: ID serverless endpoint — в `test_req.py` (`ENDPOINT_ID`)
- **API key**: `RUNPOD_API_KEY` в `.env` (не коммитить!)
- **Network volume** (должен быть примонтирован к endpoint):
  - `/runpod-volume/huggingface_cache` — кэш HF (`HF_HOME`)
  - `/runpod-volume/trellis-weights` — веса модели через `snapshot_download`

## Контракт API

**Запрос** (`POST https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync`):

```json
{
  "input": {
    "image_url": "https://example.com/image.png"
  }
}
```

**Успех**:

```json
{
  "status": "success",
  "message": "3D-модель успешно сгенерирована!",
  "model_base64": "<base64 GLB>"
}
```

**Ошибка**:

```json
{
  "error": "..."
}
```

## Локальная разработка

```bash
pip install requests python-dotenv

# .env (не в git):
# RUNPOD_API_KEY=your_key_here

python test_req.py
```

TRELLIS inference работает **только внутри Docker на RunPod**, не локально (если только нет GPU-окружения как в Dockerfile).

## Сборка Docker — важное

- `spconv-cu118` строго под CUDA 11.8
- FlexiCubes клонируется отдельно (нет во vendored TRELLIS)
- Зафиксированы: `xformers==0.0.20`, `numpy==1.26.4`, `transformers==4.40.2`
- Первый cold start долгий (~15 GB весов на network volume)

## Секреты

- `.env` — в gitignore, там `RUNPOD_API_KEY`
- Не класть ключи и токены в memory-bank или rules
