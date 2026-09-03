# Workspace (AI_MESH) — бриф для Cursor на фронте

> **Дата:** 2026-08-31. Репо сайта = **AI_MESH**. Этот файл лежит в **paradox_worker** (API + lab).  
> GPU / RunPod / `.env` / ключи — не трогать. Ключи только на сервере worker.

Lab-референс карточек: `scripts/studio_lab.html` (`.\scripts\studio_lab.ps1` → http://127.0.0.1:8787/).  
Контракт API: `aiMeshFalContract.md`. Слоты 1-фото: `productMultiUx.md` §11. Сетка JPEG: `posterCards.md`.

---

## Промпт в новый чат (вставить в AI_MESH)

```
Работай в AI_MESH (сайт, Studio Workspace). GPU/RunPod не трогай.

Открой соседним окном paradox_worker (git pull ветка feat/trellis2-poc):
@memory-bank/workspaceFrontend.md
@memory-bank/aiMeshFalContract.md
@memory-bank/productMultiUx.md
@memory-bank/posterCards.md

Сделай Workspace Image-to-3D:
1. Default engine = trellis2. Hero-кнопка → fullscreen picker (1/3 список, 2/3 showcase).
   Группы: Свои GPU (trellis2, hi3dgen) / Meshy · FAL / Hitem / Tripo / Rodin.
   Данные: GET /api/engines или GET /api/product-copy → engines (+ engine.showcase).
2. Поле configured === false → строка тусклая, Generate и «Выбрать» disabled.
3. Showcase (эталон trellis2): heroCutoutUrl, watermark, anchors, examples[], bestFor[].
   Lab-референс: scripts/studio_lab.html + studio_bridge/engine_showcases.py.
3. Пресеты качества Low/Medium/High/Realistic только если engine.qualityPresets (T2).
   Rodin: **не** два слота — один `rodin` + полоска Quality Tier (Lowest→Ultra) → поле `rodinQualityTier`.
4. Слоты: Front обязателен; Side/Back/Extra опционально. Пустые не слать.
5. POST /api/jobs { engine, tier, viewSlots, seed, rodinQualityTier? }. Poll GET /api/jobs/{jobId}.
6. Лента = posterUrl JPEG. Большой вьюер = один GLB (modelUrl). Не ключи в браузер.
7. Визуал: ruby-jelly (rose/coral), не cosmic cyan. Вьюер .js не .mjs.
8. Hunyuan на витрине нет. Не обещать «как Meshy». Generate = деньги, confirm.

Не копировать 3DAI 35/40 cr. Не класть FAL_KEY / Tripo / Rodin / Hitem в клиент.
```

---

## Каталог движков (витрина)

| id | UI группа | provider | credits (юзер, 2.5×) | Заметки |
|----|-----------|----------|----------------------|---------|
| `trellis2` | Свои GPU | runpod | 10 + cold 12 | **default**. Пресеты качества |
| `hi3dgen` | Свои GPU | runpod | 4 + cold 8 | Черновик, не рыцарь |
| `meshy` | Meshy · FAL | fal | 80 | Единственный живой FAL |
| `hitem3d` | Hitem | hitem | 50 | v2.1 fast |
| `hitem3d_pro` | Hitem | hitem | 90 | v2.1 pro |
| `hitem3d_v3` | Hitem | hitem | 210 | v3 quality |
| `hitem3d_portrait` | Hitem | hitem | 50 | портрет |
| `tripo` | Tripo | tripo | 30 | H3.1 |
| `tripo_p1` | Tripo | tripo | 50 | P1 |
| `tripo_p2` | Tripo | tripo | 70 | **P2 Preview** `P2-20260801`, `quad=true` (image-only v1) |
| `rodin` | Rodin | rodin | 15–60 по тиру | **Один** Rodin 2.5; Quality Tier Lowest→Ultra (default Medium≈25 cr). Ultra≈60 |

Нет на витрине: `rodin_extreme` (legacy id, API → ultra), `hunyuan`, `hunyuan_pro`, FAL-T2. Hunyuan = Tencent Cloud, регистрация с РФ зависла (SMS). Не рисовать карточку.

**Rodin Quality Tier → Hyper3D:** lowest→Extreme-Low · low→Low · medium→Medium · high→High · ultra→Extreme-High. См. `RODIN_QUALITY_TIERS` в `studio_bridge/rodin_client.py`; в каталоге `engine.rodinQualityTiers[]`.

Поле `configured` (bool): ключ на бэке есть/нет. Не путать с «сеть плохая».

---

## Engine showcase (picker правая 2/3)

Эталон: **`trellis2`** в `studio_bridge/engine_showcases.py`. Lab: `studio_lab.html` → hero-кнопка «Модель» → fullscreen picker.

Поле `engine.showcase` (optional):

| Поле | Тип | Зачем |
|------|-----|--------|
| `headline` | string | заголовок витрины |
| `heroCutoutUrl` | url | PNG без фона, центр композиции |
| `heroFallbackUrl` | url | запас, если cutout 404 |
| `watermark` | string | крупный текст на фоне |
| `capabilities` | string[] | chips |
| `bestFor` | string[] | rose chips «когда выбирать» |
| `avoidFor` | string[] | опционально |
| `examples` | `{kind,url,label}[]` | полоска 4 превью (input/output/detail) |
| `anchors` | `{text,class}[]` | подписи вокруг hero: `tl` `tr` `bl` `br` |

Новый engine = скопировать блок `trellis2` в `engine_showcases.py` + свои `/preview_textures/…` или R2 URL.

---

## Job id (poll как есть)

| Префикс | Пример |
|---------|--------|
| T2 | UUID без префикса |
| Hi3DGen | `rp:hi3dgen:<uuid>` |
| Meshy | `fal:meshy:<request_id>` |
| Hitem | `hitem:<engine>:<task_id>` |
| Tripo | `tripo:<engine>:<task_id>` |
| Rodin | `rodin:<engine>:<uuid>\|<subscription_key>` |

Не парсить Rodin на фронте. Poll целиком `jobId`.

Fail: `creditsRefunded: true`, `creditsCharged: 0`. Кошелёк — AI_MESH.

---

## Не делать

Ключи в localStorage / Vite env клиента. Клон 3DAI. img2mv. Обещать Hunyuan. Generate без confirm. GLB в сетке карточек.
