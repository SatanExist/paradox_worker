"""Part a rig's skin where the generator fused body parts that move apart, and cap the openings.
Rule (envelope skinning, as Blender bone envelopes / 3ds Max Skin envelopes / Maya dropoff): a skin point may blend two
bones only if it lies inside the envelope of EVERY joint between them, i.e. the joints whose turning would pull the
two bones' copies of that point apart. Across one joint (parent and child) skin always blends. A joint's envelope = a ball of ENV x its limb radius (distance from the joint to
the nearest skin; ENV 2 = Blender's radius + equal fade distance). So an elbow point blends arm and forearm, a waist
pouch does not blend arm and chest (it is far from the shoulder), a fist on a thigh does not blend hand and leg.
1. Each face's leading bone = most weight over its corners. An edge between faces is cut when its point may not blend
   the two leading bones. Around each point faces joined by uncut edges share one corner (wedge).
2. Every point keeps the weighted bones that all faces around it may blend with their leading bone (one set: the skin
   stays closed). A point with none parts along the cut edges; a wedge still with none parts by face lead.
3. Closed one-sided openings are capped by a minimum-area triangulation (Liepa 2003 step 1); slits stay open.
python parts.py <rig.glb> <out.glb>   (env ENV default 2; NOCAP=1 skips caps; DIAG=1 prints each cap)"""
import json
import os
import struct
import sys
from collections import deque
from pathlib import Path

import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).parent))
from ourxfer import acc, load  # noqa: E402
from judge import rig  # noqa: E402
from envelope import Envelope  # noqa: E402

ENV = float(os.environ.get("ENV", "2"))
MAXRIM = 600
src, out = sys.argv[1:3]
V, F, W, heads, kids, names = rig(src)
J = len(names)
adj = [[] for _ in range(J)]
for p, ks in enumerate(kids):
    for c in ks:
        adj[p].append(c)
        adj[c].append(p)
dist = np.full((J, J), 99)
for s_ in range(J):
    dist[s_, s_] = 0
    q = deque([s_])
    while q:
        x = q.popleft()
        for y in adj[x]:
            if dist[s_, y] == 99:
                dist[s_, y] = dist[s_, x] + 1
                q.append(y)
_, wv = np.unique(np.round(V, 6), axis=0, return_inverse=True)
wv = wv.ravel()
nw = int(wv.max()) + 1
Fw = wv[F]
nf = len(F)
lead = W[F].sum(1).argmax(1)
# edges shared by two faces
a = Fw.ravel()
b = Fw[:, [1, 2, 0]].ravel()
fid = np.repeat(np.arange(nf), 3)
key = np.minimum(a, b).astype(np.int64) * nw + np.maximum(a, b)
o = np.argsort(key, kind="stable")
k_ = key[o]
pr = np.nonzero(k_[1:] == k_[:-1])[0]
if len(pr):
    pr = pr[np.r_[True, pr[1:] != pr[:-1] + 1]]  # first two faces of a non-manifold edge
h1, h2 = o[pr], o[pr + 1]
Vw = np.zeros((nw, 3))
Vw[wv] = V
rule = Envelope(Vw, heads, kids, ENV)
par, env = rule.par, rule.env
print("joint envelopes (x limb radius", ENV, "):", " ".join(f"{names[i]}={env[i]:.3f}" for i in range(J) if par[i] >= 0
                                                         and names[i].endswith(("Arm", "ForeArm", "UpLeg", "Spine2"))))
may_blend = rule.may_blend


