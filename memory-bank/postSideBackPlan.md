# План после Side/Back тупика (честный roadmap)

> **Дата:** 2026-08-10 (Pedrokita)  
> **Настроение:** жаль, что «кнопки идеального зада с 1 фото» нет — это не провал работы, а **потолок стека**  
> **Связь:** `t2FinishPlan.md`, `productMultiUx.md`, `sideBackUnblock.md`, `textureWowPlan.md`

---

## 0. Честно про «не справились»

**Не справились** = не нашли способ сделать Meshy-уровень **бок/зад с одной картинки** на нашем open T2.

**Справились** = выяснили границу и закрыли дорогие тупики:

| Сделали | Зачем важно |
|---------|-------------|
| Front ultra (rt6) + soft_input props | Prod recipe есть |
| Remesh/denser не чинят зад | Не жечь GPU зря |
| Synth / Gemini → T2 | Не продукт |
| W3D++ abort | Не AGPL-deps hell в prod |
| Research + UX spec A | Знаем *как* говорить юзеру и когда multi помогает |

Индустрия тоже **не** «решила невидимую сторону с 1 JPEG» — решила **обходом**: multi-фото или закрытый движок. Мы упёрлись в ту же физику.

---

## 1. Цель продукта на ближайший горизонт

```
1 фото  →  честный T2 (сильный front, mid side/back)  +  вау-текстура
2–4 фото →  опция multi (реальные ракурсы)              — UI в Studio
1 фото «как Meshy сзади» →  другой shape позже (C2)    — не сейчас
```

Не обещать то, чего T2 не умеет. Вау искать в **текстуре и UX**, не в knobs зада.

---

## 2. План по фазам

### Фаза P0 — зафиксировать (сейчас ✅ / дожать доки)

| # | Задача | Где | Статус |
|---|--------|-----|--------|
| P0.1 | Research fusion | `multiViewFusionResearch.md` | ✅ |
| P0.2 | UX multi spec | `productMultiUx.md` | ✅ |
| P0.3 | Unblock matrix closed paths | `sideBackUnblock.md` | ✅ |
| P0.4 | Этот roadmap | `postSideBackPlan.md` | ✅ |
| P0.5 | Memory push когда Pedrokita скажет | git | ⏳ |

### Фаза P1 — продукт честности (без GPU)

| # | Задача | Где | Примечание |
|---|--------|-----|------------|
| P1.1 | Слоты Front / Side / Back / Extra + copy | **AI_MESH Studio** | по `productMultiUx.md` |
| P1.2 | Default = 1 фото; multi только если есть доп. слоты | Studio → bridge | API уже есть |
| P1.3 | Help: чеклист «не нужна студия, нужна одна поза» | сайт / Studio | успокоить про «неидеальные» фото |
| P1.4 | (опц.) Smoke 3–4 **реальных** фото vs single | paradox worker | proof пути A глазами |

**Критерий P1:** юзер понимает ожидания; multi не продаётся как «AI sheet».

### Фаза P2 — вау без новой формы (GPU texture)

| # | Задача | Где | Примечание |
|---|--------|-----|------------|
| P2.1 | MV-Adapter W2b на **best clay** (Armor ultra / prod) | Track A / `textureWowPlan.md` | F3 |
| P2.2 | Не красить «мыло» и чужой Meshy-mesh | правило | |
| P2.3 | Сравнить глаза: clay vs textured на том же GLB | preview | |

**Критерий P2:** текстура тянет восприятие; форма та же, но «дороже» выглядит.

### Фаза P3 — freeze T2 в продукте

| # | Задача | Примечание |
|---|--------|------------|
| P3.1 | Tier copy: preview / quality / ultra (если ultra в Studio) | F5 |
| P3.2 | Docs: soft_input для mid-props; character = best-effort back | `techContext` + Studio |
| P3.3 | Не открывать заново synth→T2 / remesh-for-back | locked |

**Критерий P3:** «T2 finish» можно считать закрытым для shape.

### Фаза P4 — новый shape / smarter fusion (позже)

| # | Задача | Когда |
|---|--------|-------|
| P4.0 | **ReconViaGen** — MASTER `reconViaGenMvRefiner.md` | 🟢 HOT eyes; D2 GLB → D3 pod → D4 worker |
| P4.1 | Hi3DGen / TripoSG spike (C2) | ⏸ если RVG fail |
| P4.2 | Не кормить weak synth в naive T2 | locked |
| P4.3 | Лицензии / EU prod | до любого prod merge |

**Критерий P4.0:** Side/Back или front-integrity **better** vs Armor ultra / pair soap — иначе soft-NO-GO.  
**Критерий P4.1:** Side/Back **better** vs `t0_armor_ultra_s42` глазами — иначе закрыть метод.

### Явно не в плане

- Ещё Unique3D / Wonder3D v1 → T2  
- Gemini sheet как prod multi  
- Wonder3D++ без чистого venv/бюджета  
- Confidence fusion без нормальных real views  
- «Ещё denser / soft на рыцаре ради зада»

---

## 3. Порядок «что делать завтра»

Рекомендуемый порядок (один трек за раз):

```
1) D2  ReconViaGen GLB smoke + A/B     ← D-track MASTER
2) P1  Studio UX
3) P2  Texture W2b
4) D3  ReconViaGen pod (если D2 better)
5) P3  Tier freeze
```

Если Studio далеко — можно начать с **P2**, спека P1 уже в памяти.

---

## 4. Метрика успеха (чтобы не грустить зря)

| Вопрос | Успех |
|--------|--------|
| Props с 1 фото | soft_input GO — уже есть |
| Character front | ultra GO — уже есть |
| Character back с 1 фото = Meshy | **не цель этого стека** |
| Character back с 2–4 фото | лучше single на согласованных — цель P1+smoke |
| Вау «дорого» | текстура P2 |
| Когда снова лезть в shape | только P4 с бюджетом |

---

## 5. Decision log

| Дата | Решение |
|------|---------|
| 2026-08-10 | Side/Back с 1 фото на T2 = потолок; план → P1 UX, P2 tex, P3 freeze, P4 later |
| 2026-08-10 | **A pair smoke eyes:** мыло + dual sword → soft-NO-GO Gemini F+B; путь A остаётся для *реальных* фото |
| 2026-08-10 | ComfyUI multiview SEO = noise; **ReconViaGen + MV Refiner** spike → `reconViaGenMvRefiner.md` |
| 2026-08-11 | **Eyes HF ReconViaGen (Pedrokita): ОГО** — sharp side/back, 1 меч; screens in reconviagen/ |
| 2026-08-11 | D-track **MASTER** expanded: prod=separate endpoint; naive multi closed; fusion patch=optional |

---

## 6. Статус одной строкой

```
Shape T2: front done, back mid accepted.
Next: P1 Studio honesty UX → P2 MV-Adapter on best clay → P3 freeze → P4 Hi3DGen if needed.
```
