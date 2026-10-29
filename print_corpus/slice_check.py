"""Slice print_corpus results with PrusaSlicer and check what the printer would really do.

  python slice_check.py [id ...]       results in out/ not yet sliced for the current recipe
  python slice_check.py --again ...    re-slice even if this recipe already has a row

Each result (out/<id>.glb, the print-ready body) goes to PrusaSlicer's command line as a Z-up STL, turned the
way up the report suggests (printTurn) if it does, with a
stock profile (Original Prusa MK4 Input Shaper, 0.4 mm nozzle, 0.20 mm STRUCTURAL, Prusament PLA) and
automatic supports. From the G-code: print time, filament in grams (and how much of it is support), layers,
and how much of the model's outline the nozzle actually traces: on each layer the model's own cross-section
(Manifold, at the layer's middle) is walked every 0.1 mm and each point is measured to the nearest extrusion
of the model (not support, skirt or brim). Within half its width + 0.1 mm it is traced; within half its
width + 0.6 mm it is smoothed over (surface texture finer than the 0.4 mm nozzle: hi3dgen_snowman's knit,
a third of its outline, is there, 0.4-0.5 mm off); further, it is lost: detail the slicer drops as too thin
for the nozzle (a 0.04 mm fin, a needle tip) — it won't be on the print.

Rows go to slice.jsonl, tagged with the recipe (as run.py's) so they line up with results.jsonl.
PrusaSlicer: D:/tools/PrusaSlicer (portable 2.9.6), datadir D:/tools/prusa_datadir (PRUSA_DIR / PRUSA_DATADIR).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import manifold3d as mf
import numpy as np
import trimesh
from scipy.spatial import cKDTree

from run import recipe

HERE = Path(__file__).resolve().parent
PRUSA = Path(os.environ.get("PRUSA_DIR", "D:/tools/PrusaSlicer/PrusaSlicer-2.9.6")) / "prusa-slicer-console.exe"
DATADIR = os.environ.get("PRUSA_DATADIR", "D:/tools/prusa_datadir")
PROFILE = ["--printer-profile", "Original Prusa MK4 Input Shaper 0.4 nozzle",
           "--print-profile", "0.20mm STRUCTURAL @MK4IS 0.4", "--material-profile", "Prusament PLA @PGIS"]
FILAMENT_MM2 = np.pi * (1.75 / 2) ** 2
PLA_G_PER_MM3 = 1.24e-3
STEP_MM = 0.1  # outline sampling
SLACK_MM = 0.1  # a point this far past an extrusion's edge still counts as traced
LOST_MM = 0.6  # further than this past the edge it isn't printed at all; between, the nozzle smoothed it over
NOT_MODEL = ("Support material", "Support material interface", "Skirt/Brim", "Wipe tower", "Custom")
TIME_LIMIT_S = 15 * 60


def stl_of(glb: Path, stl: Path, turn=None) -> trimesh.Trimesh:
    """The body in mm, Z up (glTF is Y up, metres), standing on z = 0; turned first by `turn` (3x3, the report's
    printTurn rotation: the way up it prints with least support) when given."""
    sc = trimesh.load(glb)
    m = (sc.geometry.get("body") if isinstance(sc, trimesh.Scene) else sc).copy()
    m.apply_scale(1000.0)
    if turn is not None:
        R = np.eye(4)
        R[:3, :3] = np.asarray(turn, np.float64)
        m.apply_transform(R)
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    m.apply_translation([0, 0, -m.bounds[0, 2]])
    m.export(stl)
    return m


def parse(gcode: Path):
    """Layers [(z, height, model segments (n,2,2), widths)], filament mm by type, header values."""
    head: dict[str, str] = {}
    layers, by_type = [], {}
    x = y = 0.0
    z = h = 0.0
    kind, width = "", 0.45
    segs, widths = [], []
    relative_e, last_e = True, 0.0
    move = re.compile(r"G([0-3])(?:\s(.*))?$")

    def close():
        if segs:
            layers.append((z, h, np.array(segs).reshape(-1, 2, 2), np.array(widths)))

    with open(gcode, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.split(";", 1)[0].strip() if not line.startswith(";") else line
            if line.startswith(";"):
                if line.startswith(";LAYER_CHANGE"):
                    close()
                    segs, widths = [], []
                elif line.startswith(";Z:"):
                    z = float(line[3:])
                elif line.startswith(";HEIGHT:"):
                    h = float(line[8:])
                elif line.startswith(";TYPE:"):
                    kind = line[6:].strip()
                elif line.startswith(";WIDTH:"):
                    width = float(line[7:])
                elif " = " in line:
                    k, _, v = line[2:].partition(" = ")
                    head[k.strip()] = v.strip()
                continue
            if line.startswith("M82"):
                relative_e = False
            elif line.startswith("M83"):
                relative_e = True
            elif line.startswith("G92"):
                for tok in line.split()[1:]:
                    if tok[0] == "E":
                        last_e = float(tok[1:])
            m = move.match(line)
            if not m:
                continue
            g = int(m.group(1))
            nx, ny, e, i, j = x, y, None, 0.0, 0.0
            for tok in (m.group(2) or "").split():
                c, v = tok[0], tok[1:]
                if c == "X":
                    nx = float(v)
                elif c == "Y":
                    ny = float(v)
                elif c == "E":
                    e = float(v)
                elif c == "I":
                    i = float(v)
                elif c == "J":
                    j = float(v)
            de = 0.0
            if e is not None:
                de = e if relative_e else e - last_e
                if not relative_e:
                    last_e = e
            if de > 0 and (nx, ny) != (x, y):  # a de-retract pushes filament back without printing
                by_type[kind] = by_type.get(kind, 0.0) + de
                if kind not in NOT_MODEL:
                    if g in (2, 3):  # an arc about (x + I, y + J): as chords about 0.2 mm long
                        cx, cy = x + i, y + j
                        a0, a1 = np.arctan2(y - cy, x - cx), np.arctan2(ny - cy, nx - cx)
                        sweep = (a1 - a0) % (2 * np.pi)
                        if g == 2:
                            sweep -= 2 * np.pi
                        r = float(np.hypot(i, j))
                        n = max(1, int(abs(sweep) * r / 0.2))
                        aa = a0 + sweep * np.arange(n + 1) / n
                        px, py = cx + r * np.cos(aa), cy + r * np.sin(aa)
                        px[-1], py[-1] = nx, ny
                        for k in range(n):
                            segs.append(((px[k], py[k]), (px[k + 1], py[k + 1])))
                            widths.append(width)
                    else:
                        segs.append(((x, y), (nx, ny)))
                        widths.append(width)
            x, y = nx, ny
    close()
    return layers, by_type, head


def outline_points(cs):
    """Points every STEP_MM along a cross-section's outline."""
    out = []
    for poly in cs.to_polygons():
        p = np.asarray(poly, np.float64)
        q = np.roll(p, -1, axis=0)
        for a, b in zip(p, q):
            n = max(1, int(np.ceil(np.linalg.norm(b - a) / STEP_MM)))
            out.append(a + (b - a) * (np.arange(n)[:, None] / n))
    return np.vstack(out) if out else np.zeros((0, 2))


