# Активный контекст

> **Как пользоваться:** в начале каждого нового чата — `@memory-bank/activeContext.md`.
> В конце сессии: *«Обнови activeContext — что мы сделали»* → `git push`.
> Синхронизация вдвоём: см. `@memory-bank/teamWorkflow.md`.

Последнее обновление: **2026-08-03** — front best + метрики зафиксированы; knobs в коде; **шаги squeeze T2** (после deploy)

---

## Кто работал последним

| Поле | Значение |
|------|----------|
| Кто | Pedrokita (с Cursor агентом) |
| ПК | Windows (`D:\AI_HUB\paradox_worker`) |
| Ветка worker | `feat/trellis2-poc` |
| Фокус | **шаги squeeze T2** — 0: commit/push/CI/release → 1…5 A/B с метриками |

### Чеклист шагов (T2 knobs дожим)

| Шаг | Действие | Статус | Артефакт / критерий |
|-----|----------|--------|---------------------|
| **0** | commit+push worker/CLI/metrics → CI `trellis2` → RunPod New Release | ⏸ ждём OK на commit | image `trellis2-sha-*` |
| **1** | best + `guidance_interval 0 1` (ss+shape) | ⏸ | `…-gi01.glb` — табард? |
| **2** | best + steps **75** | ⏸ | `…-s75.glb` |
| **3** | best + shape guidance **10** | ⏸ | `…-sg10.glb` |
| **4** | best + `remesh_band 2` | ⏸ | `…-band2.glb` |
| **5** | best + `max_hole_perimeter 0.1` | ⏸ | `…-hole01.glb` |
| — | Hi3DGen | ⏸ после T2 knobs | если табард всё ещё каша |

На **каждом** job писать: `infer_s` / `exec_s` / verts / faces (CLI `--- metrics ---` + `summarize_t2_front_metrics.py`).

Best baseline для шагов 1–5:
`1536_cascade` + remesh + 700k + steps50 + RGB + seed42 → `sampler50-pro-1536-e700.glb`

### Метрики front A/B (verts/faces + время)

`infer_s` = handler `inference_ms` (без cold load). `exec_s` = RunPod `executionTime` (load+infer+export).

| label | verts | faces | MB | infer_s | exec_s | load_s |
|-------|------:|------:|---:|--------:|-------:|-------:|
| Track A seed42 | 231023 | 471924 | 8.44 | — | — | — |
| D' 1024+50+500k | 244156 | 493766 | 8.86 | 128.8 | 277.4 | 142.3 |
| F@D' project0.5 | 243477 | 499060 | 8.91 | 130.1 | 286.5 | 151.2 |
| E 1024+700k | 339869 | 688554 | 12.34 | 130.5 | 275.1 | 140.3 |
| C@D' 1536+500k | 241729 | 485780 | 8.73 | 183.3 | 327.4 | 135.3 |
| **C+E best 1536+700k** | **332711** | **669158** | **12.02** | **182.8** | **334.4** | 142.0 |
| tokens 98k (=same) | 333159 | 669892 | 12.04 | 238.5 | 459.0 | 205.0 |
| G maxq no-remesh | 428607 | 767078 | 14.35 | 197.7 | 369.1 | 167.7 |
| G+F remesh+p0.9 | 384991 | 791890 | 14.12 | 185.0 | 341.6 | 147.6 |

Скрипт: `scripts/summarize_t2_front_metrics.py` (логи часто UTF-16 от PowerShell `*>`).

### Код (локально, ждёт шаг 0 deploy)

Файлы: `worker_trellis2.py`, `test_req_trellis2.py`, `scripts/summarize_t2_front_metrics.py`, preview dropdown.
- `guidance_interval` в sampler params (HF default `[0.6,1.0]`)
- steps max **100** (было 50)
- `remesh_band`, `max_hole_perimeter`, `remove_small_cc`
- ответ: `mesh_stats` {vertices, faces}; CLI печатает timing + local GLB counts

---

## Наработки front (золотой рыцарь) — 2026-08-03

### Scope глаз
Только **перед**. Бока/спина — позже.

### Best recipe (product candidate)

