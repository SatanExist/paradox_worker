"""The joint-envelope rule shared by parts.py and inner.py: where on the body two bones may share skin.
Two bones may blend at a point only if it lies inside the envelope of EVERY joint between them (the joints whose
turning pulls the two bones' copies of the point apart); a joint's envelope is a ball of ENV x its limb radius (the
distance from the joint to the nearest skin; ENV 2 = Blender's envelope radius + equal fade distance). Across one
joint (parent and child) skin always blends: that is the joint itself.
A cloth joint (a bone chain added for a cape or skirt, marked "cloth" in the node's extras) has no limb and no radius:
the cloth is one sheet, so its envelope is unbounded. Two cloth bones blend anywhere; a cloth bone and a body bone
blend only where the body's own joints between them allow."""
import numpy as np
from scipy.spatial import cKDTree


class Envelope:
    def __init__(self, skin_points, heads, kids, env=2.0, cloth=None):
        J = len(heads)
        self.heads = heads
        par = np.full(J, -1)
        for p_, ks in enumerate(kids):
            for c_ in ks:
                par[c_] = p_
        self.par = par

        def up(x):
            r = []
            while x >= 0:
                r.append(x)
                x = par[x]
            return r

        # joints between two bones: the heads of the path bones below their lowest common ancestor
        PM = np.zeros((J, J, J), bool)
        for A_ in range(J):
            ua = up(A_)
            for B_ in range(J):
                ub = up(B_)
                lca = next(x for x in ua if x in ub)
                for x in ua[:ua.index(lca)] + ub[:ub.index(lca)]:
                    PM[A_, B_, x] = True
        self.PM = PM
        self.rad = cKDTree(skin_points).query(heads)[0]  # limb radius at each joint
        self.env = np.maximum(env * self.rad, 1e-9)
        if cloth is not None:
            self.env[np.asarray(cloth, bool)] = np.inf

    def may_blend(self, pts, A_, B_):
        """Point pts[i] may blend bones A_[i] and B_[i]. Only the joints between each pair are measured (points grouped
        by pair): the same numbers as measuring every joint and masking, without the points x all-joints table."""
        J = len(self.heads)
        res = np.ones(len(pts), bool)
        pair = np.asarray(A_, np.int64) * J + np.asarray(B_, np.int64)
        order = np.argsort(pair, kind="stable")
        keys, starts = np.unique(pair[order], return_index=True)
        ends = np.append(starts[1:], len(order))
        for key, s0, s1 in zip(keys.tolist(), starts.tolist(), ends.tolist()):
            joints = np.flatnonzero(self.PM[key // J, key % J])
            if len(joints) <= 1:  # across one joint skin always blends
                continue
            idx = order[s0:s1]
            P = pts[idx]
            ok = np.ones(len(idx), bool)
            for x in joints.tolist():
                ok &= np.linalg.norm(P - self.heads[x], axis=1) / self.env[x] <= 1
            res[idx] = ok
        return res
