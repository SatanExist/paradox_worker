"""Fast weight transfer: the skeleton and weights of a rigged LIGHT copy (e.g. 200k triangles) put onto the full
original GLB. Each original vertex takes the weights of its 4 nearest copy vertices (inverse distance), top 4 kept.
Only adds to the original file: joint nodes, a skin, JOINTS_0/WEIGHTS_0; the mesh, UVs and textures stay as they are.
python ourxfer.py <original plain.glb> <rigged copy.glb> <out.glb>"""
import json
import struct
import sys
import time

import numpy as np
from scipy.spatial import cKDTree

SIZES = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
TYPES = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8, 5122: np.int16, 5120: np.int8}


def load(p):
    b = open(p, "rb").read()
    n = struct.unpack("<I", b[12:16])[0]
    return json.loads(b[20:20 + n]), bytearray(b[20 + n + 8:])


def acc(j, binary, i):
    a = j["accessors"][i]
    v = j["bufferViews"][a["bufferView"]]
    dt = np.dtype(TYPES[a["componentType"]])
    k = SIZES[a["type"]]
    start = v.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = v.get("byteStride", 0)
    if stride and stride != dt.itemsize * k:
        raw = np.frombuffer(binary, np.uint8, count=stride * a["count"], offset=start).reshape(a["count"], stride)
        out = raw[:, :dt.itemsize * k].copy().view(dt).reshape(a["count"], k)
    else:
        out = np.frombuffer(binary, dt, count=a["count"] * k, offset=start).reshape(a["count"], k)
    if a.get("normalized"):
        out = out.astype(np.float64) / np.iinfo(dt).max
    return out


def local(nd):
    if "matrix" in nd:
        return np.array(nd["matrix"], float).reshape(4, 4).T
    t = np.array(nd.get("translation", [0, 0, 0]), float)
    x, y, z, w = nd.get("rotation", [0, 0, 0, 1])
    s = np.array(nd.get("scale", [1, 1, 1]), float)
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = r * s
    m[:3, 3] = t
    return m


def worlds(j):
    parent = {c: i for i, nd in enumerate(j["nodes"]) for c in nd.get("children", [])}
    memo = {}

    def w(i):
        if i not in memo:
            memo[i] = (w(parent[i]) if i in parent else np.eye(4)) @ local(j["nodes"][i])
        return memo[i]
    return w, parent


