"""Minimal Open3D loader for MV-Adapter UV atlas (CPU pybind only).

Replaces the upstream __init__.py so import does not pull visualization/ml/GUI
(dash/plotly) or require libcuda at import time on CI buildx.
"""
# paradox: headless uv-atlas

from __future__ import annotations

import os
import sys

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "True")
os.environ.setdefault("OPEN3D_DISABLE_WEB_VISUALIZER", "true")

from open3d._build_config import _build_config  # noqa: E402, F401

__DEVICE_API__ = "cpu"
__version__ = "0.18.0"

from open3d.cpu.pybind import (  # noqa: E402
    camera,
    core,
    data,
    geometry,
    io,
    pipelines,
    t,
    utility,
)
from open3d.cpu import pybind  # noqa: E402


def _insert_pybind_names(skip_names: tuple[str, ...] = ()) -> None:
    submodules = {}
    prefix = f"open3d.{__DEVICE_API__}.pybind"
    for modname, module in list(sys.modules.items()):
        if prefix not in modname:
            continue
        if any("." + skip_name in modname for skip_name in skip_names):
            continue
        subname = modname.replace(f"{__DEVICE_API__}.pybind.", "")
        if subname not in sys.modules:
            submodules[subname] = module
    sys.modules.update(submodules)


_insert_pybind_names(skip_names=("ml",))

sys.modules.setdefault("open3d.core", core)
sys.modules.setdefault("open3d.camera", camera)
sys.modules.setdefault("open3d.geometry", geometry)
sys.modules.setdefault("open3d.t", t)
