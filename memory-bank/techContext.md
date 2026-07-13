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
  "model_base64": "<base64 GLB>",
  "billing": {
    "gpu_type": "NVIDIA GeForce RTX 3090",
    "gpu_pool": "AMPERE_24",
    "datacenter": "EU-RO-1",
    "worker_id": "...",
    "handler_ms": {
      "model_load_ms": 0,
      "inference_ms": 95000,
      "glb_export_ms": 120000,
      "total_ms": 215000
    }
  }
}
```

### Оценка стоимости (через API)

RunPod **не отдаёт** точную цену в `/status/{job_id}` — только `delayTime` и `executionTime` (мс).

Модуль `runpod_billing.py`:

```python
from runpod_billing import estimate_from_status_payload

estimate = estimate_from_status_payload(
    status_payload,          # GET /v2/{endpoint}/status/{job_id}
    endpoint_id=ENDPOINT_ID,
    api_key=RUNPOD_API_KEY,
)
# estimate["cost_usd"], estimate["billable_sec"], estimate["gpu_type"], ...
```

Формула (estimate): `(delayTime + executionTime) / 1000 + idleTimeout` секунд × тариф GPU ($/сек).

- `idleTimeout` — из `GET https://rest.runpod.io/v1/endpoints/{id}`
- Тариф GPU — по `output.billing.gpu_type` из worker или по пулу endpoint'а
- Сверка с реальным счётом: `GET https://rest.runpod.io/v1/billing/endpoints` (агрегаты по часам, не per job)

`test_req.py` печатает оценку после `COMPLETED` / `FAILED`.

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
| `:v2026-07-13-1` | Immutable date-based релиз (пример) |
| `:sha-abc1234` | Immutable по коммиту |
| `:stable` | Прод primary — `workflow_dispatch` promote после теста |

Процесс:
- GitHub Actions (`.github/workflows/build.yml`) пушит `latest` в GHCR.
- Позже: добавить теги `v...` + `stable` и controlled rollout (RO → CZ).
- **RunPod Flash** (UI «Deploy with Flash») не используем — нужен кастомный Dockerfile для TRELLIS.

### Env на endpoint (важно)

- **Не задавать** `RUNPOD_SOURCE_PATH` для кастомного Docker с `CMD ["python", "-u", "/app/worker.py"]`
- Рекомендуется: `RUNPOD_INIT_TIMEOUT=900` (cold start с загрузкой весов)
- Model field: пусто

## Сборка Docker — важное

- `spconv-cu118` строго под CUDA 11.8
- FlexiCubes: **MaxtirError/FlexiCubes** @ `f97beb0` (TRELLIS submodule fork), не nv-tlabs
- `kaolin` для torch 2.0.1 + cu118 (FlexiCubes dependency)
- **nvdiffrast** (MeshRenderer / GLB export):
  - Системные пакеты: `libegl1-mesa-dev`, `libgl1-mesa-dev`, `libgles2-mesa-dev`, `libglvnd-dev`, …
  - `ENV PYOPENGL_PLATFORM=egl`
  - `pip install --no-build-isolation` (иначе ABI mismatch с torch)
  - `TORCH_CUDA_ARCH_LIST="7.5 8.0 8.6 8.9"` для CI buildx (3090/4090/A5000/L4)
- Зафиксированы: `xformers==0.0.20`, `numpy==1.26.4`, `transformers==4.40.2`
- Первый cold start долгий (~15 GB весов на network volume) → `RUNPOD_INIT_TIMEOUT=900` на endpoint

## GPU на RunPod endpoint

Образ **CUDA 11.8** — совместим только с **Ampere/Ada 24GB**:

| GPU | Статус |
|-----|--------|
| RTX 3090, 4090, A5000, L4 | ✅ оставить |
| PRO 6000 MIG 24GB | ✅ fallback |
| RTX 5090, B300 MIG 34GB | ❌ отключить (Blackwell, CUDA 12.x+) |
| A40, RTX A6000 (48GB) | ❌ отключить |

Tier gpuIds: только `AMPERE_24`, `ADA_24` — без `ADA_32_PRO`, `AMPERE_48`.

## Секреты

- `.env` — в gitignore, там `RUNPOD_API_KEY`
- Не класть ключи и токены в memory-bank или rules
