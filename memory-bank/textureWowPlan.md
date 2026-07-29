# Texture Wow Plan — путь к качеству уровня Meshy

> **Статус:** активный фокус с **2026-07-24**  
> **Решение:** пилить текстурирование до вау; остальное (T1c, Clerk…) на паузе.  
> **Обновлено:** 2026-07-29 — **Serverless worker ready** (`worker_mvadapter.py` + `Dockerfile.mvadapter`); W2b tuning checklist.

---

## Вердикт по текущему стеку

| Путь | Вердикт |
|------|---------|
| TRELLIS.2 paint (`worker_texture.py` / Texture v1) | **не prod** — грязный generative albedo |
| TRELLIS.2 bake / `1024_cascade`+textured | **mid** — props терпимо; **character (рыцарь) заметно хуже Meshy** |
| Цель | **~80–90% Meshy** self-host EU с **одной** картинки (не 100%) |

**T1c (Studio → Texture v1 paint) — НЕ делать**, пока нет wow pipeline.

### Доказательство разрыва (рыцарь, 2026-07-24)

- Референс: `preview_textures/ref_gold_armor.png` (золотой доспех + меч), **одна** фотка в оба пайплайна.
- **Meshy (эталон):** меш **без грубых ошибок**, зад читаемый (львы на плечах, пластины спины, пояс), clay уже «скульптурный»; textured — чёткий металл, контраст gold/steel/leather, без мыла. Clay + textured скрины сохранены в сессии (front/back).
- **Мы:** `model-armor-wow.glb` = T2 `1024_cascade` + textured 2048 → силуэт похож, но меш проще/мягче, зад слабее, текстуры **мыльные / пластиковые**.
- Chest W1: `model-wow-baseline.glb` — mid, не вау.

**Вывод Pedrokita:** Meshy **на голову выше** по мешу + заду + текстурам на том же single image. Разрыв = их полный stack (shape + synth MV + texture), не только «чуть лучше bake».

**Важно для продукта:** Meshy не требует multi-view upload. Вау с 1 фото = внутренний synth multi-view + сильные модели. Фаза 2 копирует паттерн self-host; одной подкрутки TRELLIS.2 cascade **недостаточно** (доказано рыцарем).

**Мораль (2026-07-24):** держимся — mid на T2 не приговор; конфету варим стеком, не «ещё cascade». SOTA часто закрыт (Meshy/Hunyuan EU), но OSS MV/texture есть.

---

## Без иллюзий: TRELLIS.2 vs MV-Adapter

> Разделение ролей. Не ждать от одной модели того, что должна дать другая.

### Что реально выжать из TRELLIS.2 (оставить / не ждать чуда)

| Можем получить | Не получим (доказано / потолок семейства) |
|----------------|-------------------------------------------|
| Рабочий **image→3D** self-host EU (MIT) | Вау как Meshy end-to-end на character |
| **Clay preview** за разумные $ (warm ~$0.02–0.03) | Чёткий PBR-металл «из коробки» bake |
| Узнаваемый силуэт props/персонажей | Скульптурный меш уровня Meshy clay |
| Mid textured bake (сундук «норм», рыцарь mid) | Убедительный **зад** как у Meshy с 1 фото |
| Shape-черновик для следующего texture worker | Спасение слабой геометрии «перекраской» |
| Tier preview `512` / quality `1024_cascade` | Догон Meshy seed’ами / 4096 / metallic clamp |

**Роль T2 в продукте:** mid generate + clay + (временно) legacy bake; **не** носитель обещания «как Meshy».  
**Не делать:** ещё A/B cascade ради вау; T1c paint; маркетинг «Meshy quality» на T2 bake.

**Ок крутить у T2 (инфра, не качество-вау):** idle/warm, R2, ETA, clay-first UX, Industry recipes → polish params.

---

### Что обязан дать MV-Adapter (W2) — критерии без розовых очков

