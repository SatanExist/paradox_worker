# Активный контекст

> **Как пользоваться:** в начале каждого нового чата — `@memory-bank/activeContext.md`.
> В конце сессии: *«Обнови activeContext — что мы сделали»* → `git push`.
> Синхронизация вдвоём: см. `@memory-bank/teamWorkflow.md`.

Последнее обновление: **2026-07-10**

---

## Кто работал последним

| Поле | Значение |
|------|----------|
| Кто | Pedrokita (с Cursor агентом) |
| ПК | Windows (`D:\AI_HUB\paradox_worker`) |
| Коммит | `0649896` — docs: multi-endpoint fallback + async smoke test |

---

## Текущий фокус

**Фаза:** MVP воркера готов → **починить деплой образа на RunPod** → первый `COMPLETED` на `test_req.py` → интеграция с сайтом.

**Ближайшая цель:** заменить битый digest образа на `ghcr.io/satanexist/paradox_worker:latest` на обоих endpoint'ах и прогнать smoke test.

---

## Корневая причина 48ч IN_QUEUE (2026-07-10, RunPod Support)

**Не capacity.** Support (Hector Vallejos) подтвердил: на обоих endpoint'ах был **обрезанный SHA-256 digest (63 символа вместо 64)** → pull образа падает с parse error → воркер мигает `Initializing` → исчезает → jobs в `IN_QUEUE` / «Waiting for GPU».

Битый digest (не использовать):
```
sha256:2131ce5fa2429c77d79c882bbddd667d3df6debc41c3710e5c58108fc812c6d  ← 63 chars
```

**Фикс:** `ghcr.io/satanexist/paradox_worker:latest` (сейчас). Потом — `:stable` для прода.

Также сделано на CZ: Release #13 — удалён `RUNPOD_SOURCE_PATH=/worker.py` (неверный путь; CMD в образе = `/app/worker.py`).

---

## RunPod endpoints (карта)

| Роль | Имя | ID | Регион | Volume |
|------|-----|-----|--------|--------|
| Primary (CZ) | mushy_fuchsia_shark | `splmm6w2rblqkp` | EU-CZ-1 | `paradox-models` → `/runpod-volume` |
| Secondary (RO) | nasty_tan_boa | `88djlbwtw4sjlv` | EU-RO-1 | `witty_blush_toucan` → `/runpod-volume` |

Образ (целевой): `ghcr.io/satanexist/paradox_worker:latest`  
CI: `.github/workflows/build.yml` пушит `latest` на каждый push в `main`.

**RunPod Flash** (Deploy with Flash в UI) — **не используем**: для TRELLIS нужен кастомный Docker (CUDA 11.8, spconv, vendored TRELLIS). Flash ≠ FlashBoot.

---

## Сделано

- [x] RunPod Serverless worker с TRELLIS-image-large
- [x] Docker-образ CUDA 11.8 + deps TRELLIS + фикс FlexiCubes
- [x] Кэш весов на network volume
- [x] Экспорт GLB через `render_utils.render_glb`
- [x] `test_req.py`: async `/run` + polling + fallback CZ→RO при `IN_QUEUE` > 10 мин
- [x] `scripts/watch_endpoint.py` — мониторинг `/health`
- [x] Memory bank + Cursor rules
- [x] Support ticket → ответ: malformed digest
- [x] CZ Release #13: `RUNPOD_SOURCE_PATH` удалён

---

## В работе (прямо сейчас)

- [ ] **Шаг 1:** CZ + RO — image → `:latest`, Save, rollout 100%
- [x] RunPod infra OK: RO worker Ready, job reaches handler (~71s)
- [ ] **Шаг 2:** Rebuild Docker (FlexiCubes fix) → push main → `:latest` на endpoints
- [ ] **Шаг 3:** `test_req.py` → `COMPLETED`
- [ ] Прод: теги `vX.Y.Z` + `stable` в CI и на primary endpoint
- [ ] Вариант B: fallback в `.env` (`RUNPOD_ENDPOINT_ID_SECONDARY`)
- [ ] Интеграция с сайтом (`AI_MESH`)