```text
image          = …/smoke/ref_gold_armor.png   # RGB, НЕ cutout
preprocess     = true
pipeline_type  = 1536_cascade
remesh         = true
remesh_project = 0
decimation     = 700000
ss/shape steps = 50, guidance ~8.0/8.5
seed           = 42
texture_mode   = clay
```

| Артефакт | Роль |
|----------|------|
| `model-armor-clay-sampler50-pro-1536-e700.glb` | **текущий best** — грудь/над поясом сильно лучше; табард всё ещё каша |
| `model-armor-clay-sampler50-pro-1536.glb` | 1536+500k — big+ front |
| `model-armor-clay-sampler50-pro-e700.glb` | 1024+700k — weak+ |
| `model-armor-clay-sampler50-pro42.glb` | D' 1024+500k — рост ок, без решета |
| `model-armor-clay-seed42.glb` | Track A baseline |

Preview: `?file=model-armor-clay-sampler50-pro-1536-e700.glb`

### Жёсткие выводы

| Факт | Следствие |
|------|-----------|
| Cutout + no-preprocess | **сплющивает** — не для quality A/B |
| no-remesh / max-q G | **дыры** — не front recipe |
| `remesh_project` | **no-op** для sharpness |
| 1536 + steps50 + remesh | главный **big+** |
| denser 700k | **weak+**; табард чувствителен |
| Табард на best | всё ещё **каша** → похоже на потолок T2 occupancy |
| Красить мыло / Meshy-mesh | **нет** |
| Seed roulette | **отложено** (2026-08-03) |

Подробности: `textureWowPlan.md` § **Корневая матрица T2** + § **Остаток методик**.

---

## Простыми словами (долгосрок)

Матрица front **пройдена**. Best = 1536+remesh+700k+steps50+RGB.  
Остаток = **табард**. Дальше таблица методик (tokens / Hi3DGen / …), не kitchen-sink и не seeds.

```
Front?
├─ cutout / no-remesh G  → squash / дыры ❌
├─ remesh_project / tokens98k → no-op ❌
├─ 1536+steps50+remesh+700k → ✅ best (табард каша)
└─ дальше → шаги 0–5 knobs → Hi3DGen
```

---

## Текущий фокус

| | Статус |
|--|--------|
| Матрица A–G front | ✅ |
| Best recipe | ✅ 1536+remesh+700k+steps50 |
| Метрики verts/time | ✅ таблица в activeContext |
| tokens 98k | ✅ same |
| Код interval/band/holes/steps100 | ✅ локально |
| Deploy нового образа | ⏸ **шаг 0** |
| A/B 1–5 | ⏸ после release |
| Seeds | ⏸ не сейчас |
| Hi3DGen | ⏸ после squeeze T2 |

---

## Очередь спринта

| # | Задача | Статус |
|---|--------|--------|
| Front матрица T2 | ✅ | |
| Метрики + knobs code | ✅ | |
| **Шаг 0** commit/push/CI/release | ⏸ | |
| Шаги 1–5 A/B | ⏸ | |
| Hi3DGen | ⏸ | |

**План:** чеклист шагов в шапке activeContext.

**MV-Adapter ops:** `workersMin=0` всегда. Не serverless marathon. Pod terminate после smoke.

**Warm clay `512` (2026-07-22, 5 jobs back-to-back):**

| | JOB1 (cold) | JOB2–5 warm avg |
|--|-------------|-----------------|
| wall | 812 с | **27.3 с** |
| model_load | 233 с | 0 с |
| handler | 319 с | 23.4 с |

Endpoint: `workersMin=0` (без always-on — дорого), `workersStandby=2`, `idleTimeout=60` (T2 + texture). Первый job после простоя — cold; подряд в окне idle — **~25–31 с**. Studio warm ETA: **35 с**.

**MV-Adapter ops:** `workersMin=0` всегда (тесты тоже — cold/throttled OK). Не поднимать min перед smoke. Heal только на zombie IN_QUEUE.
- Не heal’ить перед каждым submit (Studio + smoke) — только на zombie / stuck IN_QUEUE
- `idleTimeout=60` — `scripts/set_endpoint_idle.py --seconds 60 --apply`
- Ручной heal: `python scripts/heal_t2_endpoint.py`
- FlashBoot **off**, `workersMax≥2`
- Estimate `$0.17` на одном clay = cold + delay/zombie, **не** целевой COGS (warm ~$0.02–0.03)

