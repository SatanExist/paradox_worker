# D-track MASTER — ReconViaGen + умный multi fusion

> **Статус:** 🟢 **HOT** — HF eyes GO-ish (Pedrokita «ОГО»); интеграция = отдельный shape engine  
> **Обновлено:** 2026-08-11 (Pedrokita)  
> **Мастер этой задачи:** **этот файл** (`reconViaGenMvRefiner.md`)  
> **Связь:** `postSideBackPlan.md` P4.0, `t2FinishPlan.md` T4.1, `multiViewFusionResearch.md`, `productMultiUx.md`, `sideBackUnblock.md` (D)

---

## 0. Одной фразой

**Naive T2 multi (average/stochastic) — закрыт.**  
**ReconViaGen** — первый кандидат с **умным fusion** (+ VGGT); глаза на HF подтвердили.  
**Prod:** не чинить `image_urls` в текущем worker, а **второй endpoint** (или позже patch fusion в T2 как R&D).

---

## 1. Проблема (простым языком)

### 1 фото → наш T2 ultra

- Модель **видит** только то, что на картинке (обычно front).
- Бок/зад — **догадка**, не «игнор».
- Front ok — это **норма** режима 1-photo.

### N фото → **наш** T2 multi

- Виды **не игнорируются**, но fusion **тупой** (`trellis2_multi_image.py`):

```python
pred = sum(preds) / len(preds)   # multidiffusion
# stochastic = по очереди один вид на шаг
```

- При **согласных** реальных фото — иногда лучше single.
- При **конфликте** (Gemini: меч в руке vs на поясе) — **smear всего меша**, даже front.
- Итог на Gemini/U3D: 🔴 soft-NO-GO (4v + pair F+B).

### Что такое «умное влияние» (ReconViaGen)

- **Не** front перерисовывает JPEG back.
- На каждом шаге 3D для **каждой точки/токена** решают: **какому виду верить больше**.
- Default: **`adaptive_guidance_weight`** — вес ~ ‖v_cond − v_uncond‖; early steps ровнее, late — острее.
- Плюс **Stage 1 VGGT** — sparse structure из multi, не только SLat fusion.

---

## 2. Что НЕ делаем (зафиксировано)

| Идея | Вердикт |
|------|---------|
| Synth views (Gemini/U3D) → **наш** T2 `image_urls` | 🔴 closed |
| «ReconViaGen рисует виды → летят в наш T2» | ❌ не его API; T2 уже внутри RVG |
| Ждать PR #104 confidence fusion в stock T2 | ⏸ upstream WIP |
| ComfyUI Nano Banana → naive Trellis tutorials | шум, не proof |
| Wonder3D++ pod без бюджета/deps | ❌ C1 abort |

---

## 3. Что ReconViaGen v0.5 (технически)

| | |
|--|--|
| Repo | https://github.com/GAP-LAB-CUHK-SZ/ReconViaGen **branch `v0.5`** |
| Paper | arXiv:2510.23306 (ICLR 2026) |
| HF UI | https://stable-x-reconviagen-v0-5.hf.space/ |
| HF API | https://stable-x-reconviagen-v0-5.hf.space/?view=api |
| License | MIT (repo) + условия весов **TRELLIS.2** |

### Пайплайн

```
RGBA views (1–N)
  → Stage1  ReconViaGen / VGGT     → sparse coords 32³
  → Stage2  T2 Shape SLat         → multi fusion (adaptive_guidance_weight)
  → Stage3  T2 Texture SLat       → PBR
  → GLB
```

### Fusion strategies (6; default `adaptive_guidance_weight`)

| Strategy | Суть |
|----------|------|
| `sequential` | ≈ наш stochastic |
| `average` / `average_right` | average / PoE-style CFG |
| `weighted_average` | вес ~ согласие с консенсусом velocity |
| **`adaptive_guidance_weight`** | вес ~ уверенность вида; **prod default** |
| `fixed_guidance_rescale` | per-view rescale + PoE |

---

## 4. Доказательства (наши прогоны)

| Прогон | Результат |
|--------|-----------|
| T2 ultra single (Armor) | ✅ front baseline `t0_armor_ultra_s42.glb` |
| T2 multi Gemini 4v | 🔴 мыло + debris |
| T2 multi Gemini F+B pair | 🔴 мыло + **2 меча** + front smear |
| **HF ReconViaGen** (Pedrokita eyes) | 🟢 **«ОГО»** — sharp side/back, 1 меч, PBR |

