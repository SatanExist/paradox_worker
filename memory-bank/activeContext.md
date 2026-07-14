# Активный контекст

> **Как пользоваться:** в начале каждого нового чата — `@memory-bank/activeContext.md`.
> В конце сессии: *«Обнови activeContext — что мы сделали»* → `git push`.
> Синхронизация вдвоём: см. `@memory-bank/teamWorkflow.md`.

Последнее обновление: **2026-07-14** (retest v1 + старт POC TRELLIS.2)

---

## Кто работал последним

| Поле | Значение |
|------|----------|
| Кто | Pedrokita (с Cursor агентом) |
| ПК | Windows (`D:\AI_HUB\paradox_worker`) |
| Ветка | `feat/trellis2-poc` |
| Коммит | `feat/trellis2-poc` — TRELLIS.2 POC + memory-bank session update |

---

## Текущий фокус

**Фаза 0 (v1):** RO ✅ свежий образ, CZ ⚠️ **всё ещё stale** (`render_glb` error). Нужен **New Release** на CZ.

**Фаза 1 (quality):** **POC TRELLIS.2** — ветка `feat/trellis2-poc`:
- `Dockerfile.trellis2`, `worker_trellis2.py`, CI `build-trellis2.yml`
- Образ: `ghcr.io/satanexist/paradox_worker:trellis2-sha-<short>`
- Отдельный RunPod endpoint (24GB, CUDA 12.4) — **ещё не создан**

**v1 retest 2026-07-14:** RO COMPLETED (дракон seed 42, сундук, best-of-N seeds 1/7/123). CZ FAILED на том же коде.

**Качество v1:** props (сундук) — рабочий MVP; creatures (дракон) — слабо; чёрные дыры на UV bake — лимит `to_glb` v1, не баг воркера.

**Полный план (4 фичи сайта, модели, economics):** `@memory-bank/platformRoadmap.md`

**Ключевые решения сессии 2026-07-13:**
- Core AI_MESH = **self-host RunPod**, не Tripo/Meshy/fal API (unit economics)
- Следующий quality tier: **TRELLIS.2** (MIT, EU)
- **Hunyuan** — не EU prod (лицензия Tencent)
- Сайт: generate → retopo → texture → rig/anim — **отдельные workers по фазам**

---

## RunPod endpoints (карта)

| Роль | Имя | ID | Регион | Volume | Версия (API) |
|------|-----|-----|--------|--------|--------------|
| Primary (CZ) | mushy_fuchsia_shark | `splmm6w2rblqkp` | EU-CZ-1 | `paradox-models` → `/runpod-volume` | v16 (GPU+idle) — **образ stale** |
| Secondary (RO) | nasty_tan_boa | `88djlbwtw4sjlv` | EU-RO-1 | `witty_blush_toucan` → `/runpod-volume` | v12 — **свежий образ, COMPLETED** |
| Quality (T2) | *(создать)* | — | EU-RO/CZ | отдельный volume | `trellis2-sha-...` |

**Образ v1 (целевой):** immutable `:sha-4dd1f7f` или `:stable` после promote.

**CI v1** (`build.yml`): `:latest`, `:vYYYY-MM-DD-<run>`, `:sha-<short>`.  
**CI v2** (`build-trellis2.yml`): `:trellis2-latest`, `:trellis2-sha-<short>`.  
**Прод:** `workflow_dispatch` → promote в `:stable` (только v1 пока).

**RunPod Flash** (Deploy with Flash в UI) — **не используем**. **FlashBoot** — можно оставить ON.

---

## Инциденты и корневые причины (хронология)

### 1. 48ч IN_QUEUE — битый digest (2026-07-10, RunPod Support)

**Не capacity.** Support (Hector Vallejos): обрезанный SHA-256 (**63** hex вместо 64) → pull падает → воркер мигает `Initializing` → jobs в `IN_QUEUE`.

Битый digest (не использовать):
```
sha256:2131ce5fa2429c77d79c882bbddd667d3df6debc41c3710e5c58108fc812c6d  ← 63 chars
```

**Фикс:** тег `:latest` или полный digest из GHCR, не из чата.

### 2. Inference `dmc_table` NameError (2026-07-10)

nv-tlabs FlexiCubes с `from tables import *` ломается как submodule TRELLIS.

**Фикс:** `cf84884` — MaxtirError/FlexiCubes @ `f97beb0` + kaolin cu118.

### 3. Тестовая картинка 404 (2026-07-10)

`fox.png` в `example_images/` — **404**. Рабочий URL: `example_image/T.png`.

**Фикс:** `0d59207` — `test_req.py` → `T.png`.

### 4. RO Unhealthy на RTX 5090 (2026-07-10, Release #6)

После добавления **AMPERE_48 / RTX 5090** воркеры `unhealthy=1`, job в `IN_QUEUE` бесконечно.  
На **RTX 4090** модель уже грузилась в VRAM; падение было только на fox 404.

