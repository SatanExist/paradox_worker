#!/usr/bin/env bash
# D3: ReconViaGen v0.5 pod oneshot — clone + conda setup + Armor F+B → GLB.
# Expects /workspace/data/{front,back}.png and scripts/reconviagen_infer.py uploaded.
set -euo pipefail

LOG=/workspace/logs/d3_reconviagen.log
mkdir -p /workspace/logs /workspace/data /workspace/outputs /workspace/hf_cache
exec > >(tee -a "$LOG") 2>&1

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

export HF_HOME="${HF_HOME:-/runpod-volume/huggingface_cache}"
# Fallback if network volume not mounted
if [[ ! -d /runpod-volume ]]; then
  export HF_HOME=/workspace/hf_cache
fi
mkdir -p "$HF_HOME"
export PYTHONUNBUFFERED=1
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-8.9;8.6;8.0}"
export DEBIAN_FRONTEND=noninteractive

log "=== D3 ReconViaGen oneshot START ==="
log "HF_HOME=$HF_HOME"
nvidia-smi -L || true
nvidia-smi || true

(
  while true; do
    gpu="$(nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null || echo n/a)"
    echo "[HB $(date -u +%H:%M:%SZ)] load=$(cut -d' ' -f1-3 /proc/loadavg) gpu=$gpu"
    sleep 30
  done
) &
HB_PID=$!
trap 'kill $HB_PID 2>/dev/null || true' EXIT

# --- Miniconda (upstream wants py3.10 + CUDA 12.1) ---
CONDA_ROOT=/workspace/miniconda3
if [[ ! -x "$CONDA_ROOT/bin/conda" ]]; then
  log "=== install Miniconda ==="
  curl -fsSL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -o /tmp/miniconda.sh
  bash /tmp/miniconda.sh -b -p "$CONDA_ROOT"
fi
# shellcheck disable=SC1091
source "$CONDA_ROOT/etc/profile.d/conda.sh"

# Anaconda ToS (required for non-interactive conda create since 2024+)
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main || true
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r || true

ENV_NAME=reconviagen_v05
PY=python
if ! conda env list | grep -q "^${ENV_NAME} "; then
  log "=== create conda env $ENV_NAME (py3.10 + torch 2.4 cu121) ==="
  conda create -y -n "$ENV_NAME" python=3.10
  conda activate "$ENV_NAME"
  # Prefer pip torch wheels — conda torch often breaks with iJIT_NotifyEvent on RunPod.
  pip install --upgrade pip
  pip install torch==2.4.0 torchvision==0.19.0 --index-url https://download.pytorch.org/whl/cu121
else
  log "=== reuse conda env $ENV_NAME ==="
  conda activate "$ENV_NAME"
fi

# Heal known conda-torch + Intel ITT breakage if present.
if ! python -c "import torch" 2>/dev/null; then
  log "=== torch import broken — reinstall via pip cu121 + intel-openmp ==="
  conda install -y -c conda-forge intel-openmp || true
  pip install --force-reinstall torch==2.4.0 torchvision==0.19.0 --index-url https://download.pytorch.org/whl/cu121
fi

log "python=$(python -V) torch=$(python -c 'import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())')"
PY=python

# --- Clone ReconViaGen v0.5 ---
RVG=/workspace/ReconViaGen
if [[ ! -d "$RVG/.git" ]]; then
  log "=== clone ReconViaGen v0.5 (recursive) ==="
  git clone --recursive -b v0.5 https://github.com/GAP-LAB-CUHK-SZ/ReconViaGen.git "$RVG"
else
  log "=== ReconViaGen already present ==="
  cd "$RVG"
  git submodule update --init --recursive || true
fi
cd "$RVG"

# Upstream setup.sh pins huggingface_hub==0.33.4 with transformers==5.3.0 — pip conflict.
# Demo path uses 1.7.2; align --basic to that.
sed -i 's/huggingface_hub==0.33.4/huggingface_hub==1.7.2/g' ./setup.sh || true
# RunPod containers are already root; setup.sh uses sudo which is often missing.
sed -i 's/sudo apt install -y libjpeg-dev/apt-get install -y -qq libjpeg-dev || true/g' ./setup.sh || true
sed -i 's/sudo //g' ./setup.sh || true
# o-voxel lives under wheels/TRELLIS.2 in v0.5; setup.sh expects ./o-voxel
if [[ ! -e ./o-voxel && -d ./wheels/TRELLIS.2/o-voxel ]]; then
  ln -sfn wheels/TRELLIS.2/o-voxel ./o-voxel
  log "symlinked ./o-voxel -> wheels/TRELLIS.2/o-voxel"
fi

MARKER=/workspace/.d3_setup_done
if [[ ! -f "$MARKER" ]]; then
  log "=== apt helpers (getopt / libjpeg) ==="
  apt-get update -y
  apt-get install -y --no-install-recommends util-linux libjpeg-dev build-essential git ninja-build || true

  log "=== setup.sh (long; cuda extensions) ==="
  # Already in env — do NOT pass --new-env
  # shellcheck disable=SC1091
  . ./setup.sh --basic --xformers --flash-attn --cumesh --o-voxel --flexgemm --nvdiffrec --spconv --mipgaussian --kaolin --nvdiffrast
  touch "$MARKER"
  log "=== setup DONE ==="
else
  log "=== setup marker found — skip ==="
fi

# Ensure demo-ish extras for rembg etc. already in --basic
$PY -c "import o_voxel, torch; print('o_voxel ok', torch.cuda.is_available())"

FRONT=/workspace/data/front.png
BACK=/workspace/data/back.png
if [[ ! -f "$FRONT" || ! -f "$BACK" ]]; then
  log "ERROR: need $FRONT and $BACK"
  exit 1
fi

INFER=/workspace/scripts/reconviagen_infer.py
if [[ ! -f "$INFER" ]]; then
  log "ERROR: missing $INFER"
  exit 1
fi

OUT=/workspace/outputs/r_pod_armor_fb.glb
log "=== infer F+B → $OUT ==="
$PY "$INFER" \
  --repo "$RVG" \
  --image "$FRONT" \
  --image "$BACK" \
  --seed 42 \
  --pipeline 1024_cascade \
  --strategy adaptive_guidance_weight \
  --ss-source mesh \
  --decimation 700000 \
  --texture-size 2048 \
  --save "$OUT"

ls -lah "$OUT"
log "=== D3 DONE ==="
