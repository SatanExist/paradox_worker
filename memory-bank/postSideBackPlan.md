# План после Side/Back тупика (честный roadmap)

> **Дата:** 2026-08-10 (Pedrokita); **обновлено 2026-08-13** — img2mv класс FROZEN  
> **Настроение:** жаль, что «кнопки идеального зада с 1 фото» нет — это не провал работы, а **потолок стека**  
> **Связь:** `t2FinishPlan.md`, `productMultiUx.md`, `sideBackUnblock.md`, `textureWowPlan.md`, `synthMultiViewProd.md` (frozen), `reconViaGenMvRefiner.md`

---

## 0. Честно про «не справились»

**Не справились** = не нашли способ сделать Meshy-уровень **бок/зад с одной картинки** на нашем open T2.

**Справились** = выяснили границу и закрыли дорогие тупики:

| Сделали | Зачем важно |
|---------|-------------|
| Front ultra (rt6) + soft_input props | Prod recipe есть |
| Remesh/denser не чинят зад | Не жечь GPU зря |
| Synth / Gemini → T2 | Не продукт |
| **Класс img2mv OSS (2026-08-13)** | MIT прогнан; лучшие виды закрыты лицензией; рынок ушёл в native 3D |
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
| P1.1 | Слоты Front / Side / Back / Extra + copy | **AI_MESH Studio** | спека+bridge ✅; UI ⏳ |
| P1.1b | Bridge `viewSlots` + `/api/product-copy` | paradox_worker | ✅ 2026-08-13 |
| P1.2 | Default = 1 фото; multi только если есть доп. слоты | Studio → bridge | API уже есть |
| P1.3 | Help: чеклист «не нужна студия, нужна одна поза» | сайт / Studio | успокоить про «неидеальные» фото |
| P1.4 | (опц.) Smoke 3–4 **реальных** фото vs single | paradox worker | proof пути A глазами |

**Критерий P1:** юзер понимает ожидания; multi не продаётся как «AI sheet».

### Фаза P2 — вау без новой формы (GPU texture)

| # | Задача | Примечание |
|---|--------|------------|
| P2.1 | MV-Adapter W2b на clay персонажа | ❌ фольга 80k/200k; только чистый проп |
| P2.1b | Native T2 PBR + W3a polish (High/Realistic) | ✅ v17 live, рыцарь глаза OK |
| P2.2 | Не красить «мыло» и чужой Meshy-mesh | правило |
| P2.3 | Глаза: clay vs textured vs native PBR | победил native PBR |

**Критерий P2 (character):** закрыт native PBR, не MV-Adapter.

### Фаза P3 — freeze T2 в продукте

| # | Задача | Примечание |
|---|--------|------------|
| P3.1 | Tier copy: **low / medium / high / realistic** | bridge ✅ 2026-08-16; UI ⏳ |
| P3.2 | Docs: soft_input для mid-props; character = best-effort back | `techContext` + Studio |
| P3.3 | Не открывать заново synth→T2 / remesh-for-back | locked |

**Критерий P3:** «T2 finish» можно считать закрытым для shape.

### Фаза P4 — новый shape / smarter fusion (позже)

| # | Задача | Когда |
|---|--------|-------|
| P4.0 | **ReconViaGen** — MASTER `reconViaGenMvRefiner.md` | fusion для **реальных** 2–4 фото; **не** Meshy с 1 кадра. Image `a48c0e3` live; `mesh` SIGSEGV; 1-photo GLB ≠ ultra |
| P4.1 | ~~Hi3DGen~~ / TripoSG / Direct3D-S2 (C2) | Hi3DGen 🟡 переставлен 2026-08-20 в быстрый тир (v1-файнтюн, потолок 256³ — как качество не годится). Форма: Pixal3D / Direct3D-S2 / TripoSG — через гейт `netParkProgram.md`, порядок в `roadmap.md` Ф2 |
| P4.2 | Не кормить weak synth в naive T2 / RVG | locked; класс frozen |
| P4.3 | Лицензии / EU prod | Hunyuan/Era3D/Zero123++ — нет |

**Критерий P4.0:** Side/Back или front-integrity **better** vs Armor ultra / pair soap — иначе soft-NO-GO.  
**Критерий P4.1:** Side/Back **better** vs `t0_armor_ultra_s42` глазами — иначе закрыть метод.

### Явно не в плане

- Ещё Unique3D / Wonder3D v1 → T2  
- Gemini / любой AI-sheet как prod multi  
- Wonder3D++ / Era3D в prod (AGPL)  
- Новый img2mv sidecar (класс frozen)  
- RVG как замена Meshy на 1 фото  
- Confidence fusion без нормальных **реальных** views  
- «Ещё denser / soft на рыцаре ради зада»

---

## 3. Порядок «что делать дальше» (после разгрома img2mv)

Разгром = **не** «продукт мёртв». Мёртв только слой «нарисовать бока и скормить T2».

Рекомендуемый порядок (один трек за раз):

```
✅ P3  Freeze T2 v17+ (native PBR + PNG + polish); постеры v21
🔄 P1  Studio UI                          ← товарищ сейчас
▲  Сети / tex / инструменты юзера         ← наш фокус
   Hi3DGen · polish/MVPainter · RVG на реальных фото
1) lab API+viewer ✅
2) Draco skip (не в worker)
▼  MCP / Blender / Unreal                 ← низший приоритет
❌ img2mv — не этап
```

**Split 2026-08-18:** визуал Studio = товарищ; generation = сети/текстуры/инструменты. MCP/DCC не начинать. Сайт копирует `posterCards.md`, не CSS lab.

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
| 2026-08-13 | **img2mv класс FROZEN** (`synthMultiViewProd.md` §14). Next = P1 UX → P2 tex → P3 freeze. RVG = real photos. 1-photo Meshy = P4.1 native 3D. |
| 2026-08-17 | Lab viewer lock (лоадер-карточка, не постер на весь кадр). P1 UI = товарищ; generation = мы. |
| 2026-08-18 | **Приоритет:** сети / текстуры / инструменты юзера ▲. MCP/Blender/прочие API ▼. Draco skip. |

---

## 6. Статус одной строкой

```
img2mv: FROZEN. T2 v21 live. Draco skip. MCP last.
Next him: Studio UI. Next us: сети / tex / юзер-тулзы (Hi3DGen · RVG · polish).
```
