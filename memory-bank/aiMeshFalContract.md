# Контракт AI_MESH ↔ paradox_worker (хаб v1)

> **Дата:** 2026-08-27; **касса 2026-08-31:** FAL = только Meshy.  
> **Зачем:** API, который Studio (AI_MESH) должен бить.  
> Lab-референс: `scripts/studio_lab.html`. Бриф фронта: `workspaceFrontend.md`.

Не юрконсультация. Ключ FAL **не** в браузер. Ключи Tripo/Rodin тоже только сервер.

## Эндпоинты

База: `scripts/studio_api.py` (`http://127.0.0.1:8787` в лабе).

| Метод | Путь | Что |
|-------|------|-----|
| GET | `/api/product-copy?country=RU` | слоты + `engines` + `credits` |
| GET | `/api/engines?country=DE` | витрина: T2, Hi3DGen, Meshy, Hitem, Tripo, Rodin |
| GET | `/api/credits` | тарифы draft/quality/cold + Meshy/Hitem/Tripo/Rodin ≥ 2.5× |
| POST | `/api/jobs` | `engine` + `viewSlots` + опционально `country` |
| GET | `/api/jobs/{id}?country=RU` | poll; FAL `fal:meshy:…`; Hitem `hitem:…`; Tripo `tripo:…`; Rodin `rodin:…\|…` |

Страна: тело/`?country=` **или** заголовок `CF-IPCountry`. Гео-гейт Hunyuan в коде жив на потом; слота Hunyuan в каталоге нет.

## Движки

Default = `trellis2`. Честные имена в UI: «Meshy 6», не «наша SOTA».

Живой FAL: **только `meshy`**. Живой Hitem: `hitem3d`, `hitem3d_pro`, `hitem3d_v3`, `hitem3d_portrait` (`hitem:<engine>:<task_id>`). Живой Tripo: `tripo`, `tripo_p1` (`tripo:<engine>:<task_id>`). Живой Rodin: `rodin`, `rodin_extreme` (`rodin:<engine>:<uuid>|<subscription_key>`). POST `hunyuan` → **501**. Tencent — позже. Карточка без ключа в каталоге `configured: false`; create без ключа → 501.

Ключи: `FAL_KEY`, `HITEM_CLIENT_ID`, `HITEM_CLIENT_SECRET`, `TRIPO_API_KEY`, `RODIN_API_KEY`/`HYPER3D_API_KEY` только сервер.

## Кредиты

Номинал $0.025. FAL Meshy: `ceil(list * 2.5 / 0.025)`. Fail → `creditsRefunded: true`, `creditsCharged: 0`. Кошелёк считает AI_MESH. Безлимит выключен.

T2 Low = draft; Medium = quality; High/Realistic дороже; `creditsColdSurcharge` если воркер cold.

## A/B рыцарь

`python scripts/fal_knight_ab.py` — по умолчанию только Meshy.  
`--live` жжёт деньги. Пока `knightGate: pending` — слот не продавать как «лучше T2».

## Не делать

Ключ FAL/Tripo/Rodin в клиенте; веса Hunyuan на RunPod; API 3D AI Studio как бэкенд; клон визуала 3DAI.