cut = ~may_blend(Vw[a[h1]], lead[fid[h1]], lead[fid[h2]])
keep = ~cut
# split the surface only along cut edges (like Blender's Edge Split): around each point, faces joined through an
# uncut edge share one corner ("wedge"); a cut edge separates wedges. Corner index = f*3+k.
corner_a = lambda h: (h // 3) * 3 + (h % 3)  # noqa: E731  corner of half-edge h at its start point
corner_b = lambda h: (h // 3) * 3 + (h % 3 + 1) % 3  # noqa: E731  ... at its end point
h1k, h2k = h1[keep], h2[keep]
same_a = a[h1k] == a[h2k]  # the two faces may run the edge the same way (non-oriented mesh) or opposite ways
u = np.concatenate([corner_a(h1k), corner_b(h1k)])
v = np.concatenate([np.where(same_a, corner_a(h2k), corner_b(h2k)), np.where(same_a, corner_b(h2k), corner_a(h2k))])
A = sp.coo_matrix((np.ones(len(u)), (u, v)), (nf * 3, nf * 3))
nwedge, wedge = connected_components(A + A.T, directed=False)
print(f"ENV {ENV}: cut edges {int(cut.sum())} of {len(h1)}, points {nw} -> wedges {nwedge}", flush=True)
Wf = W[F.ravel()]
lf = np.repeat(lead, 3)  # leading bone of each corner's face
# corners x bones: the weighted bones this corner's face may blend with its leading bone at this point (+ the lead)
pt_ = Fw.ravel()
near = np.zeros((len(lf), J), bool)
near[np.arange(len(lf)), lf] = True
idx, bk = np.nonzero(Wf > 0)  # a point has at most 4 weighted bones (JOINTS_0): all of them, no sort needed
near[idx, bk] |= may_blend(Vw[pt_[idx]], lf[idx], bk)


def per_group(g, n):
    """Sparse group-membership matrix (n x len(g)) for summing rows by group."""
    return sp.csr_matrix((np.ones(len(g), np.int64), (g, np.arange(len(g)))), shape=(n, len(g)))


def common(g):
    """Bones every face meeting in group g may keep: one set of weights per group keeps the skin closed there, and no
    face's corners reach past its own leading bone's joint, so no face stretches between far-apart parts."""
    n = np.bincount(g)
    cnt = per_group(g, len(n)) @ near.astype(np.int64)  # whole numbers: the same counts as np.add.at, faster
    return cnt == n[:, None]


# 1. every point keeps the bones all faces around it may share (continuous skin, no face stretches far);
# 2. a point whose faces share none parts, along the cut edges (wedges); a wedge still sharing none parts by face lead.
pt = Fw.ravel()
brk = ~common(pt).any(1)
_, g0 = np.unique(np.where(brk[pt], nw + wedge, pt), return_inverse=True)
g0 = g0.ravel()
broken = ~common(g0).any(1)
_, grp = np.unique(np.where(broken[g0], (g0.max() + 1) * (1 + lf) + g0, g0), return_inverse=True)
grp = grp.ravel()
allowed = common(grp)
print(f"points that part: {int(brk.sum())}, wedges parted again by lead: {int(broken.sum())}, groups {grp.max() + 1}",
      flush=True)
cw = grp
Wc = Wf * allowed[grp]
z = Wc.sum(1) <= 0
if z.any():  # nothing left: the allowed bone nearest (in the skeleton) to all its faces' leads
    S = (per_group(grp, grp.max() + 1) @ dist[lf].astype(np.int64)).astype(float)  # sums of whole numbers: exact
    fb = np.where(allowed, S, np.inf).argmin(1)[grp]
    Wc[z] = 0
    Wc[z, fb[z]] = 1
Wc /= Wc.sum(1, keepdims=True)
Wn = Wf / np.maximum(Wf.sum(1, keepdims=True), 1e-12)
removed = 100 * (1 - (Wn * allowed[grp]).sum() / Wn.sum())
print(f"corners changed {100 * (np.abs(Wc - Wn).sum(1) > 1e-6).mean():.2f} %, weight mass removed {removed:.3f} %",
      flush=True)
P = V[F.ravel()]
first = {}
for ci, cid in enumerate(cw.tolist()):
    first.setdefault(cid, ci)


def triangulate(X):
    """Minimum-area triangulation of a closed polygon (dynamic programming, Barequet & Sharir 1995 / Liepa 2003)."""
    n = len(X)
    C = np.zeros((n, n))
    K = np.zeros((n, n), int)
    for gap in range(2, n):  # all spans of one length at once: they only need shorter spans
        i = np.arange(n - gap)[:, None]
        j = i + gap
        ks = i + np.arange(1, gap)[None, :]
        cost = C[i, ks] + C[ks, j] + 0.5 * np.linalg.norm(np.cross(X[ks] - X[i], X[j] - X[i]), axis=2)
        m = np.argmin(cost, axis=1)
        r = np.arange(n - gap)
        C[r, r + gap] = cost[r, m]
        K[r, r + gap] = ks[r, m]
    tris, st = [], [(0, n - 1)]
    while st:
        i, j = st.pop()
        if j - i < 2:
            continue
        k = K[i, j]
        tris.append((i, k, j))
        st += [(i, k), (k, j)]
    return tris


cap = []
loops = skipped = 0
if not os.environ.get("NOCAP"):
    # an edge is open when the skin parts at both its ends; an opening's rim runs group to group along open edges
    same = a[h1] == a[h2]
    ga1, gb1 = grp[corner_a(h1)], grp[corner_b(h1)]
    ga2 = np.where(same, grp[corner_a(h2)], grp[corner_b(h2)])
    gb2 = np.where(same, grp[corner_b(h2)], grp[corner_a(h2)])
    op = (ga1 != ga2) & (gb1 != gb2)
    partner = dict(zip(h1[op].tolist(), h2[op].tolist())) | dict(zip(h2[op].tolist(), h1[op].tolist()))
    print("open edges", int(op.sum()), flush=True)
    nxt, hof = {}, {}
    for h in partner:
        nxt.setdefault(int(grp[corner_a(h)]), []).append(int(grp[corner_b(h)]))
        hof[int(grp[corner_a(h)])] = h
    slits = 0
    seen = set()
    for s0 in list(nxt):
        if s0 in seen or len(nxt[s0]) != 1:
            continue
        path, x = [], s0
        while x in nxt and len(nxt[x]) == 1 and x not in seen:
            seen.add(x)
            path.append(x)
            x = nxt[x][0]
        if x != s0 or len(path) < 3:
            continue
        hs = {hof[w] for w in path}
        if any(partner[h] in hs for h in hs):  # both sides of one edge on this rim: a slit, not a hole (a lid would
            slits += 1                       # stretch between the two sides under animation)
            continue
        if len(path) > MAXRIM:
            skipped += 1
            continue
        corners = [first[w] for w in path[::-1]]  # reversed: the cap runs each rim edge the other way
        tt = triangulate(P[corners])
        for (i, k, jj) in tt:
            cap.append((corners[i], corners[k], corners[jj]))
        loops += 1
        if os.environ.get("DIAG"):
            X = P[corners]
            area = sum(0.5 * np.linalg.norm(np.cross(X[k] - X[i], X[jj] - X[i])) for i, k, jj in tt)
            per = np.linalg.norm(np.roll(X, -1, 0) - X, axis=1).sum()
            side = np.bincount(lf[corners], minlength=J).argmax()
            print(f"  loop {len(path)} pts, side {names[side]}, rim length {per:.3f}, cap area {area:.4f}, "
                  f"span {np.ptp(X, 0).round(3)}, centre {X.mean(0).round(3)}", flush=True)
print("slits left open", slits if not os.environ.get("NOCAP") else 0)
print("capped openings", loops, "cap triangles", len(cap), "skipped (rim >", MAXRIM, "points)", skipped, flush=True)
cap = np.array(cap, int).reshape(-1, 3)
src_corner = np.concatenate([np.arange(len(P)), cap.ravel()])
Wout = Wc[src_corner]
top = np.argsort(-Wout, 1)[:, :4]
tw = np.take_along_axis(Wout, top, 1)
tw /= tw.sum(1, keepdims=True)
j, bb = load(src)
assert len(j["meshes"]) == 1 and len(j["meshes"][0]["primitives"]) == 1
prim = j["meshes"][0]["primitives"][0]
olds = {k2: acc(j, bb, prim["attributes"][k2]).copy() for k2 in prim["attributes"]}
bb = bytearray(bb)  # a fresh buffer: the old one is held by numpy views and can't grow


def put(arr, target=34962):
    global bb
    bb += bytes(-len(bb) % 4)
    j["bufferViews"].append({"buffer": 0, "byteOffset": len(bb), "byteLength": arr.nbytes, "target": target})
    bb += arr.tobytes()
    return len(j["bufferViews"]) - 1


fc = F.ravel()
for k2, old in olds.items():
    if k2 == "JOINTS_0":
        new = top
    elif k2 == "WEIGHTS_0":
        new = tw
    else:
        new = old[fc][src_corner].copy()
        if k2 == "NORMAL" and len(cap):
            T = P[cap.ravel()].reshape(-1, 3, 3)
            nn = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
            nn /= np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-20)
            new[len(P):] = np.repeat(nn, 3, 0)
    new = np.ascontiguousarray(new.astype(old.dtype))
    ac = dict(j["accessors"][prim["attributes"][k2]])
    ac.pop("byteOffset", None)
    ac["bufferView"] = put(new)
    ac["count"] = len(new)
    if k2 == "POSITION":
        ac["min"], ac["max"] = new.min(0).tolist(), new.max(0).tolist()
    j["accessors"].append(ac)
    prim["attributes"][k2] = len(j["accessors"]) - 1
idx = np.arange(len(src_corner), dtype=np.uint32)
j["accessors"].append({"bufferView": put(idx, 34963), "componentType": 5125, "count": len(idx), "type": "SCALAR"})
prim["indices"] = len(j["accessors"]) - 1
j["buffers"][0]["byteLength"] = len(bb)
s = json.dumps(j, separators=(",", ":")).encode()
s += b" " * (-len(s) % 4)
body = struct.pack("<I", len(s)) + b"JSON" + s + struct.pack("<I", len(bb)) + b"BIN" + bytes(1) + bytes(bb)
open(out, "wb").write(b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body)
print(json.dumps({"partedPoints": int(brk.sum()), "cappedOpenings": loops, "capTriangles": len(cap),
                  "weightMassRemovedPct": round(float(removed), 2)}), flush=True)
