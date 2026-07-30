#!/usr/bin/env bash
# Phase 1 Pod baseline: MV-Adapter FAST path (same as serverless default).
# Records wall-clock phases from [i2tex] logs into timings file.
#
# Usage (Web Terminal / SSH on Pod):
#   cd /workspace && bash /workspace/mvadapter_w2_fast_oneshot.sh
# Resume deps already installed:
#   SKIP_INSTALL=1 bash /workspace/mvadapter_w2_fast_oneshot.sh
set -euo pipefail
exec > >(tee -a /workspace/w2_fast_run.log) 2>&1

DATA_DIR=/workspace/data
OUT_DIR=/workspace/outputs
REPO_DIR=/workspace/MV-Adapter
IMAGE="$DATA_DIR/ref_gold_armor.png"
MESH="$DATA_DIR/model-armor-clay_repaired.glb"
ZIP_URL="${ZIP_URL:-https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/mvadapter_w2_upload.zip}"
FAST_SCRIPT_URL="${FAST_SCRIPT_URL:-https://raw.githubusercontent.com/SatanExist/paradox_worker/feat/trellis2-poc/docker/mvadapter_serverless_i2tex.py}"
TORCH_INDEX="https://download.pytorch.org/whl/cu124"
SKIP_INSTALL="${SKIP_INSTALL:-0}"
SAVE_NAME="${SAVE_NAME:-knight_fast}"

mkdir -p "$DATA_DIR" "$OUT_DIR" /workspace/checkpoints
cd /workspace

echo "=== Phase 1 FAST oneshot $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

if [[ ! -f "$IMAGE" || ! -f "$MESH" ]]; then
  echo "=== Fetching assets zip ==="
  wget -q -O /tmp/mvadapter_w2_upload.zip "$ZIP_URL"
  unzip -o /tmp/mvadapter_w2_upload.zip -d /workspace
fi
[[ -f "$IMAGE" && -f "$MESH" ]] || { echo "ERROR: missing $IMAGE or $MESH"; exit 1; }
echo "assets OK: $(ls -lh "$IMAGE" "$MESH")"

if [[ ! -d "$REPO_DIR/.git" ]]; then
  git clone --depth 1 https://github.com/huanngzh/MV-Adapter.git "$REPO_DIR"
fi
cd "$REPO_DIR"

# Always refresh fast script from paradox_worker (phase logs + serverless settings).
mkdir -p scripts
wget -q -O scripts/mvadapter_serverless_i2tex.py "$FAST_SCRIPT_URL"
python -c "import pathlib; p=pathlib.Path('scripts/mvadapter_serverless_i2tex.py'); assert p.stat().st_size>500; print('fast script', p, p.stat().st_size, 'bytes')"

if [[ "$SKIP_INSTALL" != "1" ]]; then
  apt-get update -qq
  apt-get install -y -qq wget unzip ninja-build build-essential \
      libgl1 libglib2.0-0 libgomp1 >/dev/null || true

  echo "=== Pin torch 2.4.1+cu124 ==="
  python -m pip install -U pip setuptools wheel ninja
  pip install --force-reinstall torch==2.4.1+cu124 torchvision==0.19.1+cu124 torchaudio==2.4.1+cu124 --index-url "$TORCH_INDEX"
  python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available()); assert torch.cuda.is_available()"

  echo "=== MV-Adapter deps ==="
  grep -vE 'nvdiffrast|cvcuda|^torch$|^torchvision$|^torchaudio$|git\+https://github.com/NVlabs/nvdiffrast' requirements.txt > /tmp/mvadapter_reqs.txt || true
  pip install --ignore-installed \
    "diffusers==0.31.0" "transformers==4.46.3" "accelerate==0.34.2" "peft==0.13.2" \
    "huggingface_hub>=0.23,<1.0"
  pip install --ignore-installed -r /tmp/mvadapter_reqs.txt || true

  echo "=== Re-pin torch after deps ==="
  pip install --force-reinstall torch==2.4.1+cu124 torchvision==0.19.1+cu124 torchaudio==2.4.1+cu124 --index-url "$TORCH_INDEX"

  echo "=== nvdiffrast + cvcuda + texture extras ==="
  pip install --no-build-isolation --ignore-installed "git+https://github.com/NVlabs/nvdiffrast.git"
  pip install "cvcuda-cu12==0.16.0"
  pip install gltflib jaxtyping typeguard spandrel==0.4.1 opencv-python-headless matplotlib imageio
  # open3d needed for UV atlas (full wheel OK on GPU pod)
  pip install "open3d==0.18.0" || pip install --no-deps "open3d-cpu==0.18.0"
  python -c "import cvcuda, open3d; print('cvcuda+open3d ok', open3d.__version__)"

  mkdir -p checkpoints
  [[ -f checkpoints/RealESRGAN_x2plus.pth ]] || wget -q --show-progress -O checkpoints/RealESRGAN_x2plus.pth \
    https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth
  [[ -f checkpoints/big-lama.pt ]] || wget -q --show-progress -O checkpoints/big-lama.pt \
    https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt
else
  echo "=== SKIP_INSTALL=1 (reuse existing env) ==="
  python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
fi

export PYTHONUNBUFFERED=1
export MVADAPTER_TEX_STEPS="${MVADAPTER_TEX_STEPS:-30}"
export MVADAPTER_UV_SIZE="${MVADAPTER_UV_SIZE:-2048}"

TIMINGS="$OUT_DIR/${SAVE_NAME}_timings.txt"
LOG_RUN="$OUT_DIR/${SAVE_NAME}_run.log"
echo "=== FAST texture run steps=$MVADAPTER_TEX_STEPS uv=$MVADAPTER_UV_SIZE ==="
echo "timings -> $TIMINGS"

T0=$(date +%s)
set +e
python -u -m scripts.mvadapter_serverless_i2tex \
  --image "$IMAGE" \
  --mesh "$MESH" \
  --save_dir "$OUT_DIR" \
  --save_name "$SAVE_NAME" \
  --seed 42 \
  --remove_bg \
  2>&1 | tee "$LOG_RUN"
RC=${PIPESTATUS[0]}
set -e
T1=$(date +%s)
WALL=$((T1 - T0))

{
  echo "save_name=$SAVE_NAME"
  echo "wall_sec=$WALL"
  echo "exit_code=$RC"
  echo "steps=$MVADAPTER_TEX_STEPS"
  echo "uv_size=$MVADAPTER_UV_SIZE"
  echo "preprocess_mesh=false"
  echo "--- [i2tex] phase lines ---"
  grep -E '^\[i2tex\]' "$LOG_RUN" || true
  echo "--- glb ---"
  ls -lh "$OUT_DIR"/"$SAVE_NAME"_shaded.glb 2>/dev/null || echo "NO_GLB"
} | tee "$TIMINGS"

if [[ "$RC" -eq 0 && -f "$OUT_DIR/${SAVE_NAME}_shaded.glb" ]]; then
  echo "DONE_OK wall_sec=$WALL" | tee -a /workspace/w2_fast_run.log
  echo "GLB: $OUT_DIR/${SAVE_NAME}_shaded.glb"
  echo "Next: download GLB + paste timings table to chat"
  exit 0
fi

echo "DONE_FAIL rc=$RC wall_sec=$WALL" | tee -a /workspace/w2_fast_run.log
exit "$RC"