MV-Adapter = **не замена всего Meshy**. Это слой:

`1 image (+ наш clay/mesh) → синтетические согласованные виды → texture/bake path`

| Обязан закрыть (иначе W2 провален) | Не обещаем от первого POC |
|------------------------------------|---------------------------|
| С **1 фото** (как Meshy UX) без user multi-view upload | 100% Meshy на рыцаре с первого прогона |
| Заметный рост **sharpness albedo** vs `model-armor-wow.glb` | Идеальный меш (меш всё ещё от T2, пока не сменим shape) |
| Меньше «пластилина» на металле / читаемее материалы | Автоматом починить кривую топологию T2 |
| Работа на **4090 24GB** (SDXL или sd21 fallback) | ≤40GB MVPainter-качество в том же POC |
| Воспроизводимый smoke: рыцарь + сундук, артефакт GLB/atlas | Prod Studio endpoint в первую неделю spike |
| Честный отчёт: ближе к Meshy на X% / всё ещё mid | «Готово, мы Meshy» |

**Если после MV-Adapter tex лучше, а меш/зад всё ещё стыдные:**  
→ текстурный стек ок, **shape** надо усиливать отдельно (другая EU-ok geometry model или Meshy-like refine) — не винить только MV-Adapter.

**Если tex почти не лучше cascade bake:**  
→ пробовать MVPainter (≥40GB) или другой texture backend; не возвращаться к «ещё T2 paint».

---

### Сводка ролей (одна таблица)

| Слой | Кто | Ожидание |
|------|-----|----------|
| Shape / clay | **TRELLIS.2** | mid форма; достаточно для preview и как вход в texture |
| Synth multi-view + чёткие maps | **MV-Adapter** (потом MVPainter) | главный рычаг «слаще рыцаря»; обязан дать видимый скачок tex |
| Polish / viewer | наш код + Studio | блики, HDRI, PBR clamp — дешёвый дожим, не замена модели |
| Эталон | Meshy рыцарь 1 photo | цель качества; не лицензия на копирование их весов |

**Конфета = T2 (форма mid) + MV-стек (внешность) + polish.**  
Не «T2 научится быть Meshy». Не «MV-Adapter починит кривой меш магией».

---

## Целевая архитектура

```
1 image (как у Meshy)
        │
        ▼
┌───────────────────┐
│ 1. Shape          │  TRELLIS.2 clay (оставляем)
└─────────┬─────────┘
          ▼
┌───────────────────┐
│ 2. Synth multi-view│  4–6 согласованных видов ИЗ одной картинки
│    appearance      │  MV-Adapter / MVPainter / …
└─────────┬─────────┘
          ▼
┌───────────────────┐
│ 3. Bake → UV      │  nvdiffrast / projection
└─────────┬─────────┘
          ▼
┌───────────────────┐
│ 4. PBR + polish   │  rough/metal, denoise, seams, clamp
└─────────┬─────────┘
          ▼
        GLB (wow)
```

Опционально позже: юзерские `image_urls[]` как доп. сигнал — бонус, не требование для вау.

---

## Фазы

| Фаза | Что | Срок | Статус |
|------|-----|------|--------|
| **0** | Стоп-линия: paint frozen, T1c off, план в memory | 1 день | ✅ 2026-07-24 |
| **1** | Cascade bake baseline; A/B vs Meshy | 3–7 дней | ✅ chest + **armor проигрыш по sharpness** |
| **2** | Synth multi-view texture POC (MV-Adapter → MVPainter) | 2–4 нед | 🔄 **W2 smoke ✅** → **W2b tuning** |
| **3** | Production `paradox-texture-v2` worker + Studio | 1–2 мес | ⬜ |
| **4** | Polish: seams, upscale, viewer HDRI; опц. multi-image UX | 2–4 нед | ⬜ |
| **5** | Hard cases: characters, prompt retexture | ongoing | ⬜ |

