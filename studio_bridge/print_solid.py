"""Make a model one closed solid for printing while keeping its surface: the print pipeline's step 1.

Generated models come in two kinds. TRELLIS draws a thin double "paper skin" (0.15–0.5 mm) around a
hollow, with holes into it; Hunyuan draws one surface, open in places or already closed. A slicer
prints a paper skin as paper. So candidates are built, measured against the original, and the
best one is kept ("auto pick"). Every model first gets a local repair (cut a small patch round every
defect and refill it); then:

  repair     drop inside-out pockets and crumbs, one exact self-union (CGAL via libigl), bridge pieces
             floating within 1.5 mm. The surface stays as modelled, apart from the patches.
  solidify   only for a paper skin (repaired walls thinner than 1 mm on average, 2·V/A): fill the
             chamber behind the skin (space a 3 mm ball can't reach from outside), then the same finish.
             On a real solid the "chamber" would be its own interior, so solids never get this.
  wrap       CGAL Alpha Wrap at 0.5 mm, then the same bridges. Closed and manifold by construction, and it
             fills thin openwork (beads, lace) solid, at the cost of rounding up to 0.5 mm. Only built for
             models that came in open.

A candidate that left original surface behind (farther than 1 mm and outside the result) on more than
0.1 % of it fails. Of the rest the one that changed least wins, unless the other holds clearly more
volume: that is the one that filled the hollow. Lengths are in mm at the working print height.
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import Any, Callable

BALL_MM = 3.0  # a chamber is space a ball this size can't reach from outside
WRAP_ALPHA_MM = 0.5
WRAP_OFFSET_MM = 0.02  # hugs the surface: the wrap sits 0.02 mm outside it
BRIDGE_REACH_MM = 1.5  # pieces floating farther than this from the body are left as they are
CRUMB_MM3 = 1.0
LOST_MM = 1.0
LOST_MAX_SHARE = 0.001
MORE_SOLID = 1.10  # the rounder candidate must hold this much more volume to be worth its rounding
MAX_VOXELS = 60_000_000  # chamber grid; the distance transforms take ~25 bytes a voxel at peak
SKIN_MM = 1.0  # mean wall (2·volume/area) below this is a paper skin with a hollow to fill
SAMPLES = 200_000
SEED = 0

Log = Callable[[str], None]


# --- local repair ----------------------------------------------------------------------------------


def _weld(m):
    m.merge_vertices(merge_tex=True, merge_norm=True)  # by position only: what a slicer sees
    m.update_faces(m.nondegenerate_faces())
    m.update_faces(m.unique_faces())
    m.remove_unreferenced_vertices()
    return m


def _edge_use(m, directed: bool):
    import numpy as np

    e = m.faces[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2).astype(np.int64)
    if not directed:
        e = np.sort(e, axis=1)
    _, inv, cnt = np.unique(e[:, 0] * len(m.vertices) + e[:, 1], return_inverse=True, return_counts=True)
    return cnt[inv.ravel()].reshape(-1, 3)


def _open_faces(m):
    """Faces on an edge that isn't shared by exactly two faces: holes and fins."""
    return (_edge_use(m, directed=False) != 2).any(axis=1)


def _twisted_faces(m):
    """Faces on a seam where the surface can't be oriented: an edge walked twice in the same direction."""
    return (_edge_use(m, directed=True) > 1).any(axis=1)


def _ms(m):
    import numpy as np
    import pymeshlab

    ms = pymeshlab.MeshSet()
    ms.add_mesh(pymeshlab.Mesh(np.asarray(m.vertices, np.float64), np.asarray(m.faces, np.int32)))
    return ms


def _from_ms(ms):
    import trimesh

    cm = ms.current_mesh()
    return _weld(trimesh.Trimesh(cm.vertex_matrix(), cm.face_matrix(), process=False))


def _reorient(m, log: Log):
    import pymeshlab

    ms = _ms(m)
    try:
        ms.meshing_re_orient_faces_coherently()
    except pymeshlab.PyMeshLabException:  # a fin left over: settle the edges first, then orient
        ms.meshing_repair_non_manifold_edges(method=0)
        ms.meshing_repair_non_manifold_vertices()
        try:
            ms.meshing_re_orient_faces_coherently()
        except pymeshlab.PyMeshLabException:
            log("  reorient skipped: still not 2-manifold")
    return _from_ms(ms)


def _cut_around(m, bad, radius: float):
    """The bad faces, their first ring, and every face within `radius` mm of them."""
    import numpy as np
    from scipy.spatial import cKDTree

    sel = bad.copy()
    v = np.zeros(len(m.vertices), dtype=bool)
    v[m.faces[bad].ravel()] = True
    sel |= v[m.faces].any(axis=1)
    near = cKDTree(m.triangles_center[bad]).query(m.vertices, distance_upper_bound=radius)[0] < radius
    sel |= near[m.faces].all(axis=1)
    return sel


