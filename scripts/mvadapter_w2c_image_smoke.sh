#!/usr/bin/env bash
# Smoke on prebuilt GHCR mvadapter image (no pip marathon).
# Overlays xatlas i2tex from R2; paints ultra tex80k clay by default.
set -euo pipefail
exec > >(tee -a /workspace/w2c_image_run.log) 2>&1

DATA_DIR=/workspace/data
OUT_DIR=/workspace/outputs
ZIP_URL="${ZIP_URL:-https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/mvadapter_w2_upload.zip}"
MESH_URL="${MESH_URL:-https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/armor_ultra_rt6_tex80k.glb}"
IMAGE_URL="${IMAGE_URL:-https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/ref_gold_armor.png}"
MESH="${MESH:-$DATA_DIR/armor_ultra_rt6_tex80k.glb}"
IMAGE="${IMAGE:-$DATA_DIR/ref_gold_armor.png}"
SAVE_NAME="${SAVE_NAME:-armor_w2b_ultra}"
export PYTHONUNBUFFERED=1
export MVADAPTER_TEX_STEPS="${MVADAPTER_TEX_STEPS:-30}"
export MVADAPTER_UV_SIZE="${MVADAPTER_UV_SIZE:-2048}"
export MVADAPTER_UV_BACKEND="${MVADAPTER_UV_BACKEND:-xatlas}"
export MVADAPTER_DECIMATE_FACES="${MVADAPTER_DECIMATE_FACES:-80000}"
# Prefer volume caches when attached
export HF_HOME="${HF_HOME:-/workspace/huggingface_cache}"
export TORCH_HOME="${TORCH_HOME:-/workspace/torch_cache}"
export TORCH_EXTENSIONS_DIR="${TORCH_EXTENSIONS_DIR:-/workspace/torch_extensions}"

mkdir -p "$DATA_DIR" "$OUT_DIR" "$HF_HOME" "$TORCH_HOME" "$TORCH_EXTENSIONS_DIR"
cd /workspace

echo "=== W2c image smoke $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "python=$(command -v python) PARADOX_BUILD_SHA=${PARADOX_BUILD_SHA:-unknown}"
echo "mesh=$MESH image=$IMAGE save_name=$SAVE_NAME"

if [[ ! -f "$IMAGE" ]]; then
  echo "=== Fetch image ==="
  wget -q -O "$IMAGE" "$IMAGE_URL" || curl -fsSL -o "$IMAGE" "$IMAGE_URL"
fi
if [[ ! -f "$MESH" ]]; then
  echo "=== Fetch mesh ==="
  wget -q -O "$MESH" "$MESH_URL" || curl -fsSL -o "$MESH" "$MESH_URL"
fi
# Optional zip fallback for bundled i2tex copy
if [[ ! -f /workspace/mvadapter_serverless_i2tex.py && ! -f /workspace/docker/mvadapter_serverless_i2tex.py ]]; then
  wget -O /tmp/w2.zip "$ZIP_URL" || true
  unzip -o /tmp/w2.zip -d /workspace || true
fi
[[ -f "$IMAGE" && -f "$MESH" ]] || { echo "ERROR: missing $IMAGE or $MESH"; exit 1; }
echo "assets OK: $(ls -lh "$IMAGE" "$MESH")"

# Always refresh serverless i2tex from zip/R2 (xatlas path may be newer than image).
if [[ -f /workspace/mvadapter_serverless_i2tex.py ]]; then
  cp -f /workspace/mvadapter_serverless_i2tex.py /app/MV-Adapter/scripts/mvadapter_serverless_i2tex.py
elif [[ -f /workspace/docker/mvadapter_serverless_i2tex.py ]]; then
  cp -f /workspace/docker/mvadapter_serverless_i2tex.py /app/MV-Adapter/scripts/mvadapter_serverless_i2tex.py
else
  wget -O /app/MV-Adapter/scripts/mvadapter_serverless_i2tex.py \
    https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/mvadapter_serverless_i2tex.py
fi
sed -i 's/\r$//' /app/MV-Adapter/scripts/mvadapter_serverless_i2tex.py || true

cd /app/MV-Adapter
python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
# Older mvadapter images may miss xatlas/trimesh (added later in Dockerfile).
python -c "import xatlas, trimesh" 2>/dev/null || pip install -q xatlas trimesh
python -c "import torch, xatlas, trimesh; print('ok', torch.__version__, torch.cuda.is_available())"

TIMINGS="$OUT_DIR/${SAVE_NAME}_timings.txt"
LOG_RUN="$OUT_DIR/${SAVE_NAME}_run.log"
T0=$(date +%s)
set +e
python -u -m scripts.mvadapter_serverless_i2tex \
  --image "$IMAGE" \
  --mesh "$MESH" \
  --save_dir "$OUT_DIR" \
  --save_name "$SAVE_NAME" \
  --seed 42 \
  --remove_bg \
  --uv_backend xatlas \
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
  echo "decimate_faces=$MVADAPTER_DECIMATE_FACES"
  echo "uv_backend=$MVADAPTER_UV_BACKEND"
  echo "mesh=$MESH"
  echo "image_sha=${PARADOX_BUILD_SHA:-unknown}"
  echo "--- [i2tex] phase lines ---"
  grep -E '^\[i2tex\]' "$LOG_RUN" || true
  echo "--- glb ---"
  ls -lh "$OUT_DIR/${SAVE_NAME}_shaded.glb" 2>/dev/null || echo "NO_GLB"
} | tee "$TIMINGS"

if [[ "$RC" -eq 0 && -f "$OUT_DIR/${SAVE_NAME}_shaded.glb" ]]; then
  echo "DONE_OK wall_sec=$WALL"
  exit 0
fi
echo "DONE_FAIL rc=$RC wall_sec=$WALL"
exit "$RC"
