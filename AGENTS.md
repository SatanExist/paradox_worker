# paradox_worker — точка входа для агента

RunPod Serverless worker: **картинка → TRELLIS → 3D (GLB base64)**.  
Quality tier (POC): **TRELLIS.2** — `Dockerfile.trellis2` / `worker_trellis2.py`. 
H0 geometry: **Hi3DGen** — `Dockerfile.hi3dgen` / `worker_hi3dgen.py` (отдельный endpoint). 
N2 Pixal3D: 🔴 закрыт как quality 2026-08-21 — `Dockerfile.pixal3d` / `worker_pixal3d.py` (idle). 
N3 Direct3D-S2: 🔴 закрыт как quality 2026-08-21 — `Dockerfile.direct3ds2` / `worker_direct3ds2.py` (idle). 
N4 Step1X-3D: 🔴 закрыт как quality 2026-08-22 — `Dockerfile.step1x3d` / `worker_step1x3d.py` (idle). 
N5 TripoSG: next — `scripts/triposg_n5_spike.md`. 
Texture v1 (scaffold): **mesh paint** — `Dockerfile.texture` / `worker_texture.py`. 
Texture v2 (wow): **MV-Adapter** — `Dockerfile.mvadapter` / `worker_mvadapter.py`.

## С чего начать

0. **`@memory-bank/roadmap.md`** — 🧭 **ГЛАВНЫЙ ПЛАН:** фазы Ф0–Ф7, целевая карта парка, что нужно от юзера
1. `@memory-bank/activeContext.md` — текущие задачи и статус
1a. **`@memory-bank/netParkProgram.md`** — парк 3D-сетей, гейт приёмки новой сети, условия возврата закрытых
1a2. **`@memory-bank/netParkResearch2026.md`** — **числа под план:** 3D Arena Elo, лицензии, доступность весов, ловушки
1b. **`@memory-bank/netsTexToolsPlan.md`** — **наш фокус:** сети/tex/инструменты; H0/Pixal3D/Direct3D-S2/Step1X 🔴 quality closed; MCP last
2. **`@memory-bank/midPropHolesGate.md`** — mid-prop holes (🟢 closed via soft_input; archive + ops)
3. **`@memory-bank/t2InternetAudit.md`** — **как правильно T2** (официалы vs обзоры vs наш рыцарь; стоп кругам)
4. **`@memory-bank/t2FinishPlan.md`** — **дожим T2** (prod recipe, side/back pass, tex; Hi3DGen после)
4. **`@memory-bank/sideBackUnblock.md`** — Side/Back после тупика (A/B/C; C1 abort)
5. **`@memory-bank/postSideBackPlan.md`** — **roadmap:** P1 UX → P2 tex → P3 freeze; RVG = real slots; P4.1 native 3D
6. **`@memory-bank/reconViaGenMvRefiner.md`** — ReconViaGen = fusion реальных фото (не img2mv, не 1-photo Meshy)
7. **`@memory-bank/multiViewFusionResearch.md`** — multi-view series ↔ 3D fusion (research)
8. **`@memory-bank/productMultiUx.md`** — **путь A:** честный 1-фото + слоты реальных ракурсов (spec)
9. **`@memory-bank/synthMultiViewProd.md`** — Synth MV→shape (**🔴 FROZEN 2026-08-13** — класс img2mv исчерпан)
10. `@memory-bank/cursor-shpargalka.md` — полная шпаргалка по Cursor и памяти
11. `@memory-bank/teamWorkflow.md` — синхронизация двух разработчиков через git
12. `@memory-bank/techContext.md` — API, RunPod, карта файлов
13. `@memory-bank/systemPatterns.md` — архитектура и решения
15. **`@memory-bank/posterCards.md`** — сетка = JPEG `posterUrl`; GLB только во вьюере

## Команды

