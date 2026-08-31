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
1. Default engine = trellis2. Селектор — кликабельные карточки по вендорам, не один <select>.
   Группы: Свои GPU (trellis2, hi3dgen) / Meshy · FAL / Hitem / Tripo / Rodin.
   Данные: GET /api/engines или GET /api/product-copy → engines.
2. Поле configured === false → карточка тусклая, Generate не слать (нет ключа на бэке).
3. Пресеты качества Low/Medium/High/Realistic только если engine.qualityPresets (T2).
   Чужие сети — без этой лестницы, свои credits/etaSeconds.
4. Слоты: Front обязателен; Side/Back/Extra опционально. Пустые не слать.
5. POST /api/jobs { engine, tier, viewSlots, seed }. Poll GET /api/jobs/{jobId}.
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
| `rodin` | Rodin | rodin | 30 | Gen-2.5 High |
| `rodin_extreme` | Rodin | rodin | 60 | Extreme-High |

Нет на витрине: `hunyuan`, `hunyuan_pro`, FAL-T2. Hunyuan = Tencent Cloud, регистрация с РФ зависла (SMS). Не рисовать карточку.

Поле `configured` (bool): ключ на бэке есть/нет. Не путать с «сеть плохая».

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
