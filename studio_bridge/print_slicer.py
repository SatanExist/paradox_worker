"""What PrusaSlicer says of a print: time and plastic from the real slicer, for choices a surface estimate can't
make (print_solid.print_turn), and how wide a brim keeps it on the plate (brim_needed). Settings are the file
print_mk4.ini, so no installed profiles are needed. Found as PRUSA_SLICER or prusa-slicer on the PATH; without it
the callers go without."""
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
BRIMS_MM = (0, 5, 10, 20)  # brim widths tried, narrowest first: on the 42-model corpus each step frees 13, 11 and 3 models
LOW_ADHESION = "Low bed adhesion"  # PrusaSlicer's alert (Print::alert_when_supports_needed, SupportPointCause::SeparationFromBed)
ALERT_STEP = "=> Alert if supports needed"  # the progress line of the step that raises it (see _slice)


def _program() -> str | None:
    return os.getenv("PRUSA_SLICER") or shutil.which("prusa-slicer-console") or shutil.which("prusa-slicer")


def _dies_with_parent() -> None:
    import ctypes

    ctypes.CDLL(None).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG: the memory guard stops the tool, and this with it


def _seconds(text: str) -> int:
    return sum(int(v) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[u] for v, u in re.findall(r"(\d+)([dhms])", text))


def _slice(m, rotation=None, settings: str = "", tail: bool = False, alert_only: bool = False) -> tuple[str, str] | None:
    """Slice `m` (closed, in mm, Y up) on the plate, turned first by `rotation` (3x3) when given, with `settings`
    (ini lines) over SETTINGS. Returns (the slicer's output at log level 3, the G-code's last TAIL_BYTES when
    `tail`), or None when it can't (no program, doesn't fit the bed, over SLICE_LIMIT_S).
    `alert_only`: only the alerts are wanted, so the slicer is stopped at the first progress line after ALERT_STEP,
    before the rest of the slicing and the G-code (direct3ds2_knight: 3.1 s of 7.3 s, the same alerts)."""
    import threading

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
        stl, gcode, over = Path(tmp) / "m.stl", Path(tmp) / "m.gcode", Path(tmp) / "over.ini"
        trimesh.Trimesh(V, m.faces, process=False).export(stl)
        over.write_text(settings, encoding="utf-8")
        try:
            proc = subprocess.Popen([program, "--datadir", empty, "--loglevel", "3", "--load", str(SETTINGS), "--load", str(over),
                                     "--export-gcode", "--output", str(gcode), str(stl)],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    errors="replace", preexec_fn=_dies_with_parent if sys.platform.startswith("linux") else None)
        except OSError:
            return None
        late = threading.Timer(SLICE_LIMIT_S, proc.kill)  # over the limit it is stopped, and its return code says so
        late.start()
        out, at_alert, stopped = [], False, False
        try:
            for line in proc.stdout:
                if alert_only and at_alert and re.match(r"\d+ => ", line):  # the next step began: the alerts are all out (same stream)
                    stopped = True
                    proc.kill()
                    break
                at_alert = at_alert or ALERT_STEP in line
                out.append(line)
        finally:
            proc.stdout.close()
            proc.wait()
            late.cancel()
        if stopped:
            return "".join(out), ""
        if proc.returncode != 0 or not gcode.is_file():
            return None
        end = ""
        if tail:
            with open(gcode, "rb") as f:
                f.seek(max(0, gcode.stat().st_size - TAIL_BYTES))
                end = f.read().decode("utf-8", "replace")
    return "".join(out), end


def slice_stats(m, rotation=None) -> dict[str, Any] | None:
    """Print time and plastic of `m` (closed, in mm, Y up) on the plate, turned first by `rotation` (3x3) when given:
    {"minutes", "grams"}; None when the slicer can't (no program, doesn't fit the bed, over SLICE_LIMIT_S)."""
    got = _slice(m, rotation, tail=True)
    if got is None:
        return None
    tail = got[1]
    spent = re.search(r"estimated printing time \(normal mode\) = (.*)", tail)
    grams = re.search(r"total filament used \[g\] = ([\d.]+)", tail)
    if not spent or not grams:
        return None
    return {"minutes": round(_seconds(spent.group(1)) / 60, 1), "grams": round(float(grams.group(1)), 1)}


def brim_needed(m, rotation=None) -> dict[str, Any] | None:
    """How wide a brim keeps `m` (closed, in mm, Y up, turned first by `rotation` when given) on the plate while it
    prints: the narrowest of BRIMS_MM for which PrusaSlicer's stability check raises no LOW_ADHESION. Its check
    weighs what the model pulls with (height, weight, the nozzle's tug at the print acceleration) against the
    footing plus the brim, and only runs with supports off, so it is sliced that way: it is cautious, as supports
    standing on the plate help hold a print too (hunyuan_operative, 365 mm² of feet, wants 10 mm). Those 6-9 mm²
    on the plate (rodin_knight, rodin_spider, hunyuan31_scorpion) need 20. Returns {"brimMm", "holds": False when
    even the widest still gets the alert}; None when the slicer can't."""
    for width in BRIMS_MM:
        got = _slice(m, rotation, f"support_material = 0\nbrim_width = {width}\n", alert_only=True)
        if got is None:
            return None
        if LOW_ADHESION not in got[0]:
            return {"brimMm": width, "holds": True}
    return {"brimMm": BRIMS_MM[-1], "holds": False}
