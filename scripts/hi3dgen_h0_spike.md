# H0 spike — Hi3DGen (1-photo high-fidelity geometry)

> **Статус:** 🟡 **H0e = тот же Space `app.py`, clay всё ещё мыло.** Не сломанный вызов. Сетка = TRELLIS FlexiCubes **256³**; обзоры смотрят Preview nvdiffrast + другие входы. Метод открыт до same-image на HF Space.  
> **План:** `memory-bank/netsTexToolsPlan.md`  
> **Не путать с** TRELLIS.2 worker (`worker_trellis2.py`). Это отдельный стек.

## Как пользоваться (бумага + `app.py` + issues)

Сеть = **фото → нормаль → меш**. Не T2. PBR нет. «Multiple Images» в UI — *coming soon*, не RVG.

Официальный ритуал ([HF Space `app.py`](https://huggingface.co/spaces/Stable-X/Hi3DGen/blob/main/app.py), [arXiv 2503.22236](https://arxiv.org/html/2503.22236v2)):

1. Одно **изолированное** фото предмета (лучше почти-изометрия / CGI-эстетика — appendix).
2. Preprocess **1024** (квадрат + pad). Фон в Space и у нас = **rembg u2net** (GitHub HEAD = BiRefNet, хуже, [#36](https://github.com/Stable-X/Stable3DGen/issues/36)).
3. Нормаль **768**, `data_type='object'`. **Демо Space = YOSO** `yoso-normal-v1-8-1`. Бумага = **NiRNE** (другой чекпойнт, `lzt02/NiRNE`). В NoRLD идёт нормаль с белым фоном, не RGB.
4. Stage 1 Sparse Structure: **ss=50, CFG=3.0** (бумага: «optimal»). Слайдер max 50 — не крутить выше.
5. Stage 2 slat: **slat=6, CFG=3.0**. Это локальные латенты на уже выбранных вокселях, **не** плотность сетки.
6. Экспорт `formats=["mesh"]` → `to_trimesh()` → GLB.

Смотреть **Normal Bridge** до меша: мыльная нормаль → мыльный меш (абляция в бумаге).

## Аудит исходников vs мы (2026-08-19)

Почему «мыльный силуэт вместо модели», если H0e уже клон HF Space.

### Официальный контракт (не YouTube)

| Источник | Что сказано |
|----------|-------------|
| [Space `app.py`](https://huggingface.co/spaces/Stable-X/Hi3DGen/blob/main/app.py) | rembg → YOSO 768 → `pipe.run(normal, ss=50/CFG3, slat=6/CFG3, formats=mesh)` → **Preview** = `render_video` color+normal 1024 → GLB = `to_trimesh()` **без** `vertex_attrs` |
| `pipeline.json` `trellis-normal-v0-1` | occupancy **16³**, SLAT **64³**, mesh decoder `resolution=64` |
| `SLatMeshDecoder` | `SparseFeatures2Mesh(res=resolution*4)` → extract **256³** |
| [#52](https://github.com/Stable-X/Stable3DGen/issues/52) | «256 blocky»; **512 = ~520 GB VRAM**. Слайдера резкости нет |
| Бумага ICCV | CFG 3 / 50 steps; нормаль **NiRNE**; сравнивают vs Trellis-RGB / Hunyuan / Dora на *их* кадрах |
| [#36](https://github.com/Stable-X/Stable3DGen/issues/36) | GitHub MC хуже Space FlexiCubes; даже клон Space может чуть отличаться из‑за версий torch |
| [#50](https://github.com/Stable-X/Stable3DGen/issues/50) | SECourses «Ultra Advanced App» = **не** апстрим |
| Примеры Space | chibi-игрушка, бульдог, стилизованный bust — не full-body золотой character с филигранью |

Voxel на full-body рыцаре ≈ **8 мм**. Лев на груди = несколько вокселей → волна, не гравировка. Силуэт (рога, меч, палды) — это потолок 256³, не баг handler’а.

### Наш вызов (H0e, `hi3dgen-sha-e3334ab`)

Совпадает с Space `generate_3d`: rembg u2net, YOSO 768 `object`, `preprocess_image=False` на нормаль, ss=50/3, slat=6/3, FlexiCubes из Space `flexicube.py`, `formats=["mesh"]`.

Не совпадает (мелочь, **не** «силуэт вместо модели»):

- Нет nvdiffrast Preview JPEG (в образе нет nvdiffrast; Space ставит его на первом GPU)
- seed **42** vs слайдер Space default **0**
- torch 2.4 cu124 vs Space ZeroGPU ~2.10 / cu126
- `onnxruntime` CPU vs Space GPU rembg

Уже опровергнуто: slat=12, GitHub MC, «положить vertex_attrs в GLB», «Нормаль как Preview» в Review. Нагрудник остался мылом = **позиции вершин**, не шейдер.

### Как правильно мерить дальше

1. Тот же `ref_gold_armor` на HF Space Preview вблизи груди. Если мыло — контракт модели на этом входе.
2. Наш worker на **example Space** (например `assets/example_image/0.png`, chibi). Если там «как в обзоре» — сеть живая, рыцарь вне контракта.
3. Не крутить extract 512. Не slat=25. Не путать NiRNE (бумага) с YOSO (демо).

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

Код в образе = **HF Space** `e574b11` (тот же `app.py`, rembg u2net, FlexiCubes). Не GitHub HEAD.

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
| H0b3 | normal 768 → 1024 | не Gradio; нормаль H0c острая — не рычаг |
| **H0c** | FlexiCubes extract на GitHub-стеке | +34 verts vs MC; **глаза: всё ещё комок**. Не вердикт сети |

### H0c — FlexiCubes (глаза 2026-08-19)

Smoke: seed 42 / ss=50 / slat=6 / `mesh_extract=flexicubes`.  
Локально: `preview_textures/h0c_armor_flexicubes.glb` + `h0c_armor_flexicubes_normal.png`.

| | H0 MC | H0c FlexiCubes |
|--|--|--|
| Вершины | 155 382 | 155 416 (+34) |
| Файл | 7.46 MB | 7.46 MB |

Нормаль YOSO острая. Меш — **комок глины**, даже перед: Pedrokita. Это не «потолок Hi3DGen».

Мы гнали **GitHub Stable3DGen**, который авторы сами считают хуже [HF Space](https://huggingface.co/spaces/Stable-X/Hi3DGen) ([#36](https://github.com/Stable-X/Stable3DGen/issues/36)):

| | Демо (HF Space) | Наш H0/H0c |
|--|--|--|
| Preprocess | **rembg `u2net`** | **BiRefNet** |
| Extract | оригинальный `flexicube.py` (NVIDIA) | GitHub MC, потом наш патч MaxtirError |
| `to_trimesh` | faces + computed normals | то же; **6ch vertex_attrs не пишутся в GLB** |

H0c не уравнял нас с демо. **H0d** = клон Space, но смотрели **clay GLB без `vertex_attrs`**.  
Демо «шикарно» = вкладка Preview: nvdiffrast `color`=`attrs[:,:3]` + `normal_map`=`attrs[:,3:]`.  
`to_trimesh()` это выкидывает → 7 MB мыло. Next = экспорт 6ch в GLB.

## Зачем нам

T2 ultra: макро ок, микро мыло. Hi3DGen в демо даёт HF geometry. Наш GLB пока не тот пайплайн.

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
- kaolin в image ради FlexiCubes (Space `flexicube.py` без kaolin уже в клоне)
- extract 512 «чтобы было как в обзорах» ([#52](https://github.com/Stable-X/Stable3DGen/issues/52): сотни GB)
- Считать бумажный NiRNE = Space YOSO
- Считать SECourses Ultra App = официальный Hi3DGen

## Следующий шаг после глаз

- Образ = **HF Space** (как T2 = microsoft/TRELLIS.2), не GitHub HEAD.  
- Push `Dockerfile.hi3dgen` → CI → Release **только** `s15aqi9lxs` → smoke seed 42.  
- Не H1. Не slat=25. T2 не патчить.
