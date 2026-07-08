# Активный контекст

> **Как пользоваться:** в начале каждого нового чата — `@memory-bank/activeContext.md`.
> В конце сессии: *«Обнови activeContext — что мы сделали»* → `git push`.
> Синхронизация вдвоём: см. `@memory-bank/teamWorkflow.md`.

Последнее обновление: **2026-07-08**

---

## Кто работал последним

| Поле | Значение |
|------|----------|
| Кто | Pedrokita (с Cursor агентом) |
| ПК | Windows (D:\PyCharm\paradox_worker) |
| Коммит | (см. GitHub Actions build; фикс в `worker.py` + улучшение `test_req.py`) |

---

## Текущий фокус

**Фаза:** MVP воркера готов → готовимся к интеграции с сайтом.

**Ближайшая цель:** стабилизировать RunPod endpoint: убрать падения на старте/инференсе и добиться `COMPLETED` на `test_req.py`.

---

## Сделано

- [x] RunPod Serverless worker с TRELLIS-image-large
- [x] Docker-образ CUDA 11.8 + deps TRELLIS + фикс FlexiCubes
- [x] Кэш весов на network volume
- [x] Экспорт GLB через `render_utils.render_glb`
- [x] Локальный тест `test_req.py` (runsync)
- [x] Memory bank + Cursor rules (на русском)
- [x] `teamWorkflow.md` + скрипты `sync-start` / `sync-end`
- [x] `cursor-shpargalka.md` — полный туториал по Cursor и памяти

---

## В работе

- [ ] Первый «прогон» синхронизации: один делает push, второй pull (вы + брат)
- [ ] Выбрать стек frontend (в плане — Next.js)
- [ ] RunPod endpoint: добиться успешного прогона `test_req.py` (COMPLETED)

---

## Следующие шаги (порядок)

1. Оба: `git pull` или `.\scripts\sync-start.ps1`
2. Один обновляет этот файл после сессии → `git push`
3. Второй: pull → новый чат → `@memory-bank/activeContext.md`
4. RunPod: дождаться GPU capacity (throttling) → запустить `test_req.py` → собрать traceback/логи при падении
5. Если RunPod job падает: смотреть Logs (теперь печатается полный traceback) и фиксить по конкретной строке
6. После стабилизации воркера: создать репо сайта (`AI_MESH`) — upload, API, Three.js viewer
7. Опционально: параметр `seed` в worker input

---

## Блокеры

- RunPod GPU capacity: воркеры часто `Throttled` / нет свободных GPU (EU-CZ-1, 3090/24GB). Нужен wait/смена региона/квоты/уменьшить max workers.

---

## Журнал сессий (пример — дополняйте)

| Дата | Кто | Что сделано | Следующий шаг |
|------|-----|-------------|---------------|
| 2026-07-08 | — | Memory-bank, rules, teamWorkflow | Прогнать sync вдвоём |
| 2026-07-08 | Pedrokita | 1) `test_req.py`: добавлен polling по `/status/{id}` при `IN_QUEUE`; 2) `worker.py`: форс `ATTN_BACKEND=xformers` (фикс `flash_attn`), добавлен полный traceback в logs; 3) Endpoints: обновление image через GHCR digest | Дождаться GPU capacity → повторить `test_req.py` → по traceback починить `dmc_table is not defined` |
| | | | |
| | | | |

> **Пример после реальной работы:**
>
> | 2026-07-09 | Иван | seed в worker.py, test OK | API route |
> | 2026-07-10 | Брат | pull + проверил endpoint | Three.js |

---

## Недавние решения

| Дата | Что | Заметки |
|------|-----|---------|
| 2026-07-08 | Контекст через git, не через чаты | `teamWorkflow.md` |
| 2026-07-08 | Memory-bank на русском | |
| — | GLB в base64 | До появления S3 |

---

## Быстрый тест

```powershell
cd D:\AI_HUB\paradox_worker
python test_req.py
```

Ожидаем: JSON с `"status": "success"` и `"model_base64"`.
