# Превью карточек: `posterUrl` (JPEG) vs `modelUrl` (GLB)

> **Зачем:** сетка истории должна быть лёгкой и «как у сильных». GLB 12–97 MB в каждой плитке — нельзя ни в lab, ни на сайте.  
> **Статус:** код в worker/bridge; **live на сайте после** CI + New Release T2.  
> **Не путать с Draco** — Draco потом для большого вьюера, не для сетки.

---

## 1. Слои (что для чего)

| Слой | Что видит человек | Вес | Кто делает |
|------|-------------------|-----|------------|
| **Сетка / история** | JPEG ~50–150 КБ, студийный 3/4 | лёгкий | worker в конце джоба → R2 `poster_url` |
| **Большое окно** | настоящий GLB + IBL | 12–97 MB, **один** | клик → `modelUrl` |
| **Скачать / DCC** | тот же GLB | как есть | `modelUrl` |
| **Draco / proxy** | позже, если сайт тормозит на High ~47 MB | сжатый меш | не этот шаг |

Фото входа в плитке — запасной fallback, не «вау». Живой Three.js в 31 карточке — запрещён.

## 2. Контракт API

После COMPLETED worker уже отдаёт `model_url`. Добавляем:

```json
{
  "model_url": "https://…/trellis2/{jobId}.glb",
  "poster_url": "https://…/trellis2/{jobId}.jpg"
}
```

Studio / lab: `posterUrl` + `modelUrl` (camelCase в `normalize_job_payload`).

- Нет `posterUrl` → плитка: фото входа или «…», **не** грузить GLB.
- Клик → только тогда `modelUrl`.

## 3. Как получаем JPEG (worker)

После polish/export GLB, **до** ответа джоба:

1. CPU рендер `studio_bridge/poster.py` (trimesh + PIL, без нового GPU-пайплайна).
2. Кадр 512², 3/4 спереди, фон как у карточки, простой Lambert по albedo.
3. Upload R2 `trellis2/{jobId}.jpg` (`Content-Type: image/jpeg`).
4. Если рендер упал — джоб **всё равно success**, `poster_url=null` (WARN в логе).

Не жжём второй infer. Не ставим pyrender в этом шаге (EGL уже в образе, но лишняя зависимость).

## 4. Lab сегодня vs сайт

| | Lab (этот ПК) | Сайт (товарищ) |
|--|----------------|----------------|
| Старые локальные GLB | клиентский снимок → `preview_textures/thumbs/` (один раз) | не используются |
| Новые джобы после релиза | `posterUrl` с R2 сразу в «Recent» | лента = `posterUrl` |
| Пока image без poster.py | thumbs как сейчас | fallback на входное фото |

Сайт **не копирует** lab-трюк «скачай 97 MB ради плитки».

## 5. Порядок работ

1. `poster.py` + тест на кубе / локальном GLB  
2. `_upload_r2` умеет jpeg; `_deliver_glb` пишет `poster_url`  
3. `normalize` → `posterUrl`; lab Recent  
4. `Dockerfile.trellis2` COPY `poster.py`  
5. Push → CI trellis2 → New Release → один smoke, проверить что jpg на R2  
6. Пакет товарищу: лента только `posterUrl`

GPU на шаге 5, не на 1–4.