Warm timing: `scripts/warm_timing_t2.py --no-zombie-watch --no-heal`.

## RunPod endpoints (карта)

| Роль | Имя | ID | Регион | Volume | Статус |
|------|-----|-----|--------|--------|--------|
| Primary (CZ) | mushy_fuchsia_shark | `splmm6w2rblqkp` | EU-CZ-1 | `paradox-models` | v1, образ **stale** |
| Secondary (RO) | nasty_tan_boa | `88djlbwtw4sjlv` | EU-RO-1 | `witty_blush_toucan` | v1 OK |
| Quality (T2) | paradox-trellis2_endpoint | `ynzpzjvcbfl656` | EU-RO-1 | `paradox-trellis2` (`netu72a8j2`) | **T2 + R2 OK** |
| **Texture v1** | TRELLIS_texturing | `a968zrhd6hmj7s` | EU-RO-1 | `paradox-trellis2` | **live**; image `texture-sha-c6fa8b5`; R2 env ✅ |
| **MV-Adapter** | paradox-mvadapter | `ggjypsxh0u1djj` | EU-RO-1 | `paradox-mvadapter-storage` (`dses29m9i5`, 40GB) | **workersMin=0**; v11+volume; Release #10 timeout без кэша → retry smoke |

**`.env`:** `RUNPOD_ENDPOINT_ID_TRELLIS2=ynzpzjvcbfl656`, `RUNPOD_ENDPOINT_ID_TEXTURE=a968zrhd6hmj7s`  
(локально также могут быть `RUNPOD_S3_*` для volume S3 — **не** путать с `R2_*`)

**Env на T2 / texture (обязательные для delivery):**
- `HF_TOKEN`, `TRELLIS2_DINOV3_PATH=/runpod-volume/dinov3-vitl16-pretrain-lvd1689m`
- `R2_ENDPOINT_URL`, `R2_BUCKET=ai-mesh-models`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`
- `R2_PUBLIC_BASE_URL=https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev`, `R2_REGION=auto`

**Volume T2 содержит:** `trellis2-weights/`, `dinov3-vitl16-pretrain-lvd1689m/`, `outputs/`, `huggingface_cache/`

**CI:** `build-trellis2.yml` → `:trellis2-*`; `build-texture.yml` → `:texture-*` (thin overlay); `build-mvadapter.yml` → `:mvadapter-latest` / `:mvadapter-sha-*`.  
**RunPod Flash** — не используем. **FlashBoot** — **off**.

**Texture smoke (2026-07-23):**
- FAIL #1: R2 mesh download 403 без User-Agent → фикс `c6fa8b5`
- OK infer #2: COMPLETED ~171 с / ~$0.065; `delivery=volume` (worker до R2 env) → GLB с volume S3 `model-tex.glb`
- Clay для теста: `trellis2/51f69412-180b-4e56-b470-acb248d14341-e1.glb`

**Заметка сеть:** прямой GET volume S3 иногда stall — для продукта нужен `model_url` (R2).

**Zombie queue:** 4-я причина `IN_QUEUE` — см. `systemPatterns.md` (idle/ready + EXITED ghost). Код: `runpod_queue_watchdog.py`, `scripts/heal_t2_endpoint.py`.

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

### 10. Zombie IN_QUEUE + EXITED ghost (2026-07-16/17)

Health: `ready/idle>=1`, `inProgress=0`, job вечно `IN_QUEUE`. REST: worker `desiredStatus=EXITED` при `workersMax=1` + FlashBoot.  
**Фикс (клиент):** `runpod_queue_watchdog` — proactive DELETE ghosts, cancel/retry; `heal_t2_endpoint.py --purge`. Ops: FlashBoot off, max>=2.

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
- [x] **POC TRELLIS.2** — Docker/CI/endpoint/DINOv3 local/BiRefNet/volume+R2 delivery
- [x] Full `1024_cascade`/2048 COMPLETED + локальный `model-v2-full.glb` через R2
- [x] R2 `model_url` на T2 endpoint
- [x] Zombie watchdog + heal scripts (локально, ждать commit)
- [x] FlashBoot off / workersMax>=2 на T2
- [ ] Ротация R2 token
- [ ] A/B: сундук v1 vs TRELLIS.2; batch seeds для зада
- [ ] Commit+push watchdog + memory-bank

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
| nvdiffrast / diff_gaussian | ✅ в образе v1 |
| **DINOv3 gated HF (RU)** | ✅ обход: Meta portal → `.pth` → HF-папка на volume |
| **RMBG-2.0 gated + CC BY-NC** | ✅ rembg → `ZhengPeng7/BiRefNet` (+ `einops`) |
| Huge GLB base64 → пустой `output` | ✅ delivery volume/R2 (`ad1bca9`) |
| Zombie EXITED ghost / FlashBoot | ✅ heal + FlashBoot off + max=2; ghosts всё ещё бывают → watchdog |
| Качество mesh v1 (creatures) | 🔄 A/B vs TRELLIS.2 |
| CZ v1 stale image | ⚠️ New Release |
| EU-CZ-1 capacity | ⚠️ `throttled` — терпимо |

### TRELLIS.2 — важные факты (2026-07-15/17)

1. **HF DINOv3 reject ≠ Meta reject.** Meta portal дал `.pth`; HF-репо остался closed. Worker грузит локальный путь.
2. **Нельзя** класть ~16 MB GLB в JSON RunPod status — job COMPLETED, `output` пустой. Писать на volume / R2.
3. **RMBG-2.0** — не для commercial AI_MESH без договора BRIA; BiRefNet — POC/open rembg (= вырез фона, не «зад»).
4. Smoke CI: не `import` CUDA-расширений на buildx (нет `libcuda`) — проверка `.so` + `trellis2` config.
5. Single-image: невидимая сторона — догадка модели; улучшение POC = seeds / фото; multi-view — позже.

---

## Заметки по RunPod (важное)

- **Четыре симптома «IN_QUEUE»:**
  1. Битый digest → `initializing` мигает и пропадает
  2. `throttled` → ждёт свободный GPU в регионе (capacity)
  3. `unhealthy` → воркер стартует и падает (5090, missing deps, crash)
  4. **Zombie** → `idle/ready` + `EXITED` ghost, job не dequeue
- `:latest` — dev/починка; **`:stable`** — прод
- Network volume не шарится между регионами
- REST API endpoint config: `https://rest.runpod.io/v1/endpoints/{id}`
- GraphQL: imageName, gpuIds, gpuTypeIds, version

