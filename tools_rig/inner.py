"""Inner skin where the generator fused parts that move apart (an arm grown into the flank, a fist into a thigh).
The generator made no skin there, so when the arm lifts the model's inside shows. The body is seen the way Maya's
geodesic voxel bind sees it: the inside is filled with small cubes (generalized winding number, robust to holes and
loose pieces), each cube belongs to the bone whose limb it lies deepest in (distance to the bone over that bone's
limb radius), and where two neighbouring cubes belong to bones that may not share skin there (the joint-envelope rule,
envelope.py) a wall is built on the face between them, twice: one copy moves with each side and faces away from it,
like the caps of a cut in Unreal's mesh slicing or Blender's bisect fill. The walls are smoothed (Taubin 1995: no
shrinking) and take their weights and UVs from the nearest skin on their own side. At rest they are hidden inside the
body; when the parts move apart each side shows its own wall instead of the inside.
python inner.py <rig.glb> <out.glb>
  env CELL (default 3): cubes across the thinnest limb's radius, a resolution like a texture size, not a decision."""
import json
import os
import struct
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).parent))
from envelope import Envelope  # noqa: E402
from judge import rig  # noqa: E402
from ourxfer import acc, load  # noqa: E402

import igl  # noqa: E402

CELL = float(os.environ.get("CELL", "3"))
MAX_CELLS = 6_000_000  # memory bound of the grid; when hit the cubes grow and the report says so
src, out = sys.argv[1:3]
V, F, W, heads, kids, names = rig(src)
J = len(names)
_, wv = np.unique(np.round(V, 6), axis=0, return_inverse=True)
wv = wv.ravel()
Vw = np.zeros((wv.max() + 1, 3))
Vw[wv] = V
Fw = wv[F]
rule = Envelope(Vw, heads, kids)
par = rule.par

# each bone as a segment from its head to the middle of its children's heads (a leaf: half its parent's length on)
tails = heads.copy()
for b in range(J):
    if kids[b]:
        tails[b] = heads[kids[b]].mean(0)
    elif par[b] >= 0:
        tails[b] = heads[b] + 0.5 * (heads[b] - heads[par[b]])


def seg_dist(P, b):
    a, d = heads[b], tails[b] - heads[b]
    t = np.clip(((P - a) @ d) / max(d @ d, 1e-18), 0, 1)
    return np.linalg.norm(P - (a + t[:, None] * d), axis=1)


# a bone's limb radius: how far its own skin lies from it (median over the points it leads)
lead_v = W.argmax(1)
R = np.full(J, np.nan)
share = np.bincount(lead_v, minlength=J) / len(V)
for b in range(J):
    own = V[lead_v == b]
    if len(own) >= 20:
        R[b] = np.median(seg_dist(own, b))
R = np.where(np.isfinite(R) & (R > 0), R, np.maximum(rule.rad, 1e-6))
main = share >= 0.01  # bones that carry a real part of the body
h = R[main].min() / CELL
lo, hi = V.min(0) - 2 * h, V.max(0) + 2 * h
n = np.ceil((hi - lo) / h).astype(int)
grown = False
while n.prod() > MAX_CELLS:
    h *= 1.25
    n = np.ceil((hi - lo) / h).astype(int)
    grown = True
print(f"cube {h:.4f} ({'grown to fit memory' if grown else f'thinnest limb radius / {CELL:g}'}), grid {n.tolist()}", flush=True)
ix = np.stack(np.meshgrid(*[np.arange(k) for k in n], indexing="ij"), -1).reshape(-1, 3)
Q = lo + (ix + 0.5) * h
inside = igl.fast_winding_number(Vw, Fw.astype(np.int64), Q) > 0.5
print("cubes inside", int(inside.sum()), flush=True)
label = np.full(len(Q), -1)
qi = np.nonzero(inside)[0]
for s0 in range(0, len(qi), 200000):  # (tried: the lead of the nearest skin point instead - shards between the thighs)
    sl = qi[s0:s0 + 200000]
    D = np.stack([seg_dist(Q[sl], b) / R[b] for b in range(J)], 1)
    label[sl] = D.argmin(1)
