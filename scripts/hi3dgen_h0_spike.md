# H0 spike — Hi3DGen (1-photo high-fidelity geometry)

> **Статус:** 🟡 **ПЕРЕСТАВЛЕН 2026-08-20 (не закрыт).** Как путь к качеству — soft-NO-GO: файнтюн **TRELLIS v1** с extract 256³, same-image на официальном Space дал то же мыло, в 3D Arena **11-е место из 19** (Elo 1207, win 47.7%). Как **быстрый тир геометрии ≈8.5 с** — оставляем в парке, воркер уже развёрнут. Условия возврата к качеству: `netParkProgram.md` шаг 6. Исследование с числами: `netParkResearch2026.md`.  
> **План:** `memory-bank/netsTexToolsPlan.md`  
> **Не путать с** TRELLIS.2 worker (`worker_trellis2.py`). Это отдельный стек.

## Вердикт H0 (2026-08-20) — почему закрыли

Вопрос был: «обзоры обещали, что Hi3DGen круче Trellis2 — почему у нас мыло, тот ли это Hi3DGen».

**Тот.** Образ = клон Space по пину `e574b11` (CI падает при несовпадении SHA), веса `trellis-normal-v0-1`, тот же `generate_3d`.

| Проверка 2026-08-20 | Результат |
|---------------------|-----------|
| **Same-image на официальном Space** (`ref_gold_armor_bust.png`, дефолты, YOSO) | 407k verts / 19.5 MB, **то же мыло** на льве и кромках. Наш YOSO: 408k / 21.4 MB, NiRNE: 21.2 MB |
| Есть ли более свежий меш-чекпойнт у Stable-X | **Нет.** `trellis-normal-v0-1` (2025-03) — единственный, и он наш |
| Куда ушли авторы | `trellis-vggt-v0-1` (09.2025) → **`trellis-vggt-v0-2`** (10.2025), lib `reconviagen`. Мы уже на v0-2 (`worker_reconviagen.py`) |

**Разгадка «круче Trellis2»:** бумага (arXiv 2503.22236, 03.2025) сравнивает себя с **Trellis-RGB / Hunyuan / Dora**, т.е. с TRELLIS **v1** на RGB-входе. Это «тюнингованный v1 > базовый v1», а не «> TRELLIS.2». Мы читали обзоры весны 2025 как обещание против v2.

**Почему приём с T2 не переносится:** T2 разогнали переключением `pipeline_type` (`512 / 1024 / 1024_cascade / 1536_cascade`, `worker_trellis2.py:43`). У Hi3DGen такой ручки нет вообще: occupancy 16³ → SLAT 64³ → extract 256³, без каскада; 512 ≈ 520 GB VRAM ([#52](https://github.com/Stable-X/Stable3DGen/issues/52)). Bust-кроп (7.4 → 21 MB) и NiRNE были последние два честных рычага — оба отработаны.

**Почему в шоукейсах иначе:** (1) класс входа — normal bridging живёт на высокочастотной нормали (камень, статуи, ткань, механика, реальные фото); гладкое отражающее золото не даёт рельефа, мостить нечего; (2) подача — PBR/свет/подставки, а Hi3DGen отдаёт голую геометрию.

**Итог:** Hi3DGen не default и не апгрейд над T2. Остаётся в ящике под фото/статуи. За ультра-геометрией персонажа — T2 `1536_cascade`; за следующим шагом — RVG на реальных ракурсах.

### Внешняя проверка (2026-08-20, `netParkResearch2026.md`)

| Источник | Что даёт |
|----------|----------|
| [3D Arena](https://arxiv.org/html/2506.18787v1), 123k голосов, 19 моделей | Hi3DGen **11-е**, Elo 1207, win 47.7% — **ниже TRELLIS v1** (1306). Поправка в его пользу: текстурированные получают +144 Elo просто за текстуру, а он без текстур |
| [Direct3D-S2](https://arxiv.org/html/2505.17412v1) абляция разрешений | 256³/384³ = «limited geometric details and misalignment», 512³ = «significantly enhanced high-frequency», 1024³ = «sharper edges». Hi3DGen сидит на **256³** → наше мыло опубликовано третьей стороной как эффект разрешения |
| Та же бумага, таблица сравнения | Hi3DGen стоит **бейзлайном, который превосходят** |
| Миф «лучший» | (1) свой user study против Hunyuan-2.0 / Dora / Clay / Tripo-2.5 / Trellis — все 2024–нач.2025; (2) [SECourses туториал](https://github.com/FurkanGozukara/Stable-Diffusion/wiki/Hi3DGen-Full-Tutorial-With-Ultra-Advanced-App-to-Generate-the-Very-Best-3D-Meshes-from-Static-Images) «the very best right now» — а его Ultra App **не апстрим** ([#50](https://github.com/Stable-X/Stable3DGen/issues/50)) |
| Замер скорости (форум) | Hi3DGen **8.5 с** / ~5 MB голой геометрии против TRELLIS.2 **167 с** / ~35 MB → его настоящая ниша у нас = быстрый тир |
| Непроверенный класс входа | DetailVerse + «works best with 1024-pixel»: сеть заточена под детально-плотные объекты. Реальное фото / камень мы **не гоняли** — это и есть условие возврата |

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
