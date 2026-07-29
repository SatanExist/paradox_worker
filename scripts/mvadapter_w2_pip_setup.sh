#!/usr/bin/env bash
# Shared pip setup for MV-Adapter W2 on RunPod pytorch:2.4.0-cuda12.4 image.
# Pins torch cu124 so nvdiffrast CUDA build matches host CUDA 12.4.
set -euo pipefail

TORCH_INDEX="${TORCH_INDEX:-https://download.pytorch.org/whl/cu124}"
TORCH_VER="${TORCH_VER:-2.4.1+cu124}"
TV_VER="${TV_VER:-0.19.1+cu124}"
TA_VER="${TA_VER:-2.4.1+cu124}"

echo "=== Pin PyTorch ${TORCH_VER} (CUDA 12.4) ==="
python -m pip install -U pip setuptools wheel
pip install --ignore-installed \
  "torch==${TORCH_VER}" "torchvision==${TV_VER}" "torchaudio==${TA_VER}" \
  --index-url "${TORCH_INDEX}"

python -c "import torch; print('torch', torch.__version__, 'torch.cuda', torch.version.cuda, 'cuda_ok', torch.cuda.is_available())"

echo "=== Build tools (nvdiffrast) ==="
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq ninja-build build-essential >/dev/null || true
fi
pip install -q ninja || true

echo "=== MV-Adapter pip deps (no torch upgrade) ==="
grep -vE 'nvdiffrast|cvcuda|(^|[^a-z])torch([^a-z]|$)|torchvision|torchaudio' requirements.txt > /tmp/mvadapter_reqs.txt
cat > /tmp/mvadapter_constraints.txt <<EOF
torch==${TORCH_VER}
torchvision==${TV_VER}
torchaudio==${TA_VER}
EOF
# Pin diffusers stack before requirements.txt (unpinned diffusers 0.39+ breaks torch 2.4.1).
PIP_CONSTRAINT=/tmp/mvadapter_constraints.txt pip install --ignore-installed \
  "diffusers==0.31.0" "transformers==4.46.3" "accelerate==0.34.2" "peft==0.13.2" \
  "huggingface_hub>=0.23,<1.0"
PIP_CONSTRAINT=/tmp/mvadapter_constraints.txt pip install --ignore-installed -r /tmp/mvadapter_reqs.txt

echo "=== nvdiffrast ==="
echo "=== nvdiffrast ==="
pip install --no-build-isolation --ignore-installed "git+https://github.com/NVlabs/nvdiffrast.git"

echo "=== CV-CUDA (required for texture uv_padding) ==="
pip install "cvcuda-cu12==0.16.0"
python -c "import cvcuda; print('cvcuda ok')"
