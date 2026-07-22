# Технический контекст

## Стек

| Компонент | Технология |
|-----------|------------|
| GPU runtime | RunPod Serverless |
| Базовый образ | `runpod/pytorch:2.0.1-py3.10-cuda11.8.0-devel-ubuntu22.04` |
| 3D-модель | TRELLIS-image-large (`JeffreyXiang/TRELLIS-image-large`) — **legacy v1** |
| Quality tier (POC) | TRELLIS.2-4B (`microsoft/TRELLIS.2-4B`) — CUDA 12.4, отдельный образ |
| Worker SDK | `runpod` Python SDK |
| Inference | PyTorch + CUDA, ленивая загрузка pipeline |
| Формат выхода | GLB: v1 — base64 в JSON; **T2** — volume + **R2 `model_url`** (настроено); base64 только если маленький |

## Ключевые файлы

| Файл | Назначение |
|------|------------|
| `worker.py` | RunPod handler v1: картинка → TRELLIS → GLB → base64 |
| `worker_trellis2.py` | Quality: TRELLIS.2 → GLB на volume / R2 / base64 (cap) |
| `Dockerfile` | v1 контейнер (CUDA 11.8) |
| `Dockerfile.trellis2` | quality (CUDA 12.4, torch 2.6, einops, boto3) |
| `test_req.py` | Smoke test v1 endpoint |
| `runpod_queue_watchdog.py` | Zombie IN_QUEUE detect + DELETE ghost pods + retry |
| `test_req_trellis2.py` | Smoke T2 + watchdog/heal; R2 download |
| `scripts/heal_t2_endpoint.py` | Ручной heal ghost workers / purge-queue |
| `scripts/diagnose_t2_queue.py` | Live probe: health + short submit watch |
| `scripts/convert_dinov3_meta_to_hf.py` | Meta `.pth` → HF-папка DINOv3 для volume |
| `scripts/batch_seeds.py` | Best-of-N seeds → GLB |
| `scripts/studio_api.py` | POC HTTP API: `POST/GET /api/jobs` для Studio |
| `scripts/studio_smoke.py` | Smoke без HTTP (image/text → RunPod poll) |
| `studio_bridge/` | Tier mapping + normalize status + text2image hook |
| `scripts/save_glb_from_status.py` | Скачать GLB по job id без base64 в терминале |
| `scripts/view_model.html` | Локальный GLB viewer (`python -m http.server` + `?model=/file.glb`) |
| `scripts/download_volume_glb.py` | S3 API volume→ПК (часто stall из РФ; предпочитать R2) |
| `scripts/rerun_workflow.py` | Re-run failed GitHub Actions (нужен `GITHUB_TOKEN`) |
| `scripts/cleanup_endpoints.py` | Audit/fix GPU list + idleTimeout |
| `scripts/fetch_ci_log.py` | Скачать лог GitHub Actions job (нужен `GITHUB_TOKEN`) |
| `TRELLIS/` | Исходники TRELLIS v1 (`PYTHONPATH=/app/TRELLIS`) |

## Настройка RunPod

- **API key**: `RUNPOD_API_KEY` в `.env` (не коммитить!)
- **Endpoints** (defaults в `test_req.py` / `.env`):

| Роль | ID | Регион | Volume |
|------|-----|--------|--------|
| Primary CZ | `splmm6w2rblqkp` | EU-CZ-1 | `paradox-models` |
| Secondary RO | `88djlbwtw4sjlv` | EU-RO-1 | `witty_blush_toucan` |
| Quality T2 | `ynzpzjvcbfl656` | EU-RO-1 | `paradox-trellis2` |

- **Docker images** (GHCR): `ghcr.io/satanexist/paradox_worker`
  - **v1:** `:latest`, `:sha-<short>`, `:stable` (prod)
  - **TRELLIS.2:** `:trellis2-latest`, `:trellis2-sha-<short>` (актуальный POC: `trellis2-sha-ad1bca9`)
  - **Не использовать** обрезанный digest вручную — SHA-256 = **64** hex после `sha256:`
  - Digest копировать только из GitHub Packages / `docker inspect`, не из чата
