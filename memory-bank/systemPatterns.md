# Архитектура и решения

## Pipeline: URL картинки → GLB base64

```
Клиент (test_req.py или будущий сайт)
    │
    ▼ POST /runsync { input: { image_url } }
RunPod Serverless
    │
    ▼ handler(job)
worker.py
    ├─ load_model()          [лениво, один раз на lifetime воркера]
    ├─ скачать картинку        [urllib + User-Agent]
    ├─ pipeline.run(image)   [TRELLIS, seed=1]
    ├─ postprocessing_utils.to_glb(gaussian, mesh) → .export(path)
    └─ return model_base64
```

## Паттерны RunPod / TRELLIS (не ломать)

### 1. Network volume для весов

```python
os.environ["HF_HOME"] = "/runpod-volume/huggingface_cache"
snapshot_download(..., local_dir="/runpod-volume/trellis-weights")
```

Веса должны жить на примонтированном volume — после первого запуска cold start быстрый.

### 2. Symlink для ckpts TRELLIS

TRELLIS ищет чекпоинты в `/app/ckpts`. Symlink на реальный путь в скачанных весах:

```python
os.symlink(os.path.join(model_path, "ckpts"), "/app/ckpts")
```

Не убирать без проверки путей загрузки TRELLIS.

### 3. Ленивая загрузка модели

`pipeline = None` глобально; `load_model()` при первом job. Быстрый старт воркера, GPU не трогаем без задачи.

### 4. Очистка temp-файлов

PNG и GLB удаляются после base64. GLB кратко в памяти — ок для MVP.

### 5. Attention backend: xformers (без flash-attn)

В некоторых окружениях TRELLIS по умолчанию пытается импортировать `flash_attn` и падает с:
`ModuleNotFoundError: No module named 'flash_attn'`.

Решение для нашего Dockerfile (где установлен `xformers`): форсировать backend до загрузки TRELLIS:

```python
os.environ.setdefault("ATTN_BACKEND", "xformers")
```

### 6. Полный traceback в логах RunPod

Ошибки вида `... is not defined` или падения внутри зависимостей невозможно чинить “вслепую”.
Поэтому при исключениях в `handler()` печатаем полный stacktrace в RunPod logs (`traceback.format_exc()`),
а в ответ возвращаем короткое `{ "error": "..." }`.

## Журнал решений

| Дата | Решение | Почему |
|------|---------|--------|
| 2026 | GLB как base64 в JSON | Проще всего для MVP, без S3 |
| 2026 | `runsync` для тестов | Удобнее async poll при разработке |
| 2026 | seed=1 фиксированный | Воспроизводимый тест; позже — параметр в input |
| 2026 | TRELLIS vendored в репо | Контроль Dockerfile, патч FlexiCubes |
| 2026-07-08 | `ATTN_BACKEND=xformers` | Избежать зависимости `flash_attn` и падений на старте |
| 2026-07-08 | Печатать полный traceback в logs | Быстрее диагностировать падения внутри зависимостей |
| 2026-07-10 | Не pin digest вручную в RunPod UI | Обрезанный SHA-256 (63 chars) ломает pull; симптом = IN_QUEUE / Initializing loop |
| 2026-07-10 | Docker, не RunPod Flash | TRELLIS + CUDA 11.8 + vendored код — только кастомный образ |
| 2026-07-10 | MaxtirError FlexiCubes + kaolin in Docker | nv-tlabs fork uses `from tables import *` → `dmc_table` NameError in serverless |
| 2026-07-10 | Только 24GB Ampere/Ada GPU на endpoint | CUDA 11.8 образ несовместим с RTX 5090 / Blackwell |
| 2026-07-13 | nvdiffrast в Docker с EGL + no-build-isolation | GLB export требует MeshRenderer; CI падал без libegl-dev |
| 2026-07-13 | Smoke test URL → T.png | fox.png в TRELLIS repo 404 |

## Будущее (когда будет сайт)

- **Upload**: браузер → ваш API → URL картинки → RunPod (тот же контракт)
- **Большие модели**: S3 presigned URL вместо base64, если GLB > ~5 MB
- **Async**: RunPod `/run` + polling или webhooks вместо `/runsync`
- **Multi-endpoint (HA на serverless)**: 2 endpoint'а в разных регионах + fallback по времени в `IN_QUEUE`
- **Несколько воркеров**: отдельные endpoint'ы под generate, retopo, texture, rig/anim — см. `platformRoadmap.md`

