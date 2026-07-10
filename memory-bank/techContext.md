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
| `test_req.py` | Локальный тест RunPod API: async `/run` + polling + fallback |
| `scripts/watch_endpoint.py` | Мониторинг `/health` (queue, workers, throttled) |
| `TRELLIS/` | Исходники TRELLIS в репо (`PYTHONPATH=/app/TRELLIS`) |

## Настройка RunPod

- **API key**: `RUNPOD_API_KEY` в `.env` (не коммитить!)
- **Endpoints** (defaults в `test_req.py` / `.env`):

| Роль | ID | Регион | Volume |
|------|-----|--------|--------|
| Primary CZ | `splmm6w2rblqkp` | EU-CZ-1 | `paradox-models` |
| Secondary RO | `88djlbwtw4sjlv` | EU-RO-1 | `witty_blush_toucan` |

- **Docker image** (GHCR): `ghcr.io/satanexist/paradox_worker`
  - Сейчас (починка): `:latest`
  - Прод (план): `:stable` или `:vX.Y.Z`
  - **Не использовать** обрезанный digest вручную — SHA-256 = **64** hex после `sha256:`
  - Digest копировать только из GitHub Packages / `docker inspect`, не из чата
- **Network volume** (должен быть примонтирован к endpoint):
  - `/runpod-volume/huggingface_cache` — кэш HF (`HF_HOME`)
  - `/runpod-volume/trellis-weights` — веса модели через `snapshot_download`

### Multi-endpoint (вариант B)

Для повышения доступности на serverless используем 2 endpoint'а в разных регионах:

- `RUNPOD_ENDPOINT_ID_PRIMARY` — основной регион
- `RUNPOD_ENDPOINT_ID_SECONDARY` — резервный регион (fallback, если primary долго в `IN_QUEUE`)

Важно: **network volume не шарится между регионами**, поэтому во втором регионе нужен отдельный volume, смонтированный в тот же путь `/runpod-volume`.

## Контракт API

Рекомендуемо для сайта: **async**.

**Запрос (async)** (`POST https://api.runpod.ai/v2/{ENDPOINT_ID}/run`):

```json
{
  "input": {
    "image_url": "https://example.com/image.png"
  }
}
```

Ответ содержит `id`, который нужно опрашивать.

**Статус** (`GET https://api.runpod.ai/v2/{ENDPOINT_ID}/status/{id}`).

Для отладки можно использовать `/runsync`, но в проде лучше `/run` + polling/webhook.

**Запрос (sync, debug)** (`POST https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync`):

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
# RUNPOD_ENDPOINT_ID_PRIMARY=...
# RUNPOD_ENDPOINT_ID_SECONDARY=...  (опционально)

python test_req.py
```

TRELLIS inference работает **только внутри Docker на RunPod**, не локально (если только нет GPU-окружения как в Dockerfile).

## Деплой образа

| Тег | Когда |
|-----|--------|
| `:latest` | CI на каждый push в `main`; dev и экстренная починка |
| `:v2026-07-10-1` | Immutable релиз (пример) |
| `:stable` | Прод primary — обновляется только после теста на secondary |

Процесс:
- GitHub Actions (`.github/workflows/build.yml`) пушит `latest` в GHCR.
- Позже: добавить теги `v...` + `stable` и controlled rollout (RO → CZ).
- **RunPod Flash** (UI «Deploy with Flash») не используем — нужен кастомный Dockerfile для TRELLIS.

### Env на endpoint (важно)

- **Не задавать** `RUNPOD_SOURCE_PATH` для кастомного Docker с `CMD ["python", "-u", "/app/worker.py"]`
- Model field: пусто

## Сборка Docker — важное

- `spconv-cu118` строго под CUDA 11.8
- FlexiCubes: **MaxtirError/FlexiCubes** @ `f97beb0` (TRELLIS submodule fork), не nv-tlabs
- `kaolin` для torch 2.0.1 + cu118 (FlexiCubes dependency)
- Зафиксированы: `xformers==0.0.20`, `numpy==1.26.4`, `transformers==4.40.2`
- Первый cold start долгий (~15 GB весов на network volume)

## Секреты

- `.env` — в gitignore, там `RUNPOD_API_KEY`
- Не класть ключи и токены в memory-bank или rules