def _local_repair(m, log: Log, rounds: int = 10, cut_first: bool = True):
    """Keep the surface; cut a small patch round each defect and refill it, growing the patch each round."""
    import numpy as np
    import trimesh

    m = _weld(m)
    for r in range(rounds):
        lab = trimesh.graph.connected_component_labels(m.face_adjacency, node_count=len(m.faces))
        area = np.bincount(lab, m.area_faces)
        keep = area >= max(area.max() * 1e-4, 0.5)  # crumbs: under 0.5 mm² of surface
        if not keep.all():
            m.update_faces(keep[lab])
            m.remove_unreferenced_vertices()
        bad, kind = _open_faces(m), "open"
        if not bad.any():  # orientation only means something once every edge has two faces
            m = _reorient(m, log)
            bad, kind = _twisted_faces(m), "twisted"
        if not bad.any():
            break
        log(f"  repair round {r}: {kind} faces {int(bad.sum())}, pieces {int(keep.sum())}")
        if cut_first or r or not _open_faces(m).any():
            radius = 0.5 * (r + 1) if cut_first else 0.5 * max(r, 1)
            m.update_faces(~_cut_around(m, bad, radius))
            m.remove_unreferenced_vertices()
        ms = _ms(m)
        ms.meshing_repair_non_manifold_edges(method=0)
        ms.meshing_repair_non_manifold_vertices()
        ms.meshing_close_holes(maxholesize=100000, refinehole=True, selfintersection=False)
        m = _from_ms(ms)
    m = _reorient(m, log)
    trimesh.repair.fix_normals(m)
    return m


# --- the exact chain -------------------------------------------------------------------------------


def _fill_chamber(m, log: Log, ball_mm: float = BALL_MM):
    """Drop the skin faces that face into a chamber, then close what is left: the hollow becomes solid.
    Returns the mesh and the chamber's volume in cm³ (0 when there is none and nothing changed)."""
    import numpy as np
    import trimesh
    from scipy import ndimage

    ext = float(m.extents.max())
    p = max(0.25, ext / 480)
    for _ in range(3):  # a big boxy model gets coarser voxels instead of more memory
        lo = m.bounds[0] - ball_mm - 2 * p
        dims = np.ceil((m.bounds[1] + ball_mm + 2 * p - lo) / p).astype(int) + 1
        if np.prod(dims) <= MAX_VOXELS:
            break
        p *= (np.prod(dims) / MAX_VOXELS) ** (1 / 3) * 1.01
    pts, _ = trimesh.sample.sample_surface(m, int(m.area / (p * 0.4) ** 2), seed=SEED)
    skin = np.zeros(dims, dtype=bool)
    idx = np.clip(np.floor((np.vstack([pts, m.vertices]) - lo) / p).astype(int), 0, dims - 1)
    skin[tuple(idx.T)] = True
    del pts, idx
    clear = ndimage.distance_transform_edt(~skin).astype(np.float32) * p > ball_mm  # ball centres that fit
    lab, _ = ndimage.label(clear)
    reach = lab == lab[0, 0, 0]  # the ones that get in from outside
    del lab
    outside = ndimage.distance_transform_edt(~reach).astype(np.float32) * p <= ball_mm  # all those balls sweep
    del reach
    interior = ~skin & ~outside
    del skin, outside
    deep = interior & clear
    del clear
    if not deep.any():
        return m, 0.0
    chamber = ndimage.binary_dilation(deep, np.ones((3, 3, 3), bool), iterations=int(np.ceil(ball_mm / p)) + 2, mask=interior)
    del deep, interior
    cm3 = float(chamber.sum()) * p**3 / 1000
    probe = np.clip(np.floor((m.triangles_center + m.face_normals * 2 * p - lo) / p).astype(int), 0, dims - 1)
    inner = chamber[tuple(probe.T)]
    del chamber
    log(f"  chamber {cm3:.1f} cm3 at {p:.2f} mm; inner skin faces {int(inner.sum())} of {len(m.faces)}")
    if not inner.any():
        return m, cm3
    m = m.copy()
    m.update_faces(~inner)
    m.remove_unreferenced_vertices()
    return _local_repair(m, log, cut_first=False), cm3


def _drop_pockets(m):
    """Inside-out shells (sealed pockets within the body) and crumbs under 1 mm³ go: the body is solid there."""
    import trimesh

    parts = m.split(only_watertight=False)
    if len(parts) <= 1:
        return m
    kept = [q for q in parts if q.volume > CRUMB_MM3]
    return trimesh.util.concatenate(kept) if kept else m


