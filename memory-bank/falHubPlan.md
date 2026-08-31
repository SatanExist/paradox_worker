# План: свой T2 + Meshy на FAL + прямые API заводов

> **Дата:** 2026-08-26; **касса 2026-08-31:** FAL = **только Meshy**.  
> **Зачем:** что реально можно продавать без своего фундамента и без consumer-ключей Meshy.  
> **Связь:** `tz50CtoReview.md`, FAL API Services (ключ FAL не в браузер).

Не юрконсультация. Цены FAL — playground 2026-08-27 (глазами). COGS T2 — наши замеры.

---

## Решение кассы (2026-08-31)

**На FAL оставляем только Meshy** (завод для РФ закрыт, другого белого склада нет).

Остальное **не через FAL**:

| Слот | Чем крутим | Статус |
|------|------------|--------|
| T2 / Hi3DGen | наш RunPod | живой |
| Meshy | FAL Partner | живой каталог |
| Tripo | `openapi.tripo3d.ai` | wrap YES (Lorna); **адаптер live** `tripo_client.py` (H3.1 / P1). Generate — позже |
| Rodin | `api.hyper3d.com` | wrap YES (David); conc=1; **адаптер live** `rodin_client.py` (High / Extreme). Generate — позже |
| Hitem | `api.hitem3d.ai` | **живой адаптер** `hitem_client.py`. Селфсервис: ключ в `.env`. Sales только conc>30 |
| Hunyuan | Tencent Cloud **позже** | снят с FAL; веса на RunPod нет |

FAL Trellis-2 / FAL Rodin / FAL Tripo / FAL Hitem / FAL Hunyuan — не витрина. Билдеры в коде спрятаны (`show_in_catalog=False`), create на них → 501.

FAL — не замена T2. Default = T2.

---

## Набор нейронок (витрина v1)

| Слот в UI | Чем крутим | Себестоимость | Идея цены юзеру | Зачем |
|-----------|------------|---------------|-----------------|-------|
| Черновик | наш Hi3DGen | дёшево | низкий тариф | секунды, не обещать рыцаря |
| Качество (default) | наш T2 | warm ~$0.02–0.08, realistic/cold выше | средний/высокий тариф, отдельно cold | единственный прошедший наш рыцарь |
| Meshy 7 | **FAL** `meshy/v7/image-to-3d` (в коде ещё v6) | глина **$0.80**, tex **$1.20** | ≥2.5× (80 / 120 cr) | **единственный слот FAL.** Не default. 3DAI 35/40 cr не копировать. Enterprise РФ 🔴. |
| Tripo | прямой API (H3.1 / P1) | H tex ~$0.30; P1 ~$0.50 | ≥2.5× от PAYG | wrap YES; не FAL v2.5 |
| Rodin | прямой API Gen-2.5 | High $0.30; Extreme-High $0.60 | ≥2.5× | wrap YES; **1 concurrent** |
| Hitem | прямой API `hitem3d` / `_pro` / `_v3` / `_portrait` | fast $0.50 / pro $0.90 / v3 $2.10 | ≥2.5× | селфсервис, ключ в `.env` |
| Hunyuan | Tencent **позже** | — | — | не FAL. Веса на RunPod нет. |
| Запас T2 на FAL | не кладём | $0.25–0.35 | — | дороже своего T2 |

**Meshy на FAL** (`fal-ai/meshy/v6` в шлюзе; playground v7 $0.80/$1.20): не default, не демпинг «как 3DAI за 35 cr». Ключ meshy.ai consumer — нет. **Enterprise Meshy для РФ закрыт 2026-08-28** (compliance). Опт завода нет.  
**Hunyuan:** не на витрине, пока не разберём Tencent Cloud. Гео-гейт EU/UK/KR в коде остаётся на потом. Веса Hunyuan на RunPod — нет.

### Meshy 7 vs 3DAI (глаза 2026-08-27)

