"""Give a SkinTokens humanoid rig standard bone names (Mixamo style, no prefix), by the shape of the bone tree.
All-or-nothing: if the tree is not a full humanoid (pelvis, spine up, 2 legs down, chest with neck + 2 arms), nothing is renamed.
Only glTF node names change; indices, weights and bytes of the mesh stay the same.
python rename.py <out dir> a_rig.glb ..."""
import json
import struct
import sys
from pathlib import Path

import numpy as np

UP = np.array([0.0, 1.0, 0.0])  # glTF is Y-up


def read(p):
    b = open(p, "rb").read()
    n = struct.unpack("<I", b[12:16])[0]
    return json.loads(b[20:20 + n]), b[20 + n:]


def write(p, j, rest):
    s = json.dumps(j, separators=(",", ":")).encode()
    s += b" " * (-len(s) % 4)
    body = struct.pack("<I", len(s)) + b"JSON" + s + rest
    open(p, "wb").write(b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body)


def skeleton(j, rest):
    binary = rest[8:]
    skin = j["skins"][0]
    a = j["accessors"][skin["inverseBindMatrices"]]
    v = j["bufferViews"][a["bufferView"]]
    ibm = np.frombuffer(binary, np.float32, count=a["count"] * 16,
                        offset=v.get("byteOffset", 0) + a.get("byteOffset", 0)).reshape(-1, 4, 4).transpose(0, 2, 1)
    pos = np.array([np.linalg.inv(m)[:3, 3] for m in ibm])
    nodes = skin["joints"]
    idx = {nd: i for i, nd in enumerate(nodes)}
    parents = np.full(len(nodes), -1)
    for nd in nodes:
        for c in j["nodes"][nd].get("children", []):
            if c in idx:
                parents[idx[c]] = idx[nd]
    return pos, parents, nodes


