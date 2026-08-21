# N2 — Pixal3D (SIGGRAPH 2026, MIT): первая сеть волны интеграции

> **Статус:** 🔴 **закрыт как quality 2026-08-21** (глаза: «ниже среднего»). Эндпоинт idle (`workersMin=0`), не переоткрывать ради львов.
> Место в плане: `memory-bank/roadmap.md` Ф2. Следующий кандидат — **Direct3D-S2**.
> Числа и лицензия: `memory-bank/netParkResearch2026.md`.

## Почему именно она первая

Не потому что «новая и хвалят», а потому что **дешевле всех в интеграции**: стоит на бэкенде TRELLIS.2, а наш `Dockerfile.trellis2` уже собирает весь тяжёлый нативный стек (nvdiffrast, nvdiffrec, CuMesh + cubvh, FlexGEMM, o-voxel). Одна новая компиляция всё же нашлась: **NATTEN 0.21.0** — её тянет апсемплер NAF внутри кондиционера (`proj_in_channels=2048`). Готового колеса под наш `cp311 + torch 2.6 + cu124` нет (у авторов есть только `cp310`).

## Что выяснили без единой секунды GPU

| Проверка | Результат |
|----------|-----------|
| Доступ к весам | `gated=False`, 19 файлов, **22.4 GB** (`scripts/f2_check_weights.py`). Флаг `extra_gated_eu_disallowed` в карточке неактивен, потому что репо не gated |
| `pipeline.json` | `Trellis2ImageTo3DPipeline`, те же ступени ss → shape slat → tex slat, `default_pipeline_type: 1536_cascade` |
| Кондишн-модели | `DinoV3FeatureExtractor` (`facebook/dinov3-vitl16…`) и BiRefNet-rembg — **ровно наша пара**, включая ту же проблему gated-репо |
| **Дельта архитектуры** | у нас `SLatFlowModel`; у них **`ElasticSLatFlowModel`** с `image_attn_mode: "proj"` и `proj_in_channels: 2048`. Остальные аргументы совпадают до последнего |
| Вывод по дельте | стоковый TRELLIS.2 такой класс не построит → **шорткат «подменить `TRELLIS2_MODEL_ID` на существующем эндпоинте» отменён**, нужен их форк |
| Демо на HF | генерация проходит (~87 с на 1024), но `extract_glb_api` объявлен на 240 с > лимита бесплатного ZeroGPU → GLB бесплатно не получить |

Отсюда и решение идти сразу на свою инфру, а не покупать HF PRO.

## Чем отличается от нашего T2 по входу

Pixal3D нужен **угол зрения камеры**: он оценивается MoGe-2 (`Ruicheng/moge-2-vitl`) по уже обесфоненной картинке, либо задаётся руками через `manual_fov` (радианы). Это часть pixel-aligned схемы: фичи пикселей проецируются в 3D по реальной геометрии камеры. MoGe грузится, отдаёт intrinsics и сразу выгружается из VRAM — так сделано и у апстрима.

Апстрим использует **не-gated зеркало** DINOv3 `camenduru/dinov3-vitl16-pretrain-lvd1689m` — нам это удобно, отдельного обхода gating не требуется.

## Файлы

| Файл | Роль |
|------|------|
| `Dockerfile.pixal3d` | образ: T2-стек без изменений + клон `TencentARC/Pixal3D@master` + MoGe. `PYTHONPATH` включает и Pixal3D, и TRELLIS.2 (o-voxel живёт в дереве T2) |
| `worker_pixal3d.py` | handler: image_url → preprocess → камера (MoGe / `manual_fov`) → `pipeline.run(pipeline_type=f"{resolution}_cascade")` → `o_voxel.postprocess.to_glb` → volume + R2/base64 |
| `docker/smoke_pixal3d_imports.py` | build-time проверка: скомпилированные .so + MoGe + наличие **их** `Pixal3DImageTo3DPipeline` и `DinoV3ProjFeatureExtractor` в дереве |
| `.github/workflows/build-pixal3d.yml` | → `ghcr.io/satanexist/paradox_worker:pixal3d-sha-*` |
| `test_req_pixal3d.py` | async submit + poll + сохранение GLB под Review |

Ветки апстрима: `master` (версия на TRELLIS.2, её и берём), `paper` (на Direct3D-S2), `pr-12`. Ветки `main`, о которой пишет README, **не существует** — в Dockerfile зашит `master` через `ARG PIXAL3D_REF`.

### Две мины в сборке (найдены прогонами CI 2026-08-20)