## Паттерн: Multi-worker pipeline (AI_MESH)

Платформа = **4 инструмента на сайте**, каждый — отдельный RunPod endpoint (не один fat Docker):

| task_type | Worker | Модель (open-source) | VRAM |
|-----------|--------|----------------------|------|
| `generate` (quality) | paradox_worker → v2 | TRELLIS.2 | 24 GB |
| `generate` (fast) | paradox-sf3d | SF3D / TripoSR | 6–8 GB |
| `retopo` | paradox-retopo | FastMesh, PartUV | 16–24 GB |
| `texture` | paradox-texture | TRELLIS paint | ~8 GB |
| `rig` / `animate` | paradox-rig | UniRig + motion presets | ~9 GB |

Backend AI_MESH роутит по `task_type` + `model_tier` → `RUNPOD_ENDPOINT_ID`.

**Экономика (измерено 2026-07-20):** T2 preview cold ~$0.13 / warm ~$0.03; T2 Full cold ~$0.16 / warm ~$0.08; v1 ~$0.04. API Meshy/Tripo ~$0.30–0.60 — core только self-host. Доля warm = ключ к blended COGS.

**EU:** MIT/Apache модели; Hunyuan (EU license ban) — не в prod pipeline.

Детали, фазы, pricing: `@memory-bank/platformRoadmap.md`.

## Паттерн: Multi-endpoint fallback (serverless HA)

Проблема: в serverless бывают периоды, когда **в одном регионе нет свободных GPU** (долгий `IN_QUEUE`, `Throttled`).

Решение:

- Поднять **2 endpoint'а** с одним и тем же образом воркера в **разных регионах** (например, EU и US).
- В каждом регионе иметь свой **network volume** (веса кэшируются локально в регионе; volume не шарится между регионами).
- На стороне клиента/сайта:
  - Отправить job в primary endpoint (`/run`).
  - Если job остаётся в `IN_QUEUE` дольше \(X\) минут → отменить и отправить в secondary endpoint.
  - Дальше обычный polling `/status/{id}` до `COMPLETED/FAILED`.

Минимальный безопасный UX:
- Free: ждать capacity \(X\) минут, потом просить повторить позже.
- Paid: включать fallback в другой регион и/или более широкий список GPU.

## Паттерн: Controlled rollout через теги образа (prod)

Проблема: в serverless нестабильна не только capacity, но и **релизы** (новый образ может сломать старт/инференс).

Решение: деплоить endpoint'ы по Docker image **с версионированными тегами** и отдельным тегом **`stable`**:

- `ghcr.io/.../paradox_worker:vX.Y.Z` — неизменяемый релиз (или date-based: `v2026-07-09-1`)
- `ghcr.io/.../paradox_worker:stable` — “боевой указатель” на последнюю проверенную версию
- Не использовать `latest` как продовый тег.

Процесс (канарейка):
1. Собрать и запушить `vX.Y.Z`.
2. Обновить **secondary endpoint** (резервный регион) на `vX.Y.Z` и прогнать 1–2 job.
3. Если ок — передвинуть `stable` на `vX.Y.Z` (или обновить primary на `vX.Y.Z`).
4. Обновить **primary endpoint**.

Связка с Multi-endpoint:
- Multi-endpoint решает **capacity** (где есть свободный GPU).
- Controlled rollout решает **надёжность релизов** (не ломаем всё сразу).

## Конспект T2 POC: кто что делает (2026-07-17)

Цепочка: **клиент → RunPod → GPU worker → volume + R2 → клиент качает GLB**.

| Кто | Роль | Что делает | Чего НЕ делает |
|-----|------|------------|----------------|
| **Пользователь / Pedrokita** | заказчик, ops | смотрит GLB, крутит seed/params, UI RunPod (FlashBoot, max workers), ротация ключей | не Terminate'ит воркеры вручную в проде |
| **Клиент сейчас** (`test_req_trellis2.py`) | отправка job + watchdog | submit `/run`, poll status/health, перед submit — DELETE EXITED ghosts, zombie → cancel/heal/retry, скачать по `model_url` | не считает 3D |
| **Клиент позже** (AI_MESH Studio backend) | то же, что тест | встроить `runpod_queue_watchdog` + `RUNPOD_API_KEY` на сервере | не в браузере пользователя |
| **GPU worker** (`worker_trellis2.py`) | инференс | картинка → BiRefNet → TRELLIS.2 → remesh → **clay GLB** (default) или textured bake → volume + R2 | не чистит очередь RunPod |
| **RunPod Serverless** | оркестратор | очередь, scale workers, billing | иногда врёт health (`ready` при EXITED) — zombie |
| **Network volume** `paradox-trellis2` | кэш + бэкап GLB | веса, DINOv3, `outputs/*.glb` | не для скачивания с ПК (S3 stall) |
| **Cloudflare R2** | публичная доставка | `model_url` для Studio/ПК | не считает 3D |
| **Heal-скрипт** (`scripts/heal_t2_endpoint.py`) | ops / cron | purge queue + DELETE EXITED | не генерация |

