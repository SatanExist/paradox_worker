"""Cape bones: loose cloth (a cape, a robe, a long skirt) gets its own bone chains hung from the hips, instead of
following the legs. Only when the user asks for it (auto_rig cape: true), like VRM / VRoid tools where the artist adds
skirt or hair bones: Mixamo and AccuRIG add none, and telling a cape from a double-walled armour by the shape alone is
not reliable (2026-11-20 trial: three rule changes, each fixed one model and broke another). Human rigs only: the
cloth is found on the named leg bones and hung from Hips.

1. Loose cloth = skin weight on a leg bone at points that cannot see that bone (Blender's bone heat visibility,
   Baran & Popovic 2007 "Pinocchio"): the straight line from the point to the nearest point of the bone enters solid
   matter (crosses the front of a surface). The leg's own skin (armour of any thickness, boots) sees its bone; cloth
   hanging around or behind the leg is hidden by the leg's skin. Leaving a wall's thickness (the inner wall of a double
   shell, the far side of a cloth sheet) does not hide. A toe (leaf) bone has no child joint to bound it: never moves.
2. A hidden point with the leg's own skin beyond it (the ray from the bone through the point, continued, hits skin
   that sees that leg) is inside the leg (a gap between plates, a body under armour) and keeps its weight.
3. A leg is one connected piece of surface: of the skin each leg keeps, only the largest connected piece stays; the
   other pieces are cloth lying by the leg in the open (a cape hem beside the boot sees the foot bone).
4. The cloth is cut into SECTORS around the up axis through Hips and LEVELS from its top to its hem; each sector with
   cloth gets a chain (one bone per level and a tip, the first a child of Hips) at the cloth's weighted median point
   per level. Each loose point is weighted to the 2 nearest sectors x the 2 nearest levels (linear), its moved weight
   only, 4 bones kept. The chain bones are marked "cloth" in their node extras (envelope.py: cloth blends freely).
Settings (flagged, like VRM skirt tools' chain counts): SECTORS 8, LEVELS 4.
Leg colliders for the engine's spring bones: each upper and lower leg bone gets "clothCollider" in its node extras =
the median distance of its own kept skin (weight over half) from the bone, so the cape slides over the legs; the
Godot package (game_godot.py) makes a capsule of it.
Check said in the report: the share of the moved points that hang outside the legs (farther from the leg bones than
90 % of the leg's own skin). A real cape: almost all (rodin knight 0.98); false cloth from double walls or plate gaps
lies inside the leg's thickness (mech 0.30, armour 0.36, skeleton 0.00, 2026-11-20).
Needs open3d (ray casts; a SkinTokens requirement, so in the rig Python) + scipy. Same file in -> same file out.
python cape.py <rig.glb> <out.glb>   -> last line JSON; the file is written only when cloth was found"""
import json
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from ourxfer import acc, load, worlds  # noqa: E402

SECTORS = 8
LEVELS = 4
LEGS = ("LeftUpLeg", "RightUpLeg")
OUTSIDE_PCT = 90  # "outside the leg" = farther from the leg bones than this share of the leg's own skin


