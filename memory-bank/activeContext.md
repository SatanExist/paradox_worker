# Активный контекст

> **Как пользоваться:** в начале каждого нового чата — `@memory-bank/activeContext.md`.
> В конце сессии: *«Обнови activeContext — что мы сделали»* → `git push`.
> Синхронизация вдвоём: см. `@memory-bank/teamWorkflow.md`.

Последнее обновление: **2026-07-17** (full quality R2 OK + zombie heal + quality notes)

---

## Кто работал последним

| Поле | Значение |
|------|----------|
| Кто | Pedrokita (с Cursor агентом) |
| ПК | Windows (`D:\AI_HUB\paradox_worker`) |
| Ветка | `feat/trellis2-poc` |
| Коммит | `ad1bca9` — GLB delivery volume/R2; образ `trellis2-sha-ad1bca9` (watchdog ещё локально) |

---

## Текущий фокус

**Фаза 1 (quality) — TRELLIS.2 + R2 + watchdog OK:**
- Endpoint `ynpzjvcbfl656` (EU-RO-1), volume `paradox-trellis2` (`netu72a8j2`)
- Образ: `ghcr.io/satanexist/paradox_worker:trellis2-sha-ad1bca9`
- R2 bucket `ai-mesh-models`, pub: `https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev`
- Smoke `512`/1024 → `model-v2-r2.glb` (~3.5 MB), job `5717f49f-…-e2`
- **Full** `1024_cascade`/2048 → `model-v2-full.glb` (~16.7 MB), job `08f458cc-9412-45b6-88fc-ccab2c3eab07-e2`, ~$0.13, `delivery: r2`
- Zombie: ghost `EXITED` блокировал очередь → `heal_t2_endpoint.py --purge` + `runpod_queue_watchdog` (DELETE ghosts + cancel/retry)
- Визуально: лицо/шипы ок; **невидимая сторона** слабее (нормально для single-image)

**Качество / «допы» (не путать):**
- **BiRefNet** (`preprocess_image`) = вырез фона, **не** «додумать зад»
- Зад додумывает сама TRELLIS.2; рычаги POC: `seed` / best-of-N, ракурс фото, pipeline/texture
- Отдельного плагина «красивый зад» нет; multi-view — позже (не POC)

**Фаза 0 (v1):** RO OK; CZ stale — не блокер T2.

**Следующие шаги:**
1. Endpoint ops: FlashBoot **off** ✅; `workersMax=2` ✅; `workersStandby` всё ещё **2** (если в UI есть — поставь 0)
2. **Ротация R2 API token** (светился в чате) + обновить env
3. Batch seeds на сундуке (сравнить зад) и/или A/B v1 vs T2
4. Commit+push: watchdog/heal + memory-bank (когда попросит Pedrokita)
5. В AI_MESH Studio: встроить `runpod_queue_watchdog` при создании job

**Конспект «кто что делает»:** `@memory-bank/systemPatterns.md` → раздел «Конспект T2 POC».

**Полный план:** `@memory-bank/platformRoadmap.md`

---

## RunPod endpoints (карта)

| Роль | Имя | ID | Регион | Volume | Статус |
|------|-----|-----|--------|--------|--------|
| Primary (CZ) | mushy_fuchsia_shark | `splmm6w2rblqkp` | EU-CZ-1 | `paradox-models` | v1, образ **stale** |
| Secondary (RO) | nasty_tan_boa | `88djlbwtw4sjlv` | EU-RO-1 | `witty_blush_toucan` | v1 OK |
| Quality (T2) | paradox-trellis2_endpoint | `ynpzjvcbfl656` | EU-RO-1 | `paradox-trellis2` (`netu72a8j2`) | **T2 + R2 OK** (`ad1bca9`) |

**`.env`:** `RUNPOD_ENDPOINT_ID_TRELLIS2=ynpzjvcbfl656`  
(локально также могут быть `RUNPOD_S3_*` для volume S3 — **не** путать с `R2_*`)

**Env на T2 endpoint (обязательные для delivery):**
- `HF_TOKEN`, `TRELLIS2_DINOV3_PATH=/runpod-volume/dinov3-vitl16-pretrain-lvd1689m`
- `R2_ENDPOINT_URL`, `R2_BUCKET=ai-mesh-models`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`
- `R2_PUBLIC_BASE_URL=https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev`, `R2_REGION=auto`

**Volume T2 содержит:** `trellis2-weights/`, `dinov3-vitl16-pretrain-lvd1689m/`, `outputs/`, `huggingface_cache/`

**CI v2** (`build-trellis2.yml`): `:trellis2-latest`, `:trellis2-sha-<short>`.  
**RunPod Flash** (no-Docker product) — не используем. **FlashBoot** на T2 — **оставляем on**; zombie лечим watchdog + `workersMax>=2`.

**Заметка сеть:** прямой GET с ПК на RunPod volume S3 (`s3api-eu-ro-1`) у нас **stall** (~5–9 KB) — для скачивания использовать `model_url` (R2), не volume S3.

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
- [ ] FlashBoot off / workersMax>=2 на T2
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
| Zombie EXITED ghost / FlashBoot | ✅ клиентский heal; ops FlashBoot off ещё TODO |
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

---

## Недавние решения

| Дата | Что | Заметки |
|------|-----|---------|
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

**TRELLIS.2 (full quality + R2):**
```powershell
.\.venv\Scripts\python.exe test_req_trellis2.py --pipeline-type 1024_cascade --texture-size 2048 --save model-v2-full.glb
# ожидание: delivery=r2, model_url=https://pub-….r2.dev/trellis2/<job>.glb
# viewer: python -m http.server 8765 → /scripts/view_model.html?model=/model-v2-full.glb
# heal: .\scripts\heal_t2_endpoint.py --purge
```

Ожидаем T2: `"status": "COMPLETED"` + `delivery: "r2"` + `model_url`.