if __name__ == "__main__":
    t0 = time.time()
    orig_p, rig_p, out_p = sys.argv[1:4]
    jo, bo = load(orig_p)
    jr, br = load(rig_p)
    wr, par_r = worlds(jr)
    skin = jr["skins"][0]
    joints = skin["joints"]
    ibm = acc(jr, br, skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1).astype(np.float64)
    bind = wr(joints[0]) @ ibm[0]  # skinned vertices -> world at bind
    pts, dense = [], []
    for nd in jr["nodes"]:
        if nd.get("skin") is None or "mesh" not in nd:
            continue
        for pr in jr["meshes"][nd["mesh"]]["primitives"]:
            at = pr["attributes"]
            P = acc(jr, br, at["POSITION"]).astype(np.float64)
            pts.append(P @ bind[:3, :3].T + bind[:3, 3])
            J = acc(jr, br, at["JOINTS_0"]).astype(np.int64)
            W = acc(jr, br, at["WEIGHTS_0"]).astype(np.float64)
            D = np.zeros((len(P), len(joints)))
            np.add.at(D, (np.repeat(np.arange(len(P)), 4), J.ravel()), W.ravel())
            dense.append(D)
    pts, dense = np.concatenate(pts), np.concatenate(dense)
    tree = cKDTree(pts)
    # joint nodes copied into the original file (same hierarchy, local transforms), roots added to the scene
    jo.setdefault("skins", [])
    base = len(jo["nodes"])
    remap = {old: base + k for k, old in enumerate(joints)}
    for old in joints:
        nd = {k: v for k, v in jr["nodes"][old].items() if k in ("name", "translation", "rotation", "scale", "matrix")}
        kids = [remap[c] for c in jr["nodes"][old].get("children", []) if c in remap]
        if kids:
            nd["children"] = kids
        jo["nodes"].append(nd)
    roots = [remap[o] for o in joints if par_r.get(o) not in remap]
    # world of each joint root's ancestors in the rigged file goes into the root's own transform
    for o in joints:
        if par_r.get(o) not in remap:
            m = wr(o)
            nd = jo["nodes"][remap[o]]
            for k in ("translation", "rotation", "scale"):
                nd.pop(k, None)
            nd["matrix"] = list(m.T.reshape(-1))
    jo["nodes"].append({"name": "Armature", "children": roots})  # like Blender's files: the bones under one Armature node
    jo["scenes"][jo.get("scene", 0)]["nodes"].append(len(jo["nodes"]) - 1)
    jworld = np.array([wr(o) for o in joints])
    wo, _parent_o = worlds(jo)
    blobs = []

    def add(arr, ctype, typ, target=None):
        data = np.ascontiguousarray(arr).tobytes()
        off = len(bo) + sum(len(x) for x in blobs)
        pad = (-off) % 4
        blobs.append(b"\0" * pad + data)
        jo["bufferViews"].append({"buffer": 0, "byteOffset": off + pad, "byteLength": len(data), **({"target": target} if target else {})})
        a = {"bufferView": len(jo["bufferViews"]) - 1, "componentType": ctype, "count": len(arr), "type": typ}
        jo["accessors"].append(a)
        return len(jo["accessors"]) - 1
    skins_by_m = {}
    done = {}
    moved = 0
    users = {}
    for i, nd in enumerate(jo["nodes"][:base]):
        if "mesh" in nd:
            users.setdefault(nd["mesh"], []).append(i)
    acc_users = {}
    for m in jo["meshes"]:
        for pr in m["primitives"]:
            for k in ("POSITION", "NORMAL", "TANGENT"):
                if k in pr["attributes"]:
                    acc_users[pr["attributes"][k]] = acc_users.get(pr["attributes"][k], 0) + 1

    def bake(i, M):
        """Put the mesh node's own transform into its vertices (skinned meshes ignore node transforms, and engines
        would size the model's box with it), when nothing else shares that data. Returns the new world matrix."""
        nd = jo["nodes"][i]
        if np.allclose(M, np.eye(4)) or len(users[nd["mesh"]]) > 1:
            return M
        prims = jo["meshes"][nd["mesh"]]["primitives"]
        keys = [(pr["attributes"][k], k) for pr in prims for k in ("POSITION", "NORMAL", "TANGENT") if k in pr["attributes"]]
        if any(acc_users[a] > 1 for a, _ in keys) or any(j_ in jo["nodes"][i] for j_ in ("children",)):
            return M
        R = M[:3, :3]
        N = np.linalg.inv(R).T
        for a, k in set(keys):
            arr = acc(jo, bo, a)
            if arr.dtype != np.float32:
                return M
            x = arr.astype(np.float64)
            if k == "POSITION":
                y = x @ R.T + M[:3, 3]
                jo["accessors"][a]["min"], jo["accessors"][a]["max"] = list(map(float, y.min(0))), list(map(float, y.max(0)))
            elif k == "NORMAL":
                y = x @ N.T
                y /= np.maximum(np.linalg.norm(y, axis=1, keepdims=True), 1e-12)
            else:
                y = x.copy()
                y[:, :3] = x[:, :3] @ R.T
                y[:, :3] /= np.maximum(np.linalg.norm(y[:, :3], axis=1, keepdims=True), 1e-12)
            arr2 = np.frombuffer(bo, np.float32, count=arr.size, offset=jo["bufferViews"][jo["accessors"][a]["bufferView"]].get("byteOffset", 0)
                                 + jo["accessors"][a].get("byteOffset", 0)).reshape(arr.shape)
            arr2[:] = y.astype(np.float32)
        P_ = np.eye(4) if i not in _parent_o else wo(_parent_o[i])
        for k in ("translation", "rotation", "scale", "matrix"):
            nd.pop(k, None)
        if not np.allclose(P_, np.eye(4)):
            nd["matrix"] = list(np.linalg.inv(P_).T.reshape(-1))
        return np.eye(4)
    for i, nd in enumerate(jo["nodes"][:base]):
        if "mesh" not in nd:
            continue
        M = bake(i, wo(i))
        key = tuple(np.round(M, 9).ravel())
        if key not in skins_by_m:
            ib = np.array([np.linalg.inv(jw) @ M for jw in jworld]).transpose(0, 2, 1).astype(np.float32)
            jo["skins"].append({"joints": [remap[o] for o in joints], "inverseBindMatrices": add(ib, 5126, "MAT4"),
                                "skeleton": roots[0]})
            skins_by_m[key] = len(jo["skins"]) - 1
        nd["skin"] = skins_by_m[key]
        for pr in jo["meshes"][nd["mesh"]]["primitives"]:
            pa = pr["attributes"]["POSITION"]
            if (pa, key) not in done:
                P = acc(jo, bo, pa).astype(np.float64)
                Pw = P @ M[:3, :3].T + M[:3, 3]
                d, nn = tree.query(Pw, k=4)
                w = 1.0 / np.maximum(d, 1e-9)
                w /= w.sum(1, keepdims=True)
                D = (dense[nn] * w[:, :, None]).sum(1)
                top = np.argsort(-D, axis=1)[:, :4]
                tw = np.take_along_axis(D, top, 1)
                tw /= np.maximum(tw.sum(1, keepdims=True), 1e-12)
                jt = 5121 if len(joints) < 256 else 5123
                done[(pa, key)] = (add(top.astype(np.uint8 if jt == 5121 else np.uint16), jt, "VEC4", 34962),
                                   add(tw.astype(np.float32), 5126, "VEC4", 34962))
                moved += len(P)
            pr["attributes"]["JOINTS_0"], pr["attributes"]["WEIGHTS_0"] = done[(pa, key)]
    binary = bytes(bo) + b"".join(blobs)
    binary += b"\0" * ((-len(binary)) % 4)
    jo["buffers"][0]["byteLength"] = len(binary)
    s = json.dumps(jo, separators=(",", ":")).encode()
    s += b" " * (-len(s) % 4)
    body = struct.pack("<I", len(s)) + b"JSON" + s + struct.pack("<I", len(binary)) + b"BIN\0" + binary
    open(out_p, "wb").write(b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body)
    print(f"XFER {moved} vertices from {len(pts)} copy vertices, {len(joints)} bones, {time.time() - t0:.1f}s")
