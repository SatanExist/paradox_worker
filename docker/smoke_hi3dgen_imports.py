"""Build-time smoke for Hi3DGen image (no GPU / no HF weights)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("SPCONV_ALGO", "native")

repo = Path(os.environ.get("HI3DGEN_REPO", "/app/Stable3DGen"))
if str(repo) not in sys.path:
    sys.path.insert(0, str(repo))

assert (repo / "hi3dgen").is_dir(), f"missing hi3dgen package in {repo}"
import hi3dgen.pipelines  # noqa: F401
from hi3dgen.representations.mesh.cube2mesh import SparseFeatures2Mesh  # noqa: F401
from hi3dgen.representations.mesh.flexicubes.flexicubes import FlexiCubes  # noqa: F401

import torch

print("torch", torch.__version__, "cuda_built", torch.cuda.is_available())
print("hi3dgen pipelines ok; flexicubes import ok")
