# Product multi UX — честный 1-фото + опция ракурсов

> **Статус:** 🟢 **spec locked** 2026-08-10; 2026-08-13: synth/img2mv **не режим** (класс frozen)  
> **Слой:** продукт / Studio (AI_MESH) + контракт bridge; **не** новый GPU worker  
> **Связь:** `postSideBackPlan.md` P1, `synthMultiViewProd.md` (frozen), `reconViaGenMvRefiner.md` (optional later tier)

---

## 1. Решение одной фразой

**По умолчанию — одна картинка и честный потолок T2.**  
**Опция — до 3 доп. реальных ракурсов** (не AI-sheet). Multi включается только если юзер реально приложил виды.

---

## 2. Зафиксированные выборы (без развилок)

| Вопрос | Решение | Почему |
|--------|---------|--------|
| Где UI | **AI_MESH Studio** (фронт) | Это продукт; этот репо = API + док |
| Где контракт | `studio_bridge` / `studio_api` уже умеет `imageUrls` 2–4 | Не менять API без нужды |
| Слоты | **Жёсткие роли:** Front (обяз.) + Side + Back + Extra | Понятнее свободных «2–4 URL» |
| Fusion в UI | **Скрыт**; 1-photo = single T2; real multi = `stochastic` (позже **ReconViaGen** если endpoint) | Naive на synth 🔴; RVG не 1-photo |
| AI sheet / Gemini / img2mv | **Не режим продукта** | класс frozen 2026-08-13 |
| Когда делать smoke | **После UI или по желанию** на реальных фото предмета | Не блокер спеки |

---

## 3. Два режима (для юзера)

### Обычный (default)

- 1 фото в слот **Front**.
- Job: single T2. Пресет качества: **low / medium / high / realistic** (default **medium**). Все — нативный PBR T2, не глина.
- Ожидание: хороший перед; бок/зад — догадка.

### Несколько ракурсов (optional)

- Front + хотя бы **ещё один** из Side / Back / Extra → multi (2–4 URL).
- Порядок в API: `[front, side?, back?, extra?]` — пустые слоты не слать.
- Ожидание: бок/зад лучше **если** фото согласованы; иначе может быть хуже single.

---

## 4. Макет слотов (Studio)

```
[ Front * ]     ← всегда
[ + Добавить ракурсы ]  ← раскрывает:

    [ Side  ]  [ Back  ]  [ Extra ]
```

- Пока доп. слоты пустые → single (даже если блок раскрыт).
- Заполнен Front + любой доп. → multi.
- Максимум 4 картинки (как `MAX_MULTI_IMAGES` в bridge).

Не показывать: `multiImageMode`, «multidiffusion», «TRELLIS».

---

## 5. Copy (готовые строки)

**Под Front (всегда):**  
«3D с одной картинки. Перед будет ближе к фото; бок и зад модель достраивает сама.»

**Под блоком ракурсов:**  
«Реальные фото того же предмета сбоку и сзади улучшают форму. Снимки должны быть похожи по свету и размеру. Картинки „со всех сторон“ из нейросети часто портят результат — лучше одна чёткая фотка.»

**Tooltip / help (коротко):**  
«Нужны: один объект, одна поза, разные углы, чистый фон. Не смешивайте фото и скетч.»

**После job (статус):**  
- 1 вид → «Собрано с 1 фото»  
- N видов → «Собрано с N ракурсов»

---

## 6. Чеклист для help-страницы (Meshy-style)

✅ Один предмет, одна поза  
✅ Углы заметно разные (front / side / back)  
✅ Похожий свет и размер в кадре  
✅ Чистый фон (или удалить фон на всех)  
❌ Два почти одинаковых «почти front»  
❌ AI-turnaround вместо съёмки  
❌ Фото + скетч вперемешку  

Если сомневаешься — оставь одно фото.

---

## 7. Backend mapping

| UI | Bridge / RunPod |
|----|-----------------|
| только Front | `imageUrl` **или** `viewSlots: { front }` → single |
| Front + 1–3 доп. | `viewSlots: { front, side?, back?, extra? }` → `imageUrls` 2–4, `multiImageMode: "stochastic"` |
| legacy | `imageUrls` 2–4 без ролей — всё ещё ок |
| copy для UI | `GET /api/product-copy` (`qualityPresets`, слоты, честный потолок) |
| quality preset | `low` \| `medium` \| `high` \| `realistic` (default **medium**). Legacy: `preview`→low, `quality`→medium, `ultra`→high |

Worker допускает до 8 URL; **продукт Studio = max 4** (не расширять без причины).

Проверка без GPU: `python scripts/check_product_multi_ux.py`