**Причина:** CUDA 11.8 / torch 2.0.1 **несовместим с Blackwell (5090)** и 48GB tier.

### 5. CZ «не находит workers» — throttled (2026-07-10/13)

Live-тест: `throttled=1` ~60–90 сек, потом `ready=1` → `IN_PROGRESS`.  
В EU-CZ-1 tier **24GB = Unavailable** в UI — это **capacity**, не digest-баг. Выглядит как старый IN_QUEUE.

### 6. Job FAILED: `No module named 'nvdiffrast'` (2026-07-10)

Inference доходит до GLB export, но в образе не было nvdiffrast.

**Фикс:** `0d59207` + `609b201` — nvdiffrast в Dockerfile (EGL deps, `--no-build-isolation`, `TORCH_CUDA_ARCH_LIST`).

### 7. CI build fail на nvdiffrast (2026-07-13)

`EGL/egl.h: No such file or directory` при `pip install` без dev-пакетов.

**Фикс:** `609b201` — libegl1-mesa-dev и др. + `PYOPENGL_PLATFORM=egl`.

### 8. Job FAILED: `No module named 'diff_gaussian_rasterization'` (2026-07-13)

После nvdiffrast inference доходит до `to_glb` → `render_multiview` → `GaussianRenderer`, но в образе не было mip-splatting / diff-gaussian-rasterization.

**Фикс:** Dockerfile 6.8 — `git clone autonomousvision/mip-splatting` + `pip install .../submodules/diff-gaussian-rasterization/` (как `setup.sh --mipgaussian`).

### 9. Первый `COMPLETED` + сохранение GLB локально (2026-07-13)

Сгенерирован `COMPLETED` на RO (`88djlbwtw4sjlv`). GLB можно скачать без копирования base64 через скрипт:
`scripts/save_glb_from_status.py` → сохраняет `model.glb`.

---

## Сделано

- [x] RunPod Serverless worker с TRELLIS-image-large
- [x] Docker CUDA 11.8 + deps + FlexiCubes (MaxtirError) + kaolin + **nvdiffrast**
- [x] Кэш весов на network volume
- [x] `test_req.py`: async `/run` + polling + fallback CZ→RO + **T.png**
- [x] `scripts/watch_endpoint.py`
- [x] Support ticket → malformed digest
- [x] CZ Release #13: `RUNPOD_SOURCE_PATH` удалён
- [x] CI: version tags + manual `:stable` promote (`30d3565`)
- [x] Диагностика 5090 / throttled / nvdiffrast (live API + job poll)

---

## В работе (прямо сейчас)

- [x] **RunPod:** GPU list → только 4090/A5000/L4/3090 (PATCH API, v16/v12)
- [x] **RunPod:** `idleTimeout` → **10s** (было 180 CZ / 40 RO)
- [x] **Worker tuning:** `simplify=0.98`, `texture_size=2048`, `seed` в input
- [x] `scripts/cleanup_endpoints.py` — audit + `--apply`
- [ ] **New Release** на **CZ** (RO уже OK)
- [ ] Promote `:stable` v1 после стабильных тестов
- [x] **POC scaffold TRELLIS.2** — Dockerfile, worker, CI (ветка `feat/trellis2-poc`)
- [ ] CI green `build-trellis2` → deploy quality endpoint
- [ ] A/B: сундук v1 vs TRELLIS.2

---

## Чеклист RunPod (актуальный)

### GPU types — на ОБОИХ endpoint'ах

**Убрать:**
- NVIDIA GeForce RTX 5090
- NVIDIA B300 MIG 34GB
- NVIDIA A40, NVIDIA RTX A6000 (48GB)
- Tier `ADA_32_PRO`, `AMPERE_48` в gpuIds

**Оставить (приоритет):**
- RTX 3090, RTX 4090, RTX A5000, L4
- PRO 6000 MIG 24GB (fallback, Low Supply в CZ)

Только **24GB Ampere/Ada** — образ собран под CUDA 11.8.

### Образ

```
ghcr.io/satanexist/paradox_worker:latest
```
или immutable `v2026-07-13-XX` после CI. **Без** обрезанного `@sha256:...`.

### Env на endpoint

- **Нет** `RUNPOD_SOURCE_PATH`
- Рекомендуется: `RUNPOD_INIT_TIMEOUT=900` (cold start ~15 GB весов)
- Model field: пусто

### CZ (`splmm6w2rblqkp`, v14)

1. Edit → GPU list (см. выше)
2. Image → свежий тег
3. Volume `paradox-models` → `/runpod-volume` — не трогать
4. Save → New Release → rollout 100%

### RO (`88djlbwtw4sjlv`, v6 — **ещё не обновлялся!**)

1. То же GPU list
2. Image → тот же тег что CZ
3. Volume `witty_blush_toucan` — не трогать
4. Save → New Release

