# Texture Wow Plan — путь к качеству уровня Meshy

> **Статус:** активный фокус с **2026-07-24**  
> **Решение:** вау упирается в **мыльный меш**; краска вторична.  
> **Обновлено:** 2026-07-31 — E2 отменён (unit economics); только shape.

---

## Мыльный меш → куда смотреть

### Исходное суждение (держать)

**Меш T2 на рыцаре мыльный по мелким деталям.**  
Макро / силуэт — сильный, издалека даже вау. Узоры (плечи, грудь, пояс) — месиво.  
Meshy на той же картинке держит орнамент в Solid.

| | T2 clay seed42 | Meshy |
|--|----------------|-------|
| ~Verts / tris | **~230–240k** / ~471k | **~337k** / ~640k |
| Макро | ок | ок |
| Микро-узоры | **мыло** | читаемые |

**Про вершины:** Meshy ~**+40% verts** (~337k vs ~240k) и больше faces — у них просто **больше бюджета на рельеф**. Это не единственная причина (у нас 471k tris уже «шум» на орнаменте, не чёткие львы), но **игнорировать разницу нельзя**: мы режем/ремешим агрессивнее, чем эталон.

**Следствие:** пока нет мелкой геометрии — **красить бессмысленно**.  
Но гипотеза Pedrokita: **T2 умеет круче — мы могли накосячить в пайплайне**, а не только «потолок модели». Сначала проверить это дёшево (наши рычаги), потом чужие модели.

### Где мы могли накосячить (наш T2 clay path)

Код: `worker_trellis2.py` → `_mesh_to_clay_glb`. Track A: `1024_cascade`, `remesh=True`, `decimation_target=500_000`, seed42.

| Рычаг | Сейчас | Риск |
|-------|--------|------|
| **`remesh=True`** | `remesh_narrow_band_dc` + simplify | Ремеш **сглаживает** HF; классика «мыла» |
| **`project_back=0.0`** | захардкожено | Нет проекции обратно на исходную поверхность → деталь теряется |
| **`pipeline_type`** | Track A = **`1024_cascade`** | Есть **`1536_cascade`** — на рыцаре **не гоняли** |
| **`decimation_target`** | 500k → на выходе ~471k F / ~230k V | Meshy ~640k F / ~337k V; можно поднять target и/или `remesh=false` |
| **Критерий Track A** | дыры / рога, не орнамент | Winner по дырам ≠ winner по микро-детали |
| **repair** | trimesh/pymeshlab | Вряд ли главный мыло-фактор; вторично |

**Дешёвый A/B на том же seed42 / том же ref (только Solid, без paint):**

1. `remesh=false` (или позже `project_back>0` если протащим в input)  
2. `pipeline_type=1536_cascade`  
3. выше `decimation_target` (например 700k–1M) — ближе к бюджету Meshy по плотности  

Если после этого узоры всё ещё мыло → тогда потолок T2 / нужна другая shape-модель.  
Если стало ближе к Meshy → **мы виноваты в постпроцессе**, не «T2 плохой».

### Отменено

| Идея | Почему нет |
|------|------------|
| Seeds как фикс орнамента | Не снимают класс мыла (дырки — да, львы — нет) |
| Paint / W2b / serverless wow на мыльном clay | Красим мыло |
| E2: Meshy-меш + наша краска | Unit economics / не prod |

### Порядок

```
1a. A/B нашего T2 (remesh / 1536 / denser) — дёшево, self-host
1b. Если мало → shape spike EU (Hi3DGen …)
2. UV / poly (не убивая HF)
3. Texture
4. PBR / viewer
```

### Кандидаты (сравнение «где лучше / где мы слабее»)

| Кандидат | Сильная сторона | Слабая / риск | EU | Когда трогать |
|----------|-----------------|---------------|-----|----------------|
| **TRELLIS.2** (наш) | Макро, MIT, уже в prod, warm COGS | Микро мыло **на текущем clay path**; не гоняли 1536 / no-remesh | ✅ | **Сначала A/B пайплайна** |
| **Meshy** | Микро-орнамент, ~337k V | Закрытый SaaS, не core economics | n/a | Только эталон глазами |
| **Hi3DGen** | Заточен под **HF geometry** (normal bridging); MIT; часто хвалят за detail vs Trellis-семейства | Отдельный стек/Pod; не наш warm path | ✅ | Spike Solid после/параллельно T2 A/B |
| **TripoSG** | Shape MIT, roadmap Tier S | Меньше evidence на ornament character | ✅ | Второй spike если Hi3DGen/T2 A/B слабо |
| **Hunyuan3D** | Очень сильный | **Не EU prod** | ❌ | Не core |

