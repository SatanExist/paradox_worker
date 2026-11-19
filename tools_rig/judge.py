"""Bend judge: a range-of-motion (ROM) test of a rigged GLB, the check riggers run on skin weights.

Every bone in turn is bent 45 degrees four ways (both ways about the two axes square to the bone) about its own joint,
its children going along, and the skin follows by the file's own weights (linear blend skinning, as engines draw it).
A triangle is "torn" in a pose when one of its edges grows by more than 1 % of the model's diagonal (about 4 px in
our 384 px look views: a gap the eye sees). Right weights bend the skin smoothly near the joint, so an edge only
grows by a share of its own small length; a jump like that means part of the model hangs on the wrong bone (a leg on
an arm, a cape on a knee) or the weights jump between neighbours. Tiny edges stretched in place stay unseen and
don't count (a first try counted an edge doubling: it lit up weight noise all over dense models). Measured: the share of the surface that tears in at least one pose, the worst pose, and the mean
stretch (area-weighted |log edge ratio|, 0 = rigid) as a tie-break. No randomness: same file, same numbers.
The 1 % and 45 degrees are our choice (no published standard for judging a rig without a reference).
python judge.py <rigged.glb> [--pic out.png]"""
import json
import sys

import numpy as np

from ourxfer import acc, load

ANGLE = np.radians(45.0)
TORN = 0.01  # of the diagonal


def rot(axis, a):
    axis = axis / np.linalg.norm(axis)
    x, y, z = axis
    c, s, C = np.cos(a), np.sin(a), 1 - np.cos(a)
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                     [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                     [z * x * C - y * s, z * y * C + x * s, c + z * z * C]])


def rig(path):
    """-> rest vertices (bind space), faces, dense weights (n x J), joint heads (J x 3), children lists, names."""
    j, b = load(path)
    skin = j["skins"][0]
    joints = skin["joints"]
    ibm = acc(j, b, skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1).astype(np.float64)
    heads = np.array([np.linalg.inv(m)[:3, 3] for m in ibm])
    idx = {n: k for k, n in enumerate(joints)}
    kids = [[idx[c] for c in j["nodes"][n].get("children", []) if c in idx] for n in joints]
    V, F, W, off = [], [], [], 0
    for nd in j["nodes"]:
        if nd.get("skin") is None or "mesh" not in nd:
            continue
        for pr in j["meshes"][nd["mesh"]]["primitives"]:
            at = pr["attributes"]
            P = acc(j, b, at["POSITION"]).astype(np.float64)
            Fi = acc(j, b, pr["indices"]).reshape(-1, 3).astype(np.int64) if "indices" in pr else np.arange(len(P)).reshape(-1, 3)
            Jn = acc(j, b, at["JOINTS_0"]).astype(np.int64)
            Wn = acc(j, b, at["WEIGHTS_0"]).astype(np.float64)
            D = np.zeros((len(P), len(joints)))
            np.add.at(D, (np.repeat(np.arange(len(P)), 4), Jn.ravel()), Wn.ravel())
            V.append(P)
            F.append(Fi + off)
            W.append(D)
            off += len(P)
    return np.concatenate(V), np.concatenate(F), np.concatenate(W), heads, kids, [j["nodes"][n].get("name", "") for n in joints]


def judge(path):
    V, F, W, heads, kids, names = rig(path)
    W = W / np.maximum(W.sum(1, keepdims=True), 1e-12)
    J = len(heads)
    sub = []
    for k in range(J):  # each bone's subtree
        s, stack = [], [k]
        while stack:
            i = stack.pop()
            s.append(i)
            stack += kids[i]
        sub.append(s)
    e0 = np.stack([np.linalg.norm(V[F[:, (i + 1) % 3]] - V[F[:, i]], axis=1) for i in range(3)], 1)
    ok = e0.min(1) > 1e-9 * np.ptp(V, 0).max()
    area = 0.5 * np.linalg.norm(np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]), axis=1) * ok
    total = area.sum()
    gap = TORN * np.linalg.norm(np.ptp(V, 0))
    torn_any = np.zeros(len(F), bool)
    poses, worst = 0, (0.0, "")
    mean_sum = 0.0
    for k in range(J):
        tip = np.mean([heads[c] for c in kids[k]], 0) if kids[k] else None
        d = (tip - heads[k]) if tip is not None else (heads[k] - heads[parent]) if (parent := next((p for p in range(J) if k in kids[p]), None)) is not None else None
        if d is None or np.linalg.norm(d) < 1e-9:
            continue
        d = d / np.linalg.norm(d)
        ref = np.array([0.0, 1.0, 0.0]) if abs(d[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
        a1 = np.cross(d, ref)
        a1 /= np.linalg.norm(a1)
        a2 = np.cross(d, a1)
        ws = W[:, sub[k]].sum(1)
        moved = ws > 1e-6
        if not moved.any():
            continue
        tri = moved[F].any(1)
        Ft = F[tri]
        for axis, tag in ((a1, "a"), (a2, "b")):
            for sgn in (1, -1):
                R = rot(axis, sgn * ANGLE)
                P = V.copy()
                Pm = V[moved] - heads[k]
                P[moved] = V[moved] + ws[moved, None] * (Pm @ R.T + heads[k] - V[moved])
                e = np.stack([np.linalg.norm(P[Ft[:, (i + 1) % 3]] - P[Ft[:, i]], axis=1) for i in range(3)], 1)
                r = np.abs(np.log(np.maximum(e, 1e-12) / np.maximum(e0[tri], 1e-12))).max(1)
                r[~ok[tri]] = 0
                torn = ((e - e0[tri]).max(1) > gap) & ok[tri]
                torn_any[np.flatnonzero(tri)[torn]] = True
                share = area[tri][torn].sum() / total
                mean_sum += (area[tri] * r).sum() / total
                poses += 1
                if share > worst[0]:
                    worst = (share, f"{names[k]} {tag}{'+' if sgn > 0 else '-'}")
    return {"bones": J, "poses": poses, "tornPct": round(100 * area[torn_any].sum() / total, 3),
            "worstPose": worst[1], "worstPosePct": round(100 * worst[0], 3),
            "meanStretch": round(mean_sum / max(poses, 1), 5)}, (V, F, torn_any)


if __name__ == "__main__":
    res, (V, F, torn) = judge(sys.argv[1])
    print(json.dumps(res))
    if "--pic" in sys.argv:
        from PIL import Image
        S = 520
        out = Image.new("RGB", (2 * S, S), (30, 30, 30))
        c = V[F].mean(1)
        for col, (x, flip) in enumerate([(0, 1), (2, -1)]):
            X, Y = c[:, x] * flip, c[:, 1]
            lo = np.array([X.min(), Y.min()])
            kk = (S - 20) / max(np.ptp(X), np.ptp(Y))
            u = ((X - lo[0]) * kk + 10).astype(int)
            v = (S - 10 - (Y - lo[1]) * kk).astype(int)
            img = np.full((S, S, 3), 30, np.uint8)
            o = np.argsort(torn)
            img[v[o], u[o]] = np.where(torn[o, None], [255, 60, 40], [150, 150, 150]).astype(np.uint8)
            out.paste(Image.fromarray(img), (col * S, 0))
        out.save(sys.argv[sys.argv.index("--pic") + 1])