**Артефакты:**

| | Path |
|--|------|
| Eyes screens | `preview_textures/reconviagen/r_eyes_side.png`, `r_eyes_back_ui.png` |
| Naive pair GLB | `preview_textures/a_pair_front_back_ultra_stoch_s42.glb` |
| HF GLB (TODO) | `preview_textures/reconviagen/r_hf_*.glb` via smoke script |

---

## 5. Три пути интеграции «умного алгоритма»

| # | Путь | Сложность | Ожидание | Рекомендация |
|---|------|-----------|----------|--------------|
| **1** | **ReconViaGen как отдельный RunPod handler** | средняя | близко к HF «ого» | **prod v1** |
| **2** | Patch `adaptive_guidance_weight` в `trellis2_multi_image.py` | средняя R&D | лучше naive на **real** multi; без VGGT — не полный RVG | spike **после** pod A/B |
| **3** | Полный порт v0.5 в monolith worker | высокая | = (1), дольше | ❌ не первым |

### Путь 1 — prod architecture (target)

```
Studio
  ├─ tier "preview/quality"     → worker_trellis2 (1 photo, fast)
  └─ tier "multi_shape" / RVG   → worker_reconviagen (1–4 photos, slow, PBR)

bridge: shapeEngine: trellis2 | reconviagen
        или отдельный endpoint_id
```

- **Не** заменяет T2 ultra для 1-photo default.
- **Не** вшивать в один handler без причины.

### Путь 2 — fusion-only patch (optional R&D)

Файл: `studio_bridge/trellis2_multi_image.py`  
Добавить mode `adaptive_guidance_weight` (взвешенная сумма preds по ‖v_cond−v_uncond‖).  
A/B: те же front+back vs текущий stochastic/multidiffusion.

---

## 6. Продукт (как стыкуется)

| Режим | Движок | Когда |
|-------|--------|-------|
| Default | T2 ultra 1 photo | быстро, front ok, зад — догадка |
| Real multi 2–4 | T2 stochastic **или** ReconViaGen tier | real photos + UX `productMultiUx.md` |
| «Лучший бок/зад» | **ReconViaGen** | optional paid/slow tier |
| Synth → naive T2 | — | **не продукт** |

**MultiView Refiner** (cuzelac) — **вторичный** track: refine **готового** ultra mesh + views; Comfy/visualbruno; не serverless из коробки.

---

## 7. HF API + smoke

| | |
|--|--|
| OpenAPI | https://stable-x-reconviagen-v0-5.hf.space/gradio_api/openapi.json |
| Schema | https://stable-x-reconviagen-v0-5.hf.space/gradio_api/info |
| Script | `scripts/reconviagen_hf_smoke.py` |

**Два вызова, одна `session_hash`:**

1. `/image_to_3d` — gallery, strategy, pipeline, stage sliders  
2. `/extract_glb` — decimation, texture_size → download GLB  

**Spike defaults:**

| Param | Value |
|-------|-------|
| `multi_image_strategy` | `adaptive_guidance_weight` |
| `pipeline_type` | `1024_cascade` (или `1536_cascade`) |
| `ss_source` | `mesh` |
| `seed` | 42 |
| `decimation_target` | 700000 |

```powershell
python scripts/reconviagen_hf_smoke.py `
  --image preview_textures\gemini_mv\front.png `
  --image preview_textures\gemini_mv\back.png `
  --seed 42 --decimation 700000 `
  --save preview_textures\reconviagen\r_hf_armor_fb.glb
```

**HF limits:** ZeroGPU queue 5–15+ min; steps урезаны vs local; prod → свой pod.

---

## 8. MultiView Refiner (secondary)

| | |
|--|--|
| Repo | https://github.com/cuzelac/ComfyUI-Trellis2-MultiViewRefiner |
| PR | visualbruno/ComfyUI-Trellis2#125 |
| Input | existing mesh + front/back/left/right |
| Fusion | **spatial blend** (`blend_temperature`, `front_axis`) |

Spike M0: Armor ultra clay + F+B refine (Comfy pod).  
Prod idea: `1 foto → ultra` → optional refine если юзер дал Side/Back.