### Проверка

```powershell
cd D:\AI_HUB\paradox_worker
$env:PYTHONUTF8=1
.\.venv\Scripts\python.exe scripts\watch_endpoint.py --once
.\.venv\Scripts\python.exe test_req.py
```

Ожидаем: `throttled` 1–2 мин (CZ) → `ready=1` → `IN_PROGRESS` → `COMPLETED`.

Тестовый URL картинки:
```
https://raw.githubusercontent.com/microsoft/TRELLIS/main/assets/example_image/T.png
```

---

## Блокеры

| Блокер | Статус |
|--------|--------|
| Битый digest | ✅ снят |
| FlexiCubes `dmc_table` | ✅ в образе |
| nvdiffrast missing | ✅ в Dockerfile |
| nvdiffrast CI build | ✅ `609b201` |
| diff_gaussian_rasterization missing | ✅ фикс в образе (mip-splatting submodule) |
| Качество mesh слабое (single-image) | 🔄 R&D: multi-image + альтернативные модели |
| 5090 / 48GB GPU | ⚠️ убрать в UI (RO всё ещё v6 с 5090 первым) |
| EU-CZ-1 capacity | ⚠️ `throttled` 1–2 мин — терпимо, не баг |

---

## Заметки по RunPod (важное)

- **Три разных симптома «IN_QUEUE»:**
  1. Битый digest → `initializing` мигает и пропадает
  2. `throttled` → ждёт свободный GPU в регионе (capacity)
  3. `unhealthy` → воркер стартует и падает (5090, missing deps, crash)
- `:latest` — dev/починка; **`:stable`** — прод
- Network volume не шарится между регионами
- REST API endpoint config: `https://rest.runpod.io/v1/endpoints/{id}`
- GraphQL: imageName, gpuIds, gpuTypeIds, version

---

## Журнал сессий

| Дата | Кто | Что сделано | Следующий шаг |
|------|-----|-------------|---------------|
| 2026-07-08 | Pedrokita | Memory-bank, test_req async, worker traceback/xformers | RunPod тест |
| 2026-07-09 | Pedrokita | Multi-endpoint fallback, watch_endpoint, CZ Release #13, support ticket | Digest fix |
| 2026-07-10 | Pedrokita | Digest fix; FlexiCubes+kaolin; CI tags; 5090 unhealthy; throttled CZ; nvdiffrast missing | Rebuild, GPU list, retest |
| 2026-07-13 | Pedrokita | Commit+push nvdiffrast; CI EGL fix `609b201`; memory-bank update | CI green → RunPod release → COMPLETED |
| 2026-07-13 | Pedrokita | Dockerfile 6.8: diff_gaussian_rasterization (mip-splatting submodule) | push → CI → New Release → retest |
| 2026-07-14 | Pedrokita | RunPod PATCH cleanup (GPU+idle); worker tuning; retest FAILED stale image | CI → New Release → retest |
| 2026-07-14 | Pedrokita | RO retest OK (дракон, сундук, 3 seeds); CZ stale; POC TRELLIS.2 scaffold | CI trellis2 → quality endpoint → A/B |

---

## Недавние решения

| Дата | Что | Заметки |
|------|-----|---------|
| 2026-07-13 | **platformRoadmap.md** — 4 фичи AI_MESH, модели, фазы, API vs self-host | Сессия стратегии |
| 2026-07-13 | Core = self-host, не SaaS API | Unit economics |
| 2026-07-14 | POC TRELLIS.2: отдельный Docker/worker/CI, xformers POC | Параллельно v1, не ломать legacy |
| 2026-07-13 | TRELLIS.2 next; Hunyuan off EU prod | MIT + license |
| 2026-07-13 | nvdiffrast: EGL deps + `--no-build-isolation` + `TORCH_CUDA_ARCH_LIST` | Официальный рецепт NVlabs для Docker |
| 2026-07-13 | Smoke test image → `T.png` | fox.png 404 |
| 2026-07-10 | Не использовать 5090/B300 с CUDA 11.8 | Только 24GB Ampere/Ada |
| 2026-07-10 | CI tags + manual `:stable` | `30d3565` |
| 2026-07-10 | MaxtirError FlexiCubes + kaolin | `cf84884` |
| 2026-07-10 | `:latest` вместо битого digest | Support |
| 2026-07-10 | Не RunPod Flash | Кастомный Docker |
| 2026-07-09 | CZ Release #13: убрать `RUNPOD_SOURCE_PATH` | |
| 2026-07-08 | Multi-endpoint fallback | `test_req.py` |

---

## Быстрый тест

```powershell
cd D:\AI_HUB\paradox_worker
$env:PYTHONUTF8=1
.\.venv\Scripts\python.exe scripts\watch_endpoint.py --once
.\.venv\Scripts\python.exe test_req.py
```

Ожидаем: JSON с `"status": "success"` и `"model_base64"`.
