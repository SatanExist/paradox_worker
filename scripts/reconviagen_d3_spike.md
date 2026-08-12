# D3 spike — ReconViaGen v0.5 on RunPod — ABORT

> **Статус:** 🔴 **ABORT** 2026-08-11 (Pedrokita)  
> **Урок:** не голый pod+setup.sh → **`Dockerfile.reconviagen`**  
> **Мастер:** `memory-bank/reconViaGenMvRefiner.md`  
> **Pod:** `7xlrv84slybehj` terminated

## Что выяснили (полезно для D4)

- HF eyes всё ещё 🟢 («ОГО») — метод ок, install path нет
- Upstream setup.sh ломается на RunPod: ToS, sudo, hub pin, o-voxel path, torch↔o_voxel↔flex_gemm/triton
- SSH с этой машины нестабилен → Web Terminal pain
- Torch pin: `2.4.0+cu121`; o-voxel `--no-deps`; flex_gemm хочет `triton>=3.2` — конфликт с torch 2.4 bundle

## Next

D4: Dockerfile на базе паттернов `Dockerfile.trellis2` + ReconViaGen v0.5 hybrid pipeline.

## Цель

Свой pod → GLB Armor front+back с `adaptive_guidance_weight`, без HF ZeroGPU.

## Команды

```powershell
.\.venv\Scripts\python.exe scripts\reconviagen_d3_pod.py
# debug / long install:
.\.venv\Scripts\python.exe scripts\reconviagen_d3_pod.py --keep
.\.venv\Scripts\python.exe scripts\reconviagen_d3_pod.py --no-run
```

## Артефакты

| | |
|--|--|
| Oneshot | `scripts/reconviagen_d3_oneshot.sh` |
| Infer | `scripts/reconviagen_infer.py` |
| Pod runner | `scripts/reconviagen_d3_pod.py` |
| Out GLB | `preview_textures/reconviagen/r_pod_armor_fb.glb` |
| Volume | `netu72a8j2` (paradox-trellis2) → HF cache |

## Критерий

Глаза vs Armor ultra + vs naive pair F+B. Better → D4 Dockerfile/worker.
