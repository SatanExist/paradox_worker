# W3 spike — delight + PBR on native T2 669k (not W2b 80k)

> **Дата:** 2026-08-16  
> **Вход:** `preview_textures/armor_t2_ultra_native_pbr_png.glb` + `ref_gold_armor.png`  
> **Не вход:** clay 80k/200k, MV-Adapter decimate, img2mv  
> **Критерий глаз:** львы/табард вблизи; блик **не** едет вместе с albedo при орбите; Force matte начинает быть заметным

## Зачем

Нативный T2 ultra PBR (4096, 528k V / 669k F) — лучший GLB рыцаря. Дырки:

| Слой | Есть у T2 | Нет |
|------|-----------|-----|
| Albedo | да, с **запечённым светом** фото | delight |
| Metallic / Roughness | да (B≈0.99 почти везде) | разделение ткань vs золото |
| Normal / AO | нет | рельеф орнамента в шейдере |
| Geometry micro | макро ок | львы не скульптура. ~~Hi3DGen~~ 🔴 закрыт 2026-08-20 → остался только T2 на большем разрешении (N1 bust-кроп, `netsTexToolsPlan.md`) |

## Два этажа (не путать)

| Этаж | Что | GPU | Когда |
|------|-----|-----|--------|
| **W3a CPU** | retinex albedo + bump-from-albedo на **тех же UV** | $0 | сразу; `scripts/glb_delight_pbr.py` |
| **W3b MVPainter** | новые виды → `infer_pbr` (basecolor/M/R) → `infer_paint --use_pbr` | **≥40GB**, Blender 4.2 | только если W3a слабо И нужен learned delight |
| ~~**P4.1 Hi3DGen**~~ | другая **форма** (normal-bridge) | отдельный стек | 🔴 **закрыт 2026-08-20** — v1-файнтюн, потолок 256³ |

MVPainter **не** обещает tangent normal map (README: basecolor + metallic + roughness).  
Bump W3a — дешёвый фейк из albedo; не путать со скульптурой Hi3DGen.

## W3a — команда

```powershell
.\.venv\Scripts\python.exe scripts\glb_delight_pbr.py `
  preview_textures\armor_t2_ultra_native_pbr_png.glb `
  -o preview_textures\armor_t2_ultra_native_pbr_delight.glb `
  --bump --dump-maps
```

Сравнить в `scripts/preview_glb_local.html`: PNG atlas vs delight.  
**Pass:** орбита меньше «плоского блика», орнамент читаемее.  
**Fail:** грязь/мыло → не крутить strength; идти в W3b или стоп.

### W3a — вердикт глаз (2026-08-16, Pedrokita) 🟢 PASS

`armor_t2_ultra_native_pbr_delight.glb` vs native PNG. Env on и Env off оба ок; текстуры **убедительнее**.  
W3b MVPainter **не стартовать** как next — W3a закрыл гипотезу «baked light + нет bump».  
Next product: CPU post-step после T2 textured export + IBL в Studio.

## W3b — MVPainter (ещё не запускать pod без глаз W3a)

| | |
|--|--|
| Repo | https://github.com/amap-cvlab/MV-Painter Apache-2.0 |
| VRAM | **≥40GB** — 4090 pool **нет**; dedicated **A6000 48GB** |
| Mesh | TRELLIS.2 GLB → `--geo_rotation -90` |
| Риск | install Blender+custom rasterizer 1–2ч; **669k может OOM** на bake |
| Abort | OOM на rasterize / виды разъехались / львы хуже native PBR → **terminate**, не decimate «чтобы влезло» |

Upstream:

```bash
python infer_multiview.py --input_glb_dir ./data/glbs --input_img_dir ./data/imgs \
  --output_dir ./outputs/armor --geo_rotation -90
python infer_pbr.py --mv_res_dir ./outputs/armor
python infer_paint.py --mv_res_dir ./outputs/armor/mvpainter \
  --output_dir ./results/armor --use_pbr
```

После smoke — **Terminate** pod (не оставлять RUNNING).

## Явно не делать

- MV-Adapter ещё раз на 80k/200k clay
- T2 knobs / img2mv
- Hunyuan Paint (EU)
- decimate 669k «под MVPainter»
- считать Force matte инструментом качества
