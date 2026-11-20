"""Bend judge v3, fast (same numbers as judge3.py: rigid rings skipped, only the needed points posed):
Bend judge v3: the poses of v2 (published protocol: each joint 30 deg about x, y, z, children along, LBS), the
distortion as the original as-rigid-as-possible energy of Sorkine & Alexa 2007 on each vertex's ring:
E_i = sum_j w_ij |e'_ij - R_i e_ij|^2 with the best rotation R_i, w_ij the cotangent weights of the intrinsic Delaunay
triangulation (positive, so obtuse and needle triangles of AI meshes don't flip or blow up them). It is in length
units, not divided by a triangle's height like the per-triangle gradient of v2, whose needles blew up (operative 274).
Sum over vertices of the max over poses, divided by the surface area: the mean of |J - R|^2 over the surface, the same
quantity for any mesh density. Lower is better; only ranks tries of the same model. No cut-offs of ours.
python judge3.py <rigged.glb> [angle_deg]"""
import json
import os
import sys

# The bones run in threads; OpenBLAS (numpy's LAPACK) starts its own threads inside each call and, past its
# MAX_THREADS (24 in numpy's build), crashes (seen: exit 139 on the 9th run). One BLAS thread per call, as
# joblib/scikit-learn do for outer threading. Read when numpy loads, so a caller that imported numpy first
# must set it in its environment (autorig runs this file as its own process).
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import igl
import numpy as np
import scipy.sparse as sp

from judge import rig, rot
from ourxfer import flat_free

AXES = np.eye(3)


def judge4(path, angle=30.0, detail=False):
    V, F, W, heads, kids, names = rig(path)
    W = W / np.maximum(W.sum(1, keepdims=True), 1e-12)
    J = len(heads)
    sub = []
    for k in range(J):
        s, stack = [], [k]
        while stack:
            i = stack.pop()
            s.append(i)
            stack += kids[i]
        sub.append(s)
    dbl = np.linalg.norm(np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]), axis=1)
    Fa = flat_free(V, F)
    area = 0.5 * dbl.sum()
    L = sp.triu(igl.intrinsic_delaunay_cotmatrix(V, Fa)[0].tocsr(), 1).tocoo()
    keep = L.data > 0
    I, Jn, w = L.row[keep], L.col[keep], L.data[keep]
    I, Jn, w = np.concatenate([I, Jn]), np.concatenate([Jn, I]), np.concatenate([w, w])  # both directions
    e = V[Jn] - V[I]
    worst = np.zeros(len(V))
    a = np.radians(angle)

    def bone(k):
        """-> (ring centres, their max energy over the bone's three poses) or None."""
        ws = W[:, sub[k]].sum(1)
        moved = ws > 1e-6
        if not moved.any():
            return None
        wse = np.where(moved, ws, 0.0)  # what the pose applies: unmoved points stay put
        # a ring whose points all stay put (0) or all turn with the bone (1) moves rigidly: its energy is exactly 0
        bent = (wse[I] != wse[Jn]) | ((wse[I] != 0) & (wse[I] != 1))
        act = np.zeros(len(V), bool)
        act[I[bent]] = True
        sel = np.flatnonzero(act[I])
        if not len(sel):
            return None
        Is, Js, ws_e, es = I[sel], Jn[sel], w[sel], e[sel]
        vi, li = np.unique(Is, return_inverse=True)
        ends, inv = np.unique(np.concatenate([Is, Js]), return_inverse=True)
        lI, lJ = inv[: len(sel)], inv[len(sel):]
        Ve, we = V[ends], wse[ends, None]
        rest = np.bincount(li, weights=ws_e * (es * es).sum(1), minlength=len(vi))
        best = np.zeros(len(vi))
        for ax in AXES:
            R = rot(ax, a)
            Pe = Ve + we * ((Ve - heads[k]) @ R.T + heads[k] - Ve)
            ed = Pe[lJ] - Pe[lI]
            S = np.empty((len(vi), 3, 3))
            for p in range(3):
                for q in range(3):
                    S[:, p, q] = np.bincount(li, weights=ws_e * es[:, p] * ed[:, q], minlength=len(vi))
            # min over rotations of sum w|e' - R e|^2 = sum w(|e'|^2 + |e|^2) - 2 (s1 + s2 + sign(det S) s3)
            # (Kabsch / orthogonal Procrustes): only the singular values are needed, not the rotation
            sv = np.linalg.svd(S, compute_uv=False)
            tr = sv[:, 0] + sv[:, 1] + np.sign(np.linalg.det(S)) * sv[:, 2]
            moved_len = np.bincount(li, weights=ws_e * (ed * ed).sum(1), minlength=len(vi))
            best = np.maximum(best, np.maximum(moved_len + rest - 2 * tr, 0.0))
        return vi, best

    from concurrent.futures import ThreadPoolExecutor  # numpy's LAPACK and bincount let other threads run
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:
        for got in pool.map(bone, range(J)):
            if got is not None:  # max over poses: the same whatever order the bones finish in
                worst[got[0]] = np.maximum(worst[got[0]], got[1])
    out = {"bones": J, "angle": angle, "distortion": round(float(worst.sum() / area), 6)}
    if detail:
        o = np.sort(worst)[::-1]
        out["top0.1%share"] = round(float(o[: max(1, len(o) // 1000)].sum() / max(o.sum(), 1e-30)), 3)
    return out


if __name__ == "__main__":
    print(json.dumps(judge4(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 30.0, True)))
