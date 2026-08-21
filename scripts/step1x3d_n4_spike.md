# N4 — Step1X-3D (Apache-2.0): второй столб «форма + текстура»

> **Статус:** 🟡 scaffold. Direct3D-S2 закрыт как quality 2026-08-21 (другой персонаж). Это Ф2 приоритет 3.
> Место: `memory-bank/roadmap.md` волна 1, `netParkResearch2026.md` § Step1X-3D.
> Pixal3D / Hi3DGen / Direct3D-S2 как quality **не** переоткрывать.

## Зачем

T2 остаётся prod 1-фото. N2/N3 не дали ни pixel-aligned верность, ни SDF-львов. Step1X-3D — **другой класс**: hybrid VAE-DiT → watertight TSDF, затем опционально SD-XL текстура. Единственный открытый кандидат «форма+текстура» кроме T2 (Apache-2.0, веса + training code).

Демо HF Space **PAUSED** — только своя инфра.

## Две стадии, два гейта

| Стадия | Что | VRAM (офиц.) | Наш первый образ |
|--------|-----|----------------|------------------|
| 1. Geometry `Step1X-3D-Geometry-1300m` | картинка → watertight clay GLB | часть от 27G пика | **да, сразу** |
| 2. Texture `Step1X-3D-Texture` | меш+картинка → SD-XL bake | 27G вместе с geometry | **нет**, пока стадия 1 не PASS |

Официальная таблица: geometry+texture = **27G / 152 с** на 50 шагов. 4090 = 24 GB. Поэтому:

1. Гейт идентичности — **только геометрия**, стадии разгрузить (`del` + `empty_cache`).
2. GPU: 4090 first, A6000/A40/L40S запас. Если 4090 OOM на geometry — не даунгрейдить octree, а 48 GB.
3. Текстуру (pytorch3d, kaolin, Hunyuan baker, nvdiffrast) **не класть в первый образ**.

`octree_resolution` дефолт **384** (не путать с Direct3D SDF 1024). Не крутить до first A/B.

RGBA cutout рыцаря → `preprocess_image` пропускает rembg (alpha). Не звать `bria` (RMBG).

## Стек — отдельный образ

| Что | Step1X-3D geometry | Наш T2 |
|-----|--------------------|--------|
| torch | **2.5.1 cu124** | 2.6.0 cu124 |
| python | **3.10** | 3.11 |
| transformers | **==4.48.0** | >=4.45 |
| native | pymeshlab (reduce/floater) | nvdiffrast / flex_gemm |

Общий слой с T2 / Direct3D-S2 невозможен (другой torch+py). Веса geometry ~1.3B + DINOv2/T5. Том T2 после N2/N3 тесный — если не влезет, свой volume.

Не ставить в geometry-образ: pytorch3d, kaolin, sageattention, deepspeed, wandb, gradio, custom_rasterizer.

## API (стадия 1)

```python
from step1x3d_geometry.models.pipelines.pipeline import Step1X3DGeometryPipeline
pipe = Step1X3DGeometryPipeline.from_pretrained(
    "stepfun-ai/Step1X-3D", subfolder="Step1X-3D-Geometry-1300m"
).to("cuda")
out = pipe(image_path, guidance_scale=7.5, num_inference_steps=50,
           force_remove_background=False)
out.mesh[0].export("out.glb")
```

`.to()` у diffusers-пайплайна **возвращает self** (не как Direct3D-S2).

## Гейт

Same-input, до ручек. Рыцарь `ref_gold_armor_cutout.png`.

**PASS** = это **наш** рыцарь (рога, лев на груди), не архетип. Текстуру тогда открываем вторым образом.
**FAIL** = снова другой персонаж / мыло без идентичности → закрываем как quality, next **TripoSG**.

## Файлы

| Файл | Роль |
|------|------|
| `Dockerfile.step1x3d` | geometry-only: torch 2.5.1 cu124, pymeshlab, rembg. Нет pytorch3d/kaolin |
| `worker_step1x3d.py` | image_url → Geometry-1300m → clay GLB, `force_remove_background=False` |
| `docker/smoke_step1x3d_imports.py` | дерево классов + CPU-импорты, запрет texture-стека |
| `.github/workflows/build-step1x3d.yml` | → `ghcr.io/satanexist/paradox_worker:step1x3d-sha-*` |
| `test_req_step1x3d.py` | async submit + poll |

Пакета `streaming` в первом джобе не было: `step1x3d_geometry/__init__.py` тянет training `data`/`systems`. После clone патчим init на `from . import models`. Плюс `typeguard` (его импортирует `utils/typing.py`).

**Не делать:** texture bake «чтобы красивее»; octree sweep; always-on; переоткрывать N2/N3.
