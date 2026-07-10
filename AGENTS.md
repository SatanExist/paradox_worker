# paradox_worker — точка входа для агента

RunPod Serverless worker: **картинка → TRELLIS → 3D (GLB base64)**.

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
python test_req.py                    # тест RunPod endpoint (async + fallback)
python scripts/watch_endpoint.py      # мониторинг /health
docker build -t paradox .  # сборка образа worker
```

## Memory bank

| Файл | Назначение |
|------|------------|
| `memory-bank/projectbrief.md` | Зачем существует проект |
| `memory-bank/techContext.md` | Стек, API, секреты |
| `memory-bank/systemPatterns.md` | Pipeline, решения |
| `memory-bank/activeContext.md` | **Обновлять каждую сессию + push** |
| `memory-bank/teamWorkflow.md` | Как работать вдвоём на разных ПК |
| `memory-bank/cursor-shpargalka.md` | Полный туториал / шпаргалка по Cursor |
