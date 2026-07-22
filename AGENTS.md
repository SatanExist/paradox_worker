# paradox_worker — точка входа для агента

RunPod Serverless worker: **картинка → TRELLIS → 3D (GLB base64)**.  
Quality tier (POC): **TRELLIS.2** — отдельный `Dockerfile.trellis2` / `worker_trellis2.py`.

## С чего начать

1. `@memory-bank/activeContext.md` — текущие задачи и статус
2. `@memory-bank/cursor-shpargalka.md` — полная шпаргалка по Cursor и памяти
3. `@memory-bank/teamWorkflow.md` — синхронизация двух разработчиков через git
4. `@memory-bank/techContext.md` — API, RunPod, карта файлов
5. `@memory-bank/systemPatterns.md` — архитектура и решения

## Команды

```powershell
.\scripts\sync-start.ps1   # начало сессии: git pull + превью контекста
.\scripts\sync-end.ps1     # перед push: статус + чеклист
python test_req.py                    # тест v1 endpoint (async + fallback)
python test_req_trellis2.py           # тест quality endpoint (TRELLIS.2)
python scripts/batch_seeds.py --image-url "<url>" --seeds 1 7 42 --out-prefix model
python scripts/studio_smoke.py --mode image --tier preview
python scripts/studio_api.py   # http://127.0.0.1:8787/docs
python scripts/cleanup_endpoints.py   # audit GPU list + idleTimeout (--apply to fix)
docker build -t paradox .             # v1 worker image
docker build -f Dockerfile.trellis2 -t paradox-trellis2 .  # quality image
```

## Memory bank

| Файл | Назначение |
|------|------------|
| `memory-bank/projectbrief.md` | Зачем существует проект |
| `memory-bank/platformRoadmap.md` | **План AI_MESH: 4 фичи, модели, фазы, economics** |
| `memory-bank/techContext.md` | Стек, API, секреты |
| `memory-bank/systemPatterns.md` | Pipeline, решения |
| `memory-bank/activeContext.md` | **Обновлять каждую сессию + push** |
| `memory-bank/teamWorkflow.md` | Как работать вдвоём на разных ПК |
| `memory-bank/cursor-shpargalka.md` | Полный туториал / шпаргалка по Cursor |
