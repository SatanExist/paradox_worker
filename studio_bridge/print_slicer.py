"""What PrusaSlicer says a print takes: time and plastic from the real slicer, for choices a surface estimate can't
make (print_solid.print_turn). Settings are the file print_mk4.ini, so no installed profiles are needed. Found as
PRUSA_SLICER or prusa-slicer on the PATH; without it the callers go without."""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SETTINGS = Path(__file__).with_name("print_mk4.ini")
PROFILE = "Prusa MK4, 0.4 mm nozzle, 0.20 mm layers, PLA"
SLICE_LIMIT_S = 300  # a model that takes longer goes without what it was asked for
TAIL_BYTES = 300_000  # the totals are in the settings block at the end of the G-code


def _program() -> str | None:
    return os.getenv("PRUSA_SLICER") or shutil.which("prusa-slicer-console") or shutil.which("prusa-slicer")


def _dies_with_parent() -> None:
    import ctypes

    ctypes.CDLL(None).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG: the memory guard stops the tool, and this with it


def _seconds(text: str) -> int:
    return sum(int(v) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[u] for v, u in re.findall(r"(\d+)([dhms])", text))


def slice_stats(m, rotation=None) -> dict[str, Any] | None:
    """Print time and plastic of `m` (closed, in mm, Y up) on the plate, turned first by `rotation` (3x3) when given:
    {"minutes", "grams"}; None when the slicer can't (no program, doesn't fit the bed, over SLICE_LIMIT_S)."""
    import numpy as np
    import trimesh

    program = _program()
    if program is None:
        return None
    V = np.asarray(m.vertices, np.float64)
    if rotation is not None:
        V = V @ np.asarray(rotation, np.float64).T
    V = np.c_[V[:, 0], -V[:, 2], V[:, 1]]  # Z up, as slicers have it
    V[:, 2] -= V[:, 2].min()
    with tempfile.TemporaryDirectory(prefix="slice-") as tmp, tempfile.TemporaryDirectory(prefix="slicer-data-") as empty:
        stl, gcode = Path(tmp) / "m.stl", Path(tmp) / "m.gcode"
        trimesh.Trimesh(V, m.faces, process=False).export(stl)
        try:
            done = subprocess.run([program, "--datadir", empty, "--load", str(SETTINGS), "--export-gcode", "--output", str(gcode), str(stl)],
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", timeout=SLICE_LIMIT_S,
                                  preexec_fn=_dies_with_parent if sys.platform.startswith("linux") else None)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if done.returncode != 0 or not gcode.is_file():
            return None
        with open(gcode, "rb") as f:
            f.seek(max(0, gcode.stat().st_size - TAIL_BYTES))
            tail = f.read().decode("utf-8", "replace")
    spent = re.search(r"estimated printing time \(normal mode\) = (.*)", tail)
    grams = re.search(r"total filament used \[g\] = ([\d.]+)", tail)
    if not spent or not grams:
        return None
    return {"minutes": round(_seconds(spent.group(1)) / 60, 1), "grams": round(float(grams.group(1)), 1)}
