"""Turn diagonals: two neighbouring triangles make a four-sided patch, and its diagonal can run either way over
the same four corners. The cut takes whichever way the collapses left; here each pair takes the way that lies on
the original better. Same vertices, same number of triangles, same file size: only the index buffers change.

Checked 2026-11-05 at the exam budgets: closer up close on 14 of 20 models, about the same on 5, one a little
further by the number only (TRELLIS bust .87 -> 1.08, the same to the eye); the operative's mask visibly cleaner.
Folds stay (they need even triangles, see the exam notes). Deterministic: no random numbers, pairs in a fixed order.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

COMPONENT = {5121: "uint8", 5123: "uint16", 5125: "uint32"}
PASSES = 6
# A pair is turned when the new pair's normals disagree with the original's at least this much less...
GAIN = 0.85
# ...and the surface moves no further from it than this.
DISTANCE_SLACK = 1.1
# A turn may not leave a triangle with a smaller corner than this (degrees), unless the pair already had one.
NEEDLE_DEG = 8.0


def _samples():
    import numpy as np

    bary = np.array([[1, 1, 1], [4, 1, 1], [1, 4, 1], [1, 1, 4], [2, 2, 1], [2, 1, 2], [1, 2, 2]], float)
    return bary / bary.sum(1, keepdims=True)


def _read(path: Path) -> tuple[bytes, dict, int]:
    raw = path.read_bytes()
    length = struct.unpack("<I", raw[12:16])[0]
    return raw, json.loads(raw[20:20 + length]), 20 + length + 8


def _worlds(gltf: dict) -> dict[int, Any]:
    """Each node's world matrix."""
    import numpy as np

    def local(node):
        if "matrix" in node:
            return np.array(node["matrix"], float).reshape(4, 4).T
        m = np.eye(4)
        x, y, z, w = node.get("rotation", [0, 0, 0, 1])
        m[:3, :3] = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
        m[:3, :3] = m[:3, :3] @ np.diag(node.get("scale", [1, 1, 1]))
        m[:3, 3] = node.get("translation", [0, 0, 0])
        return m

    out: dict[int, Any] = {}

    def walk(i, parent):
        out[i] = parent @ local(gltf["nodes"][i])
        for child in gltf["nodes"][i].get("children", []):
            walk(child, out[i])

    for scene in gltf.get("scenes", []):
        for root in scene.get("nodes", []):
            walk(root, np.eye(4))
    return out


def _faces(V, T):
    """Unit normals and areas."""
    import numpy as np

    cross = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])
    area = np.linalg.norm(cross, axis=1) / 2
    return cross / np.maximum(area[:, None] * 2, 1e-20), area


def _min_angle(V, T):
    import numpy as np

    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    out = np.full(len(T), 180.0)
    for p, q, r in ((a, b, c), (b, c, a), (c, a, b)):
        u, v = q - p, r - p
        cos = (u * v).sum(1) / np.maximum(np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1), 1e-20)
        out = np.minimum(out, np.degrees(np.arccos(np.clip(cos, -1, 1))))
    return out


class _Cost:
    """Per triangle, area-weighted: how far its normal disagrees with the original's, and its squared distance
    to the original, from seven points on it. Remembered per triangle (by its corners)."""

    def __init__(self, V, original):
        self.V, self.original, self.seen, self.bary = V, original, {}, _samples()

    def get(self, T):
        import numpy as np

        HV, HF, Hn, tree = self.original
        # rotated to start at the smallest corner, which keeps the winding (sorted corners lost it)
        keys = [tuple(t[t.index(min(t)):] + t[:t.index(min(t))]) for t in T.tolist()]
        todo = sorted({k for k in keys if k not in self.seen})
        if todo:
            A = np.array(todo)
            n, area = _faces(self.V, A)
            a, b, c = self.V[A[:, 0]], self.V[A[:, 1]], self.V[A[:, 2]]
            w = self.bary
            points = (a[:, None] * w[:, 0, None] + b[:, None] * w[:, 1, None] + c[:, None] * w[:, 2, None]).reshape(-1, 3)
            d2, nearest, _ = tree.squared_distance(HV, HF, points)
            # Signed: near a surface that faces the other way counts as far off. A thin wall has two such sides
            # close together; unsigned, the harbour's outer wall was pulled in through its inner side (2026-11-07).
            dots = (Hn[nearest] * np.repeat(n, len(w), 0)).sum(1).reshape(-1, len(w))
            normal_err = (1 - dots).mean(1) * area
            distance = d2.reshape(-1, len(w)).mean(1) * area
            for k, x, y in zip(todo, normal_err.tolist(), distance.tolist()):
                self.seen[k] = (x, y)
        values = np.array([self.seen[k] for k in keys])
        return values[:, 0], values[:, 1]


