# TRELLIS.2 finish — prod master

> **Статус:** 🟡 **ACTIVE** — shape front/props ✅; side/back mid accepted; дальше P1 UX + P2 tex (`postSideBackPlan.md`); Hi3DGen = P4  
> **Создан:** 2026-08-10 (Pedrokita)  
> **Решение:** synth MV→T2 🔴 NO-GO; **не** бросаем T2 — freeze prod + tex + optional multi UX; Meshy-back с 1 фото ≠ T2 knobs  
> **Связь:** `postSideBackPlan.md`, `textureWowPlan.md`, `midPropHolesGate.md`, `synthMultiViewProd.md`, `productMultiUx.md`

---

## 1. Цель одной фразой

**1 фото → T2** — максимум качества в рамках MIT warm path: props **GO**, character **best-effort** (front сильный; бок/зад честно mid vs Meshy).

**Не цель:** догнать Meshy на орнаменте **только knobs** — матрица front уже закрыта; дожим = prod + side/back pass + tex.

---

## 2. Что уже закрыто (не повторять)

| Тема | Статус | Артефакт / вывод |
|------|--------|------------------|
| Front knobs A–G | ✅ | best ≈ **gi01-rt6** (`1536+steps50+remesh+700k+guidance_interval [0,1]`) |
| tokens 98k | ✅ | no-op |
| remesh_project 0.5/0.9 | ✅ | no-op sharpness |
| no-remesh max-q | ✅ | дыры — не recipe |
| cutout no-preprocess | ✅ | сплющило |
| Mid-prop holes | ✅ | `soft_input` v16, chest GO |
| Synth U3D/W3D → T2 | 🔴 NO-GO | `synthMultiViewProd.md` Gate E |
| MV4b multi | 🔴 | хуже single (quality baseline) |

---

## 3. Prod recipe (freeze)

| Tier | Когда | Shape | Input |
|------|-------|-------|-------|
| **preview** | demo / ETA | 512 clay | 1 photo |
| **quality** | default props | 1024 clay + hole0.1 | 1 photo ± **soft_input** |
| **ultra** | character / best-effort | **1536** rt6 recipe | 1 photo RGB + preprocess |

**Ultra = rt6** в коде: `quality_tier=ultra` → steps50, gi01 interval, 700k decim, remesh on.

**Character path:** рекомендовать **ultra**; при OOM → auto-downgrade quality (уже в worker).

**Props path:** **quality** + `softInput` в Studio bridge.

---

## 4. Очередь дожима (релевантный порядок)

### T0 — Prod verify (без новых GPU экспериментов)

| # | Задача | Выход |
|---|--------|-------|
| T0.1 | Endpoint image = `trellis2-sha-*` с ultra/rt6 + soft_input | echo `generation.*` в smoke |
| T0.2 | Smoke: chest **quality+soft**, armor **ultra** s42 | 2 GLB на R2 |
| T0.3 | Compare viewer: gi01-rt6 локальный vs fresh ultra job | same recipe? |
| T0.4 | Док: tier → ожидания в `techContext.md` | UX copy для Studio |

### T1 — Side / Back pass (новая ось, не front)

> Front исчерпан. Критерий: **Side + Back** на `ref_gold_armor`, baseline = **ultra gi01-rt6** (не quality).

| # | Ось | Гипотеза | 1 job each |
|---|-----|----------|------------|
| T1.1 | `remesh_band` 2 vs 1 | меньше сглаживания боков | `--remesh-band 2` @ ultra |
| T1.2 | `remesh_project` 0.3 / 0.7 | проекция HF на бок | `--remesh-project` @ ultra |
| T1.3 | `decimation_target` 800k–1M | плотнее vs Meshy verts | @ ultra |
| T1.4 | `soft_input` на character? | вряд ли орнамент; optional | eyes only |

**Gate T1:** ✅ **CLOSED** 2026-08-10 (Pedrokita): band2 / proj0.7 / e800 = **identical** к Armor ultra; Side/Back mid/weak без прироста. Ось knobs для бока/зада **закрыта**; T2 shape ceiling = **ultra rt6** (front strong, side/back best-effort).

### T2 — Остаток knobs (если T0 deploy отставал)

Из `textureWowPlan.md` § остаток — только если **не** в prod image:

| # | Knob | Статус |
|---|------|--------|
| T2.1 | steps 75 / guidance 10 @ ultra | A/B если не гоняли на rt6 |
| T2.2 | hole perimeter / band (шаги 4–5) | на armor ultra |
| T2.3 | best-of-N seeds 1,7,42 @ **ultra** | дешёвый lottery орнамента |

### T3 — Texture (parallel, shape не меняет)

| # | Задача |
|---|--------|
| T3.1 | MV-Adapter W2b на **gi01-rt6** clay (`ref_gold_armor`) |
| T3.2 | A/B: cascade tex vs MV-Adapter vs Meshy ref |
| T3.3 | Serverless mvadapter polish (holes highlight, not fix) |