- **Network volume** (mount `/runpod-volume` на Pod часто как `/workspace`):
  - `/runpod-volume/huggingface_cache` — кэш HF (`HF_HOME`)
  - `/runpod-volume/trellis-weights` — веса TRELLIS v1
  - `/runpod-volume/trellis2-weights` — веса TRELLIS.2-4B
  - `/runpod-volume/dinov3-vitl16-pretrain-lvd1689m` — локальный DINOv3 (Meta, не gated HF)
  - `/runpod-volume/outputs/` — GLB quality tier

### TRELLIS.2 env (endpoint)

| Key | Назначение |
|-----|------------|
| `HF_TOKEN` | HF для TRELLIS.2-4B / BiRefNet и т.п. |
| `TRELLIS2_DINOV3_PATH` | локальная HF-папка DINOv3 |
| `TRELLIS2_REMBG_MODEL` | default `ZhengPeng7/BiRefNet` |
| `TRELLIS2_OUTPUT_DIR` | default `/runpod-volume/outputs` |
| `R2_ENDPOINT_URL` | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` |
| `R2_BUCKET` | `ai-mesh-models` |
| `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | R2 **Account API token** (S3 client creds, не `cfat_`) |
| `R2_PUBLIC_BASE_URL` | `https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev` |
| `R2_REGION` | `auto` |

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
    "image_url": "https://example.com/image.png",
    "simplify": 0.98,
    "texture_size": 2048,
    "seed": 1
  }
}
```

Опциональные поля `input`:

| Поле | Default | Диапазон | Описание |
|------|---------|----------|----------|
| `simplify` | `0.98` | 0.90–0.999 | Mesh decimation (выше = детальнее) |
| `texture_mode` | `clay` | `clay` / `textured` | **Default clay** = gray mesh, skip UV/bake; `textured` = legacy bake |
| `texture_size` | `2048` | 1024 / 2048 / 4096 | Only for `texture_mode=textured` |
| `seed` | `1` | 0 … 2³¹−1 | TRELLIS random seed |
| `verbose` | `true` | bool | GLB export logs |

Ответ содержит `id`, который нужно опрашивать.

**Статус** (`GET https://api.runpod.ai/v2/{ENDPOINT_ID}/status/{id}`).

Для отладки можно использовать `/runsync`, но в проде лучше `/run` + polling/webhook.

### AI_MESH Studio — tier mapping (2026-07-20)

| UI tier | Endpoint | `input` ключи | Delivery | ETA UX |
|---------|----------|---------------|----------|--------|
| **preview** | T2 `ynzpzjvcbfl656` | `pipeline_type: "512"`, `texture_mode: "clay"`, `return_base64: false` | R2 `model_url` | cold ~6 мин / warm ~40 с |
| **quality** | T2 | `pipeline_type: "1024_cascade"`, `texture_mode: "clay"` | R2 `model_url` | cold ~8 мин / warm ~4 мин |
| legacy textured | T2 | + `texture_mode: "textured"`, `texture_size` 1024/2048 | R2 | bake UV (opt-in) |
| legacy fast | v1 RO `88djlbwtw4sjlv` | `simplify`, `texture_size`, `seed` | base64 (мелкие GLB) | ~2 мин |

**Studio backend обязан:**
1. `POST /run` → poll `/status/{id}` до terminal
2. На T2 читать `output.model_url`, не `model_base64`
3. Встроить `runpod_queue_watchdog.run_with_zombie_retries` (ghost heal)
4. ETA: если endpoint cold → показывать cold; если недавний job на том же endpoint → warm
5. `output.billing.handler_ms.model_load_ms === 0` → warm факт

