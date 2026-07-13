# AI_MESH — дорожная карта платформы

> **Назначение:** стратегический план платформы (4 фичи на сайте, модели, фазы, экономика).
> **Связанные файлы:** `projectbrief.md`, `systemPatterns.md`, `activeContext.md`.
> Последнее обновление: **2026-07-13**

---

## Видение продукта (сайт)

На AI_MESH пользователь получает **pipeline из четырёх инструментов** (не одна кнопка):

| # | Инструмент на сайте | Что делает | Статус |
|---|---------------------|------------|--------|
| 1 | **3D генерация** | Image/text → textured mesh (GLB) | 🟡 MVP (`paradox_worker`, TRELLIS v1) |
| 2 | **ИИ ретопология** | High-poly → game-ready low-poly / quads | ⚪ не начато |
| 3 | **ИИ текстурирование** | Mesh + prompt/image → новые PBR-текстуры | ⚪ не начато |
| 4 | **ИИ анимирование** | Auto-rig + preset motion → animated GLB/FBX | ⚪ не начато |

**Цепочка (идеальный UX):**

```
Генерация → [опционально] Ретопо → [опционально] Retexture → [опционально] Rig+Anim → Export
```

Каждый шаг — отдельная job; результат предыдущего шага — input следующего.

---

## Архитектура (целевая)

```
┌─────────────────────────────────────────────────┐
│  AI_MESH Frontend (React / Three.js viewer)      │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│  Backend API (отдельный репо, не paradox_worker) │
│  auth, billing, storage (S3/R2), job router      │
└───┬─────────┬─────────┬─────────┬───────────────┘
    │         │         │         │
    ▼         ▼         ▼         ▼
 RunPod    RunPod    RunPod    RunPod
 generate  retopo    texture   rig+anim
```

### Принципы

- **Не один fat Docker** — отдельные endpoint'ы / образы под разные GPU-профили и релизы.
- **Self-host open-source** — core pipeline; **не** перепродажа Tripo/Meshy/fal API (unit economics не сходится).
- **EU-first** — модели с MIT/Apache; Hunyuan self-host/API **не для EU prod** (лицензия).
- **RunPod Serverless** — тот же паттерн, что `paradox_worker`: volume для весов, immutable tags, billing по GPU-time.

### Репозитории

| Слой | Репо | Статус |
|------|------|--------|
| Worker: generate | `paradox_worker` (этот) | MVP |
| Worker: retopo / texture / rig | новые репо или monorepo позже | план |
| Frontend + API gateway | `AI_MESH` (отдельный) | не начато |

---

## Фича 1: 3D генерация

### Сейчас

- Модель: **TRELLIS-image-large** (`JeffreyXiang/TRELLIS-image-large`)
- Stack: CUDA **11.8**, torch 2.0.1
- Вход: `image_url` → выход: GLB base64
- COGS (4090, idle 5–10s): **~$0.07–0.12/job**

### Цель (quality tier)

