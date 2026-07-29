#!/usr/bin/env bash
# One-shot W2: pin torch cu124, install deps without PIP_CONSTRAINT, re-pin torch, nvdiffrast, run.
set -euo pipefail
exec > >(tee -a /workspace/w2_run.log) 2>&1

DATA_DIR=/workspace/data
OUT_DIR=/workspace/outputs
REPO_DIR=/workspace/MV-Adapter
IMAGE="$DATA_DIR/ref_gold_armor.png"
MESH="$DATA_DIR/model-armor-clay_repaired.glb"
ZIP_URL="${ZIP_URL:-https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/mvadapter_w2_upload.zip}"
TORCH_INDEX="https://download.pytorch.org/whl/cu124"

mkdir -p "$DATA_DIR" "$OUT_DIR" /workspace/checkpoints
cd /workspace
apt-get update -qq
apt-get install -y -qq wget unzip ninja-build build-essential >/dev/null || true

if [[ ! -f "$IMAGE" || ! -f "$MESH" ]]; then
  echo "=== Fetching assets zip ==="
  wget -q -O /tmp/mvadapter_w2_upload.zip "$ZIP_URL"
  unzip -o /tmp/mvadapter_w2_upload.zip -d /workspace
fi
[[ -f "$IMAGE" && -f "$MESH" ]] || { echo "ERROR: missing assets"; exit 1; }

if [[ ! -d "$REPO_DIR/.git" ]]; then
  git clone --depth 1 https://github.com/huanngzh/MV-Adapter.git "$REPO_DIR"
fi
cd "$REPO_DIR"

echo "=== Pin torch 2.4.1+cu124 ==="
python -m pip install -U pip setuptools wheel ninja
pip install --force-reinstall torch==2.4.1+cu124 torchvision==0.19.1+cu124 torchaudio==2.4.1+cu124 --index-url "$TORCH_INDEX"
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"

echo "=== MV-Adapter deps (no PIP_CONSTRAINT) ==="
grep -vE 'nvdiffrast|cvcuda|^torch$|^torchvision$|^torchaudio$|git\+https://github.com/NVlabs/nvdiffrast' requirements.txt > /tmp/mvadapter_reqs.txt || true
# Unpinned diffusers pulls 0.39+ with flash_attn_3 custom_op that crashes on torch 2.4.1.
pip install --ignore-installed \
  "diffusers==0.31.0" "transformers==4.46.3" "accelerate==0.34.2" "peft==0.13.2" \
  "huggingface_hub>=0.23,<1.0"
pip install --ignore-installed -r /tmp/mvadapter_reqs.txt || true

echo "=== Re-pin torch after deps ==="
pip install --force-reinstall torch==2.4.1+cu124 torchvision==0.19.1+cu124 torchaudio==2.4.1+cu124 --index-url "$TORCH_INDEX"
python -c "import torch; print(torch.__version__, torch.version.cuda); assert str(torch.version.cuda).startswith('12.')"

echo "=== nvdiffrast ==="
pip install --no-build-isolation --ignore-installed "git+https://github.com/NVlabs/nvdiffrast.git"

echo "=== CV-CUDA (required for texture uv_padding) ==="
pip install "cvcuda-cu12==0.16.0"
python -c "import cvcuda; print('cvcuda ok')"

mkdir -p checkpoints
[[ -f checkpoints/RealESRGAN_x2plus.pth ]] || wget -q --show-progress -O checkpoints/RealESRGAN_x2plus.pth https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth
[[ -f checkpoints/big-lama.pt ]] || wget -q --show-progress -O checkpoints/big-lama.pt https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt

echo "=== texture extras ==="
pip install gltflib jaxtyping typeguard

echo "=== texture_i2tex (W2b: clay repaired + preprocess_mesh) ==="
python -m scripts.texture_i2tex \
  --image "$IMAGE" \
  --mesh "$MESH" \
  --save_dir "$OUT_DIR" \
  --save_name knight_i2tex_v2 \
  --remove_bg \
  --preprocess_mesh
ls -lh "$OUT_DIR"/knight_i2tex_v2_shaded.glb || ls -lh "$OUT_DIR"
echo DONE_OK >> /workspace/w2_run.log
