# Synth Multi-View → Shape — prod master

> **Статус:** 🔴 **FROZEN 2026-08-13** — класс MIT img2mv→T2 **исчерпан** (данные + интернет-срез). Не «недоделанный spike».  
> **Создан:** 2026-08-10 (Pedrokita + Cursor)  
> **Проблема:** 1 фото → слабые **бок/зад** vs Meshy; UX = **одна** картинка  
> **Связь:** `postSideBackPlan.md` (куда дальше), `textureWowPlan.md`, `reconViaGenMvRefiner.md` (fusion ≠ img2mv), spikes W3D/U3D

---

## 1. Проблема одной фразой

**Пользователь грузит 1 фото.** Meshy/Rodin на `ref_gold_armor` дают читаемый **зад и бок** с орнаментом.  
**T2 single** — сильный **перед**, бок/зад «плывут».

**Гипотеза 2026-08-10 (закрыта):** prod-ответ = внутренний synth multi-view (как Meshy), не просьба снять 6 ракурсов.  
**Факт 2026-08-13:** в OSS под EU self-host **нет** Meshy-класса img2mv. Meshy прячет свой согласованный synth/native 3D. Наш MIT путь этот слой не клонирует. Честный 1-фото потолок = T2 ultra; лучший зад = **реальные** фото или **другой native shape** (P4.1).

---

## 2. UX (не обсуждается)

| | |
|--|--|
| **Default** | 1 upload → T2 (clay или textured) |
| **Optional** | 2–4 **реальных** фото → слоты Studio (`productMultiUx.md`) |
| **Не делаем** | скрытый synth 4–6 views → T2 (класс frozen) |
| **Не prod** | обязательный «снимите side/back»; AI-sheet как вход |

---

## 3. Как делают конкуренты (снаружи)

| Продукт | UX | Технология (известное / заявленное) |
|---------|-----|-------------------------------------|
| **Meshy** | 1 фото | Закрытый stack; паттерн ≈ synth MV + strong shape + tex |
| **Tripo** | 1 фото | Свои модели (TripoSR → …); research lineage, closed prod |
| **Rodin / Hyper3D** | 1 фото | **Native 3D diffusion** (tri-plane), не «6 JPEG → reconstruct» |
| **InstantMesh (OSS)** | 1 фото | Zero123++ views → reconstruct (веса MV часто NC) |

**Вывод 2026-08-13:** рынок продаёт 1 фото. Внутри у лидеров — закрытый synth **или** native 3D. Наш self-host EU **не** клонирует этот слой MIT img2mv. InstantMesh-паттерн отравлен NC-весами.

---

## 4. Целевая prod-архитектура

```
                    ┌─────────────────────────────────────┐
  User: 1 photo ──► │  Studio / API (mode=image, tier=…)   │
                    └──────────────┬──────────────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │ shape_tier=standard    │ shape_tier=multi_synth  │  (later: shape_tier=native)
          ▼                        ▼
   T2 single + soft          Synth MV engine
   (props, fast)            (Unique3D / W3D++ / …)
          │                        │
          │                   4–6 RGB URLs
          │                        ▼
          │                   T2 image_urls[]
          │                   fusion: stochastic | multidiffusion
          │                        │
          └────────────┬───────────┘
                       ▼
                 clay GLB (+ optional MV-Adapter tex)
                       ▼
                      R2 → viewer
```

| Слой | Worker / образ | Статус |
|------|----------------|--------|
| T2 single + `soft_input` | `worker_trellis2.py` | ✅ prod |
| T2 multi fusion | `studio_bridge/trellis2_multi_image.py` + worker | ✅ код; synth path не замкнут |
| Synth MV (shape) | pod spike / future sidecar | 🟡 views only |
| Texture | `worker_mvadapter.py` | 🟡 W2 smoke; не Meshy wow |
| Router «1 photo → engine» | нет | ⏸ после gate |

**COGS (оценка spike):** synth MV ~+$0.05–0.15 + T2 multi ~×1.2–1.8 VRAM/time vs single на 4090.

---

## 5. Инвентарь: что уже пробовали

### 5.1 Сделано

