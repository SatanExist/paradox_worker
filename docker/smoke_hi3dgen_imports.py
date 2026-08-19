"""Build-time smoke for Hi3DGen image (no GPU / no HF weights)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("SPCONV_ALGO", "native")

repo = Path(os.environ.get("HI3DGEN_REPO", "/app/Hi3DGen"))
if str(repo) not in sys.path:
    sys.path.insert(0, str(repo))

assert (repo / "trellis").is_dir(), f"missing trellis package in {repo}"
assert (repo / "app.py").is_file(), f"missing Space app.py in {repo}"
assert (repo / "trellis" / "representations" / "mesh" / "flexicube.py").is_file()

import rembg  # noqa: F401
from trellis.representations.mesh.flexicube import FlexiCubes  # noqa: F401

import torch

print("torch", torch.__version__, "cuda_built", torch.cuda.is_available())
print("hi3dgen Space layout ok; rembg + FlexiCubes import ok")
