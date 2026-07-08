# Архитектура и решения

## Pipeline: URL картинки → GLB base64

```
Клиент (test_req.py или будущий сайт)
    │
    ▼ POST /runsync { input: { image_url } }
RunPod Serverless
    │
    ▼ handler(job)
worker.py
    ├─ load_model()          [лениво, один раз на lifetime воркера]
    ├─ скачать картинку        [urllib + User-Agent]
    ├─ pipeline.run(image)   [TRELLIS, seed=1]
    ├─ render_utils.render_glb(outputs, path)
    └─ return model_base64
```

## Паттерны RunPod / TRELLIS (не ломать)

### 1. Network volume для весов

```python
os.environ["HF_HOME"] = "/runpod-volume/huggingface_cache"
snapshot_download(..., local_dir="/runpod-volume/trellis-weights")
```

Веса должны жить на примонтированном volume — после первого запуска cold start быстрый.

### 2. Symlink для ckpts TRELLIS

TRELLIS ищет чекпоинты в `/app/ckpts`. Symlink на реальный путь в скачанных весах:

```python
os.symlink(os.path.join(model_path, "ckpts"), "/app/ckpts")
```

Не убирать без проверки путей загрузки TRELLIS.

### 3. Ленивая загрузка модели

`pipeline = None` глобально; `load_model()` при первом job. Быстрый старт воркера, GPU не трогаем без задачи.

### 4. Очистка temp-файлов

PNG и GLB удаляются после base64. GLB кратко в памяти — ок для MVP.

### 5. Attention backend: xformers (без flash-attn)

В некоторых окружениях TRELLIS по умолчанию пытается импортировать `flash_attn` и падает с:
`ModuleNotFoundError: No module named 'flash_attn'`.

Решение для нашего Dockerfile (где установлен `xformers`): форсировать backend до загрузки TRELLIS:

```python
os.environ.setdefault("ATTN_BACKEND", "xformers")
```

### 6. Полный traceback в логах RunPod

Ошибки вида `... is not defined` или падения внутри зависимостей невозможно чинить “вслепую”.
Поэтому при исключениях в `handler()` печатаем полный stacktrace в RunPod logs (`traceback.format_exc()`),
а в ответ возвращаем короткое `{ "error": "..." }`.

## Журнал решений

| Дата | Решение | Почему |
|------|---------|--------|
| 2026 | GLB как base64 в JSON | Проще всего для MVP, без S3 |
| 2026 | `runsync` для тестов | Удобнее async poll при разработке |
| 2026 | seed=1 фиксированный | Воспроизводимый тест; позже — параметр в input |
| 2026 | TRELLIS vendored в репо | Контроль Dockerfile, патч FlexiCubes |
| 2026-07-08 | `ATTN_BACKEND=xformers` | Избежать зависимости `flash_attn` и падений на старте |
| 2026-07-08 | Печатать полный traceback в logs | Быстрее диагностировать падения внутри зависимостей |

## Будущее (когда будет сайт)

- **Upload**: браузер → ваш API → URL картинки → RunPod (тот же контракт)
- **Большие модели**: S3 presigned URL вместо base64, если GLB > ~5 MB
- **Async**: RunPod `/run` + polling или webhooks вместо `/runsync`
- **Несколько воркеров**: отдельные endpoint'ы под 3D, текстуры, анимации

## Конвенции кода

- Handler возвращает `{"error": "..."}` при ошибке, не кидает exception наружу
- `print()` для логов в RunPod dashboard
- Комментарии в worker могут быть на русском; новый код — комментарии на английском
- Не коммитить `.env`, ключи, бинарные GLB
