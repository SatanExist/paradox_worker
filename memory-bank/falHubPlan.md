# План: свой T2 + набор через FAL

> **Дата:** 2026-08-26  
> **Зачем:** что реально можно продавать без своего фундамента и без consumer-ключей Meshy.  
> **Связь:** `tz50CtoReview.md` (что выкинуть из ТЗ 5.0), FAL API Services (юзеры через наш бэкенд, ключ FAL не в браузер).

Не юрконсультация. Цены FAL — playground 2026-08-27 (глазами). COGS T2 — наши замеры. Сверка с вендорами: раздел ниже.

---

## Что мы можем (мнение)

1. **Сайт-кабинет** (AI_MESH): кредиты, полка GLB, Generate, пресеты отраслей, слоты реальных фото. Это и есть товар.
2. **Своя генерация** (этот репо): TRELLIS.2 = качество по умолчанию; Hi3DGen = быстрый черновик. Самохост дешевле FAL Trellis 2.
3. **Набор чужих сетей через FAL**, не через личные кабинеты Meshy/Tripo: ключ FAL на бэкенде, в UI честно написано чья сеть.
4. **Платная доводка** (позже): упростить сетку / STL / LOD на готовом файле. Не мясорубка после каждой генерации.
5. **Не делаем:** Hunyuan-**веса** у себя (EU/UK/KR вне лицензии, включая Output). Ключ с meshy.ai / tripo3d.ai в Generate. Цифра 98% маржи на T2 quality.

**Письма на meshy.ai / tripo3d.ai / Tencent не нужны**, чтобы крутить то, что уже на FAL как Partner + commercial use. Договор тогда с FAL. Письмо — только если нужен опт дешевле FAL или Hunyuan для ЕС через Tencent Cloud Europe.

FAL — касса чужих сетей. Не замена T2.

---

## Набор нейронок (витрина v1)

| Слот в UI | Чем крутим | Себестоимость | Идея цены юзеру | Зачем |
|-----------|------------|---------------|-----------------|-------|
| Черновик | наш Hi3DGen | дёшево | низкий тариф | секунды, не обещать рыцаря |
| Качество (default) | наш T2 | warm ~$0.02–0.08, realistic/cold выше | средний/высокий тариф, отдельно cold | единственный прошедший наш рыцарь |
| Meshy 6 | FAL `fal-ai/meshy/v6/image-to-3d` | ~$0.80 | ≥2.5× (~80 cr) | **в v1** через FAL, не ключ meshy.ai; не default |
| Hunyuan Rapid/Pro | FAL `fal-ai/hunyuan-3d/v3.1/{rapid,pro}/image-to-3d` | $0.225 / $0.375 | ≥2.5× | **гео-сплит:** EU/UK/KR скрыт+403; иначе слот, не default |
| Печать / деталь | FAL `hitem3d/hi3d/image-to-3d` | ~$0.50 fast / ~$0.90 pro | ≥2.5× | ToS Hitem3D разрешает End Users |
| Органика / hero | FAL `fal-ai/hyper3d/rodin/v2` | $0.40 (HighPack ×3) | ~2.5× | Partner FAL, не default |
| Быстрый чужой | FAL `tripo3d/tripo/v2.5/image-to-3d` | $0.20–0.40 | ~2.5× | Partner FAL; не путать с письмом в Tripo Studio |
| Запас T2 | FAL `fal-ai/trellis-2` | $0.25 / $0.30 / $0.35 (512/1024/1536) | только если наш GPU лёг | **дороже своего T2** — не витрина |

**Meshy на FAL** (`fal-ai/meshy/v6/image-to-3d`, ~$0.80, Partner): **в v1**. Письмо на meshy.ai не нужно. Не default из-за цены.  
**Hunyuan на FAL:** Tencent через FAL, не наши веса. **Глобальный гео-сплит:** слот только вне EU/UK/KR; сервер 403 + UI hide. Веса Hunyuan на RunPod — нет.

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

Где искать выгоду по Meshy/Rodin: **не агрегатор**, а Meshy sales (volume) и Hyper3D Business/Enterprise ($120 пол, ~$0.29/модель **если** их API ToS пускает End Users). Иначе FAL.

Hitem3D можно и напрямую (цена = FAL, ToS End Users). Tripo Developer PAYG = FAL. Hunyuan EU — Tencent Cloud Europe, не дешёвые витрины.

---

## Как это устроено

```
AI_MESH Studio  →  кошелёк кредитов
        →  studio_api / бэкенд AI_MESH
              ├── RunPod T2 / Hi3DGen
              └── FAL (один ключ, не в браузер)
        →  GLB на R2  →  кабинет
        →  позже: кнопка remesh/LOD на готовом файле
```

Ключ FAL и ключ RunPod только на сервере. Юзер видит «Rodin (Hyper3D)» / «Hitem3D», не «наша секретная SOTA».

---

## Фазы

**Фаза 0 — кабинет (AI_MESH, сейчас)**  
Кредиты, джобы, полка, пресеты, слоты Front/Side/Back. Generate = T2. Draft = Hi3DGen.

**Фаза 1 — шлюз FAL (этот репо + AI_MESH)**  
Код: `studio_bridge/fal_client.py`, `engines.py`, `gateway.py`, `geo.py`, `credits.py`. Lab: селектор в `studio_lab.html`. Контракт для сайта: `aiMeshFalContract.md`.  
Слоты: Meshy, Hunyuan (гео-сплит), Hitem3D, Rodin, Tripo v2.5. Рыцарь A/B: `scripts/fal_knight_ab.py` (dry-run; `--live` жжёт FAL). Пока `knightGate=pending`.

**Фаза 2 — доводка**  
Python remesh/STL на GLB с R2, платная кнопка. Не C++ в спринте 1.

**Фаза 3 — письма (не блокер)**  
Только ради оптовой цены или Hunyuan-для-ЕС через Tencent Cloud Europe. Витрина FAL от писем не зависит.

**Не фаза:** свой фундамент; img2mv; Pixal3D/Step1X как quality; монорепо frontend в paradox_worker.

---

## Правило приёмки чужого слота

Как парк сетей: тот же вход (рыцарь cutout), глаза до ручек. Если хуже T2 на персонаже — слот не «качество», а «другое» (печать / hard-surface / запас).
