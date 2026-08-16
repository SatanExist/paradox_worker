# paradox_worker — точка входа для агента

RunPod Serverless worker: **картинка → TRELLIS → 3D (GLB base64)**.  
Quality tier (POC): **TRELLIS.2** — `Dockerfile.trellis2` / `worker_trellis2.py`.  
Texture v1 (scaffold): **mesh paint** — `Dockerfile.texture` / `worker_texture.py`.  
Texture v2 (wow): **MV-Adapter** — `Dockerfile.mvadapter` / `worker_mvadapter.py`.

## С чего начать

1. `@memory-bank/activeContext.md` — текущие задачи и статус
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
14. **`@scripts/unique3d_mv2b_spike.md`** — MV2b Unique3D (архив); класс frozen → `synthMultiViewProd.md`

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
# Local Studio lab (generate + review): py -3 scripts/studio_api.py
#   http://127.0.0.1:8787/  →  /scripts/studio_lab.html
# Card-only review: http://127.0.0.1:8765/scripts/model_review.html?file=preview_textures/armor_t2_v17_realistic.png.glb
#   (http.server: .js MIME ok; .mjs is text/plain on Windows)
python scripts/reconviagen_hf_smoke.py --image path1.png --image path2.png --save out.glb
python scripts/studio_api.py   # http://127.0.0.1:8787/docs
python scripts/cleanup_endpoints.py   # audit GPU list + idleTimeout (--apply to fix)
docker build -t paradox .             # v1 worker image
docker build -f Dockerfile.trellis2 -t paradox-trellis2 .  # quality image
docker build -f Dockerfile.reconviagen -t paradox-reconviagen .  # ReconViaGen multi-view hybrid
docker build -f Dockerfile.texture -t paradox-texture .    # mesh paint image
docker build -f Dockerfile.mvadapter -t paradox-mvadapter .  # MV-Adapter wow texture
```

## Memory bank

| Файл | Назначение |
|------|------------|
| `memory-bank/projectbrief.md` | Зачем существует проект |
| `memory-bank/midPropHolesGate.md` | mid-prop holes gate (🟢 closed; soft_input) |
| `memory-bank/t2FinishPlan.md` | **Дожим TRELLIS.2** (T0–T5; Hi3DGen после) |
| `memory-bank/sideBackUnblock.md` | **Side/Back unblock** — A/B/C после тупика MIT→T2 |
| `memory-bank/postSideBackPlan.md` | **Roadmap после тупика** (P1–P4) |
| `memory-bank/reconViaGenMvRefiner.md` | **D-track MASTER:** ReconViaGen integration + smart fusion |
| `memory-bank/multiViewFusionResearch.md` | **Research:** multi-view series ↔ 3D fusion (T2/Meshy/papers) |
| `memory-bank/productMultiUx.md` | **Путь A** + **§11 пакет товарищу** (ещё не слали) |
| `memory-bank/synthMultiViewProd.md` | Synth/img2mv→shape (**🔴 FROZEN 2026-08-13**) |
| `memory-bank/textureWowPlan.md` | **План вау-текстур** (фазы, T2 vs MV-Adapter, W2) |
| `scripts/wonder3d_mv2_spike.md` | MV2 Wonder3D (soft-NO-GO 2026-08-07) |
| `scripts/unique3d_mv2b_spike.md` | MV2b Unique3D (архив; класс img2mv frozen) |
| `scripts/mvadapter_w2_spike.md` | Чеклист Pod smoke `texture_i2tex` |
| `scripts/mvpainter_w3_spike.md` | **W3** delight/PBR на native T2 669k (не 80k) |
| `Dockerfile.mvadapter` | MV-Adapter texture worker image |
| `worker_mvadapter.py` | RunPod handler: mesh+image → MV-Adapter textured GLB |
| `memory-bank/techContext.md` | Стек, API, секреты |
| `memory-bank/systemPatterns.md` | Pipeline, решения |
| `memory-bank/activeContext.md` | **Обновлять каждую сессию + push** |
| `memory-bank/teamWorkflow.md` | Как работать вдвоём на разных ПК |
| `memory-bank/cursor-shpargalka.md` | Полный туториал / шпаргалка по Cursor |
