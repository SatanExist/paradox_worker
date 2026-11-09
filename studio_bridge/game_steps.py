"""Smooth steps: a cut sometimes bends sharply across an edge where the original is smooth, a narrow step that
reads as a thin dark line (the dragon's chest, the snowman, the mech's belly plate: exam 8, 2026-11-08). Here such
corners move a little (onto the original, or towards their neighbours' middle) when that halves the steps around
them without turning the surface further from the original. Same triangles, same file size, only positions move.

Checked 2026-11-08/09 on 6 models at the exam budgets: the user's slivers on the dragon, snowman and mech gone,
no new dents seen, the user marked all of them "great". Not fixed here: thin details on too few triangles (the
operative's eye slit, the mech's barrels) and needle streaks on bumpy TRELLIS surfaces (a needle rule was tried and
showed nothing to the eye). Deterministic: no random numbers, corners in a fixed order.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

from studio_bridge.game_turn import COMPONENT, _faces, _read, _samples, _worlds

PASSES = 4
STEP_CUT = 30.0  # the cut bends across an edge more than this (degrees)...
STEP_SLACK = 20.0  # ...and more than the original under it by this much
BAD_DOT = -0.3  # a triangle facing this far away from the original next to it counts as folded over
NEAR = 0.01  # ...when it is this close to it (share of the model's size)


class _Original:
    def __init__(self, path: Path, shift):
        import igl
        import numpy as np

        from studio_bridge.game_look import _load

        m = _load(path, 4)
        self.V = np.ascontiguousarray(m["V"] + np.asarray(shift, float))
        self.F = np.ascontiguousarray(m["F"], np.int64)
        self.n, _ = _faces(self.V, self.F)
        self.tree = igl.AABB()
        self.tree.init(self.V, self.F)
        self.size = float(np.linalg.norm(self.V.max(0) - self.V.min(0)))

    def near(self, P):
        import numpy as np

        d2, i, c = self.tree.squared_distance(self.V, self.F, np.ascontiguousarray(P, float))
        return np.sqrt(d2), i, c


class _Cut:
    """The cut's triangles over all its parts, with corners at the same place welded (they move together, so no
    cracks open at seams). Positions go back into the file in each part's own frame."""

    def __init__(self, path: Path):
        import numpy as np

        self.path = path
        self.raw, self.g, self.bin0 = _read(path)
        self.data = bytearray(self.raw)
        worlds = _worlds(self.g)
        self.prims: list[dict[str, Any]] = []
        seen: set[int] = set()
        for ni, node in enumerate(self.g.get("nodes", [])):
            if "mesh" not in node or ni not in worlds or node["mesh"] in seen:
                continue
            seen.add(node["mesh"])
            for prim in self.g["meshes"][node["mesh"]]["primitives"]:
                if prim.get("mode", 4) != 4 or "indices" not in prim:
                    continue
                pa = self.g["accessors"][prim["attributes"]["POSITION"]]
                ia = self.g["accessors"][prim["indices"]]
                pv, iv = self.g["bufferViews"][pa["bufferView"]], self.g["bufferViews"][ia["bufferView"]]
                at = self.bin0 + pv.get("byteOffset", 0) + pa.get("byteOffset", 0)
                stride = pv.get("byteStride", 12)
                P = np.array([struct.unpack_from("<3f", self.raw, at + k * stride) for k in range(pa["count"])], float)
                W = worlds[ni]
                kind = np.dtype(COMPONENT[ia["componentType"]])
                where = self.bin0 + iv.get("byteOffset", 0) + ia.get("byteOffset", 0)
                T = np.frombuffer(self.raw, kind, ia["count"], where).astype(np.int64).reshape(-1, 3)
                nrm = None
                if "NORMAL" in prim["attributes"]:
                    na = self.g["accessors"][prim["attributes"]["NORMAL"]]
                    nv = self.g["bufferViews"][na["bufferView"]]
                    nrm = (self.bin0 + nv.get("byteOffset", 0) + na.get("byteOffset", 0), nv.get("byteStride", 12))
                self.prims.append(dict(pa=pa, at=at, stride=stride, P=P, W=W, V=P @ W[:3, :3].T + W[:3, 3], T=T, nrm=nrm))
        V = np.concatenate([p["V"] for p in self.prims])
        self.off = np.cumsum([0] + [len(p["V"]) for p in self.prims])
        scale = float(np.linalg.norm(V.max(0) - V.min(0))) or 1.0
        key = np.round(V / (scale * 1e-7)).astype(np.int64)
        _, first, gid = np.unique(key, axis=0, return_index=True, return_inverse=True)
        self.gid = gid.reshape(-1)
        self.X = V[first].copy()
        self.X0 = self.X.copy()
        self.G = np.concatenate([self.gid[p["T"] + self.off[k]] for k, p in enumerate(self.prims)])

    def save(self) -> None:
        import numpy as np

        moved = np.any(self.X != self.X0, axis=1)
        for k, p in enumerate(self.prims):
            gl = self.gid[self.off[k]:self.off[k + 1]]
            hit = np.nonzero(moved[gl])[0]
            if not len(hit):
                continue
            inv = np.linalg.inv(p["W"])
            local = self.X[gl[hit]] @ inv[:3, :3].T + inv[:3, 3]
            p["P"][hit] = local
            for j, q in zip(hit.tolist(), local.tolist()):
                struct.pack_into("<3f", self.data, p["at"] + j * p["stride"], *q)
            p["pa"]["min"] = p["P"].min(0).astype(np.float32).astype(float).tolist()
            p["pa"]["max"] = p["P"].max(0).astype(np.float32).astype(float).tolist()
            if p["nrm"]:
                # corners next to a moved one get their normal again from their own faces (sharp splits kept)
                T = p["T"]
                touch = np.zeros(len(p["P"]), bool)
                touch[T[np.any(moved[gl[T]], axis=1)].reshape(-1)] = True
                cross = np.cross(p["P"][T[:, 1]] - p["P"][T[:, 0]], p["P"][T[:, 2]] - p["P"][T[:, 0]])
                acc = np.zeros_like(p["P"])
                for c in range(3):
                    np.add.at(acc, T[:, c], cross)
                at, stride = p["nrm"]
                for j in np.nonzero(touch)[0].tolist():
                    length = np.linalg.norm(acc[j])
                    if length > 0:
                        struct.pack_into("<3f", self.data, at + j * stride, *(acc[j] / length))
        # min/max may have grown the JSON: write the container again
        js = json.dumps(self.g, separators=(",", ":")).encode()
        js += b" " * (-len(js) % 4)
        old = struct.unpack("<I", self.raw[12:16])[0]
        rest = bytes(self.data[20 + old:])
        self.path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + len(rest))
                              + struct.pack("<II", len(js), 0x4E4F534A) + js + rest)