**T2 input (доп. поля):** `pipeline_type`, `texture_mode`, `decimation_target`, `preprocess_image`, `remesh`, `return_base64`; `texture_size` только при `textured`.

**Clay release checklist:**
1. Push `worker_trellis2.py` → CI `build-trellis2.yml` (или `docker build -f Dockerfile.trellis2`)
2. New RunPod Release on `ynzpzjvcbfl656` with new image tag
3. Smoke: `python test_req_trellis2.py --pipeline-type 512 --texture-mode clay --save model-clay.glb`

### Studio Bridge API (POC, 2026-07-20)

Локально: `python scripts/studio_api.py` → `http://127.0.0.1:8787` (Swagger `/docs`).  
Код: `studio_bridge/`, smoke: `scripts/studio_smoke.py`.

**Base URL (dev):** `http://127.0.0.1:8787`

#### `GET /health`
```json
{ "status": "ok" }
```

#### `POST /api/jobs`
Создать async job. RunPod ключ **только на сервере**, не в браузере.

Request:
```json
{
  "mode": "image",
  "tier": "preview",
  "imageUrl": "https://example.com/photo.png",
  "seed": 1
}
```

| Поле | Тип | Обязательно | Описание |
|------|-----|-------------|----------|
| `mode` | `"image"` \| `"text"` | нет (default `image`) | `text` — позже, нужен `OPENAI_API_KEY` на бэке |
| `tier` | `"preview"` \| `"quality"` | нет (default `preview`) | preview=512/tex1024; quality=1024_cascade/tex2048 |
| `imageUrl` | string | да для `mode=image` | Публичный https URL картинки |
| `prompt` | string | да для `mode=text` | Текстовый prompt |
| `seed` | int | нет (default 1) | Seed генерации |

Response `200`:
```json
{
  "jobId": "bb74f5b8-e081-4e04-b8e4-b166a8d9fb95-e1",
  "mode": "image",
  "tier": "preview",
  "endpointId": "ynzpzjvcbfl656",
  "imageUrl": "https://...",
  "prompt": null,
  "etaSecondsCold": 360,
  "etaSecondsWarm": 45,
  "status": "queued"
}
```

Ошибки: `400` (нет imageUrl/prompt), `501` (text mode не настроен), `500`.

#### `GET /api/jobs/{jobId}?tier=preview`
Poll статуса. **Параметр `tier` обязателен совпадать с тем, что был при POST.**

Response:
```json
{
  "jobId": "...",
  "status": "queued | running | ready | failed",
  "runpodStatus": "IN_QUEUE | IN_PROGRESS | COMPLETED | ...",
  "modelUrl": "https://pub-....r2.dev/trellis2/{jobId}.glb",
  "delivery": "r2",
  "error": null,
  "etaSecondsCold": 360,
  "etaSecondsWarm": 45,
  "isWarm": false,
  "handlerMs": { "model_load_ms": 0, "inference_ms": 61972, ... },
  "delayTimeMs": 152142,
  "executionTimeMs": 245657
}
```

**Маппинг для UI:**

| `status` | Показать пользователю |
|----------|------------------------|
| `queued` | «В очереди…» |
| `running` | «Генерируем 3D…» |
| `ready` | Открыть `modelUrl` в viewer |
| `failed` | Ошибка + retry |

**ETA:** до первого poll показывать `etaSecondsCold`; если недавно был job на том же tier — `etaSecondsWarm`. После `ready`: `isWarm === true` → warm был фактически.

**Poll interval:** 3–5 с, timeout UI ~10–15 мин (preview cold до ~6 мин).

**Viewer:** GLB по `modelUrl` (Three.js / model-viewer). Не ждать base64.

**Фронт не вызывает RunPod напрямую** — только эти 2 ручки (или их копия в Next.js API routes).

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
  "generation": {
    "simplify": 0.98,
    "texture_size": 2048,
    "seed": 1,
    "verbose": true
  },
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