def _union(*meshes):
    """One exact union (CGAL arithmetic): resolves every self-crossing. Needs consistently oriented input."""
    import igl.copyleft.cgal as cgal
    import numpy as np
    import trimesh

    allm = trimesh.util.concatenate(list(meshes)) if len(meshes) > 1 else meshes[0]
    V, F, _ = cgal.mesh_boolean(np.asarray(allm.vertices, np.float64), np.asarray(allm.faces, np.int64), type_str="union")
    return trimesh.Trimesh(V, F, process=False)


def _wrap(V, F, alpha: float, offset: float = WRAP_OFFSET_MM):
    """CGAL Alpha Wrap: always a closed, manifold, self-intersection-free shell."""
    import numpy as np
    import trimesh
    from CGAL.CGAL_Alpha_wrap_3 import Int_Vector, Point_3_Vector, Polygon_Vector, alpha_wrap_3
    from CGAL.CGAL_Kernel import Point_3
    from CGAL.CGAL_Polyhedron_3 import Polyhedron_3

    pts = Point_3_Vector()
    pts.reserve(len(V))
    for x, y, z in np.asarray(V, float).tolist():
        pts.append(Point_3(x, y, z))
    polys = Polygon_Vector()
    polys.reserve(len(F))
    for a, b, c in np.asarray(F, np.int64).tolist():
        iv = Int_Vector()
        iv.append(a)
        iv.append(b)
        iv.append(c)
        polys.append(iv)
    P = Polyhedron_3()
    alpha_wrap_3(pts, polys, alpha, offset, P)
    fd, name = tempfile.mkstemp(suffix=".off")
    os.close(fd)
    try:
        P.write_to_file(name)  # the bindings have no array export; OFF is a few seconds even at 1M faces
        return trimesh.load(name, process=False)
    finally:
        os.unlink(name)


def _bridge(m, log: Log, reach: float = BRIDGE_REACH_MM):
    """Pieces floating next to the body (a feather, a bead) get a bridge: a local wrap of the piece plus the
    patch of body facing it, then one exact union of everything. The rest of the surface is untouched.
    Returns the mesh and how many pieces were bridged."""
    import igl
    import numpy as np
    import trimesh

    parts = sorted(m.split(only_watertight=False), key=lambda q: -len(q.faces))
    if len(parts) <= 1:
        return m, 0
    main = parts[0]
    cent = main.triangles_center
    pieces, bridged = [main], 0
    for q in parts[1:]:
        pieces.append(q)
        gap = float(np.sqrt(igl.point_mesh_squared_distance(q.vertices, main.vertices, main.faces)[0].min()))
        if gap > reach or gap < 1e-3:  # too far to tie, or already touching: the union joins those
            continue
        near = np.sqrt(igl.point_mesh_squared_distance(cent, q.vertices, q.faces)[0]) < gap + 1.0
        patch = trimesh.Trimesh(main.vertices, main.faces[near], process=False)
        patch.remove_unreferenced_vertices()
        both = trimesh.util.concatenate([q, patch])
        pieces.append(_wrap(both.vertices, both.faces, alpha=max(0.4, 1.6 * gap)))
        bridged += 1
    out = _union(*pieces)
    shells = out.split(only_watertight=False)
    if len(shells) > 1:
        out = trimesh.util.concatenate([s for s in shells if s.volume > CRUMB_MM3])  # pockets the union sealed
    log(f"  bridges: {len(parts)} pieces, {bridged} bridged")
    return out, bridged


def _thickness(m) -> float | None:
    """Mean wall thickness 2·V/A in mm; None while the mesh isn't closed."""
    if not m.is_watertight or m.area <= 0:
        return None
    return float(2 * abs(m.volume) / m.area)


def _finish(m, log: Log):
    t = time.time()
    m = _drop_pockets(m)
    try:
        m = _drop_pockets(_union(m))
    except Exception as exc:  # non-orientable seams can still break it; the slicer copes with crossings
        log(f"  self-union failed, kept as is: {exc}")
    log(f"  self-union {time.time() - t:.0f}s")
    t = time.time()
    m, bridged = _bridge(m, log)
    log(f"  bridges {time.time() - t:.0f}s")
    return m, {"piecesBridged": bridged}


def _repaired(orig, repaired, log: Log):
    return _finish(repaired.copy(), log)


def _solidified(orig, repaired, log: Log):
    t = time.time()
    m, chamber = _fill_chamber(repaired.copy(), log)
    log(f"  chamber {time.time() - t:.0f}s")
    m, extra = _finish(m, log)
    return m, {"chamberCm3": round(float(chamber), 2), **extra}


def _wrapped(orig, repaired, log: Log):
    t = time.time()
    m = _wrap(orig.vertices, orig.faces, WRAP_ALPHA_MM)
    log(f"  wrap {time.time() - t:.0f}s")
    m, bridged = _bridge(m, log)
    return m, {"piecesBridged": bridged}