def main(src, out):
    import open3d as o3d
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    j, b = load(src)
    skin = j["skins"][0]
    joints = list(skin["joints"])
    J = len(joints)
    names = [j["nodes"][n].get("name", "") for n in joints]
    ix = {n: i for i, n in enumerate(names)}
    if not all(n in ix for n in LEGS + ("Hips",)):
        return {"chains": 0, "why": "no named hips and legs (Rig type: Human is needed)"}
    ibm = acc(j, b, skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1).astype(np.float64)
    heads = np.array([np.linalg.inv(m)[:3, 3] for m in ibm])
    nidx = {n: k for k, n in enumerate(joints)}
    kids = [[nidx[c] for c in j["nodes"][n].get("children", []) if c in nidx] for n in joints]
    prims = [pr for nd in j["nodes"] if nd.get("skin") is not None and "mesh" in nd
             for pr in j["meshes"][nd["mesh"]]["primitives"]]
    if len(prims) != 1:
        return {"chains": 0, "why": f"{len(prims)} skinned parts (one is expected after the rig)"}
    at = prims[0]["attributes"]
    V = acc(j, b, at["POSITION"]).astype(np.float64)
    F = acc(j, b, prims[0]["indices"]).reshape(-1, 3).astype(np.int64)
    Jn = acc(j, b, at["JOINTS_0"]).astype(np.int64)
    Wn = acc(j, b, at["WEIGHTS_0"]).astype(np.float64)

    def sub(i):
        s, st = [], [i]
        while st:
            x = st.pop()
            s.append(x)
            st += kids[x]
        return s

    def seg_dist(P, i):  # distance from points to bone i (head to its first child)
        a_, ab = heads[i], heads[kids[i][0]] - heads[i]
        t = np.clip(((P - a_) @ ab) / (ab @ ab), 0, 1)
        d = a_ + t[:, None] * ab - P
        return d, np.linalg.norm(d, axis=1)

    leg = sorted(set(sub(ix[LEGS[0]]) + sub(ix[LEGS[1]])))
    scene = o3d.t.geometry.RaycastingScene()
    scene.add_triangles(o3d.core.Tensor(V.astype(np.float32)), o3d.core.Tensor(F.astype(np.uint32)))
    eps = 1e-4 * float(np.linalg.norm(V.max(0) - V.min(0)))  # ray start off its own triangle (numerical)
    tri_n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])  # front side by winding
    hidden = np.zeros(Jn.shape, bool)
    outward = np.zeros(Jn.shape + (3,), np.float32)  # bone -> point direction of each tested weight
    # 1. visibility
    for i in leg:
        if not kids[i]:
            continue
        rows, cols = np.nonzero((Jn == i) & (Wn > 0))
        P = V[rows]
        d, L = seg_dist(P, i)
        dn = d / np.maximum(L, 1e-12)[:, None]
        hits = scene.list_intersections(o3d.core.Tensor(np.c_[P + eps * dn, dn].astype(np.float32)))
        ray = np.repeat(np.arange(len(P)), np.diff(hits["ray_splits"].numpy().astype(np.int64)))
        front = (tri_n[hits["primitive_ids"].numpy().astype(np.int64)] * dn[ray]).sum(1) < 0
        enter = (hits["t_hit"].numpy() < L[ray] - 2 * eps) & front
        hidden[rows, cols] = np.bincount(ray[enter], minlength=len(P)) > 0
        outward[rows, cols] = -dn
    # 2. inside the leg: the leg's own skin beyond the point (most corners of the hit triangle see that leg)
    for side in LEGS:
        bones = np.array(sub(ix[side]))
        sees = (np.isin(Jn, bones) & (Wn > 0) & ~hidden).any(1)
        rows, cols = np.nonzero(np.isin(Jn, bones) & hidden)
        if not len(rows):
            continue
        o_ = outward[rows, cols].astype(np.float64)
        hit = scene.cast_rays(o3d.core.Tensor(np.c_[V[rows] + eps * o_, o_].astype(np.float32)))
        tri = hit["primitive_ids"].numpy().astype(np.int64)
        ok = np.isfinite(hit["t_hit"].numpy())
        inside = np.zeros(len(rows), bool)
        inside[ok] = sees[F[tri[ok]]].sum(1) >= 2
        hidden[rows[inside], cols[inside]] = False
    # 3. one piece per leg (points welded by position, joined along mesh edges)
    _, uid = np.unique(V.astype(np.float32).view(np.dtype((np.void, 12))), return_inverse=True)
    uid = uid.ravel()
    U = int(uid.max()) + 1
    Fu = uid[F]
    edges = np.r_[Fu[:, [0, 1]], Fu[:, [1, 2]], Fu[:, [2, 0]]]
    for side in LEGS:
        bones = np.array(sub(ix[side]))
        has = np.isin(Jn, bones) & (Wn > 0) & ~hidden
        kept = np.zeros(U, bool)
        kept[uid[has.any(1)]] = True
        if not kept.any():
            continue
        ee = edges[kept[edges[:, 0]] & kept[edges[:, 1]]]
        _, lab = connected_components(coo_matrix((np.ones(len(ee)), (ee[:, 0], ee[:, 1])), shape=(U, U)), directed=False)
        off = kept & (lab != np.argmax(np.bincount(lab[kept])))
        hidden |= has & off[uid][:, None] & np.isin(Jn, bones[[bool(kids[x]) for x in bones]])
    Wkeep = np.where(hidden, 0.0, Wn)
    share = (Wn - Wkeep).sum(1)
    loose = share > 0
    if not loose.any():
        return {"chains": 0, "why": "no loose cloth found on the legs"}

    # the check: moved points outside the legs' own thickness
    legb = [i for i in leg if kids[i]]

    def leg_dist(P):
        return np.min([seg_dist(P, i)[1] for i in legb], axis=0)
    legw = (np.isin(Jn, legb) * Wkeep).sum(1)
    reach = np.percentile(leg_dist(V[legw > 0.5]), OUTSIDE_PCT) if (legw > 0.5).any() else 0.0
    moved = share > 0.5
    outside = float((leg_dist(V[moved]) > reach).mean()) if moved.any() else 0.0

    # leg colliders: the median distance of each upper / lower leg bone's own skin from it
    colliders = {}
    for side in ("Left", "Right"):
        for nm in (side + "UpLeg", side + "Leg"):
            i = ix.get(nm)
            if i is None or not kids[i]:
                continue
            own = (Wkeep * (Jn == i)).sum(1) > 0.5
            if own.any():
                colliders[nm] = float(np.median(seg_dist(V[own], i)[1]))

    # 4. chains: sectors around the up (y) axis through Hips, levels from the cloth's top to its hem
    hips = heads[ix["Hips"]]
    P, S = V[loose], share[loose]
    u = (np.arctan2(P[:, 0] - hips[0], P[:, 2] - hips[2]) + np.pi) / (2 * np.pi) * SECTORS - 0.5  # centres at integers
    sec = np.round(u).astype(int) % SECTORS

    def wmed(x, w):
        o = np.argsort(x, kind="stable")
        c = np.cumsum(w[o])
        return float(x[o][np.searchsorted(c, c[-1] / 2)])

    chains = {}  # sector -> (joint heads (LEVELS + 1, 3), top, hem)
    for s in range(SECTORS):
        Q, Sq = P[sec == s], S[sec == s]
        if not len(Q):
            continue
        top, bot = Q[:, 1].max(), Q[:, 1].min()
        step = (top - bot) / LEVELS
        pts = []
        for y in top - step * np.arange(LEVELS + 1):
            m = np.abs(Q[:, 1] - y) <= step / 2
            pts.append([wmed(Q[m, 0], Sq[m]), y, wmed(Q[m, 2], Sq[m])] if m.any() else [np.nan, y, np.nan])
        pts = np.array(pts)
        for c in (0, 2):  # empty bands: from the neighbours
            ok = ~np.isnan(pts[:, c])
            pts[:, c] = np.interp(np.arange(len(pts)), np.flatnonzero(ok), pts[ok, c])
        chains[s] = (pts, top, bot)
    have = np.array(sorted(chains))
    new_heads, new_parent, new_names, bone_of = [], [], [], {}
    for s in have.tolist():
        for m in range(LEVELS + 1):
            bone_of[(s, m)] = J + len(new_heads)
            new_heads.append(chains[s][0][m])
            new_parent.append(ix["Hips"] if m == 0 else bone_of[(s, m - 1)])
            new_names.append(f"Cape{s}_{m}")

    def nearest_chain(si):  # a sector without cloth -> the closest sector with a chain (around the circle)
        d = np.abs((have - si + SECTORS / 2) % SECTORS - SECTORS / 2)
        return int(have[np.argmin(d)])

    s0 = np.floor(u).astype(int)
    fs = u - s0
    Wl = np.zeros((len(P), 4))
    Jl = np.zeros((len(P), 4), np.int64)
    for e, (sx, ws) in enumerate(((s0 % SECTORS, 1 - fs), ((s0 + 1) % SECTORS, fs))):
        for i_s in np.unique(sx):
            m_ = sx == i_s
            cs = nearest_chain(int(i_s))
            _, top, bot = chains[cs]
            v = (top - P[m_, 1]) / max(top - bot, 1e-12) * LEVELS - 0.5  # bone centres at integers
            l0 = np.clip(np.floor(v).astype(int), 0, LEVELS - 1)
            l1 = np.clip(l0 + 1, 0, LEVELS - 1)
            fl = np.where(l0 == l1, 0, np.clip(v - np.floor(v), 0, 1))
            Jl[m_, 2 * e] = [bone_of[(cs, x)] for x in l0.tolist()]
            Jl[m_, 2 * e + 1] = [bone_of[(cs, x)] for x in l1.tolist()]
            Wl[m_, 2 * e] = ws[m_] * (1 - fl)
            Wl[m_, 2 * e + 1] = ws[m_] * fl
    Wl = Wl / np.maximum(Wl.sum(1, keepdims=True), 1e-12) * S[:, None]
    Jc = np.concatenate([Jn[loose], Jl], 1)
    Wc = np.concatenate([Wkeep[loose], Wl], 1)
    top4 = np.argsort(-Wc, axis=1, kind="stable")[:, :4]
    Jall, Wall = Jn.copy(), Wn.copy()
    Jall[loose] = np.take_along_axis(Jc, top4, 1)
    Wt = np.take_along_axis(Wc, top4, 1)
    Wall[loose] = Wt / np.maximum(Wt.sum(1, keepdims=True), 1e-12)

    # write: nodes, skin joints + inverse bind matrices, JOINTS_0 / WEIGHTS_0
    w, _ = worlds(j)
    G = w(joints[ix["Hips"]]) @ ibm[ix["Hips"]]  # bind space -> world, the same for every bone at rest
    bb = bytearray(b)

    def put(arr, target=None):
        nonlocal bb
        bb += bytes(-len(bb) % 4)
        v = {"buffer": 0, "byteOffset": len(bb), "byteLength": arr.nbytes}
        if target:
            v["target"] = target
        j["bufferViews"].append(v)
        bb += arr.tobytes()
        return len(j["bufferViews"]) - 1

    node_of, node_world, new_ibm = {}, {}, []
    for k, (h, par, nm) in enumerate(zip(new_heads, new_parent, new_names)):
        T = np.eye(4)
        T[:3, 3] = h
        world = G @ T
        pnode = joints[par] if par < J else node_of[par]
        loc = np.linalg.inv(w(pnode) if par < J else node_world[par]) @ world
        nd = {"name": nm, "translation": loc[:3, 3].tolist(), "extras": {"cloth": True}}
        if not np.allclose(loc[:3, :3], np.eye(3), atol=1e-9):
            nd = {"name": nm, "matrix": loc.T.ravel().tolist(), "extras": {"cloth": True}}
        j["nodes"].append(nd)
        ni = len(j["nodes"]) - 1
        j["nodes"][pnode].setdefault("children", []).append(ni)
        node_of[J + k], node_world[J + k] = ni, world
        new_ibm.append(np.linalg.inv(world) @ G)
    for nm, r in colliders.items():
        j["nodes"][joints[ix[nm]]].setdefault("extras", {})["clothCollider"] = round(r, 6)
    skin["joints"] = joints + [node_of[J + k] for k in range(len(new_heads))]
    allibm = np.concatenate([ibm, np.array(new_ibm)]).transpose(0, 2, 1).astype(np.float32)
    j["accessors"].append({"bufferView": put(np.ascontiguousarray(allibm)), "componentType": 5126,
                           "count": len(allibm), "type": "MAT4"})
    skin["inverseBindMatrices"] = len(j["accessors"]) - 1
    for key, arr, ct in (("JOINTS_0", Jall.astype(np.uint16), 5123), ("WEIGHTS_0", Wall.astype(np.float32), 5126)):
        j["accessors"].append({"bufferView": put(np.ascontiguousarray(arr), 34962), "componentType": ct,
                               "count": len(arr), "type": "VEC4"})
        at[key] = len(j["accessors"]) - 1
    j["buffers"][0]["byteLength"] = len(bb)
    s = json.dumps(j, separators=(",", ":")).encode()
    s += b" " * (-len(s) % 4)
    bb += bytes(-len(bb) % 4)
    body = struct.pack("<I", len(s)) + b"JSON" + s + struct.pack("<I", len(bb)) + b"BIN" + bytes(1) + bytes(bb)
    Path(out).write_bytes(b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body)
    return {"chains": len(have), "bones": len(new_heads), "clothPoints": int(loose.sum()),
            "clothPct": round(100 * float(loose.mean()), 1), "outsideLegs": round(outside, 2),
            "legColliders": {k: round(v, 6) for k, v in colliders.items()}}


if __name__ == "__main__":
    print(json.dumps(main(*sys.argv[1:3])), flush=True)