def label(pos, parents):
    """-> ({bone: role name}, None) or (None, reason). Called when the user said the model is a human (Rig type: Human,
    as Mixamo / AccuRIG ask): the humanoid template and plain signs decide (spine above the pelvis, legs below it, an arm
    and a leg on each side, head above the chest); nothing about proportions, so no hand-set limits."""
    J = len(parents)
    kids = {i: [k for k in range(J) if parents[k] == i] for i in range(J)}

    def depth(i):
        return 0 if not kids[i] else 1 + max(depth(k) for k in kids[i])

    def chain(i):  # down single-child links; stops after a branching bone
        c = [i]
        while len(kids[c[-1]]) == 1:
            c.append(kids[c[-1]][0])
        return c

    def sub(i):
        return [i] + [x for k in kids[i] for x in sub(k)]

    def top(i):  # highest point of the subtree
        return max(pos[x] @ UP for x in sub(i))

    def tip(i):  # deepest point of the subtree
        while kids[i]:
            i = max(kids[i], key=lambda k: (depth(k), -k))
        return i

    order = [i for i in range(J) if parents[i] < 0]
    pelvis = None
    for i in order + [k for k in range(J)]:
        if len(kids[i]) >= 3:
            pelvis = i
            break
    if pelvis is None:
        return None, "no bone with 3+ branches (pelvis)"
    py = pos[pelvis] @ UP
    ups = [k for k in kids[pelvis] if top(k) > py]
    if not ups:
        return None, "no branch going up from the pelvis (spine)"
    spine0 = max(ups, key=lambda k: (depth(k), -k))
    legs = [k for k in kids[pelvis] if k != spine0 and pos[tip(k)] @ UP < py and len(chain(k)) >= 3]
    if len(legs) < 2:
        return None, f"{len(legs)} leg(s) going down from the pelvis"
    if len(legs) > 2:  # keep the pair with knees farthest apart
        pairs = [(a, b) for a in legs for b in legs if a < b]
        legs = list(max(pairs, key=lambda ab: np.linalg.norm(pos[chain(ab[0])[1]] - pos[chain(ab[1])[1]])))
    spine = chain(spine0)
    chest = spine[-1]
    if len(kids[chest]) < 3:
        return None, f"chest has {len(kids[chest])} branches, need neck + 2 arms"
    cy = pos[chest] @ UP
    if cy < py:
        return None, "chest below pelvis"
    def walk(i):  # down the deepest child each time (skips short side leaves like cape bits)
        c = [i]
        while kids[c[-1]]:
            c.append(max(kids[c[-1]], key=lambda k: (depth(k), -k)))
        return c

    # facing: toes point forward; left = up x forward. A skeleton without toe bones (or with toes straight down) faces
    # the way the glTF spec says assets face: +Z, their left is +X.
    fw = np.zeros(3)
    for lg in legs:
        c = walk(lg)
        if len(c) >= 4:
            fw += pos[c[3]] - pos[c[2]]
    fw -= (fw @ UP) * UP
    facing = "toes"
    if not np.any(fw):
        fw, facing = np.array([0.0, 0.0, 1.0]), "glTF front +Z"
    left = np.cross(UP, fw / np.linalg.norm(fw))
    side = lambda i: float((pos[tip(i)] - pos[pelvis]) @ left)
    ck = [k for k in kids[chest] if depth(k) >= 2]  # arms have 3+ bones along the deepest way
    if len(ck) < 2 or len(kids[chest]) < 3:
        return None, f"chest has {len(kids[chest])} branches ({len(ck)} long), need neck + 2 arms"
    L_arm, R_arm = max(ck, key=side), min(ck, key=side)
    if not (side(L_arm) > 0 > side(R_arm)):
        return None, "no arm on each side"
    rest_ = [k for k in kids[chest] if k not in (L_arm, R_arm)]
    neck0 = max(rest_, key=top)
    if top(neck0) < cy:
        return None, "nothing above the chest (head)"
    L_leg, R_leg = sorted(legs, key=side, reverse=True)
    if not side(L_leg) > 0 > side(R_leg):
        return None, "no leg on each side"
    m = {pelvis: "Hips"}
    names = ["Spine", "Spine1", "Spine2"]
    for i, b in enumerate(spine):
        m[b] = names[i] if i < 2 else ("Spine2" if b == chest else None)
    m = {k: v for k, v in m.items() if v}
    m[chest] = "Spine2" if len(spine) >= 3 else names[len(spine) - 1]
    nk = chain(neck0)
    if len(nk) == 1:
        m[nk[0]] = "Head"
    else:
        m[nk[0]] = "Neck"
        m[nk[1]] = "Head"
    def name_fingers(hand, s):
        """Fingers = the hand's branches that go on from the hand (not back up the arm). Thumb = the one most
        forward (palms face down/in in a T or A pose, the thumb points forward); the rest from the front back:
        index, middle, ring, pinky (fewer fingers: index, then pinky last). Up to 3 bones each, Mixamo style."""
        fwd_arm = pos[hand] - pos[parents[hand]]
        roots = [k for k in kids[hand] if (pos[k] - pos[hand]) @ fwd_arm >= -1e-9 or depth(k) >= 1]
        if not roots or (len(roots) == 1 and not kids[roots[0]]):  # a lone end bone is the hand's tip, not a finger
            return 0
        thumb = max(roots, key=lambda k: float((pos[k] - pos[hand]) @ fw))
        rest = sorted([k for k in roots if k != thumb], key=lambda k: -float((pos[k] - pos[hand]) @ fw))
        order = {0: [], 1: ["Index"], 2: ["Index", "Pinky"], 3: ["Index", "Middle", "Pinky"]}.get(len(rest), ["Index", "Middle", "Ring", "Pinky"])
        named = 0
        for root, f in [(thumb, "Thumb")] + list(zip(rest, order)):
            for i, b in enumerate(walk(root)[:3], 1):
                m[b] = f"{s}Hand{f}{i}"
                named += 1
        return named

    fingers_named = {}
    # collarbone or not, decided once for both arms (mirror names): with it, upper arm c1->c2 ~= forearm c2->c3
    vote = 0.0
    for root in (L_arm, R_arm):
        c = walk(root)
        if len(c) < 4:
            vote = -1e9
            break
        seg = lambda a, b: float(np.linalg.norm(pos[c[b]] - pos[c[a]]))
        vote += abs(np.log(seg(0, 1) / seg(1, 2))) - abs(np.log(seg(1, 2) / seg(2, 3)))
    with_clav = vote > 0
    for s, root in (("Left", L_arm), ("Right", R_arm)):
        c = walk(root)
        roles = ["Shoulder", "Arm", "ForeArm", "Hand"] if with_clav else ["Arm", "ForeArm", "Hand"]
        for b, r in zip(c, roles):
            m[b] = s + r
        hand = c[len(roles) - 1] if len(c) >= len(roles) else None
        if hand is not None:
            fingers_named[s] = name_fingers(hand, s)
    for s, root in (("Left", L_leg), ("Right", R_leg)):
        for b, r in zip(walk(root), ["UpLeg", "Leg", "Foot", "ToeBase"]):
            m[b] = s + r
    info = {"facing": facing, "spine": len(spine), "neck": len(nk),
            "clav": [m.get(L_arm) == "LeftShoulder", m.get(R_arm) == "RightShoulder"], "fingers": fingers_named}
    return (m, info), None


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for p in map(Path, sys.argv[2:]):
        j, rest = read(p)
        pos, parents, nodes = skeleton(j, rest)
        res, why = label(pos, parents)
        if res is None:
            print(f"RENAME {p.stem}: NOT humanoid ({why}), left as is")
            continue
        m, info = res
        for b, nm in m.items():
            j["nodes"][nodes[b]]["name"] = nm
        write(out / p.name, j, rest)
        print(f"RENAME {p.stem}: {len(m)}/{len(nodes)} named {info}")
