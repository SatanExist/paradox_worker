# Mid-prop holes gate — мастер-файл проблемы

> **Статус:** 🔴 **BLOCKER** — не возвращаемся к MV2 / основному плану, пока gate не зелёный.  
> **Создан:** 2026-08-05 (Pedrokita)  
> **Связь:** `activeContext.md` § G0–G3; research R1; P2 CuMesh уже недостаточен.

---

## 1. Проблема одной фразой

На **негабаритных mid-prop** (компактный объект: сундук и аналоги) TRELLIS.2 даёт **явные сквозные дыры / щели**.  
Конкурентные 3D генераторы на таком классе обычно **не** оставляют дыр «в лоб».  
Это **fail продукта**, не «особенность сложного ассета» и не повод заводить preset «сундук vs рыцарь».

**Repro (не цель SKU):** `typical_misc_monster_chest` / `model-chest-p2b-ultra.glb`  
**Контраст:** рыцарь (thick silhouette) часто без таких дыр; mid-prop с cracks/spikes/joints — да.

---

## 2. Что говорят официальные источники

### HF `microsoft/TRELLIS.2-4B` — Known Limitations

> *Geometric Artifacts (Small Holes): … raw meshes may occasionally contain small holes or minor topological discontinuities. For applications requiring strictly watertight geometry … hole-filling algorithms.*

- Дыры — **признанная limitation**
- Watertight **не** обещан из коробки
- Рекомендация Microsoft: **postprocess hole-fill**, не per-asset quality presets

### Project / O-Voxel

- Явно поддерживают *open surfaces, non-manifold, enclosed interiors*
- Открытая/рваная топология ближе к **дизайну представления**, чем к багу одного входа

### Tutorial `to_glb` / `o_voxel/postprocess.py`

| Ветка | Поведение |
|-------|-----------|
| `remesh=False` | simplify → repair → `fill_holes(≈0.03)` ×2 |
| `remesh=True` | `fill_holes` **до** remesh → Dual Contouring → simplify; **после remesh fill в апстриме нет** |

Дефолт CuMesh: `max_hole_perimeter ≈ 3e-2`.  
**Нет** tutorial «preset по уровню моделирования / props».

### Наш worker (уже сделано, недостаточно)

| Шаг | Что | Итог |
|-----|-----|------|
| P2 | tier `quality` hole `0.1` | слабо против явных дыр |
| P2b | post-remesh CuMesh fill + repair | лучше, **не** SaaS-bar |
| trimesh local repair | `model-chest-p2b-repaired.glb` | всё ещё `watertight=False` |

---

## 3. Форумы / issues (community consensus)

