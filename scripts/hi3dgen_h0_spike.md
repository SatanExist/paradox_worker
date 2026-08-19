# H0 spike — Hi3DGen (1-photo high-fidelity geometry)

> **Статус:** 🟡 **H0c FlexiCubes** (2026-08-19). Глаза H0/H0b1 = **мыло**. Не GO. Метод не закрыт.  
> **План:** `memory-bank/netsTexToolsPlan.md`  
> **Не путать с** TRELLIS.2 worker (`worker_trellis2.py`). Это отдельный стек.

## Как пользоваться (бумага + `app.py` + issues)

Сеть = **фото → нормаль → меш**. Не T2. PBR нет. «Multiple Images» в UI — *coming soon*, не RVG.

Официальный ритуал ([`app.py`](https://github.com/Stable-X/Stable3DGen/blob/main/app.py), [arXiv 2503.22236](https://arxiv.org/html/2503.22236v2)):

1. Одно **изолированное** фото предмета (лучше почти-изометрия / CGI-эстетика — appendix).
2. Preprocess **1024** (квадрат + pad). Фон: GitHub/наш = **BiRefNet**; HF Space = **rembg**.
3. Нормаль **768**, `data_type='object'`, YOSO `yoso-normal-v1-8-1` (в бумаге NiRNE). В NoRLD идёт **нормаль с белым фоном**, не RGB.
4. Stage 1 Sparse Structure: **ss=50, CFG=3.0** (бумага: «optimal»). Слайдер max 50 — не крутить выше.
5. Stage 2 slat: **slat=6, CFG=3.0**. Это локальные латенты на уже выбранных вокселях, **не** плотность сетки.
6. Экспорт `formats=["mesh"]` → `to_trimesh()` → GLB.

Смотреть **Normal Bridge** до меша: мыльная нормаль → мыльный меш (абляция в бумаге).

| Knob | Default | Не делать |
|------|---------|-----------|
| ss_steps / ss CFG | 50 / 3 | ss>50 |
| slat_steps / slat CFG | 6 / 3 | slat ради densify (H0b1: 12 ≈ тот же 7.5 MB) |
| normal reso | 768 | 1024 не официальный Gradio |
| mesh resolution slider | **нет** | [#52](https://github.com/Stable-X/Stable3DGen/issues/52): 256 «blocky», 512 → сотни GB VRAM |

Подпись Gradio «~40 MB» — предупреждение виджету. Наш GLB ~7.5 MB / 155k verts = геометрия без `vertex_attrs`. Размер файла ≠ острота.

### Что пишут в issues

- [#36](https://github.com/Stable-X/Stable3DGen/issues/36): локальный GitHub **хуже HF Space**. Авторы: (1) rembg vs BiRefNet; (2) **FlexiCubes → marching cubes**. Когда нормали одинаковые, мыло/ямки = MC. Пользователи ждут FlexiCubes обратно.
- [#43](https://github.com/Stable-X/Stable3DGen/issues/43): FlexiCubes теперь **Apache-2.0**, в апстрим не вернули.
- [#26](https://github.com/Stable-X/Stable3DGen/issues/26): народ на 6 GB гоняет те же ss=50 / slat=6.
- [#1](https://github.com/Stable-X/Stable3DGen/issues/1): текстур нет.
- [#50](https://github.com/Stable-X/Stable3DGen/issues/50): сторонний «Ultra Advanced App», не апстрим.

Декодер TRELLIS-normal всё ещё пишет **21 вес FlexiCubes** (`sdf`+`deform`+`weights`). GitHub `EnhancedMarchingCubes` их **игнорирует**. H0c = вернуть FlexiCubes extract (MaxtirError fork, без kaolin).

## Что это

Бумага: *Hi3DGen: High-fidelity 3D Geometry Generation from Images via Normal Bridging* (ICCV 2025, arXiv 2503.22236).

Код: **[Stable-X/Stable3DGen](https://github.com/Stable-X/Stable3DGen)** MIT. Адапт **TRELLIS v1** + normal bridge.

Веса:

| Модель | Роль |
|--------|------|
| `Stable-X/trellis-normal-v0-1` | image/normal → mesh (finetune TRELLIS) |
| `Stable-X/yoso-normal-v1-8-1` | RGB → normal (YOSO / StableNormal turbo) |
| `ZhengPeng7/BiRefNet` | фон / preprocess |

HF Space: https://huggingface.co/spaces/Stable-X/Hi3DGen — не prod. Голый pod 2026-08-18 — abort.

## Ops (как T2 / RVG D4)

1. Push `Dockerfile.hi3dgen` → CI `build-hi3dgen` → `ghcr.io/satanexist/paradox_worker:hi3dgen-sha-<short>`  
2. **Свой** volume `paradox-hi3dgen` (`qm6i6st1tr`, EU-RO-1, 80 GB). Не том T2 `netu72a8j2`. Веса `/runpod-volume/hi3dgen/weights`  
3. Отдельный serverless `mvpjjsb2fxj2ht`, `workersMin=0`. T2 `ynzpzjvcbfl656` v21 не патчить  
4. New Release **только** template `s15aqi9lxs` → smoke `test_req_hi3dgen.py` (рыцарь seed 42, **slat=6**) → GPU слить  
5. Глаза: High T2 vs H0, **каркас** + albedo off; смотреть ещё `normal_url`

Не: `setup.sh` на живом pod, SSH/SCP oneshot, always-on `workersMin>0`, общий диск с T2.

Env: `HI3DGEN_MESH_EXTRACT=flexicubes` (default). `mc` = старый marching cubes, только A/B.

## Глаза H0 (2026-08-19, Pedrokita)

Артефакт: `preview_textures/h0_armor_hi3dgen.glb` (~7.5 MB), seed 42, official default **ss=50 / slat=6**.  
R2: `hi3dgen/7bf18394-debe-4f8a-8334-901c18cb543b-e2.glb`.

| | |
|--|--|
| Макро | «низкокачественная» vs T2 High; силуэт цел, один меч |
| Микро / бок / зад | **орнаменты уже видны** (спина, табард, плечи) — дырка T2 |
| Вердикт | не default; **метод не закрывать** |

### H0b — slat не densify

| Шаг | Knob | Итог |
|-----|------|------|
| **H0b1** | slat 6 → **12** | 7.49 vs 7.46 MB, ~56 с. Pedrokita: **мыло**. Slat не рычаг |
| H0b2 | slat **25** | **не делать** |
| H0b3 | normal 768 → 1024 | не Gradio; только если нормаль мыльная |
| **H0c** | **FlexiCubes extract** | next: веса декодера наконец используются |

## Зачем нам

T2 ultra: макро ок, микро (львы/табард) мыло. Knobs закрыты. Hi3DGen — единственный оставшийся **открытый** bet на скульптуру с 1 фото.

## Сравнение (глаза)

| | Файл / джоб |
|--|-------------|
| Вход | тот же `ref_gold_armor` |
| Baseline форма | High `preset_high_armor.png.glb` (**меш**, albedo выкл / каркас) |
| H0 MC | `preview_textures/h0_armor_hi3dgen.glb` |
| Не baseline | Meshy SaaS; W2b 80k |

Смотреть: **Front орнамент вблизи**, **Side**, **Back**, карта нормалей. Цвет/золото не критерий.

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
- slat=25 как densify
- kaolin/nvdiffrast в `Dockerfile.hi3dgen` ради FlexiCubes (достаточно MaxtirError + stub `check_tensor`)

## Следующий шаг после глаз

- Сейчас → **H0c** FlexiCubes (CI → Release `s15aqi9lxs` → smoke seed 42 slat=6).  
- Если нормаль острая, а меш всё ещё мыло — тогда rembg vs BiRefNet, не slat.  
- GO после H0c → H1 paint.  
- NO-GO → не TripoSG без новой просьбы.
