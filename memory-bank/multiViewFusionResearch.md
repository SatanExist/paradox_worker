# Research: multi-view series ↔ 3D generators (согласование)

> **Дата:** 2026-08-10 (Pedrokita)  
> **Зачем:** ответить «T2 всё равно что Gemini/фото/synth?» и «мы криво подаём или вход плохой?»  
> **Связь:** `sideBackUnblock.md`, `synthMultiViewProd.md`, наши smokes B/MV4b

---

## 1. Главный вывод (для продукта)

**T2 (и большинство image→3D) не знает provenance.** Ему всё равно: iPhone, Gemini sheet, Unique3D.  
Важны только **пиксели + согласованность серии + способ fusion**.

«Синтетика плохая» у нас = ярлык **класса входа** (часто конфликтный / низкий HF / не ortho), не бит в API.

Формула:

```text
multi success ≈ view_consistency × detail_fidelity × fusion_quality
```

Наш стек: fusion = **naive** (stochastic / equal multidiffusion). При конфликтных видах multi **может быть хуже single** — это не баг только наших knobs, так пишут upstream и papers.

---

## 2. Как устроен multi у TRELLIS / TRELLIS.2

Источники: [TRELLIS.2 PR #104](https://github.com/microsoft/TRELLIS.2/pull/104), [issue #103](https://github.com/microsoft/TRELLIS.2/issues/103), DeepWiki TRELLIS multi-image, код `inject_sampler` (stochastic % N / average preds).

| Mode | Механика | Плюсы | Минусы |
|------|----------|-------|--------|
| **stochastic** | на шагах denoising **циклически** меняют conditioning-картинку | дешевле по VRAM; иногда стабильнее на практике | «лотерея» порядка; разные позы/детали → дёрганье |
| **multidiffusion** | на каждом шаге считают pred **по каждому** виду и **усредняют** (равные веса 1/N) | идея «все виды сразу» | конфликт → smear / толще-тоньше; автор PR сам хочет confidence-aware |

**Важно (upstream README / DeepWiki):** multi у TRELLIS — **tuning-free** без спец. обучения на multi; «may not give the best results for all input images». Оба режима плохо переваривают разные позы / inconsistent details.

**Community:** [#103 multi-image inputs is worse](https://github.com/microsoft/TRELLIS.2/issues/103) — люди видят multi **хуже** single; у кого-то multidiffusion ломает, stochastic ок. Наш Gemini B (ultra, оба mode) = soft-NO-GO глазами — в том же классе.

**Автор PR #104:** deformation при multidiffusion ≈ из-за **равного average**; план — fusion с приоритетом более уверенного вида (ещё WIP).

**У нас в коде:** worker `MAX_MULTI_IMAGES=8`; Studio `imageUrls` **2–4**. Provenance не передаётся.

---

## 3. Почему naive multi портит (теория + paper)

Источник: [MV-SAM3D](https://arxiv.org/html/2603.11633v2) (2026).

Проблема:

1. Single-view модель на **невидимых** регионах **галлюцинирует**.  
2. Она **не отличает** «увидел» vs «выдумал».  
3. Naive Multi-Diffusion: `v̂ = Σ (1/N) · v_θ(x,t,c_i)` — все виды равны в каждой точке 3D.  
4. Надёжный вид j смешивается с галлюцинацией вида k → **деградация**, не улучшение.  
5. Явно: **TRELLIS + naive Multi-Diffusion отстаёт** от confidence-aware методов.

Их фикс (training-free, не наш код):

- **attention-entropy weighting** — низкая энтропия attention = выше confidence  
- **visibility weighting** — геом. видимость точки из камеры  

Следствие для нас: чинить «подачу» без смены fusion = только half-fix. Нужны либо **согласованные виды**, либо **лучший fusion** (путь D), либо не multi.

---

## 4. Что требуют инструменты от серии (best practices)

### Meshy Multi-view ([docs](https://docs.meshy.ai/en/webapp/guides/choosing/generation-method), [help](https://help.meshy.ai/en/articles/12634481-how-to-use-multi-view), [tutorial](https://www.meshy.ai/tutorials/multi-view-image-to-3d))

| Требование | Смысл |
|------------|--------|
| 2–4 (до ~8 в таблице методов) **реальных** углов | front / side / back / 3/4 |
| Один объект, одна сессия | не «разные интерпретации» |
| Ровный свет, похожий масштаб/дистанция | меньше конфликта |
| Чистый фон | silhouette |
| Asymmetry (логотипы, ручки) | multi сохраняет; single часто зеркалит/теряет |

Meshy **сами** разделяют: Image-to-3D (1 фото, зад = догадка) vs Multi-view (2–4 фото, зад читается с входа).  
Back-side accuracy ★ выше у Multi-view — при **хороших** фото, не при любом sheet.

**Meshy: когда multi НЕ нужен** ([best practices](https://help.meshy.ai/en/articles/16102789-meshy-multi-view-best-practices-angles-and-images)):

- только одно чёткое фото;
- «доп. виды» = другой объект / другая поза;
- blur / low-res / тяжёлый crop;
- углы почти одинаковые (два «почти front»);
- смесь sketch + photo.

Их FAQ: **больше картинок ≠ лучше** — важнее consistency. Это прямо совпадает с нашим soft-NO-GO на Gemini/U3D.

Дополнительно (help + tutorial): углы ≥45–90° apart; rembg на **всех** видах; ≥~1040²; rotate object, не camera; character sheet — одна поза (A/T), один стиль.

### InstantMesh / Zero123++ lineage

Другая схема: **1 фото → внутренний** multi-view diffusion (обученный быть согласованным) → sparse recon.  
Views не «любые JPEG с чата», а **связанная** генерация под реконструкцию.  
Поэтому InstantMesh ≠ «залей 4 Gemini в T2».

### Классическая photogrammetry / NeRF multi-view

Ещё жёстче: известные **камеры**, overlap, калибровка.  
Generative multi (T2) калибровку не требует, но тогда **семантика** серии должна быть согласована — иначе average врёт.

---

## 5. Два разных пайплайна (не путать)

```text
A) USER multi  →  image_urls[]  →  T2 fusion     (у нас API есть)
B) 1 photo → SYNTH views → image_urls[] → T2   (MIT synth у нас NO-GO)
C) 1 photo → INTERNAL MV diffusion → recon     (InstantMesh-класс; другой стек)
D) 1 photo → NATIVE 3D diffusion               (Rodin-класс; другой стек)
```

Gemini turnaround = внешне похож на A, по качеству согласованности ближе к **плохому B**.  
Wonder3D/Unique3D = явный B с слабым MV prior.

---

## 6. «Мы криво подаём?» — честный разбор

| Фактор | Оценка | Комментарий |
|--------|--------|-------------|
| Provenance ignore | ✅ норма | так и должно |
| Equal multidiffusion | ⚠ слабо | known limitation; PR автор согласен |
| Порядок / число видов | 🟡 | 4 ок; порядок может влиять на stochastic |
| Preprocess на cutout | 🟡 | может чуть портить; не главный killer |
| Gemini inconsistency (меч, выдуманный зад) | 🔴 | главный killer B |
| U3D/W3D 256px melt | 🔴 | главный killer MIT synth |
| Нет camera poses / visibility weights | ⚠ | нет в нашем fusion (и в PR #104) |

**Вердикт research:** гипотеза «дело не в слове synth, а в согласованности + fusion» — **подтверждена литературой и нашими глазами**.  
Гипотеза «только кривая подача, виды были ок» — **отвергнута** для Gemini/U3D (виды 3D-несогласованы / низкий HF). Wonder3D: и потолок модели, и preprocess.

---

## 7. Практические рекомендации (AI_MESH)

1. **Prod multi:** только под **реальные** согласованные 2–4 фото; UX = `productMultiUx.md`.  
2. **Не обещать** «Gemini sheet → multi T2».  
3. **Synth → T2:** 🔴 closed (MIT path).  
4. **Fusion / side-back:** MASTER → `reconViaGenMvRefiner.md` (ReconViaGen prod path; naive T2 multi closed).  
5. **1-photo character back:** ReconViaGen tier или честный ultra front; не synth→naive T2.

---

## 8. Ссылки

| | |
|--|--|
| TRELLIS.2 PR #104 multi | https://github.com/microsoft/TRELLIS.2/pull/104 |
| TRELLIS.2 #103 multi worse | https://github.com/microsoft/TRELLIS.2/issues/103 |
| MV-SAM3D (naive vs confidence) | https://arxiv.org/html/2603.11633v2 |
| Meshy multi-view guide | https://www.meshy.ai/tutorials/multi-view-image-to-3d |
| Meshy multi best practices | https://help.meshy.ai/en/articles/16102789-meshy-multi-view-best-practices-angles-and-images |
| Meshy method chooser | https://docs.meshy.ai/en/webapp/guides/choosing/generation-method |
| TRELLIS multi (tuning-free note) | https://github.com/microsoft/TRELLIS (Updates 12/18/2024; issue #7) |
| ReconViaGen v0.5 × T2 | https://github.com/GAP-LAB-CUHK-SZ/ReconViaGen/tree/v0.5 |
| ReconViaGen HF demo | https://huggingface.co/spaces/Stable-X/ReconViaGen-v0.5 |
| MultiView Refiner | https://github.com/cuzelac/ComfyUI-Trellis2-MultiViewRefiner |
| D-track MASTER | `memory-bank/reconViaGenMvRefiner.md` |
| InstantMesh | https://github.com/TencentARC/InstantMesh |

---

## 9. Статус одной строкой

```
T2 multi = provenance-blind; needs consistent views + non-naive fusion.
Our B/MV4b failures = inconsistent/low-fid series × equal average — matches SOTA critique.
Next: real-photo multi UX checklist; not more weak synth→T2.
```