def coverage(man, shift, layers):
    """Shares of the model's outline (summed over layers) smoothed over and lost (see the top), and the
    heights where most of the lost is."""
    total = smoothed = missed = 0
    worst = []
    for z, h, segs, widths in layers:
        pts = outline_points(man.slice(z - h / 2)) + shift
        if not len(pts):
            continue
        # extrusions sampled every STEP_MM along their length
        a, b = segs[:, 0], segs[:, 1]
        n = np.maximum(1, np.ceil(np.linalg.norm(b - a, axis=1) / STEP_MM).astype(int))
        k = np.repeat(np.arange(len(segs)), n)
        tt = (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)) / np.repeat(n, n)
        ex = a[k] + (b[k] - a[k]) * tt[:, None]
        edge = widths[k] / 2 + STEP_MM / 2
        d, j = cKDTree(ex).query(pts, distance_upper_bound=float(edge.max()) + LOST_MM)
        past = np.full(len(pts), np.inf)
        hit = np.isfinite(d)
        past[hit] = d[hit] - edge[j[hit]]
        lost = past > LOST_MM
        total += len(pts)
        smoothed += int(((past > SLACK_MM) & ~lost).sum())
        missed += int(lost.sum())
        worst.append((int(lost.sum()), round(z, 2)))
    worst.sort(reverse=True)
    share = lambda c: c / total if total else 0.0  # noqa: E731
    return share(smoothed), share(missed), [z for c, z in worst[:5] if c]