**Критерий успеха Фазы 2:** тот же рыцарь / сундук визуально ближе к Meshy по sharpness albedo и металлу, чем cascade bake.

---

## Spike: кандидаты Фазы 2 (2026-07-24)

### MVPainter

| | |
|--|--|
| Repo | [amap-cvlab/MV-Painter](https://github.com/amap-cvlab/MV-Painter) |
| License | **Apache-2.0** (EU OK) |
| Pipeline | `infer_multiview` → optional `infer_pbr` → `infer_paint` |
| TRELLIS mesh | `--geo_rotation -90` |
| **VRAM** | **≥40 GB** — **не подходит к текущему 4090 pool** |
| Deps | CUDA 12.1, Blender 4.2, custom rasterizer, cupy |

### MV-Adapter (W2 в работе)

| | |
|--|--|
| Repo | [huanngzh/MV-Adapter](https://github.com/huanngzh/MV-Adapter) |
| License | **Apache-2.0** ✅ EU |
| Texture entry | `python -m scripts.texture_i2tex --image … --mesh … --save_dir … --remove_bg` → `*_shaded.glb` |
| MV preview | `scripts.inference_ig2mv_sdxl` (image+geometry → views) |
| **VRAM** | SDXL ~14–16GB; `--variant sd21` если &lt;10GB |
| Extra deps | CV-CUDA; checkpoints RealESRGAN + LaMa |
| Scaffold | `Dockerfile.mvadapter`, `scripts/mvadapter_w2_spike.md` |

**Вывод:** W2 = MV-Adapter на 4090. MVPainter — ceiling позже на ≥40GB.

---

## W2 smoke — результат (2026-07-28)

**Pod:** `rm934rvrjh60g5` (A6000, CPU resume для скачивания).  
**Артефакт:** `knight_i2tex_shaded.glb` (21 MB, albedo **4096² JPEG**, ~444k verts).  
**Baseline:** `model-armor-wow.glb` (cascade T2 bake, albedo **2048²**).

| Критерий | Verdict |
|----------|---------|
| Четче cascade по цвету/контрасту | ✅ золото теплее, меньше «грязного bake» |
| Meshy wow (1 photo) | ❌ мыльновато, дыры на стыках |
| Serverless worker | ✅ `worker_mvadapter.py` + `Dockerfile.mvadapter` |

**Рабочий pip-стек (RunPod `pytorch:2.4.0-cu124`):**  
`torch==2.4.1+cu124`, `diffusers==0.31.0`, `transformers==4.46.3`, `cvcuda-cu12==0.16.0`, `gltflib`, `pymeshlab==2022.2.post3`, nvdiffrast.

**Скачивание с pod:** gateway SSH **без SCP** → `python3 -m http.server 8888` +  
`https://<pod>-8888.proxy.runpod.net/knight_i2tex_shaded.glb`  
или Direct TCP SCP (порт из Connect UI).

**Preview локально:** `python -m http.server 8765` → `scripts/preview_glb_local.html?file=knight_i2tex_shaded.glb`

---

## W2b — что даст **значительное** улучшение

> Разделяем три слоя: **форма (mesh)**, **текстура (UV/projection)**, **мелкие детали (PBR/viewer)**.  
> MV-Adapter **не чинит** дыры в геометрии T2 — только красит то, что есть.

### A. Форма / модель (TRELLIS.2 — главный рычаг для «дыр на меше»)

| Проблема | Причина | Что делать | Impact |
|----------|---------|------------|--------|
| **Чёрные щели на локтях, поясе, стыках пластин** | Часть = **дыры в mesh** (non-manifold, открытые грани, разорванные острова UV после T2) | Inspect GLB **до** texture: `scripts/_inspect_glb_mats.py`, pymeshlab **close holes / remove duplicates / repair non-manifold** | 🔴 высокий |
| Слабый рельеф (лев «плывёт») | T2 mesh **сглажен**, мало high-frequency geometry | `1024_cascade` + выше decimation target; best-of-N seeds; позже — EU shape model с лучшим character | 🔴 высокий |
| Плохой зад | T2 single-view bias | Multi-view **shape** (отдельная тема) или synth views только для tex (не shape) | 🟡 средний |
| Ориентация mesh | MV-Adapter чувствителен к rotation | `--preprocess_mesh`, проверить azimuth камер; сравнить с upstream demo orientation | 🟡 средний |
| Артеfact линии (ноги) | Rig/bones или internal faces в GLB | Strip skeleton, remove internal faces перед texture | 🟡 средний |

**Smoke-test «дыра = mesh или texture?»**

1. Открыть **clay** / untextured mesh в viewer — если щель видна **без текстуры** → **geometry**.
2. Только с текстурой → **UV projection / coverage** (слой B).

### B. Текстура (MV-Adapter — главный рычаг для «мыла»)

| Проблема | Причина | Что делать | Impact |
|----------|---------|------------|--------|
| **Мыльновато** на гравировках | Albedo **JPEG** в GLB; blend 6×768 views | Патч export → **PNG**; `uv_size=4096` уже ок; `num_inference_steps` 50→75 | 🔴 высокий |
| Блики слабые vs ref | Export `metallic=0`, `roughness=0.9` | Post-process GLB: metallic/roughness maps или `scripts/patch_glb_pbr.py` | 🔴 высокий |
| Щели **только в текстуре** | Непокрытые UV (6 views, occluded zones) | `--preprocess_mesh`; inpaint LaMa (уже в pipe); **view mask** для uv_blend; больше views / другой azimuth | 🔴 высокий |
| Цвет не как ref | `reference_conditioning_scale` default 1.0 | Sweep 1.0–1.3; проверить `--remove_bg` | 🟡 средний |
| Log smoke | `No view mask provided for UV blending` | Изучить `uv_blend` / view visibility mask в MV-Adapter | 🟡 средний |

**W2b команда (следующий прогон):**

```bash
python -m scripts.texture_i2tex \
  --image /workspace/data/ref_gold_armor.png \
  --mesh /workspace/data/model-armor-wow.glb \
  --save_dir /workspace/outputs \
  --save_name knight_i2tex_v2 \
  --remove_bg \
  --preprocess_mesh
```

Опционально до texture: mesh repair script (pymeshlab) → `model-armor-wow_repaired.glb`.

### C. Мелкие детали (после W2b или параллельно)

| Слой | Что даёт | Когда |
|------|----------|-------|
| **Normal map** | Рельеф львов/гравировок **без** denser mesh | MVPainter `infer_pbr` (≥40GB) или bake normal из multi-view depth |
| **Metallic/Roughness** | Сталь vs золото vs кожа | MVPainter PBR pass или heuristic из albedo |
| **Viewer polish** | HDRI, tone mapping, `Fix metallic` | Studio / `preview_glb_local.html` — дешёвый дожим |
| **Upscale atlas** | RealESRGAN уже в pipe (`view_upscale=True`) | Проверить что не съедается JPEG export |

**Realistic expectation:** MV-Adapter W2 = **sharp albedo win**. Мелкая скульптура + PBR separation = **MVPainter tier** или multi-pass pipeline (Фаза 2→3).

---

## Дыры: decision tree

```
Щель видна на clay / untextured mesh?
├─ ДА  → T2 geometry (close holes, remesh, лучший seed, другой decimation)
└─ НЕТ → texture projection
         ├─ preprocess_mesh + view mask + inpaint
         ├─ больше / другие camera azimuth
         └─ проверить uv_unwarp (model-armor-wow_unwarp.glb на pod)
```

**Не путать:** Meshy «дыр нет» потому что **shape + texture** согласованы; наш cascade mesh уже с артефактами — MV-Adapter их **подсвечивает**, не создаёт.

---

## W2 checklist (текущий)

- [x] Лицензия Apache-2.0
- [x] Entry `texture_i2tex` + критерии pass/fail в `scripts/mvadapter_w2_spike.md`
- [x] Dockerfile scaffold (не CI)
- [x] Pod helper `mvadapter_create_pod.py` + bootstrap / oneshot scripts
- [x] Pod smoke: `rm934rvrjh60g5` — green run → `knight_i2tex_shaded.glb`
- [x] A/B локально: MV-Adapter **лучше** cascade; **не** Meshy wow
- [x] Pin stack: torch cu124, diffusers 0.31, cvcuda-cu12, gltflib
- [ ] **W2b:** `--preprocess_mesh`, mesh repair, PNG export, PBR patch
- [ ] **W2b:** chest prop (второй asset) — regression
- [ ] Stop pod после W2b (volume OK на EXITED)
- [x] `worker_mvadapter.py` + `Dockerfile.mvadapter` + `test_req_mvadapter.py` — Serverless worker ready
- [ ] Если tex plateau → MVPainter ≥40GB

---

## W2b checklist (следующий спринт)

| # | Task | Owner | Expected win |
|---|------|-------|--------------|
| 1 | Mesh inspect + repair (holes, non-manifold) before texture | paradox_worker | меньше **geometry** дыр |
| 2 | `texture_i2tex --preprocess_mesh` + orientation doc | paradox_worker | меньше UV щелей |
| 3 | PNG albedo in GLB export (patch gltflib save) | paradox_worker | меньше мыла |
| 4 | `patch_glb_pbr.py` metallic/roughness from ref heuristics | paradox_worker | блики ближе к ref |
| 5 | Sweep `reference_conditioning_scale`, steps 75 | pod smoke | цвет/резкость |
| 6 | Clay A/B: щели на clay? → shape vs texture verdict | manual | decision tree |
| 7 | Document RunPod download recipe (HTTP 8888) | spike.md | ops |
| 8 | `--resume` in `mvadapter_create_pod.py` | paradox_worker | ops |

---

## Track A — clay seeds (active)

**Goal:** best mesh (fewest holes) from same `ref_gold_armor.png`, then repair → MV v2.

**Winner (2026-07-28, wireframe A/B):** **seed 42**
- рога целые (на 1/7/123 кончики рогов склеены)
- нет дыр у локтей и на поясе
- файл: `model-armor-clay-seed42.glb` → repair → `model-armor-clay_repaired.glb`

```powershell
# 1. Host ref image (R2) → IMAGE_URL
python scripts/batch_seeds_trellis2.py `
  --image-file preview_textures/ref_gold_armor.png `
  --seeds 1 7 42 123 `
  --texture-mode clay `
  --out-prefix model-armor-clay-seed

# 2. Wireframe in preview_glb_local.html → pick best seed
# 3. Repair
python scripts/repair_glb_mesh.py model-armor-clay-seed42.glb -o model-armor-clay_repaired.glb

# 4. MV v2 on pod (after Start) with repaired clay mesh
```

Scripts: `scripts/batch_seeds_trellis2.py`, `scripts/repair_glb_mesh.py`, `scripts/upload_r2_asset.py`.

---

## Следующий конкретный шаг

1. ~~W1 cascade + armor A/B~~ ✅  
2. ~~W2 kickoff + smoke knight~~ ✅ (partial pass)  
3. **Сейчас:** W2b — mesh repair + `--preprocess_mesh` + PNG/PBR export → второй прогон рыцаря  
4. Параллельно: зафиксировать «дыры = mesh T2» vs «UV gaps» на clay viewer  
5. Если tex plateau после W2b → MVPainter на ≥40GB pod (ceiling)

---

## Не делаем

- Тюнить TRELLIS paint / «ещё cascade seed»
- Hunyuan в EU prod
- Meshy API в core
- Обещать 8K как Meshy сразу
- Требовать от юзера multi-view для базового вау (Meshy не требует)