### T4 — T2-family optional (после T0–T1)

| # | Задача | Зачем |
|---|--------|-------|
| T4.1 | **ReconViaGen** integration | MASTER `reconViaGenMvRefiner.md`; D2 smoke → D4 worker |
| T4.2 | User multi 2–4 фото → T2 naive | bridge ✅; prod only **real** photos; RVG tier separate |
| T4.3 | (opt.) adaptive fusion patch in `trellis2_multi_image.py` | после pod A/B |
| T4.3 | P2c Meshlib hole fill | если props/regression после T1 |

### T5 — Product freeze

| # | Задача |
|---|--------|
| T5.1 | Studio: 1 upload, tier preview/quality/ultra, soft toggle props |
| T5.2 | Badge «quality reduced» on downgrade |
| T5.3 | **Recipe freeze doc** — «1-photo T2 bar» vs Meshy (честно) |

---

## 5. Явно **не** T2 finish (другие треки)

| | |
|--|--|
| Hi3DGen / TripoSG | после **T0–T1 + T5** closed |
| Synth MV worker wrap | 🔴 cancelled |
| Hunyuan / Era3D prod | ❌ |
| Per-asset SKU presets | ❌ |

---

## 6. Gates

### Gate T-FINISH — «T2 track closed»

| # | Критерий | GO |
|---|----------|-----|
| F1 | Prod ultra = rt6 live + smoke | ✅ |
| F2 | T1 side/back pass | ✅ **CLOSED** 2026-08-10 — all same; ceiling = ultra rt6 |
| F3 | Texture W2b на best clay | ≥ cascade; eyes |
| F4 | Props chest soft v16 | уже ✅ |
| F5 | Product tier UX | Studio or bridge complete |

**После F1–F5:** можно открывать **H0 Hi3DGen** для character back/side без чувства «бросили T2».

---

## 7. Команды (шпаргалка)

```powershell
# Ultra rt6 armor (best single)
python test_req_trellis2.py --quality-tier ultra --texture-mode clay --seed 42 `
  --image-url "https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/ref_gold_armor.png" `
  --save preview_textures/t2_armor_ultra_s42.glb

# Chest props
python test_req_trellis2.py --quality-tier quality --texture-mode clay --soft-input `
  --image-url "https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/ref_chest.png" `
  --save preview_textures/t2_chest_soft.glb

# T1 example: remesh_band 2
python test_req_trellis2.py --quality-tier ultra --texture-mode clay --seed 42 `
  --remesh-band 2 --image-url "…/ref_gold_armor.png" --save preview_textures/t2_armor_ultra_band2.glb
```

**Viewer:** `scripts/preview_mv4b_compare.html` или `preview_glb_local.html?file=…`

**Локальный best reference:** `model-armor-clay-sampler50-pro-gi01-rt6.glb`

---

## 8. Decision log

| Дата | Решение |
|------|---------|
| 2026-08-10 | Pedrokita: **дожимать T2**, Hi3DGen после finish track |
| 2026-08-10 | Synth→T2 NO-GO; focus = ultra prod + T1 side/back + tex |
| 2026-08-10 | **T0 smoke ✅** armor ultra s42 (336k V, rt6 echo); chest soft ref_chest s42 (244k V, soft_input) |
| | R2: `smoke/ref_chest.png` uploaded; job `4e4e60e7-…` |
| 2026-08-10 | **T1.1** remesh_band=2 @ ultra s42 ✅ `aebbb1d8-…` 332k V (~$0.13) |
| 2026-08-10 | **T1.2** remesh_project=0.7 @ ultra s42 ✅ `72f147ba-…` 351k V (~$0.06) |
| 2026-08-10 | **T1.3** decim 800k @ ultra s42 ✅ `a47c6d3a-…` 396k V (~$0.05) |
| 2026-08-10 | **Eyes T1.3:** Pedrokita — e800 vs Armor ultra = **same** |
| 2026-08-10 | **Gate T1 CLOSED:** band2 / proj0.7 / e800 = **identical** к Armor ultra; Side/Back слабо как раньше |
| | **Вывод:** remesh/decim knobs **не** чинят бок/зад; shape ceiling = ultra rt6 front |
| 2026-08-10 | **Unblock matrix** → `sideBackUnblock.md`; B soft-NO-GO; C1 abort |
| 2026-08-10 | Side/Back с 1 фото на T2 = потолок; roadmap → `postSideBackPlan.md` |
| | **Next:** P1 UX / P2 tex / P3 freeze; P4 Hi3DGen later |

---

## 9. Статус одной строкой

```
Synth MV→T2:  🔴 closed
Side/Back 1p: mid accepted (not Meshy)
T2 finish:    P1 UX → P2 tex → P3 freeze → P4 Hi3DGen (postSideBackPlan.md)
```