def slice_one(mid: str, rec: str, turn=None) -> dict:
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        stl, gcode = Path(tmp) / f"{mid}.stl", Path(tmp) / f"{mid}.gcode"
        m = stl_of(HERE / "out" / f"{mid}.glb", stl, turn)
        # placed by the slicer itself (its --center refuses some large models as outside the bed)
        cmd = [str(PRUSA), "--datadir", DATADIR, *PROFILE, "--export-gcode", "--support-material",
               "--support-material-auto", "--output", str(gcode), str(stl)]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIME_LIMIT_S)
        row: dict = {"id": mid, "recipe": rec, "profile": PROFILE[1::2], "turned": turn is not None}
        if p.returncode != 0 or not gcode.exists():
            row.update({"ok": False, "error": (p.stderr or p.stdout)[-400:], "secs": round(time.time() - t0)})
            return row
        slice_secs = time.time() - t0
        layers, by_type, head = parse(gcode)
    man = mf.Manifold(mf.Mesh64(vert_properties=np.ascontiguousarray(m.vertices, np.float64),
                                tri_verts=np.asarray(m.faces, np.uint64)))
    # where the slicer put it: its footprint's box (objects_info) over the model's own
    foot = np.asarray(json.loads(head["objects_info"])["objects"][0]["polygon"], np.float64)
    shift = (foot.min(0) + foot.max(0)) / 2 - (m.bounds[0, :2] + m.bounds[1, :2]) / 2
    smoothed, missed, where = coverage(man, shift, layers)
    grams = float(head.get("total filament used [g]", "nan"))
    support = sum(v for k, v in by_type.items() if k.startswith("Support")) / max(sum(by_type.values()), 1e-9)
    row.update({
        "ok": True,
        "printTime": head.get("estimated printing time (normal mode)"),
        "filamentG": grams,
        "supportG": round(grams * support, 1),
        "layers": len(layers),
        "outlineSmoothed": round(smoothed, 4),
        "outlineLost": round(missed, 4),
        "lostAtZ": where,
        "sliceSecs": round(slice_secs),
        "secs": round(time.time() - t0),
    })
    return row


def main() -> None:
    args = sys.argv[1:]
    again = "--again" in args
    ids = [a for a in args if not a.startswith("--")]
    rec = recipe()
    path = HERE / "slice.jsonl"
    done = set()
    if path.exists():
        done = {(r["id"], r["recipe"]) for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())}
    todo = ids or sorted(f.stem for f in (HERE / "out").glob("*.glb") if "." not in f.stem and not f.stem.endswith("-alternate"))
    todo = [i for i in todo if again or (i, rec) not in done]
    turns = {}  # the way up results.jsonl suggests for this recipe
    for r in map(json.loads, (HERE / "results.jsonl").read_text(encoding="utf-8").splitlines()):
        if r.get("recipe") == rec and ((r.get("printTurn") or {}).get("turned")):
            turns[r["id"]] = r["printTurn"]["turned"]["rotation"]
    print(f"recipe {rec}: {len(todo)} to slice", flush=True)
    for k, mid in enumerate(todo, 1):
        row = slice_one(mid, rec, turns.get(mid))
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        print(f"[{k}/{len(todo)}] {mid:22} " + (f"{row['printTime']:>14} {row['filamentG']:6.1f} g (support {row['supportG']:5.1f}) "
              f"outline smoothed {row['outlineSmoothed'] * 100:5.2f} % lost {row['outlineLost'] * 100:5.2f} %  {row['secs']}s" if row["ok"] else f"FAILED {row['error'][-200:]}"), flush=True)


if __name__ == "__main__":
    main()