Воркспейс 3DAI точнее карточки: Ultra/tex/PBR off → **35 cr**, 5–10 мин; tex+PBR on → **40 cr**. Basic $19/1000 cr = $0.019/cr → $0.67 / $0.76. Завод Meshy API: 20 / 30 cr × $0.02 (Pro) = $0.40 / $0.60. Склады: FAL $0.80/$1.20; Pixazo как FAL; WaveSpeed $0.88/$1.32 (ToS против SaaS). Дешёвая цена 3DAI — не агрегатор.

Правила витрины с этого SKU: default T2; Meshy — именной слот с ETA 5–10 мин; тумблер текстуры прыгает в кредитах, не +5 cr; пакет не копировать $19=1000 под их Meshy.

**РФ (практика, не юрсовет):** селфсервис RunPod/FAL с Visa у нас уже проходит — это не «всё запрещено». Enterprise KYC (страна компании, счёт) жёстче кабинета. На созвоне Meshy не играть чужую страну. Приём денег от юзеров (Stripe из РФ) — отдельный слой, не путать с оплатой FAL.

---

## Честная экономика (не таблица Gemini)

Свой T2 на тёплом воркере **дешевле**, чем FAL Trellis 2. Маржа живёт на **своём** Generate, FAL — доплата за «другую сеть».

Правила цен:

- Свой GPU: закладывать **cold** отдельной строкой или средним COGS, не $0.006.
- FAL: цена юзеру ≥ **2.5×** публичного тарифа (ретрай, НДС, поддержка).
- Неудачный job — возврат кредитов.
- Безлимит не делать.

Пакет вроде $25 / 1000 кредитов ок, если номинал кредита бьётся с реальной сеткой тарифов, а не с выдуманным $0.006.

---

## Сверка цен FAL vs первоисточник (2026-08-27)

Глазами на playground FAL + официальные API/billing страницы. Публичный list, не wholesale.