L3 = label.reshape(n)

# walls: faces between inside cubes of bones that may not share skin there
quads = []  # (4 lattice corners, side-A bone, side-B bone, axis)
for ax in range(3):
    a_ = np.take(L3, np.arange(n[ax] - 1), axis=ax)
    b_ = np.take(L3, np.arange(1, n[ax]), axis=ax)
    m = (a_ >= 0) & (b_ >= 0) & (a_ != b_)
    cells = np.argwhere(m)
    if not len(cells):
        continue
    A_, B_ = a_[m], b_[m]
    e = np.eye(3, dtype=int)[ax]
    centre = lo + (cells + 0.5) * h + 0.5 * h * e
    wall = ~rule.may_blend(centre, A_, B_)
    cells, A_, B_ = cells[wall], A_[wall], B_[wall]
    u, w = [k for k in range(3) if k != ax]
    eu, ew = np.eye(3, dtype=int)[u], np.eye(3, dtype=int)[w]
    base = cells + e  # the lattice corner on the shared face
    corners = np.stack([base, base + eu, base + eu + ew, base + ew], 1)
    if np.cross(eu, ew) @ e < 0:  # order the corners so the quad's normal is +ax (from side A to side B)
        corners = corners[:, ::-1]
    for c4, a1, b1 in zip(corners, A_, B_):
        quads.append((c4, a1, b1))
print("wall faces", len(quads), flush=True)
if not quads:
    import shutil
    shutil.copyfile(src, out)
    print(json.dumps({"wallFaces": 0, "cube": round(float(h), 5)}))
    sys.exit()