| ID | Что | Артеfact | Вердict views | **Views → T2 → GLB?** |
|----|-----|----------|---------------|------------------------|
| MV1 | T2 `image_urls` + fusion API | `worker_trellis2.py` | infra OK | — |
| MV2 | Wonder3D v1 MIT | `preview_textures/mv2_*` | soft-NO-GO (blob side/back) | ❌ |
| MV2b raw | Unique3D img2mv | `preview_textures/u3d_*` | слабо | ❌ |
| MV2b HQ | Unique3D + Tile + ESRGAN | `preview_textures/u3d_*_hq` | NO-GO Gate A | ❌ Gate B skip |
| W2 | MV-Adapter texture | `knight_*_shaded.glb` | tex ↑ vs cascade | ❌ shape path |
| P0 | Bridge `imageUrls` | studio smoke | API OK | ⚠️ 2 разных объекта |
| G2 | soft_input holes | chest v16 | ✅ props | — |

### 5.2 Остаток трека — **отменён** (2026-08-13)

MV4b уже дал Gate E на GLB (U3D→T2 хуже single). Повтор W3D-blob→T2 / MV7 wrap / MV8 tier **не открывать**.

| ID | Вердикт |
|----|---------|
| MV4 / MV4b | ✅ сделано; 🔴 NO-GO |
| MV4c / MV5 | ❌ skip — views слабее U3D, fusion тот же |
| MV6 ig2mv→T2 | ❌ skip — `ig2mv` нужен **готовый меш** (это texture, не shape). `i2mv` без меша = тот же класс Unique3D; опц. 30с глаз на HF, не GPU-трек |
| W3D++ / Era3D | ❌ AGPL, не prod |
| ReconViaGen × T2 | ❌ не img2mv; см. `reconViaGenMvRefiner.md` |
| MV7 / MV8 | ❌ cancelled — нечего оборачивать в worker |

