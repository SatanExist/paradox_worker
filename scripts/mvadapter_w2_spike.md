# W2 spike — MV-Adapter image→texture (knight)

Manual GPU checklist. Success = `*_shaded.glb` sharper than `model-armor-wow.glb`.

**W2 result (2026-07-28):** ✅ sharper albedo vs cascade; ❌ Meshy wow (holes + blur). See `memory-bank/textureWowPlan.md` § W2b.

## Inputs (local)

| File | Role |
|------|------|
| `preview_textures/ref_gold_armor.png` | reference image (1 photo, same as Meshy A/B) |
| `model-armor-wow.glb` | mesh geometry stand-in (or clay GLB when ready) |
| `knight_i2tex_shaded.glb` | W2 MV-Adapter output (local after download) |
| Meshy knight screenshots | visual ceiling |

Upload image to litterbox/R2 if worker needs URL; for pod SSH use local paths.

## License

MV-Adapter: **Apache-2.0** (EU OK). Verify any bundled SDXL base weights separately.

## Entry command (upstream)

```bash
# On pod, after clone https://github.com/huanngzh/MV-Adapter + deps + checkpoints:
python -m scripts.texture_i2tex \
  --image /data/ref_gold_armor.png \
  --mesh /data/model-armor-wow.glb \
  --save_dir /data/outputs \
  --save_name knight_i2tex \
  --remove_bg

# W2b (recommended next):
#   ... --preprocess_mesh

# Low VRAM:
#   ... --variant sd21

# Output: /data/outputs/knight_i2tex_shaded.glb
```

Also useful: `scripts.inference_ig2mv_sdxl` (image+geometry → multi-view PNG) before full texture.

**Mesh orientation:** upstream requires demo-consistent orientation; TRELLIS GLB may need rotation (document what works).

## Автоматика (локально)

```powershell
# Список pod
.\.venv\Scripts\python.exe scripts\mvadapter_create_pod.py --list

# Поднять 4090 (платно!) — fallback A6000
.\.venv\Scripts\python.exe scripts\mvadapter_create_pod.py --create --name paradox-mvadapter-w2

# Zip для Jupyter upload (~13 MB): data/ + bootstrap
powershell -File scripts\pack_mvadapter_upload.ps1
# → mvadapter_w2_upload.zip
```

**Active pod (2026-07-28 W2b):** `mqsh4ke3xez0vz` (`paradox-mvadapter-w2b`, A6000, $0.53/hr).  
Assets zip: `https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/mvadapter_w2_upload.zip`  
Mesh: `model-armor-clay_repaired.glb` (seed 42). Output: `knight_i2tex_v2_shaded.glb`

**Web Terminal one-liner (Connect → Start Web Terminal):**
```bash
cd /workspace && wget -q -O /tmp/w2.zip https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/mvadapter_w2_upload.zip && unzip -o /tmp/w2.zip -d /workspace && bash /workspace/mvadapter_w2_oneshot.sh
```

**Download GLB (pod running):** gateway SSH has **no SCP**. On pod:
```bash
cd /workspace/outputs && python3 -m http.server 8888
```
Browser: `https://<pod-id>-8888.proxy.runpod.net/knight_i2tex_v2_shaded.glb`

Or Direct TCP SCP (port from Connect UI): `scp -P <port> -i ~/.ssh/id_ed25519 root@<ip>:/workspace/outputs/knight_i2tex_v2_shaded.glb .`

**Pinned stack:** torch 2.4.1+cu124, diffusers 0.31.0, cvcuda-cu12, gltflib, pymeshlab 2022.2.post3.

После smoke — **Stop** pod (keep volume) or **Terminate** (wipes data).

## Pass / fail

| Pass | Fail → next |
|------|-------------|
| Clear sharpness win on gold/steel vs cascade bake | Try `--preprocess_mesh`; mesh repair; PNG export; MVPainter ≥40GB |
| Mesh still mid (expected) | Shape = T2 problem; check holes on **clay** before blaming texture |
| Holes at joints | Decision tree: geometry (T2) vs UV projection — see textureWowPlan § Дыры |

## After first green smoke

- `worker_mvadapter.py` + Serverless endpoint `paradox-mvadapter`
- Contract: `mesh_url` + `image_url` → `model_url` (same spirit as texture v1)
- Studio later (not T1c paint)
