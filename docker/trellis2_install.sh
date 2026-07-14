#!/usr/bin/env bash
# Install TRELLIS.2 Python deps inside Docker (no conda).
# Uses xformers instead of flash-attn for faster/reliable CI builds.
set -euo pipefail

TRELLIS2_ROOT="${TRELLIS2_ROOT:-/app/TRELLIS.2}"
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-8.0;8.6;8.9+PTX}"

cd "${TRELLIS2_ROOT}"

echo "==> Basic Python deps"
pip install --no-cache-dir \
  imageio imageio-ffmpeg tqdm easydict opencv-python-headless ninja trimesh \
  transformers gradio==6.0.1 tensorboard pandas lpips zstandard \
  kornia timm

pip install --no-cache-dir \
  git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8

echo "==> xformers (ATTN_BACKEND=xformers; skip flash-attn compile in POC)"
pip install --no-cache-dir xformers

echo "==> nvdiffrast"
git clone -b v0.4.0 --depth 1 https://github.com/NVlabs/nvdiffrast.git /tmp/nvdiffrast
pip install --no-cache-dir --no-build-isolation /tmp/nvdiffrast
rm -rf /tmp/nvdiffrast

echo "==> nvdiffrec"
git clone -b renderutils --depth 1 https://github.com/JeffreyXiang/nvdiffrec.git /tmp/nvdiffrec
pip install --no-cache-dir --no-build-isolation /tmp/nvdiffrec
rm -rf /tmp/nvdiffrec

echo "==> CuMesh"
git clone --recursive --depth 1 https://github.com/JeffreyXiang/CuMesh.git /tmp/CuMesh
pip install --no-cache-dir --no-build-isolation /tmp/CuMesh
rm -rf /tmp/CuMesh

echo "==> FlexGEMM"
git clone --recursive --depth 1 https://github.com/JeffreyXiang/FlexGEMM.git /tmp/FlexGEMM
pip install --no-cache-dir --no-build-isolation /tmp/FlexGEMM
rm -rf /tmp/FlexGEMM

echo "==> o-voxel (from TRELLIS.2 submodule)"
rm -rf /tmp/o-voxel
cp -r "${TRELLIS2_ROOT}/o-voxel" /tmp/o-voxel
pip install --no-cache-dir --no-build-isolation /tmp/o-voxel
rm -rf /tmp/o-voxel

echo "==> Import smoke test"
python - <<'PY'
import o_voxel
import trellis2
print("trellis2 import OK")
PY
