# H0 spike — Hi3DGen (1-photo high-fidelity geometry)

> **Статус:** 🟡 **глаза H0** (2026-08-19) — не GO в default, не NO-GO. Метод живой. Next = **H0b** (плотность).  
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
2. **Свой** volume `paradox-hi3dgen` (`qm6i6st1tr`, EU-RO-1, 80 GB). Не том T2 `netu72a8j2`. Веса `/runpod-volume/hi3dgen/weights`  
3. Отдельный serverless `mvpjjsb2fxj2ht`, `workersMin=0`. T2 `ynzpzjvcbfl656` v21 не патчить  
4. New Release **только** template `s15aqi9lxs` → smoke `test_req_hi3dgen.py` (рыцарь seed 42) → GPU слить  
5. Глаза в lab: High T2 vs H0, **каркас** + albedo off  

Не: `setup.sh` на живом pod, SSH/SCP oneshot, always-on `workersMin>0`, общий диск с T2.

## Глаза H0 (2026-08-19, Pedrokita)

Артефакт: `preview_textures/h0_armor_hi3dgen.glb` (~7.5 MB), seed 42, official default **ss=50 / slat=6** (как Gradio).  
R2: `hi3dgen/7bf18394-debe-4f8a-8334-901c18cb543b-e2.glb`.

| | |
|--|--|
| Макро | «низкокачественная» vs T2 High; силуэт цел, один меч |
| Микро / бок / зад | **орнаменты уже видны** (спина, табард, плечи) — дырка T2 |
| Вердикт | не default; **метод не закрывать** |
| 7.5 vs ~40 MB демо | не баг шагов SS (уже max 50); плотность скорее в **slat** и/или экспорте |

### H0b — докрутка по шагам (один knob за прогон)

| Шаг | Knob | Зачем |
|-----|------|--------|
| **H0b1** | `slat_steps` 6 → **12**, ss=50, seed 42 | больше structured latent; сравнивать с 7.5 MB |
| H0b2 | slat **25**, если 12 мало | ещё деталь; не прыгать в 50 сразу |
| H0b3 | normal 768 → 1024 | карта нормалей; только если slat насытился |
| Не | ss>50 (слайдер апстрима), T2 knobs, H1 paint, decimate | рано |

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

- Сейчас → **H0b1** (slat 12), не H1.  
- GO после плотности → H1 в `netsTexToolsPlan.md` (чем красить этот меш).  
- NO-GO → не TripoSG без новой просьбы; вернуться к инструментам лабы на T2.