def _edges(G) -> dict[tuple[int, int], list[int]]:
    by: dict[tuple[int, int], list[int]] = {}
    for t, (a, b, c) in enumerate(G.tolist()):
        for u, v in ((a, b), (b, c), (c, a)):
            by.setdefault((min(u, v), max(u, v)), []).append(t)
    return {e: ts for e, ts in by.items() if len(ts) == 2}


def _points(A, B, C):
    """Seven points on each triangle (corners A, B, C of shape (..., 3)), flattened."""
    w = _samples()
    return (A[..., None, :] * w[:, 0, None] + B[..., None, :] * w[:, 1, None] + C[..., None, :] * w[:, 2, None]).reshape(-1, 3)


def _cross_faces(A, B, C):
    import numpy as np

    cross = np.cross(B - A, C - A)
    area = np.linalg.norm(cross, axis=-1) / 2
    return cross / np.maximum(area[..., None] * 2, 1e-20), area


def _angles(n, on, a, b):
    import numpy as np

    cut = np.degrees(np.arccos(np.clip((n[..., a, :] * n[..., b, :]).sum(-1), -1, 1)))
    org = np.degrees(np.arccos(np.clip((on[..., a, :] * on[..., b, :]).sum(-1), -1, 1)))
    return np.where(cut > STEP_CUT, np.maximum(cut - org - STEP_SLACK, 0), 0)


def _steps(X, G, E, o) -> list[tuple[int, int]]:
    """Edges where the cut makes a step the original has not got."""
    import numpy as np

    keys = sorted(E)
    if not keys:
        return []
    pairs = np.array([E[k] for k in keys])
    ids = np.unique(pairs)
    T = G[ids]
    n, _ = _cross_faces(X[T[:, 0]], X[T[:, 1]], X[T[:, 2]])
    _, ii, _ = o.near(_points(X[T[:, 0]], X[T[:, 1]], X[T[:, 2]]))
    on = o.n[ii].reshape(-1, 7, 3).mean(1)
    on /= np.maximum(np.linalg.norm(on, axis=1, keepdims=True), 1e-20)
    pos = np.searchsorted(ids, pairs)
    s = _angles(n, on, pos[:, 0], pos[:, 1])
    return [k for k, x in zip(keys, s.tolist()) if x > 0]