- Модель: **TRELLIS.2-4B** ([microsoft/TRELLIS.2](https://github.com/microsoft/TRELLIS.2))
- Stack: CUDA **12.4**, ~24 GB VRAM
- Лицензия: **MIT** ✅ EU

### Fast tier (preview)

- Модель: **SF3D** или **TripoSR**
- VRAM: 6–8 GB, время: 1–5 сек
- COGS: **~$0.01/job**

### Быстрые улучшения без смены модели

- `simplify=0.98`, `texture_size=2048`
- Multi-image input (`image_urls[]`)
- Best-of-N seeds

---

## Фича 2: ИИ ретопология

**Задача:** после генерации mesh часто 100k–500k+ tris; для игр нужно 5k–50k quads.

| Компонент | Open-source | VRAM | Лицензия EU |
|-----------|-------------|------|-------------|
| **FastMesh** (v1k / v4k verts) | [jhkim0759/FastMesh](https://github.com/jhkim0759/FastMesh) | 16–24 GB | ✅ |
| **PartUV** (UV unwrap) | [EricWang12/PartUV](https://github.com/EricWang12/PartUV/) | ~7 GB | ✅ |
| Fallback: decimate + Instant Meshes | классика | CPU/GPU | ✅ |

**Референс-реализация API:** [3DAIGC-API](https://github.com/FishWoWater/3DAIGC-API) (mesh-retopology endpoints).

**COGS (оценка):** ~$0.03–0.08/job на 4090.

**UX на сайте:** загрузить GLB или «из шага 1» → poly budget → quad/tri → новый mesh.

---

## Фича 3: ИИ текстурирование

**Два сценария:**

1. **Retexture** — есть mesh + новый prompt/картинка → новые PBR maps.
2. **Re-bake** — после ретopo перезапечь текстуры на новых UV.

| Модель | Назначение | VRAM | EU |
|--------|------------|------|-----|
| TRELLIS mesh painting | text/image guided paint | ~8 GB | ✅ MIT |
| Bake pipeline (nvdiffrast) | multiview → bake | как generate | ✅ |

**Не для EU prod:** Hunyuan3D-Paint (Tencent Community License, EU/UK/KR excluded).

**COGS (оценка):** ~$0.05–0.10/job.

---

## Фича 4: ИИ анимирование

Разбить на **два шага** (как Meshy/Tripo):

```
Mesh (GLB) → UniRig (skeleton + skinning) → Retarget preset motion → Animated GLB/FBX
```

| Шаг | Инструмент | Статус OSS | EU |
|-----|------------|------------|-----|
| Auto-rig | **[UniRig](https://github.com/VAST-AI-Research/UniRig)** (VAST/Tripo, SIGGRAPH'25) | skeleton + skinning ✅ | ✅ MIT |
| Motion | Библиотека FBX-клипов + retarget | не «генерация из текста» на v1 | ✅ |
| Export | GLB с animation channels | стандарт | ✅ |

**Ограничение:** rig имеет смысл для **персонажей/существ**; для props (решётка, мебель) — скрывать или disable в UI.

**COGS (оценка):** rig ~$0.05–0.08; retarget ~CPU, копейки.

**v2 (не MVP):** text → motion (research, дорого).

---

## Исследование моделей (сводка, 2026)

### Tier S — production open-source (image→3D)

| Модель | Качество | VRAM | CUDA | EU legal |
|--------|----------|------|------|----------|
| **TRELLIS.2-4B** | ⭐⭐⭐⭐½ | 24 GB | 12.4 | ✅ MIT |
| **Hunyuan3D 2.1** | ⭐⭐⭐⭐⭐ textures | 10–29 GB | 12.4 | ❌ EU ban |
| **Hi3DGen** | геометрия | ~16 GB | 12.x | ✅ MIT |
| **TripoSG** | shape | 12–24 GB | 12.x | ✅ MIT |

### Tier B — fast preview

| Модель | VRAM | Время | EU |
|--------|------|-------|-----|
| SF3D | 6 GB | <1 сек | ✅ |
| TripoSR | 6–8 GB | <0.5 сек | ✅ MIT |

### Закрытые SaaS (не для core — только benchmark)

Tripo, Meshy, Rodin, CSM, Luma — свои модели; API **$0.30–1.20/job** → unit economics не сходится для перепродажи.

### Hunyuan3D — почему не берём в EU

- Лицензия Tencent: **Territory excludes EU, UK, South Korea**
- Hosted Service (RunPod/API) подпадает под license
- US endpoint **не спасает**, если output идёт EU-пользователям
- **Исключение:** отдельный US-only продукт с geo-block + ToS (сложно, не MVP)

### Референс «Tripo Studio в open-source»

- [Open3DStudio](https://github.com/FishWoWater/Open3DStudio) — UI
- [3DAIGC-API](https://github.com/FishWoWater/3DAIGC-API) — backend: TRELLIS.2, FastMesh, UniRig, paint, RunPod template

Использовать как **карту фич и моделей**, не обязательно как dependency.

---

## Unit economics: API vs self-host

### API (не для core prod)

| Провайдер | ~$/job (image→3D + texture) |
|-----------|----------------------------|
| fal TRELLIS v1 | $0.02 (слабое качество) |
| Tripo API | $0.30–0.50 |
| Meshy API | $0.48–0.60 |
| fal TRELLIS.2 | $0.30–0.35 |
| fal Hunyuan Pro | $0.38–0.53 |
| fal Rodin | $0.40–1.20 |
| Hyper3D direct | ~$0.75–2.25 |

При 1000 jobs/мес: **$300–600** API vs **$50–120** self-host.

### Self-host RunPod (целевые COGS)

| Tier | Модель | ~$/job |
|------|--------|--------|
| Fast | SF3D / TripoSR | $0.01 |
| Quality | TRELLIS.2 | $0.05–0.12 |
| Retopo | FastMesh | $0.03–0.08 |
| Texture | TRELLIS paint | $0.05–0.10 |
| Rig | UniRig | $0.05–0.08 |

**Вывод:** AI_MESH monetization viable только на **своих workers**. API — POC/hero-tier only.

### Пример pricing для пользователя (self-host)

| Tier | COGS | Цена пользователю | Маржа |
|------|------|-------------------|-------|
| Fast preview | ~$0.01 | $0.05–0.10 | 80–90% |
| Quality generate | ~$0.08 | $0.20–0.40 | 60–75% |
| Retopo / texture | ~$0.06 | $0.15–0.30 | 60%+ |
| Rig + anim | ~$0.08 | $0.25–0.50 | 70%+ |

---

## Фазы разработки

### Фаза 0 — сейчас (1–2 нед)

- [ ] Стабильный **generate** (TRELLIS v1 → COMPLETED стабильно)
- [ ] RunPod: убрать 5090/48GB, `idleTimeout` 5–10s, immutable tags
- [ ] Тюнинг: simplify, texture_size, multi-image, seeds
- [ ] `scripts/save_glb_from_status.py`, billing в ответе

**На сайте:** только генерация (когда будет frontend).

### Фаза 1 — MVP платформы (1–2 мес)

- [ ] Backend: jobs, storage GLB (S3/R2), auth, credits
- [ ] Frontend: viewer + upload + job status
- [ ] POC **TRELLIS.2** (CUDA 12.4 Docker)
- [ ] Optional **SF3D** fast endpoint

**На сайте:** п.1 «3D генерация» (quality + preview).

### Фаза 2 — post-process (2–3 мес)

- [ ] Worker **retopo** (FastMesh + PartUV)
- [ ] Worker **retexture** (TRELLIS paint)
- [ ] Pipeline: one-click «оптимизировать» / «перетекстурировать» из результата gen

**На сайте:** п.1 + п.2 + п.3.

### Фаза 3 — animation (3–4 мес)

- [ ] Worker **UniRig**
- [ ] Библиотека 20–50 preset motions + retarget
- [ ] Preview анимации в Three.js

**На сайте:** все 4 инструмента (базовый уровень).

### Фаза 4 — polish

- Multi-image, part segmentation, routing по типу объекта (prop vs character)
- Promote `:stable`, dual-region HA (EU only, без Hunyuan)

---

## Docker / infra roadmap

| Образ | CUDA | Модели | Назначение |
|-------|------|--------|------------|
| `paradox_worker:cuda11.8-trellis-v1` | 11.8 | TRELLIS v1 | текущий legacy |
| `paradox_worker:cuda12.4-trellis2` | 12.4 | TRELLIS.2 | quality generate |
| `paradox_worker:cuda12.4-sf3d` | 11.8–12.4 | SF3D/TripoSR | fast preview |
| `paradox_worker:cuda12.4-retopo` | 12.4 | FastMesh, PartUV | retopo |
| `paradox_worker:cuda12.4-texture` | 12.4 | TRELLIS paint | retexture |
| `paradox_worker:cuda12.4-rig` | 12.4 | UniRig | rig |

Не объединять всё в один образ на старте — разные deps, VRAM, циклы релизов.

---

## Backend router (черновик контракта)

```json
{
  "task_type": "generate | retopo | texture | rig | animate",
  "model_tier": "fast | quality",
  "input": {
    "image_url": "...",
    "mesh_url": "...",
    "prompt": "...",
    "poly_target": 10000,
    "motion_preset": "walk"
  }
}
```

Router (AI_MESH backend) → `endpoint_id` по `task_type` + `model_tier` + region (EU).

---

## Dual-region + Hunyuan (не MVP)

Если когда-нибудь нужен Hunyuan для non-EU:

- EU endpoint → TRELLIS.2 (MIT)
- US endpoint → Hunyuan **только** для пользователей вне EU/UK/KR
- Geo-block + ToS + отдельный compliance

**Для старта не делать** — overkill.

---

## Чеклист «не забыть»

- [ ] Hunyuan — **не** EU prod
- [ ] API Tripo/Meshy/fal — **не** core economics
- [ ] Анимация v1 = rig + presets, не text-to-motion
- [ ] Каждая фича = отдельный RunPod endpoint
- [ ] Immutable image tags, не `:latest` в prod
- [ ] GLB в object storage, не base64 в UI для больших файлов

---

## Журнал решений (стратегия)

| Дата | Решение | Почему |
|------|---------|--------|
| 2026-07-13 | Core = self-host RunPod, не SaaS API | Unit economics: $0.08 vs $0.40+/job |
| 2026-07-13 | TRELLIS.2 как следующий quality tier | MIT, EU, evolution от текущего TRELLIS |
| 2026-07-13 | Hunyuan не для EU prod | Tencent license excludes EU |
| 2026-07-13 | 4 фичи = 4 workers, phased rollout | Не fat Docker; generate first |
| 2026-07-13 | Anim v1 = UniRig + preset retarget | Реалистичный scope; как Tripo/Meshy |
| 2026-07-13 | 3DAIGC-API / Open3DStudio — reference | Карта моделей, не обязательный fork |