---

## Следующие шаги (порядок)

1. Исправить image на обоих endpoint'ах (см. чеклист ниже)
2. `.\.venv\Scripts\python.exe scripts\watch_endpoint.py --once` — `running > 0`
3. `.\.venv\Scripts\python.exe test_req.py` — дождаться `COMPLETED`
4. Обновить memory-bank → `git push`
5. После стабилизации: `stable` тег + controlled rollout (RO канарейка → CZ)
6. Сайт: async API + multi-endpoint fallback

---

## Чеклист фикса образа (выполнять по порядку)

### Endpoint CZ (`splmm6w2rblqkp`)

1. Serverless → **mushy_fuchsia_shark** → Edit Endpoint
2. Container image: `ghcr.io/satanexist/paradox_worker:latest`
3. Убедиться: **нет** `@sha256:...` с обрезанным digest
4. Volume `paradox-models` на `/runpod-volume` — не трогать
5. `RUNPOD_SOURCE_PATH` — **нет** в env
6. Save → Releases → **100%**

### Endpoint RO (`88djlbwtw4sjlv`)

1. То же image: `ghcr.io/satanexist/paradox_worker:latest`
2. Volume `witty_blush_toucan` — не трогать
3. Save → Releases → **100%**

### Проверка

```powershell
cd D:\AI_HUB\paradox_worker
$env:PYTHONUTF8=1
.\.venv\Scripts\python.exe scripts\watch_endpoint.py --once
.\.venv\Scripts\python.exe test_req.py
```

Если образ приватный в GHCR — проверить **Container Registry Credentials** на endpoint.

---

## Блокеры

- ~~GPU capacity 48ч~~ → **снят**: была ошибка digest (support 2026-07-10)
- [ ] Подтвердить фикс после смены на `:latest`
- EU capacity может снова влиять на скорость старта, но не должен блокировать pull образа

---

## Заметки по RunPod (важное)

- **Битый digest** маскируется под «Waiting for GPU» / `throttled` — всегда проверять длину `sha256:` (ровно **64** hex) или использовать тег.
- `:latest` — для починки и dev; **`:stable`** — для прода (не обновляется от случайного push).
- **Не копировать digest из чата** — только из GitHub Packages / `docker inspect`.
- Network volume не шарится между регионами — отдельный volume на RO.
- `scripts/watch_endpoint.py` — снимок `/health` без UI.

---

## Журнал сессий

| Дата | Кто | Что сделано | Следующий шаг |
|------|-----|-------------|---------------|
| 2026-07-08 | Pedrokita | Memory-bank, test_req async, worker traceback/xformers | RunPod тест |
| 2026-07-09 | Pedrokita | Multi-endpoint fallback, мониторинг `/health`, CZ Release #13, support ticket | Диагностика capacity (ошибочно) |
| 2026-07-10 | Pedrokita | Digest fix → RO Ready; test FAILED `dmc_table`; Dockerfile → MaxtirError FlexiCubes + kaolin | Rebuild image, push main, retest |

---

## Недавние решения

| Дата | Что | Заметки |
|------|-----|---------|
| 2026-07-10 | Фикс: `:latest` вместо битого digest | Support Hector Vallejos |
| 2026-07-10 | Не переходить на RunPod Flash | TRELLIS требует кастомный Docker |
| 2026-07-10 | Прод: `:stable` после успешного теста | см. `systemPatterns.md` |
| 2026-07-09 | CZ заморозка + убрать `RUNPOD_SOURCE_PATH` | Release #13 |
| 2026-07-08 | Multi-endpoint fallback | `test_req.py` + env vars |

---

## Быстрый тест

```powershell
cd D:\AI_HUB\paradox_worker
$env:PYTHONUTF8=1
.\.venv\Scripts\python.exe scripts\watch_endpoint.py --once
.\.venv\Scripts\python.exe test_req.py
```

Ожидаем: `running > 0` в health, затем JSON с `"status": "success"` и `"model_base64"`.
