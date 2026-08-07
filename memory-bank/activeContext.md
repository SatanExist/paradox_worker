# Активный контекст

> **Как пользоваться:** в начале каждого нового чата — `@memory-bank/activeContext.md`.
> В конце сессии: *«Обнови activeContext — что мы сделали»* → `git push`.
> Синхронизация вдвоём: см. `@memory-bank/teamWorkflow.md`.

Последнее обновление: **2026-08-07** — 🟢 **mid-prop holes gate CLOSED** (soft v16); **фокус = MV2 Wonder3D**

---

## 🟢 Mid-prop holes gate — CLOSED (2026-08-07)

| | |
|--|--|
| **Win** | `soft_input` на T2 (strength 0.75) — chest без сквозных дыр, clay smooth |
| **Live** | image `trellis2-sha-91f8441`, endpoint **v16** |
| **Артефакт глаз** | `model-chest-soft-worker-v16.glb` — Pedrokita: **замечательно** |
| **Не путь** | voxel (Minecraft), CuMesh knobs alone, trimesh fill |
| **Lattice/open** | industry limit (Meshy тоже плёнки) — best-effort, не блокер |
| **Ops** | после deploy: recycle workers (stale idle); echo `generation.soft_input` |

Мастер: `memory-bank/midPropHolesGate.md` (исторический канон; статус 🟢).

### План дальше

| # | Шаг | Статус |
|---|-----|--------|
| ✅ | Soft productize + deploy + smoke | done |
| 🔄 | **MV2** Wonder3D 1→6 RGB → T2 `image_urls` | **сейчас** |
| ⏸ | MV3 wrap API / Studio | after MV2 GO |
| ⏸ | Режимы `solid`/`character` (soft on/off) | later |
| ❌ | voxel prod, per-SKU presets | — |

## ⚠ INCIDENT 2026-08-06 — забытый pod

| | |
|--|--|
| Pod | `dynmbd1jzzvd04` (`paradox-g1c-holes`, 4090 ~$0.74/ч) |
| Что случилось | SSH fail → pod оставили RUNNING → деньги сгорели |
| **Правило** | Любой pod: **terminate в той же сессии**, даже если smoke не прошёл |

```powershell
.\.venv\Scripts\python.exe scripts\mvadapter_create_pod.py --list
.\.venv\Scripts\python.exe scripts\mvadapter_create_pod.py --terminate <pod_id>
```

## Кто работал последним

| Поле | Значение |
|------|----------|
| Кто | Pedrokita (с Cursor агентом) |
| ПК | Windows (`D:\AI_HUB\paradox_worker`) |
| Ветка worker | `feat/trellis2-poc` |
| Фокус | 🔄 **MV2 Wonder3D** (holes gate 🟢) |

### 🔄 MV2 — сейчас

| | |
|--|--|
| **Цель** | 1 user photo → Wonder3D 6 RGB views → T2 multi (`image_urls`) |
| **Spike** | `scripts/wonder3d_mv2_spike.md` |
| **Не** | Wonder3D mesh как product shape; Era3D (AGPL) |
| **Ops** | короткий GPU pod + **terminate сразу**; бюджет беречь (~$19) |

| # | Шаг MV2 | Статус |
|---|---------|--------|
| 1 | Pod oneshot Wonder3D → 6 views (armor + chest) | 🔄 |
| 2 | Eyes consistency F/L/R/B | ⏸ |
| 3 | Optional: views → T2 multi smoke | ⏸ |
| 4 | Verdict GO/NO-GO → MV3 | ⏸ |

### Holes gate (архив статуса)

| # | Шаг | Статус |
|---|-----|--------|
| **G0–G1e** | research / fill / voxel / soft / lattice | ✅ closed |
| **G2** | soft in worker + deploy v16 | ✅ |
| **G3** | eyes soft worker | ✅ GO |

### Prod policy (как у крупных 3D SaaS) — GO 2026-08-04, live 2026-08-05

| Тема | Решение |
|------|---------|
| Тиры | `preview` / `quality` (default product) / `ultra` (= rt6) |
| **Не per-asset** | Тиры = **VRAM/ETA ladder**, не «пресет для сундука vs рыцаря». Разный вход → downgrade, не отдельный tier per SKU |
| Ultra | best-effort; сложный вход (chest) → OOM на remesh |
| При OOM | worker **auto-downgrade**: (1) remesh=false на том же меше → (2) полный re-infer `quality` |
| Ответ | `quality_tier_requested/used`, `downgraded`, `downgrade_reason`, `downgrade_attempts` |
| Выключить | `allow_downgrade=false` / CLI `--no-downgrade` |
| UX Studio | не показывать CUDA OOM; «качество снижено» если downgraded |
| Hi3DGen | после T2+texture |
| **Mid-prop holes** | 🟢 closed (soft_input v16) → `midPropHolesGate.md` |

**Smoke 2026-08-05:** armor `ultra` ✅; chest P2b live но **дыры** → gate. Deploy: `trellis2-sha-4c24928` v15.

### Решения зафиксированы

| Тема | Решение |
|------|---------|
| Hi3DGen | **после** полного T2 + texture |
| Single-view knobs | **закрыты** → recipe **rt6** = tier **ultra** |
| MV1 | ✅ |
| Synth / MV2 | **⏸ until holes gate 🟢** |
| Per-asset presets | **нет** |
| Mid-prop holes | **blocker**; post-repair (Meshlib) = путь; CuMesh недостаточен |

### С чего начинаем сейчас

1. 🔴 **G1–G3** mid-prop holes — см. `midPropHolesGate.md`
2. ~~MV2~~ **paused**
3. Основной план (MV2→MV6) — **только после 🟢 gate**

### Единый план (с blocker)

```
✅ MV0–MV1 → ✅ P1–P2 → ✅ R1
                    ↓
               🔴 G0–G3 mid-prop holes   ← МЫ ЗДЕСЬ
                    ↓
               🟢 gate
                    ↓
               ⏸ MV2 → MV3 → MV4 → MV5 → MV6
                    ↓
               ⏸ X* / P3 / H0
```

| # | Шаг | Статус |
|---|-----|--------|
| MV0–MV1 / P1–P2 / R1 | infra | ✅ |
| **G0–G3** | mid-prop holes gate | 🔴 G1 |
| **MV2** | Wonder3D | ⏸ after gate |
| MV3–MV6 | synth shape product | ⏸ |
| X* / P3 / H0 | texture / studio / Hi3DGen | ⏸ |
| **MV6** | Recipe freeze «1-photo shape» | product | ⏸ |
| **P2c** | Meshlib hole fill | жёстче CuMesh | ⏸ if still needed post-MV4 |
| **P3** | Studio: tier UX + downgraded badge | product front | ⏸ parallel later |
| **X1** | MV-Adapter texture на best clay | вау tex | после MV5 / \|\| W2b |
| **X2** | W2b holes (mesh repair, PNG, PBR) | tex polish | ⏸ |
| **H0** | Hi3DGen spike | next-tier shape | ⏸ после T2+tex |
| **S0** | Studio 1-upload E2E | product | ⏸ |

