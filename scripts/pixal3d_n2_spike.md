# N2 — Pixal3D (SIGGRAPH 2026, MIT): первая сеть волны интеграции

> **Статус:** 🟡 код готов, ждёт пуша → CI → volume → эндпоинт.
> Место в плане: `memory-bank/roadmap.md` Ф2, приоритет 1.
> Числа и лицензия: `memory-bank/netParkResearch2026.md`.

## Почему именно она первая

Не потому что «новая и хвалят», а потому что **дешевле всех в интеграции**: стоит на бэкенде TRELLIS.2, а наш `Dockerfile.trellis2` уже собирает весь тяжёлый нативный стек (nvdiffrast, nvdiffrec, CuMesh + cubvh, FlexGEMM, o-voxel). В новом образе **не компилируется ничего нового**.

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
| `docker/smoke_pixal3d_imports.py` | build-time проверка: скомпилированные .so + **их** `Pixal3DImageTo3DPipeline` и `DinoV3ProjFeatureExtractor` + MoGe |
| `.github/workflows/build-pixal3d.yml` | → `ghcr.io/satanexist/paradox_worker:pixal3d-sha-*` |
| `test_req_pixal3d.py` | async submit + poll + сохранение GLB под Review |

Ветки апстрима: `master` (версия на TRELLIS.2, её и берём), `paper` (на Direct3D-S2), `pr-12`. Ветки `main`, о которой пишет README, **не существует** — в Dockerfile зашит `master` через `ARG PIXAL3D_REF`.

## Ops-чеклист (не выполнено)

1. Коммит + пуш → CI собирает образ (нужно разрешение юзера).
2. Volume: 22.4 GB весов. Свободное место есть на существующих 80 GB в EU-RO-1 — новый volume заводить не нужно, если он не забит.
3. Эндпоинт `workersMin=0`, GPU 24 GB+. `PIXAL3D_LOW_VRAM=1` если 24 GB не хватит: модели staging'ом по стадиям, пик = одна flow-модель + один DinoV3 вместо ~18 GB сразу.
4. Первый прогон: `resolution=1024`, `--manual-fov` не задавать (проверить MoGe).

## Гейт приёмки (по `netParkProgram.md`)

Same-input A/B на рыцаре `ref_gold_armor.png` и сундуке против T2 ultra, **до** любых ручек. Сравнивать надо не плотность сетки, а **верность рефу**: заявка Pixal3D — pixel-aligned точность, а не больше вокселей. Два прогона не лучше → закрываем и пишем условие возврата.
