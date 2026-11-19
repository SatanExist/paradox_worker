"""The joint-envelope rule shared by parts.py and inner.py: where on the body two bones may share skin.
Two bones may blend at a point only if it lies inside the envelope of EVERY joint between them (the joints whose
turning pulls the two bones' copies of the point apart); a joint's envelope is a ball of ENV x its limb radius (the
distance from the joint to the nearest skin; ENV 2 = Blender's envelope radius + equal fade distance). Across one
joint (parent and child) skin always blends: that is the joint itself."""
import numpy as np
from scipy.spatial import cKDTree


class Envelope:
    def __init__(self, skin_points, heads, kids, env=2.0):
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

    def may_blend(self, pts, A_, B_, chunk=50000):
        """Point pts[i] may blend bones A_[i] and B_[i]."""
        res = np.empty(len(pts), bool)
        for s0 in range(0, len(pts), chunk):
            sl = slice(s0, s0 + chunk)
            D = np.linalg.norm(pts[sl, None, :] - self.heads[None], axis=2) / self.env
            m = self.PM[A_[sl], B_[sl]]
            res[sl] = ((D * m).max(1) <= 1) | (m.sum(1) <= 1)
        return res