```powershell
.\scripts\sync-start.ps1   # начало сессии: git pull + превью контекста
.\scripts\sync-end.ps1     # перед push: статус + чеклист
python test_req.py                    # тест v1 endpoint (async + fallback)
python test_req_trellis2.py           # тест quality endpoint (TRELLIS.2)
python test_req_texture.py --mesh-url "<glb>" --image-url "<img>"  # Texture v1 (needs ENDPOINT)
python test_req_mvadapter.py --mesh-url "<glb>" --image-url "<img>"  # Texture v2 MV-Adapter (needs ENDPOINT)
python scripts/batch_seeds.py --image-url "<url>" --seeds 1 7 42 --out-prefix model
python scripts/studio_smoke.py --mode image --tier medium --dry-run
python scripts/check_product_multi_ux.py
python scripts/check_fal_hub.py           # geo + credits 2.5x + FAL field names
python scripts/fal_knight_ab.py           # dry-run payloads; --live spends FAL
# Local Studio lab (generate + review): .\scripts\studio_lab.ps1
#   http://127.0.0.1:8787/  →  /scripts/studio_lab.html
#   полка GLB, файл→R2, рефы рыцарь/сундук; Generate = живой GPU
#   (uses .venv-studio; do not use the stale 3.14.0 .venv — ctypes/uvicorn)
# Card-only review: http://127.0.0.1:8765/scripts/model_review.html?file=preview_textures/armor_t2_v17_realistic.png.glb
#   (http.server: .js MIME ok; .mjs is text/plain on Windows)
python scripts/reconviagen_hf_smoke.py --image path1.png --image path2.png --save out.glb
python scripts/cleanup_endpoints.py   # audit GPU list + idleTimeout (--apply to fix)
docker build -t paradox .             # v1 worker image
docker build -f Dockerfile.trellis2 -t paradox-trellis2 .  # quality image
docker build -f Dockerfile.hi3dgen -t paradox-hi3dgen . # Hi3DGen mesh (CI → :hi3dgen-sha-*)
docker build -f Dockerfile.pixal3d -t paradox-pixal3d . # Pixal3D pixel-aligned (CI → :pixal3d-sha-*)
python test_req_pixal3d.py --image-url "<img>" --resolution 1024 --save preview_textures/f2_pixal3d_knight.glb
docker build -f Dockerfile.direct3ds2 -t paradox-direct3ds2 . # Direct3D-S2 SDF (CI → :direct3ds2-sha-*)
python test_req_direct3ds2.py --image-url "<img>" --sdf-resolution 1024 --save preview_textures/n3_direct3ds2_knight_1024.glb
docker build -f Dockerfile.step1x3d -t paradox-step1x3d .  # Step1X-3D geometry (CI → :step1x3d-sha-*)
python test_req_step1x3d.py --image-url "<img>" --save preview_textures/n4_step1x3d_knight.glb
python scripts/f2_recon_space.py --net triposr --subject knight # Ф2 разведка через HF Spaces
python scripts/f2_space_status.py # живы ли демо кандидатов и на каком железе
python scripts/f2_check_weights.py # доступ к весам + размеры репозиториев
python scripts/f2_capacity.py # RunPod: volumes и эндпоинты (сколько места под парк)
docker build -f Dockerfile.texture -t paradox-texture .    # mesh paint image
docker build -f Dockerfile.mvadapter -t paradox-mvadapter .  # MV-Adapter wow texture
```

## Memory bank