---

## 9. Roadmap (D-track)

| Phase | Задача | Статус |
|-------|--------|--------|
| D0 | Research + Comfy noise filter | ✅ |
| D1 | HF eyes (Pedrokita ОГО) | ✅ |
| D2 | GLB via HF smoke (API) | 🔴 HF queue/timeout — skip for prod |
| D3 | Pod spike `v0.5` / oneshot F+B | 🔴 **ABORT** 2026-08-11 — deps hell (ToS/torch/sudo/hub/o-voxel/triton); pod terminated |
| D4 | **`Dockerfile.reconviagen`** + handler + CI | 🟡 **IN PROGRESS** — scaffold готов; CI build = gate |
| D4.1 | CI `build-reconviagen.yml` green | ⏳ **NEXT** после push |
| D4.2 | Pod smoke на image: Armor F+B vs T2 ultra / naive multi | ⏳ после CI |
| D4.3 | Endpoint + `RUNPOD_ENDPOINT_ID_RECONVIAGEN` + bridge tier | ⏳ после GO smoke |
| D5 | (opt.) fusion patch в `trellis2_multi_image.py` | ⏸ после A/B |
| D6 | (opt.) MV Refiner Comfy spike | ⏸ |

**Stop rule:** 2× same/worse vs Armor ultra → soft-NO-GO метод.

### D4 — перспективный план (зафиксирован 2026-08-12)

| Шаг | Действие | Gate |
|-----|----------|------|
| 1 | Commit scaffold + push → CI | build green |
| 2 | Чинить только падающие layers (flash-attn, kaolin, …) | build green |
| 3 | Pod smoke **на готовом image** (не setup.sh) | GLB ≈ HF eyes |
| 4 | Отдельный RunPod endpoint + bridge `multi_shape` | E2E job OK |
| 5 | Studio P1 слоты → tier выбирает endpoint | UX честность |

**Параллельно (не блокирует D4):** P1 Studio UX (`productMultiUx.md`); P2 texture W2 на best clay после стабильного shape.

**Не делать:** monolith RVG в `Dockerfile.trellis2`; HF Space API в prod; голый pod + `setup.sh`.

---

## 10. Сравнительная таблица (все методы)

| Метод | Вход | Fusion / core | Статус |
|-------|------|---------------|--------|
| T2 single ultra | 1 img | single cond | ✅ prod clay |
| T2 naive multi | N img | stoch / equal avg | 🔴 Gemini |
| Synth → T2 | synth | naive | 🔴 |
| **ReconViaGen v0.5** | 1–N img | VGGT + adaptive | 🟢 eyes hot |
| MV Refiner | mesh + N img | spatial blend | 🟡 secondary |
| Hi3DGen / TripoSG | 1 img | other engine | ⏸ P4.1 |

---

## 11. Decision log

| Дата | Решение |
|------|---------|
| 2026-08-10 | Naive T2 multi + synth paths 🔴; Comfy SEO = noise |
| 2026-08-10 | ReconViaGen + MV Refiner = D-track candidates |
| 2026-08-11 | HF eyes: Pedrokita «ОГО» — sharp side/back, 1 sword |
| 2026-08-11 | **Не** chain synth→RVG→наш T2; RVG = цельный GLB |
| 2026-08-11 | **Prod path:** отдельный ReconViaGen endpoint; fusion-only patch = optional R&D |
| 2026-08-11 | HF API smoke timeout ×3 — D2 skip; **D3 pod** = next (own GPU) |
| 2026-08-11 | **D3 ABORT:** pod terminated; Франкенштейн env (torch↔o_voxel↔flex_gemm/triton). Eyes HF всё ещё GO. |
| 2026-08-11 | **Правило:** тяжёлые GPU-стеки — **сразу Dockerfile + image**, не голый pod + setup.sh |
| 2026-08-12 | **D4 план:** CI build = gate; smoke на image; отдельный endpoint; P1 UX параллельно; D5 fusion patch только после A/B |
| | **Next:** push scaffold → CI green → pod smoke F+B Armor |

---

## 12. Статус одной строкой

```
D-track: D4 scaffold ready. Next = CI build → pod smoke on image → endpoint. P1 UX parallel.
```
