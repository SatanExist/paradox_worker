"""A result GLB coloured by wall thickness (print_solid.wall_thickness at every vertex): grey = at least the
printer's minimum wall, orange under it, red under half of it.
usage: python thick.py <id>... [--printer=resin]   -> view/<id>_thick.glb (mm, on the plate); open view/thick.html"""
import sys
from pathlib import Path

import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # paradox_worker
from studio_bridge.print_solid import PRINTERS, _ray_thickness  # noqa: E402

printer = PRINTERS[next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--printer=")), "fdm")]
for mid in [a for a in sys.argv[1:] if not a.startswith("--")]:
    m = trimesh.load(HERE / "out" / f"{mid}.glb", force="mesh")
    m.apply_scale(1000.0)  # the results are in metres
    t = _ray_thickness(m, np.asarray(m.vertices, np.float64), -np.asarray(m.vertex_normals, np.float64))
    lo = printer.min_wall_mm
    col = np.where((t < lo / 2)[:, None], [220, 40, 40], np.where((t < lo)[:, None], [245, 150, 30], [190, 190, 190]))
    m.visual = trimesh.visual.ColorVisuals(m, vertex_colors=np.hstack([col, np.full((len(t), 1), 255)]).astype(np.uint8))
    (HERE / "view").mkdir(exist_ok=True)
    m.export(HERE / "view" / f"{mid}_thick.glb")
    print(f"{mid}: under {lo} mm at {np.mean(t < lo):.1%} of vertices, under {lo / 2} mm at {np.mean(t < lo / 2):.1%}")
