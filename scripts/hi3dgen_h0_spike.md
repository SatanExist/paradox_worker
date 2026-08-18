# H0 spike — Hi3DGen (1-photo high-fidelity geometry)

> **Статус:** 🔄 **D4 path** — `Dockerfile.hi3dgen` + CI → GHCR → volume → serverless. Голый pod **ABORT** (2026-08-18).  
> **План:** `memory-bank/netsTexToolsPlan.md`  
> **Не путать с** TRELLIS.2 worker (`worker_trellis2.py`). Это отдельный стек.

## Что это

Бумага: *Hi3DGen: High-fidelity 3D Geometry Generation from Images via Normal Bridging* (ICCV 2025, arXiv 2503.22236).

Код, который реально запускать: **[Stable-X/Stable3DGen](https://github.com/Stable-X/Stable3DGen)** (репо также как Hi3DGen). MIT. Адапт **TRELLIS v1** + normal bridge; NVIDIA kaolin/nvdiffrast/flexicubes **убраны** (коммерчески спокойнее, чем наш T2 образ).

Веса:

| Модель | Роль |
|--------|------|
| `Stable-X/trellis-normal-v0-1` | image/normal → mesh (finetune TRELLIS) |
| `Stable-X/yoso-normal-v1-8-1` | RGB → normal (YOSO / StableNormal turbo) |
| `ZhengPeng7/BiRefNet` | фон / preprocess |

Пайплайн в `app.py`: фото → preprocess 1024 → **normal 768** → `Hi3DGenPipeline.run(..., formats=["mesh"])` → `mesh.glb`.  
В демо: «каждый меш ~40 MB». **Текстуры PBR нет** — только форма. «Multiple Images» в UI — *coming soon*, не RVG.

HF Space: https://huggingface.co/spaces/Stable-X/Hi3DGen — не prod, 2026-08-18 не прогнали. Голый pod 2026-08-18 — abort.

## Ops (как T2 / RVG D4)

1. Push `Dockerfile.hi3dgen` → CI `build-hi3dgen` → `ghcr.io/satanexist/paradox_worker:hi3dgen-sha-<short>`  
2. Network volume тот же паттерн: `HF_HOME=/runpod-volume/huggingface_cache`, веса ` /runpod-volume/hi3dgen/weights`  
3. Отдельный **serverless** endpoint, `workersMin=0`, env как T2 (HF_TOKEN, R2_*)  
4. New Release на image tag → **один** smoke `test_req_hi3dgen.py` (рыцарь seed 42) → GPU слить  
5. Глаза в lab: High T2 vs H0, **каркас** + albedo off  

Не: `setup.sh` на живом pod, SSH/SCP oneshot, always-on `workersMin>0`.

## Зачем нам

T2 ultra: макро ок, микро (львы/табард) мыло. Knobs закрыты. Hi3DGen — единственный оставшийся **открытый** bet на скульптуру с 1 фото.

## Сравнение (глаза)

| | Файл / джоб |
|--|-------------|
| Вход | тот же `ref_gold_armor` (R2 smoke / lab пресет Рыцарь) |
| Baseline форма | `preview_textures/t0_armor_ultra_s42.glb` и/или High `preset_high_armor.png.glb` (смотреть **меш**, albedo выкл / каркас) |
| Не baseline | Meshy SaaS как «должен совпасть»; W2b 80k |

Смотреть: **Front орнамент вблизи**, **Side**, **Back**. Цвет/золото не критерий.

| Вердикт | Когда |
|---------|--------|
| **GO** | львы/швы читаемее T2 **или** зад заметно цельнее, макро не развалился |
| **soft-NO-GO** | макро хуже T2, микро чуть лучше — не тащить в default |
| **NO-GO** | blob / дыры / два меча / хуже T2 везде |

Два прогона same/worse → метод закрыт (`sideBackUnblock.md`).

## Явно не делать

- Голый pod + pip/clone (D3 hell; инцидент 2026-08-06)
- Кормить Hi3D-меш в T2 shape
- img2mv / Gemini sheet
- Decimate «чтобы влез paint» до вердикта формы
- Смешивать с `Dockerfile.trellis2` на том же worker
- Считать HF Space = prod

## Следующий шаг после глаз

- GO → H1 в `netsTexToolsPlan.md` (чем красить этот меш).  
- NO-GO → не TripoSG без новой просьбы; вернуться к инструментам лабы на T2.
