# AI_MESH — дорожная карта платформы

> **Назначение:** стратегический план платформы (4 фичи на сайте, модели, фазы, экономика).
> **Связанные файлы:** `projectbrief.md`, `systemPatterns.md`, `activeContext.md`.
> Последнее обновление: **2026-07-22** (фазы 0/1 + quality sprint)

---

## Quality sprint (2026-07-22)

Улучшение генерации **без retrain TRELLIS.2** — рецепты вокруг пайплайна:

| # | Задача | Статус |
|---|--------|--------|
| 1 | Industry Quality Recipes (`industryPresets` → polish, T2I, `decimation_target`) | ✅ POLY_LAB |
| 2 | Warm ETA + `warm_timing_t2.py` (ops-повтор later) | ✅ |
| 3 | Best-of-N seeds UI | ⏸ отложено — seed только same model+image |
| 4 | Upload quality hints | ✅ POLY_LAB (`imageQuality.ts`) |
| 4b | Image Enhancement toggle (2D preprocess) | ✅ POLY_LAB (`imageEnhance.ts`) |
| 5 | Library UX | ✅ POLY_LAB (`JobHistory` filters) |
| 6 | Auth + credits mock | ✅ POLY_LAB (Guest wallet, 402 on low balance) |
| next | Clerk/Stripe or Texture worker | ⬜ |

**Seed:** не «лучшее зерно мира». Best-of-N = N стохастических прогонов **одного** T2 на одном входе. Между моделями seed не переносится. UX проще: «Ещё вариант».

Промпт влияет на mesh только через **Text→Image→T2**. Single-view: не обещать идеальную «спину».

---

## Видение продукта (сайт)

На AI_MESH пользователь получает **pipeline из четырёх инструментов** (не одна кнопка):

| # | Инструмент на сайте | Что делает | Статус |
|---|---------------------|------------|--------|
| 1 | **3D генерация** | **Image → textured mesh (GLB)**; text→3D как отдельный путь | 🟡 MVP (`paradox_worker`, TRELLIS v1/T2) |
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

### Text → 3D: варианты реализации (2026-07-20)

1. **MVP bridge (рекомендовано):** text → image (LLM image model) → текущий T2 image→3D.
   - Плюсы: почти без изменений worker, быстрый запуск в Studio.
   - Минусы: качество ограничено этапом text→image.
2. **Отдельный text2mesh endpoint:** прямой text→3D worker.
   - Плюсы: нативный text→3D.
   - Минусы: новый стек, выше COGS, больше R&D/лицензионных рисков.
3. **Hybrid:** preview через bridge, quality через text2mesh позже.

**Решение на сейчас:** MVP делать через вариант 1; вариант 2 — после стабилизации Studio image→3D флоу.

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

**Измерено 2026-07-20 (4090, paradox_worker T2 endpoint):**

| Tier | Cold | Warm | Примечание |
|------|------|------|------------|
| T2 preview `512` clay | ~$0.13 | ~$0.02–0.03 | **2026-07-22:** warm wall **27.3 с** avg (5× run); cold wall **812 с** (0 workers at start) |
| T2 Full `1024_cascade` | ~$0.16 | ~$0.08 | warm = оценка (exec − model_load) |
| v1 RO | ~$0.04 | ~$0.01 | legacy fast |

Blended COGS Full при 40% warm ≈ **$0.13**; при 70% warm ≈ **$0.10**. Операционно: очередь + не гасить GPU в пик.

**Конкуренты (цена для юзера, не их COGS):** Meshy Pro ~$0.40/job (20 cr), Meshy API ~$0.60, fal/Tripo ~$0.30–0.50.

**Вердикт:** monetization viable на self-host; не перепродавать API; не позиционировать как «дешёвый Meshy 1:1» — ниша + preview/quality + честный ETA.

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

> Статус фаз обновлён **2026-07-20** (факт vs план 07-13).

### Фаза 0 — foundation worker — ✅ essentially done

- [x] Стабильный generate (v1 RO COMPLETED; CZ stale — не blocker)
- [x] RunPod GPU list / idleTimeout / immutable tags / FlashBoot off T2
- [x] T2 quality endpoint + R2 `model_url` + watchdog
- [x] Замеры cold/warm, seeds, A/B T2 vs v1
- [ ] SF3D fast tier — **отложено** (preview = T2 `512`)

### Фаза 1 — MVP платформы — 🟡 in progress (~70%)

- [x] Frontend PolyLab (`POLY_LAB`): landing + `/generate` + viewer
- [x] Live image→3D: R2 upload → T2 → proxy-glb; zombie watchdog в Next
- [x] Persist jobs / **asset library** (JSON `.data/jobs.json` MVP)
- [x] Text→3D hybrid (text→image→T2) + polish
- [x] Preview/Quality в UI + ETA/cost CTA
- [x] **Clay-first generate** (`texture_mode: clay|textured` в worker; Studio default clay)
- [x] Docker/Release clay worker на `ynzpzjvcbfl656` (`6d763fa`)
- [x] **Industry Quality Recipes** в Studio (prompt + decimation по отрасли)
- [x] Library UX filters + Image Enhancement + upload hints
- [x] Auth + credits mock (Guest wallet; Clerk later)
- [ ] Best-of-N seeds в UI — **отложено** (seed only same model+image)
- [ ] Auth + credits/billing — Clerk/Stripe (mock done)

**На сайте сейчас:** п.1 «3D генерация» = **clay mesh** (как Meshy); textured bake = legacy opt-in; отрасль = quality recipe.

---

### Фаза 2 — post-process (2–3 мес) — ⚪ не начато

- [ ] Worker **retopo** (FastMesh + PartUV)
- [ ] Worker **retexture / PBR** (TRELLIS paint) — **отдельная фича после clay generate**
- [ ] Pipeline: one-click «оптимизировать» / «перетекстурировать» из результата gen

**Продукт:** Generate (clay) → [опц.] Texture (PBR) → [опц.] Retopo → Export.  
Не обещать photoreal мелкий текст на single-view bake.

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
