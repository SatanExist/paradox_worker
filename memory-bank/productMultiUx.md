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
| 2. Слоты + copy в Studio UI | **AI_MESH** | ⏳ **товарищ** (визуал); bridge готов |
| 3. Smoke: 3–4 **реальных** фото → multi vs single глазами | paradox worker / R2 | ⏳ когда есть съёмка |
| 4. Help-статья на сайте | AI_MESH | ⏳ вместе с UI |

---

## 10. Статус одной строкой

```
A UX: locked. Bridge viewSlots + product-copy ✅. Studio UI still AI_MESH (other PC).
```
