"""Minimal Open3D loader for MV-Adapter UV atlas (CPU pybind only).

Replaces upstream __init__.py: no visualization/ml (dash/plotly), but still
preload bundled libc++ / libGL that BUILD_GUI=True pybind wheels need.
"""
# paradox: headless uv-atlas

from __future__ import annotations

import os
import sys
from ctypes import CDLL
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "True")
os.environ.setdefault("OPEN3D_DISABLE_WEB_VISUALIZER", "true")
os.environ.setdefault("OPEN3D_CPU_RENDERING", "true")

from open3d._build_config import _build_config  # noqa: E402

__DEVICE_API__ = "cpu"
__version__ = "0.18.0"

_PKG = Path(__file__).resolve().parent


def _load_cdll(path: Path) -> CDLL:
    if not path.is_file():
        raise FileNotFoundError(f"Shared library file not found: {path}")
    if sys.platform == "win32" and sys.version_info >= (3, 8):
        return CDLL(str(path), winmode=0)
    return CDLL(str(path))


# Upstream open3d wheels with BUILD_GUI=True ship these next to __init__.py.
# Without preloading, `import open3d.cpu.pybind` fails on missing libGL/libc++.
if sys.platform.startswith("linux"):
    for pattern in ("*c++abi.*", "*c++.*"):
        matches = sorted(_PKG.glob(pattern))
        if matches:
            try:
                _load_cdll(matches[0])
            except OSError as exc:
                print(f"open3d headless: optional preload {matches[0].name} failed: {exc}")

    os.environ.setdefault("LIBGL_DRIVERS_PATH", str(_PKG))
    for name in ("libEGL.so.1", "libGL.so.1"):
        candidate = _PKG / name
        if candidate.is_file():
            try:
                _load_cdll(candidate)
            except OSError as exc:
                print(f"open3d headless: optional preload {name} failed: {exc}")

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

# Silence unused-import lint for build config side effects.
_ = _build_config