**Итог сравнения:** эталон качества = Meshy Solid. Наш gap = микро + меньше vert budget. Кандидат №1 на починку — **не сразу новая модель**, а проверка «T2 + честный export». Кандидат №2 на замену/дополнение shape — **Hi3DGen** (геометрия).

**Следующий шаг:** T2 clay A/B на `ref_gold_armor` seed42 — **прогоны DONE 2026-08-01**, нужен визуальный Solid вердикт.

### T2 A/B прогон (2026-08-01) — гипотеза «портим export»

| | Baseline seed42 | A no-remesh | B 1536_cascade |
|--|-----------------|-------------|----------------|
| pipeline | 1024_cascade | 1024_cascade | **1536_cascade** |
| remesh | True | **False** | True (default) |
| decimation_target | 500k | **700k** | **700k** |
| Verts | ~230–240k | **~351k** | **~327k** |
| Faces | ~471k | **~677k** | **~673k** |
| Файл | `model-armor-clay-seed42.glb` | `model-armor-clay-noremesh42.glb` | `model-armor-clay-1536-42.glb` |
| Wall | (Track A warm ~30s) | ~322s cold | ~98s warm |

Плотность теперь **в зоне Meshy** (~337k V / ~640k F) или выше.  

### Вердикт глаз (2026-08-02, Pedrokita) — гипотеза **FAIL**

На no-remesh / 1536 (и в целом):
- наплечники — размазаны / **каша**  
- пояс + «ткань» под ним — **каша**  
- топология на мелких деталях — ужас  

**Вывод:** больше verts/faces не сделали орнамент читаемым. Remesh/1024 — не главный виновник HF-каши.  
T2 на этом character даёт сильный **макро**, слабый **микро** (шум вместо скульптуры).  

→ Не крутить дальше T2 ради львов **как основной план**. Hi3DGen Solid — следующий shape spike.  
T2 роль: preview / mid / props; не носитель «Meshy-орнамент».

### Ещё колдовство над T2? (разбор идей, 2026-08-02)

| Идея | Реализм | Заметка |
|------|---------|---------|
| **Лучший вход** (чистый cutout, без грязного rembg, ровный свет, выше res) | 🟡 дешёвый A/B | Может чуть подтянуть силуэт/зад; **не** превратит кашу-льва в Meshy-скульпт |
| **`preprocess_image=false`** + ручной alpha | 🟡 1 job | Имеет смысл один раз проверить |
| **Multi-view в T2** (несколько ракурсов объекта) | 🟠 у нас **не подключено** | Официальный T2 card = single image; v1 имел `run_multi_image`; T2 multi = community forks / Comfy, не наш worker |
| **Синтез «видов со всех сторон» → T2** | 🔴 дорого / R&D | По сути строить кусок Meshy; synth MV сам ошибается → в T2 уйдёт каша с других сторон |
| **Кропы мелких деталей (лев, пояс) как доп. вход** | 🔴 почти нет | Модель ждёт **виды целого объекта**, не патчи орнамента; у нас API только `image_url` |
| Ещё seeds / steps ради HF | ❌ | Уже отказ; класс каши не снят |

**Честно:** идея «нагенерить виды + детали и скормить T2» звучит как Meshy UX, но **self-host это отдельный стек** (MV synth + multi-cond + валидация), не «ещё один флаг».  
Дешёвый остаток на T2: **один** прогон с лучшим cutout / `preprocess=false`. Если каша та же — закрываем T2-колдовство по орнаменту.

### Cutout + no-preprocess (2026-08-02)

| | Baseline seed42 | Cutout + `--no-preprocess` |
|--|-----------------|----------------------------|
| image | RGB + BiRefNet preprocess | RGBA u2net cutout, preprocess off |
| remesh / pipeline / decim | True / 1024_cascade / 500k | same |
| Verts / faces | 231023 / 471924 | **238373 / 482836** |
| Файл | `model-armor-clay-seed42.glb` | `model-armor-clay-nopreprocess42.glb` |
| Cutout URL | — | `…/smoke/ref_gold_armor_cutout.png` |

**Вердикт = глаза** (наплечник / пояс): стал ли орнамент читаемее? Если нет → тема «неправильно подаём» закрыта → **сначала T2 max-quality (sampler)**, потом Hi3DGen.