---

## 8. Что не делаем в v1 этого UX

- Авто-детект «это Gemini sheet» (provenance API нет).
- Авто-warn «углы слишком похожи» (можно v2).
- Отдельный «ultra» в UI — теперь **high** / **realistic**.
- Обещание «как Meshy с одной фотки по заду».

---

## 9. План внедрения

| Шаг | Где | Статус |
|-----|-----|--------|
| 1. Эта спека | `paradox_worker` memory | ✅ |
| 1b. Bridge `viewSlots` + `/api/product-copy` | `studio_bridge` | ✅ 2026-08-13; **2026-08-16:** пресеты low/medium/high/realistic + native PBR |
| 2. Слоты + copy в Studio UI | **AI_MESH** | ⏳ пакет §11 **ещё не слали**. Прототип: `studio_lab.html` |
| 3. Smoke: 3–4 **реальных** фото → multi vs single глазами | paradox worker / R2 | ⏳ когда есть съёмка |
| 4. Help-статья на сайте | AI_MESH | ⏳ вместе с UI |

---

## 10. Статус одной строкой

```
A UX: locked. Bridge + presets + qualityReduced ✅. Lab прототип ✅.
Пакет товарищу: §11 + git push feat/trellis2-poc. UI делать в AI_MESH.
```

---

## 11. Пакет товарищу (AI_MESH) — для Cursor на другом ПК

> Репо сайта = **AI_MESH**. Этот репо = API + прототип + контракт. GPU не трогать.
> Ветка worker: `feat/trellis2-poc`. Сначала `git pull`.

### Промпт в новый чат Cursor (AI_MESH)

```
Работай в AI_MESH (сайт). GPU/RunPod не трогай — это paradox_worker.

Контракт (можно открыть соседним окном paradox_worker):
@memory-bank/productMultiUx.md
Смотри §11 и GET /api/product-copy.

Сделай Studio:
1. Селектор Low / Medium / High / Realistic из qualityPresets. Default medium.
   Персонаж: High. Realistic = 4K того же меша, на карточке как High, файл тяжелее.
2. Слоты: Front обязателен; Side / Back / Extra опционально. Пустые не слать.
3. Карточка модели: IBL + орбита. Идеи света из paradox_worker/scripts/studio_viewer.js
   (Studio/Gallery судить материал; Neon/Night только wow). Визуал сайта: ruby-jelly
   (rose/coral), не cosmic cyan. Файл вьюера копируй как .js, не .mjs.
4. ETA в минутах из etaSecondsCold/Warm. Не писать «4–80 секунд» как у Rodin.
5. Если job.qualityReduced === true — бейдж текстом qualityReducedCopy
   («Качество снижено, чтобы модель собралась»). Не показывать CUDA/OOM.
6. GLB приходит modelUrl с R2 (25–100 MB). Карточка грузит этот URL.
   Не ждать base64. Превью-меш/Draco — не в этой задаче.

Демо без генерации:
- Low сундук (~12 MB):
  https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/trellis2/18c5eae7-656b-4ea2-afec-bf91bb2b5b40-e2.glb
- Medium сундук (~25 MB):
  https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/trellis2/2c2cff9e-ccc4-4d68-a2a9-e44bbabb2283-e2.glb
- High рыцарь (~47 MB, 2K+polish):
  https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/trellis2/315cf9fb-d9de-4349-900c-0cf2b09a6aa2-e1.glb
- Realistic рыцарь (~97 MB):
  https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/trellis2/13796711-fc97-45cb-b6d3-580052cf5fb3-e2.glb

Честно: 1 фото = сильный перед; бок/зад = догадка. AI-sheet не режим.
```

### Что уже есть у нас (не верстать заново)

| Что | Где смотреть |
|-----|----------------|
| Copy + пресеты | `GET /api/product-copy` → `qualityPresets`, слоты, честный потолок |
| Слоты | Front обязателен; Side/Back/Extra опционально; пустые не слать |
| Пресеты | **low / medium / high / realistic**, default **medium**. Legacy: preview→low, quality→medium, ultra→high |
| Clay | только если явно `textureMode: "clay"` — не default |
| Job status | `modelUrl`, `qualityReduced`, `qualityReducedCopy`, `modelBytes`, ETA |
| Прототип экрана | `scripts/studio_lab.html` |
| Прототип карточки | `scripts/model_review.html` + `scripts/studio_viewer.js` |
| Контракт | `studio_bridge/product_multi_ux.py`, `studio_bridge/tiers.py`, `studio_bridge/normalize.py` |

### Пресеты (для селектора, как Rodin-полка — не их ETA)