| Модель | FAL | Первоисточник | Дельта |
|--------|-----|---------------|--------|
| **Hitem3D** v2.1 1536 fast / pro | $0.50 / $0.90 ($0.02/cr) | [docs](https://docs.hitem3d.ai/en/api/getting-started/pricing): 25 / 45 cr × $0.02 | **0%** |
| **Tripo** v2.5 img→3d | $0.20 / $0.30 / $0.40 + $0.05 style/quad | [Developers](https://developers.tripo3d.ai/en/pricing): 1 cr = $0.01; 20 / 30 / 40 cr; quad +5 | **0%** |
| **Hunyuan** Rapid / Pro | $0.225 / $0.375; PBR +$0.15 | Tencent Express 15 cr / Pro 25 cr. Prepaid $0.015 → те же $. Postpaid $0.02 → $0.30 / $0.50. PBR +10 cr | **0% vs prepaid**; FAL дешевле postpaid. **Не EU/UK/KR** |
| **Rodin** v2 | **$0.40**/gen; v2.5 HighPack **+$0.80** | API от 0.5 cr. [Business](https://hyper3d.ai/pricing) $120 ≈ 416 моделей → **~$0.29**. Direct **$1.50/cr** → $0.75 за 0.5 cr | FAL **+38%** к Business; **дешевле** Direct |
| **Meshy 6** img→3d | **$0.80** (playground) | 30 cr с tex. Pro $20/1000 = $0.02/cr → **$0.60** | FAL **+33%** к Pro |
| **Trellis 2** | $0.25 / $0.30 / $0.35 | наш T2 warm **~$0.02–0.08** | FAL **×4–15** vs тёплый T2 |

Вывод: Tripo и Hitem3D на FAL — не наценка, а тот же PAYG с правом wrap. Meshy/Rodin дороже их подписок — это цена легальности без consumer-ключа. Свой T2 на FAL не дублировать.

---

## Агрегаторы кроме FAL (2026-08-27)

Исследование публичных каталогов/ToS. Не юрконсультация.

**Второго FAL по партнёрским 3D с более низкой list-ценой нет.**

| Площадка | Meshy-6 / Rodin | Wrap нашим юзерам | Заметка |
|----------|-----------------|-------------------|---------|
| **fal.ai** | $0.80 / $0.40 | **Да** (API Services, End Users, ключ не в браузер) | База |
| **WaveSpeedAI** | $0.80 / $0.40 (Meshy-7 **$1.32** vs FAL **$1.20**) | **Нет:** ToS §8 — нельзя make available Services как SaaS | Каталог шире (Seed3D $0.35, SAM 3D $0.02). Rapid Hunyuan страница **$0.0225** — похоже на 1 credit, не generation |
| **Replicate** | нет Partner Meshy/Rodin | свой продукт ок | Hunyuan-2 OSS ~$0.12; community Trellis.2 ~$1.18 |
| **PiAPI / Eachlabs / Segmind** | нет | слабее FAL | Trellis.2 $0.10; Hunyuan v2 OSS $0.16–0.30 |
| **PoYo** | Meshy **$0.30** | серый | −63% к Partner-list; Meshy ToS запрещает resell |
| **Atlas Cloud** | Hunyuan **$0.02** | не проверять как опт | Совпадает с Tencent **$/credit**, не с 15 cr Express |
| **3D AI Studio API** | их кредиты | конкурент | Строить хаб на их API = копировать Dashboard |
| **Kie.ai** | 3D-партнёров нет | реселлер видео/картинок | Не наш стек |

Где искать выгоду по Meshy: только FAL (завод РФ закрыт). Rodin/Tripo/Hitem — прямой API, не FAL.

Hitem3D можно и напрямую (цена = FAL, ToS End Users). Tripo Developer PAYG = FAL. Hunyuan EU — Tencent Cloud Europe, не дешёвые витрины.

---

## Как это устроено

```
AI_MESH Studio  →  кошелёк кредитов
        →  studio_api / бэкенд AI_MESH
              ├── RunPod T2 / Hi3DGen
              ├── FAL — только Meshy (ключ не в браузер)
              ├── Hitem Open Platform (HITEM_CLIENT_*)
              └── прямые API: Tripo, Rodin (адаптеры next)
        →  GLB на R2  →  кабинет
        →  позже: Hunyuan через Tencent; кнопка remesh/LOD
```

Ключи FAL / RunPod / Tripo / Rodin только на сервере. Юзер видит «Rodin (Hyper3D)» / «Tripo», не «наша секретная SOTA».

---

## Фазы

**Фаза 0 — кабинет (AI_MESH, сейчас)**  
Кредиты, джобы, полка, пресеты, слоты Front/Side/Back. Generate = T2. Draft = Hi3DGen.

**Фаза 1 — шлюз (этот репо + AI_MESH)**  
Код: `studio_bridge/fal_client.py`, `engines.py`, `gateway.py`, `geo.py`, `credits.py`.  
Живой FAL-слот: **Meshy**. Рыцарь A/B: `scripts/fal_knight_ab.py` (по умолчанию только meshy). `knightGate=pending`.  
Next: адаптеры Tripo / Rodin. Hitem уже в шлюзе. Hunyuan — Tencent, не сейчас.

**Фаза 2 — доводка**  
Python remesh/STL на GLB с R2, платная кнопка. Не C++ в спринте 1.

**Фаза 3 — Tencent / FAL invoice**  
Hunyuan для витрины — когда откроется Tencent Cloud. FAL Enterprise — инвойс/conc по Meshy, не скидка на чужие Partner-сети.

**Не фаза:** свой фундамент; img2mv; Pixal3D/Step1X как quality; монорепо frontend в paradox_worker.

## Сетки по заводам (2026-08-31)

Цена ниже = **API COGS** за генерацию, не розница (у нас ×2.5). Канвас: `enterprise-nets.canvas.tsx`.

### Polylab — свой GPU (RunPod)

| Сетка | Для чего | Параметры | Сильные | Цена API | Слот |
|-------|----------|-----------|---------|----------|------|
| TRELLIS.2 Realistic | Качество default, 1 фото | Пресеты Low–Realistic, native PBR. Рыцарь PASS | Дешевле чужих, свой пайплайн | Warm ~$0.02–0.08; cold отдельно | `trellis2` |
| Hi3DGen | Черновик объёма | ~256³, clay, секунды | Дёшево и быстро | Копейки GPU / 4 cr | `hi3dgen` |

Concurrent = `workersMax`. Cold start воркера ≠ очередь чужого API.

### Meshy — только FAL

Завод РФ 🔴. Consumer Pro нельзя. Concurrent = FAL (2…~40).

| Сетка | Для чего | Параметры | Сильные | Цена API | Слот |
|-------|----------|-----------|---------|----------|------|
| Meshy 6/7 | Именной слот, не default | FAL v6 (playground v7), глина или tex+PBR, часто 5–10 мин | Бренд, персонажный look | Глина **$0.80** / tex **$1.20** / ultra $1.40 | `meshy` |

### Hitem / Hi3D — прямой Open Platform

Кабинет: пакет → **Create Key** (не hi3d.ai Pro). 1 cr = $0.02. Concurrent FAQ **30**. Адаптер живой.

| Сетка | Для чего | Параметры | Сильные | Цена API | Слот |
|-------|----------|-----------|---------|----------|------|
| hitem3dv2.1 fast | Печать / hard-surface | 1536fast, ~2M faces, PBR, GLB, 1–4 вида | Дешевле Meshy, 30 сразу, ToS End Users | **$0.50** (25 cr) | `hitem3d` |
| hitem3dv2.1 pro | То же, выше деталь | 1536pro, PBR, GLB | Как fast, pro-рез | **$0.90** (45 cr) | `hitem3d_pro` |
| hi3dv3.0 quality | Максимум без master | 2048quality, PBR, GLB | Больше вокселей | **$2.10** (105 cr) | `hitem3d_v3` |
| portrait v2.1 fast | Портрет / bust | scene-portraitv2.1, 1536profast | Заточен под лицо | **$0.50** | `hitem3d_portrait` |

Не на полке: v1.5, v2.0, 2048master **$9.10**, relief/split/depth.

### Tripo — VAST (адаптер next)

Wrap YES. 1 cr = $0.01. Concurrent **H 10 / P 5**.

| Сетка | Для чего | Параметры | Сильные | Цена API | Слот |
|-------|----------|-----------|---------|----------|------|
| H3.1 | Быстрый чужой | 20 / 30 / 40 cr | Дёшево, много параллели | $0.20 / $0.30 / $0.40 | next |
| P1 | Выше качество Tripo | 40 / 50 / 60 cr; snapshot P1-20260311 | Их pro-линейка | $0.40 / $0.50 / $0.60 | next |

### Rodin — Deemos (адаптер next)

Wrap YES. Concurrent **1**. 120–240 = RPM.

| Сетка | Для чего | Параметры | Сильные | Цена API | Слот |
|-------|----------|-----------|---------|----------|------|
| Gen-2.5 High | Органика / hero | GLB PBR; tex/BANG отдельно | Визуал витрины | **$0.30**; tex +$0.30 | next |
| Extreme-High | Жирный тир | Тот же API | Максимум Rodin | **$0.60**; +tex → $0.90 | не default |

### Tencent Hunyuan — пауза

Не FAL, не веса на RunPod. Express ≈ **$0.23**, Pro ≈ **$0.38** prepaid. Concurrent 1 / 3.

Очередь ≠ cold start. RPM ≠ параллельные генерации.

## Следующий Enterprise (не сегодняшняя пачка)

| Куда | Зачем | Когда |
|------|--------|--------|
| [Tencent HY 3D Global](https://www.tencentcloud.com/products/ai3d) Contact sales | Hunyuan на витрину (сейчас слот снят) | **позже**, не эта неделя |
| [fal.ai/enterprise](https://fal.ai/enterprise) | Инвойс, concurrency >40, не скидка на Partner Meshy/Rodin | Когда объём FAL, не вместо заводов |
| CSM / Luma / Stability | US, слабый смысл vs T2+Tripo | Не слать в этой волне |

Stripe Atlas — потом (приём денег), не ключ к Meshy.

---

## Правило приёмки чужого слота

Как парк сетей: тот же вход (рыцарь cutout), глаза до ручек. Если хуже T2 на персонаже — слот не «качество», а «другое» (печать / hard-surface / запас).