1. **`huggingface_hub` 1.x.** Голый `pip install huggingface_hub` теперь резолвится в ветку 1.x, а `transformers` её не принимает и падает на импорте. Пин `>=0.34,<1.0`, и **повторно последним шагом** — MoGe/diffusers тянут обратно. Подробности и следствия для остальных образов: `memory-bank/techContext.md`.
2. **Два gated-репозитория в их `pipeline.json`.** `image_cond_model` = `facebook/dinov3-*`, `rembg_model` = `briaai/RMBG-2.0` (ещё и CC BY-NC). Первый прогон упал на втором из них. Подмена ровно та же, что в `worker_trellis2.py`: локальный DINOv3 с тома + `ZhengPeng7/BiRefNet`. Отличие от T2 в мелочи: мы качаем в HF-кэш, а не в `local_dir`, поэтому `pipeline.json` приходит симлинком на blob — перед записью его надо **отвязать**, иначе портится общий blob.
3. **triton требует GPU-драйвер на импорте.** `pixal3d.pipelines` лениво тянет `flex_gemm` → triton autotune → `RuntimeError: 0 active drivers`. На CI-раннере GPU нет, поэтому **импортировать пайплайн в билд-тайме нельзя в принципе**. Смоук проверяет наличие классов по дереву исходников; настоящий импорт впервые случится на RunPod.
4. **`natten`.** Прогон 2 (`e46e904f…-e1`) прошёл gated-репы и упал на `ModuleNotFoundError: No module named 'natten'`. Это не DiT, а **NAF** (`valeoai/NAF`, `torch.hub.load`) — без него `proj_in_channels` остаётся 1024, а чекпойнт обучен на 2048. Апстрим: `pip install natten==0.21.0` из исходников. Официальные колёса 0.21.x — torch 2.7+; колесо авторов — `cp310`. Собираем `NATTEN_CUDA_ARCH=8.6;8.9` (карты эндпоинта).

## Ops-чеклист

1. ✅ Образ собран: `ghcr.io/satanexist/paradox_worker:pixal3d-sha-376f791` (третья попытка CI, две мины выше).
2. ✅ Volume: свой заводить не пришлось. Веса легли в HF-кэш на `paradox-trellis2` (`netu72a8j2`): том вырос 28.1 → 50.5 GiB из 80. Там же общий DINOv3, который сеть переиспользует. **Свободно ~29 GiB — второй копии весов уже не влезет**, поэтому качаем в кэш, а не в `local_dir`.
3. ✅ Эндпоинт `paradox-pixal3d` = `1k4hyr6cs9nxr0`, template `pwcli28kc9`, `workersMin=0`, GPU 4090 → A6000 / A40 / L40S (24 GB в приоритете, 48 GB как запас под 1536). Создаётся скриптом `scripts/pixal3d_create_endpoint.py` (REST хочет полные имена GPU, а не группы `ADA_24`).
4. Прогон 1 (`22216b80…-e2`): веса скачались, пайплайн начал грузиться, упал на gated RMBG — см. мину 2.
5. Образ `pixal3d-sha-60ecb7c` (подмена gated-реп) → прогон 2 (`e46e904f…-e1`, ~7 мин) упал на `natten` — см. мину 4. `PIXAL3D_LOW_VRAM=1` в запасе, если 24 GB не хватит.

## Гейт приёмки (по `netParkProgram.md`)

Same-input A/B на рыцаре `ref_gold_armor.png` и сундуке против T2 ultra, **до** любых ручек. Сравнивать надо не плотность сетки, а **верность рефу**: заявка Pixal3D — pixel-aligned точность, а не больше вокселей. Два прогона не лучше → закрываем и пишем условие возврата.

## Вердикт 2026-08-21 — 🔴 закрыт как quality

Не апгрейд над T2 Realistic. Это тот же класс TRELLIS.2 + proj-кондиционер: больше треугольников не сделали львов скульптурой.

| Прогон | Джоб | Итог |
|--------|------|------|
| 1024 + `LOW_VRAM` на 4090 | `1f87f4c1…-e1` | COMPLETED. 755k verts / `n2_pixal3d_knight_1024.glb`. Глаза: «рыцарь есть, качество слабое» |
| 1536 на 48 GB only | `938ba7c9…-e1` | CANCELLED. В EU-RO-1 (том `netu72a8j2`) 48 GB = None; A40 High только в EU-SE-1 |
| 1536 + `LOW_VRAM` на 4090 | `2008e6a6…-e1` | COMPLETED. 863k verts / 989k faces / 42.4 MB / ~4 мин GPU. `n2_pixal3d_knight_1536.glb` |

**Глаза на 1536 (юзер):** ниже среднего. Львы/палды мыло, золото пластик, кромка меча рваная, на спине дыра/инверт, на шлеме чёрная крышка. Плотность сетки выше T2 — рельеф нет.

**Почему так:** заявка сети — pixel-aligned back-projection, не 1024³ SDF. Каскад 1536 на нашем железе получен; честный 48 GB в этом зале недоступен и уже не нужен — 1536 отработал, качество не выросло.

**Условие возврата:** новый чекпойнт не на ElasticSLat/TRELLIS.2 **или** непроверенный класс входа (реальное фото / плотный орнамент), не «ещё раз 1536 на A6000». Сундук не гоняем — два прогона рыцаря already worse.

**Не делать:** крутить seed / FOV / texture_size; держать воркер always-on; ждать 48 GB в EU-RO-1.

Образ `pixal3d-sha-7d6e18e`, endpoint `1k4hyr6cs9nxr0`. Дальше парк: Direct3D-S2 (`sdf_resolution=1024`), отдельный образ — стек конфликтует с T2.
