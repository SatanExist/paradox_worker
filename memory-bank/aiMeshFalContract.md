# Контракт AI_MESH ↔ paradox_worker (FAL-хаб v1)

> **Дата:** 2026-08-27  
> **Зачем:** фронт AI_MESH на этом ПК нет; здесь — API, который Studio должен бить.  
> Lab-референс: `scripts/studio_lab.html` (селектор движка, гео Hunyuan, кредиты).

Не юрконсультация. Ключ FAL **не** в браузер.

## Эндпоинты

База: `scripts/studio_api.py` (`http://127.0.0.1:8787` в лабе).

| Метод | Путь | Что |
|-------|------|-----|
| GET | `/api/product-copy?country=RU` | слоты + `engines` + `credits` |
| GET | `/api/engines?country=DE` | витрина; Hunyuan `visible:false` в EU/UK/KR |
| GET | `/api/credits` | тарифы draft/quality/cold и FAL ≥ 2.5× |
| POST | `/api/jobs` | `engine` + `viewSlots` + опционально `country` |
| GET | `/api/jobs/{id}?country=RU` | poll; FAL id вида `fal:meshy:<request_id>` |

Страна: тело/`?country=` **или** заголовок `CF-IPCountry`. Без страны Hunyuan **запрещён** (fail closed), не только скрыт в UI.

## Движки

Default = `trellis2`. Честные имена в UI: «Meshy 6», «Hunyuan Rapid (Tencent)», не «наша SOTA».

Hunyuan generate с `country=DE` → **403**. Meshy через FAL, не ключ meshy.ai.

## Кредиты

Номинал $0.025. FAL: `ceil(list * 2.5 / 0.025)`. Fail → `creditsRefunded: true`, `creditsCharged: 0`. Кошелёк считает AI_MESH. Безлимит выключен.

T2 Low = draft; Medium = quality; High/Realistic дороже; `creditsColdSurcharge` если воркер cold.

## A/B рыцарь

`python scripts/fal_knight_ab.py` — dry-run payload по официальным API-вкладкам FAL.  
`--live` жжёт деньги. Пока `knightGate: pending` — слот не продавать как «лучше T2».

## Не делать

Ключ FAL в клиенте; веса Hunyuan на RunPod; API 3D AI Studio как бэкенд; клон визуала 3DAI.
