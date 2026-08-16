# TRELLIS.2 — интернет-аудит + как пользоваться (2026-08-16)

> **Зачем файл:** неделя хождений по кругу. Здесь: что T2 **есть**, как его **правильно** гонять, почему обзоры ≠ наш рыцарь, **что делать дальше** (одно решение).  
> **Источники:** Microsoft HF/GitHub/project page; fal prompt guide; Trify3D VFX review; trellis2.com vs Meshy; наши A/B в `textureWowPlan.md` / `t2FinishPlan.md`.

---

## 1. Что такое TRELLIS.2 по официалам (не маркетинг YouTube)

| | Факт |
|--|------|
| Модель | `microsoft/TRELLIS.2-4B`, MIT research; **Input = Single Image** |
| Выход | **Один прогон: форма + PBR** (base color, roughness, metallic, opacity) |
| Резолюции | `512` / `1024_cascade` / `1536_cascade` |
| Официальный export | `remesh=True`, `decimation_target` до **1_000_000**, `texture_size` **2048–4096** |
| Ограничения HF | мелкие дыры; **нет RLHF/эстетического alignment**; качество = распределение датасета + вход |
| Не умеет | retexture чужого меша; rig/anim; Meshy-платформу; гарантированный зад с 1 фото |

Официальный пайплайн = **3 стадии в одной модели**: sparse structure → shape latent → **material latent**.  
Текстура T2 — **не** отдельный MV-Adapter. Это их Stage 3.

Project page прямо: *shape + material*, PBR, arbitrary topology. Не «clay + потом покрасим как Meshy».

---

## 2. Как правильно использовать (интернет + наши прогоны)

### Вход (fal / гайды — совпадает)

**Хорошо:** один объект, центр кадра, чистый фон, **ровный свет**, ≥512, без окклюзии.  
**Плохо (прямо пишут):** бликующий металл, жёсткие тени, прозрачность, куча объектов, low-res, extreme perspective.

Наш `ref_gold_armor.png` = **анти-пример входа**: золото, baked specular, орнамент, character. Обзоры крутят вазы/игрушки/столбы — другой класс.

### Режим модели

| Цель | Правильно | Неправильно |
|------|-----------|-------------|
| Как в обзорах / HF demo | **Официальный textured cascade** 1024/1536, их PBR, dense mesh | Clay → срезать 80k → чужая краска |
| Preview Studio | `512` clay, дёшево | ultra + paint на всё |
| Props prod | T2 **quality** + soft_input + **их bake** (или clay если дыры) | ждать Meshy-львов |
| Character close-up | T2 = черновик; retopo + отдельная tex **или** другой shape | knobs / img2mv / третий paint |

### Polycount

Microsoft demo: **до 1M faces**, не 80k.  
80k/200k — наш костыль под xatlas UV. Судить T2 по срезанному мешу = судить не T2.

### Текстура

Правильный T2-путь: **их material stage** (PBR maps вместе с мешем).  
MV-Adapter — **другой продукт**: перекраска готового меша. Имеет смысл, если меш уже ок. На мыльной глине рыцаря — усиливает кашу.

---

## 3. Почему обзоры «лучше Meshy», а у нас «понос»

| Обзор | Мы |
|-------|-----|
| Лёгкий проп, студийный свет | Hard character + золото |
| Смотрят **нативный T2 textured GLB** | Сначала clay, потом MV-Adapter на 80k/200k |
| Издалека / красивый HDRI | Вблизи + Fix metallic |
| Сравнивают T2 vs старый/средний Meshy на пропе | Сравниваем с Meshy Solid **на том же рыцаре** |

VFX-ревью (Trify3D, 2026): T2 **стоит** для background/mid props; **не** для hero character close-up / анимации без retopo. Это не наше нытьё — это прод-консенсус.

Meshy (свой compare): T2 = open image→GLB; Meshy = платформа (PBR retexture любого меша, remesh, rig). Разные продукты.

**Вывод:** T2 не сломан. Мы гоняем его **вне контракта модели** и мерим **чужой планкой**.

---

## 4. Что мы уже доказали сами (не повторять)

| Эксперимент | Итог |
|-------------|------|
| Больше verts / 1536 / no-remesh ради львов | FAIL — каша остаётся |
| Side/back knobs | identical, mid accepted |
| img2mv → T2 | FROZEN |
| T2 cascade bake на рыцаре | mid, хуже Meshy |
| MV-Adapter на ultra clay 80k/200k | albedo живой; геометрия плывёт |

Хождение по кругу = снова крутить эти оси.

---

## 5. Решение: как T2 жить в AI_MESH (стоп метаться)

### Контракт продукта (честный)

```
T2 = лучший self-host MIT image→3D для ПРОПОВ и PREVIEW персонажа.
Не = Meshy-герой вблизи с 1 фото.
```

### Три режима, не один «wow»

| Studio | Что крутим | Ожидание пользователя |
|--------|------------|------------------------|
| **Preview** | T2 512 clay | силуэт за секунды |
| **Standard** | T2 1024 **нативный PBR** (их Stage 3), без 80k cut | «как в обзорах» на пропах |
| **Hero / close-up** | не обещать T2; слоты реальных фото → RVG **или** Hi3DGen shape + отдельная tex | иначе разочарование |

### Вердикт пункта 2 (2026-08-16, Pedrokita)

Нативный T2 ultra PBR на `ref_gold_armor` **ближе к обзорам**, чем clay и чем MV-Adapter 80k/200k.  
Это **потолок T2 на этом character** (hard input: золото + орнамент). Дальше: W3 delight на том же меше; UX честности; Hi3DGen/реальные фото — не knobs.

### Запрещено

- новый sidecar img2mv  
- Hunyuan (EU)  
- ещё decimate A/B «на всякий»  
- Hi3DGen spike **параллельно** с MVPainter (выбрать одно)

---

## 6. Якоря

- HF: https://huggingface.co/microsoft/TRELLIS.2-4B  
- GitHub: https://github.com/microsoft/TRELLIS.2  
- Page: https://microsoft.github.io/TRELLIS.2/  
- fal input: reflective surfaces = плохой вход  
- Trify3D: props yes, hero character no without retopo  
- Наш recipe: `t2FinishPlan.md` ultra rt6; tex: `textureWowPlan.md`