| Кнопка | Worker | Tex | Soft | Polish | ETA cold/warm (4090, честно) | Типичный GLB |
|--------|--------|-----|------|--------|------------------------------|--------------|
| Low | preview / 512 | 1024 | нет | нет | ~6 мин / ~45 с | ~12 MB (сундук) |
| Medium | quality / 1024 | 2048 | да, hole 0.1 | нет | ~8 мин / ~4 мин | ~25 MB (сундук) |
| High | ultra / 1536 | 2048 | нет | да | ~10 мин / ~5 мин | ~47 MB (рыцарь 2K) |
| Realistic | ultra / 1536 | **4096** | нет | да | ~12 мин / ~6 мин | ~97 MB (рыцарь 4K) |

Не писать «4–80 секунд» как у Rodin. Cold = поднятие воркера.

Пресеты = **лестница детализации одного T2 PBR**, не «реализм vs стилизация». Стиль задаёт фото.

**Глаза 2026-08-16 (рыцарь):** High и Realistic на карточке **одинаковы**. Одинаковый ultra-меш; разница только 2K vs 4K (~47 vs ~97 MB). Для Studio персонажа рекомендовать **High**. Realistic — если нужен 4K вблизи / экспорт в DCC.

### Тяжёлый GLB — как делают крупные (и что делаем мы)

Meshy / Rodin / Sketchfab **не** пихают 100 MB в JSON и не ждут полный файл, чтобы показать карточку:

| Слой | У них | У нас сейчас |
|------|--------|----------------|
| Превью в ленте | рендер / короткий ролик / маленький proxy | можно постер с фото входа; live GLB на карточке |
| Вьюер | Draco / meshopt + сжатые текстуры (KTX2/WebP), CDN | Three.js грузит `modelUrl` с R2 как есть |
| Скачать | тот же или «оригинал» | тот же `modelUrl` |
| 4K PNG | редко в веб-карточке | Realistic = PNG 4K специально для Blender/совместимости |

**Не делать в этой задаче UI:** второй worker «сжать в Draco». Карточка честно грузит R2. Если тормозит — позже Low как proxy или Draco, не сейчас.

### DCC later (Blender / Unreal / Cursor)

Не в этой задаче сайта. Когда дойдём: аддон/MCP бьёт в **тот же** API, что Studio. Агент не считает 3D — ждёт `modelUrl` и импортирует GLB. RunPod-ключ на сервере, не в DCC.

### Бейдж `qualityReduced` (это не стиль)

Иногда GPU не влезает в VRAM на High/Realistic. Worker **сам** повторяет легче (тот же job): сначала без remesh, потом как Medium. Юзер просил Realistic, получил более лёгкий меш.

- Поле: `qualityReduced: true`
- Текст: `qualityReducedCopy` — «Качество снижено, чтобы модель собралась.»
- **Не** показывать `downgrade_reason`, CUDA, OOM.
- На удачных смоках рыцаря/сундука этого не было (`false`).

### Карточка модели (обязательно IBL)

- Референс света: Hyper3D Rodin — ~70% вау = HDRI/rim/пол, не другая физика меша.
- Режимы света в прототипе: **Studio** (судить PBR) / **Gallery** (честный цвет) / Outdoor / Neon / Night.
- Studio/Gallery/Outdoor = циклорама (без серого диска на горизонте). Neon/Night = чёрная пустота + контактная тень.
- Neon/Night = wow only, не для приёмки материала.
- Visual сайта: **ruby-jelly** (rose/coral), не cosmic cyan.
- Файл вьюера: **`.js`**, не `.mjs`.

### Честный продукт (не обещать)

- 1 фото = сильный **перед**; бок/зад = догадка T2.
- Реальные ракурсы улучшают форму **если** свет/масштаб согласованы.
- AI-sheet / Gemini turnaround — не режим.
- img2mv / MV-Adapter 80k на персонаже — закрыто.

### Живой движок (для них не трогать GPU)

- Endpoint T2 `ynzpzjvcbfl656`, image `trellis2-sha-ffd6d36`, **v17**.
- Low сундук ~12 MB: `https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/trellis2/18c5eae7-656b-4ea2-afec-bf91bb2b5b40-e2.glb`
- Medium сундук ~25 MB: `https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/trellis2/2c2cff9e-ccc4-4d68-a2a9-e44bbabb2283-e2.glb`
- High рыцарь ~47 MB: `https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/trellis2/315cf9fb-d9de-4349-900c-0cf2b09a6aa2-e1.glb`
- Realistic рыцарь ~97 MB: `https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/trellis2/13796711-fc97-45cb-b6d3-580052cf5fb3-e2.glb`
