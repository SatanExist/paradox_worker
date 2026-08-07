# MV2 spike — Wonder3D (1 photo → 6 views for TRELLIS.2)

> **Goal for AI_MESH:** generate **multi-view RGB** (optionally normals) from **one** user photo, then feed `image_urls[]` into our T2 multi worker (MV1).  
> **Not** the goal of this spike: Wonder3D Instant-NSR / NeuS mesh as product shape (that stays T2).

**Status:** 🔄 **resumed 2026-08-07** (holes gate 🟢 via soft_input v16)  
**Plan refs:** `memory-bank/activeContext.md` § MV2; research synth 2026-08-04.
---

## Scope (pass / fail)

| Must | Skip (this spike) |
|------|-------------------|
| MIT license OK | Era3D (AGPL) |
| 6 ortho-ish RGB views from 1 image | Wonder3D as final GLB exporter |
| Works on RunPod **4090 24GB** (fp16 + xformers) | Always-on serverless yet |
| Armor + chest refs | Production Studio wiring (→ MV3) |
| Views usable as T2 `image_urls` (eyes) | N=4 A/B (→ MV5) |

**Pass:** grid / folder of 6 color views, consistent silhouette, front ≈ input.  
**Fail:** random views / AGPL deps / >24GB only / only normals without RGB.

---

## Upstream facts (README)

| | |
|--|--|
| Repo | [xxlong0/Wonder3D](https://github.com/xxlong0/Wonder3D) |
| License | **MIT** (+ acknowledgement) |
| Branch note | `Wonder3D_Plus` (Wonder3D++) — later if v1 weak |
| Output | 6 views: color + normals; azimuth **0, 45, 90, 180, -90, -45°** (input-view camera system) |
| Resolution | **256×256** generation (input resized) — keep sharp after downsample |
| Camera | assumes **orthographic**-like; front-facing input best |
| VRAM | diffusion OK on 1×GPU fp16; use `1gpu.yaml` / xformers |
| HF pipeline | `flamehaze1115/wonder3d-v1.0` + custom `wonder3d-pipeline` (tested around **diffusers 0.19.3** — pin carefully) |

### Fast path (library / HF) — preferred for spike

```python
from diffusers import DiffusionPipeline
import torch
from PIL import Image

pipe = DiffusionPipeline.from_pretrained(
    "flamehaze1115/wonder3d-v1.0",
    custom_pipeline="flamehaze1115/wonder3d-pipeline",
    torch_dtype=torch.float16,
)
pipe.unet.enable_xformers_memory_efficient_attention()
pipe.to("cuda:0")

cond = Image.open("ref.png").convert("RGB")  # object centered ~80% height
images = pipe(cond, num_inference_steps=20, output_type="pt", guidance_scale=1.0).images
# → multi-view tensor; save RGB tiles for T2
```

### Full path (repo scripts)

```bash
conda create -n wonder3d && conda activate wonder3d
pip install -r requirements.txt
# tiny-cuda-nn optional for Instant-NSR only — skip if we only need MV RGB

accelerate launch --config_file 1gpu.yaml test_mvdiffusion_seq.py \
  --config configs/mvdiffusion-joint-ortho-6views.yaml \
  validation_dataset.root_dir=./example_images \
  validation_dataset.filepaths=['owl.png'] \
  save_dir=./outputs
```

Windows: upstream branch `main-windows`. Prefer **Linux RunPod** for spike (same as W2).

---

## Our pipeline (target after MV2)

```
1 user image (armor / chest)
        │
        ▼
   Wonder3D  →  6× RGB (+normals optional)
        │
        ▼
   T2 multi  image_urls[] + stochastic (MV1)
        │
        ▼
   clay GLB  (rt6 / quality tier)
```

Normals: keep for later (mesh refine / debug); **v1 product path = RGB → T2**.

---

## Inputs (same as Track A / P2)

| File / URL | Role |
|------------|------|
| `preview_textures/ref_gold_armor.png` | character stress |
| TRELLIS `typical_misc_monster_chest.png` | prop / holes stress |
| BiRefNet / rembg cutout | foreground; Wonder3D sensitive to mask quality |

---

## Checklist

- [ ] Confirm MIT + SD base weights OK for EU self-host (note any NC base if bundled)
- [ ] Spike env: RunPod GPU pod (4090) **or** local CUDA — not Windows marathon
- [ ] Pin `diffusers` version that works with `wonder3d-pipeline`
- [ ] HF pipeline: armor → 6 RGB views saved under `preview_textures/mv2_armor/`
- [ ] Same for chest → `preview_textures/mv2_chest/`
- [ ] Eyes: consistency F/L/R/B; no crazy morph
- [ ] Optional: upload views to R2 → `test_req_trellis2.py --image-urls … --multi-image-mode stochastic --quality-tier quality`
- [ ] Document wall time + peak VRAM
- [ ] Stop/terminate pod after smoke
- [ ] Write verdict in `activeContext.md` → GO / NO-GO for MV3

---

## Ops (reuse W2 pattern)

```powershell
# Preferred: create → oneshot → download → terminate (always):
.\.venv\Scripts\python.exe scripts\wonder3d_mv2_pod.py

# Manual / Web Terminal only (still terminate same session):
.\.venv\Scripts\python.exe scripts\wonder3d_mv2_pod.py --no-run
.\.venv\Scripts\python.exe scripts\mvadapter_create_pod.py --terminate <pod_id>
```

Uses public `runpod/pytorch` (no GHCR). Download views via SCP after DONE, or HTTP `python -m http.server 8888` on pod.

---

## Risks / known limits

| Risk | Mitigation |
|------|------------|
| 256² soft / lost ornament | accept for spike; upscale later or Wonder3D++ |
| Front-facing bias | UX: ask/crop front; document |
| Ortho vs perspective T2 | A/B in MV4/MV5 |
| `diffusers` version hell | pin 0.19.x in spike image |
| Instant-NSR deps | **out of scope** for MV2 |
| AGPL Era3D looks sharper | R&D only, not prod |

---

## After MV2

| Next | When |
|------|------|
| **MV3** | wrap 1→N in worker/Pod API |
| **MV4** | wire → T2 multi (rt6 knobs) |
| **MV5** | A/B single vs multi; N=6 vs 4; **chest stress** |
| **P2c** | Meshlib holes — only if MV2/MV4 still leave prop gaps |
| **P3** | Studio tier UX — can parallel product |

---

## Decision log

| Date | Note |
|------|------|
| 2026-08-07 | Holes gate closed (soft); **MV2 resumed** — pod oneshot armor+chest, terminate same session |
| 2026-08-05 | MV2 started; spike doc created; order = MV2 before P2c/P3 |