| Источник | Вывод |
|----------|--------|
| [#25](https://github.com/microsoft/TRELLIS.2/issues/25) | remesh → inner shells; `remesh=False` → грязный меш; tradeoff |
| [#105](https://github.com/microsoft/TRELLIS.2/issues/105) | без remesh → holes / broken geo |
| [#21](https://github.com/microsoft/TRELLIS.2/issues/21) | remesh ↔ double shell vs face flips |
| [#140](https://github.com/microsoft/TRELLIS.2/issues/140) | дыры сваривают inner/outer; нужен **visibility-based** cleanup |
| Pixal3D [#18](https://github.com/TencentARC/Pixal3D/issues/18) | тот же o-voxel: thin shell + micro leaks; manifold ≠ default |
| Comfy Trellis2 | после remesh → **FillHoles Meshlib** (жёстче CuMesh) |

**Consensus:** системный класс артефактов O-Voxel + remesh; чинят **внешним repair**, не официальным «prop preset».

---

## 4. Product gate (наш bar)

| | |
|--|--|
| **G0 pass** | На mid-prop repro **нет явных сквозных дыр** при осмотре front/side (как ожидают от SaaS) |
| **G0 fail** | Видны щели на полосах / стыках / «плоских» досках / замке «в лоб» |
| **Не цель G0** | Идеальный watertight для 3D-печати; Meshy-орнамент на character |
| **Не решение** | 20 SKU-пресетов; бесконечные T2 knobs без post-repair |

---

## 5. План решения (только это → потом основной план)

```
🔴 BLOCKER
   G0  определить gate + repro artifacts          ✅ (этот файл)
   G1  жёсткий post: pymeshlab / Meshlib close    ⚠ G1c optional
   G1a trimesh fill_holes                        ✅ DONE — **no-op** (см. §5.1)
   G1b voxel solidify (marching cubes)           ❌ REJECTED aesthetic (Minecraft)
   G1d soft-input A/B (plank grooves)            ✅ GO chest
   G1e intentional lattice                       ✅ industry limit (Meshy too)
   G2  soft_input in worker_trellis2               ✅ code (deploy pending)
   G3  smoke + глаза GO/NO-GO                    ⏸ after deploy
   G4  visibility inner-shell (#140) / Meshlib   ⏸ if soft+MV2 insufficient
   MV2 Wonder3D 1→6 views → T2 multi             ⏭ after G3
        ↓
🟢 gate green → resume основной план (MV2→… if not already done)
```

### 5.2 Decision matrix (2026-08-07) — все возможности

| # | Опция | Pros | Cons | Вердикт |
|---|--------|------|------|---------|
| A | CuMesh hole knobs | уже live | не закрывает see-through | ❌ done |
| B | trimesh/pymeshlab fill | $0 | no-op на chest | ❌ done |
| C | **voxel solidify** | watertight | **pixel clay** | ❌ **NO-GO aesthetic** |
| D | **soft-input** (залить борозды PNG) | дёшево; проверяет гипотезу «дыры = shading» | не product UX; не чинит зад | ✅ **GO 2026-08-07** → productize as preprocess |
| E | remesh=false A/B | меньше inner-shell (#25) | грязный mesh | ⏸ if D weak |
| F | **MV2 Wonder3D → T2 multi** | Meshy-like; бока/зад | ~$1–2 spike | ⏭ после D |
| G | Meshlib / G4 visibility | smooth clay possible | R&D | ⏸ last resort |
| H | per-asset presets | — | anti-policy | ❌ never |

**Prod path (если D помогает частично):** soft-norm optional + **MV2** + (если нужно) Meshlib/G4 — **не** voxel.
### 5.1 Ключевой факт G1a (2026-08-05)

На `model-chest-p2b-ultra.glb`:

| Метрика | Значение |
|---------|----------|
| Verts / faces | ~237k / ~475k |
| `watertight` | False |
| **boundary_edges** | **только ~236** |
| `trimesh.repair.fill_holes` ×N | **0 faces добавлено** (no-op) |

**Вывод:** явные «дыры» глазами — **не** классические open boundary loops, которые закрывает CuMesh/`fill_holes`.  
Скорее: thin see-through gaps, inner-shell peek (#25/#140), или щели без простого perimeter-loop.  
Поэтому **ещё больший `max_hole_perimeter` / trimesh fill не решит gate**. Нужен другой класс фикса: **voxel solidify / Meshlib / visibility cleanup**.

| # | Задача | Артефакт / критерий |
|---|--------|---------------------|
| **G0** | Мастер-файл + memory blocker | этот файл; `activeContext` |
| **G1a** | trimesh fill на P2b | no-op ✅ documented |
| **G1b** | `scripts/repair_glb_voxel_solidify.py` | `model-chest-p2b-voxel*.glb`; глаза |
| **G1c** | Meshlib/pymeshlab на Linux/pod (если G1b мылит деталь) | optional |
| **G2** | Worker: выбранный post после clay | новый sha |
| **G3** | Endpoint smoke + глаза | GO/NO-GO |
| **G4** | Visibility inner-shell (#140) | if needed |

**Отложено до 🟢:** MV2 Wonder3D, MV3–MV6, P3 Studio, X*, H0.

---

## 6. Артефакты repro

| Файл | Роль |
|------|------|
| `model-chest-p2b-ultra.glb` | baseline после P2b (CuMesh) |
| `preview_textures/model-chest-p2b-voxel128.glb` | G1b voxel128 — watertight, boundary=0 |
| `preview_textures/model-chest-p2b-voxel256.glb` | G1b voxel256 — denser, watertight |
| `model-chest-p2b-repaired.glb` | trimesh — слабо |
| `model-chest-quality-*.glb` | P2 A/B |
| `model-chest-ultra-downgrade2.glb` | P1 path |
| Preview | `scripts/preview_glb_local.html` → G1b dropdown |

---

## 7. Журнал

| Дата | Что |
|------|-----|
| 2026-08-05 | Проблема сформулирована: mid-prop hole gate; docs/issues; MV2 paused |
| 2026-08-07 | **G1e eyes (agent+Pedrokita):** lattice raw = **2425 components**, «рассыпанные» прутья; soft75 = куб-решётка лучше, но не чистая cage. **Вывод:** T2 плохо держит intentional open mesh; soft ≠ убийца сетки в первую очередь — лимит модели. Soft остаётся для mid-prop с ложными щелями (chest). |
| 2026-08-07 | **G1d soft75 = 🟢 GO глазами (Pedrokita):** ни одной сквозной дыры, сложные зоны OK, clay smooth. `model-chest-soft75-quality.glb`. Гипотеза «дыры = тёмные борозды/тени на входе» подтверждена. |
| 2026-08-07 | **G1d soft75 smoke ✅** (~$0.10): `model-chest-soft75-quality.glb` — worker quality, seed42. Metrics: **watertight=True, boundary=0** (vs P2b ultra boundary=236). Aesthetic vs baseline — **глаза**. |
| 2026-08-07 | **G1b voxel REJECTED** глазами: watertight OK, но Minecraft/pixel clay — **не SaaS bar**. Gate = smooth clay без сквозных щелей. Дальше: soft-input A/B → MV2 → G4/Meshlib. |
| 2026-08-07 | Баланс +$19. G1b regen локально (`.venv314`): voxel128/256 watertight. G2: `mesh_repair=voxel` opt-in в worker. Pod/deploy ⏸ до глаз. |
| 2026-08-06 | **INCIDENT:** pod `dynmbd1jzzvd04` (G1c) забыли terminate → деньги сгорели. Правило: spike → **terminate в той же сессии**, даже если SSH fail. |
| 2026-08-05 | **G1a:** boundary_edges≈236; trimesh fill **no-op** |
| 2026-08-05 | Local pymeshlab/scipy на py3.14 сломаны → G1c только pod/web или fix venv |

---

## 8. Ссылки

- HF card: https://huggingface.co/microsoft/TRELLIS.2-4B  
- postprocess: https://github.com/microsoft/TRELLIS.2/blob/main/o-voxel/o_voxel/postprocess.py  
- Spike Wonder3D (после gate): `scripts/wonder3d_mv2_spike.md`
