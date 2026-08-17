# Превью карточек: `posterUrl` (JPEG) vs `modelUrl` (GLB)

> **Зачем:** сетка истории должна быть лёгкой и «как у сильных». GLB 12–97 MB в каждой плитке — нельзя ни в lab, ни на сайте.  
> **Статус:** 🟢 live T2 **v18** `trellis2-sha-ea4ea58` — worker отдаёт `poster_url`. Сайт/лента у товарища.  
> **Не путать с Draco** — Draco потом для большого вьюера, не для сетки.

---

## 1. Слои (что для чего)

| Слой | Что видит человек | Вес | Кто делает |
|------|-------------------|-----|------------|
| **Сетка / история** | JPEG ~50–150 КБ × студии (studio/outdoor/gallery/neon/night) | лёгкий | GPU still полного GLB → R2 `poster_url` + `poster_urls` |
| **Большое окно** | настоящий GLB + IBL | 12–97 MB, **один** | клик → `modelUrl` |
| **Скачать / DCC** | тот же GLB | как есть | `modelUrl` |
| **Draco / proxy** | позже, если сайт тормозит на High ~47 MB | сжатый меш | не этот шаг |

Фото входа в плитке — запасной fallback, не «вау». Живой Three.js в 31 карточке — запрещён.

## 2. Контракт API

После COMPLETED worker уже отдаёт `model_url`. Добавляем:

```json
{
  "model_url": "https://…/trellis2/{jobId}.glb",
  "poster_url": "https://…/trellis2/{jobId}.jpg",
  "poster_urls": {
    "studio": "https://…/trellis2/{jobId}.jpg",
    "outdoor": "https://…/trellis2/{jobId}_outdoor.jpg",
    "gallery": "https://…/trellis2/{jobId}_gallery.jpg",
    "neon": "https://…/trellis2/{jobId}_neon.jpg",
    "night": "https://…/trellis2/{jobId}_night.jpg"
  }
}
```

Studio / lab: `posterUrl` + `posterUrls` (camelCase в `normalize_job_payload`).

- Нет `posterUrl` → плитка: фото входа или «…», **не** грузить GLB.
- Клик → только тогда `modelUrl`.
- Hover на карточке крутит `posterUrls` (neon → солнце → gallery…). Это **готовые JPEG**, не 31 живых Three.js.

## 3. Как получаем JPEG (worker)

После polish/export GLB, **до** ответа джоба:

1. CPU рендер `studio_bridge/poster.py` — fallback. Prod: `poster_gpu.py` (nvdiffrast, полный меш, 768², MSAA×2).
2. Один raster, пять студий как в lab viewer: studio / outdoor / gallery / neon / night. Сердечко/ник — не в JPEG.
3. Upload R2 `trellis2/{jobId}.jpg` + `_{env}.jpg`.
4. Если рендер упал — джоб **всё равно success**, `poster_url=null` (WARN в логе).

Не жжём второй infer. GPU still после export — nvdiffrast уже в образе T2. CPU `poster.py` только если CUDA/nvdiffrast упал.

## 4. Lab сегодня vs сайт

| | Lab (этот ПК) | Сайт (товарищ) |
|--|----------------|----------------|
| Старые локальные GLB | клиентский снимок → `preview_textures/thumbs/` (один раз) | не используются |
| Новые джобы после релиза | `posterUrl` + hover `posterUrls` | лента = `posterUrl`, hover = `posterUrls` |
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
