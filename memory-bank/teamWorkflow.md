# Синхронизация контекста — двое на одном проекте

Один аккаунт Cursor **не** синхронизирует чаты между компами.
Общая память команды = **файлы в git** (`memory-bank/`, `.cursor/rules/`).

---

## Золотое правило

```
Начало работы:  git pull  →  @memory-bank/activeContext.md  →  задача
Конец работы:   обновить activeContext  →  git commit  →  git push
```

---

## Быстрый старт (оба компа)

### Первый раз

```powershell
git clone https://github.com/SatanExist/paradox_worker.git
cd paradox_worker

# Создать .env локально (не коммитить!)
# RUNPOD_API_KEY=ваш_ключ

# Открыть папку в Cursor: File → Open Folder
```

### Каждая сессия

```powershell
# Windows — из корня репо:
.\scripts\sync-start.ps1
```

Или вручную:

```powershell
git pull
```

Затем **новый чат** в Cursor:

```
@memory-bank/activeContext.md @memory-bank/teamWorkflow.md

Продолжаем проект. Прочитай activeContext и скажи, где мы остановились.
```

---

## Практический пример: два дня, два человека

### День 1 — ты (ПК #1)

**Утро:**

```powershell
cd D:\AI_HUB\paradox_worker
.\scripts\sync-start.ps1
```

**Чат в Cursor:**

```
@memory-bank/activeContext.md

Добавь параметр seed в worker.py — пусть приходит из job input,
если не передан — seed=1 как сейчас.
```

**После работы — чат:**

```
Обнови activeContext и systemPatterns если нужно.
Запиши в журнал сессий: я добавил seed, тест прошёл.
```

**Конец дня — терминал:**

```powershell
git add worker.py memory-bank/
git commit -m "Add optional seed param to RunPod worker input"
git push
```

---

### День 2 — брат (ПК #2)

**Утро:**

```powershell
cd C:\Projects\paradox_worker   # путь может быть другим — git не важен
.\scripts\sync-start.ps1
```

Вывод `sync-start` покажет свежий `activeContext` — брат видит твою работу **без** твоего чата.

**Чат брата в Cursor (новый чат!):**

```
@memory-bank/activeContext.md

Брат продолжает. Seed уже добавлен — начни черновик API route
для будущего сайта (опиши в комментарии, без деплоя).
```

**Конец дня брата:**

```powershell
git add .
git commit -m "Draft API integration notes in memory-bank"
git push
```

---

### День 3 — ты снова

```powershell
git pull
```

В `activeContext.md` уже записано, что сделал брат. Новый чат — продолжаешь.

---

## Что писать в activeContext после сессии

Шаблон — секции **«Кто работал»** и **«Журнал сессий»** в `activeContext.md`.

Пример записи в журнале:

```markdown
| Дата | Кто | Что сделано | Следующий шаг |
|------|-----|-------------|---------------|
| 2026-07-09 | Ты | seed в worker.py, test_req OK | API route на сайте |
| 2026-07-10 | Брат | Описал API flow в techContext | Three.js viewer |
```

---

## Если оба правили activeContext (конфликт git)

```powershell
git pull
# Git: CONFLICT in memory-bank/activeContext.md
```

**Решение:** открыть файл, оставить **обе** записи в журнале сессий, объединить чеклисты «Сделано». Удалить маркеры `<<<<<<<` / `=======` / `>>>>>>>`.

```powershell
git add memory-bank/activeContext.md
git commit -m "Merge activeContext from both sessions"
git push
```

---

## Что НЕ синхронизируется

| Не синхронизируется | Что делать |
|---------------------|------------|
| История чатов Cursor | Memory-bank + журнал сессий |
| User Rules (может не совпасть) | Дублировать в `.cursor/rules/project-core.mdc` |
| `.env` с API ключом | У каждого свой файл локально |
| Путь к проекту на диске | Не важен для git |

---

## Чеклист перед push

- [ ] `activeContext.md` обновлён (дата, журнал, следующий шаг)
- [ ] Если меняли API worker — обновлён `techContext.md`
- [ ] Если приняли решение — запись в `systemPatterns.md`
- [ ] `.env` не попал в `git status`
- [ ] `git push` выполнен

---

## Скрипты

| Скрипт | Когда |
|--------|-------|
| `scripts/sync-start.ps1` | В начале сессии — pull + превью контекста |
| `scripts/sync-end.ps1` | Перед commit — статус + напоминание |

---

## Промпты-копипаста

**Начало сессии:**

```
@memory-bank/activeContext.md
Продолжаем. Кратко: где остановились и что делаем сегодня?
```

**Конец сессии:**

```
Обнови memory-bank/activeContext.md: журнал сессий, чеклисты, следующий шаг.
Кто работал: [твоё имя]. Не коммить — я сам сделаю push.
```

**После архитектурного решения:**

```
Добавь решение в memory-bank/systemPatterns.md и кратко в activeContext.
```