# --- measuring and picking -------------------------------------------------------------------------


def _pieces(m) -> int:
    import numpy as np
    import trimesh

    lab = trimesh.graph.connected_component_labels(m.face_adjacency, node_count=len(m.faces))
    return int(len(np.unique(lab)))


def _measure(orig, orig_pts, m) -> dict[str, Any]:
    """'changed': result surface more than 0.3 mm off the original. 'lost': original surface more than 1 mm
    from the result and outside it. Skin buried inside the new solid was filled on purpose: not lost."""
    import igl
    import numpy as np
    import trimesh

    V = np.asarray(m.vertices, np.float64)
    F = np.asarray(m.faces, np.int64)
    pts, _ = trimesh.sample.sample_surface(m, SAMPLES, seed=SEED)
    off = np.sqrt(igl.point_mesh_squared_distance(pts, orig.vertices, orig.faces)[0])
    gone = np.sqrt(igl.point_mesh_squared_distance(orig_pts, V, F)[0])
    far = gone > 0.3
    outside = np.ones(len(orig_pts), dtype=bool)
    if far.any():
        outside[far] = igl.winding_number(V, F, orig_pts[far]) < 0.5
    lost = gone * outside
    watertight = bool(m.is_watertight)
    return {
        "watertight": watertight,
        "parts": _pieces(m),
        "volumeCm3": round(float(m.volume) / 1000, 2) if watertight else None,
        "faces": int(len(m.faces)),
        "changedShare": round(float((off > 0.3).mean()), 4),
        "lostShare": round(float((lost > LOST_MM).mean()), 5),
        "lostMaxMm": round(float(lost.max()), 2),
    }


def _pick(cands: list[dict[str, Any]]):
    closed = [c for c in cands if c["watertight"] and (c["volumeCm3"] or 0) > 0]
    if not closed:
        return None, "no candidate came out closed"
    ok = [c for c in closed if c["lostShare"] <= LOST_MAX_SHARE]
    note = None
    if not ok:
        least = min(c["lostShare"] for c in closed)
        ok = [c for c in closed if c["lostShare"] == least]
        note = f"every candidate lost some surface; kept the one that lost least ({least:.2%})"
    ok.sort(key=lambda c: c["changedShare"])
    best = ok[0]
    for c in ok[1:]:
        if c["volumeCm3"] > best["volumeCm3"] * MORE_SOLID:
            best = c
    return best, note


def make_solid(mesh, mm_per_unit: float, log: Log = print):
    """One closed solid made from `mesh` (any units; `mm_per_unit` gives the print scale), and the report.
    Raises when no candidate came out closed, so the caller can fall back."""
    import numpy as np
    import trimesh

    t0 = time.time()
    orig = _weld(trimesh.Trimesh(np.asarray(mesh.vertices, np.float64) * mm_per_unit, np.asarray(mesh.faces), process=False))
    came_closed = bool(orig.is_watertight)
    orig_pts, _ = trimesh.sample.sample_surface(orig, SAMPLES, seed=SEED)

    t1 = time.time()
    builders: list[tuple[str, Callable]] = []
    repaired = wall = None
    try:
        repaired = _local_repair(orig.copy(), log)
        wall = _thickness(repaired)
        log(f" local repair {time.time() - t1:.0f}s, closed {repaired.is_watertight}, wall {wall if wall is None else round(wall, 2)} mm")
        builders.append(("repair", _repaired))
        if wall is None or wall < SKIN_MM:  # a paper skin, or unknown: the gate judges the result
            builders.append(("solidify", _solidified))
    except Exception as exc:
        log(f" local repair failed: {exc}")
    if not came_closed or not builders:
        builders.append(("wrap", _wrapped))
    cands: list[dict[str, Any]] = []
    for name, build in builders:
        t1 = time.time()
        log(f" {name}:")
        try:
            m, extra = build(orig, repaired, log)
        except Exception as exc:
            log(f"  {name} failed: {exc}")
            continue
        c = {"method": name, **_measure(orig, orig_pts, m), **extra, "secs": round(time.time() - t1, 1)}
        log(f"  {name}: {c}")
        c["_mesh"] = m
        cands.append(c)

    best, note = _pick(cands)
    if best is None:
        raise RuntimeError(note)
    out = best["_mesh"]
    out.apply_scale(1.0 / mm_per_unit)
    trimesh.repair.fix_normals(out)
    info: dict[str, Any] = {
        "method": best["method"],
        "cameClosed": came_closed,
        "wallMm": None if wall is None else round(wall, 2),
        "candidates": [{k: v for k, v in c.items() if not k.startswith("_")} for c in cands],
        "secs": round(time.time() - t0, 1),
    }
    if note:
        info["note"] = note
    return out, info