C4 = np.array([q[0] for q in quads])  # (m, 4, 3) lattice corners
SA = np.array([q[1] for q in quads])
SB = np.array([q[2] for q in quads])
key = (C4[..., 0] * (n[1] + 1) + C4[..., 1]) * (n[2] + 1) + C4[..., 2]
uk, vid = np.unique(key.ravel(), return_inverse=True)
vid = vid.reshape(-1, 4)
lat = np.stack([uk // ((n[1] + 1) * (n[2] + 1)), (uk // (n[2] + 1)) % (n[1] + 1), uk % (n[2] + 1)], 1)
X = lo + lat * h

# Taubin smoothing over the wall's own edges; its rim (edges on one face only) stays where it meets the body
E = np.concatenate([vid[:, [0, 1]], vid[:, [1, 2]], vid[:, [2, 3]], vid[:, [3, 0]]])
Es = np.sort(E, 1)
ue, cnt = np.unique(Es, axis=0, return_counts=True)
rim = np.zeros(len(X), bool)
rim[ue[cnt == 1].ravel()] = True
nbr_i = np.concatenate([ue[:, 0], ue[:, 1]])
nbr_j = np.concatenate([ue[:, 1], ue[:, 0]])
deg = np.bincount(nbr_i, minlength=len(X)).astype(float)
# the rim lies on the skin, so the wall meets the body like a cut's cap meets its cut (and nothing pokes out at rest)
_, _, Crim = igl.point_mesh_squared_distance(X[rim], Vw, Fw.astype(np.int64))
X[rim] = Crim
for it in range(20):
    for lam in (0.5, -0.53):
        avg = np.zeros_like(X)
        np.add.at(avg, nbr_i, X[nbr_j])
        step = avg / np.maximum(deg, 1)[:, None] - X
        step[rim] = 0
        X = X + lam * step

# two copies: the side-A copy faces from A to B (+axis order of the quad), the side-B copy the other way
tri_a = np.concatenate([vid[:, [0, 1, 2]], vid[:, [0, 2, 3]]])
side_a = np.concatenate([SA, SA])
side_b = np.concatenate([SB, SB])
tris = np.concatenate([tri_a, tri_a[:, ::-1]])
side = np.concatenate([side_a, side_b])
# a copy is needed only where its own side's skin is open: its generalized winding number (Jacobson 2013) there is
# about 1/2, the value on an opening. About 0 means the copy would hang outside a side whose skin is whole (a fist
# pushed into a thigh: two closed skins crossing, nothing missing), about 1 means it is hidden inside that skin
# anyway. Each copy triangle goes to the nearest of the three cases at its centre.
lead_c = W.argmax(1)
lf = lead_c[F]
wn_own = np.zeros(len(tris))
for b in np.unique(side):
    okf = np.ones(len(F), bool)
    for k in range(3):
        okf &= rule.may_blend(V[F[:, k]], lf[:, k], np.full(len(F), b)) | (lf[:, k] == b)
    m = side == b
    wn_own[m] = igl.fast_winding_number(Vw, Fw[okf].astype(np.int64), X[tris[m]].mean(1))
case = np.rint(np.clip(wn_own, 0, 1) * 2)  # 0 outside own skin, 1 on its opening, 2 inside it
print("copy triangles: on an opening", int((case == 1).sum()), "outside a whole skin", int((case == 0).sum()),
      "inside it", int((case == 2).sum()), flush=True)
pair_sides = np.concatenate([np.stack([SA, SB], 1)] * 2 + [np.stack([SB, SA], 1)] * 2)
if os.environ.get("CHECK"):
    # check only (no file written): how much skin two parts that move apart share where the model has no skin of its
    # own (the wall face is on an opening of either side), in cross-sections of the thinner of the two limbs
    m_ = len(quads)
    open_q = (case.reshape(4, m_) == 1).any(0)
    ta = tri_a  # side-A copy, one per wall face: triangles q and m_+q
    ar = 0.5 * np.linalg.norm(np.cross(X[ta[:, 1]] - X[ta[:, 0]], X[ta[:, 2]] - X[ta[:, 0]]), axis=1)
    area_q = ar[:m_] + ar[m_:]
    res = {}
    for q in np.nonzero(open_q)[0]:
        a1, b1 = sorted((int(SA[q]), int(SB[q])))
        res[(a1, b1)] = res.get((a1, b1), 0.0) + area_q[q]
    out_ = [{"a": names[a1], "b": names[b1], "area": round(float(v), 6),
             "sections": round(float(v / (np.pi * min(R[a1], R[b1]) ** 2)), 2)} for (a1, b1), v in res.items()]
    out_.sort(key=lambda d: -d["sections"])

    def part(nm):  # body, left/right arm (fingers included), left/right leg; None for bones without a humanoid name
        # the shoulder girdle (clavicle) grows out of the body by nature and hardly moves: it is neither
        side_ = "left " if nm.startswith("Left") else "right " if nm.startswith("Right") else ""
        if "Shoulder" in nm:
            return None
        if any(k in nm for k in ("Arm", "Hand")) and side_:
            return side_ + "arm"
        if any(k in nm for k in ("UpLeg", "Leg", "Foot", "Toe")) and side_:
            return side_ + "leg"
        if any(k in nm for k in ("Hips", "Spine", "Chest", "Neck", "Head")):
            return "body"
        return None

    def main_bone(pt_):  # the limb's thickest long bone, its radius is the unit
        return {"left arm": "LeftArm", "right arm": "RightArm", "left leg": "LeftUpLeg", "right leg": "RightUpLeg"}.get(pt_)
    groups = {}
    for (a1, b1), v in res.items():
        pa, pb = part(names[a1]), part(names[b1])
        if pa is None or pb is None or pa == pb:
            continue
        key_ = tuple(sorted((pa, pb)))
        groups[key_] = groups.get(key_, 0.0) + v
    gout = []
    for (pa, pb), v in groups.items():
        units = [names.index(main_bone(x)) for x in (pa, pb) if main_bone(x) in names]
        if not units:
            continue
        r_ = min(R[u] for u in units)
        gout.append({"parts": [pa, pb], "sections": round(float(v / (np.pi * r_ ** 2)), 2)})
    gout.sort(key=lambda d: -d["sections"])
    print(json.dumps({"fused": out_, "parts": gout}), flush=True)
    sys.exit()
tris, side, pair_sides = tris[case == 1], side[case == 1], pair_sides[case == 1]
if not len(tris):
    import shutil
    shutil.copyfile(src, out)
    print(json.dumps({"wallFaces": len(quads), "cube": round(float(h), 5), "newTriangles": 0}))
    sys.exit()
# one new vertex per (wall point, side bone)
pk = tris * J + side[:, None]
upk, new_id = np.unique(pk.ravel(), return_inverse=True)
new_id = new_id.reshape(-1, 3)
pt, sb = upk // J, upk % J
P = X[pt]
# vertex normals of each copy
fn = np.cross(P[new_id[:, 1]] - P[new_id[:, 0]], P[new_id[:, 2]] - P[new_id[:, 0]])
vn = np.zeros_like(P)
for k in range(3):
    np.add.at(vn, new_id[:, k], fn)
vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-20)

# where each new vertex takes weights and UVs: the nearest skin on its own side (a corner led by a bone that may
# share skin with the side's bone at that place)
trees = {b: cKDTree(V[lead_c == b]) for b in range(J) if (lead_c == b).any()}
ids = {b: np.nonzero(lead_c == b)[0] for b in trees}
best_d = np.full(len(P), np.inf)
best = np.zeros(len(P), int)
for b in trees:
    ok = rule.may_blend(P, sb, np.full(len(P), b)) | (sb == b)
    if not ok.any():
        continue
    d, k = trees[b].query(P[ok])
    sel = np.nonzero(ok)[0]
    better = d < best_d[sel]
    best_d[sel[better]] = d[better]
    best[sel[better]] = ids[b][k[better]]
print("new vertices", len(P), "triangles", len(tris), f"(max distance to own-side skin {best_d.max():.4f})", flush=True)

# write: old vertices + new ones, old triangles + walls
j, bb = load(src)
assert len(j["meshes"]) == 1 and len(j["meshes"][0]["primitives"]) == 1
prim = j["meshes"][0]["primitives"][0]
olds = {k2: acc(j, bb, prim["attributes"][k2]).copy() for k2 in prim["attributes"]}
old_idx = acc(j, bb, prim["indices"]).ravel().astype(np.uint32) if "indices" in prim else np.arange(len(V), dtype=np.uint32)
bb = bytearray(bb)


def put(arr, target=34962):
    global bb
    bb += bytes(-len(bb) % 4)
    j["bufferViews"].append({"buffer": 0, "byteOffset": len(bb), "byteLength": arr.nbytes, "target": target})
    bb += arr.tobytes()
    return len(j["bufferViews"]) - 1


nv = len(V)
for k2, old in olds.items():
    if k2 == "POSITION":
        add = P
    elif k2 == "NORMAL":
        add = vn
    else:
        add = old[best]
    new = np.ascontiguousarray(np.concatenate([old, add.astype(old.dtype)]))
    ac = dict(j["accessors"][prim["attributes"][k2]])
    ac.pop("byteOffset", None)
    ac["bufferView"] = put(new)
    ac["count"] = len(new)
    if k2 == "POSITION":
        ac["min"], ac["max"] = new.min(0).tolist(), new.max(0).tolist()
    j["accessors"].append(ac)
    prim["attributes"][k2] = len(j["accessors"]) - 1
idx = np.concatenate([old_idx, (new_id + nv).ravel().astype(np.uint32)])
j["accessors"].append({"bufferView": put(idx, 34963), "componentType": 5125, "count": len(idx), "type": "SCALAR"})
prim["indices"] = len(j["accessors"]) - 1
j["buffers"][0]["byteLength"] = len(bb)
s = json.dumps(j, separators=(",", ":")).encode()
s += b" " * (-len(s) % 4)
body = struct.pack("<I", len(s)) + b"JSON" + s + struct.pack("<I", len(bb)) + b"BIN" + bytes(1) + bytes(bb)
open(out, "wb").write(b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body)
pairs = {}
for a1, b1 in pair_sides:
    k3 = f"{names[a1]} side of {names[b1]}"
    pairs[k3] = pairs.get(k3, 0) + 1
print("kept copy triangles:", sorted(pairs.items(), key=lambda x: -x[1])[:10], flush=True)
print(json.dumps({"wallFaces": len(quads), "cube": round(float(h), 5), "newTriangles": int(len(tris))}), flush=True)
