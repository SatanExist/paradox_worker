# N3 — Direct3D-S2 (MIT): микро-геометрия, `sdf_resolution=1024`

> **Статус:** 🟡 scaffold. Ждём commit+push → CI образ → endpoint.
> Место в плане: `memory-bank/roadmap.md` Ф2 приоритет 2, `netParkProgram.md` шаг 2.
> Pixal3D как quality закрыт 2026-08-21 — это **другой класс** (sparse SDF 1024³), не ещё один TRELLIS.2.

## Зачем

Hi3DGen сидит на extract 256³. T2/Pixal3D — та же линейка sparse latent, не воксельный SDF. У Direct3D-S2 есть явный рычаг **`sdf_resolution=1024`** (~24 GB → 4090), и их же абляция публикует: 256³ = limited details, 1024³ = sharper edges. Это дырка продукта (львы).

## Стек — отдельный образ, общий том

| Что | Direct3D-S2 | Наш T2 / Pixal3D |
|-----|-------------|------------------|
| torch | **2.5.1 cu121** | 2.6.0 cu124 |
| python | **3.10** | 3.11 |
| transformers | **==4.40.2** | >=4.45 |
| triton | **==3.1.0** | >=3.2.0 |
| sparse conv | **torchsparse** | flex_gemm |

Общий Docker-слой невозможен. Веса (~7.9 GB, `gated=False`, `wushuang98/Direct3D-S2` / `direct3d-s2-v-1-1`) **влезают на том T2** `netu72a8j2` (~29 GiB свободно после Pixal3D). Свой volume не заводим, пока не упрёмся в место. HF-кэш раздельный по repo id.

Апстрим-Dockerfile глотает падение torchsparse (`|| echo failed`). Мы **нет**: без него сеть не сеть. Архитектуры только `8.6;8.9` (4090 / A6000 / A40 / L40S). Тег `v2.1.0` у mit-han-lab **не существует** (последний релиз `v2.0.0`) — клонируем `main`, как авторы.

`flash-attn` из `requirements.txt` не собираем: `SPARSE_ATTN_BACKEND=xformers`. Их sparse-модуль это умеет.

BiRefNet — уже `ZhengPeng7/BiRefNet` (не gated RMBG). Наш cutout рыцаря RGBA → rembg пропускается.

## API (три строки апстрима)

```python
pipeline = Direct3DS2Pipeline.from_pretrained(
    "wushuang98/Direct3D-S2", subfolder="direct3d-s2-v-1-1"
).to("cuda:0")
mesh = pipeline(image, sdf_resolution=1024, remove_interior=True, remesh=False)["mesh"]
mesh.export("out.glb")
```

Текстур нет — сравниваем **форму** (львы, кромки) с T2 Realistic, не PBR.

## Файлы

| Файл | Роль |
|------|------|
| `Dockerfile.direct3ds2` | cuda 12.1 devel + py3.10 + torch 2.5.1 cu121 + torchsparse + voxelize (`udf_ext`) |
| `worker_direct3ds2.py` | image_url → pipeline(sdf=1024) → GLB volume + R2 |
| `docker/smoke_direct3ds2_imports.py` | torchsparse `.so`, `udf_ext`, класс пайплайна |
| `.github/workflows/build-direct3ds2.yml` | `ghcr.io/satanexist/paradox_worker:direct3ds2-sha-*` |
| `test_req_direct3ds2.py` | async submit + poll |
| `scripts/direct3ds2_create_endpoint.py` | template + endpoint, `workersMin=0` |

## Ops-чеклист

1. ⏳ commit + push → CI (запас 2–3 итерации: torchsparse капризный)
2. ⏳ `scripts/direct3ds2_create_endpoint.py --apply` после зелёного тега
3. ⏳ A/B рыцарь `ref_gold_armor_cutout.png`, **сразу 1024**, без ручек. Не даунгрейдить в 512 «чтобы влезло»
4. Глаза: лев на груди / палды vs `armor_t2_v17_realistic.png.glb`

## Гейт

Same-input, до любых knobs. Два прогона same/worse T2 → закрываем. Условие возврата пишем тогда.

**Не делать:** 512 как «честный» прогон; seed-sweep; ждать 48 GB; общий образ с T2.
