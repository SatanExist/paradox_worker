"""Rebuild a model as one closed solid when repair can't close it — the print pipeline's guarantee.

The model is turned into voxels at print scale: the surface, plus everything the generalized
winding number says is inside. Openings narrower than about two `close_mm` are bridged (only around
the actual holes, and where a part floats a hair off the body), everything the outside can't reach
is filled, debris is dropped, and a new surface is traced with marching cubes. That surface is
closed by construction; its vertices are then moved back onto the original wherever that keeps it
closed, untangled and free of self-intersections, which returns the detail the voxels blurred.
The report states what is left of the difference as the distance to the original, in mm."""

from __future__ import annotations

from typing import Any

MAX_VOXELS = 24_000_000  # ~25 MB per bool grid; keeps the CPU worker well inside its memory
WINDING_CHUNK = 2_000_000
SEED = 0


def _winding_inside(V, F, origin, pitch, dims):
    import igl
    import numpy as np

    inside = np.zeros(dims, dtype=bool)
    ys = origin[1] + pitch * (np.arange(dims[1]) + 0.5)
    zs = origin[2] + pitch * (np.arange(dims[2]) + 0.5)
    yy, zz = np.meshgrid(ys, zs, indexing="ij")
    per_slab = dims[1] * dims[2]
    step = max(1, WINDING_CHUNK // per_slab)
    for x0 in range(0, dims[0], step):
        xs = origin[0] + pitch * (np.arange(x0, min(x0 + step, dims[0])) + 0.5)
        pts = np.empty((len(xs), dims[1], dims[2], 3))
        pts[..., 0] = xs[:, None, None]
        pts[..., 1] = yy
        pts[..., 2] = zz
        w = igl.fast_winding_number(V, F, pts.reshape(-1, 3))
        inside[x0 : x0 + len(xs)] = w.reshape(len(xs), dims[1], dims[2]) > 0.5
    return inside


def _near_open_edges(mesh, origin, pitch, dims, reach: int):
    """Voxels within `reach` voxels of an edge that isn't shared by exactly two faces: where the holes are."""
    import numpy as np
    from scipy import ndimage

    near = np.zeros(dims, dtype=bool)
    edges, counts = np.unique(mesh.edges_sorted, axis=0, return_counts=True)
    open_ = edges[counts != 2]
    if len(open_) == 0:
        return near
    a, b = mesh.vertices[open_[:, 0]], mesh.vertices[open_[:, 1]]
    steps = int(np.clip(np.ceil(np.linalg.norm(b - a, axis=1).max() / (pitch / 2)), 1, 2000))
    t = np.linspace(0.0, 1.0, steps + 1)
    for t0 in np.array_split(t, max(1, len(t) // 64)):  # bounded memory on long edges
        pts = (a[None] + (b - a)[None] * t0[:, None, None]).reshape(-1, 3)
        idx = np.clip(np.floor((pts - origin) / pitch).astype(int), 0, np.array(dims) - 1)
        near[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    ball = ndimage.generate_binary_structure(3, 1)
    return ndimage.binary_dilation(near, ball, iterations=reach)


def remesh_solid(mesh, mm_per_unit: float, voxel_mm: float = 0.3, close_mm: float = 1.5, compare_to=None):
    """Closed one-piece version of `mesh`, and a report on what changed (all lengths in mm)."""
    import igl
    import numpy as np
    import trimesh
    from scipy import ndimage
    from skimage.measure import marching_cubes

    ref = compare_to if compare_to is not None else mesh
    V = np.ascontiguousarray(mesh.vertices, dtype=np.float64)
    F = np.ascontiguousarray(mesh.faces, dtype=np.int64)
    lo, hi = mesh.bounds

    pitch = voxel_mm / mm_per_unit
    for _ in range(3):  # a large model gets coarser voxels instead of more memory
        n_close = max(1, int(round(close_mm / mm_per_unit / pitch)))
        pad = (n_close + 3) * pitch
        dims = np.ceil((hi - lo + 2 * pad) / pitch).astype(int) + 1
        if np.prod(dims) <= MAX_VOXELS:
            break
        pitch *= (np.prod(dims) / MAX_VOXELS) ** (1 / 3) * 1.01
    origin = lo - pad
    dims = tuple(int(d) for d in dims)

    # Surface voxels from dense samples (catches open sheets and thin walls the winding number misses).
    occ = np.zeros(dims, dtype=bool)
    n_samples = int(min(20_000_000, max(100_000, mesh.area / pitch**2 * 6)))
    samples, _ = trimesh.sample.sample_surface(mesh, n_samples, seed=SEED)  # same model, same result
    for p in (samples, V):
        idx = np.clip(np.floor((p - origin) / pitch).astype(int), 0, np.array(dims) - 1)
        occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    del samples
    occ |= _winding_inside(V, F, origin, pitch, dims)

    # Bridge narrow openings, fill whatever the outside can't reach. The closing (grow, fill, shrink
    # back) would also fill every fold and crevice narrower than the bridge, so it is kept only around
    # the mesh's actual holes; everywhere else the surface stays as modelled.
    ball = ndimage.generate_binary_structure(3, 1)
    grown = ndimage.binary_fill_holes(ndimage.binary_dilation(occ, ball, iterations=n_close))
    closed = ndimage.binary_erosion(grown, ball, iterations=n_close, border_value=0)
    del grown
    solid = ndimage.binary_fill_holes(occ | (closed & _near_open_edges(mesh, origin, pitch, dims, reach=n_close + 2)))
    del occ
    # Parts the model meant to touch (a feather, a hand on a hilt) may float a hair apart: join them to
    # the main piece, again only where the gap is, so a print doesn't drop them. Pieces are counted
    # after the blur below: it erases one-voxel necks, so a part tied on by one voxel comes out loose.
    voxel_mm3 = (pitch * mm_per_unit) ** 3

    def parts(grid):
        # Pieces as the surface will be traced (after the blur), and the ones big enough to keep.
        traced = ndimage.gaussian_filter(grid.astype(np.float32), 0.8) >= 0.5
        labels, n = ndimage.label(traced)
        sizes = ndimage.sum(traced, labels, range(1, n + 1))
        big = np.flatnonzero(sizes >= max(sizes.max() * 0.002, 1.0 / voxel_mm3)) + 1
        return labels, big, np.argmax(sizes) + 1

    labels, big, top = parts(solid)
    # Join the big pieces, and any small one the voxels still tie to the main piece by a neck.
    tied = ndimage.label(solid)[0]
    tied = np.unique(labels[tied == np.bincount(tied[labels == top]).argmax()])
    join = np.setdiff1d(np.union1d(big, tied[tied > 0]), [top])
    del tied
    if len(join):
        main = labels == top
        rest = np.isin(labels, join)
        reach = n_close + 2
        gaps = ndimage.binary_dilation(main, ball, iterations=reach) & ndimage.binary_dilation(rest, ball, iterations=reach)
        anchor = np.unravel_index(np.argmax(main), main.shape)
        del main
        solid = ndimage.binary_fill_holes(solid | (closed & gaps))
        for _ in range(3):  # a neck the blur would still erase gets a voxel thicker, inside the gap only
            now = parts(solid)[0]
            if (now[rest] == now[anchor]).all():
                break
            solid |= ndimage.binary_dilation(solid, ball) & gaps
        del rest, gaps
    del closed, labels

    # Debris: pieces under 1 mm³ or under 0.2% of the main piece.
    labels, n_pieces = ndimage.label(solid)
    sizes = ndimage.sum(solid, labels, range(1, n_pieces + 1))
    keep = np.flatnonzero(sizes >= max(sizes.max() * 0.002, 1.0 / voxel_mm3)) + 1
    solid = np.isin(labels, keep)
    del labels

    # A light blur so the surface isn't stair-stepped; marching cubes winds faces inward here.
    field = ndimage.gaussian_filter(solid.astype(np.float32), 0.8)
    del solid
    # The blur can seal a one-voxel channel and leave a hollow bubble behind it: fill those too.
    sealed = ndimage.binary_fill_holes(field >= 0.5) & (field < 0.5)
    field[sealed] = 1.0
    del sealed
    verts, faces, _, _ = marching_cubes(field, level=0.5, spacing=(pitch,) * 3)
    del field
    verts += origin + pitch / 2
    out = trimesh.Trimesh(verts, faces[:, ::-1], process=True)
    out, loose = _drop_slivers(out, min_volume=1.0 / mm_per_unit**3, min_share=0.002)

    target = int(min(1_000_000, max(200_000, len(F))))
    if len(out.faces) > target:
        out = _decimate(out, target)

    # Last, so the self-intersection guard sees the surface that ships (edge collapse can fold it too).
    rv = np.ascontiguousarray(ref.vertices, dtype=np.float64)
    rf = np.ascontiguousarray(ref.faces, dtype=np.int64)
    out, snapped = _snap_to_original(out, rv, rf, reach=1.5 * pitch, mm_per_unit=mm_per_unit)

    pts, _ = trimesh.sample.sample_surface(out, 30_000, seed=SEED)
    dist = np.sqrt(igl.point_mesh_squared_distance(np.ascontiguousarray(pts), rv, rf)[0]) * mm_per_unit
    info: dict[str, Any] = {
        "voxelMm": round(pitch * mm_per_unit, 3),
        "bridgedMm": round(2 * n_close * pitch * mm_per_unit, 2),
        "piecesDropped": int(n_pieces - len(keep)) + loose,
        "snappedShare": round(snapped, 3),
        "deviationMm": {
            "mean": round(float(dist.mean()), 3),
            "p95": round(float(np.percentile(dist, 95)), 3),
            "max": round(float(dist.max()), 3),
        },
    }
    return out, info


def _snap_to_original(mesh, rv, rf, reach: float, mm_per_unit: float):
    """Move vertices back onto the original surface where it is near: the voxels' blur goes, detail returns.

    Only positions change, never which vertices a face uses, so the shell stays closed. Two things
    could still spoil it, and both are undone vertex by vertex: two vertices landing on one point
    (a file format that welds by position, like STL, would fuse them) and a face turning over.
    Holes the solid bridged are farther than `reach` from the original, so they keep their new surface.
    """
    import igl
    import numpy as np
    import trimesh

    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces)
    d2, fi, closest = igl.point_mesh_squared_distance(np.ascontiguousarray(verts), rv, rf)
    # Only onto the side of the original the vertex faces: a thin sheet (a wing, a cloak) is wrapped
    # by the solid on both sides, and snapping both onto the same sheet would leave a zero-thickness wall.
    rn = np.cross(rv[rf[:, 1]] - rv[rf[:, 0]], rv[rf[:, 2]] - rv[rf[:, 0]])
    rn /= np.linalg.norm(rn, axis=1, keepdims=True) + 1e-30
    facing = np.einsum("ij,ij->i", rn[fi], mesh.vertex_normals) > 0.3
    move = (d2 < reach * reach) & facing
    before_n = mesh.face_normals.copy()
    tol = reach * 1e-3

    for _ in range(4):
        new = np.where(move[:, None], closest, verts)
        # vertices that would share a point
        keys = np.round(new / tol).astype(np.int64)
        _, inverse, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
        clash = move & (counts[inverse.ravel()] > 1)
        # faces that would turn over, fold sharply or collapse
        tri = new[faces]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-30
        flipped = np.einsum("ij,ij->i", n, before_n) < 0.35  # turned past ~70°: a fold in the making
        bad = clash.copy()
        bad[faces[flipped].ravel()] = True
        bad &= move
        if not bad.any():
            break
        move &= ~bad

    # Where snapped and unsnapped neighbours meet, the surface can fold through itself without any
    # face turning over: find those faces and put them and their neighbours back, until none are left.
    for _ in range(4):
        crossing = _self_intersecting(np.where(move[:, None], closest, verts), faces, mm_per_unit)
        crossing &= move[faces].any(axis=1)  # the rebuild's own hairline contacts aren't the snap's doing
        if not crossing.any():
            break
        ring = np.zeros(len(verts), dtype=bool)
        ring[faces[crossing].ravel()] = True
        ring[faces[ring[faces].any(axis=1)].ravel()] = True
        move &= ~ring
    else:
        move[:] = False  # still folded: keep the plain rebuild rather than ship a crossed surface

    out = trimesh.Trimesh(np.where(move[:, None], closest, verts), faces, process=False)
    return out, float(move.mean())


def _self_intersecting(verts, faces, mm_per_unit: float):
    import numpy as np
    import pymeshlab

    # Checked as a slicer sees it: in mm, rounded to float32 like the file. Surfaces that merely touch
    # register or not depending on rounding, so it looks twice, from two offsets, and counts either.
    f = np.ascontiguousarray(faces, dtype=np.int32)
    hit = np.zeros(len(f), dtype=bool)
    for shift in (0.0, 37.31):
        v = (verts * mm_per_unit + shift).astype(np.float32).astype(np.float64)
        ms = pymeshlab.MeshSet()
        ms.add_mesh(pymeshlab.Mesh(v, f))
        ms.compute_selection_by_self_intersections_per_face()
        hit |= ms.current_mesh().face_selection_array()  # read now: the view dies with ms
    return hit


def _drop_slivers(mesh, min_volume: float = 0.0, min_share: float = 1e-4):
    """Marching cubes and edge collapse leave tiny flat pieces glued on, and a part can come loose
    when the blur thins its neck: a print has no use for either. Returns the mesh and how many went."""
    import trimesh

    parts = mesh.split(only_watertight=False)
    if len(parts) <= 1:
        return mesh, 0
    biggest = max(abs(p.volume) for p in parts)
    kept = [p for p in parts if len(p.faces) >= 8 and abs(p.volume) >= max(biggest * min_share, min_volume)]
    # No merge_vertices: after the snap two kept pieces could share a point, and fusing them breaks the shell.
    return trimesh.util.concatenate(kept), len(parts) - len(kept)


def _decimate(mesh, target_faces: int):
    import pymeshlab
    import trimesh

    ms = pymeshlab.MeshSet()
    ms.add_mesh(pymeshlab.Mesh(mesh.vertices, mesh.faces))
    ms.meshing_decimation_quadric_edge_collapse(
        targetfacenum=target_faces, preservetopology=True, preservenormal=True, qualitythr=0.5
    )
    cur = ms.current_mesh()
    out = _drop_slivers(trimesh.Trimesh(cur.vertex_matrix(), cur.face_matrix(), process=False))[0]
    return out if out.is_watertight else mesh  # never trade the guarantee for a smaller file