| Файл | Назначение |
|------|------------|
| **`memory-bank/roadmap.md`** | 🧭 **Главный roadmap:** Ф0 среда → Ф1 микро → Ф2 риг → Ф3 части → Ф4 fast tier → Ф5 реальные фото → Ф6 tex → Ф7 MCP |
| `memory-bank/projectbrief.md` | Зачем существует проект |
| `memory-bank/netParkProgram.md` | **Парк 3D-сетей:** инвентарь, гейт приёмки, план шаги 1–6, условия возврата закрытых сетей |
| `memory-bank/netParkResearch2026.md` | **Исследование 2026-08-20:** 3D Arena Elo, откуда миф «Hi3DGen лучший», Direct3D-S2 (MIT, веса, 1024³), ловушка Sparc3D, лицензия Hunyuan |
| `memory-bank/midPropHolesGate.md` | mid-prop holes gate (🟢 closed; soft_input) |
| `memory-bank/netsTexToolsPlan.md` | **Фокус generation:** H0/Pixal3D/Direct3D-S2/Step1X 🔴 quality closed; next TripoSG; MCP last |
| `scripts/pixal3d_n2_spike.md` | **N2 Pixal3D:** 🔴 закрыт 2026-08-21 как quality |
| `scripts/direct3ds2_n3_spike.md` | **N3 Direct3D-S2:** 🔴 закрыт 2026-08-21 как quality (другой персонаж) |
| `scripts/step1x3d_n4_spike.md` | **N4 Step1X-3D:** 🔴 закрыт 2026-08-22 как quality (мыло) |
| `scripts/triposg_n5_spike.md` | **N5 TripoSG:** MIT, >8 GB, гейт vs T2 |
| `Dockerfile.step1x3d` | Step1X-3D geometry: torch 2.5.1 cu124, без texture baker |
| `worker_step1x3d.py` | RunPod handler: image → watertight clay GLB |
| `Dockerfile.direct3ds2` | Direct3D-S2 image: torch 2.5.1 cu121 + torchsparse + voxelize |
| `worker_direct3ds2.py` | RunPod handler: image → sdf_resolution=1024 → clay GLB |
| `Dockerfile.pixal3d` | Pixal3D image: T2-стек + их форк + MoGe + NATTEN |
| `worker_pixal3d.py` | RunPod handler: image → камера (MoGe) → pixel-aligned mesh + PBR GLB |
| `Dockerfile.hi3dgen` | Hi3DGen mesh worker image (volume weights) |
| `worker_hi3dgen.py` | RunPod handler: image → normal-bridge mesh GLB |
| `memory-bank/sideBackUnblock.md` | **Side/Back unblock** — A/B/C после тупика MIT→T2 |
| `memory-bank/postSideBackPlan.md` | **Roadmap после тупика** (P1–P4) |
| `memory-bank/reconViaGenMvRefiner.md` | **D-track MASTER:** ReconViaGen integration + smart fusion |
| `memory-bank/multiViewFusionResearch.md` | **Research:** multi-view series ↔ 3D fusion (T2/Meshy/papers) |
| `memory-bank/posterCards.md` | **Сетка = JPEG `posterUrl`**, GLB только во вьюере |
| `memory-bank/synthMultiViewProd.md` | Synth/img2mv→shape (**🔴 FROZEN 2026-08-13**) |
| `memory-bank/textureWowPlan.md` | **План вау-текстур** (фазы, T2 vs MV-Adapter, W2) |
| `scripts/wonder3d_mv2_spike.md` | MV2 Wonder3D (soft-NO-GO 2026-08-07) |
| `scripts/unique3d_mv2b_spike.md` | MV2b Unique3D (архив; класс img2mv frozen) |
| `scripts/mvadapter_w2_spike.md` | Чеклист Pod smoke `texture_i2tex` |
| `scripts/mvpainter_w3_spike.md` | **W3** delight/PBR на native T2 669k (не 80k) |
| `Dockerfile.mvadapter` | MV-Adapter texture worker image |
| `worker_mvadapter.py` | RunPod handler: mesh+image → MV-Adapter textured GLB |
| `memory-bank/falHubPlan.md` | **План v1:** свой T2 + витрина FAL (Meshy, Hunyuan гео-сплит, Hitem3D, Rodin, Tripo) |
| `memory-bank/aiMeshFalContract.md` | Контракт AI_MESH: `/api/engines`, кредиты, гео Hunyuan, job id `fal:…` |
| `memory-bank/tz50CtoReview.md` | **CTO-разбор ТЗ 5.0:** кабинет да; FAL wrap да; веса Hunyuan / greenfield монорепо нет |
| `memory-bank/techContext.md` | Стек, API, секреты |
| `memory-bank/systemPatterns.md` | Pipeline, решения |
| `memory-bank/activeContext.md` | **Обновлять каждую сессию + push** |
| `memory-bank/teamWorkflow.md` | Как работать вдвоём на разных ПК |
| `memory-bank/cursor-shpargalka.md` | Полный туториал / шпаргалка по Cursor |
