# Side / Back unblock — карта после тупика T2

> **Статус:** 🟡 **ACTIVE** 2026-08-10 — C1 abort; B soft-NO-GO; research fusion → `multiViewFusionResearch.md`  
> **Контекст:** 1-photo T2 front OK; Side/Back mid; MIT img2mv→T2 🔴; remesh knobs identical  
> **Связь:** `t2FinishPlan.md`, `synthMultiViewProd.md`, `multiViewFusionResearch.md`, spikes W3D/U3D

---

## 0. Уточнение ( Pedrokita 2026-08-10 )

T2 **provenance-blind**: Gemini / user photo / Unique3D = одни и те же `image_urls`.  
Провал B/MV4b = **несогласованная или слабая серия × naive fusion**, не магический флаг «синтетика».  
Детали и ссылки: **`multiViewFusionResearch.md`**.

---

## 1. Диагноз одной фразой

Тупик не в «synth невозможен», а в **исчерпанном стеке**: слабый MIT img2mv + naive T2 multidiffusion. Remesh/decim **не** меняют придуманный зад (один seed → одна форма).

---

## 2. Что закрыто (не повторять)

| Путь | Вердикт | Почему |
|------|---------|--------|
| Front knobs (rt6) | ✅ потолок front | матрица A–G |
| T1 remesh_band / project / e800 | ✅ **identical** к ultra | постпроцесс ≠ новая геометрия |
| Wonder3D v1 → views → (план T2) | soft-NO-GO | силуэты тают |
| Unique3D HQ → T2 (MV4b) | 🔴 NO-GO | multi **хуже** single |
| «Ещё denser / soft на рыцаре» | ❌ skip | ROI≈0 |

**Community echo:** T2 issues/PR#104 — multi нужен для unseen; naive average → deformation; плохие views портят; MR-lab: «views I supplied are the issue». Papers (MV-SAM3D): naive TRELLIS multi-diffusion lags; bad views can beat good ones.

---

## 3. Матрица разблокировки (пробовать по очереди)

| ID | Метод | Суть | Шанс Side/Back | Prod? | Статус |
|----|-------|------|----------------|-------|--------|
| **A** | Product honesty | 1foto=T2 ultra; real multi optional | высокий *если* есть фото | ✅ цель UX | 🟢 **spec** `productMultiUx.md` |
| **B** | Strong 2D sheet → T2 | Gemini/Flux turnaround → crop → `imageUrls` | средний | ⚠ API/лицензия | 🔴 **soft-NO-GO** eyes |
| **C1** | Wonder3D++ **end-to-end** GLB | свой mesh, **не** →T2 | средний (цельность) | ⚠ **AGPL-3.0** | ❌ **ABORT** deps hell 2026-08-10 |
| **C2** | Hi3DGen / TripoSG | другой shape engine | средний–высокий | отдельный стек | ⏸ после/parallel B |
| **D** | Better fusion | **ReconViaGen** adaptive (+ optional MV Refiner) | высокий на HF eyes | R&D→prod | 🟢 **MASTER** `reconViaGenMvRefiner.md` |

### B — детали (Gemini proof 2026-08-10)

Gemini Flash дал **отличный** 2×2 sheet рыцаря (front/rear/left/right): согласованный стиль, читаемый зад.  
Это **2D**, не 3D: выдуманный лев на спине; меч спереди в руке / сбоку у бедра — риск конфликта для T2.

**Spike:** crop 4 панелей → R2 → T2 multi (stochastic + multidiffusion) vs **Armor ultra** single.  
Артефакт листа: `assets/…image-f6afda69….png` / `preview_textures/gemini_mv/`.

### C1 — Wonder3D++ (не путать с v1→T2)

++ = multi RGB+normals → **cascaded mesh**. Конкурент T2 на Side/Back цельность; front-орнамент может проиграть ultra.  
**Не** кормить views в T2. Один GLB A/B глазами. License: проверить branch `Wonder3D_Plus` перед prod (в `activeContext` раньше помечали ❌ для EU prod — уточнить).

### C2 — Hi3DGen

Отдельный image→3D. Главный next-tier для character back/side после/рядом с B. Не «флаг T2».

---

## 4. Порядок прогонов ( Pedrokita: «попробуем все» )

```
1) B  Gemini→T2          ✅ soft-NO-GO eyes
2) C1 W3D++ E2E          ❌ ABORT deps/AGPL
3) C2 Hi3DGen            ⏸ next shape
4) A  honesty UX + real-photo multi checklist  🟢 spec `productMultiUx.md`
5) D  confidence fusion  ⏸ only after good views
```

Критерий каждого: Side/Back **better / same / worse** vs `t0_armor_ultra_s42.glb`.  
Два подряд **same/worse** на одном методе → метод закрыт.

---

## 5. Decision log

| Дата | Решение |
|------|---------|
| 2026-08-10 | Gate T1 closed; remesh identical |
| 2026-08-10 | Synth U3D→T2 NO-GO; community agrees naive multi+bad views |
| 2026-08-10 | Gemini sheet = proof strong **2D** multi; путь **B** открыт |
| 2026-08-10 | Pedrokita: занести в память + **пробовать все** методы A–C |
| 2026-08-10 | **B** crops → R2 `smoke/gemini_mv/{front,back,left,right}.png` |
| 2026-08-10 | **B multid** ultra s42 ✅ `ea6e981c-…` 343k V num_images=4 (~$0.15) → `b_gemini_ultra_multid_s42.glb` |
| 2026-08-10 | **B stoch** ultra s42 ✅ `051992b1-…` 344k V (~$0.07) → `b_gemini_ultra_stoch_s42.glb` |
| 2026-08-10 | **Eyes B (Pedrokita):** зад *попытался*, **узоры мыло** + debris → **soft-NO-GO** |
| 2026-08-10 | **C1 ABORT** `e2fgdvjkek98bs` — deps hell; terminate; no GLB |
| 2026-08-10 | **Research** `multiViewFusionResearch.md`: provenance-blind; consistency×fusion; Meshy/MV-SAM3D/PR104 |
| 2026-08-10 | **A UX locked** → `productMultiUx.md` (Front+Side+Back+Extra; stochastic; AI sheet не режим) |
| 2026-08-10 | **Roadmap** → `postSideBackPlan.md` (P1 UX → P2 tex → P3 freeze → P4 Hi3DGen) |
| 2026-08-10 | **A pair smoke:** front+back → ultra stoch s42 `f63ea879-…` → `a_pair_front_back_ultra_stoch_s42.glb` (~$0.12) |
| 2026-08-10 | **Eyes pair F+B (Pedrokita):** бок/зад пытаются; **весь меш мыло** (front smear); **2 меча** (рука+пояс) → soft-NO-GO |
| | **Next:** P1 Studio / P2 tex; не Gemini→T2 |

---

## 6. Статус одной строкой

```
Dead: MIT img2mv→T2 + remesh + B Gemini4 + pair F+B Gemini + C1
A:    productMultiUx.md ✅; Gemini multi soft-NO-GO (даже 2 вида)
Plan: postSideBackPlan.md — P1 → P2 → P3 → P4
Open: C2 Hi3DGen | F3 tex | F5 freeze
```