#### Что значит «пресеты» (важно — обновлено research R1)

| Вопрос | Ответ |
|--------|--------|
| Нужен пресет «сундук vs рыцарь»? | **Нет** — docs Microsoft/HF/CuMesh **не дают** per-asset class; только knobs |
| Наши `preview/quality/ultra` | **VRAM/ETA/resolution ladder**, не «уровень моделирования объекта» |
| Почему рыцарь без дыр, сундук с дырами? | Глаз: сундук «проще». T2: **thin spikes, cracks-as-gaps, lid/body, skull joints** = дороже для occupancy, чем thick armor |
| Почему ultra на сундуке OOM? | remesh VRAM на denser occupancy — не «сломанный» tier |
| Что говорит HF card? | *Geometric Artifacts (Small Holes)* — **known limitation**; hole-fill scripts |
| Что говорит community (Comfy)? | remesh → simplify → **FillHoles Meshlib** (сильнее CuMesh perimeter) |
| Issues | [#25](https://github.com/microsoft/TRELLIS.2/issues/25) remesh/inner hull; [#105](https://github.com/microsoft/TRELLIS.2/issues/105) no-remesh → holes |
| Product default | `quality` = mid stable; `ultra` = best-effort |
| Не делать | 20 asset presets до synth multi-view — оверинжиниринг vs docs |

#### Tier presets (код `TIER_PRESETS`)

| Tier | pipeline | decim | steps | interval | remesh | Когда |
|------|----------|-------|-------|----------|--------|-------|
| `preview` | 512 | 300k | 12 | [0.6,1] | on | ETA / демо |
| `quality` | 1024 | 500k | 12 | [0.6,1] | on | **default prod**; `max_hole_perimeter=0.1` (P2) |
| `ultra` | 1536 | 700k | 50 | [0,1] rt6 | on | best-effort → downgrade |

### Research R1: дыры, «простой» prop, presets (2026-08-05)

#### Официальные docs / HF / README
- Input = **single image**; export recipe один: `to_glb(remesh=True, remesh_band=1, …)`.
- **Нет** tutorial «preset for props / characters / difficulty».
- HF **Limitations**: small holes / topological discontinuities — ожидаемо; для watertight → hole-filling.
- CuMesh `fill_holes(max_hole_perimeter)` — только **boundary loops** заданного размера; не weld стыков, не «трещина → рельеф».

#### Глаз vs voxel-сложность (Pedrokita observation)

| | Рыцарь | Сундук (example TRELLIS chest) |
|--|--------|--------------------------------|
| Для глаза | сложный character | «простой» prop |
| Для T2 occupancy | thick continuous silhouette | thin spikes, wood cracks→gaps, multi-part joints |
| Ultra | ✅ влезает | часто OOM → `quality` |
| Типичный дефект | мыло орнамента (micro) | **дыры / щели** (topology) |

**Миф:** «проще скульптура ⇒ меньше дыр».  
**Факт:** дыры коррелируют с **тонкими / открытыми / стыкующимися** структурами + known O-Voxel artifacts, не с «количеством полигонов в голове художника».

#### Community export ladder (не официальный Microsoft product API)
```
raw O-Voxel mesh
  → remesh (CuMesh)
  → simplify
  → fill_holes (CuMesh perimeter)     ← у нас P2/P2b
  → [опц.] Meshlib / reconstruct      ← P2c R&D
```
Comfy Trellis2 workflows явно добавляют **Trellis2FillHolesWithMeshlib** после remesh — сигнал, что CuMesh hole fill **недостаточен** на hard cases.

#### Следствия для плана
1. **Не** плодить per-SKU presets.
2. P2 CuMesh — закрыт; остаточные дыры chest → **P2c Meshlib** (дешёвый A/B) **и/или** **MV2** (корневой shape).
3. Честный A/B дыр: один `quality_tier` на armor и chest (не ultra-armor vs quality-chest).
4. Studio UX: «дыры на props» = expected mid; wow через synth MV + post, не обещать watertight на single-view T2.

### План фичи: 1 фото → ракурсы → T2 (деталь MV*)

| # | Шаг | Статус |
|---|-----|--------|
| MV0–MV1 / P1–P2 / R1 | закрыты | ✅ |
| **MV2** Wonder3D views only (не их mesh) | spike doc ✅; pod smoke 🔄 | 🔄 |
| MV3–MV6 | worker → T2 wire → A/B → freeze | ⏸ |
| P2c Meshlib | только если нужно после MV4 | ⏸ |

### MV2 notes (2026-08-05)

- Чеклист: `scripts/wonder3d_mv2_spike.md`
- Scope: **RGB×6** для `image_urls` → T2; Instant-NSR/NeuS Wonder3D mesh = **out of scope**
- HF: `flamehaze1115/wonder3d-v1.0` + custom pipeline; gen **256²**; azimuth 0/45/90/180/-90/-45
- Wonder3D++ branch — later if v1 weak
- Spike env: **RunPod Linux 4090**, не Windows marathon
- Success: armor + chest view grids + optional T2 multi smoke

### Research: MV1 / synth / N views (2026-08-04)

#### Официальный T2 про multi-image
- HF model card / README Microsoft: **Input = Single Image**. Официальных туториалов «1→ракурсы→T2» **нет**.
- Issue [#10](https://github.com/microsoft/TRELLIS.2/issues/10): multi = community workarounds, не roadmap от Microsoft.
- PR [#104](https://github.com/microsoft/TRELLIS.2/pull/104): open, tuning-free fusion (`stochastic` / `multidiffusion`); автор: multidiffusion может **деформировать** пропорции.
- Issue [#103](https://github.com/microsoft/TRELLIS.2/issues/103): у части людей multi **хуже** single; stochastic чаще ok, multidiffusion — спорно.
- TRELLIS **v1** README: multi-image есть, но *tuning-free, may not give best for all images*.

**Вывод MV1:** коммит/деплой multi **имеет смысл как инфраструктура** (есть серию), но версия **заведомо не final** — официально T2 single-image; fusion API ещё эволюционирует. OK деплоить early.

#### Synth multi-view кандидаты (качество vs прод)

| Кандидат | Согласованность видов | Лицензия | Прод self-host AI_MESH |
|----------|----------------------|----------|-------------------------|
| **Zero123 / XL / Stable Zero123** | слабее (по 1 виду за раз) | часто research / Stability caps | слабо как prod core |
| **Zero123++** | лучше (тайл 6 видов за раз) | code Apache, **weights CC-BY-NC** | ❌ commercial weights |
| **Era3D** (6 view, 512) | сильный paper / ortho variant | **AGPL-3.0** | ❌ без open-source всего продукта |
| **SV3D** (Stability) | очень сильный consistency | Community / **$1M revenue** / Enterprise | ⚠ не как дешёвый core |
| **Wonder3D / ++** | 6 видов color+normal; зрелый | **MIT** | ✅ кандидат #1 на spike |
| **InstantMesh** pipeline | паттерн: synth 6 → reconstruct | code Apache; MV часто через Zero123++ NC | ⚠ паттерн ок, веса MV-весов проверить |
| **MV-Adapter** (уже у нас) | 6 views для tex (+mesh) | **Apache-2.0** | ✅ уже в стеке; для *shape* — отдельный spike (ig2mv без/со слабым mesh?) |

**Не Era3D в prod** из‑за AGPL. Spike качества можно на Era3D offline, prod путь — **Wonder3D (MIT)** и/или переиспользование **MV-Adapter** views.

#### Сколько ракурсов (4 vs 6)
- **Wonder3D / Era3D / InstantMesh**: дефолт пайплайна = **6** видов (фиксированные azimuth).
- InstantMesh: можно **меньше** views, если synth inconsistent — иногда лучше.
- T2 multidiffusion: cost/VRAM ~×N; stochastic дешевле.
- **v1 рекомендация:** стартовать **6** (как в литературе), A/B против **4 (F/L/R/B)** на рыцаре; не фиксировать N до MV5.

#### Рекомендуемый порядок ( Pedrokita GO — freeze 2026-08-05 )
1. ~~MV1 / P1 / P2 / R1~~ ✅
2. **MV2** Wonder3D spike (views) — 🔄
3. **MV3** worker 1→N
4. **MV4** → T2 multi
5. **MV5** A/B (N=6 vs 4; stochastic first; **chest stress**) → **MV6** freeze
6. P2c / P3 / X* / H0 — по необходимости, не блокируют MV2–MV4

### Журнал (свежее)

| Дата | Что |
|------|-----|
| 2026-08-05 | **BLOCKER mid-prop holes:** мастер `midPropHolesGate.md`; MV2 paused; G1a fill no-op (236 boundary edges). |
| 2026-08-05 | **R1 research:** HF small-holes; нет per-asset presets; chest «проще глазу» ≠ проще T2; +P2c later. |
| 2026-08-05 | **P2b deploy:** `4c24928` → v15. Chest ultra→quality; `max_hole=0.1`; post-remesh; `model-chest-p2b-ultra.glb`. Preview dropdown + chest. |
| 2026-08-05 | **P2 A/B:** chest @ `quality` baseline vs hole 0.1; tier default → 0.1 + P2b в коде. |
| 2026-08-05 | **План:** тиры ≠ per-asset; P2 holes; единая таблица shape+prod+texture. |
| 2026-08-05 | **P1 deploy:** `d69687b` → v14. Chest ultra→quality ✅; front ok, holes/gaps → P2. Armor ultra full rt6 ✅. Recycle warm workers после template PATCH. |
| 2026-08-04 | **P1:** `quality_tier` preview/quality/ultra + OOM auto-downgrade (remesh=false → quality re-infer). Memory+techContext. Deploy pending. |
| 2026-08-04 | **Diag1:** rt6 + armor на `9f9ff96` ✅; OOM сундука ≠ регресс. |
| 2026-08-04 | MV1 smoke: lite ✅; rt6 chest CuMesh OOM. |
| 2026-08-03 | Research multi/synth/N; Meshy-паттерн; rt6 recipe closed. |

---

### (legacy ниже) Product front / squeeze — детали сессий

### Product front (best)

```text
1536 + remesh + 700k + steps50
+ guidance_interval [0,1]
+ rescale_t 6/6
→ …-gi01-rt6.glb
```
e800 = mixed (не default).

### Что ещё осталось на Trellis.2 (простыми словами)

| # | Что | Зачем | Статус |
|---|-----|--------|--------|
| **A** | **Multi-view вход** (перед+бок+спина) | Community PR #104 style: `image_urls[]` + `multi_image_mode` (multidiffusion/stochastic); monkeypatch в образе | 🟡 **код готов**, не задеплоено; **нет side/back фото** для A/B |
| **B** | Глаза **бока/спина** на rt6 | Preview Front/Side/Back; бок rt6 целый, орнамент soft | ✅ осмотр |
| **C** | Skip-simplify / 1M faces | Последний denser-extreme | 🟡 дорого, e800 уже mixed |
| **D** | Seeds best-of-N на rt6 | Другая «удача» орнамента | ⏸ later |
| **E** | ss guidance 9–12 / interval 0.3 | тонкая настройка | 🟡 низкий шанс |
| **F** | Post: meshlib / reconstruct (Comfy-стиль) | дыры после, не узор как на фото | R&D |
| **G** | Hi3DGen | уже не T2 | после закрытия A–F |

**Важно:** «сгенерировать от картинки со всех сторон» ≠ просто крутить knobs. Это **новый вход** `image_urls[]` + поддержка в `pipeline` (у нас сейчас только `image_url`). Для вау как Meshy часто делают **synth** multi-view внутри — у нас для текстур уже MV-Adapter; для **shape** multi-view ещё не проброшен.

**Что крутили:** только `rescale_t` ss/shape **→ 6** (было 5/3). Interval `[0,1]`, steps 50.

| | gi01 BEST | rt6 |
|--|-----------|-----|
| rescale_t ss/shape | 5 / 3 | **6 / 6** |
| verts/faces | 328k / 664k | 331k / 670k |
| infer_s | ~227 | ~228 |

Preview: `?file=model-armor-clay-sampler50-pro-gi01-rt6.glb`  
Дальше по очереди: denser **800k** на победителе (gi01 или rt6).

### Шаг 5 готов
`…-gi01-hole01.glb` = gi01 + `max_hole_perimeter=0.1`  
328k V / 664k F; infer ~227s (как gi01).  
Preview: `?file=model-armor-clay-sampler50-pro-gi01-hole01.glb`

### Чеклист squeeze — итог

| Шаг | Вердикт |
|-----|---------|
| 0 deploy 42d302c | ✅ |
| 1 `guidance_interval [0,1]` | ✅ **big++** → **BEST** |
| 2 steps 75 | ≈worse / unclear — не в recipe |
| 3 shape guid 10 | ≈same — не в recipe |
| 4 remesh_band 2 | ≈same good — не обязателен |
| 5 hole perimeter 0.1 | ⏳ глаза (метрики ≈ gi01) |

**Product front:** gi01 = 1536 + remesh + 700k + steps50 + interval `[0,1]`.

### Research: что ещё можно (не в чеклисте 0–5)

| Идея | Источник | Статус у нас | Приоритет |
|------|----------|--------------|-----------|
| **`shape rescale_t=6`** (ss тоже 6) | issue #92 max-q | у gi01 shape **3** / ss **5** — **не гоняли 6/6 на gi01** | 🟠 дешёвый A/B |
| **decim 800k–1M** на gi01 | README / #92 | был 700k; E700 без interval | 🟠 |
| **skip / слабый simplify** | #124 + CuMesh#28 | «без simplify = sharper, export slow» | 🟡 дорого по ETA |
| **ss guidance 9–12** | сторонние гайды | пробовали shape 10 ≈same | 🟡 низкий |
| **interval `[0.3,1]`** (ComfyUI) | visualbruno | у нас `[0,1]` уже big++ | 🟢 опц. mid |
| **MeshRefiner / reconstruct quad / meshlib holes** | ComfyUI Trellis2 | нет в worker | 🟠 R&D |
| **multi-view / лучше вход** | docs | single RGB; бока later | 🟠 product |
| **Hi3DGen / TripoSG** | наша матрица H | ⏸ | 🔴 next-tier shape |
| seeds best-of-N | community | отложено | ⏸ |

Самый честный «упустили внутри T2»: **`rescale_t=6` на shape** и **decim ≥800k поверх gi01**. Остальное — postprocess fork или другая модель.


**Шаг 4 вердикт:** также хорошо как gi01 → `remesh_band` не обязателен в recipe (default 1 ок).

**Best front по-прежнему:** `…-gi01.glb` — 1536 + remesh + 700k + steps50 + `guidance_interval [0,1]`.

**Осталось:**
| # | Что | Зачем |
|---|-----|--------|
| **5** | `max_hole_perimeter 0.1` (на gi01) | последний T2 knob; на gi01 дыр уже мало — шанс малый |
| — | Hi3DGen | другой shape, если хотим ещё micro сверх T2 |
| ⏸ | seeds / TripoSG / кроп | later / не сейчас |

s75 / sg10 / band2 → **не** в product recipe.

**Что крутили:** только `shape_slat guidance_strength` **8.5 → 10**; steps 50; interval `[0,1]`.

| | gi01 BEST | sg10 |
|--|-----------|------|
| shape guidance | 8.5 | **10** |
| verts/faces | 328k / 664k | 332k / 677k |
| infer_s | ~227 | ~230 |

Preview: `?file=model-armor-clay-sampler50-pro-gi01-sg10.glb`  
Критерий: резче/выразительнее gi01 или same/worse?

### Вердикт шаг 1 (только перед) — **big++**
шлем/нагрудник/пояс заметно лучше; дыр на поясе нет.  
→ `guidance_interval [0,1]` в **best recipe**.

### Шаг 2 артефакт
`model-armor-clay-sampler50-pro-gi01-s75.glb` = gi01 + steps **75**  
322k V / 652k F; infer **257s** (gi01 был 227s).  
Preview: `?file=model-armor-clay-sampler50-pro-gi01-s75.glb`  
Критерий: ещё резче gi01 или same/worse?

### Метрики front A/B (verts/faces + время)

`infer_s` = handler `inference_ms` (без cold load). `exec_s` = RunPod `executionTime` (load+infer+export).

| label | verts | faces | MB | infer_s | exec_s | load_s |
|-------|------:|------:|---:|--------:|-------:|-------:|
| Track A seed42 | 231023 | 471924 | 8.44 | — | — | — |
| D' 1024+50+500k | 244156 | 493766 | 8.86 | 128.8 | 277.4 | 142.3 |
| F@D' project0.5 | 243477 | 499060 | 8.91 | 130.1 | 286.5 | 151.2 |
| E 1024+700k | 339869 | 688554 | 12.34 | 130.5 | 275.1 | 140.3 |
| C@D' 1536+500k | 241729 | 485780 | 8.73 | 183.3 | 327.4 | 135.3 |
| **C+E best 1536+700k** | **332711** | **669158** | **12.02** | **182.8** | **334.4** | 142.0 |
| tokens 98k (=same) | 333159 | 669892 | 12.04 | 238.5 | 459.0 | 205.0 |
| G maxq no-remesh | 428607 | 767078 | 14.35 | 197.7 | 369.1 | 167.7 |
| G+F remesh+p0.9 | 384991 | 791890 | 14.12 | 185.0 | 341.6 | 147.6 |

Скрипт: `scripts/summarize_t2_front_metrics.py` (логи часто UTF-16 от PowerShell `*>`).

### Код (локально, ждёт шаг 0 deploy)

Файлы: `worker_trellis2.py`, `test_req_trellis2.py`, `scripts/summarize_t2_front_metrics.py`, preview dropdown.
- `guidance_interval` в sampler params (HF default `[0.6,1.0]`)
- steps max **100** (было 50)
- `remesh_band`, `max_hole_perimeter`, `remove_small_cc`
- ответ: `mesh_stats` {vertices, faces}; CLI печатает timing + local GLB counts

---

## Наработки front (золотой рыцарь) — 2026-08-03

### Scope глаз
Только **перед**. Бока/спина — позже.

### Best recipe (product candidate)

```text
image          = …/smoke/ref_gold_armor.png   # RGB, НЕ cutout
preprocess     = true
pipeline_type  = 1536_cascade
remesh         = true
remesh_project = 0
decimation     = 700000
ss/shape steps = 50, guidance ~8.0/8.5
seed           = 42
texture_mode   = clay
```

| Артефакт | Роль |
|----------|------|
| `model-armor-clay-sampler50-pro-1536-e700.glb` | **текущий best** — грудь/над поясом сильно лучше; табард всё ещё каша |
| `model-armor-clay-sampler50-pro-1536.glb` | 1536+500k — big+ front |
| `model-armor-clay-sampler50-pro-e700.glb` | 1024+700k — weak+ |
| `model-armor-clay-sampler50-pro42.glb` | D' 1024+500k — рост ок, без решета |
| `model-armor-clay-seed42.glb` | Track A baseline |

Preview: `?file=model-armor-clay-sampler50-pro-1536-e700.glb`

### Жёсткие выводы

| Факт | Следствие |
|------|-----------|
| Cutout + no-preprocess | **сплющивает** — не для quality A/B |
| no-remesh / max-q G | **дыры** — не front recipe |
| `remesh_project` | **no-op** для sharpness |
| 1536 + steps50 + remesh | главный **big+** |
| denser 700k | **weak+**; табард чувствителен |
| Табард на best | всё ещё **каша** → похоже на потолок T2 occupancy |
| Красить мыло / Meshy-mesh | **нет** |
| Seed roulette | **отложено** (2026-08-03) |

Подробности: `textureWowPlan.md` § **Корневая матрица T2** + § **Остаток методик**.

---

## Простыми словами (долгосрок)

Матрица front **пройдена**. Best = 1536+remesh+700k+steps50+RGB.  
Остаток = **табард**. Дальше таблица методик (tokens / Hi3DGen / …), не kitchen-sink и не seeds.

```
Front?
├─ cutout / no-remesh G  → squash / дыры ❌
├─ remesh_project / tokens98k → no-op ❌
├─ 1536+steps50+remesh+700k → ✅ best (табард каша)
└─ дальше → шаги 0–5 knobs → Hi3DGen
```

---

## Текущий фокус

| | Статус |
|--|--------|
| Матрица A–G front | ✅ |
| Best recipe | ✅ 1536+remesh+700k+steps50 |
| Метрики verts/time | ✅ таблица в activeContext |
| tokens 98k | ✅ same |
| Код interval/band/holes/steps100 | ✅ локально |
| Deploy нового образа | ⏸ **шаг 0** |
| A/B 1–5 | ⏸ после release |
| Seeds | ⏸ не сейчас |
| Hi3DGen | ⏸ после squeeze T2 |

---

## Очередь спринта

| # | Задача | Статус |
|---|--------|--------|
| Front матрица T2 | ✅ | |
| Метрики + knobs code | ✅ | |
| **Шаг 0** commit/push/CI/release | ⏸ | |
| Шаги 1–5 A/B | ⏸ | |
| Hi3DGen | ⏸ | |

**План:** чеклист шагов в шапке activeContext.

**MV-Adapter ops:** `workersMin=0` всегда. Не serverless marathon. Pod terminate после smoke.

**Warm clay `512` (2026-07-22, 5 jobs back-to-back):**

| | JOB1 (cold) | JOB2–5 warm avg |
|--|-------------|-----------------|
| wall | 812 с | **27.3 с** |
| model_load | 233 с | 0 с |
| handler | 319 с | 23.4 с |

Endpoint: `workersMin=0` (без always-on — дорого), `workersStandby=2`, `idleTimeout=60` (T2 + texture). Первый job после простоя — cold; подряд в окне idle — **~25–31 с**. Studio warm ETA: **35 с**.

**MV-Adapter ops:** `workersMin=0` всегда (тесты тоже — cold/throttled OK). Не поднимать min перед smoke. Heal только на zombie IN_QUEUE.
- Не heal’ить перед каждым submit (Studio + smoke) — только на zombie / stuck IN_QUEUE
- `idleTimeout=60` — `scripts/set_endpoint_idle.py --seconds 60 --apply`
- Ручной heal: `python scripts/heal_t2_endpoint.py`
- FlashBoot **off**, `workersMax≥2`
- Estimate `$0.17` на одном clay = cold + delay/zombie, **не** целевой COGS (warm ~$0.02–0.03)

Warm timing: `scripts/warm_timing_t2.py --no-zombie-watch --no-heal`.

## RunPod endpoints (карта)

| Роль | Имя | ID | Регион | Volume | Статус |
|------|-----|-----|--------|--------|--------|
| Primary (CZ) | mushy_fuchsia_shark | `splmm6w2rblqkp` | EU-CZ-1 | `paradox-models` | v1, образ **stale** |
| Secondary (RO) | nasty_tan_boa | `88djlbwtw4sjlv` | EU-RO-1 | `witty_blush_toucan` | v1 OK |
| Quality (T2) | paradox-trellis2_endpoint | `ynzpzjvcbfl656` | EU-RO-1 | `paradox-trellis2` (`netu72a8j2`) | **T2 + R2 OK** |
| **Texture v1** | TRELLIS_texturing | `a968zrhd6hmj7s` | EU-RO-1 | `paradox-trellis2` | **live**; image `texture-sha-c6fa8b5`; R2 env ✅ |
| **MV-Adapter** | paradox-mvadapter | `ggjypsxh0u1djj` | EU-RO-1 | `paradox-mvadapter-storage` (`dses29m9i5`, 40GB) | **workersMin=0**; v11+volume; Release #10 timeout без кэша → retry smoke |

**`.env`:** `RUNPOD_ENDPOINT_ID_TRELLIS2=ynzpzjvcbfl656`, `RUNPOD_ENDPOINT_ID_TEXTURE=a968zrhd6hmj7s`  
(локально также могут быть `RUNPOD_S3_*` для volume S3 — **не** путать с `R2_*`)

**Env на T2 / texture (обязательные для delivery):**
- `HF_TOKEN`, `TRELLIS2_DINOV3_PATH=/runpod-volume/dinov3-vitl16-pretrain-lvd1689m`
- `R2_ENDPOINT_URL`, `R2_BUCKET=ai-mesh-models`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`
- `R2_PUBLIC_BASE_URL=https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev`, `R2_REGION=auto`

**Volume T2 содержит:** `trellis2-weights/`, `dinov3-vitl16-pretrain-lvd1689m/`, `outputs/`, `huggingface_cache/`

**CI:** `build-trellis2.yml` → `:trellis2-*`; `build-texture.yml` → `:texture-*` (thin overlay); `build-mvadapter.yml` → `:mvadapter-latest` / `:mvadapter-sha-*`.  
**RunPod Flash** — не используем. **FlashBoot** — **off**.

**Texture smoke (2026-07-23):**
- FAIL #1: R2 mesh download 403 без User-Agent → фикс `c6fa8b5`
- OK infer #2: COMPLETED ~171 с / ~$0.065; `delivery=volume` (worker до R2 env) → GLB с volume S3 `model-tex.glb`
- Clay для теста: `trellis2/51f69412-180b-4e56-b470-acb248d14341-e1.glb`

**Заметка сеть:** прямой GET volume S3 иногда stall — для продукта нужен `model_url` (R2).

**Zombie queue:** 4-я причина `IN_QUEUE` — см. `systemPatterns.md` (idle/ready + EXITED ghost). Код: `runpod_queue_watchdog.py`, `scripts/heal_t2_endpoint.py`.

---

## Инциденты и корневые причины (хронология)

### 1. 48ч IN_QUEUE — битый digest (2026-07-10, RunPod Support)

**Не capacity.** Support (Hector Vallejos): обрезанный SHA-256 (**63** hex вместо 64) → pull падает → воркер мигает `Initializing` → jobs в `IN_QUEUE`.

Битый digest (не использовать):
```
sha256:2131ce5fa2429c77d79c882bbddd667d3df6debc41c3710e5c58108fc812c6d  ← 63 chars
```

**Фикс:** тег `:latest` или полный digest из GHCR, не из чата.

### 2. Inference `dmc_table` NameError (2026-07-10)

nv-tlabs FlexiCubes с `from tables import *` ломается как submodule TRELLIS.

**Фикс:** `cf84884` — MaxtirError/FlexiCubes @ `f97beb0` + kaolin cu118.

### 3. Тестовая картинка 404 (2026-07-10)

`fox.png` в `example_images/` — **404**. Рабочий URL: `example_image/T.png`.

**Фикс:** `0d59207` — `test_req.py` → `T.png`.

### 4. RO Unhealthy на RTX 5090 (2026-07-10, Release #6)

После добавления **AMPERE_48 / RTX 5090** воркеры `unhealthy=1`, job в `IN_QUEUE` бесконечно.  
На **RTX 4090** модель уже грузилась в VRAM; падение было только на fox 404.

**Причина:** CUDA 11.8 / torch 2.0.1 **несовместим с Blackwell (5090)** и 48GB tier.

### 5. CZ «не находит workers» — throttled (2026-07-10/13)

Live-тест: `throttled=1` ~60–90 сек, потом `ready=1` → `IN_PROGRESS`.  
В EU-CZ-1 tier **24GB = Unavailable** в UI — это **capacity**, не digest-баг. Выглядит как старый IN_QUEUE.

### 6. Job FAILED: `No module named 'nvdiffrast'` (2026-07-10)

Inference доходит до GLB export, но в образе не было nvdiffrast.

**Фикс:** `0d59207` + `609b201` — nvdiffrast в Dockerfile (EGL deps, `--no-build-isolation`, `TORCH_CUDA_ARCH_LIST`).

### 7. CI build fail на nvdiffrast (2026-07-13)

`EGL/egl.h: No such file or directory` при `pip install` без dev-пакетов.

**Фикс:** `609b201` — libegl1-mesa-dev и др. + `PYOPENGL_PLATFORM=egl`.

### 8. Job FAILED: `No module named 'diff_gaussian_rasterization'` (2026-07-13)

После nvdiffrast inference доходит до `to_glb` → `render_multiview` → `GaussianRenderer`, но в образе не было mip-splatting / diff-gaussian-rasterization.

**Фикс:** Dockerfile 6.8 — `git clone autonomousvision/mip-splatting` + `pip install .../submodules/diff-gaussian-rasterization/` (как `setup.sh --mipgaussian`).

### 9. Первый `COMPLETED` + сохранение GLB локально (2026-07-13)

Сгенерирован `COMPLETED` на RO (`88djlbwtw4sjlv`). GLB можно скачать без копирования base64 через скрипт:
`scripts/save_glb_from_status.py` → сохраняет `model.glb`.

### 10. Zombie IN_QUEUE + EXITED ghost (2026-07-16/17)

Health: `ready/idle>=1`, `inProgress=0`, job вечно `IN_QUEUE`. REST: worker `desiredStatus=EXITED` при `workersMax=1` + FlashBoot.  
**Фикс (клиент):** `runpod_queue_watchdog` — proactive DELETE ghosts, cancel/retry; `heal_t2_endpoint.py --purge`. Ops: FlashBoot off, max>=2.

---

## Сделано

- [x] RunPod Serverless worker с TRELLIS-image-large
- [x] Docker CUDA 11.8 + deps + FlexiCubes (MaxtirError) + kaolin + **nvdiffrast**
- [x] Кэш весов на network volume
- [x] `test_req.py`: async `/run` + polling + fallback CZ→RO + **T.png**
- [x] `scripts/watch_endpoint.py`
- [x] Support ticket → malformed digest
- [x] CZ Release #13: `RUNPOD_SOURCE_PATH` удалён
- [x] CI: version tags + manual `:stable` promote (`30d3565`)
- [x] Диагностика 5090 / throttled / nvdiffrast (live API + job poll)

---

## В работе (прямо сейчас)

- [x] **RunPod:** GPU list → только 4090/A5000/L4/3090 (PATCH API, v16/v12)
- [x] **RunPod:** `idleTimeout` → **10s** (было 180 CZ / 40 RO)
- [x] **Worker tuning:** `simplify=0.98`, `texture_size=2048`, `seed` в input
- [x] `scripts/cleanup_endpoints.py` — audit + `--apply`
- [ ] **New Release** на **CZ** (RO уже OK)
- [ ] Promote `:stable` v1 после стабильных тестов
- [x] **POC TRELLIS.2** — Docker/CI/endpoint/DINOv3 local/BiRefNet/volume+R2 delivery
- [x] Full `1024_cascade`/2048 COMPLETED + локальный `model-v2-full.glb` через R2
- [x] R2 `model_url` на T2 endpoint
- [x] Zombie watchdog + heal scripts (локально, ждать commit)
- [x] FlashBoot off / workersMax>=2 на T2
- [ ] Ротация R2 token
- [ ] A/B: сундук v1 vs TRELLIS.2; batch seeds для зада
- [ ] Commit+push watchdog + memory-bank

---

## Чеклист RunPod (актуальный)

### GPU types — на ОБОИХ endpoint'ах

**Убрать:**
- NVIDIA GeForce RTX 5090
- NVIDIA B300 MIG 34GB
- NVIDIA A40, NVIDIA RTX A6000 (48GB)
- Tier `ADA_32_PRO`, `AMPERE_48` в gpuIds

**Оставить (приоритет):**
- RTX 3090, RTX 4090, RTX A5000, L4
- PRO 6000 MIG 24GB (fallback, Low Supply в CZ)

Только **24GB Ampere/Ada** — образ собран под CUDA 11.8.

### Образ

```
ghcr.io/satanexist/paradox_worker:latest
```
или immutable `v2026-07-13-XX` после CI. **Без** обрезанного `@sha256:...`.

### Env на endpoint

- **Нет** `RUNPOD_SOURCE_PATH`
- Рекомендуется: `RUNPOD_INIT_TIMEOUT=900` (cold start ~15 GB весов)
- Model field: пусто

### CZ (`splmm6w2rblqkp`, v14)

1. Edit → GPU list (см. выше)
2. Image → свежий тег
3. Volume `paradox-models` → `/runpod-volume` — не трогать
4. Save → New Release → rollout 100%

### RO (`88djlbwtw4sjlv`, v6 — **ещё не обновлялся!**)

1. То же GPU list
2. Image → тот же тег что CZ
3. Volume `witty_blush_toucan` — не трогать
4. Save → New Release

### Проверка

```powershell
cd D:\AI_HUB\paradox_worker
$env:PYTHONUTF8=1
.\.venv\Scripts\python.exe scripts\watch_endpoint.py --once
.\.venv\Scripts\python.exe test_req.py
```

Ожидаем: `throttled` 1–2 мин (CZ) → `ready=1` → `IN_PROGRESS` → `COMPLETED`.

Тестовый URL картинки:
```
https://raw.githubusercontent.com/microsoft/TRELLIS/main/assets/example_image/T.png
```

---

## Блокеры

| Блокер | Статус |
|--------|--------|
| Битый digest | ✅ снят |
| FlexiCubes `dmc_table` | ✅ в образе |
| nvdiffrast / diff_gaussian | ✅ в образе v1 |
| **DINOv3 gated HF (RU)** | ✅ обход: Meta portal → `.pth` → HF-папка на volume |
| **RMBG-2.0 gated + CC BY-NC** | ✅ rembg → `ZhengPeng7/BiRefNet` (+ `einops`) |
| Huge GLB base64 → пустой `output` | ✅ delivery volume/R2 (`ad1bca9`) |
| Zombie EXITED ghost / FlashBoot | ✅ heal + FlashBoot off + max=2; ghosts всё ещё бывают → watchdog |
| Качество mesh v1 (creatures) | 🔄 A/B vs TRELLIS.2 |
| CZ v1 stale image | ⚠️ New Release |
| EU-CZ-1 capacity | ⚠️ `throttled` — терпимо |

### TRELLIS.2 — важные факты (2026-07-15/17)

1. **HF DINOv3 reject ≠ Meta reject.** Meta portal дал `.pth`; HF-репо остался closed. Worker грузит локальный путь.
2. **Нельзя** класть ~16 MB GLB в JSON RunPod status — job COMPLETED, `output` пустой. Писать на volume / R2.
3. **RMBG-2.0** — не для commercial AI_MESH без договора BRIA; BiRefNet — POC/open rembg (= вырез фона, не «зад»).
4. Smoke CI: не `import` CUDA-расширений на buildx (нет `libcuda`) — проверка `.so` + `trellis2` config.
5. Single-image: невидимая сторона — догадка модели; улучшение POC = seeds / фото; multi-view — позже.

---

## Заметки по RunPod (важное)

- **Четыре симптома «IN_QUEUE»:**
  1. Битый digest → `initializing` мигает и пропадает
  2. `throttled` → ждёт свободный GPU в регионе (capacity)
  3. `unhealthy` → воркер стартует и падает (5090, missing deps, crash)
  4. **Zombie** → `idle/ready` + `EXITED` ghost, job не dequeue
- `:latest` — dev/починка; **`:stable`** — прод
- Network volume не шарится между регионами
- REST API endpoint config: `https://rest.runpod.io/v1/endpoints/{id}`
- GraphQL: imageName, gpuIds, gpuTypeIds, version

---

## Журнал сессий

| Дата | Кто | Что сделано | Следующий шаг |
|------|-----|-------------|---------------|
| 2026-08-03 | Pedrokita | Front best+метрики; knobs code; чеклист шагов 0–5; tokens=same | Шаг 0 commit/push/release |
| 2026-08-03 | Pedrokita | Front матрица: best=1536+remesh+700k+steps50; табард каша; seeds⏸; memory обновлена | Таблица остатка → tokens98k или Hi3DGen |
| 2026-08-02 | Pedrokita | Долгосрок = корневая матрица осей; max-q = stress G; код sampler в push | Deploy → ось D sampler |
| 2026-07-31 | Pedrokita | xatlas path; decimate 80k; GHCR Pod smoke; preview + lights | quality after latency |
| 2026-07-08 | Pedrokita | Memory-bank, test_req async, worker traceback/xformers | RunPod тест |
| 2026-07-09 | Pedrokita | Multi-endpoint fallback, watch_endpoint, CZ Release #13, support ticket | Digest fix |
| 2026-07-10 | Pedrokita | Digest fix; FlexiCubes+kaolin; CI tags; 5090 unhealthy; throttled CZ; nvdiffrast missing | Rebuild, GPU list, retest |
| 2026-07-13 | Pedrokita | Commit+push nvdiffrast; CI EGL fix `609b201`; memory-bank update | CI green → RunPod release → COMPLETED |
| 2026-07-13 | Pedrokita | Dockerfile 6.8: diff_gaussian_rasterization (mip-splatting submodule) | push → CI → New Release → retest |
| 2026-07-14 | Pedrokita | RunPod PATCH cleanup (GPU+idle); worker tuning; retest FAILED stale image | CI → New Release → retest |
| 2026-07-14 | Pedrokita | RO retest OK (дракон, сундук, 3 seeds); CZ stale; POC TRELLIS.2 scaffold | CI trellis2 → quality endpoint → A/B |
| 2026-07-15/16 | Pedrokita | T2 endpoint+volume; DINOv3 Meta; BiRefNet; volume GLB delivery; full 1024_cascade OK | Download GLB; R2; A/B vs v1 |
| 2026-07-16 | Pedrokita | R2 bucket+env на T2; smoke `delivery:r2` + local download; volume S3 с ПК не тянет | Full quality + rotate R2 token; A/B |
| 2026-07-17 | Pedrokita | Zombie watchdog; heal ghost; full `08f458cc` R2; rembg≠зад notes | FlashBoot off; rotate R2; seeds; commit |
| 2026-07-20 | Pedrokita | warm 366s→40s; seeds 1/7/42; A/B v1 vs T2 Full; unit economics canvas; Studio defaults | Визуальный A/B; мост AI_MESH contract |
| 2026-07-20 | Pedrokita | Уточнили scope: сейчас только image→3D; обсудили варианты text→3D | Выбрать MVP-путь text→image→T2 |
| 2026-07-20 веч | Pedrokita | POLY_LAB live E2E (пистолет); proxy-glb CORS; watchdog в Studio; Meshy Workspace notes | Commit POLY_LAB; warm; library UX |
| 2026-07-22 | Pedrokita | Warm 5× clay: cold 812s wall, warm avg 27.3s; ETA Studio 35s | Best-of-N отложен |
| 2026-07-23 | Pedrokita | Push recipes + warm script; seed UX clarified (same model only) | Upload hints / Library |
| 2026-07-23 | Pedrokita | Upload quality hints (`imageQuality.ts`) in Studio | Library UX |
| 2026-07-23 | Pedrokita | Image Enhancement toggle (`imageEnhance.ts`) — 2D preprocess | Library UX |
| 2026-07-23 | Pedrokita | Library UX: All/Clay/Tex/Фото/Текст filters + badges | Auth + credits mock |
| 2026-07-23 | Pedrokita | Credits mock + demo auth; job charges 4/12 cr | Clerk or Texture фаза 2 |
| 2026-07-23 | Pedrokita | Texture v0: Studio action=texture → legacy bake | Mesh paint worker (T1) |
| 2026-07-23 | Pedrokita | T1a scaffold: `worker_texture.py`, Dockerfile.texture, test_req_texture | T1b: build+endpoint+smoke |
| 2026-07-23 | Pedrokita | Thin texture Dockerfile + `build-texture.yml` → GHCR | Ждать CI; создать RunPod endpoint |
| 2026-07-24 | Pedrokita | Баланс OK → Pod `zhdeac3dd4otww` A6000; zip `mvadapter_w2_upload.zip` | Upload + bootstrap smoke |
| 2026-07-28 | Pedrokita | W2 smoke green: `knight_i2tex_shaded.glb`; A/B лучше cascade; дыры+мыло → W2b plan | W2b mesh repair + preprocess_mesh |
| 2026-07-29 | Pedrokita | Endpoint `ggjypsxh0u1djj` deployed; smoke fail spandrel→cv2; CI fixes pushed | New Release + smoke retry |
| 2026-07-24 | Pedrokita | W2 GO: MV-Adapter Apache-2.0; spike.md + Dockerfile.mvadapter | Pod smoke рыцарь |
| 2026-07-23 | Pedrokita | Texture endpoint `a968zrhd6hmj7s`; UA fix; infer smoke OK; warm ops idle=60 / no pre-heal | R2 retest smoke; Studio T1c |

---

## Недавние решения

| Дата | Что | Заметки |
|------|-----|---------|
| 2026-08-02 | **T2 A/B FAIL на HF** | no-remesh/1536 denser ≈ Meshy polycount; орнамент всё ещё каша → потолок T2 micro, не только export |
| 2026-08-01 | **Сначала чинили T2 export** | Проверили; не хватило |
| 2026-07-31 | **Мыльный меш → не красить; E2 нет** | Unit economics |
| 2026-07-28 | **W2 smoke partial pass** | Tex лучше cascade; дыры = mesh T2 + UV gaps; мыло = JPEG + нет PBR |
| 2026-07-24 | **Meshy рыцарь = эталон** (1 photo): меш+зад+tex | Наш cascade mid; вау через новый stack |
| 2026-07-24 | **Meshy вау с 1 фото** — не user multi-view | Разрыв = их synth MV + models; наш cascade проигрывает |
| 2026-07-24 | **Вау-first по текстурам** | Paint v1 frozen; T1c off; план `textureWowPlan.md`; цель 1 img → synth MV → bake |
| 2026-07-23 | **Texture v1 = отдельный endpoint/образ** (не мультитаск на T2) | Endpoint `a968zrhd6hmj7s`; image `texture-sha-c6fa8b5`; volume тот же `paradox-trellis2`. v0 bake = Studio fallback |
| 2026-07-23 | Warm без `workersMin` | idleTimeout=60; не heal перед submit; always-on слишком дорого для POC |
| 2026-07-22 | Clay-first: `texture_mode=clay|textured` в worker; Studio default clay; T2-friendly polish | Release `6d763fa` + smoke OK |
| 2026-07-22 | Industry Quality Recipes в Studio (presets → polish/T2I/decimation) | Warm economics |
| 2026-07-20 | Unit economics: self-host 2–4× дешевле API; не клон Meshy; warm = ключ к марже | canvas + platformRoadmap § measured |
| 2026-07-20 | Text→3D: в текущем worker отсутствует; MVP-вариант = text→image→T2 | отдельный text2mesh endpoint — позже |
| 2026-07-20 | Studio tiers: preview=`512`/1024, quality=`1024_cascade`/2048 | ETA cold/warm в UX |
| 2026-07-20 веч | POLY_LAB live + zombie watchdog (client); Release не нужен; wall≠cold | meshyWorkspace.md |
| 2026-07-20 | Warm T2 `512`: load 0 → wall ~40 с (vs cold ~6 мин) | Studio ETA: cold vs warm честно |
| 2026-07-17 | rembg (BiRefNet) ≠ додумывание зада; зад = модель + seed/multi-view later | UX: не ждать «плагин спины» в POC |
| 2026-07-17 | Watchdog: proactive DELETE EXITED ghosts + heal после zombie | клиент/Studio, не GPU handler |
| 2026-07-17 | Zombie queue watchdog (idle/ready + IN_QUEUE) | `runpod_queue_watchdog` + heal script |
| 2026-07-16 | T2 delivery: volume + **R2 `model_url`** (prod path) | bucket `ai-mesh-models`; pub-c826…r2.dev |
| 2026-07-16 | Full quality T2: volume path, не base64 | `ad1bca9`; base64 только мелкие |
| 2026-07-16 | rembg = BiRefNet, не RMBG-2.0 | gated + NC |
| 2026-07-15 | DINOv3 с Meta CDN → convert → volume | HF geo-reject из РФ |
| 2026-07-13 | **platformRoadmap.md** — 4 фичи AI_MESH | Сессия стратегии |
| 2026-07-13 | Core = self-host, не SaaS API | Unit economics |
| 2026-07-14 | POC TRELLIS.2: отдельный Docker/worker/CI | Параллельно v1 |
| 2026-07-13 | TRELLIS.2 next; Hunyuan off EU prod | MIT + license |
| 2026-07-13 | nvdiffrast: EGL deps + `--no-build-isolation` + `TORCH_CUDA_ARCH_LIST` | Официальный рецепт NVlabs для Docker |
| 2026-07-13 | Smoke test image → `T.png` | fox.png 404 |
| 2026-07-10 | Не использовать 5090/B300 с CUDA 11.8 | Только 24GB Ampere/Ada |
| 2026-07-10 | CI tags + manual `:stable` | `30d3565` |
| 2026-07-10 | MaxtirError FlexiCubes + kaolin | `cf84884` |
| 2026-07-10 | `:latest` вместо битого digest | Support |
| 2026-07-10 | Не RunPod Flash | Кастомный Docker |
| 2026-07-09 | CZ Release #13: убрать `RUNPOD_SOURCE_PATH` | |
| 2026-07-08 | Multi-endpoint fallback | `test_req.py` |

---

## Быстрый тест

**v1 (RO):**
```powershell
cd D:\AI_HUB\paradox_worker
$env:PYTHONUTF8=1
.\.venv\Scripts\python.exe test_req.py
```

**TRELLIS.2 (clay / textured):**
```powershell
cd D:\AI_HUB\paradox_worker
$env:PYTHONUTF8=1
.\.venv\Scripts\python.exe test_req_trellis2.py --pipeline-type 512 --texture-mode clay --save model-clay.glb
# legacy bake:
.\.venv\Scripts\python.exe test_req_trellis2.py --pipeline-type 512 --texture-mode textured --texture-size 1024 --save model-tex.glb
```
```powershell
.\.venv\Scripts\python.exe test_req_trellis2.py --pipeline-type 1024_cascade --texture-size 2048 --save model-v2-full.glb
# ожидание: delivery=r2, model_url=https://pub-….r2.dev/trellis2/<job>.glb
# viewer: python -m http.server 8765 → /scripts/view_model.html?model=/model-v2-full.glb
# heal: .\scripts\heal_t2_endpoint.py --purge
```

Ожидаем T2: `"status": "COMPLETED"` + `delivery: "r2"` + `model_url`.