Опциональный ритуал (не план): HF Space [MV-Adapter I2MV SDXL](https://huggingface.co/spaces/VAST-AI/MV-Adapter-I2MV-SDXL) на `ref_gold_armor`. Если бок/лев каша — дыру «свой адаптер не пробовали» закрыть без pod. Если вдруг 3D-consistent — тогда RVG, не naive T2. **Не ждать этого, чтобы двигаться.**

---

## 6. Матрица лицензий (EU self-host)

| Кандидат | Лицензия | Prod AI_MESH |
|----------|----------|--------------|
| Wonder3D v1 | MIT | spike done; 🔴 views |
| Wonder3D++ | **AGPL** (HF) | ❌ |
| Unique3D | MIT | spike done; 🔴 Gate E |
| MV-Adapter | Apache-2.0 | ✅ **texture** (`ig2mv`/`i2tex`); не shape |
| TRELLIS.2 | MIT | ✅ |
| Era3D | AGPL | ❌ prod; offline eyes only |
| Zero123++ weights | NC | ❌ |
| Hunyuan3D 2.1 / 2mv | Community License **не EU/UK/KR** | ❌ |
| Hunyuan 2.5 / 3.x | hosted, весов нет | ❌ |
| Zero123++ / InstantMesh MV | веса **CC-BY-NC** | ❌ |
| SV3D / SPAR3D | Stability Community **$1M cap** | ⚠ не core |
| Hi3DGen / TripoSG / Direct3D-S2 | MIT | **P4.1** native 3D (не img2mv) |
| Step1X-3D | Apache-2.0 | P4.1 candidate |
| MV-Adapter **i2mv** | Apache + SDXL Community | не spike shape; см. §5.2 ритуал |

---

## 7. Gates (freeze)

### Gate V — качество synth views (глаза)

На `ref_gold_armor` + chest:

| # | Критерий | GO | NO-GO |
|---|----------|----|-------|
| V1 | Front ≈ input (identity) | ✅ | другой объект |
| V2 | Side silhouette читается | плечо/меч не blob | плавленый blob (W3D-class) |
| V3 | Back не flat noise | объём, симметрия ± | random cutout |

**Не блокирует MV4**, если V2/V3 слабые — всё равно гоняем end-to-end.

### Gate E — end-to-end (обязательный перед prod)

Baseline: `model-armor-clay-sampler50-pro-gi01-rt6.glb` (single T2).

| # | Критерий | GO | SOFT-GO | NO-GO |
|---|----------|----|---------|-------|
| E1 | Job COMPLETED quality clay | GLB | — | fail |
| E2 | **Back** лучше single (глаза) | читаемее пластины/пояс | ≈ single | хуже |
| E3 | **Side** орнамент лучше single | чётче | ≈ | хуже |
| E4 | Front не деградировал | ≥ single | — | хуже |
| E5 | Chest multi: дыр ≤ single+soft | — | — | больше дыр |

**Итог Gate E:**

| Verdict | Действие |
|---------|----------|
| **GO** | MV7 worker wrap → beta tier |
| **SOFT-GO** | R&D only; default остаётся T2 single; optional flag |
| **NO-GO** | synth→T2 closed **с данными**; ускорить Plan B (Hi3DGen) |

### Gate P — prod

| # | Критерий |
|---|----------|
| P1 | p95 latency + COGS в budget tier |
| P2 | Fallback: synth fail → T2 single (не 500) |
| P3 | `generation.synth_engine` + `fusion_mode` в echo для ops |
| P4 | Не обещать Meshy 1:1 в маркетинге до E=GO |

---

## 8. План реализации (релевантный порядок)

### Фаза 0 — закрыть дыру ✅ **DONE** (MV4b 2026-08-10)

| Step | Действие | Выход |
|------|----------|-------|
| **0.1** | Upload `u3d_armor_hq/armor_rgb_*.png` (+ опц. chest) на R2 | public URLs |
| **0.2** | `test_req_trellis2.py --image-urls … --quality-tier quality --texture-mode clay` ×2 modes | 2 GLB |
| **0.3** | 0.2 с `--multi-image-mode stochastic` и `multidiffusion` | compare |
| **0.4** | Повтор 0.2–0.3 на `mv2_armor/armor_rgb_*.png` (W3D) | data point |
| **0.5** | Eyes: Front/Side/Back vs rt6 single; запись в § Decision log | **Gate E verdict** |

### MV4b results (2026-08-10)

| Variant | Job | GLB | Verts | Infer | $ |
|---------|-----|-----|-------|-------|---|
| **single** (ref_gold_armor) | `5d3a50f0-…` | [R2](https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/trellis2/5d3a50f0-4a93-46d5-804d-dc523ad0a065-e2.glb) | 241k | 16s warm | ~0.025 |
| **U3D→stochastic** | `95658a89-…` | [R2](https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/trellis2/95658a89-89ca-43fd-8738-16a401735121-e2.glb) | 234k | 106s cold | ~0.112 |
| **U3D→multidiffusion** | `dc1eb48a-…` | [R2](https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/trellis2/dc1eb48a-8d86-426c-bc5d-008a9383cebc-e1.glb) | 237k | 45s warm | ~0.034 |

View URLs: `smoke/mv4b/u3d_armor_rgb_00..03.png` on R2.

**Viewer (local):**
```text
http://127.0.0.1:8765/scripts/preview_glb_local.html?file=preview_textures/mv4b_armor_single_q.glb
http://127.0.0.1:8765/scripts/preview_glb_local.html?file=preview_textures/mv4b_armor_u3d_stoch.glb
http://127.0.0.1:8765/scripts/preview_glb_local.html?file=preview_textures/mv4b_armor_u3d_multid.glb
```

**Preliminary (auto ortho, not final Gate E):** back/side ≈ между собой; явного выигрыша multi над single на рыцаре **не видно** в quick render → скорее **SOFT-NO-GO / ≈ single** до глаз в Three.js.

**Gate E глаза 2026-08-10 (Pedrokita, `preview_mv4b_compare.html`):**

| Variant | Front | Side/Back | vs ожидание |
|---------|-------|-----------|-------------|
| U3D → stoch / multid | мыло | мыло | **хуже** — «ужасающее мыло» |
| Single quality s42 | узнаваемый рыцарь | слабые бок/зад | **не best** — мыльные детали; baseline = `quality`, не **ultra gi01-rt6** |

**Вывод:** даже с заведомо слабым single, multi **не спасает** — скорее ломает. Synth U3D→T2 **NO-GO** для prod. MV4b **не доказал** «multi лучше single на best rt6» — но глаза уже против synth path.

**Честный baseline для будущих A/B:** `model-armor-clay-sampler50-pro-gi01-rt6.glb` (ultra), не `quality` tier.

python scripts/upload_r2_asset.py preview_textures/u3d_armor_hq/armor_rgb_00.png --key smoke/u3d_armor_rgb_00.png
# … все 4–6 views

python test_req_trellis2.py --quality-tier quality --texture-mode clay `
  --image-urls <url0> <url1> <url2> <url3> `
  --multi-image-mode stochastic --save model-armor-u3d-multi-stoch.glb

python test_req_trellis2.py ... --multi-image-mode multidiffusion --save model-armor-u3d-multi-multid.glb
```

### Фазы 1–3 (MV7 wrap / product tier) — ❌ **cancelled 2026-08-13**

Gate E = NO-GO. Не выбирать synth engine, не делать worker wrap, не делать Studio `multi_synth`.

### Фаза 1 — выбор synth engine (если E ≠ NO-GO) — архив

| Step | Действие |
|------|----------|
| 1.1 | Таблица: U3D HQ vs W3D vs single на armor **и** chest |
| 1.2 | Spike **MV-Adapter ig2mv** → RGB views → T2 (mesh-hint) |
| 1.3 | Offline eyes: Wonder3D++ / Era3D views **без prod** |
| 1.4 | Freeze `synth_engine_default` (likely Unique3D HQ или winner) |

### Фаза 2 — worker wrap (MV7)

| Step | Действие |
|------|----------|
| 2.1 | Sidecar script или pod step: `1 image → synth views → temp R2 URLs` |
| 2.2 | `worker_trellis2.py`: input flag `synth_multi_view: true` → internal `image_urls` |
| 2.3 | Echo: `generation.synth_engine`, `generation.fusion_mode`, `generation.view_count` |
| 2.4 | Smoke на endpoint; cold/warm timings |

**Не monolith:** synth MV тяжёлый → отдельный образ или sequential job на том же pod (как W2 pattern).

### Фаза 3 — product (MV8)

| Step | Действие |
|------|----------|
| 3.1 | Tier или flag: `shapeMode: standard | multi_synth` (default **multi_synth** если E=GO) |
| 3.2 | Studio: всё ещё **1 upload**; router на backend |
| 3.3 | Badge/downgrade если synth fail → single |
| 3.4 | Character vs prop routing (опц.): props → single fast |

### Фаза 4 — Plan B native 3D (живёт в P4.1, не в этом файле)

Gate E = NO-GO на MIT synth→T2. Это **не** img2mv:

| Step | Действие |
|------|----------|
| B1 | Hi3DGen spike — 1 photo native (отдельный worker) |
| B2 | TripoSG spike |
| B3 | Router: character hard → native engine; props → T2+soft |

Детали Plan B → отдельный spike doc (после MV4 verdict).

---

## 9. Что **не** смешивать

| Тема | Где живёт |
|------|-----------|
| Mid-prop holes | `midPropHolesGate.md` ✅ closed |
| Texture wow / MV-Adapter paint | `textureWowPlan.md` |
| User multi-upload (2–4 real photos) | Studio bridge P0; **бонус**, не synth |
| T2 knobs / rt6 / ultra | закрыто для орнамента |
| Hunyuan / Era3D prod | ❌ |

---

## 10. Риски

| Risk | Mitigation |
|------|------------|
| Synth views OK, T2 fusion ломает пропорции | multidiffusion A/B; community PR #104 warnings |
| 256² views → потеря HF | HQ upscale path (U3D full); или 512 engine |
| Latency 2× | tier pricing; props stay single |
| «MV4 fail» ≠ «1-photo dead» | Plan B native 3D |
| Забытый pod | terminate same session |

---

## 11. Арtefacts & scripts

| | |
|--|--|
| Views W3D | `preview_textures/mv2_armor/`, `mv2_chest/` |
| Views U3D | `preview_textures/u3d_*`, `u3d_*_hq/` |
| Spikes | `scripts/wonder3d_mv2_*.sh`, `unique3d_mv2b_*.sh`, `unique3d_mv_infer.py` |
| Multi worker | `worker_trellis2.py`, `studio_bridge/trellis2_multi_image.py` |
| Upload | `scripts/upload_r2_asset.py` |
| Test | `test_req_trellis2.py --image-urls` |
| MV4b GLBs | `preview_textures/mv4b_armor_*.glb`, `mv4b_*_{front,side,back}.png` |

---

## 12. Decision log

| Дата | Решение |
|------|---------|
| 2026-08-07 | MV2 W3D views generated; soft-NO-GO на силуэты; MV4 не сделан |
| 2026-08-10 | MV2b U3D HQ Gate A NO-GO; **Gate B пропущен** — ошибка процесса |
| 2026-08-10 | **MV4b done:** U3D HQ 4v → T2 quality clay s42; single + stoch + multid GLB |
| 2026-08-10 | **Gate E глаза:** multi = «ужасающее мыло»; single quality ≠ best (мыльные детали) |
| 2026-08-10 | **Verdict:** synth U3D→T2 **NO-GO** prod; baseline MV4b = quality (не ultra gi01-rt6) |
| 2026-08-10 | Gemini→T2 soft-NO-GO; C1 W3D++ abort; research → `multiViewFusionResearch.md` |
| 2026-08-13 | **Класс img2mv FROZEN.** Интернет-срез: коммерчески чистого Meshy-класса img2mv в OSS нет. MIT (W3D/U3D) прогнан. Лучшие виды = NC/AGPL/EU-ban/Stability cap. RVG ≠ img2mv. Единственная дыра `i2mv` = ритуал HF, не GPU-трек. **Next:** P1 UX + P2 tex; 1-photo back = P4.1 native 3D; RVG только на реальные фото. |

---

## 13. Краткий статус для activeContext

```
Synth / img2mv: 🔴 FROZEN 2026-08-13 (класс исчерпан, не «ещё spike»)
Default UX:     1 photo → T2 ultra; copy честный
Real multi:     слоты Studio → RVG (fusion), не synth
1-photo Meshy:  не этот стек; P4.1 Hi3DGen/TripoSG если снова лезть в shape
```

---

## 14. Freeze 2026-08-13 — интернет-срез img2mv

**Meshy не строит зад из одного вида.** UX = 1 фото; внутри — Generate Multi-view (дорисовка side/back) **или** нативный 3D-prior. Это другой слой, чем T2 knobs и чем ReconViaGen.

Два слоя нельзя склеивать:

| Слой | Что делает | Meshy | Мы |
|------|------------|-------|-----|
| **img2mv** | Из 1 фото **дорисовать** side/back | Свой согласованный генератор | W3D/U3D/Gemini — слабо или конфликт |
| **fusion** | Склеить уже готовые виды | Свой reconstructor | Naive T2 smear; RVG = умный fusion |
| **native 3D** | Сразу объём, без JPEG-ракурсов | Возможно часть стека | T2 ultra; P4.1 Hi3DGen/TripoSG |

HF «ОГО» на ReconViaGen было на **нескольких** картинках. 1-photo RVG (`r_d42_1p_armor.glb`) львов на спине не дал — так и должно быть.

### Что в сети (2026)

**Прогнанное MIT (данные наши):** Wonder3D v1 blob; Unique3D Gate A + MV4b хуже single; Gemini 2D ок / 3D конфликт (2 меча).

**Лицензионная стена:** Zero123++ NC; InstantMesh через NC; Era3D AGPL; Wonder3D++ AGPL на HF; Hunyuan Community **не EU**; SPAR3D/SV3D Stability $1M; Hunyuan 3.x без весов.

**Рынок ушёл в native 3D** (Hunyuan-DiT, TripoSG, Direct3D-S2, Hi3DGen, TRELLIS) — img2mv это паттерн 2023–24.

**Единственная коммерчески чистая дыра:** MV-Adapter `i2mv` (без меша). Ожидание = Unique3D-класс. Не открывать GPU-трек.

**Вывод одной фразой:** подвешенность была ложной. Класс закрыт. Вау с 1 фото дальше искать в **текстуре (P2)** и **другом shape engine (P4.1)**, не в новом img2mv.
