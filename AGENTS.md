# paradox_worker — точка входа для агента

RunPod Serverless worker: **картинка → TRELLIS → 3D (GLB base64)**.  
Quality tier (POC): **TRELLIS.2** — `Dockerfile.trellis2` / `worker_trellis2.py`.  
Texture v1 (scaffold): **mesh paint** — `Dockerfile.texture` / `worker_texture.py`.  
Texture v2 (wow): **MV-Adapter** — `Dockerfile.mvadapter` / `worker_mvadapter.py`.

## С чего начать

1. `@memory-bank/activeContext.md` — текущие задачи и статус
2. **`@memory-bank/midPropHolesGate.md`** — mid-prop holes (🟢 closed via soft_input; archive + ops)
3. `@memory-bank/cursor-shpargalka.md` — полная шпаргалка по Cursor и памяти
4. `@memory-bank/teamWorkflow.md` — синхронизация двух разработчиков через git
5. `@memory-bank/techContext.md` — API, RunPod, карта файлов
6. `@memory-bank/systemPatterns.md` — архитектура и решения
7. **`@scripts/wonder3d_mv2_spike.md`** — **MV2** текущий фокус (1 photo → 6 views → T2)

## Команды

```powershell
.\scripts\sync-start.ps1   # начало сессии: git pull + превью контекста
.\scripts\sync-end.ps1     # перед push: статус + чеклист
python test_req.py                    # тест v1 endpoint (async + fallback)
python test_req_trellis2.py           # тест quality endpoint (TRELLIS.2)
python test_req_texture.py --mesh-url "<glb>" --image-url "<img>"  # Texture v1 (needs ENDPOINT)
python test_req_mvadapter.py --mesh-url "<glb>" --image-url "<img>"  # Texture v2 MV-Adapter (needs ENDPOINT)
python scripts/batch_seeds.py --image-url "<url>" --seeds 1 7 42 --out-prefix model
python scripts/studio_smoke.py --mode image --tier preview
python scripts/studio_api.py   # http://127.0.0.1:8787/docs
python scripts/cleanup_endpoints.py   # audit GPU list + idleTimeout (--apply to fix)
docker build -t paradox .             # v1 worker image
docker build -f Dockerfile.trellis2 -t paradox-trellis2 .  # quality image
docker build -f Dockerfile.texture -t paradox-texture .    # mesh paint image
docker build -f Dockerfile.mvadapter -t paradox-mvadapter .  # MV-Adapter wow texture
```

## Memory bank

| Файл | Назначение |
|------|------------|
| `memory-bank/projectbrief.md` | Зачем существует проект |
| `memory-bank/midPropHolesGate.md` | mid-prop holes gate (🟢 closed; soft_input) |
| `memory-bank/textureWowPlan.md` | **План вау-текстур** (фазы, T2 vs MV-Adapter, W2) |
| `scripts/wonder3d_mv2_spike.md` | **MV2** Wonder3D (🔄 current) |
| `scripts/mvadapter_w2_spike.md` | Чеклист Pod smoke `texture_i2tex` |
| `Dockerfile.mvadapter` | MV-Adapter texture worker image |
| `worker_mvadapter.py` | RunPod handler: mesh+image → MV-Adapter textured GLB |
| `memory-bank/techContext.md` | Стек, API, секреты |
| `memory-bank/systemPatterns.md` | Pipeline, решения |
| `memory-bank/activeContext.md` | **Обновлять каждую сессию + push** |
| `memory-bank/teamWorkflow.md` | Как работать вдвоём на разных ПК |
| `memory-bank/cursor-shpargalka.md` | Полный туториал / шпаргалка по Cursor |