---

## Журнал сессий

| Дата | Кто | Что сделано | Следующий шаг |
|------|-----|-------------|---------------|
| 2026-08-03 | Pedrokita | Front best+метрики; knobs code; чеклист шагов 0–5; tokens=same | Шаг 0 commit/push/release |
| 2026-08-03 | Pedrokita | Front матрица: best=1536+remesh+700k+steps50; табард каша; seeds⏸; memory обновлена | Таблица остатка → tokens98k или Hi3DGen |
| 2026-08-02 | Pedrokita | Долгосрок = корневая матрица осей; max-q = stress G; код sampler в push | Deploy → ось D sampler |
| 2026-07-31 | Pedrokita | xatlas path; decimate 80k; GHCR Pod smoke; preview + lights | quality after latency |
| 2026-07-08 | Pedrokita | Memory-bank, test_req async, worker traceback/xformers | RunPod тест |
| 2026-07-09 | Pedrokita | Multi-endpoint fallback, watch_endpoint, CZ Release #13, support ticket | Digest fix |
| 2026-07-10 | Pedrokita | Digest fix; FlexiCubes+kaolin; CI tags; 5090 unhealthy; throttled CZ; nvdiffrast missing | Rebuild, GPU list, retest |
| 2026-07-13 | Pedrokita | Commit+push nvdiffrast; CI EGL fix `609b201`; memory-bank update | CI green → RunPod release → COMPLETED |
| 2026-07-13 | Pedrokita | Dockerfile 6.8: diff_gaussian_rasterization (mip-splatting submodule) | push → CI → New Release → retest |
| 2026-07-14 | Pedrokita | RunPod PATCH cleanup (GPU+idle); worker tuning; retest FAILED stale image | CI → New Release → retest |
| 2026-07-14 | Pedrokita | RO retest OK (дракон, сундук, 3 seeds); CZ stale; POC TRELLIS.2 scaffold | CI trellis2 → quality endpoint → A/B |
| 2026-07-15/16 | Pedrokita | T2 endpoint+volume; DINOv3 Meta; BiRefNet; volume GLB delivery; full 1024_cascade OK | Download GLB; R2; A/B vs v1 |
| 2026-07-16 | Pedrokita | R2 bucket+env на T2; smoke `delivery:r2` + local download; volume S3 с ПК не тянет | Full quality + rotate R2 token; A/B |
| 2026-07-17 | Pedrokita | Zombie watchdog; heal ghost; full `08f458cc` R2; rembg≠зад notes | FlashBoot off; rotate R2; seeds; commit |
| 2026-07-20 | Pedrokita | warm 366s→40s; seeds 1/7/42; A/B v1 vs T2 Full; unit economics canvas; Studio defaults | Визуальный A/B; мост AI_MESH contract |
| 2026-07-20 | Pedrokita | Уточнили scope: сейчас только image→3D; обсудили варианты text→3D | Выбрать MVP-путь text→image→T2 |
| 2026-07-20 веч | Pedrokita | POLY_LAB live E2E (пистолет); proxy-glb CORS; watchdog в Studio; Meshy Workspace notes | Commit POLY_LAB; warm; library UX |
| 2026-07-22 | Pedrokita | Warm 5× clay: cold 812s wall, warm avg 27.3s; ETA Studio 35s | Best-of-N отложен |
| 2026-07-23 | Pedrokita | Push recipes + warm script; seed UX clarified (same model only) | Upload hints / Library |
| 2026-07-23 | Pedrokita | Upload quality hints (`imageQuality.ts`) in Studio | Library UX |
| 2026-07-23 | Pedrokita | Image Enhancement toggle (`imageEnhance.ts`) — 2D preprocess | Library UX |
| 2026-07-23 | Pedrokita | Library UX: All/Clay/Tex/Фото/Текст filters + badges | Auth + credits mock |
| 2026-07-23 | Pedrokita | Credits mock + demo auth; job charges 4/12 cr | Clerk or Texture фаза 2 |
| 2026-07-23 | Pedrokita | Texture v0: Studio action=texture → legacy bake | Mesh paint worker (T1) |
| 2026-07-23 | Pedrokita | T1a scaffold: `worker_texture.py`, Dockerfile.texture, test_req_texture | T1b: build+endpoint+smoke |
| 2026-07-23 | Pedrokita | Thin texture Dockerfile + `build-texture.yml` → GHCR | Ждать CI; создать RunPod endpoint |
| 2026-07-24 | Pedrokita | Баланс OK → Pod `zhdeac3dd4otww` A6000; zip `mvadapter_w2_upload.zip` | Upload + bootstrap smoke |
| 2026-07-28 | Pedrokita | W2 smoke green: `knight_i2tex_shaded.glb`; A/B лучше cascade; дыры+мыло → W2b plan | W2b mesh repair + preprocess_mesh |
| 2026-07-29 | Pedrokita | Endpoint `ggjypsxh0u1djj` deployed; smoke fail spandrel→cv2; CI fixes pushed | New Release + smoke retry |
| 2026-07-24 | Pedrokita | W2 GO: MV-Adapter Apache-2.0; spike.md + Dockerfile.mvadapter | Pod smoke рыцарь |
| 2026-07-23 | Pedrokita | Texture endpoint `a968zrhd6hmj7s`; UA fix; infer smoke OK; warm ops idle=60 / no pre-heal | R2 retest smoke; Studio T1c |