def _turn(V, T, original) -> tuple[Any, int]:
    import numpy as np

    cost = _Cost(V, original)
    total = 0
    for _ in range(PASSES):
        by_edge: dict[tuple[int, int], list] = {}
        for t, (a, b, c) in enumerate(T.tolist()):
            for u, v, w in ((a, b, c), (b, c, a), (c, a, b)):
                by_edge.setdefault((min(u, v), max(u, v)), []).append((t, u, v, w))
        pairs = []
        for (x, y), faces in sorted(by_edge.items()):
            if len(faces) != 2:
                continue
            (t1, u1, v1, c), (t2, u2, v2, d) = faces
            # wound the same way, two different far corners, and the other diagonal not an edge already
            if u1 != v2 or v1 != u2 or c == d or (min(c, d), max(c, d)) in by_edge:
                continue
            pairs.append((t1, t2, u1, v1, c, d))
        if not pairs:
            break
        P = np.array(pairs)
        old1, old2 = P[:, [2, 3, 4]], P[:, [3, 2, 5]]
        new1, new2 = np.c_[P[:, 4], P[:, 2], P[:, 5]], np.c_[P[:, 5], P[:, 3], P[:, 4]]
        n_o1, a_o1 = _faces(V, old1)
        n_o2, a_o2 = _faces(V, old2)
        facing = n_o1 * a_o1[:, None] + n_o2 * a_o2[:, None]
        facing /= np.maximum(np.linalg.norm(facing, axis=1, keepdims=True), 1e-20)
        n1, a1 = _faces(V, new1)
        n2, a2 = _faces(V, new2)
        # not folded over: both new faces look the way the pair did; no new needles
        ok = ((n1 * facing).sum(1) > 0.3) & ((n2 * facing).sum(1) > 0.3) & (a1 > 1e-14) & (a2 > 1e-14)
        angle_old = np.minimum(_min_angle(V, old1), _min_angle(V, old2))
        angle_new = np.minimum(_min_angle(V, new1), _min_angle(V, new2))
        ok &= angle_new >= np.minimum(angle_old, NEEDLE_DEG)
        idx = np.nonzero(ok)[0]
        if not len(idx):
            break
        no1, do1 = cost.get(old1[idx])
        no2, do2 = cost.get(old2[idx])
        nn1, dn1 = cost.get(new1[idx])
        nn2, dn2 = cost.get(new2[idx])
        before, after = no1 + no2, nn1 + nn2
        better = (after < GAIN * before) & (dn1 + dn2 <= (do1 + do2) * DISTANCE_SLACK + 1e-16)
        pick = idx[better]
        order = np.argsort(-(before - after)[better], kind="stable")
        used = np.zeros(len(T), bool)
        done = 0
        for k in order.tolist():
            t1, t2, u, v, c, d = pairs[pick[k]]
            if used[t1] or used[t2]:
                continue
            used[t1] = used[t2] = True
            T[t1] = (c, u, d)
            T[t2] = (d, v, c)
            done += 1
        total += done
        if not done:
            break
    return T, total


def turn_diagonals(original: Path, cut: Path, shift) -> dict[str, int]:
    """Turns the cut's diagonals in place, against the original (shift: how far the cut was moved onto the floor).
    The original's search tree is built once per call: built per query it took 97 % of the time (knight 203 -> 11 s)."""
    import igl
    import numpy as np

    from studio_bridge.game_look import _load

    raw, gltf, bin0 = _read(cut)
    if set(gltf.get("extensionsUsed", [])) & {"KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_mesh_quantization"}:
        return {"turned": 0, "faces": 0}
    m = _load(original, 4)
    HV = np.ascontiguousarray(m["V"] + np.asarray(shift, float))
    HF = np.ascontiguousarray(m["F"], np.int64)
    Hn, _ = _faces(HV, HF)
    tree = igl.AABB()
    tree.init(HV, HF)
    worlds = _worlds(gltf)
    data = bytearray(raw)
    turned = faces = 0
    done: set[int] = set()
    for ni, node in enumerate(gltf.get("nodes", [])):
        if "mesh" not in node or ni not in worlds or node["mesh"] in done:
            continue
        done.add(node["mesh"])
        for prim in gltf["meshes"][node["mesh"]]["primitives"]:
            if prim.get("mode", 4) != 4 or "indices" not in prim:
                continue
            pa, ia = gltf["accessors"][prim["attributes"]["POSITION"]], gltf["accessors"][prim["indices"]]
            pv, iv = gltf["bufferViews"][pa["bufferView"]], gltf["bufferViews"][ia["bufferView"]]
            at = bin0 + pv.get("byteOffset", 0) + pa.get("byteOffset", 0)
            stride = pv.get("byteStride", 12)
            P = np.array([struct.unpack_from("<3f", raw, at + k * stride) for k in range(pa["count"])], float)
            W = worlds[ni]
            V = P @ W[:3, :3].T + W[:3, 3]
            kind = np.dtype(COMPONENT[ia["componentType"]])
            where = bin0 + iv.get("byteOffset", 0) + ia.get("byteOffset", 0)
            T = np.frombuffer(raw, kind, ia["count"], where).astype(np.int64).reshape(-1, 3).copy()
            T, n = _turn(V, T, (HV, HF, Hn, tree))
            turned += n
            faces += len(T)
            data[where:where + ia["count"] * kind.itemsize] = T.reshape(-1).astype(kind).tobytes()
    cut.write_bytes(bytes(data))
    return {"turned": turned, "faces": faces}
