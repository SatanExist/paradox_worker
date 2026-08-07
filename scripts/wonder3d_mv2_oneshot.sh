#!/usr/bin/env bash
# MV2 oneshot: install Wonder3D HF deps + run armor + chest multi-view.
set -euo pipefail
cd /workspace

export HF_HOME="${HF_HOME:-/workspace/hf_cache}"
export PYTHONUNBUFFERED=1
mkdir -p /workspace/data /workspace/outputs/mv2_armor /workspace/outputs/mv2_chest /workspace/scripts "$HF_HOME"

echo "=== MV2 Wonder3D oneshot ==="
nvidia-smi -L || true

# Prefer system python on RunPod pytorch images
PY=python3
command -v "$PY" >/dev/null || PY=python

$PY -m pip install -q --upgrade pip
# Pin near upstream Wonder3D HF demo (diffusers~0.19); newer often breaks custom_pipeline.
$PY -m pip install -q \
  "torch" "torchvision" \
  "diffusers==0.19.3" "transformers==4.30.2" "accelerate==0.20.3" \
  "xformers" "einops" "omegaconf" "opencv-python-headless" \
  "huggingface_hub" "safetensors" "Pillow" || true

# If xformers wheel missing for this torch, continue without it.
$PY - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
if torch.cuda.is_available():
    print("gpu", torch.cuda.get_device_name(0))
PY

# Expect data uploaded next to this script or already in /workspace/data
ARMOR=/workspace/data/ref_gold_armor.png
CHEST=/workspace/data/ref_chest.png
if [[ ! -f "$ARMOR" ]]; then
  echo "missing $ARMOR — place refs in /workspace/data"
  exit 1
fi
if [[ ! -f "$CHEST" ]]; then
  # fallback: download Microsoft TRELLIS chest
  curl -fsSL -o "$CHEST" \
    "https://raw.githubusercontent.com/microsoft/TRELLIS/main/assets/example_image/typical_misc_monster_chest.png" || true
fi

INFER=/workspace/scripts/wonder3d_mv2_infer.py
if [[ ! -f "$INFER" ]]; then
  echo "missing $INFER"
  exit 1
fi

echo "=== armor ==="
$PY "$INFER" --image "$ARMOR" --out-dir /workspace/outputs/mv2_armor --stem armor --steps 20

echo "=== chest ==="
$PY "$INFER" --image "$CHEST" --out-dir /workspace/outputs/mv2_chest --stem chest --steps 20

echo "=== DONE ==="
ls -la /workspace/outputs/mv2_armor /workspace/outputs/mv2_chest
echo "Serve: cd /workspace/outputs && python3 -m http.server 8888"