**Статус кода (важно):**
- T2 full + R2 + smoke/full GLB локально — **работает**
- Watchdog/heal — **в рабочей копии, ещё не в git** (`feat/trellis2-poc`, tip образа `ad1bca9`)

**Zombie одной фразой:** health говорит «worker готов», REST — `desiredStatus=EXITED`, job в `IN_QUEUE` → клиент сносит ghost и ретраит; пользователь в UI для этого не нужен.

## Паттерн: Zombie queue watchdog (FlashBoot / stale idle)

Проблема (2026-07-16/17): health показывает `workers.idle≥1` / `ready≥1`, `jobs.inProgress=0`, job вечно `IN_QUEUE`. Worker «готов» по метрикам, но **не деqueues** — часто после FlashBoot / ночного простоя.

Это **не** capacity (`throttled`) и не битый digest (`initializing`).

Решение на стороне клиента / Studio (не пользователя):

1. Poll `/status` + `/health`.
2. Если `IN_QUEUE` ≥ ~60–90s **и** `(ready+idle)>0` **и** `inProgress=0` **и** `throttled=0` → **zombie**.
3. `POST /cancel/{id}`.
4. **Heal:** `GET .../endpoints/{id}?includeWorkers=true` → `DELETE /v1/pods/{podId}` для `desiredStatus=EXITED` (ghost FlashBoot), опц. `purge-queue`.
5. Retry submit (до N раз); опц. secondary endpoint (`RUNPOD_ENDPOINT_ID_TRELLIS2_SECONDARY`).
6. Ops: FlashBoot на T2 — **off** (решение 2026-07-20); `workersMax≥2`; `workersStandby=0` если доступно; клиентский heal остаётся страховкой.

Код:
- `runpod_queue_watchdog.py` — детект + heal + retry (переиспользовать в AI_MESH)
- `test_req_trellis2.py` — вызывает watchdog
- `scripts/heal_t2_endpoint.py` — ручной/cron heal без генерации
- `scripts/diagnose_t2_queue.py` — live probe очереди

## Диагностика «IN_QUEUE» на RunPod

Четыре разных корневые причины с похожим симптомом:

| Симптом в health | Причина | Что делать |
|------------------|---------|------------|
| `initializing` мигает, `running=0` | Битый digest / pull fail | Тег вместо `@sha256:...`, проверить 64 hex |
| `throttled > 0`, долго `inQueue` | Capacity региона | Ждать 1–2 мин; fallback RO; расширить GPU list (24GB) |
| `unhealthy > 0` | Crash при старте/inference | Логи воркера; убрать 5090; проверить deps в образе |
| `idle/ready≥1`, `inProgress=0`, job в `IN_QUEUE` | **Zombie worker** (FlashBoot/stale) | `ensure_no_ghost_workers` + cancel/retry; FlashBoot off; max≥2 |

## Качество image→3D: rembg vs «зад»

Не путать два «плагина»:

| Что | Роль | Влияние на невидимую сторону |
|-----|------|------------------------------|
| **BiRefNet** (`preprocess_image`) | вырез фона на входе | почти нет |
| **TRELLIS.2 сама** | додумывает объём/текстуру сзади по одному кадру | да, но это догадка |
| **seed / best-of-N** | разные догадки | часто лучший рычаг в POC |
| **multi-view (2–4 фото)** | реальные данные сзади | позже, не в текущем POC |

Отдельного rembg-плагина «нарисуй красивый зад» нет. UX Studio: не обещать «идеальную спину» с одного фото.

## Конвенции кода

- Handler возвращает `{"error": "..."}` при ошибке, не кидает exception наружу
- `print()` для логов в RunPod dashboard
- Комментарии в worker могут быть на русском; новый код — комментарии на английском
- Не коммитить `.env`, ключи, бинарные GLB
