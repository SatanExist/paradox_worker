"""A result GLB coloured by how far it moved from the original: grey = kept, yellow 0.3 mm, red 1 mm and more.
usage: python heat.py <id>   -> view/<id>_heat.glb and view/<id>_orig.glb (both at the manifest print height, on the plate)"""
import sys
from pathlib import Path

import igl
import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # paradox_worker
from studio_bridge.tools_ops import _load  # noqa: E402


def on_plate(m, height=120.0):
    m.apply_scale(height / m.extents[1])
    lo, hi = m.bounds
    m.apply_translation([-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2])
    return m


mid = sys.argv[1]
height = float(next(line.split("\t")[3] for line in open(HERE / "manifest.tsv", encoding="utf-8") if line.startswith(mid + "\t")))
o = on_plate(_load(HERE / "models" / f"{mid}.glb"), height)
r = on_plate(trimesh.load(HERE / "out" / f"{mid}.glb", force="mesh"), height)
d = np.sqrt(igl.point_mesh_squared_distance(np.asarray(r.vertices, float), np.asarray(o.vertices, float), np.asarray(o.faces, np.int64))[0])
t = np.clip((d - 0.3) / 0.7, 0, 1)
col = np.where(d[:, None] < 0.3, [190, 190, 190], np.stack([np.full_like(t, 255), 220 * (1 - t), 40 * (1 - t)], 1))
r.visual = trimesh.visual.ColorVisuals(r, vertex_colors=np.hstack([col, np.full((len(d), 1), 255)]).astype(np.uint8))
o.visual = trimesh.visual.ColorVisuals(o, vertex_colors=np.tile([150, 170, 200, 255], (len(o.vertices), 1)).astype(np.uint8))
(HERE / "view").mkdir(exist_ok=True)
r.export(HERE / "view" / f"{mid}_heat.glb")
o.export(HERE / "view" / f"{mid}_orig.glb")
print(f"{mid}: moved >0.3 mm on {np.mean(d > 0.3):.1%} of vertices, >1 mm on {np.mean(d > 1):.1%}")