def _corner(X, G, v, ring, pairs, o):
    """The best new place for corner v, or None: all five candidate places and the current one are judged in one
    query of the original (one by one, the queries took most of the time)."""
    import numpy as np

    R = G[ring]
    others = sorted(set(R.reshape(-1).tolist()) - {v})
    mid = X[others].mean(0)
    _, _, onto = o.near(np.stack([X[v], mid]))
    places = np.stack([X[v], onto[0], mid, onto[1], (X[v] + onto[0]) / 2, (X[v] + onto[1]) / 2])
    K = len(places)
    ids = np.unique(np.r_[ring, pairs.reshape(-1)])  # the ring and the triangles across its edges
    T = G[ids]
    corners = np.broadcast_to(X[T], (K,) + T.shape + (3,)).copy()  # (K, triangles, 3 corners, xyz)
    corners[:, T == v] = places[:, None, :]
    A, B, C = corners[..., 0, :], corners[..., 1, :], corners[..., 2, :]
    n, area = _cross_faces(A, B, C)
    rk = np.searchsorted(ids, ring)
    centre = corners[:, rk].mean(-2)
    t, r = len(ids), len(ring)
    # triangles without v are the same in every candidate: their points are asked once
    moving = np.any(T == v, axis=1)
    mv, st = np.nonzero(moving)[0], np.nonzero(~moving)[0]
    d, i, _ = o.near(np.r_[centre.reshape(-1, 3), _points(A[:, mv], B[:, mv], C[:, mv]), _points(A[0, st], B[0, st], C[0, st])])
    dc, ic = d[:K * r].reshape(K, r), i[:K * r].reshape(K, r)
    m = K * r + K * len(mv) * 7
    ds, js = np.empty((K, t, 7)), np.empty((K, t, 7), np.int64)
    ds[:, mv], js[:, mv] = d[K * r:m].reshape(K, len(mv), 7), i[K * r:m].reshape(K, len(mv), 7)
    ds[:, st], js[:, st] = d[m:].reshape(len(st), 7), i[m:].reshape(len(st), 7)
    on = o.n[js].mean(2)
    on /= np.maximum(np.linalg.norm(on, axis=-1, keepdims=True), 1e-20)
    pos = np.searchsorted(ids, pairs)
    step = _angles(n, on, pos[:, 0], pos[:, 1]).sum(-1)
    nr, ar = n[:, rk], area[:, rk]
    folded = (((nr * o.n[ic]).sum(-1) < BAD_DOT) & (dc < NEAR * o.size)).sum(-1)
    err = ((1 - (o.n[js[:, rk]] * nr[:, :, None, :]).sum(-1)).mean(-1) * ar).sum(-1)
    dist = ds[:, rk].mean(-1).mean(-1)
    if step[0] <= 0:
        return None
    best = None
    for k in range(1, K):
        if (ar[k] < 1e-6 * ar[0].max()).any() or folded[k] > folded[0]:
            continue
        if dist[k] > max(dist[0] * 1.5, 1e-4 * o.size):
            continue
        score = (float(step[k]), float(err[k]))
        if step[k] < step[0] * 0.5 and err[k] <= err[0] * 1.05 and (best is None or score < best[0]):
            best = (score, places[k])
    return None if best is None else best[1]


def load_original(original: Path, shift) -> _Original:
    """The original moved like the cut (shift), with its search tree: build once, use for the turn and the steps."""
    return _Original(original, shift)


def smooth_steps(original: Path, cut: Path, shift, mesh: _Original | None = None) -> dict[str, int]:
    """Moves the cut's corners at steps the original has not got, in place (shift: how far the cut was moved onto
    the floor; `mesh`: the original already loaded with load_original). Returns how many steps there were and are,
    and how many corners moved."""
    raw, gltf, _ = _read(cut)
    if set(gltf.get("extensionsUsed", [])) & {"KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_mesh_quantization"}:
        return {"steps": 0, "left": 0, "moved": 0}
    import numpy as np

    o = mesh or _Original(original, shift)
    c = _Cut(cut)
    X, G = c.X, c.G
    E = _edges(G)
    bad = _steps(X, G, E, o)
    first = len(bad)
    by_corner: dict[int, list[int]] = {}
    for t, row in enumerate(G.tolist()):
        for v in row:
            by_corner.setdefault(v, []).append(t)
    moved = 0
    # A corner judged and left where it was gets the same answer again while nothing near it moves: skipped.
    settled: set[int] = set()

    def near_corners(v):
        ring_corners = set(G[by_corner[v]].reshape(-1).tolist())
        return {x for u in ring_corners for t in by_corner[u] for x in G[t].tolist()}

    for _ in range(PASSES):
        if not bad:
            break
        done = 0
        for v in sorted({x for e in bad for x in e}):
            if v in settled:
                continue
            ring = by_corner[v]
            ring_edges = sorted({(min(p, q), max(p, q)) for a, b, cc in G[ring].tolist() for p, q in ((a, b), (b, cc), (cc, a))} & E.keys())
            if not ring_edges:
                settled.add(v)
                continue
            place = _corner(X, G, v, np.array(ring), np.array([E[e] for e in ring_edges]), o)
            if place is None:
                settled.add(v)
            else:
                X[v] = place
                done += 1
                settled -= near_corners(v)
        moved += done
        if not done:
            break
        bad = _steps(X, G, E, o)
    if moved:
        c.save()
    return {"steps": first, "left": len(bad), "moved": moved}