---

## T2 max-quality (2026-08-02) — следующий прогон

> Источники: upstream `Trellis2ImageTo3DPipeline.run`, [issue #92](https://github.com/microsoft/TRELLIS.2/issues/92), community (skip heavy simplify / remesh), fal/hard-surface tips.  
> Цель: **исчерпать рычаги T2** до Hi3DGen.

### Что уже закрыто

| Прогон | Итог |
|--------|------|
| no-remesh + 700k | denser, орнамент каша |
| 1536 default steps | denser, каша |
| cutout + no-preprocess | почти тот же polycount, ждать/уже глаза |

### Чего ещё не делали (главное)

Worker **не пробрасывал** в `pipeline.run`:
- `sparse_structure_sampler_params` (`steps`, `guidance_strength`, `guidance_rescale`, `rescale_t`)
- `shape_slat_sampler_params` (то же — **главный рычаг fine geometry** по community)
- `max_num_tokens` (cascade downsample)

### Preset `t2_max_quality` (один clay job)

```text
image_url     = …/smoke/ref_gold_armor_cutout.png
preprocess    = false
pipeline_type = 1536_cascade
seed          = 42
texture_mode  = clay
decimation    = 800000
remesh        = false
ss:    steps=50 guidance=8.0 rescale=0.7 rescale_t=6.0
shape: steps=50 guidance=8.5 rescale=0.5 rescale_t=6.0
max_num_tokens = 65536
→ save model-armor-clay-maxq42.glb
```

Опционально B: те же sampler + `remesh=true` (чище topo vs резкость).

### Порядок работ

1. Код: проброс params в `worker_trellis2.py` + `--quality-max` в `test_req_trellis2.py`  
2. Push → CI `build-trellis2` → **New Release** на `ynzpzjvcbfl656`  
3. Smoke max-q (~дольше default; cold дорого)  
4. Solid vs Meshy / seed42  
5. Pass → recipe; Fail → Hi3DGen, T2 тюны по орнаменту **стоп**

Логи A/B: `track_a_ab_noremesh.log`, `track_a_ab_1536.log`, `track_a_ab_nopreprocess.log`.


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

## W2c — latency + prod UV (2026-07-31) ✅ latency done

> Path работает. **80k = ~8 мин**, но на рыцаре **качество просело** (месиво). Дальше — § «Ближе к вау», не ещё latency.

### Измерения

| Прогон | Faces | xatlas | wall | Качество |
|--------|-------|--------|------|----------|
| `knight_fast` | ~471k | ~1502 с | ~29 мин | лучше деталь, дорого |
| `knight_w2c` | ~80k | ~145 с | **~8 мин** | быстро, орнамент убивает |

### Решения (не менять)

| Было | Стало |
|------|--------|
| Open3D UVAtlas | **запрещён** |
| Clay без UV | **xatlas** → bake `uv_unwarp=False` |
| Serverless 30 мин | не гонять marathon |

### Checklist latency

| # | Task | Status |
|---|------|--------|
| 1 | Decimate перед xatlas | ✅ 80k работает |
| 2 | Pod wall минуты | ✅ ~8 мин |
| 3 | Кеш UV / UV на clay в T2 | ⏸ позже |
| 4 | Serverless | ⏸ после качества Q1–Q3 |

**Meshy-like ops:** remesh/decimate + UV раз + bake. Poly budget **подбирать глазами** (не слепо 80k на character).

---

## W2b — мелочи краски (ТОЛЬКО после Q1–Q3)

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
- [x] **2026-07-31:** xatlas path DONE_OK; W2c ~8 мин @ 80k
- [x] **2026-07-31:** A/B vs Meshy зафиксирован — месиво = меш first
- [ ] **Q1–Q3:** seeds → faces A/B → один paint
- [ ] W2b мелочи / W3 — после Q1–Q3
- [ ] Если tex plateau → MVPainter ≥40GB / другой shape

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

1. ~~A/B remesh/1536/cutout~~ ✅ (плотность↑, каша осталась / cutout на глазах)  
2. **T2 max-quality:** код sampler → deploy → `model-armor-clay-maxq42.glb`  
3. Глаза → recipe или **Hi3DGen**  
4. Texture — только после не-мыльного shape

---

## Не делаем

- Synth multi-view R&D до исчерпания sampler max-q  
- Красить кашу / E2 Meshy-меш  
- Обещать Meshy-деталь на default T2  
- Hunyuan в EU core  
- Бесконечные seeds ради орнамента