---

## Недавние решения

| Дата | Что | Заметки |
|------|-----|---------|
| 2026-08-02 | **T2 A/B FAIL на HF** | no-remesh/1536 denser ≈ Meshy polycount; орнамент всё ещё каша → потолок T2 micro, не только export |
| 2026-08-01 | **Сначала чинили T2 export** | Проверили; не хватило |
| 2026-07-31 | **Мыльный меш → не красить; E2 нет** | Unit economics |
| 2026-07-28 | **W2 smoke partial pass** | Tex лучше cascade; дыры = mesh T2 + UV gaps; мыло = JPEG + нет PBR |
| 2026-07-24 | **Meshy рыцарь = эталон** (1 photo): меш+зад+tex | Наш cascade mid; вау через новый stack |
| 2026-07-24 | **Meshy вау с 1 фото** — не user multi-view | Разрыв = их synth MV + models; наш cascade проигрывает |
| 2026-07-24 | **Вау-first по текстурам** | Paint v1 frozen; T1c off; план `textureWowPlan.md`; цель 1 img → synth MV → bake |
| 2026-07-23 | **Texture v1 = отдельный endpoint/образ** (не мультитаск на T2) | Endpoint `a968zrhd6hmj7s`; image `texture-sha-c6fa8b5`; volume тот же `paradox-trellis2`. v0 bake = Studio fallback |
| 2026-07-23 | Warm без `workersMin` | idleTimeout=60; не heal перед submit; always-on слишком дорого для POC |
| 2026-07-22 | Clay-first: `texture_mode=clay|textured` в worker; Studio default clay; T2-friendly polish | Release `6d763fa` + smoke OK |
| 2026-07-22 | Industry Quality Recipes в Studio (presets → polish/T2I/decimation) | Warm economics |
| 2026-07-20 | Unit economics: self-host 2–4× дешевле API; не клон Meshy; warm = ключ к марже | canvas + platformRoadmap § measured |
| 2026-07-20 | Text→3D: в текущем worker отсутствует; MVP-вариант = text→image→T2 | отдельный text2mesh endpoint — позже |
| 2026-07-20 | Studio tiers: preview=`512`/1024, quality=`1024_cascade`/2048 | ETA cold/warm в UX |
| 2026-07-20 веч | POLY_LAB live + zombie watchdog (client); Release не нужен; wall≠cold | meshyWorkspace.md |
| 2026-07-20 | Warm T2 `512`: load 0 → wall ~40 с (vs cold ~6 мин) | Studio ETA: cold vs warm честно |
| 2026-07-17 | rembg (BiRefNet) ≠ додумывание зада; зад = модель + seed/multi-view later | UX: не ждать «плагин спины» в POC |
| 2026-07-17 | Watchdog: proactive DELETE EXITED ghosts + heal после zombie | клиент/Studio, не GPU handler |
| 2026-07-17 | Zombie queue watchdog (idle/ready + IN_QUEUE) | `runpod_queue_watchdog` + heal script |
| 2026-07-16 | T2 delivery: volume + **R2 `model_url`** (prod path) | bucket `ai-mesh-models`; pub-c826…r2.dev |
| 2026-07-16 | Full quality T2: volume path, не base64 | `ad1bca9`; base64 только мелкие |
| 2026-07-16 | rembg = BiRefNet, не RMBG-2.0 | gated + NC |
| 2026-07-15 | DINOv3 с Meta CDN → convert → volume | HF geo-reject из РФ |
| 2026-07-13 | **platformRoadmap.md** — 4 фичи AI_MESH | Сессия стратегии |
| 2026-07-13 | Core = self-host, не SaaS API | Unit economics |
| 2026-07-14 | POC TRELLIS.2: отдельный Docker/worker/CI | Параллельно v1 |
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

**v1 (RO):**
```powershell
cd D:\AI_HUB\paradox_worker
$env:PYTHONUTF8=1
.\.venv\Scripts\python.exe test_req.py
```

**TRELLIS.2 (clay / textured):**
```powershell
cd D:\AI_HUB\paradox_worker
$env:PYTHONUTF8=1
.\.venv\Scripts\python.exe test_req_trellis2.py --pipeline-type 512 --texture-mode clay --save model-clay.glb
# legacy bake:
.\.venv\Scripts\python.exe test_req_trellis2.py --pipeline-type 512 --texture-mode textured --texture-size 1024 --save model-tex.glb
```
```powershell
.\.venv\Scripts\python.exe test_req_trellis2.py --pipeline-type 1024_cascade --texture-size 2048 --save model-v2-full.glb
# ожидание: delivery=r2, model_url=https://pub-….r2.dev/trellis2/<job>.glb
# viewer: python -m http.server 8765 → /scripts/view_model.html?model=/model-v2-full.glb
# heal: .\scripts\heal_t2_endpoint.py --purge
```

Ожидаем T2: `"status": "COMPLETED"` + `delivery: "r2"` + `model_url`.
