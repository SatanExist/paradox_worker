#!/usr/bin/env bash
# Bootstrap MV-Adapter on a RunPod GPU pod (W2 spike).
# Run from /workspace after uploading knight assets to /workspace/data/
set -euo pipefail

DATA_DIR="${DATA_DIR:-/workspace/data}"
OUT_DIR="${OUT_DIR:-/workspace/outputs}"
REPO_DIR="${REPO_DIR:-/workspace/MV-Adapter}"
IMAGE="${DATA_DIR}/ref_gold_armor.png"
MESH="${DATA_DIR}/model-armor-clay_repaired.glb"
SAVE_NAME="${SAVE_NAME:-knight_i2tex_v2}"
VARIANT_ARG="${VARIANT_ARG:-}"  # e.g. --variant sd21
PREPROCESS_ARG="${PREPROCESS_ARG:---preprocess_mesh}"

mkdir -p "$DATA_DIR" "$OUT_DIR" /workspace/checkpoints

if [[ ! -f "$IMAGE" || ! -f "$MESH" ]]; then
  echo "ERROR: need $IMAGE and $MESH"
  echo "Upload from PC: ref_gold_armor.png + model-armor-clay_repaired.glb → $DATA_DIR"
  exit 1
fi

if [[ ! -d "$REPO_DIR/.git" ]]; then
  git clone --depth 1 https://github.com/huanngzh/MV-Adapter.git "$REPO_DIR"
fi
cd "$REPO_DIR"

bash "$(dirname "$0")/mvadapter_w2_pip_setup.sh" 2>/dev/null || {
  # Inline when only bootstrap.sh was uploaded
  TORCH_INDEX="https://download.pytorch.org/whl/cu124"
  python -m pip install -U pip setuptools wheel
  pip install --ignore-installed \
    torch==2.4.1+cu124 torchvision==0.19.1+cu124 torchaudio==2.4.1+cu124 \
    --index-url "${TORCH_INDEX}"
  apt-get update -qq && apt-get install -y -qq ninja-build build-essential >/dev/null || true
  pip install -q ninja || true
  grep -vE 'nvdiffrast|cvcuda|torchvision|torchaudio' requirements.txt | grep -v '^torch$' > /tmp/mvadapter_reqs.txt
  printf '%s\n' 'torch==2.4.1+cu124' 'torchvision==0.19.1+cu124' 'torchaudio==2.4.1+cu124' > /tmp/mvadapter_constraints.txt
  PIP_CONSTRAINT=/tmp/mvadapter_constraints.txt pip install --ignore-installed -r /tmp/mvadapter_reqs.txt
  pip install --no-build-isolation --ignore-installed "git+https://github.com/NVlabs/nvdiffrast.git"
  pip install "cvcuda-cu12==0.16.0"
  python -c "import cvcuda; print('cvcuda ok')"
}
pip install -q opencv-python-headless trimesh pillow requests gltflib || true

mkdir -p checkpoints
if [[ ! -f checkpoints/RealESRGAN_x2plus.pth ]]; then
  wget -q --show-progress \
    https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth \
    -O checkpoints/RealESRGAN_x2plus.pth
fi
if [[ ! -f checkpoints/big-lama.pt ]]; then
  wget -q --show-progress \
    https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt \
    -O checkpoints/big-lama.pt
fi

echo "=== Running texture_i2tex (W2b) ==="
# shellcheck disable=SC2086
python -m scripts.texture_i2tex \
  --image "$IMAGE" \
  --mesh "$MESH" \
  --save_dir "$OUT_DIR" \
  --save_name "$SAVE_NAME" \
  --remove_bg \
  $PREPROCESS_ARG \
  $VARIANT_ARG

echo "=== Done ==="
ls -lh "$OUT_DIR/${SAVE_NAME}_shaded.glb" || ls -lh "$OUT_DIR"
