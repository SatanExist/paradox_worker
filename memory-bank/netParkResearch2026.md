# Исследование: парк 3D-сетей, срез 2026-08-20

> **Зачем:** юзер: «никого не сбрасывать со счетов, нужен последовательный план, подкреплённый исследованиями — форумы, исходники, материалы, оценки».
> **План на основе этого файла:** `roadmap.md` (фазы Ф0–Ф7) + `netParkProgram.md` (гейт приёмки).
> **Правило:** обзоры-рейтинги ≠ доказательство. Ниже помечено, что откуда: бумага / бенчмарк / исходники / форум / SEO-блог.

## Метод

Что считаем доказательством, по убыванию веса:

1. **Исходники и веса** — есть ли чекпойнт, какая лицензия, какой параметр разрешения.
2. **Бенчмарк с людьми и числами** — 3D Arena (Elo, десятки тысяч голосов).
3. **Бумага** — но обязательно смотреть, **с чем** она сравнивается и какого года бейзлайны.
4. **Форумы / issues** — ловят то, чего нет в бумагах: закрытые релизы, OOM, «обещали код и не выложили».
5. **SEO-обзоры** — только как индикатор шума, не как факт.

## 1. Главное: «Hi3DGen у всех лучший» — не подтверждается числами

[**3D Arena**](https://arxiv.org/html/2506.18787v1) (arXiv 2506.18787) — крупнейшая человеческая оценка image-to-3D: **123 243 голоса**, 8 096 юзеров, 19 моделей, парные сравнения, Elo, фрод-контроль 99.75%.

| Место | Модель | Elo | Win rate | Формат |
|-------|--------|-----|----------|--------|
| 2 | TRELLIS-3DGS | 1384 | 80.1% | splat |
| 5 | **TRELLIS** (v1!) | **1306** | 67.0% | mesh |
| 7 | Hunyuan3D-2 | 1298 | 65.5% | mesh |
| 8 | InstantMesh | 1278 | 63.8% | mesh |
| 10 | Unique3D | 1230 | 55.1% | mesh |
| **11** | **Hi3DGen** | **1207** | **47.7%** | mesh |
| 13 | SF3D | 1190 | 48.4% | mesh |
| 17 | TripoSR | 1089 | 31.4% | mesh |

Hi3DGen — **11-й из 19**, win rate ниже 50%, и **на ~100 Elo ниже TRELLIS v1**, не говоря о TRELLIS.2 (её в этой таблице ещё нет, вышла позже).

**Честная поправка в пользу Hi3DGen:** та же бумага измеряет, что текстурированные модели получают **+144.1 Elo** просто за наличие текстуры, а Hi3DGen отдаёт голую геометрию. Авторы это прямо отмечают: Hi3DGen «achieving higher ELO than multiple textured models despite producing untextured meshes». То есть 1207 без текстур — достойно, но «лучший у всех» из этого не следует.

**Отдельно:** [top3d.ai arena](https://www.top3d.ai/arena) (194k голосов, другой пул) ставит TRELLIS.2 на **17-е** место с 912 Elo, а наверху — SaaS (Tripo v3.1, Hitem3D). Две арены противоречат друг другу → ещё один довод, что рейтинги не заменяют same-input A/B на **нашем** входе.

## 2. Откуда взялось «Hi3DGen лучший» — источник найден

| Источник | Что говорит | Чего не говорит |
|----------|-------------|-----------------|
| Бумага Hi3DGen (arXiv 2503.22236) | user study: предпочли Hi3DGen против **Hunyuan3D-2.0, Dora, Clay, Tripo-2.5, Trellis** | все бейзлайны — 2024 / начало 2025. TRELLIS.2 ещё не существовало |
| [SECourses / FurkanGozukara wiki](https://github.com/FurkanGozukara/Stable-Diffusion/wiki/Hi3DGen-Full-Tutorial-With-Ultra-Advanced-App-to-Generate-the-Very-Best-3D-Meshes-from-Static-Images) | «truly, this model is the very best right now» | это туториал-канал, а его «Ultra Advanced App» — **не апстрим** ([issue #50](https://github.com/Stable-X/Stable3DGen/issues/50), у нас уже записано) |
| SEO-обзоры 2026 | «Hi3DGen — best geometric quality», «community testers consistently rate…» | ни одного числа; противоречат 3D Arena |

Полезное из того же туториала (это **факт из бумаги**, не мнение): Hi3DGen учили на **DetailVerse** — синтетическом датасете с богатой детализацией, потому что Objaverse «dominated by objects with simple geometry and plain surfaces». И сеть **лучше работает на входе 1024 px**. Это подтверждает нашу гипотезу про класс входа: сеть заточена на детально-плотные объекты.

## 3. Третье лицо подтвердило нашу диагностику потолка

Бумага [**Direct3D-S2**](https://arxiv.org/html/2505.17412v1) публикует ровно ту абляцию, которую мы не могли прогнать сами — одна модель на четырёх разрешениях {256³, 384³, 512³, 1024³}:

> At lower resolutions 256³ and 384³, the generated meshes exhibit **limited geometric details and misalignment with input images**. At 512³ … **significantly enhanced high-frequency geometric details**. Further increasing to 1024³ yields meshes with **sharper edges**.

Hi3DGen извлекает меш ровно на **256³** — то есть в самой нижней строке этой абляции. Наше «мыло на льве» — это опубликованный, воспроизведённый другими авторами эффект разрешения, а не наша ошибка вызова. Плюс Hi3DGen у них стоит в таблице сравнения **как бейзлайн, который они превосходят** (Trellis / Hunyuan-2.0 / TripoSG / Hi3DGen / Ours).

## 4. Кандидаты: что реально доступно

### 🟢 Direct3D-S2 — главный кандидат на микро-геометрию

| | |
|--|--|
| Исходники | [DreamTechAI/Direct3D-S2](https://github.com/DreamTechAI/Direct3D-S2), **MIT**, 1249 звёзд, релиз v1.1.0 |
| Веса | **выложены:** [`wushuang98/Direct3D-S2`](https://huggingface.co/wushuang98/Direct3D-S2), subfolder `direct3d-s2-v-1-1` (`model_sparse_1024.ckpt`, `model_sparse_512.ckpt`, `model_dense.ckpt`, `model_refiner.ckpt`) |
| Рычаг | `sdf_resolution=1024` — **явный параметр**, 4× к Hi3DGen |
| VRAM | 512 ≈ 10 GB, **1024 ≈ 24 GB** → наш 4090-пул проходит |
| API | `Direct3DS2Pipeline.from_pretrained(...)` → `pipeline(img, sdf_resolution=1024)["mesh"]` — три строки |
| Нюанс из README | 512 использовать **не надо**: это промежуточный шаг модели 1024, качество заметно ниже |
| Минус | голая геометрия без текстур (как Hi3DGen) → текстуру всё равно печём своим путём |

Это единственный найденный кандидат, который бьёт **точно в нашу дырку** (микро-рельеф) и при этом MIT + веса на месте + рычаг разрешения существует.

### 🟢 Step1X-3D — единственный кандидат «форма + текстура» кроме T2

| | |
|--|--|
| Код | [stepfun-ai/Step1X-3D](https://github.com/stepfun-ai/Step1X-3D/), **Apache-2.0**, 882 звезды |
| Веса | [`stepfun-ai/Step1X-3D`](https://huggingface.co/stepfun-ai/Step1X-3D): geometry 1.3B + geometry-label 1.3B + texture 3.5B (всего ~19.6 GB) |
| Архитектура | двухстадийная: hybrid VAE-DiT → watertight TSDF (marching cubes), затем SD-XL texture synthesis с geometric conditioning |
| Открытость | выложены не только веса и inference, но и **training code** + 800K uid датасета |
| Демо | [HF Space](https://huggingface.co/spaces/stepfun-ai/Step1X-3D) — можно валидировать без своей инфры |
| Интересно на будущее | в roadmap апстрима заявлены условия на **multi-view, bounding-box и skeleton** |

Важен тем, что это не «ещё одна геометрия»: он умеет и форму, и текстуру, то есть может быть вторым полноценным столбом рядом с T2, а не подпоркой.

### 🟢 TripoSG — третья ставка на форму

| | |
|--|--|
| Код | [VAST-AI-Research/TripoSG](https://github.com/VAST-AI-Research/TripoSG), **MIT**, 1739 звёзд |
| Веса | [`VAST-AI/TripoSG`](https://huggingface.co/VAST-AI/TripoSG) — 1.5B, rectified flow MoE, VAE на 2048 латентных токенов |
| VRAM | >8 GB — самый дешёвый из трёх |
| Демо | [HF Space](https://huggingface.co/spaces/VAST-AI/TripoSG) + scribble-вариант |
| Заявка авторов | «на уровне Tripo 2.0, превосходит все существующие open-source 3D проекты»; сильная сторона — сложные составные объекты |
| Минус | только форма, текстур нет |

### 🟢 Pixal3D — самый дешёвый для нас в интеграции (SIGGRAPH 2026)

| | |
|--|--|
| Код | [TencentARC/Pixal3D](https://github.com/tencentarc/pixal3d), **MIT**, 2006 звёзд, май 2026 |
| Что делает | pixel-aligned back-projection: поднимает пиксельные фичи в 3D напрямую, а не через attention → «near-reconstruction-level fidelity», геометрия **+ PBR текстуры** |
| Ветка `main` | улучшенная версия **на бэкенде TRELLIS.2** — то есть на нашем же стеке |
| Ветка `paper` | версия статьи на бэкенде Direct3D-S2 |
| Демо | [HF Space](https://huggingface.co/spaces/TencentARC/Pixal3D) |
| Вход | одно или несколько изображений |

**Почему это важно именно нам:** `main` собран поверх TRELLIS.2, а у нас `Dockerfile.trellis2` уже есть и обкатан. Значит интеграция дешевле любой другой новой сети — переиспользуем стек, а не строим с нуля.

**✅ Вопрос EU снят 2026-08-20.** В карточке весов стоит `extra_gated_eu_disallowed: true`, но проверка через API с нашим токеном (`scripts/f2_check_weights.py`) показала `gated=False`, 19 файлов, 7 файлов весов доступны. Флаг неактивен, потому что сам репозиторий не gated. Скачивать можно.

**⚠️ Что реально мешает:** проверить сеть на официальном демо бесплатно нельзя — `extract_glb_api` объявлен на 240 с GPU, а бесплатный ZeroGPU режет одиночный вызов на ~120 с. Геометрия считается (`generate_3d` проходит), а экспорт GLB — нет.

### 🟡 SAM 3D (Meta) — другой класс входа: реальные захламлённые фото

| | |
|--|--|
| Код | [facebookresearch/sam-3d-objects](https://github.com/facebookresearch/sam-3d-objects), 7241 звезда |
| Лицензия | **SAM Materials License** — не OSS, но **разрешает коммерческое использование**; требования: атрибуция, trade controls, патентная оговорка. Для EEA контрагент — Meta Platforms Ireland (то есть EU не исключён, в отличие от Hunyuan) |
| Вход | изображение **+ промпт** (маска / точка / bbox) → полный текстурированный меш |
| Сильная сторона | реальные фото с окклюзией и беспорядком, без мультивью и глубины. Питает «View in Room» в Facebook Marketplace |
| Рядом | **SAM 3D Body** — восстановление человека из одного фото + формат **MHR** (скелет отдельно от мягких тканей) под разрешительной коммерческой лицензией |
| Оговорка | в top3d-арене SAM 3D低 (796 Elo), но та арена оценивает красоту рендера, а не реконструкцию реального объекта — цели разные |

Ценность для парка: это единственный кандидат, заточенный под **фото реального предмета в кадре с мусором**, то есть под то, что реально снимет юзер телефоном. Плюс SAM 3D Body — потенциальный дешёвый путь к анимации гуманоидов.

### 🔴 Sparc3D / Ultra3D / Hitem3D — ловушка, не брать

Красивая бумага про 1024³ и «100× lower Chamfer», но:

- [issue #1](https://github.com/lizhihao6/Sparc3D/issues/1) и [issue #25](https://github.com/lizhihao6/Sparc3D/issues/25): кода и весов **нет и не будет**. На сайте проекта: «Code may be released upon the approval of Math Magic».
- Репозиторий использовался как реклама платного сервиса **Hitem3D**; команда перебрендировалась в **Ultra3D**; HF Space висит в «Preparing Space».
- Сообщество: «closed source: using the repo for advertisement instead of contributing».

Именно этот сервис стоит №2 в top3d-арене — то есть верх той арены нам недоступен by design. Экономия: неделя, которую мы бы потратили на попытку поднять.

### 🔴 Hunyuan3D 2.1 — лицензия подтверждена, EU запрещён

Наш запрет в `postSideBackPlan.md` P4.3 оказался верным, теперь с цитатой. [LICENSE](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/blob/main/LICENSE):

> THIS LICENSE AGREEMENT DOES NOT APPLY IN THE **EUROPEAN UNION, UNITED KINGDOM AND SOUTH KOREA**… “Territory” shall mean the worldwide territory, excluding the territory of the European Union, United Kingdom and South Korea.

Плюс п.5.c прямо запрещает использовать не только модель, но и **Output** за пределами Territory. Для EU-продукта — не рассматриваем даже на пробу, при любом Elo.

### 🟡 Риггинг — новый столб, всё живое

| Проект | Статус |
|--------|--------|
| [UniRig](https://github.com/VAST-AI-Research/UniRig) | SIGGRAPH'25, Tsinghua + Tripo. Чекпойнт скелета на [HF](https://huggingface.co/VAST-AI/UniRig); skinning выкладывали отдельно |
| [**SkinTokens / TokenRig**](https://github.com/VAST-AI-Research/SkinTokens) | преемник UniRig: скелет + skinning одной авторегрессией (Qwen3-0.6B + FSQ-CVAE, GRPO). **+98–133%** к точности skinning, +17–22% к предсказанию костей. Вход = **один меш** |
| [AniGen](https://github.com/VAST-AI-Research/AniGen) | 1 фото → сразу rigged asset. Но генерирует **свою** форму → конкурент T2, не надстройка |

Ставка: **TokenRig на нашем T2-меше**. Не конкурирует с формой, добавляет то, чего в парке нет вообще.

### 🟡 Части — HoloPart / PartCrafter

[HoloPart](https://www.tripo3d.ai/blog/holopart-generate-parts-for-3d-model) (Tripo/VAST, код и веса открыты): part **amodal** segmentation — достраивает части целиком, включая скрытую окклюзией геометрию. Для нас = разделить золото / ткань / кожу как части, а не маски в одном атласе. Побочно лечит «блик едет по всему мешу». Показательно, что top3d-арена уже завела отдельный режим голосования **Segmentation** — значит класс стал мейнстримом.

### 🟡 Быстрый тир — и здесь Hi3DGen оживает

Замер с форума (один пайплайн, один GPU, медианы):

| Сеть | Медиана | Файл | Что даёт |
|------|---------|------|----------|
| **Hi3DGen** | **8.5 с** | ~5 MB | чистая геометрия без текстур |
| TRELLIS v1 | 21.3 с | ~1.5 MB | текстура, «ships as is» |
| TRELLIS.2-4B | 167.5 с | ~35 MB | лучшая текстура, тяжёлые файлы |
| Hunyuan3D-2 | 239.4 с | ~12 MB | баланс формы и текстуры |

Вывод форумного автора, который нам полезен: «8 секунд — это другой продукт, а не более быстрый». Под 10 с юзер сидит и итерирует в диалоге; свыше 3 минут нужны очередь, воркер и уведомление.

## 5. Что это меняет в решениях

1. **Hi3DGen не сбрасываем, а переставляем.** Как путь к герою-персонажу он проигрывает (256³, 11-е место, наш A/B). Как **быстрый черновик геометрии за 8 секунд** он у нас уже развёрнут, оплачен и работает — это готовая заглушка для «быстрого тира», которого в парке нет. Плюс не проверен его настоящий класс входа: реальное фото / камень / плотная детализация при 1024 px.
2. **Микро-геометрия уходит к Direct3D-S2**, потому что там есть `sdf_resolution=1024`, MIT и веса. Это тот самый «рычаг разрешения», которого у Hi3DGen нет, и наша аналогия с разгоном T2 наконец получает адресата.
3. **Sparc3D и Hunyuan вычёркиваем по фактам**, а не по вкусу: у первого нет весов, у второго EU вне лицензии.
4. **Риггинг и части** — единственные направления, где мы получаем не «ещё на 10% острее меш», а новую возможность продукта.
