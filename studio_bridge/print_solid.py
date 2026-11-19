"""Make a model one closed solid for printing while keeping its surface: the print pipeline's step 1.

Generated models come in two kinds. TRELLIS draws a thin double "paper skin" (0.15–0.5 mm) around a
hollow, with holes into it; Hunyuan draws one surface, open in places or already closed. A slicer
prints a paper skin as paper. So candidates are built, measured against the original, and the
best one is kept ("auto pick"). Every model first gets a local repair (cut a small patch round every
defect and refill it by a minimum-weight triangulation, faces near the cut split to its size first); then:

  repair     drop inside-out pockets and crumbs, one exact self-union (CGAL via libigl), bridge pieces
             floating within 1.5 mm. The surface stays as modelled, apart from the patches.
  solidify   only for a paper skin (repaired walls thinner than 1 mm on average, 2·V/A), or when no other
             candidate came out solid: the chamber behind the raw skin (space a 3 mm ball can't reach
             from outside) becomes a solid block, fused by one union with the wrap below. Nothing is
             cut away, so no surface goes missing. On a real solid the "chamber" would be its own
             interior, so solids never get this.
  wrap       CGAL Alpha Wrap at 0.5 mm, then the same bridges. Closed and manifold by construction, and it
             fills thin openwork (beads, lace) solid, at the cost of rounding up to 0.5 mm. Only built for
             models that came in open.
  restored   the repair with the original's own faces it lost given back as slabs, whenever it lost some.

Candidates are built in the order they usually win, and the rest are skipped once one can't be beaten
(kept everything, one part, nothing seen changed by a print layer): on a real solid the repair, on a paper
skin solidify and wrap, with the repair only when neither came out solid. On the corpus the repair never
won on a paper skin and the wrap never won after a clean repair.

A candidate that left original surface behind (farther than 1 mm and outside the result) on more than
0.1 % of it fails. A paper result (walls under 1 mm) loses to any solid one. On resin a result that left the
chamber behind the skin hollow loses to one that filled it (see Printer.hollow_traps). Of the rest the one that
changed least where it shows wins, measured both ways (see _measure), after each is thickened as it will be
printed (see _pick_printed).
When every result is paper the report says so (thinWalls). Lengths are in mm at the working print height.
"""

from __future__ import annotations

import os
import gc
import time
from dataclasses import dataclass
from typing import Any, Callable

BALL_MM = 3.0  # a chamber is space a ball this size can't reach from outside
FINE_BALL_MM = 1.0  # and its narrow parts are where a ball this size fits that can't come in either (see _chamber_block)
WRAP_ALPHA_MM = 0.5
WRAP_OFFSET_MM = 0.02  # hugs the surface: the wrap sits 0.02 mm outside it
RESTORE_FAR_MM = 0.3  # original surface this far outside the repair was lost by it: given back (see _restored)
SLAB_FLOOR_MM = 0.02  # a given-back slab goes at least this deep, and is cut back no shallower where it folds (see _slabs)
BRIDGE_REACH_MM = 1.5  # pieces floating farther than this and than their own length are left as they are
BRIDGE_FIRST_MM = 0.5  # pieces this close are tied first; the step grows by BRIDGE_STEP until all that can be are (see _bridge)
BRIDGE_STEP = 1.5
CRUMB_MM3 = 1.0
SPECK_MM = 2.0  # loose pieces smaller than this, clear of the rest, are dust: left out of wrap and solidify (see _undusted)
SPECK_TOUCH_MM = 0.05  # a piece this close to a bigger one is part of it
LOST_MM = 1.0
LOST_MAX_SHARE = 0.001
MAX_VOXELS = 60_000_000  # chamber grid; the distance transforms take ~25 bytes a voxel at peak
SKIN_MM = 1.0  # mean wall (2·volume/area) below this is a paper skin with a hollow to fill
SAMPLES = 200_000
SEED = 0
VIS_RAYS = 32  # rays per point when telling surface seen from outside from hidden
PATCH_MM = 0.5  # the local repair cuts this far round a defect, as much farther each round (see _local_repair)
LEAN_FROM_FACES = 2_000_000  # meshes this big drop their cached tables after each stage (see _lean)
COLLECT_FROM_FACES = 500_000  # and from this size what the stage left is freed at once (see _lean)
THICKNESS_SAMPLES = 100_000  # surface points the wall thickness is measured at
THICKNESS_CONE_DEG = 20.0  # six rays round the inward normal at this angle, plus the normal itself
THIN_SPOT_CELL_MM = 2.0  # thin points closer than this belong to the same spot
THIN_SPOT_MIN_MM2 = 1.0  # smaller thin spots are tips and needle points, not walls: not reported
THICKEN_MARGIN_MM = 0.05  # thickened walls come out this much over the minimum, on each side
THICKEN_NEAR_MM = 1.2  # how far from a thin wall the surface may move at all
THICKEN_EDGE_MM = 0.6  # edges there are cut down to this, so the surface can bend
THICKEN_NARROW_EDGE_MM = 0.3  # and to this where the two sides of a wall cancel: a narrow strap needs vertices in the middle of its sides
THICKEN_REACH = 9.0  # how far a wall's direction is averaged: about the square root of this many faces
THICKEN_STAIR_LOSS = 1.5  # a staircase's averaged normal is shorter than one: made up for, to this many times
THICKEN_TOLERANCE_MM = 0.02  # the thickened mesh is simplified within this, far under a 0.2 mm layer
TAPER_CORR = -0.7  # a thin patch whose thickness falls this steadily toward its rim (rank correlation) is a tapered edge
TAPER_MEET = 0.25  # if its two sides meet at the rim: thinner there than this share of a nozzle line (PrusaSlicer's min_feature_size)
TAPER_LONG = 2.0  # and it runs along the rim at least as far as it reaches in: area / reach² this much, both sides counted
LEAF_REACH_MM = 3.0  # a thin patch no farther than this from thick wall, all along, is a short leaf on the body ...
LEAF_WIDE = 1.0  # ... if it is joined along as long as it reaches out (area / reach² at least this): grown only to print
STEADY_TIP_DEG = 10.0  # a model that must tilt this far before it falls stands steady; less is wobbly
FALLS_TIP_DEG = 3.0  # under this it falls at a breath: laid down, or given a base
UPRIGHT_TILT_DEG = 25.0  # a face it can rest on this close to straight down means it was made to stand
TILT_FREE_DEG = 3.0  # it may be tilted this much onto a face it rests on: nobody sees it
LYING_TRIES = 6  # laid down: this many of the steadiest hull faces and this many of the biggest are really tried
CUT_MAX_MM = 2.0  # the bottom is cut flat by at most this much (and 3 % of the height)
CUT_STEP_MM = 0.1
HOLD_MM2 = 20.0  # plate contact for the first layer to hold (upright models; one lying down is held by supports)
LIP_MM2 = 25.0  # a cut may shave this much of a bottom ledge thin (soles: 2-20 mm²; a book cover, a bust rim: 60-100)
BASE_MM = 2.0  # height of an added base
SUPPORT_SLOPE_DEG = 40.0  # a face sloping less than this down from flat gets support (PrusaSlicer's MK4 default)
SUPPORT_CELL_MM = 1.0  # a support column stands on the first surface below it within a cell this wide
SUPPORT_SAMPLES_PER_MM2 = 8.0  # surface points for the support estimate (fewer, and big models read wrong)
TURN_CONTACT_MM2 = 50.0  # turned for printing, it must still sit on the plate with this much
TURN_APART_DEG = 15.0  # candidates closer than this to one another or to how it stands are the same way up
TURN_POOL = 12  # ways up the full estimate looks at
TURN_TWIN_SUPPORT = 1.1  # of two ways up that are nearly the same, the steadier goes on with up to this much more support
TURN_TRIED = 3  # of them, at most this many go to the slicer
TURN_TRY_GAIN = 0.1  # and only for this much less support by the estimate
TURN_TRY_MIN_CM3 = 1.0  # and at least this much: nothing goes to the slicer on most models
TURN_SAVES_MIN = 5.0  # by the slicer, it is suggested only if this much faster
TURN_SAVES_G = 1.0  # and this much lighter. The slicer is touchy: hunyuan31_mech tilted under a degree reads +2, -16, -25 min


@dataclass(frozen=True)
class Printer:
    """What a kind of printer can print: every physical threshold of the print prep comes from here."""
    name: str
    layer_mm: float  # first layer: a piece no higher than this above the plate starts on it
    print_layer_mm: float  # the layers it prints in (the slicer's layer_height): a change smaller hides in their lines
    min_wall_mm: float  # thinner than this a wall or a strand is fragile
    min_print_mm: float  # thinner than this it doesn't print at all (one nozzle line, the finest resin detail)
    skin_mm: float  # mean wall (2·volume/area) below this is a paper skin with a hollow to fill
    wrap_alpha_mm: float  # the wrap rounds openings and grooves up to this
    lost_mm: float  # original surface farther than this from the result is lost
    bridge_reach_mm: float  # pieces floating farther than this and than their own length are left as they are
    shell_mm: float = 0.9  # printed solid this deep under the surface: two 0.45 mm perimeters (top/bottom 0.8-1.0 mm)
    infill: float = 0.15  # share of the inside filled deeper than that (PrusaSlicer's 15 %); 1 = printed solid
    # a hollow skin is also filled on its own surface (see _filled). Off for fdm for now: its walls must grow to 0.8 mm,
    # trellis2_crown's 0.33 mm strands then grow into each other (625k self-crossings) and thicken's exact union took
    # 310 s and 14 GB where the wrap's coat had left it 4 s; resin's 0.4 mm took 94 s and 5.7 GB.
    fill_own_surface: bool = False
    # a hollow left inside holds liquid: resin can't drain from it and we make no drain holes (slicers ask for them:
    # Lychee 3-5 mm, Formlabs 2.5 mm on Form 3, 0.75 mm on Form 4; under 0.5 mm they close). So when the chamber behind
    # the skin was found, a result that left it hollow loses to one that filled it (see _pick). Measuring the drain
    # instead ("space a drain-sized ball can't leave") was tried on 30 resin candidates on 2026-11-16: grooves on the
    # surface came out as hundreds of 0.04-0.9 cm³ pockets on every model, apart from Chandelier_01's hollow vase
    # (4.2 cm³, a 0.5-1 mm slit) only by a hand-picked volume. fdm prints a hollow as walls round it, so no.
    hollow_traps: bool = False
    # what it prints in: plate width (X), depth (Z) and height (Y), mm. fdm: the MK4 of print_mk4.ini (bed_shape,
    # max_print_height); resin: a mid-size 12K printer (Elegoo Saturn 4 Ultra, 218.88 x 122.88 x 220)
    plate_mm: tuple[float, float, float] = (250.0, 210.0, 220.0)
    nozzle_mm: float | None = 0.4  # fdm only
    slicer_ini: str = "print_mk4.ini"  # PrusaSlicer's settings for it, beside print_slicer.py (fdm only)
    slicer_name: str = "Prusa MK4, 0.4 mm nozzle, 0.20 mm layers, PLA"


# fdm: a 0.4 mm nozzle at 0.2 mm layers, two lines per wall; its solid thresholds are the corpus-proven ones.
# resin: 0.05 mm layers, walls from 0.4 mm (Formlabs' guide for supported walls), detail from 0.2 mm, kept closer.
PRINTERS = {
    "fdm": Printer("fdm", layer_mm=0.2, print_layer_mm=0.2, min_wall_mm=0.8, min_print_mm=0.4, skin_mm=SKIN_MM, wrap_alpha_mm=WRAP_ALPHA_MM, lost_mm=LOST_MM,
                   bridge_reach_mm=BRIDGE_REACH_MM),
    "resin": Printer("resin", layer_mm=0.05, print_layer_mm=0.05, min_wall_mm=0.4, min_print_mm=0.2, skin_mm=0.6, wrap_alpha_mm=0.3, lost_mm=0.5, bridge_reach_mm=1.0,
                     infill=1.0, fill_own_surface=True, hollow_traps=True, plate_mm=(218.0, 122.0, 220.0), nozzle_mm=None),
}
DEFAULT_PRINTER = "fdm"
# Other nozzles on the same MK4: Prusa's own presets for them (print_mk4_n*.ini). The line is what the nozzle lays
# (one line doesn't print thinner), a wall that holds is two of them; the solid walls under the surface are its
# perimeters (0.25: three of 0.27 mm, 0.6: two of 0.68), its layers the preset's (0.15, 0.32 mm). The first layer is 0.2 mm on all three. The thresholds that
# go by the model's own detail (skin, wrap, lost, bridge reach) stay the 0.4's.
NOZZLES = {
    0.25: dict(print_layer_mm=0.15, min_wall_mm=0.5, min_print_mm=0.25, shell_mm=0.81, slicer_ini="print_mk4_n025.ini",
               slicer_name="Prusa MK4, 0.25 mm nozzle, 0.15 mm layers, PLA"),
    0.6: dict(print_layer_mm=0.32, min_wall_mm=1.2, min_print_mm=0.6, shell_mm=1.36, slicer_ini="print_mk4_n06.ini",
              slicer_name="Prusa MK4, 0.6 mm nozzle, 0.32 mm layers, PLA"),
}


def printer_for(name: str | None, nozzle_mm: float | None = None) -> Printer:
    """The printer asked for: "fdm" (default) or "resin", and for fdm a nozzle of NOZZLES (any other, or none, is
    the 0.4 mm one)."""
    import dataclasses

    printer = PRINTERS.get(str(name or DEFAULT_PRINTER), PRINTERS[DEFAULT_PRINTER])
    try:
        nozzle = round(float(nozzle_mm), 2) if nozzle_mm is not None else None
    except (TypeError, ValueError):
        nozzle = None
    if printer.name == "fdm" and nozzle in NOZZLES:
        printer = dataclasses.replace(printer, nozzle_mm=nozzle, **NOZZLES[nozzle])
    return printer

Log = Callable[[str], None]


# --- local repair ----------------------------------------------------------------------------------


def _lean(m):
    """On a big mesh, drop trimesh's cached tables (edges, face adjacency, ...) but keep the normals, then free what
    the stage left. The tables are rebuilt on demand, so nothing changes, but on millions of faces each check left
    gigabytes behind, and meshes hold reference cycles, so a finished stage's meshes went only when the cycle
    collector got round to them: direct3ds2_knight 16.3 -> 11.2 GB, meshy_rover 9.1 -> 7.8 GB, same output bytes.
    Below LEAN_FROM_FACES clearing the tables only cost time (+6-15 %), they are rebuilt anyway.
    The collection alone starts lower, at COLLECT_FROM_FACES: when the collector runs on its own depends on how many
    objects the program holds, so unrelated code shifted it and a 1.7M-face knight kept several stages' meshes at once
    (peak 7.9 GB, over the 7 GB guard). Collecting here and after each repair round: knight 7.52 -> 5.26 GB,
    hunyuan_necromutant 6.93 -> 5.23, hunyuan_operative 6.27 -> 4.14, same output bytes and time on 8 heavy models."""
    if len(m.faces) >= LEAN_FROM_FACES:
        m._cache.clear(exclude=("face_normals", "vertex_normals"))
    if len(m.faces) >= COLLECT_FROM_FACES:
        gc.collect()
    return m


ZIP_REL = 1e-7  # open-rim vertices this close (share of the bbox diagonal) are one point (see zip_rims)


def zip_rims(m):
    """`m` (welded) with open rims that lie on each other sewn shut: an open-edge vertex closer than ZIP_REL of the
    model's size to another open-edge vertex becomes that vertex, then welded again. merge_vertices rounds to 8
    digits, so two copies of one point 6e-9 apart can land in two bins (chess_set from Poly Haven: the board is two
    open half-boxes mouth to mouth; left open, the repair dropped the middle of the board and the give-back laid it
    back askew). Only open-edge vertices move: welding every vertex by distance also collapsed real tiny triangles
    and opened holes (hunyuan31_camera 2 -> 62 open edges). Returns `m` itself when nothing is that close."""
    import numpy as np
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    import trimesh

    rim = np.unique(m.edges_sorted[trimesh.grouping.group_rows(m.edges_sorted, require_count=1)])
    if len(rim) < 2:
        return m
    V = np.asarray(m.vertices, np.float64)
    pairs = cKDTree(V[rim]).query_pairs(ZIP_REL * float(np.linalg.norm(V.max(0) - V.min(0))), output_type="ndarray")
    if not len(pairs):
        return m
    _, lab = connected_components(sp.coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(rim),) * 2),
                                  directed=False)
    first = np.full(lab.max() + 1, len(rim))
    np.minimum.at(first, lab, np.arange(len(rim)))  # each cluster goes to its first vertex: the same every run
    V[rim] = V[rim[first[lab]]]
    m.vertices = V
    return _weld(m)


def _weld(m):
    m.merge_vertices(merge_tex=True, merge_norm=True)  # by position only: what a slicer sees
    m.update_faces(m.nondegenerate_faces())
    m.update_faces(m.unique_faces())
    m.remove_unreferenced_vertices()
    return m


def _edge_use(m, directed: bool):
    import numpy as np

    e = m.faces[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2).astype(np.int64)
    if not directed:
        e = np.sort(e, axis=1)
    _, inv, cnt = np.unique(e[:, 0] * len(m.vertices) + e[:, 1], return_inverse=True, return_counts=True)
    return cnt[inv.ravel()].reshape(-1, 3)


def _open_faces(m):
    """Faces on an edge that isn't shared by exactly two faces: holes and fins."""
    return (_edge_use(m, directed=False) != 2).any(axis=1)


def _twisted_faces(m):
    """Faces on a seam where the surface can't be oriented: an edge walked twice in the same direction."""
    return (_edge_use(m, directed=True) > 1).any(axis=1)


def _ms(m):
    import numpy as np
    import pymeshlab

    ms = pymeshlab.MeshSet()
    ms.add_mesh(pymeshlab.Mesh(np.asarray(m.vertices, np.float64), np.asarray(m.faces, np.int32)))
    return ms


def _from_ms(ms):
    import trimesh

    cm = ms.current_mesh()
    return _weld(trimesh.Trimesh(cm.vertex_matrix(), cm.face_matrix(), process=False))


def _reorient(m, log: Log):
    import pymeshlab

    ms = _ms(m)
    try:
        ms.meshing_re_orient_faces_coherently()
    except pymeshlab.PyMeshLabException:  # a fin left over: settle the edges first, then orient
        ms.meshing_repair_non_manifold_edges(method=0)
        ms.meshing_repair_non_manifold_vertices()
        try:
            ms.meshing_re_orient_faces_coherently()
        except pymeshlab.PyMeshLabException:
            log("  reorient skipped: still not 2-manifold")
    return _from_ms(ms)


def _cut_around(m, bad, radius: float):
    """The bad faces, their first ring, and every face within `radius` mm of them."""
    import numpy as np
    from scipy.spatial import cKDTree

    sel = bad.copy()
    v = np.zeros(len(m.vertices), dtype=bool)
    v[m.faces[bad].ravel()] = True
    sel |= v[m.faces].any(axis=1)
    near = cKDTree(m.triangles_center[bad]).query(m.vertices, distance_upper_bound=radius)[0] < radius
    sel |= near[m.faces].all(axis=1)
    return sel


def _split_longest(V, F, need, E, fe, L):
    """Longest-edge refinement (M.-C. Rivara, "Algorithms for refining triangular grids suitable for adaptive and
    multigrid techniques", 1984; the 4T / LEPP closure): each face in `need` has its longest edge split; any face
    with a split edge that is not its longest gets its longest split too, until nothing changes (the closure ends:
    each step moves to a strictly longer edge). Every face then has its longest edge split, alone or with one or two
    others, and is cut along the median from that edge's midpoint first: the smallest angle stays at least half the
    original's (Rivara), no slivers from the cutting itself. Ties among equal edges go to the lower edge number.
    `E`, `fe`, `L`: the mesh's unique edges, each face's three of them (edge r runs from corner r to r+1), lengths."""
    import numpy as np

    rank = np.empty(len(E), np.int64)
    rank[np.lexsort((np.arange(len(E)), L))] = np.arange(len(E))
    lr = np.argmax(rank[fe], axis=1)  # which of the face's edges is its longest
    longest = fe[np.arange(len(F)), lr]
    mark = np.zeros(len(E), bool)
    mark[longest[need]] = True
    while True:
        has = mark[fe].any(axis=1) & ~mark[longest]
        if not has.any():
            break
        mark[longest[has]] = True
    nid = np.full(len(E), -1, np.int64)
    m = np.flatnonzero(mark)
    nid[m] = len(V) + np.arange(len(m))
    V2 = np.vstack([V, V[E[m]].mean(1)])
    mk = mark[fe]
    k = mk.sum(1)
    out = [F[k == 0]]
    for r in range(3):
        sel = (k > 0) & (lr == r)
        a, b, c = F[sel, r], F[sel, (r + 1) % 3], F[sel, (r + 2) % 3]  # longest edge a->b, far corner c
        f = fe[sel]
        n = nid[f[:, r]]  # midpoint of a->b
        nbc, nca = nid[f[:, (r + 1) % 3]], nid[f[:, (r + 2) % 3]]
        hb, ha = mk[sel, (r + 1) % 3], mk[sel, (r + 2) % 3]  # b->c split, c->a split
        # the median n->c first: halves (a, n, c) and (n, b, c), each split again where its other edge is
        x = ~ha
        out.append(np.c_[a[x], n[x], c[x]])
        x = ha
        out += [np.c_[a[x], n[x], nca[x]], np.c_[n[x], c[x], nca[x]]]
        x = ~hb
        out.append(np.c_[n[x], b[x], c[x]])
        x = hb
        out += [np.c_[n[x], b[x], nbc[x]], np.c_[n[x], nbc[x], c[x]]]
    return V2, np.vstack(out)


def _refine_cut(m, radius: float, size: float, rounds: int = 200):
    """The faces near the first cut split down to `size`, so a cut `radius` mm round a defect takes that much and
    not whole faces: generated models carry faces of several mm (hunyuan_lighthouse: edges 4.9 mm median, the cut
    took 41 % of its surface), and what a cut takes the repair can lose. Faces the cut needs finer: those it removes
    outright (touching a defect face, see _cut_around) and those its ball's surface crosses, while longer than
    `size`. Split by longest-edge refinement (see _split_longest): splitting the crossing edges alone never ends on
    a long thin face, the new edge from the midpoint to the far corner crosses the ball again as long as before
    (hunyuan31_drill: one 0.64 mm edge split 26 times; tripo_blaster 10 439 -> 203 480 faces in 30 rounds);
    red-green refinement (Bank, Sherman & Weiser 1983) spread on big faces (tripo_blaster, 43 mm faces: 363 614).
    Midpoint splits: the surface doesn't move. `rounds` only stops a runaway: a face's longest edge halves at least
    every other split."""
    import numpy as np
    import trimesh
    from scipy.spatial import cKDTree

    V, F = np.asarray(m.vertices, np.float64), np.asarray(m.faces, np.int64)
    for _ in range(rounds):
        t = trimesh.Trimesh(V, F, process=False)
        bad = _open_faces(t)
        if not bad.any():
            break
        E, fe, L = t.edges_unique, t.faces_unique_edges, t.edges_unique_length
        bv = np.zeros(len(V), bool)
        bv[F[bad].ravel()] = True
        ring = bv[F].any(axis=1)
        d = cKDTree(t.triangles_center[bad]).query(V, distance_upper_bound=4 * radius + L.max())[0]
        inside = (d < radius)[F]
        crossed = inside.any(axis=1) & ~inside.all(axis=1)
        need = (ring | crossed) & (L[fe].max(axis=1) > size)
        if not need.any():
            break
        V, F = _split_longest(V, F, need, E, fe, L)
    return trimesh.Trimesh(V, F, process=False)


def _rim_vertices(F, nv: int):
    """Vertices on an open half-edge (one whose reverse no face holds)."""
    import numpy as np

    a = F.ravel()
    b = np.roll(F, -1, axis=1).ravel()
    open_ = ~np.isin(a * nv + b, b * nv + a)
    rim = np.zeros(nv, bool)
    rim[a[open_]] = True
    rim[b[open_]] = True
    return rim


def _hole_loops(F, rim):
    """Every hole as a simple loop of vertices, in the order its faces walk them. `F`: the faces with a corner on the
    rim, `rim`: the rim's vertices (the walk only turns round rim vertices, whose faces are all in `F`; a half-edge
    without its reverse here is open in the whole mesh only when both its ends are on the rim). Where holes touch the
    walk keeps to its own fan of faces, and a loop that still passes a vertex twice is split there."""
    he = {}
    for f, (a, b, c) in enumerate(F.tolist()):
        he[(a, b)] = (f, 0)
        he[(b, c)] = (f, 1)
        he[(c, a)] = (f, 2)
    used, out = set(), []
    for h0 in [k for k in he if rim[k[0]] and rim[k[1]] and (k[1], k[0]) not in he]:
        if h0 in used:
            continue
        loop, h = [], h0
        while h is not None and h not in used:
            used.add(h)
            loop.append(h[0])
            f, k = he[h]
            g = (F[f][(k + 1) % 3], F[f][(k + 2) % 3])
            turned = set()
            while (g[1], g[0]) in he:
                # where faces round a vertex disagree on their direction (an edge walked twice the same way, before
                # the repair orients the surface), turning can come back to where it began: no rim there
                if g in turned:
                    g = None
                    break
                turned.add(g)
                f2, k2 = he[(g[1], g[0])]
                g = (F[f2][(k2 + 1) % 3], F[f2][(k2 + 2) % 3])
            h = g
        if h != h0:
            continue
        stack = [loop]
        while stack:
            lp = stack.pop()
            seen = {}
            for i, v in enumerate(lp):
                if v in seen:
                    j = seen[v]
                    stack += [lp[j:i], lp[:j] + lp[i:]]
                    break
                seen[v] = i
            else:
                if len(lp) >= 3:
                    out.append(lp)
    return out


def _flat(Q) -> bool:
    """All points on the line through the first and last (to rounding): a polygon of no area."""
    import numpy as np

    a, b = Q[0], Q[-1]
    d = b - a
    L = np.linalg.norm(d)
    if L == 0:
        return np.ptp(Q, axis=0).max() <= 1e-9
    return np.linalg.norm(np.cross(Q - a, d / L), axis=1).max() <= 1e-9 * L


def _split_hole(V, loop, adj, gap: float):
    """A hole split where its rim comes back within `gap` (the cut's diameter) of itself: two corners that close,
    not neighbours along the rim nor joined by a mesh edge, were parted only by the cut. Shortest split first, then
    each part again. Meshmixer and Cyclone 3DR split big holes the same way, by hand. Filled whole, a hole the cut
    opened round a thin strap or a fold spans the strap's two sides with one flat patch."""
    import numpy as np
    from scipy.spatial import cKDTree

    out, stack = [], [loop]
    while stack:
        lp = stack.pop()
        n = len(lp)
        best = None
        if n >= 6:
            P = V[lp]
            pairs = cKDTree(P).query_pairs(gap, output_type="ndarray")
            if len(pairs):
                i, k = pairs[:, 0], pairs[:, 1]
                arc = np.minimum(k - i, n - (k - i))
                d = np.linalg.norm(P[i] - P[k], axis=1)
                # a vertex meshlab split where the surface pinched leaves two copies on one spot: no split between them
                good = (arc >= 2) & (d > 0) & np.array([lp[b] not in adj.get(lp[a], ()) for a, b in zip(i, k)], bool)
                order = np.lexsort((k, i, d))  # shortest first; ties by position, so the same mesh splits the same way
                for j in order[good[order]]:
                    a, b = int(i[j]), int(k[j])
                    # both parts must be real polygons: points close along a straight run of the rim give a flat part
                    if _flat(P[a:b + 1]) or _flat(np.vstack([P[b:], P[:a + 1]])):
                        continue
                    best = (a, b)
                    break
        if best is None:
            out.append(lp)
            continue
        a, b = best
        stack += [lp[a:b + 1], lp[b:] + lp[:a + 1]]
    return out


def _unit(n):
    import numpy as np

    ln = np.linalg.norm(n, axis=-1, keepdims=True)
    return n / np.where(ln > 0, ln, 1.0), ln[..., 0]


def _fill_hole(V, F, loop, adj, he, base: int):
    """Triangles closing one hole by Liepa's minimum-weight triangulation (P. Liepa, "Filling holes in meshes",
    SGP 2003; the same weight as CGAL's triangulate_hole: first the largest dihedral angle, then the total area,
    both smallest), written here because it has to know the mesh round the hole: a triangle may not use a chord that
    is already an edge of the mesh (it would be that edge's third face). CGAL's polyline version doesn't know the
    mesh; its mesh version gives up on long rims. The dynamic program is the textbook O(n³) one, a whole diagonal at
    a time in numpy. Points on straight runs of the rim (split points) carry no shape: they are left out of the
    search and put back by fanning the triangle on their run from its centroid.
    `loop`: the rim's vertices in the order its faces walk them; `adj`: each vertex's neighbours (sets); `he`:
    (a, b) -> the face holding the half-edge a->b. Each triangle holds the rim edges reversed. Returns the triangles
    and the new vertices (numbered from `base`); nothing when no triangulation avoids the mesh's edges."""
    import numpy as np

    loop = list(loop)
    n0 = len(loop)
    p = V[loop]
    u = p - np.roll(p, 1, 0)
    w = np.roll(p, -1, 0) - p
    straight = (np.linalg.norm(np.cross(u, w), axis=1) <= 1e-9 * np.linalg.norm(u, axis=1) * np.linalg.norm(w, axis=1)) & ((u * w).sum(1) > 0)
    keep = np.flatnonzero(~straight)
    n = len(keep)
    if n < 3:
        return [], []
    K = [loop[i] for i in keep]
    P = V[K].astype(np.float64)
    runs = [[loop[(keep[j] + s) % n0] for s in range(1, (keep[(j + 1) % n] - keep[j]) % n0 or n0)] for j in range(n)]
    pos = {v: j for j, v in enumerate(K)}
    # chords already in the mesh
    chord_ok = np.ones((n, n), bool)
    for i, a in enumerate(K):
        for b in adj.get(a, ()):
            k = pos.get(b)
            if k is not None:
                chord_ok[i, k] = chord_ok[k, i] = False
    # the mesh face on each rim edge (corner j -> j+1): its unit normal, for the dihedral at the rim
    rim_n = np.zeros((n, 3), np.float32)
    for j in range(n):
        a = K[j]
        b = runs[j][0] if runs[j] else K[(j + 1) % n]
        f = he.get((a, b))
        if f is not None:
            t = V[F[f]]
            rim_n[j] = _unit(np.cross(t[1] - t[0], t[2] - t[0]))[0]
    scale = float(np.ptp(P, axis=0).max()) or 1.0
    Wa = np.full((n, n), np.inf)  # largest dihedral measure (1 - cos) inside the sub-polygon i..k
    Ws = np.full((n, n), np.inf)  # its area
    Nr = np.zeros((n, n, 3), np.float32)  # unit normal of the triangle on chord (i, k), in rim order
    O = np.full((n, n), -1, np.int64)
    idx = np.arange(n - 1)
    Wa[idx, idx + 1] = 0.0
    Ws[idx, idx + 1] = 0.0
    for g in range(2, n):
        I = np.arange(n - g)[:, None]
        M = I + 1 + np.arange(g - 1)[None, :]
        Kk = I + g
        nrm, ln = _unit(np.cross(P[M] - P[I], P[Kk] - P[I]))
        nrm = nrm.astype(np.float32)
        area = ln / 2
        # the neighbour across (i, m) and (m, k): the triangle chosen there, or the mesh face where it is a rim edge
        cl = np.einsum("abc,abc->ab", nrm, Nr[I, M])
        cr = np.einsum("abc,abc->ab", nrm, Nr[M, Kk])
        cl[:, 0] = -np.einsum("ac,ac->a", nrm[:, 0], rim_n[I[:, 0]])
        cr[:, -1] = -np.einsum("ac,ac->a", nrm[:, -1], rim_n[M[:, -1]])
        a = np.maximum(np.maximum(1 - cl, 1 - cr), np.maximum(Wa[I, M], Wa[M, Kk]))
        s = Ws[I, M] + Ws[M, Kk] + area
        ok = np.isfinite(s) & (ln > 1e-12 * scale * scale)
        if g == n - 1:  # the last triangle also sits on the rim edge n-1 -> 0
            a = np.maximum(a, 1 + np.einsum("abc,c->ab", nrm, rim_n[n - 1]))
        else:
            ok &= chord_ok[I, Kk]
        a = np.where(ok, a, np.inf)
        s = np.where(ok, s, np.inf)
        amin = a.min(1, keepdims=True)
        s2 = np.where(a <= amin, s, np.inf)
        best = s2.argmin(1)
        r = np.arange(n - g)
        i, k, m = r, r + g, r + 1 + best
        Wa[i, k] = a[r, best]
        Ws[i, k] = s2[r, best]
        O[i, k] = m
        Nr[i, k] = nrm[r, best]
    if not np.isfinite(Ws[0, n - 1]):
        return [], []
    T = []
    stack = [(0, n - 1)]
    while stack:
        i, k = stack.pop()
        if k - i < 2:
            continue
        m = int(O[i, k])
        T.append((i, m, k))
        stack += [(i, m), (m, k)]
    out, new = [], []
    for i, m, k in T:
        # the triangle's sides in rim order i->m->k->i, each with the rim points on it (only rim edges have any)
        ring = []
        for a_, b_ in ((i, m), (m, k), (k, i)):
            ring.append(K[a_])
            if (b_ - a_) % n == 1 and runs[a_]:
                ring += runs[a_]
        ring = ring[::-1]  # the patch runs the rim the other way
        if len(ring) == 3:
            out.append(tuple(ring))
            continue
        # points on its sides: fanned from a new point at the triangle's centroid, in its plane: no shape change
        c = base + len(new)
        new.append(P[[i, m, k]].mean(0))
        out += [(ring[t], ring[(t + 1) % len(ring)], c) for t in range(len(ring))]
    return out, new


def _close_holes_near(ms, gap: float) -> None:
    """Every hole of the current mesh closed: split where its rim comes back within `gap` of itself (see _split_hole),
    each part filled by Liepa's triangulation (see _fill_hole). The tables are built on the faces round the holes
    only: everything looked up is a rim vertex's or a rim edge's (hunyuan31_scorpion, 930 000 faces: built on the
    whole mesh they took 11 s of a 27 s repair, and memory enough to stop the wrap beside it).
    Until 2026-11-19 meshlab's close_holes filled them: on a hole round a thin strap or a fold it spanned both sides
    with one flat patch, and it left zero-width slits where a rim runs straight through split points."""
    import numpy as np
    import pymeshlab

    cm = ms.current_mesh()
    V, F = cm.vertex_matrix(), cm.face_matrix().astype(np.int64)
    rim = _rim_vertices(F, len(V))
    near = np.flatnonzero(rim[F].any(axis=1))
    Fn = F[near]
    adj, he = {}, {}
    for f, (a, b, c) in zip(near.tolist(), Fn.tolist()):
        he[(a, b)] = he[(b, c)] = he[(c, a)] = f
        for x, y in ((a, b), (b, c), (c, a)):
            adj.setdefault(x, set()).add(y)
            adj.setdefault(y, set()).add(x)
    tris, newv = [], []
    for hole in _hole_loops(Fn, rim):
        for lp in _split_hole(V, hole, adj, gap):
            t, nv = _fill_hole(V, F, lp, adj, he, len(V) + len(newv))
            tris += t
            newv += nv
            for tri in t:  # the next hole must not reuse this one's new edges either
                for x, y in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
                    adj.setdefault(x, set()).add(y)
                    adj.setdefault(y, set()).add(x)
    if tris:
        V2 = np.vstack([V] + ([np.array(newv)] if newv else []))
        ms.add_mesh(pymeshlab.Mesh(V2, np.vstack([F, np.array(tris, np.int64)]).astype(np.int32)))


def _local_repair(m, log: Log, rounds: int = 10, cut_first: bool = True):
    """Keep the surface; cut a small patch round each defect and refill it, growing the patch each round. The faces
    near the first cut are split down to its size first (see _refine_cut)."""
    import numpy as np
    import trimesh

    m = _weld(m)
    n0 = len(m.faces)
    m = _refine_cut(m, PATCH_MM, PATCH_MM)
    if len(m.faces) != n0:
        log(f"  refined round the first cut: {n0} -> {len(m.faces)} faces")
        # a midpoint can land on a vertex across a crack (a T-junction): welded, the crack closes before any cut
        # (tripo_sword: 3 open faces fewer in the first round)
        m = _weld(m)
    for r in range(rounds):
        lab = trimesh.graph.connected_component_labels(m.face_adjacency, node_count=len(m.faces))
        area = np.bincount(lab, m.area_faces)
        keep = area >= max(area.max() * 1e-4, 0.5)  # crumbs: under 0.5 mm² of surface
        if not keep.all():
            m.update_faces(keep[lab])
            m.remove_unreferenced_vertices()
        bad, kind = _open_faces(m), "open"
        if not bad.any():  # orientation only means something once every edge has two faces
            m = _reorient(m, log)
            bad, kind = _twisted_faces(m), "twisted"
        if not bad.any():
            break
        log(f"  repair round {r}: {kind} faces {int(bad.sum())}, pieces {int(keep.sum())}")
        radius = PATCH_MM * (r + 1) if cut_first else PATCH_MM * max(r, 1)
        if cut_first or r or not _open_faces(m).any():
            m.update_faces(~_cut_around(m, bad, radius))
            m.remove_unreferenced_vertices()
        ms = _ms(m)
        ms.meshing_repair_non_manifold_edges(method=0)
        ms.meshing_repair_non_manifold_vertices()
        _close_holes_near(ms, 2 * radius)
        m = _from_ms(ms)
        del ms
        if len(m.faces) >= COLLECT_FROM_FACES:  # the round's meshes go now, not whenever the collector runs (see _lean)
            gc.collect()
    m = _reorient(m, log)
    trimesh.repair.fix_normals(m)
    return _lean(m)


# --- the exact chain -------------------------------------------------------------------------------


def _chamber_block(m, log: Log, ball_mm: float = BALL_MM):
    """The chamber behind the skin as a solid block, reaching just into the skin so a union with the closed
    shell fuses the two. Nothing of the skin is deleted, so nothing of its surface can go missing. Works on
    the raw skin, holes and all: the ball can't get through a hole narrower than itself. The chamber is where
    the ball fits, plus the narrow parts joined to it, where only a FINE_BALL_MM ball fits and can't come in
    from outside either: trellis2_armor's legs are tubes open at the foot, and the gaps by their walls stayed
    voids once the wrap went into the tubes (it had come out solid only because dust plugged their ends).
    Returns the block (None when there is no chamber) and its volume in cm³."""
    import numpy as np
    import trimesh
    from scipy import ndimage
    from skimage.measure import marching_cubes

    ext = float(m.extents.max())
    p = max(0.25, ext / 480)
    for _ in range(3):  # a big boxy model gets coarser voxels instead of more memory
        lo = m.bounds[0] - ball_mm - 2 * p
        dims = np.ceil((m.bounds[1] + ball_mm + 2 * p - lo) / p).astype(int) + 1
        if np.prod(dims) <= MAX_VOXELS:
            break
        p *= (np.prod(dims) / MAX_VOXELS) ** (1 / 3) * 1.01
    pts, _ = trimesh.sample.sample_surface(m, int(m.area / (p * 0.4) ** 2), seed=SEED)
    skin = np.zeros(dims, dtype=bool)
    idx = np.clip(np.floor((np.vstack([pts, m.vertices]) - lo) / p).astype(int), 0, dims - 1)
    skin[tuple(idx.T)] = True
    del pts, idx
    free = ndimage.distance_transform_edt(~skin).astype(np.float32) * p  # how far each voxel is from the skin

    def rolled(r: float):
        """Where balls of radius r that can't come in from outside reach, and the space balls from outside don't."""
        clear = free > r  # ball centres that fit
        lab, _ = ndimage.label(clear)
        reach = lab == lab[0, 0, 0]  # the ones that get in from outside
        del lab
        outside = ndimage.distance_transform_edt(~reach).astype(np.float32) * p <= r  # all those balls sweep
        del reach
        inner = ~skin & ~outside
        deep = inner & clear
        del clear
        # every ball that fits in the chamber, rolled out to its full size: a round ball can't squeeze through
        # a crack in the skin, so the block stops at the skin and never fills the grooves on the outside
        rolled_out = inner & (ndimage.distance_transform_edt(~deep).astype(np.float32) * p <= r) if deep.any() else deep
        return rolled_out, inner, outside

    chamber, interior, outside = rolled(ball_mm)
    if not chamber.any():
        return None, 0.0
    narrow = rolled(FINE_BALL_MM)[0]
    del free
    lab, _ = ndimage.label(chamber | narrow)
    del narrow
    chamber = np.isin(lab, np.unique(lab[chamber])) & interior  # the narrow parts joined to it, never where big balls from outside sweep
    del lab
    cm3 = float(chamber.sum()) * p**3 / 1000
    # skin voxels with the outside next to them: a skin only a voxel thick (trellis2_harbor's cliff walls) is
    # nothing but those, and a block reaching into them came out through the wall as a wavy ridge along the rows
    # of voxels
    rim = skin & ndimage.binary_dilation(outside & ~skin)
    del outside
    chamber = ndimage.binary_dilation(chamber, mask=interior)  # the last voxel up to the skin
    del interior
    chamber = ndimage.binary_dilation(chamber, mask=chamber | (skin & ~rim))  # and one into it, never through it
    del skin, rim
    field = ndimage.gaussian_filter(chamber.astype(np.float32), 0.6)  # soften the voxel steps
    del chamber
    V, F, _, _ = marching_cubes(field, level=0.5, spacing=(p, p, p))
    del field
    block = trimesh.Trimesh(V + lo, F, process=False)
    if block.volume < 0:
        block.invert()
    block = _drop_pockets(block)
    log(f"  chamber {cm3:.1f} cm3 at {p:.2f} mm; block {len(block.faces)} faces")
    return block, cm3


def _drop_pockets(m):
    """Inside-out shells (sealed pockets within the body) and crumbs under 1 mm³ go: the body is solid there."""
    import trimesh

    parts = m.split(only_watertight=False)
    if len(parts) <= 1:
        return _lean(m)
    kept = [q for q in parts if q.volume > CRUMB_MM3]
    return _lean(trimesh.util.concatenate(kept)) if kept else _lean(m)


def _manifold_union(meshes):
    """The union of several closed, crossing-free meshes (a body and its bridges, a shell and its block) by
    Manifold: the same shape as CGAL's on the corpus (≤0.0003 mm) in 2–3% of the time. None when Manifold isn't
    installed or won't take an input as a closed manifold, so the caller falls back to CGAL."""
    try:
        import manifold3d as mf
    except ImportError:
        return None
    import numpy as np
    import trimesh

    parts = []
    for m in meshes:
        p = mf.Manifold(mf.Mesh64(vert_properties=np.ascontiguousarray(m.vertices, np.float64),
                                  tri_verts=np.ascontiguousarray(m.faces, np.uint64)))
        if p.status() != mf.Error.NoError:
            return None
        parts.append(p)
    g = mf.Manifold.batch_boolean(parts, mf.OpType.Add).to_mesh64()
    # copies: a view would keep Manifold's buffers alive past the call
    return trimesh.Trimesh(np.array(g.vert_properties[:, :3], np.float64), np.array(g.tri_verts, np.int64), process=False)


def _union(*meshes):
    """One union. Several meshes: Manifold when it takes them all (see _manifold_union). One mesh, or what
    Manifold won't take: one exact union in CGAL arithmetic, which resolves every self-crossing. Needs
    consistently oriented input."""
    import igl.copyleft.cgal as cgal
    import numpy as np
    import trimesh

    if len(meshes) > 1:
        out = _manifold_union(meshes)
        if out is not None:
            return out
    allm = trimesh.util.concatenate(list(meshes)) if len(meshes) > 1 else meshes[0]
    V, F, _ = cgal.mesh_boolean(np.asarray(allm.vertices, np.float64), np.asarray(allm.faces, np.int64), type_str="union")
    return trimesh.Trimesh(V, F, process=False)


def _undusted(m):
    """`m` without its dust, loose pieces under SPECK_MM clear of every bigger piece: what wrap and solidify are
    made of (`m` itself when it has none). The wrap tents over a speck within its alpha and the surface under
    it, a tooth: trellis2_lattice has 445 specks 0.05-1 mm off its rods, and they made a row of teeth along each
    rod. Specks farther off ended as crumbs pinned to the rods by _bridge, or dropped as floating. The chamber
    block leaves the same out, or the holes it kept round specks inside a hollow would stay as voids
    (trellis2_armor's legs)."""
    import igl
    import numpy as np
    import trimesh

    F = np.asarray(m.faces, np.int64)
    lab = trimesh.graph.connected_component_labels(m.face_adjacency, node_count=len(F))
    n = int(lab.max()) + 1 if len(lab) else 0
    if n <= 1:
        return m
    V = np.asarray(m.vertices, np.float64)
    vlab = np.zeros(len(V), np.int64)
    vlab[F.ravel()] = np.repeat(lab, 3)
    used = np.unique(F)
    lo, hi = np.full((n, 3), np.inf), np.full((n, 3), -np.inf)
    np.minimum.at(lo, vlab[used], V[used])
    np.maximum.at(hi, vlab[used], V[used])
    small = (hi - lo).max(1) < SPECK_MM
    if not small.any() or small.all():
        return m
    at = used[small[vlab[used]]]
    d2 = igl.point_mesh_squared_distance(V[at], V, F[~small[lab]])[0]
    gap = np.full(n, np.inf)
    np.minimum.at(gap, vlab[at], np.sqrt(d2))
    dust = small & (gap > SPECK_TOUCH_MM)
    if not dust.any():
        return m
    out = trimesh.Trimesh(V, F[~dust[lab]], process=False)
    out.remove_unreferenced_vertices()
    return out


def _skin(orig, shared: dict[str, Any]):
    """The original without its dust (see _undusted), made once for wrap and solidify."""
    if "skin" not in shared:
        shared["skin"] = _undusted(orig)
    return shared["skin"]


def _wrap(V, F, alpha: float, offset: float = WRAP_OFFSET_MM):
    """CGAL Alpha Wrap: always a closed, manifold, self-intersection-free shell. F None wraps the points alone."""
    import numpy as np
    import trimesh
    from CGAL.CGAL_Alpha_wrap_3 import Int_Vector, Point_3_Vector, Polygon_Vector, alpha_wrap_3
    from CGAL.CGAL_Kernel import Point_3
    from CGAL.CGAL_Polyhedron_3 import Polyhedron_3

    pts = Point_3_Vector()
    pts.reserve(len(V))
    for x, y, z in np.asarray(V, float).tolist():
        pts.append(Point_3(x, y, z))
    P = Polyhedron_3()
    if F is None:
        alpha_wrap_3(pts, alpha, offset, P)
    else:
        polys = Polygon_Vector()
        polys.reserve(len(F))
        for a, b, c in np.asarray(F, np.int64).tolist():
            iv = Int_Vector()
            iv.append(a)
            iv.append(b)
            iv.append(c)
            polys.append(iv)
        alpha_wrap_3(pts, polys, alpha, offset, P)
    # The bindings have no array export. Their OFF writer took longer than the wraps themselves on big shells
    # (25 s at 0.86M faces, harbor 204 s over 8 wraps), so the mesh is read off the handles, in the writer's
    # order and rounded to the 5 significant digits it wrote: the same vertices and faces, byte for byte.
    X = []
    for i, v in enumerate(P.vertices()):
        v.set_id(i)
        p = v.point()
        X.append((p.x(), p.y(), p.z()))
    Fo = []
    for f in P.facets():
        h = f.halfedge()
        a = h.vertex().id()
        h = h.next()
        Fo.append((a, h.vertex().id(), h.next().vertex().id()))
    V5 = np.array([float(f"{x:.5g}") for x in np.asarray(X, np.float64).ravel()], np.float64).reshape(-1, 3)
    return trimesh.Trimesh(V5, np.asarray(Fo, np.int64).reshape(-1, 3), process=False)


def _bridge(m, log: Log, printer: "Printer | None" = None):
    """Pieces floating next to the body (a feather, a bead, a block off a rover, a strand by the feet) get a
    bridge: a round pin where piece and body come closest, then one exact union of everything. The rest of the
    surface is untouched. A piece is tied when the bridge is shorter than the piece is long, or within the
    printer's bridge reach however small: a bridge longer than the piece would read as a stick. A piece that only
    touches gets a pin across the touch. A piece tied joins the body, and the nearest pieces are tied first, so each
    hangs on its closest neighbour:
    trellis2_lattice's wall rods end 1 mm from a corner post, and tied in waves, before the post was part of the
    body, they hung on 12-92 mm sticks down to the floor frame (11 over 20 mm; now none over 3.6 mm).
    The pin is as thick as the piece it holds (4·volume/area is a rod's diameter), from the thinnest rod thicken
    leaves to two walls across: the lattice's 0.9 mm rods and crumbs had 1.6 mm stubs.
    Returns the mesh and how many pieces were bridged."""
    import igl
    import numpy as np
    import trimesh

    printer = printer or PRINTERS[DEFAULT_PRINTER]
    # the body is the biggest piece by volume, as split_floating takes it: by face count a dense small piece
    # (a smooth moon over a box-like house) would be the body and the house be pinned to it
    parts = sorted(m.split(only_watertight=False), key=lambda q: (-abs(float(q.volume)), -len(q.faces)))
    if len(parts) <= 1:
        return _lean(m), 0
    n_parts = len(parts)
    body, rest = parts[0], parts[1:]
    del parts
    r_min, r_max = printer.min_wall_mm / 2 + THICKEN_MARGIN_MM, printer.min_wall_mm
    reach = np.array([max(printer.bridge_reach_mm, float(q.extents.max())) for q in rest])
    sizes = np.array([len(q.vertices) for q in rest])
    starts = np.cumsum(sizes) - sizes
    P = np.vstack([q.vertices for q in rest])
    d2, near = np.full(len(P), np.inf), np.zeros_like(P)  # each piece vertex's closest point on the body so far
    loose = np.ones(len(rest), dtype=bool)
    pieces, joined, bridged, welded, level = [body], [body], 0, 0, BRIDGE_FIRST_MM
    while True:
        if joined:  # one tree for what joined last, measured from the loose pieces only
            B = joined[0] if len(joined) == 1 else trimesh.util.concatenate(joined)
            at = np.flatnonzero(np.repeat(loose, sizes))
            got, _, hit = igl.point_mesh_squared_distance(P[at], B.vertices, B.faces)
            closer = got < d2[at]
            d2[at[closer]], near[at[closer]] = got[closer], hit[closer]
            del B, got, hit
        gap = np.sqrt(np.minimum.reduceat(d2, starts))
        can = loose & (gap <= reach)
        if not can.any():
            break
        take = np.flatnonzero(can & (gap <= level))
        if not len(take):
            level *= BRIDGE_STEP
            joined = []
            continue
        joined = [rest[i] for i in take]
        loose[take] = False
        for i in take:
            q, k = rest[i], starts[i] + int(np.argmin(d2[starts[i]:starts[i] + sizes[i]]))
            a, b = P[k], near[k]
            if gap[i] < 1e-3:
                # touching, yet a piece of its own after the union that made `m`: they meet at a point or along an
                # edge, a hinge with no thickness (trellis2_crown's petal under the stone, once filled kept its own
                # surface). Welded by a pin across the touch along the piece's normal there, its radius each way.
                u = np.asarray(q.vertex_normals[k - starts[i]], np.float64)
                if not np.isfinite(u).all() or np.linalg.norm(u) < 0.5:
                    continue
                u, b = u / np.linalg.norm(u), a
                welded += 1
            else:
                u = (b - a) / gap[i]
            r = float(np.clip(2 * abs(float(q.volume)) / max(float(q.area), 1e-9), r_min, r_max))
            # from inside the piece to inside the body, by the pin's own radius at each end
            pieces.append(trimesh.creation.cylinder(radius=r, segment=[a - u * r, b + u * r], sections=16))
            bridged += 1
        pieces += joined
    pieces += [rest[i] for i in np.flatnonzero(loose)]
    del joined, rest, P, d2, near  # the union below is the peak: nothing it doesn't need stays alive
    _lean(m)
    out = _union(*pieces)
    del pieces
    shells = out.split(only_watertight=False)
    if len(shells) > 1:
        out = trimesh.util.concatenate([s for s in shells if s.volume > CRUMB_MM3])  # pockets the union sealed
    log(f"  bridges: {n_parts} pieces, {bridged} bridged ({welded} touching, welded)")
    return _lean(out), bridged


def _thickness(m) -> float | None:
    """Mean wall thickness 2·V/A in mm; None while the mesh isn't closed."""
    if not m.is_watertight or m.area <= 0:
        return None
    return float(2 * abs(m.volume) / m.area)


def _tick(shared: dict[str, Any], stage: str, since: float) -> float:
    """Add the time since `since` to the stage of the candidate being built; returns the time now."""
    now = time.time()
    stages = shared.setdefault("stages", {})
    stages[stage] = round(stages.get(stage, 0.0) + now - since, 1)
    return now


def _finish(m, log: Log, shared: dict[str, Any]):
    t = time.time()
    m = _drop_pockets(m)
    try:
        m = _drop_pockets(_union(m))
    except Exception as exc:  # non-orientable seams can still break it; the slicer copes with crossings
        log(f"  self-union failed, kept as is: {exc}")
    log(f"  self-union {time.time() - t:.0f}s")
    t = _tick(shared, "union", t)
    m, bridged = _bridge(m, log, shared["printer"])
    log(f"  bridges {time.time() - t:.0f}s")
    _tick(shared, "bridges", t)
    return m, {"piecesBridged": bridged}


_WRAP_CHILD = r"""
import os, sys, threading, time
def alive(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
    if not h:
        return False
    try:
        return k.WaitForSingleObject(h, 0) != 0  # not signalled: still running
    finally:
        k.CloseHandle(h)
def watch(pid):  # between C calls: gone with its parent
    while alive(pid):
        time.sleep(0.5)
    os._exit(1)
if sys.platform.startswith("linux"):  # and during them: the kernel kills it with its parent
    import ctypes, signal
    ctypes.CDLL(None).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG
threading.Thread(target=watch, args=(int(sys.argv[4]),), daemon=True).start()
sys.path.insert(0, sys.argv[1])
import numpy as np
from studio_bridge.print_solid import _wrap
with np.load(sys.argv[2]) as d:
    V, F, alpha, offset = d["V"], d["F"], float(d["alpha"]), float(d["offset"])
m = _wrap(V, F, alpha, offset)
np.savez(sys.argv[3] + ".part.npz", V=np.asarray(m.vertices, np.float64), F=np.asarray(m.faces, np.int64))
os.replace(sys.argv[3] + ".part.npz", sys.argv[3])
"""

# Kills the wrap child once the whole tool (this process and its children) passes its budget: the memory guard
# counts the child too, and a tool stopped there is rerun coarser, so the wrap made beside the repair must never
# be what pushes it over. A process of its own: a thread here can't run while a C call holds the GIL.
_WRAP_WATCH = r"""
import os, sys, time
from pathlib import Path
tool, child, limit = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
if sys.platform.startswith("linux"):
    import ctypes, signal
    ctypes.CDLL(None).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG: gone with the tool
try:
    import psutil
except ImportError:
    psutil = None
def tree(pid):  # (resident bytes of pid and all below it, pids of its direct children)
    if psutil is not None:
        p = psutil.Process(pid)
        return sum(q.memory_info().rss for q in [p, *p.children(recursive=True)]), {q.pid for q in p.children()}
    total, todo, page, kids = 0, [pid], os.sysconf("SC_PAGE_SIZE"), set()
    while todo:
        p = todo.pop()
        try:
            total += int(Path(f"/proc/{p}/statm").read_text().split()[1]) * page
            for task in Path(f"/proc/{p}/task").iterdir():
                below = [int(c) for c in (task / "children").read_text().split()]
                todo += below
                if p == pid:
                    kids.update(below)
        except (OSError, ValueError):
            if p == pid:
                raise ProcessLookupError(pid)
    return total, kids
while True:
    try:
        used, kids = tree(tool)
    except Exception:
        sys.exit(0)  # the tool is gone
    if child not in kids:
        sys.exit(0)  # the wrap is done and reaped
    if used > limit:
        if psutil is not None:
            c = psutil.Process(child)
            for q in [*c.children(recursive=True), c]:
                q.kill()
        else:
            os.kill(child, 9)
        sys.exit(0)
    time.sleep(0.2)
"""
# The tool's budget with the wrap child beside it: a quarter of the guard's limit (TOOLS_MEMORY_GB, read the
# same way) kept for what the repair still grows by between two looks.
WRAP_BESIDE_SHARE = 0.75


class _WrapLater:
    """A _wrap made by another Python while this one goes on: the shell of a model that came open is needed by
    both wrap and solidify, and it depends on nothing the local repair does, so it is wrapped beside the repair
    instead of after it. The same function on the same arrays: the same mesh. The child goes when this process
    does, even when it is killed (the memory guard): on Linux the kernel kills it (PR_SET_PDEATHSIG; a watching
    thread can't run while the wrap holds the GIL), elsewhere it notices between calls. A venv's python.exe on
    Windows is a launcher whose child dies with it. (Watching stdin instead hung the child at start on Windows:
    a thread blocked on the pipe stalls the imports.) Not used when it can't start: `result` is then None and
    the caller wraps here."""

    def __init__(self, V, F, alpha: float, offset: float = WRAP_OFFSET_MM):
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        import numpy as np

        self.dir = tempfile.mkdtemp(prefix="wrap-")
        self.out = str(Path(self.dir) / "out.npz")
        inp = str(Path(self.dir) / "in.npz")
        np.savez(inp, V=np.asarray(V, np.float64), F=np.asarray(F, np.int64), alpha=alpha, offset=offset)
        self.proc = subprocess.Popen([sys.executable, "-c", _WRAP_CHILD, str(Path(__file__).resolve().parent.parent), inp, self.out,
                                      str(os.getpid())],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        limit = WRAP_BESIDE_SHARE * float(os.getenv("TOOLS_MEMORY_GB") or 7.0) * 2**30
        self.watch = subprocess.Popen([sys.executable, "-c", _WRAP_WATCH, str(os.getpid()), str(self.proc.pid), str(limit)],
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def result(self):
        import numpy as np
        import trimesh

        try:
            if self.proc.wait() != 0:
                return None
            with np.load(self.out) as d:
                return trimesh.Trimesh(d["V"], d["F"], process=False)
        except Exception:  # noqa: BLE001 - the caller wraps here instead
            return None
        finally:
            self.cancel()

    def cancel(self) -> None:
        import shutil
        from pathlib import Path

        if not Path(self.dir).is_dir():
            return
        for proc in (self.proc, getattr(self, "watch", None)):
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait()
        for _ in range(20):  # the launcher's real child may hold its input a moment longer
            shutil.rmtree(self.dir, ignore_errors=True)
            if not Path(self.dir).exists():
                break
            time.sleep(0.25)

    def __del__(self):
        try:
            self.cancel()
        except Exception:  # noqa: BLE001 - interpreter shutting down
            pass


def _shell(orig, shared: dict[str, Any], log: Log):
    """The wrap of the original: built once, used by both wrap and solidify (started early, see _WrapLater)."""
    if "shell" not in shared:
        t = time.time()
        job = shared.pop("shellJob", None)
        shell = job.result() if job is not None else None
        if job is not None and shell is None:
            log("  wrap beside the repair stopped (memory) or failed: wrapped here")
        skin = _skin(orig, shared)
        shared["shell"] = shell if shell is not None else _wrap(skin.vertices, skin.faces, shared["printer"].wrap_alpha_mm)
        log(f"  wrap {time.time() - t:.0f}s")
        _tick(shared, "wrap", t)
    return shared["shell"].copy()


def _repaired(orig, repaired, shared, log: Log):
    return _finish(repaired.copy(), log, shared)


def _block(orig, shared: dict[str, Any], log: Log):
    """The chamber block behind the skin and its volume (see _chamber_block), made once for solidify and filled."""
    if "block" not in shared:
        t = time.time()
        shared["block"] = _chamber_block(_skin(orig, shared), log)
        log(f"  chamber {time.time() - t:.0f}s")
        _tick(shared, "chamber", t)
    block, chamber = shared["block"]
    if block is None:
        raise RuntimeError("no chamber behind the skin")
    return block, chamber


def _solidified(orig, repaired, shared, log: Log):
    """The closed wrap of the skin, fused with a block filling the chamber behind it."""
    block, chamber = _block(orig, shared, log)
    shell = _shell(orig, shared, log)
    t = time.time()
    m = _drop_pockets(_union(shell, block))  # gaps the block didn't reach are sealed pockets: filled too
    log(f"  fill union {time.time() - t:.0f}s")
    t = _tick(shared, "union", t)
    m, bridged = _bridge(m, log, shared["printer"])
    _tick(shared, "bridges", t)
    return m, {"chamberCm3": round(float(chamber), 2), "piecesBridged": bridged}


def _filled(orig, repaired, shared, log: Log):
    """Solidify on the original's own surface: the closed repair fused with the same chamber block, and what the
    repair lost given back as modelled (see _restored). Solidify's wrap remakes every face a hair outside it and
    can't follow a groove narrower than its alpha: it spanned trellis2_crown's grooves between strands with rows of
    teeth, and coated the rest 0.05-0.2 mm thick (2.6 of its 10.9 cm³ for resin, the teeth unchanged by a wrap twice
    as fine, which took 11 times as long)."""
    if repaired is None or not repaired.is_watertight:
        raise RuntimeError("the repair didn't close")
    block, chamber = _block(orig, shared, log)
    t = time.time()
    m = _drop_pockets(_union(repaired.copy(), block))
    m, given, slabs, single = _given_back(orig, m, shared["printer"], log)
    log(f"  fill union {time.time() - t:.0f}s, given back {given} faces as {slabs} slabs and {single} single faces")
    t = _tick(shared, "union", t)
    m, bridged = _bridge(m, log, shared["printer"])
    _tick(shared, "bridges", t)
    return m, {"chamberCm3": round(float(chamber), 2), "piecesBridged": bridged, "facesGivenBack": given}


def _wrapped(orig, repaired, shared, log: Log):
    shell = _shell(orig, shared, log)
    t = time.time()
    m, bridged = _bridge(shell, log, shared["printer"])
    _tick(shared, "bridges", t)
    return m, {"piecesBridged": bridged}


def _lost_faces(orig, m):
    """The original's faces m lost: a corner or the centre off m by over RESTORE_FAR_MM and outside it. Returns
    those faces and the same with a ring round them, so what is given back reaches into the body."""
    import igl
    import numpy as np

    V, F = np.asarray(orig.vertices, np.float64), np.asarray(orig.faces, np.int64)
    Vm, Fm = np.asarray(m.vertices, np.float64), np.asarray(m.faces, np.int64)
    Q = np.vstack([V, V[F].mean(1)])
    far = np.sqrt(igl.point_mesh_squared_distance(Q, Vm, Fm)[0]) > RESTORE_FAR_MM
    out = np.zeros(len(Q), dtype=bool)
    if far.any():
        out[far] = _winding(Vm, Fm, Q[far], bool(m.is_watertight)) < 0.5
    bad_v, bad_c = out[: len(V)], out[len(V):]
    bad = bad_c | bad_v[F].any(1)
    grown = bad_v.copy()
    grown[F[bad].ravel()] = True
    return bad, grown[F].any(1)


def _inward(orig, idx, depth_max: float):
    """For the original's faces `idx`: which way is in, and how deep. In is the side where the original comes back
    sooner (a ray each way from the face's centre: an inside-out face of a broken model would otherwise grow
    outwards), and only as deep as that, up to `depth_max`: a strap thinner than a wall keeps its thickness, the
    thickening sees to it later. A face with nothing behind it either way (an open sheet) goes in along its normal.
    Where the face behind is given back too (both sides of a strap), the space between is shared: each goes in half
    of it, or the two copies swap places (the medial bound, as the Blender Solidify GSoC 2016 proposal bounds its
    depth by the shape's skeleton). Returns `flip` (the face's normal points in) and the depth."""
    import igl.embree
    import numpy as np

    V, Fa = np.asarray(orig.vertices, np.float64), np.asarray(orig.faces, np.int64)
    F = Fa[idx]
    n = np.asarray(orig.face_normals, np.float64)[idx]
    c = V[F].mean(1)
    ei = igl.embree.EmbreeIntersector()
    ei.init(np.asfortranarray(V, np.float32), np.asfortranarray(Fa, np.int32), True)
    back = np.full((len(F), 2), np.inf)
    hit = np.full((len(F), 2), -1, np.int64)
    for j, sgn in enumerate((-1.0, 1.0)):
        start, d = (c + sgn * n * 1e-3).astype(np.float32), (sgn * n).astype(np.float32)
        for i in range(len(F)):
            f, t, _, _ = ei.intersectRay_first(start[i], d[i])
            if f >= 0:
                back[i, j] = t + 1e-3
                hit[i, j] = f
    flip = back[:, 1] < back[:, 0]
    near = back.argmin(1)
    t = back[np.arange(len(F)), near]
    h = hit[np.arange(len(F)), near]
    given = np.zeros(len(Fa), bool)
    given[idx] = True
    shared = (h >= 0) & given[np.maximum(h, 0)]
    return flip, np.clip(np.minimum(np.where(shared, t / 2, t), depth_max), SLAB_FLOOR_MM, depth_max)


def _prisms(V, F, n, flip, depth):
    """Faces F (vertex rows V, normals n) each as a solid: the face itself outside, a copy pushed in by `depth`."""
    import numpy as np
    import trimesh

    inward = np.where(flip[:, None], n, -n)
    outer = V[F]
    inner = outer + (inward * depth[:, None])[:, None, :]
    k = len(F)
    verts = np.concatenate([outer, inner], axis=1).reshape(-1, 3)  # per face: 3 outside, then 3 inside
    base = (np.arange(k) * 6)[:, None]
    # outside faces out: wound so its normal points away from `inward`
    o = np.where(flip[:, None], [[0, 2, 1]], [[0, 1, 2]])
    tri = [o, o[:, ::-1] + 3]
    for a, b in ((0, 1), (1, 2), (2, 0)):
        oa, ob = np.take_along_axis(o, np.full((k, 1), a), 1), np.take_along_axis(o, np.full((k, 1), b), 1)
        tri += [np.hstack([ob, oa, oa + 3]), np.hstack([ob, oa + 3, ob + 3])]
    faces_out = np.concatenate([t + base for t in tri], axis=0)
    return [trimesh.Trimesh(verts[i * 6:(i + 1) * 6], faces_out[i::k] - i * 6, process=False) for i in range(k)]


def _pinned(tris0, dv, m: int, k: int):
    """A slab's faces (see _slabs) with every vertex at depth 0 being its own outside vertex: faces that then repeat
    a vertex (a rim wall there) are gone, and where all three corners stayed the inside face lies on the outside one,
    reversed: no solid there, both go. Returns the faces (outside ones first) and how many are outside."""
    import numpy as np

    idx = np.arange(2 * m)
    idx[m:][dv <= 0] = np.flatnonzero(dv <= 0)
    T = idx[tris0]
    keep = (T[:, 0] != T[:, 1]) & (T[:, 1] != T[:, 2]) & (T[:, 2] != T[:, 0])
    flat = (dv[tris0[:k]] <= 0).all(1)
    keep[:k] &= ~flat
    keep[k:2 * k] &= ~flat
    return T[keep], int((~flat).sum())


def _crossing_pairs(V, T):
    """Pairs of faces that cross each other, by CGAL's exact test (via libigl)."""
    import igl.copyleft.cgal as cgal
    import numpy as np

    r = cgal.remesh_self_intersections(V, T, detect_only=True, first_only=False)
    return np.asarray(r[2], np.int64).reshape(-1, 2)


def _slabs(orig, faces, depth_max: float, body=None, log: Log = print):
    """The original's own faces `faces` as solids, so the surface stays exactly as modelled: each connected patch
    is one slab (patches part at an edge of three faces), the patch itself outside, a copy of it pushed in (see
    _inward) and walls round its rim. One solid per face met its neighbours wall to wall, and the union cut every shared wall into slivers (hunyuan31_scorpion:
    21k faces given back grew the body by 450k faces and the thickening ran out of memory). A patch whose own faces
    are wound against each other goes back face by face. Returns the solids, how many are slabs, and how many faces
    went back one by one.
    Where the full depth in still lands inside `body` (a sleeve over a core: tripo_sword's grip), the slab goes the
    full depth: what is behind is solid anyway, and a slab as thin as the gap to the core read as a thin wall, which
    the thickening blew up into ridges along its edges. Elsewhere (a strap hanging free) it stays as thin as modelled.
    The copy pushed in crossed itself on most slabs (14 of 24 on hunyuan_lighthouse, 25 of 27 on tripo_pack, 7 of 7 on
    hunyuan31_scorpion): two sides of a strap swapped places (the shared depth in _inward ends that), and at creases
    and small features a mitered copy folds whatever the depth bound (no depth bound alone promises a fold-free
    offset of a nonconvex shape). There the depth is cut back only at the vertices of the faces that still cross, by
    half each round (backtracking, as in flip-free mesh optimisation), by CGAL's exact test: from `depth_max` down to
    SLAB_FLOOR_MM that is at most log2(depth_max / floor) rounds. Where the original's own faces cross each other no
    depth helps: the slab goes as it is, as those faces went before. What still crosses at the floor is a knife edge,
    where the two sides of a sheet meet: only the faces round those crossings go back face by face (the whole patch
    face by face gave the scorpion 11k prisms; resolving the slab by itself pinched a thin strap to nothing, and the
    thickening then lost it). A slab thinner than a wall is fine: the thickening grows it, as a thin strap."""
    import math

    import numpy as np
    import trimesh

    idx = np.flatnonzero(faces)
    flip, depth = _inward(orig, idx, depth_max)
    n = np.asarray(orig.face_normals, np.float64)[idx]
    # full depth lands inside the body: along the normal (fills[:, 1]) or against it (fills[:, 0])
    fills = np.zeros((len(idx), 2), dtype=bool)
    if body is not None:
        cen = np.asarray(orig.vertices, np.float64)[np.asarray(orig.faces, np.int64)[idx]].mean(1)
        fills = (_winding(body.vertices, body.faces, np.vstack([cen - n * depth_max, cen + n * depth_max]),
                          bool(body.is_watertight)) > 0.5).reshape(2, -1).T
    sub = trimesh.Trimesh(np.asarray(orig.vertices, np.float64), np.asarray(orig.faces, np.int64)[idx], process=False)
    sub.merge_vertices()
    V, F = np.asarray(sub.vertices, np.float64), np.asarray(sub.faces, np.int64)
    area = np.asarray(sub.area_faces, np.float64)
    sound = (F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 2] != F[:, 0]) & (area > 0)
    # patches join only across edges of exactly two faces: an edge of three splits them
    pair = trimesh.grouping.group_rows(np.sort(F[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2), 1), require_count=2) // 3
    pair = pair[sound[pair].all(1)]
    comps = trimesh.graph.connected_components(pair, nodes=np.flatnonzero(sound), min_len=1)
    try:
        import manifold3d as mf
    except ImportError:
        mf = None
    out, loose = [], [np.flatnonzero(~sound)]
    rounds = max(1, math.ceil(math.log2(depth_max / SLAB_FLOOR_MM)))  # halvings down to the floor
    shrunk = knife = own = most = 0
    work = [(np.asarray(c, np.int64), None) for c in comps]
    while work:
        c, turn = work.pop()
        # In is decided once for the whole patch, by its faces' votes weighted by area: on a thin strap the two
        # rays come back nearly together and a quarter of the faces voted the wrong way one by one
        if turn is None:
            turn = float((area[c] * flip[c]).sum()) > 0.5 * float(area[c].sum())
        Fc = F[c][:, [0, 2, 1]] if turn else F[c]  # wound outwards
        inward_c = n[c] if turn else -n[c]
        e = Fc[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)
        _, inv, cnt = np.unique(np.sort(e, 1), axis=0, return_inverse=True, return_counts=True)
        inv = inv.ravel()
        if cnt.max() > 2 or len(np.unique(e, axis=0)) < len(e):  # the model's own faces disagree on their winding
            loose.append(c)
            continue
        uv, Fl = np.unique(Fc, return_inverse=True)
        Fl = Fl.reshape(-1, 3)
        m = len(uv)
        vn = np.zeros((m, 3))
        np.add.at(vn, Fl.ravel(), np.repeat(inward_c * area[c][:, None], 3, 0))
        ln = np.linalg.norm(vn, axis=1)
        if (ln < 1e-12).any():
            loose.append(c)
            continue
        vn /= ln[:, None]
        dv = np.full(m, np.inf)
        np.minimum.at(dv, Fl.ravel(), np.repeat(np.where(fills[c, int(turn)], depth_max, depth[c]), 3))
        P = V[uv]
        rim = Fl[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)[cnt[inv] == 1]
        a, b = rim[:, :1], rim[:, 1:]
        tris0 = np.vstack([Fl, Fl[:, ::-1] + m, np.hstack([b, a, a + m]), np.hstack([b, a + m, b + m])])
        ok = False
        for r in range(rounds + 1):
            tris, k = _pinned(tris0, dv, m, len(Fl))
            Vs = np.vstack([P, P + vn * dv[:, None]])
            X = _crossing_pairs(Vs, tris)
            if not len(X):
                ok = True
                break
            movable = X[(X >= k).any(1)]  # pairs with a face that moved: the inside copy or a rim wall
            if not len(movable):  # only the original's own faces cross each other
                ok = True
                own += 1
                break
            if r == rounds:
                break
            fs = np.unique(movable.ravel())
            vs = np.unique(tris[fs[fs >= k]].ravel())
            vs = vs[vs >= m] - m
            if (dv[vs] <= SLAB_FLOOR_MM).all():
                break
            dv[vs] = np.maximum(dv[vs] / 2, SLAB_FLOOR_MM)
            most = max(most, r + 1)
        if not ok:  # a knife edge: the faces round its crossings go face by face, the rest is a slab again
            bad_v = np.unique(tris[np.unique(movable.ravel())].ravel()) % m
            bad = np.isin(Fl, bad_v).any(1)
            loose.append(c[bad])
            flip[c[bad]] = turn  # in the way the patch voted, as deep as the slab got there
            depth[c[bad]] = dv[Fl[bad]].min(1)
            knife += 1
            if (~bad).any():
                work.append((c[~bad], turn))
            continue
        if r:
            shrunk += 1
        slab = trimesh.Trimesh(Vs, tris, process=False)
        if mf is not None:
            q = mf.Manifold(mf.Mesh64(vert_properties=np.ascontiguousarray(slab.vertices, np.float64),
                                      tri_verts=np.ascontiguousarray(slab.faces, np.uint64)))
            if q.status() != mf.Error.NoError or q.volume() <= 0:
                loose.append(c)
                knife += 1
                continue
        out.append(slab)
    loose = np.concatenate(loose)
    if len(loose):
        full = fills[loose, flip[loose].astype(int)]
        out += _prisms(V, F[loose], n[loose], flip[loose], np.where(full, depth_max, depth[loose]))
    log(f"  slabs: {len(comps)} patches, {shrunk} shrunk where they folded (up to {most} rounds), {knife} times faces "
        f"round a knife edge went one by one, {own} with the original crossing itself, {len(loose)} single faces")
    return out, len(out) - len(loose), len(loose)


def _restored(orig, repaired, shared, log: Log):
    """The repair keeps the original's own faces but can lose what its cuts took (tripo_pack's strap, the rim
    under its flap); the whole wrap keeps everything but leaves teeth on every edge. So: the repair, with the
    original's own faces it lost given back as they were (see _slabs) and joined in one union. The pick still
    judges the result by what moved and what is lost."""
    t = time.time()
    m, given, slabs, single = _given_back(orig, shared["repairMesh"].copy(), shared["printer"], log)
    if not given:
        raise RuntimeError("the repair lost nothing")
    log(f"  given back {given} faces as {slabs} slabs and {single} single faces, {len(m.faces)} faces now {time.time() - t:.0f}s")
    t = _tick(shared, "union", t)
    m, bridged = _bridge(m, log, shared["printer"])
    _tick(shared, "bridges", t)
    return m, {"piecesBridged": bridged, "facesGivenBack": given}


def _given_back(orig, m, printer: Printer, log: Log = print):
    """`m` with the original's own faces it lost given back as they were (see _lost_faces, _slabs), in one union.
    Returns the mesh, how many faces went back, as how many slabs and how many single faces."""
    bad, patch = _lost_faces(orig, m)
    if not bad.any():
        return m, 0, 0, 0
    solids, slabs, single = _slabs(orig, patch, printer.min_wall_mm, body=m, log=log)
    return _drop_pockets(_union(m, *solids)), int(patch.sum()), slabs, single


# --- measuring and picking -------------------------------------------------------------------------


def _pieces(m) -> int:
    import numpy as np
    import trimesh

    lab = trimesh.graph.connected_component_labels(m.face_adjacency, node_count=len(m.faces))
    return int(len(np.unique(lab)))


def _seen(V, F, pts, normals):
    """Which surface points can be seen from outside: at least one of VIS_RAYS rays over the point's hemisphere
    gets out (embree). The walls of a sealed void, or of a hollow behind a crack, are hidden."""
    return _open_share(V, F, pts, normals) > 0.0


def _open_share(V, F, pts, normals):
    """The share of VIS_RAYS rays over each point's hemisphere that get out (embree): 0 hidden, about 1 on open
    flat ground, a few rays at the back of a sheet seen through a slit. The rays come from the C library's rand,
    so it is reset first: every candidate, and every run, is lit by the same rays."""
    import ctypes
    import ctypes.util
    import numpy as np

    try:
        import igl.embree
    except ImportError:
        return np.ones(len(pts))
    try:
        ctypes.CDLL(ctypes.util.find_library("c") or "ucrtbase").srand(SEED)
    except (OSError, AttributeError):
        pass
    return 1.0 - np.asarray(igl.embree.ambient_occlusion(V, F, pts + normals * 1e-3, normals, VIS_RAYS), np.float64)


def _winding(V, F, Q, closed: bool):
    """Winding numbers of points Q in the mesh V, F, as good as libigl's exact ones wherever they are compared with
    0.5. The exact one builds a tree that costs 15 s on harbor's 3M faces even for one point; the fast one (Barill
    et al.) took 4 s for 600k points and stayed within 0.011 of it, down to 0.01 mm off the surface, so it decides
    alone, and only points it puts within 0.1 of 0.5 are worked out exactly. That was measured on closed meshes: on
    an open one (a losing candidate) it moved a share in the report, so there every point is worked out exactly."""
    import igl
    import numpy as np

    V = np.ascontiguousarray(V, np.float64)
    F = np.ascontiguousarray(F, np.int64)
    Q = np.ascontiguousarray(Q, np.float64)
    if not closed:
        return np.asarray(igl.winding_number(V, F, Q), np.float64)
    w = np.asarray(igl.fast_winding_number(V, F, Q), np.float64)
    unsure = np.abs(w - 0.5) < 0.1
    if unsure.any():
        w[unsure] = igl.winding_number(V, F, Q[unsure])
    return w


def _tree(m):
    """libigl's distance tree of a mesh, built once for every candidate measured against it (2 s at 2M faces)."""
    import igl
    import numpy as np

    t = igl.AABB()
    t.init(np.asarray(m.vertices, np.float64), np.asarray(m.faces, np.int64))
    return t


def _orig_seen(orig, pts, fi):
    """Which of the original's surface points `pts` (on faces `fi`) can be seen from outside, from either side: a
    sheet without thickness has no inside, and its normals may point either way."""
    import numpy as np

    V, F = np.asarray(orig.vertices, np.float64), np.asarray(orig.faces, np.int64)
    n = np.asarray(orig.face_normals, np.float64)[fi]
    return _seen(V, F, pts, n) | _seen(V, F, pts, -n)


def _measure(orig, orig_pts, m, printer: Printer, orig_tree=None, orig_seen=None) -> dict[str, Any]:
    """'changed': how far the result is from the original where they show, both ways, as mesh comparison does it
    (Metro, Netfabb's and Magics' part compare; the F-score of shape reconstruction): the share of the original's
    surface seen from outside (`orig_seen`) that is no longer on the result's surface, lost or buried inside it (a wrap
    that fills between a plant's leaves buries half of them), plus the share of the result's surface seen from outside
    that is off the original and isn't thickness (a hole capped flat, a blob, the wrap's teeth). "Off" is farther than
    a print layer (Printer.print_layer_mm): a change smaller hides in the layer lines. Thickness is result surface
    that wraps the original as an offset of it: the nearest original point is inside the result, or on it, and
    straight in from the result's surface (along its normal) the original is no farther than that nearest point, give
    or take a layer. The back given to a sheet and the wrap's coat are offsets; teeth spanning a crease are not: the
    original is near them sideways, deep straight in (trellis2_bust: wrap 1.3 % changed without that test, 5.8 % with
    it, against the repair's 0.1 %; the teeth were plain to see). Before 2026-11-15 it was measured one way, at a
    fixed 0.3 mm: the backs of potted_plant_02's leaves counted 25 % and the wrap's buried leaves nothing, and two
    rules picked round it (restored over wrap; 10 % more volume wins). Surface moved out of sight (the walls of a
    filled hollow) is counted apart, as 'changedHidden'. 'lost': original surface more than lost_mm from the result
    and outside it. Skin buried inside the new solid was filled on purpose: not lost."""
    import igl
    import igl.embree
    import numpy as np
    import trimesh

    tol = printer.print_layer_mm
    V = np.asarray(m.vertices, np.float64)
    F = np.asarray(m.faces, np.int64)
    pts, fi = trimesh.sample.sample_surface(m, SAMPLES, seed=SEED)
    if orig_tree is None:
        orig_tree = _tree(orig)
    Vo, Fo = np.asarray(orig.vertices, np.float64), np.asarray(orig.faces, np.int64)
    d2, _, near = orig_tree.squared_distance(Vo, Fo, pts)
    d = np.sqrt(d2)
    moved = d > tol
    out = 1.0 if float(m.volume) >= 0 else -1.0  # normals are fixed on the winner only: aim the rays outward here
    normals = out * np.asarray(m.face_normals, np.float64)[fi]
    seen = _seen(V, F, pts, normals)
    watertight = bool(m.is_watertight)
    gone = np.sqrt(igl.point_mesh_squared_distance(orig_pts, V, F)[0])
    far = gone > tol  # nearer than that it is kept, so it doesn't matter which side it is on
    outside = np.ones(len(orig_pts), dtype=bool)
    if far.any():
        outside[far] = _winding(V, F, orig_pts[far], watertight) < 0.5
    lost = gone * outside
    kept_off = gone > tol
    if orig_seen is not None:
        kept_off = kept_off[orig_seen]
    added = moved & seen
    if added.any():
        i = np.flatnonzero(added)
        on = np.sqrt(igl.point_mesh_squared_distance(near[i], V, F)[0]) < tol
        wraps = on | (_winding(V, F, near[i], watertight) >= 0.5)
        # straight in: libigl casts both ways along the line and keeps the nearer hit, as a face's normal may be off
        hit = igl.embree.line_mesh_intersection(np.ascontiguousarray(pts[i]), np.ascontiguousarray(-normals[i]), Vo, Fo)
        depth = np.full(len(i), np.inf)
        h = hit[:, 0] >= 0
        if h.any():
            f, b = hit[h, 0].astype(np.int64), hit[h, 1:]
            at = Vo[Fo[f, 0]] * (1 - b[:, :1] - b[:, 1:2]) + Vo[Fo[f, 1]] * b[:, :1] + Vo[Fo[f, 2]] * b[:, 1:2]
            depth[h] = np.linalg.norm(at - pts[i][h], axis=1)
        added[i] = ~(wraps & (depth - d[i] <= tol))
    wall = _thickness(m)
    parts = _pieces(m)
    volume = float(m.volume)
    _lean(m)  # the candidate is kept until the pick: without its tables
    return {
        "watertight": watertight,
        "parts": parts,
        "volumeCm3": round(volume / 1000, 2) if watertight else None,
        "wallMm": None if wall is None else round(wall, 2),
        "faces": int(len(m.faces)),
        "changedShare": round((float(kept_off.mean()) if len(kept_off) else 0.0) + float(added.mean()), 4),
        "changedHiddenShare": round(float((moved & ~seen).mean()), 4),
        "lostShare": round(float((lost > printer.lost_mm).mean()), 5),
        "lostMaxMm": round(float(lost.max()), 2),
        "_paper": wall is not None and wall < printer.skin_mm,
    }


def _paper(c: dict[str, Any]) -> bool:
    return c["_paper"]


def _good(cands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Closed, kept the surface, and solid rather than paper."""
    return [c for c in cands if c["watertight"] and (c["volumeCm3"] or 0) > 0 and c["lostShare"] <= LOST_MAX_SHARE and not _paper(c)]


def _settled(cands: list[dict[str, Any]]) -> bool:
    """One candidate already can't be beaten: kept everything, one part, solid, and nothing seen changed by a layer.
    The pick takes the first of equals, so what is built after it can't change the pick: skipping it changes
    nothing. Until 2026-11-15 "nearly nothing" (0.1 %) passed too: chess_set and garden_gnome then left out the wrap.
    It lost there anyway (0.19 % against 1.3 %), but that was luck, not proof."""
    return any(c["parts"] == 1 and c["changedShare"] == 0 for c in _good(cands))


def _fills(c: dict[str, Any]) -> bool:
    """It filled the chamber behind the skin: solidify and filled are fused with its block, by construction."""
    return "chamberCm3" in c


def _pick(cands: list[dict[str, Any]], printer: Printer):
    ok, note = _passing(cands, printer)
    if not ok:
        return None, note
    # first of equals: the order they were built in. Until 2026-11-15 a "filled" candidate also replaced solidify or
    # wrap when it changed at most 0.1 % more: the one-way measure counted the wrap's coat as kept. Measured both ways
    # it wins on its own where it should (resin trellis2_bust, trellis2_crown, trellis2_statue), so the rule went.
    return min(ok, key=lambda c: c["changedShare"]), note


def _passing(cands: list[dict[str, Any]], printer: Printer):
    """The candidates the pick chooses from, and a note when none kept the surface (then the ones that lost least)."""
    closed = [c for c in cands if c["watertight"] and (c["volumeCm3"] or 0) > 0]
    if not closed:
        return [], "no candidate came out closed"
    ok = [c for c in closed if c["lostShare"] <= LOST_MAX_SHARE]
    note = None
    if not ok:
        least = min(c["lostShare"] for c in closed)
        ok = [c for c in closed if c["lostShare"] == least]
        note = f"every candidate lost some surface; kept the one that lost least ({least:.2%})"
    if any(not _paper(c) for c in ok):  # a paper skin prints as paper: it loses to any real solid
        ok = [c for c in ok if not _paper(c)]
    # the chamber is known only where a fill was built (paper skins, or when nothing else came out solid); every
    # other candidate follows the skin and leaves it hollow. On resin that holds liquid resin (see Printer):
    # Chandelier_01 wrapped kept its vase hollow behind a 0.5-1 mm slit, filling it changed 3 % more of its look.
    if printer.hollow_traps and any(_fills(c) for c in ok):
        ok = [c for c in ok if _fills(c)]
    return ok, note


def _pick_printed(cands, best, orig, orig_pts, orig_tree, orig_seen, printer: Printer, log: Log, thicken_seen: bool):
    """The pick judged on what is printed: every candidate the pick chooses from is thickened (see thicken) and
    measured again, and the least changed after thickening wins (first of equals: the order they were built in).
    Judged as built, a hollow wrap that looks a little better loses most to the thickening (tripo_blaster: wrap 5.3 %
    as built, 14.0 % thickened, against the restored repair's 8.3 % and 8.6 %). The winner keeps its thickened mesh
    in "_thick", so it isn't thickened twice; the losers' go at once. A candidate the thickening fails on keeps its
    place by the first measure only if nothing could be judged. Nothing to do where the pick had one to choose from,
    or none kept the surface."""
    ok, note = _passing(cands, printer)
    if best is None or note or len(ok) < 2:
        return best
    judged = None
    for c in ok:
        log(f" {c['method']} thickened, to judge what is printed:")
        try:
            out, info = thicken(c["_mesh"].copy(), printer, log, seen_too=thicken_seen)
        except Exception as exc:  # noqa: BLE001 - it can't be judged after
            log(f"  thicken failed: {exc}")
            continue
        a = _measure(orig, orig_pts, out, printer, orig_tree, orig_seen)
        c["changedAfter"], c["lostAfter"] = a["changedShare"], a["lostShare"]
        log(f"  {c['method']} after thickening: changed {a['changedShare']}, lost {a['lostShare']}")
        if judged is None or c["changedAfter"] < judged["changedAfter"]:
            if judged is not None:
                judged.pop("_thick", None)
            c["_thick"], judged = (out, info), c
        del out, info
    return judged or best


def make_solid(mesh, mm_per_unit: float, log: Log = print, full=None, printer: Printer = PRINTERS[DEFAULT_PRINTER],
               thicken_walls: bool = True, thicken_seen: bool = True):
    """One closed solid made from `mesh` (any units; `mm_per_unit` gives the print scale), and the report.
    `full` is the model before its fine detail was merged (tools_ops): when the repair can't close the lighter
    mesh, it is made again from that one before anything else is tried. On hunyuan_operative the self-union left
    one edge with four faces on the lighter mesh, so the 0.5 mm wrap won where the repair used to change nothing.
    Then walls thinner than the printer holds are thickened (see thicken; `thicken_seen` False leaves thin
    details seen from both sides as they are). The thresholds are the printer's (see Printer). Raises when no candidate came out closed, so the caller can fall back."""
    import numpy as np
    import trimesh

    t0 = time.time()
    orig = _weld(trimesh.Trimesh(np.asarray(mesh.vertices, np.float64) * mm_per_unit, np.asarray(mesh.faces), process=False))
    came_closed = bool(orig.is_watertight)
    orig_pts, ofi = trimesh.sample.sample_surface(orig, SAMPLES, seed=SEED)
    orig_seen = _orig_seen(orig, orig_pts, ofi)
    _lean(orig)  # kept to the end for measuring, which needs only its vertices and faces
    orig_tree = _tree(orig)
    shared: dict[str, Any] = {"printer": printer}
    if not came_closed:  # wrap and solidify will want its shell: wrapped beside the repair
        skin = _skin(orig, shared)
        if skin is not orig:
            log(f" wrap and solidify leave out {len(orig.faces) - len(skin.faces)} faces of loose dust")
        try:
            shared["shellJob"] = _WrapLater(skin.vertices, skin.faces, printer.wrap_alpha_mm)
        except Exception as exc:  # noqa: BLE001 - wrapped here when it's needed
            log(f" shell wrap not started beside the repair: {exc}")
        del skin
    stages: dict[str, float] = {"prepare": round(time.time() - t0, 1)}

    t1 = time.time()
    builders: list[tuple[str, Callable]] = []
    # the ways to fill a hollow skin: on its own surface first where the printer allows it (see Printer), then wrapped
    fills: list[tuple[str, Callable]] = ([("filled", _filled)] if printer.fill_own_surface else []) + [("solidify", _solidified)]
    repaired = wall = None
    paper = False
    try:
        repaired = _local_repair(orig.copy(), log)
        wall = _thickness(repaired)
        _lean(repaired)
        log(f" local repair {time.time() - t1:.0f}s, closed {repaired.is_watertight}, wall {wall if wall is None else round(wall, 2)} mm")
        paper = wall is None or wall < printer.skin_mm  # a paper skin, or unknown: the gate judges the result
        builders = fills if paper else [("repair", _repaired)]
    except Exception as exc:
        log(f" local repair failed: {exc}")
    stages["localRepair"] = round(time.time() - t1, 1)
    if not came_closed or not builders:
        builders.append(("wrap", _wrapped))
    cands: list[dict[str, Any]] = []

    def build(name: str, fn: Callable) -> None:
        t1 = time.time()
        log(f" {name}:")
        shared["stages"] = {}
        try:
            m, extra = fn(orig, repaired, shared, log)
        except Exception as exc:
            import traceback

            where = " < ".join(f"{os.path.basename(f.filename)}:{f.lineno} {f.name}" for f in reversed(traceback.extract_tb(exc.__traceback__)[-4:]))
            log(f"  {name} failed: {exc} (at {where})")
            return
        t2 = time.time()
        c = {"method": name, **_measure(orig, orig_pts, m, printer, orig_tree, orig_seen), **extra, "secs": round(time.time() - t1, 1)}
        _tick(shared, "measure", t2)
        c["stages"] = shared.pop("stages")
        log(f"  {name}: {c}")
        c["_mesh"] = m
        cands.append(c)

    from_full = False
    for name, fn in builders:
        if _settled(cands):
            log(f" {name}: skipped, {cands[-1]['method']} can't be beaten")
            continue
        build(name, fn)
        if name == "repair" and full is not None and not any(c["method"] == "repair" and c["watertight"] for c in cands):
            log(" repair didn't close the lighter mesh: again from the full one")
            if "shellJob" in shared:  # the shell of the lighter mesh: wrapped again from the full one when needed
                shared.pop("shellJob").cancel()
            shared.pop("skin", None)
            shared.pop("block", None)
            t1 = time.time()
            orig = _weld(trimesh.Trimesh(np.asarray(full.vertices, np.float64) * mm_per_unit, np.asarray(full.faces), process=False))
            orig_pts, ofi = trimesh.sample.sample_surface(orig, SAMPLES, seed=SEED)
            orig_seen = _orig_seen(orig, orig_pts, ofi)
            _lean(orig)
            orig_tree = _tree(orig)
            cands[:] = [c for c in cands if c["method"] != "repair"]
            try:
                repaired = _local_repair(orig.copy(), log)
                _lean(repaired)
            except Exception as exc:
                log(f" local repair failed: {exc}")
                repaired = None
            stages["fullRepair"] = round(time.time() - t1, 1)
            if repaired is not None:
                build("repair", _repaired)
            from_full, full = True, None
    # On a paper skin the repair stays paper; it is only worth building when nothing else came out solid.
    if paper and repaired is not None and not _good(cands):
        log(" no solid result: trying the repair after all")
        build("repair", _repaired)
    # The wall guessed from the repaired mesh is only a guess: holes capped flat can make a paper skin
    # look solid. What counts is the results, so when none of them came out solid, fill the hollow anyway.
    if not _good(cands) and all(c["method"] != "solidify" for c in cands):
        log(" no solid result: trying solidify after all")
        for name, fn in fills:
            build(name, fn)

    if "shellJob" in shared:  # neither wrap nor solidify was built
        shared.pop("shellJob").cancel()
    best, note = _pick(cands, printer)
    # Whenever the repair lost something, it is given back (see _restored), whoever wins so far: give-back is there
    # for what the repair lost (tripo_spellbook: the repair won and had lost the top of its page block, 1.07 mm).
    # Until 2026-11-19 only where the wrap was winning. _restored raises when the repair lost nothing.
    if best is not None and not paper and not _settled(cands):
        got = next((c for c in cands if c["method"] == "repair"), None)
        if got is not None:
            shared["repairMesh"] = got["_mesh"]
            build("restored", _restored)
            best, note = _pick(cands, printer)
    if thicken_walls:
        t1 = time.time()
        best = _pick_printed(cands, best, orig, orig_pts, orig_tree, orig_seen, printer, log, thicken_seen)
        stages["pickPrinted"] = round(time.time() - t1, 1)
    if best is None:
        raise RuntimeError(note)
    out = best["_mesh"]
    thickened = None
    if thicken_walls:
        # the hungriest step: what lost the pick goes first
        for c in cands:
            c.pop("_mesh", None)
        shared.clear()
        repaired = None
        gc.collect()
        t1 = time.time()
        try:
            out, thickened = best.pop("_thick") if "_thick" in best else thicken(out, printer, log, seen_too=thicken_seen)
        except Exception as exc:  # the model stays as picked; its thin spots are still reported
            log(f" thicken failed: {exc}")
        if thickened:  # measured against the original like the candidates, so the report says what it cost
            thickened.update({k: v for k, v in _measure(orig, orig_pts, out, printer, orig_tree, orig_seen).items() if not k.startswith("_")})
            log(f" thickened: {thickened}")
        stages["thicken"] = round(time.time() - t1, 1)
    out.apply_scale(1.0 / mm_per_unit)
    trimesh.repair.fix_normals(out)
    info: dict[str, Any] = {
        "method": best["method"],
        "printer": printer.name,
        "cameClosed": came_closed,
        "wallMm": None if wall is None else round(wall, 2),
        "resultWallMm": best["wallMm"],
        "thinWalls": _paper(best),  # every result was paper: say so instead of "ready"
        "candidates": [{k: v for k, v in c.items() if not k.startswith("_")} for c in cands],
        "stages": stages,
        "secs": round(time.time() - t0, 1),
    }
    if from_full:
        info["repairedFromFull"] = True
    if thickened:
        info["thickened"] = thickened
    if note:
        info["note"] = note
    return out, info


# --- wall thickness --------------------------------------------------------------------------------

def wall_thickness(m, seed: int = SEED):
    """Wall thickness at surface points: from each point, seven rays into the solid (the inward normal and six
    at 20° round it, always the same six), and the median distance to the wall opposite, the slanted ones
    taken along the normal. A thin plate measures its thickness, a strand its diameter, while a sharp corner
    of a thick block stays thick: the ray goes straight across. `m` is closed, in mm.
    Returns (points, thickness mm); inf where no ray found the other side."""
    import numpy as np
    import trimesh

    pts, fi = trimesh.sample.sample_surface(m, THICKNESS_SAMPLES, seed=seed)
    inward = -np.asarray(m.face_normals, np.float64)[fi] * (1.0 if float(m.volume) >= 0 else -1.0)
    return pts, _ray_thickness(m, pts, inward)


def _ray_thickness(m, pts, inward):
    """Thickness at `pts` going along unit `inward` (see wall_thickness)."""
    import igl.embree
    import numpy as np

    helper = np.where(np.abs(inward[:, :1]) < 0.9, [[1.0, 0, 0]], [[0, 1.0, 0]])
    u = np.cross(inward, helper)
    u /= np.linalg.norm(u, axis=1, keepdims=True)
    w = np.cross(inward, u)
    a = np.radians(THICKNESS_CONE_DEG)
    dirs = [inward] + [np.cos(a) * inward + np.sin(a) * (np.cos(k * np.pi / 3) * u + np.sin(k * np.pi / 3) * w) for k in range(6)]
    along = [1.0] + [float(np.cos(a))] * 6
    ei = igl.embree.EmbreeIntersector()
    ei.init(np.asfortranarray(m.vertices, np.float32), np.asfortranarray(m.faces, np.int32), True)
    start = (pts + inward * 1e-3).astype(np.float32)  # just inside, so the ray doesn't hit its own face
    dist = np.full((len(pts), len(dirs)), np.inf)
    for j, (d, cos) in enumerate(zip(dirs, along)):
        d32 = d.astype(np.float32)
        for i in range(len(pts)):
            f, t, _, _ = ei.intersectRay_first(start[i], d32[i])
            if f >= 0:
                dist[i, j] = (t + 1e-3) * cos
    return np.median(dist, axis=1)


def thin_spots(m, printer: Printer) -> dict[str, Any]:
    """Where the walls are thinner than the printer holds (Printer.min_wall_mm, "fragile") or prints at all
    (min_print_mm, "won't print"): the shares of the surface, and the spots (thin points within 2 mm of each
    other, from 1 mm² up), biggest first, each with where it is, its size, its area and its thinnest wall.
    The mean wall (2·V/A) can't see these: a solid knight with 0.3 mm fingers has a mean wall of 3 mm, and on
    trellis2_chest a 0.22 mm skin hangs 0.9 mm off the filled core. `m` is closed, in mm; positions in its frame."""
    import numpy as np
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    pts, thick = wall_thickness(m)
    thin = thick < printer.min_wall_mm
    out: dict[str, Any] = {"minWallMm": printer.min_wall_mm, "minPrintMm": printer.min_print_mm,
                           "share": round(float(thin.mean()), 4), "unprintableShare": round(float((thick < printer.min_print_mm).mean()), 4),
                           "spots": []}
    if not thin.any():
        return out
    p, t = pts[thin], thick[thin]
    cell = np.floor(p / THIN_SPOT_CELL_MM).astype(np.int64)
    keys, of = np.unique(cell, axis=0, return_inverse=True)
    of = of.ravel()
    code = lambda c: (c[:, 0] * 1_000_003 + c[:, 1]) * 1_000_033 + c[:, 2]  # noqa: E731
    order = np.argsort(code(keys))
    sorted_codes = code(keys)[order]
    rows, cols = [], []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                nb = code(keys + [dx, dy, dz])
                at = np.searchsorted(sorted_codes, nb)
                ok = (at < len(keys)) & (sorted_codes[np.minimum(at, len(keys) - 1)] == nb)
                rows.append(np.nonzero(ok)[0])
                cols.append(order[at[ok]])
    r, c = np.concatenate(rows), np.concatenate(cols)
    _, lab = connected_components(coo_matrix((np.ones(len(r)), (r, c)), shape=(len(keys),) * 2), directed=False)
    spot = lab[of]
    per_point = float(m.area) / len(pts)
    sizes = np.bincount(spot)
    for k in np.argsort(-sizes, kind="stable")[:5]:
        if sizes[k] * per_point < THIN_SPOT_MIN_MM2:
            break
        q = p[spot == k]
        lo, hi = q.min(0), q.max(0)
        out["spots"].append({
            "areaMm2": round(float(len(q) * per_point), 1),
            "centerMm": [round(float(v), 1) for v in (lo + hi) / 2],
            "sizeMm": [round(float(v), 1) for v in hi - lo],
            "thinnestMm": round(float(np.percentile(t[spot == k], 5)), 2),
        })
    return out


# --- thickening ------------------------------------------------------------------------------------

def _on_table(V, F):
    """The mesh with the table under it, for rays: what shows only from below is not seen. hunyuan_lighthouse's rocks
    are a skin open at the bottom: rays from inside got out there, so 505825 of 580204 points counted as seen from both
    sides and grew over the seen faces; on the table, 843."""
    import numpy as np

    lo, hi = V.min(0), V.max(0)
    pad = 3 * float((hi - lo).max())
    y = lo[1] - 0.01
    table = np.array([[lo[0] - pad, y, lo[2] - pad], [hi[0] + pad, y, lo[2] - pad], [hi[0] + pad, y, hi[2] + pad], [lo[0] - pad, y, hi[2] + pad]])
    return np.vstack([V, table]), np.vstack([F, np.array([[0, 2, 1], [0, 3, 2]]) + len(V)])


def _halve_edges(V, F, tags, edge_mm):
    """Edges of the faces tagged 2 (of bits: 1 near a thin wall, 2 cut here) longer than `edge_mm` halved, over and over,
    the faces round them with them, so the mesh stays closed and flat stays flat. Returns (V, F, tags)."""
    import numpy as np

    for _ in range(12):
        E = np.sort(F[:, [[0, 1], [1, 2], [2, 0]]], axis=2).reshape(-1, 2)
        key, inv = np.unique(E[:, 0] * len(V) + E[:, 1], return_inverse=True)
        uniq = np.c_[key // len(V), key % len(V)]
        inv = inv.reshape(-1, 3)
        mark = np.zeros(len(uniq), bool)
        mark[inv[(tags & 2) > 0].ravel()] = True
        mark &= np.linalg.norm(V[uniq[:, 0]] - V[uniq[:, 1]], axis=1) > edge_mm
        if not mark.any():
            break
        mid = np.full(len(uniq), -1, np.int64)
        mid[mark] = len(V) + np.arange(mark.sum())
        V = np.vstack([V, V[uniq[mark]].mean(1)])
        M = mid[inv]  # per face: the new vertex on each of its three edges, or -1
        cuts = (M >= 0).sum(1)
        out, kid = [F[cuts == 0]], [tags[cuts == 0]]
        one = np.nonzero(cuts == 1)[0]
        if len(one):  # start the face at the cut edge
            k = np.argmax(M[one] >= 0, axis=1)
            a, b, c = F[one, k], F[one, (k + 1) % 3], F[one, (k + 2) % 3]
            m = M[one, k]
            out += [np.c_[a, m, c], np.c_[m, b, c]]
            kid += [tags[one]] * 2
        two = np.nonzero(cuts == 2)[0]
        if len(two):  # start it just after the edge left whole
            k = (np.argmax(M[two] < 0, axis=1) + 1) % 3
            a, b, c = F[two, k], F[two, (k + 1) % 3], F[two, (k + 2) % 3]
            m1, m2 = M[two, k], M[two, (k + 1) % 3]
            out += [np.c_[m1, b, m2], np.c_[a, m1, m2], np.c_[a, m2, c]]
            kid += [tags[two]] * 3
        three = np.nonzero(cuts == 3)[0]
        if len(three):
            a, b, c = F[three].T
            ab, bc, ca = M[three].T
            out += [np.c_[a, ab, ca], np.c_[ab, b, bc], np.c_[ca, bc, c], np.c_[ab, bc, ca]]
            kid += [tags[three]] * 4
        F, tags = np.vstack(out), np.concatenate(kid)
    return V, F, tags


def _fixed_order(m):
    """The exact union works in several threads and hands the same faces back in a varying order: one fixed order, so
    the same model gives the same bytes."""
    import numpy as np
    import trimesh

    V, F = np.asarray(m.vertices, np.float64), np.asarray(m.faces, np.int64)
    o = np.lexsort((V[:, 2], V[:, 1], V[:, 0]))
    rank = np.empty(len(o), np.int64)
    rank[o] = np.arange(len(o))
    F = rank[F]
    k = np.argmin(F, axis=1)
    i = np.arange(len(F))
    F = np.c_[F[i, k], F[i, (k + 1) % 3], F[i, (k + 2) % 3]]
    return trimesh.Trimesh(V[o], F[np.lexsort((F[:, 2], F[:, 1], F[:, 0]))], process=False)


def _part_touching(m):
    """After an exact union two solids may touch along an edge: four faces on it, and the mesh no longer counts as
    closed. Nothing is cut: round each such edge the faces are paired, each with its neighbour across the solid, and each
    pair gets its own new vertex in the middle of the edge. Every edge then has two faces. Same shape, closed again.
    A face is split once a round, so one with two such edges takes two rounds."""
    import numpy as np
    import trimesh

    V, F = np.asarray(m.vertices, np.float64), np.asarray(m.faces, np.int64)
    for _ in range(8):
        a = F.ravel()
        b = F[:, [1, 2, 0]].ravel()
        lo, hi = np.minimum(a, b), np.maximum(a, b)
        o = np.lexsort((np.repeat(np.arange(len(F)), 3), hi, lo))
        lo, hi, face = lo[o], hi[o], np.repeat(np.arange(len(F)), 3)[o]
        start = np.r_[0, np.nonzero((lo[1:] != lo[:-1]) | (hi[1:] != hi[:-1]))[0] + 1]
        count = np.diff(np.r_[start, len(lo)])
        if not (count > 2).any():
            break
        fn = trimesh.Trimesh(V, F, process=False).face_normals
        split = np.zeros(len(F), bool)
        new_v, new_f = [], []
        F = F.copy()
        for s0, c in zip(start[count > 2], count[count > 2]):
            p, q = int(lo[s0]), int(hi[s0])
            fs = face[s0:s0 + c]
            if split[fs].any():
                continue
            axis = V[q] - V[p]
            axis /= np.linalg.norm(axis)
            other = F[fs][~np.isin(F[fs], [p, q])]
            away = V[other] - V[p]
            away -= axis[None] * (away @ axis)[:, None]
            away /= np.maximum(np.linalg.norm(away, axis=1, keepdims=True), 1e-12)
            e2 = np.cross(axis, away[0])
            fs = fs[np.argsort(np.arctan2(away @ e2, away @ away[0]), kind="stable")]
            away = away[np.argsort(np.arctan2(away @ e2, away @ away[0]), kind="stable")]
            solid_ahead = (-fn[fs] * np.cross(axis, away)).sum(1) > 0
            taken = np.zeros(c, bool)
            for i in range(c):
                j = (i + 1) % c if solid_ahead[i] else (i - 1) % c
                if taken[i] or taken[j] or i == j:
                    continue
                taken[i] = taken[j] = True
                mid = len(V) + len(new_v)
                new_v.append((V[p] + V[q]) / 2)
                for f in (fs[i], fs[j]):
                    t = F[f]
                    k = next(k for k in range(3) if {int(t[k]), int(t[(k + 1) % 3])} == {p, q})
                    x, y, z = t[k], t[(k + 1) % 3], t[(k + 2) % 3]
                    F[f] = (x, mid, z)
                    new_f.append((mid, y, z))
                    split[f] = True
        V = np.vstack([V, np.array(new_v)])
        F = np.vstack([F, np.array(new_f, np.int64)])
    return trimesh.Trimesh(V, F, process=False)


def _spread(W, deg, values):
    """Each column averaged over a short reach on the graph W: (I + reach L) x = values. CG to a fixed tolerance: the
    same input gives the same answer."""
    import numpy as np
    import scipy.sparse as sp
    import scipy.sparse.linalg as spl

    diag = 1.0 + THICKEN_REACH * deg
    M = (sp.diags(diag) - THICKEN_REACH * W).tocsr()
    pre = sp.diags(1.0 / diag)
    return np.column_stack([spl.cg(M, values[:, c], M=pre, rtol=1e-6, atol=0, maxiter=400)[0] for c in range(values.shape[1])])


def _wall_moves(V, F, near, target, lo, seen_too, draft=False, meet=0.0, leaf_to=0.0):
    """Steps 2-4 of thicken on a mesh already cut: how far each vertex moves. Returns {x, info, tf, t1, cancel}, cancel
    being the thin faces at vertices where the two sides cancelled; None when nothing is to move. A `draft` only finds
    those faces, on what it costs little to know: the wall straight across, shared half and half."""
    import igl.embree
    import numpy as np
    import scipy.sparse as sp
    import scipy.sparse.linalg as spl
    import trimesh

    s = trimesh.Trimesh(V, F, process=False)
    fn = np.asarray(s.face_normals, np.float64)
    nf = np.nonzero(near)[0]
    centre, inward = np.asarray(s.triangles_center, np.float64)[nf], -fn[nf]
    ei = igl.embree.EmbreeIntersector()
    ei.init(np.asfortranarray(V, np.float32), np.asfortranarray(F, np.int32), True)
    start, d32 = (centre + inward * 1e-3).astype(np.float32), inward.astype(np.float32)
    hit, across = np.full(len(nf), -1), np.full(len(nf), np.inf)
    for i in range(len(nf)):  # straight across first: only the near-thin faces get the full seven rays
        f, t, _, _ = ei.intersectRay_first(start[i], d32[i])
        if f >= 0:
            hit[i], across[i] = f, t + 1e-3
    del start, d32
    th = across.copy()
    if not draft:
        maybe = across < 1.5 * lo
        th[maybe] = _ray_thickness(s, centre[maybe], inward[maybe])
    thin = (th < lo) & (hit >= 0)
    if draft:
        open_p = open_q = np.ones(int(thin.sum()))
        seen_both = np.zeros(int(thin.sum()), bool)
        w = np.full(int(thin.sum()), 0.5)
    else:
        TV, TF = _on_table(V, F)
        open_p = _open_share(TV, TF, centre[thin], -inward[thin])
        open_q = _open_share(TV, TF, centre[thin] + inward[thin] * across[thin][:, None], fn[hit[thin]])
        seen_both = (open_p > 0) & (open_q > 0)
        shared = open_p + open_q
        w = np.where(shared > 0, open_q / np.where(shared > 0, shared, 1.0), 0.5)  # this side's part of the shortfall
    info: dict[str, Any] = {"toMm": round(target, 2), "behindSeen": int(((open_p > 0) & (open_q <= 0)).sum()),
                            "bothSeen": int(seen_both.sum()) if seen_too else 0,
                            "notThickened": 0 if seen_too else int(seen_both.sum())}
    d = (target - th[thin]) * w
    which = np.nonzero(thin)[0]
    keep = np.ones(len(which), bool) if seen_too else ~seen_both
    if not draft:
        edge, stub, leaf = _tapered(s, nf[which], th[which], meet, stub=lo)
        info["taperedEdge"] = int(edge.sum())
        info["shortStub"] = int(stub.sum())
        keep &= ~edge & ~stub
        if leaf_to > 0:  # a short leaf grows only to what prints (`leaf_to`), a face already that thick stays
            d = np.where(leaf, (leaf_to - th[thin]) * w, d)
            keep &= ~leaf | (d > 0)
            info["shortLeaf"] = int(leaf.sum())
    which, d = which[keep], d[keep]
    if not len(which):
        return None
    tf = nf[which]
    area = np.asarray(s.area_faces, np.float64)[tf]
    t1 = time.time()
    # the average, face to face, among faces that look about the same way
    pos = np.full(len(F), -1, np.int64)
    pos[nf] = np.arange(len(nf))
    fa = s.face_adjacency
    pa, pb = pos[fa[:, 0]], pos[fa[:, 1]]
    both = (pa >= 0) & (pb >= 0)
    pa, pb = pa[both], pb[both]
    agree = ((1 + np.einsum("ij,ij->i", fn[fa[both, 0]], fn[fa[both, 1]])) / 2) ** 2
    Wf = sp.csr_matrix((np.r_[agree, agree], (np.r_[pa, pb], np.r_[pb, pa])), shape=(len(nf), len(nf)))
    degf = np.asarray(Wf.sum(1)).ravel()
    del pos, fa, pa, pb, agree
    weight = np.zeros(len(nf))
    weight[which] = area / float(area.mean())
    wish = np.zeros((len(nf), 4))
    wish[which] = np.c_[fn[tf] * d[:, None], d] * weight[which][:, None]
    top = _spread(Wf, degf, wish)[which]
    bottom = np.maximum(_spread(Wf, degf, weight[:, None])[which, 0], 1e-9)
    # a vertex: the mean of its thin faces
    n = len(V)
    a, sum_x, sum_m = np.zeros(n), np.zeros((n, 3)), np.zeros(n)
    for c in range(3):
        v = F[tf, c]
        np.add.at(a, v, area)
        np.add.at(sum_x, v, top[:, :3] / bottom[:, None] * area[:, None])
        np.add.at(sum_m, v, top[:, 3] / bottom * area)
    x = np.zeros((n, 3))
    ok = a > 0
    x[ok] = sum_x[ok] / a[ok][:, None]
    # a staircase's averaged normal is shorter than one: made up for. A sharp edge's, near nothing, hits the cap and stays small
    ratio = (sum_m[ok] / a[ok]) / np.maximum(np.linalg.norm(x[ok], axis=1), 1e-9)
    x[ok] *= np.minimum(THICKEN_STAIR_LOSS, ratio)[:, None]
    cancelled = np.zeros(n, bool)
    cancelled[np.nonzero(ok)[0][ratio > THICKEN_STAIR_LOSS]] = True
    cancel = np.zeros(len(F), bool)
    cancel[tf[cancelled[F[tf]].any(1)]] = True
    if draft:
        return {"cancel": cancel}
    # what is not thin follows, between the moved rows and the still surface
    still = np.ones(n, bool)
    still[F[nf].ravel()] = False
    still[F[~near].ravel()] = True
    still[ok] = False
    free = np.nonzero(~(still | ok))[0]
    if len(free):
        E = np.sort(F[:, [[0, 1], [1, 2], [2, 0]]].reshape(-1, 2), axis=1)
        key = np.unique(E[:, 0] * n + E[:, 1])
        E = np.c_[key // n, key % n]
        W = sp.csr_matrix((np.ones(len(E) * 2), (np.r_[E[:, 0], E[:, 1]], np.r_[E[:, 1], E[:, 0]])), shape=(n, n))
        deg = np.asarray(W.sum(1)).ravel()
        L = sp.diags(deg) - W
        Lff = L[free][:, free].tocsr()
        rhs = -L[free][:, np.nonzero(ok)[0]] @ x[ok]
        pre = sp.diags(1.0 / deg[free])
        for c in range(3):
            x[free, c] = spl.cg(Lff, rhs[:, c], M=pre, rtol=1e-5, atol=0, maxiter=1500)[0]
    x[still] = 0
    return {"x": x, "info": info, "tf": tf, "t1": t1, "cancel": cancel}


def _tapered(s, faces, th, meet, stub=0.0):
    """Which of the thin `faces` (thickness `th`) of mesh `s` are a tapered edge, as a blade's: thin only because
    it narrows to a rim, thicker the farther in. Thickening can't help there (the two sides meet at the rim and
    cancel, see thicken), and its partial moves left tripo_sword's edge lumpy and still 0.01 mm at the rim, while
    PrusaSlicer prints the taper as it is, down to what its nozzle can, in clean steps. A thin sheet or strap is
    thin all over: without thickening it would go whole. Per connected patch of thin faces: the distance of each
    from the nearest face that is not thin, along the surface, against its thickness; a tapered edge has the one
    fall as the other grows (rank correlation at most TAPER_CORR: the sword's blade edges -0.80 to -0.84, its grip
    panels -0.33 and -0.45, small bits about 0).
    Falling is not enough. Its two sides must meet at the rim, thinner there than `meet` (what PrusaSlicer drops
    anyway): hi3dgen_space_bust's helmet thins to 0.36 mm and the dog's patches to 0.42-0.7, walls that print and
    only want thickening. And it must run along the rim, not away from it: area / reach² at least TAPER_LONG, reach
    the farthest it goes from wall that is not thin (a strip L long and R deep, both sides: 2 L / R). A spike or
    a rod tapers along its length and would go unprinted to where it reaches a nozzle line: hunyuan31_scorpion's
    rod 0.07-0.1, rodin_knight's tentacle tips 0.16-0.58, hunyuan_necromutant's claws 0.5-1.5; the sword's blade
    edges 2.3-8.3.
    Also returns the short stubs: patches no farther than `stub` (the printer's minimum wall) from wall that is not
    thin, all along. A bump that low on a thick body can't break off; it measures thin only because the ray inward
    crosses the bump, and thickened it swelled: hunyuan31_watch's dial dots grew into beads (close-up judge 49 noticed
    spots -> 1), hunyuan31_mech's vent slats closed (71 -> 12), meshy_pistol 151 -> 76; 6532 -> 5857 on the 42 models,
    none clearly worse. More surface counts as thin (rover 2.4 -> 4.2 %), but PrusaSlicer (MK4, 0.4 mm) still lays
    lines over the stubs: the watch's print keeps 99.6 % of the original's surface (99.1 % before), with a quarter of
    the swelling; crown, snowman and statue the same within slicing noise.
    And the short leaves: patches no farther than LEAF_REACH_MM from wall that is not thin, all along, and joined
    along at least as far as they reach out (area / reach² at least LEAF_WIDE, so not a spike). hunyuan_crystals has
    ~800 flakes 0.27-0.67 mm thick standing 1.5-3 mm off the rock; thickened to the full wall they doubled into
    pebbles (judge 250 spots), left as they are PrusaSlicer dropped their thinnest tips (286 mm2 of the original's
    surface). Grown only to a nozzle line (_wall_moves `leaf_to`): 42 spots, 28 mm2 lost; on the 42 models judge spots
    5857 -> 5178 (rover 128 -> 67, space_bust 82 -> 29, pack 126 -> 78), none clearly worse, slicer within 0.25 %
    of the original's surface. The cost: a thin strap hung between two thick parts within that reach (tripo_pack's,
    bag to buckle) counts as a leaf too and stays at a nozzle line; telling them apart by how the patch is held
    (one piece of thick wall round it, or pieces within a wall apart) lost the crystals' flakes as well.
    Returns (tapered, stub, leaf), one flag per face of `faces`."""
    import numpy as np
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components, dijkstra
    from scipy.stats import rankdata

    nF = len(s.faces)
    thin = np.zeros(nF, bool)
    thin[faces] = True
    fa = np.asarray(s.face_adjacency, np.int64)
    c = np.asarray(s.triangles_center, np.float64)
    # the thin faces and the faces round them; one source joined to every one that is not thin
    rim = fa[thin[fa[:, 0]] != thin[fa[:, 1]]].ravel()
    sub = np.unique(np.r_[faces, rim])
    at = np.full(nF, -1, np.int64)
    at[sub] = np.arange(len(sub))
    inner = (at[fa[:, 0]] >= 0) & (at[fa[:, 1]] >= 0)
    a, b = at[fa[inner, 0]], at[fa[inner, 1]]
    w = np.linalg.norm(c[fa[inner, 0]] - c[fa[inner, 1]], axis=1)
    n = len(sub)
    src = np.nonzero(~thin[sub])[0]
    G = sp.csr_matrix((np.r_[w, w, np.full(len(src), 1e-9)], (np.r_[a, b, np.full(len(src), n)], np.r_[b, a, src])), shape=(n + 1, n + 1))
    far = dijkstra(G, directed=True, indices=n)[:n][at[faces]]
    area = np.asarray(s.area_faces, np.float64)[faces]
    both = thin[fa[:, 0]] & thin[fa[:, 1]]
    k, label = connected_components(sp.csr_matrix((np.ones(int(both.sum())), (fa[both, 0], fa[both, 1])), shape=(nF, nF)), directed=False)
    label = label[faces]
    out = np.zeros(len(faces), bool)
    short = np.zeros(len(faces), bool)
    leaf = np.zeros(len(faces), bool)
    order = np.argsort(label, kind="stable")
    cuts = np.flatnonzero(np.diff(label[order])) + 1
    for group in np.split(order, cuts):
        ok = np.isfinite(far[group])
        if ok.all() and float(far[group].max()) <= stub:  # a short stub on the body: left as it is
            short[group] = True
            continue
        reach = float(far[group][ok].max()) if ok.any() else np.inf
        if ok.sum() >= 6 and th[group].min() < meet and area[group].sum() >= TAPER_LONG * reach * reach:
            x, y = rankdata(far[group][ok]), rankdata(th[group][ok])
            sx, sy = x.std(), y.std()
            if sx > 0 and sy > 0 and float(((x - x.mean()) * (y - y.mean())).mean() / (sx * sy)) <= TAPER_CORR:
                out[group] = True
                continue
        if ok.all() and reach <= LEAF_REACH_MM and area[group].sum() >= LEAF_WIDE * reach * reach:  # a short leaf
            leaf[group] = True
    return out, short, leaf


def thicken(m, printer: Printer, log: Log, seen_too: bool = True):
    """Walls thinner than the printer holds made thick enough by moving their two sides apart, keeping their shape.

    The surface round a thin wall is often a staircase (near thin walls on tripo_sword and tripo_pack, 26-29 % of the
    edges bend over 30 degrees), so a face's own normal is noise: moved along it, every step grows. So a patch of wall
    moves as one piece:
    1. Edges near thin walls are cut down to 0.6 mm, so the surface can bend there. Where the two sides of a wall then
       cancel (step 4), down to 0.3 mm and over again: a strap under 0.6 mm wide has no vertex in the middle of its
       sides otherwise, and nothing there can move. Cutting everything that fine took 19 GB on tripo_blaster.
    2. Each face there measures its wall as in wall_thickness, and how open its two sides are to the outside
       (_open_share, the table counting as there). The shortfall is shared by that: the side you see better moves less,
       a side seen where the other is hidden stays, seen alike or not at all: half each.
    3. Those wishes (distance times normal) are averaged from face to face over a short reach by one linear solve, and
       only between faces that look about the same way: a staircase's tread and riser mix, the two sides of a ribbon
       do not. The steps then ride along unchanged.
    4. A vertex takes the mean of its thin faces, so at a sharp edge the two sides cancel and the edge stays where it
       is. What is not thin follows by a second solve, the far surface holding still: a strap's narrow side gets taller,
       so the strap keeps its width. Nothing goes through the table.
    5. The moved mesh is simplified within 0.02 mm, far under a 0.2 mm layer, as flat parts need none of the new
       vertices, and one exact union resolves whatever now crosses.
    A sharp edge's last fraction of a millimetre stays thin by what it is, and a tapered edge (a blade's) is left as it
    is (_tapered): the slicer prints it as far as its nozzle can. `seen_too` False leaves walls seen on both
    sides as they are. `m` is closed, in mm. Returns (mesh, info), info None when nothing was thin."""
    import manifold3d as mf
    import numpy as np
    import trimesh
    from scipy.spatial import cKDTree

    t0 = time.time()
    lo = printer.min_wall_mm
    target = lo + 2 * THICKEN_MARGIN_MM
    pts, thick = wall_thickness(m)
    if not (thick < lo).any():
        return m, None
    if float(m.volume) < 0:
        m = m.copy()
        m.invert()
    near = cKDTree(pts[thick < lo]).query(m.triangles_center, distance_upper_bound=THICKEN_NEAR_MM)[0] < np.inf
    V, F, tags = _halve_edges(np.asarray(m.vertices, np.float64), np.asarray(m.faces, np.int64), near.astype(np.int8) * 3, THICKEN_EDGE_MM)
    got = _wall_moves(V, F, (tags & 1) > 0, target, lo, seen_too, draft=True)
    if got is None:
        return m, None
    if got["cancel"].any():
        V, F, tags = _halve_edges(V, F, (tags & 1) + got["cancel"].astype(np.int8) * 2, THICKEN_NARROW_EDGE_MM)
    got = _wall_moves(V, F, (tags & 1) > 0, target, lo, seen_too, meet=printer.min_print_mm * TAPER_MEET,
                      leaf_to=printer.min_print_mm + 2 * THICKEN_MARGIN_MM)
    if got is None:
        return m, None
    x, info, tf = got["x"], got["info"], got["tf"]
    t1 = got["t1"]
    # no growing through the table: on trellis2_chest walls under the flat bottom lifted it, 702 -> 295 mm2 on the bed
    moved = V + x
    moved[:, 1] = np.maximum(moved[:, 1], V[:, 1].min())
    t2 = time.time()
    moved = trimesh.Trimesh(moved, F, process=False)
    split_faces = len(F)
    del got, x, V, F, tags
    gc.collect()
    # the flat parts need none of the new vertices, and the union pays for every face. Manifold takes a mesh that
    # crosses itself as long as it is closed, and keeps it within the tolerance
    q = mf.Manifold(mf.Mesh64(vert_properties=np.ascontiguousarray(moved.vertices, np.float64), tri_verts=np.ascontiguousarray(moved.faces, np.uint64)))
    grown = len(moved.faces)
    if q.status() == mf.Error.NoError:
        g = q.simplify(THICKEN_TOLERANCE_MM).to_mesh64()
        moved = trimesh.Trimesh(np.array(g.vert_properties[:, :3], np.float64), np.array(g.tri_verts, np.int64), process=False)
    del q
    out = _fixed_order(_union(moved))
    t3 = time.time()
    if not out.is_watertight:
        out = _part_touching(out)
    out = _drop_pockets(out)  # gaps between a skin and its core that the new walls closed, and dust: gone
    if not out.is_watertight:
        raise RuntimeError("the moved walls did not close")
    log(f"  thicken: {len(tf)} thin faces of {split_faces}, moves {t2 - t1:.0f}s, union {t3 - t2:.0f}s, {grown} -> {len(out.faces)} faces")
    info["addedCm3"] = round((float(out.volume) - float(m.volume)) / 1000, 2)
    info["secs"] = round(time.time() - t0, 1)
    return out, info


# --- standing ------------------------------------------------------------------------------------

def _zup(V):
    """Y up -> Z up (a quarter turn about X), the axis Manifold slices along."""
    import numpy as np

    V = np.asarray(V, np.float64)
    return np.c_[V[:, 0], -V[:, 2], V[:, 1]]


def _yup(V):
    import numpy as np

    V = np.asarray(V, np.float64)
    return np.c_[V[:, 0], V[:, 2], -V[:, 1]]


def _tip_deg(pts2, c2, height) -> float:
    """How far a model tips before it falls, standing on the convex hull of pts2 (2D) with its centre of mass
    `height` above them at c2: atan(distance from c2 in to the hull's edge / height). Negative: it falls."""
    import numpy as np
    from scipy.spatial import ConvexHull, QhullError

    if len(pts2) < 3 or height <= 0:
        return -90.0
    try:
        h = ConvexHull(pts2)
    except (QhullError, ValueError):  # all on one line: it rolls
        return -90.0
    margin = float(-(h.equations[:, :2] @ c2 + h.equations[:, 2]).max())
    return float(np.degrees(np.arctan2(margin, height)))


def _best_cut(man, com, printer: Printer, cut_max: float, hold: bool = True):
    """Standing as it is (Z up, bottom at 0): the flat cut d (0 = none) that makes it steadiest, and its tip
    angle and plate contact. The plate holds what lies within the first layer, so d = 0 is judged on the
    cross-section half a layer up; a cut d is judged on the section at d, which becomes its flat bottom.
    The smallest cut that stands steady wins, and with `hold` one whose contact also holds on the plate
    (HOLD_MM2) before one that doesn't: trellis2_crown stood steady on 1.8 mm² of rim points, 51 mm² at 0.3 mm.
    Failing steady, the smallest within half a degree of the best. A cut that would split the model in two (a
    strand joined to it only below the cut) is never taken.
    A cut can also shave a ledge on the bottom thinner than a wall should be (Printer.min_wall_mm):
    tripo_spellbook's cover lip went from 1.5 to 0.4 mm at a 1.1 mm cut (61 mm² of it). One that shaves more
    than LIP_MM2 gives way to the first that doesn't, if that stands about as well (steady, or within half a
    degree); else it is kept and flagged. Returns (d, tip, contact, shaves, clean, footing): clean the row of the
    first cut that doesn't shave, for a base to take the ledge instead; footing the row of the smallest whole cut
    that shaves nothing and touches with at least HOLD_MM2 (None if none does): what a base would hold it by."""
    import numpy as np

    lip = _ledges(man, cut_max + printer.min_wall_mm)
    rows = []
    for d in [0.0] + [round(CUT_STEP_MM * k, 3) for k in range(1, int(cut_max / CUT_STEP_MM + 1e-9) + 1)]:
        cs = man.slice(max(d, printer.layer_mm / 2))
        polys = [np.asarray(q) for q in cs.to_polygons()]
        pts = np.vstack(polys) if polys else np.zeros((0, 2))
        rows.append((d, _tip_deg(pts, com[:2], com[2] - d), float(cs.area())))
    steady = [r for r in rows if r[1] >= STEADY_TIP_DEG]
    best = max(r[1] for r in rows)
    order = ([r for r in steady if r[2] >= HOLD_MM2] if hold else []) + steady
    order += [r for r in rows if r[1] >= best - 0.5] + sorted(rows, key=lambda r: -r[1])
    h, below, area = lip
    w = printer.min_wall_mm
    shaved = lambda d: float(area[(h - below < d) & (d < h) & (h < d + w)].sum()) if d > 0 else 0.0  # noqa: E731  no cut, nothing shaved
    parts = len(man.decompose())
    whole = lambda r: r[0] == 0 or len(man.trim_by_plane((0.0, 0.0, 1.0), r[0]).decompose()) <= parts  # noqa: E731
    pick = next((r for r in order if whole(r)), rows[0])
    footing = next((r for r in rows if r[2] >= HOLD_MM2 and shaved(r[0]) <= LIP_MM2 and whole(r)), None)
    if shaved(pick[0]) <= LIP_MM2:
        return (*pick, False, pick, footing)
    clean = next(r for r in order if shaved(r[0]) <= LIP_MM2 and whole(r))  # d = 0 shaves nothing
    if clean[1] >= min(pick[1], STEADY_TIP_DEG) - 0.5:
        return (*clean, False, clean, footing)
    return (*pick, True, clean, footing)


def _ledges(man, top: float):
    """Up-facing surface (Z up) lower than `top`: each triangle's height, the depth of solid straight under it
    and its area, for telling which flat cuts would shave a ledge thin."""
    import igl.embree
    import numpy as np

    mesh = man.to_mesh64()
    V = np.asarray(mesh.vert_properties[:, :3], np.float64)
    F = np.asarray(mesh.tri_verts, np.int64)
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    n = np.cross(b - a, c - a)
    area = np.linalg.norm(n, axis=1) / 2
    mid = (a + b + c) / 3
    up = (n[:, 2] > 0.5 * 2 * area) & (mid[:, 2] < top)
    below = np.full(int(up.sum()), np.inf)
    if up.any():
        ei = igl.embree.EmbreeIntersector()
        ei.init(np.asfortranarray(V, np.float32), np.asfortranarray(F, np.int32), True)
        down = np.array([0, 0, -1.0], np.float32)
        for i, q in enumerate(mid[up]):
            f, t, _, _ = ei.intersectRay_first((q + [0, 0, -1e-3]).astype(np.float32), down)
            if f >= 0:
                below[i] = t + 1e-3
    return mid[up, 2], below, area[up]


def print_com(m, printer: Printer):
    """Centre of mass of the model as printed, not as a solid: a printer lays solid walls printer.shell_mm deep
    under the surface and fills the rest with printer.infill, so thin parts (all wall) weigh more against a thick
    body (mostly infill) than the solid centre says. hunyuan_necromutant on its feet: tip +1.2° solid, -5.8° with
    walls only: its tentacles pull it over. Per surface point (wall_thickness, equal area each) the wall weighs
    area · min(shell, half the thickness there), at half that depth in; the rest of the volume weighs infill.
    `m` is closed, in mm."""
    import numpy as np
    import trimesh

    solid = np.asarray(m.center_mass, np.float64)
    if printer.infill >= 1.0:
        return solid
    pts, fi = trimesh.sample.sample_surface(m, THICKNESS_SAMPLES, seed=SEED)
    inward = -np.asarray(m.face_normals, np.float64)[fi] * (1.0 if float(m.volume) >= 0 else -1.0)
    depth = np.minimum(printer.shell_mm, np.nan_to_num(_ray_thickness(m, pts, inward), posinf=2 * printer.shell_mm) / 2)
    w = depth * float(m.area) / len(pts)  # the wall's volume at each point
    wall_c = ((pts + inward * depth[:, None] / 2) * w[:, None]).sum(0)
    vol = abs(float(m.volume))
    rest = max(vol - float(w.sum()), 0.0)  # the inside beyond the walls, at the solid centre less the walls
    rest_c = (solid * vol - wall_c) if rest > 0 else np.zeros(3)
    return (wall_c + printer.infill * rest_c) / (float(w.sum()) + printer.infill * rest)


def _rest_faces(V, com):
    """Faces of the convex hull: (outward normal, tip angle, tilt from straight down in degrees, area), steadiest
    first. A tip angle under 0: the centre of mass is not over the face, it does not rest on it as it is."""
    import numpy as np
    import trimesh

    hull = trimesh.Trimesh(V, process=False).convex_hull
    groups = [list(f) for f in hull.facets]
    used = {i for g in groups for i in g}
    groups += [[i] for i in range(len(hull.faces)) if i not in used]
    out = []
    for g in groups:
        nrm = np.asarray(hull.face_normals[g[0]], np.float64)
        P = hull.vertices[np.unique(hull.faces[g])]
        u = np.cross(nrm, [1.0, 0, 0] if abs(nrm[0]) < 0.9 else [0, 1.0, 0])
        u /= np.linalg.norm(u)
        w = np.cross(nrm, u)
        tip = _tip_deg(np.c_[P @ u, P @ w], np.array([com @ u, com @ w]), float((P[0] - com) @ nrm))
        out.append((nrm, tip, float(np.degrees(np.arccos(np.clip(-nrm[1], -1.0, 1.0)))), float(hull.area_faces[g].sum())))
    return sorted(out, key=lambda r: -r[1])


PLATE_MARGIN_MM = 1.0  # kept free round the model on each side of the plate
PLATE_TURN_STEP_DEG = 0.5


def plate_fit(m, printer: Printer) -> dict[str, Any]:
    """Whether `m` (in mm, Y up, as it will print) fits the printer (printer.plate_mm), turned about the vertical
    if it only fits that way: a long model can go across the plate's diagonal. Without the check a model too big
    printed nothing and said nothing (the slicer refuses it, so the turn and brim advice just went missing).
    Returns {"plateMm", "sizeMm", "fits", "turnDeg", "scale"}: `turnDeg` the turn about Y (degrees, the smallest
    of the best; 0 when it fits as it stands), `scale` how much it could grow (>= 1) or must shrink (< 1) to fit."""
    import numpy as np

    W, D, H = printer.plate_mm[0] - 2 * PLATE_MARGIN_MM, printer.plate_mm[1] - 2 * PLATE_MARGIN_MM, printer.plate_mm[2]
    V = np.asarray(m.vertices, np.float64)
    P = V[:, [0, 2]]
    try:
        from scipy.spatial import ConvexHull

        P = P[ConvexHull(P).vertices]
    except Exception:  # a flat footprint: every point
        pass
    height = float(np.ptp(V[:, 1]))

    def flat(deg):  # how much it could grow on the plate turned by `deg`, and its footprint so
        a = np.radians(deg)
        w, d = np.ptp(P @ np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]]), axis=0)
        return min(W / max(w, 1e-9), D / max(d, 1e-9)), (w, d)

    best, size = flat(0.0)
    as_is, turn = size, 0.0
    if best < 1.0:
        for deg in np.arange(PLATE_TURN_STEP_DEG, 180.0, PLATE_TURN_STEP_DEG):
            g, wd = flat(float(deg))
            if g > best + 1e-9:
                best, size, turn = g, wd, float(deg)
    scale = min(best, H / max(height, 1e-9))  # too big: shrunk by this it fits, turned the best way
    fits = bool(scale >= 1.0)
    if not fits:
        size, turn = as_is, 0.0
    return {
        "plateMm": [round(v, 1) for v in printer.plate_mm],
        "sizeMm": [round(float(size[0]), 1), round(float(size[1]), 1), round(height, 1)],
        "fits": fits,
        "turnDeg": turn,
        "scale": round(float(scale), 3),
    }


def stand(m, printer: Printer, log: Log = print, base: str = "auto"):
    """Make a model stand on the plate, and later on a shelf: its centre of mass over what it stands on, far
    enough in that a knock doesn't tip it over (the tip angle: how far it tilts before it falls).

    Upright as made (Y up), if needed with its bottom cut flat by up to 2 mm: an uneven base touches the plate
    at a few points, which hold neither the print nor the model. On the corpus a cut of 0.3–1 mm gives most
    figures a flat bottom (trellis2_statue: 0 -> 1737 mm² of contact, steady at 27°). A model that can't stand
    upright even so falls at a breath (under 3°), or only stands on a cut that shaves its bottom ledge thin
    (see _best_cut). It is tilted up to 3° onto a face of its hull, if that steadies it. A cut that only shaves
    gives way to the first that doesn't, tilted if need be, as long as the model doesn't fall: wobbly is reported,
    a base changes the look. If it would still fall and touches the plate with a footing that holds (HOLD_MM2:
    feet, a bottom) it was made to stand and gets a round base (`base` "none" leaves it as it is); otherwise it
    is an object lying about, stood on its tip by the generator (a sword, a blaster, a backpack on a hanging
    strap), and is laid on the face it lies steadiest on. Steadiness is judged by the centre of mass as printed
    (print_com), not as a solid.
    `m` is closed, in mm, Y up, bottom at 0. Returns (mesh, T, info): T the 4x4 move (rotation and shift) the
    result went through before any cut or base, so pieces kept beside it can follow; mesh None when it was
    left as it was."""
    import manifold3d as mf
    import numpy as np
    import trimesh

    V = np.asarray(m.vertices, np.float64)
    F = np.asarray(m.faces, np.int64)
    com = print_com(m, printer)
    cut_max = min(CUT_MAX_MM, 0.03 * float(m.extents[1]))
    T = np.eye(4)

    def solid(Vy):
        return mf.Manifold(mf.Mesh64(vert_properties=np.ascontiguousarray(_zup(Vy)), tri_verts=F.astype(np.uint64)))

    man = solid(V)
    if man.status() != mf.Error.NoError:
        raise RuntimeError(f"not a solid Manifold takes: {man.status()}")
    d, tip, contact, shaves, clean, footing = _best_cut(man, _zup(com[None])[0], printer, cut_max)
    com0 = com
    info: dict[str, Any] = {"pose": "upright"}
    add_base = False
    def onto(nrm):
        """Turned to rest on the hull face with outward normal nrm, centred, on the plate."""
        R = np.eye(4)
        R[:3, :3] = trimesh.geometry.align_vectors(nrm, [0, -1.0, 0])[:3, :3]
        V2 = trimesh.transform_points(np.asarray(m.vertices, np.float64), R)
        lo, hi = V2.min(0), V2.max(0)
        T2 = trimesh.transformations.translation_matrix([-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2]) @ R
        V2 = trimesh.transform_points(np.asarray(m.vertices, np.float64), T2)
        c2 = trimesh.transform_points(com0[None], T2)[0]
        man2 = solid(V2)
        cut = min(CUT_MAX_MM, 0.03 * float(np.ptp(V2[:, 1])))
        return (T2, V2, c2, man2, *_best_cut(man2, _zup(c2[None])[0], printer, cut, hold=bool(nrm[1] < -0.9)))

    if tip < FALLS_TIP_DEG or shaves:
        hull_faces = _rest_faces(V, com)
        rests = [r for r in hull_faces if r[1] > 0]
        small = [r for r in hull_faces if r[2] <= TILT_FREE_DEG]  # the tilt is judged by where it lands, not by this face
        turned = onto(small[0][0]) if small else None
        # made to stand, however weakly: it rests near straight down (or with its centre of mass over what it
        # stands on), and a flat cut gives it a footing that holds (feet, a bottom), which a base holds it by.
        # tripo_pack rests near down but touches with the tip of a hanging strap (3 mm²): its base held the whole
        # bag up on that strap; hunyuan_necromutant touches with claw tips, 28 mm² at a 0.7 mm cut
        made_to_stand = footing is not None and (any(r[2] <= UPRIGHT_TILT_DEG for r in rests) or (tip > 0 and contact >= HOLD_MM2))
        if turned and turned[5] >= FALLS_TIP_DEG and not turned[7]:  # a tilt nobody sees puts it on a face it rests on
            T, V, com, man, d, tip, contact = turned[:7]
            info["tiltDeg"] = round(small[0][2], 1)
        elif shaves and clean[1] >= FALLS_TIP_DEG and (not turned or clean[1] >= turned[8][1]):
            d, tip, contact = clean  # wobbly is no reason for a base: the first cut that shaves nothing
            shaves = False
        elif shaves and turned and turned[8][1] >= FALLS_TIP_DEG:
            T, V, com, man = turned[:4]
            d, tip, contact = turned[8]
            info["tiltDeg"] = round(small[0][2], 1)
            shaves = False
        elif made_to_stand:
            add_base = base != "none"
            if add_base:  # on the base by its footing; the base takes any ledge, no need to shave it
                d, tip, contact = footing
        elif rests and tip < FALLS_TIP_DEG:  # an object stood on its tip: laid on the face it really lies steadiest on
            biggest = sorted(rests, key=lambda r: -r[3])[:LYING_TRIES]  # a hull face's own tip angle says little: try them
            tried = rests[:LYING_TRIES] + [r for r in biggest if not any(r is x for x in rests[:LYING_TRIES])]
            lying = [onto(r[0]) for r in tried]
            best = max([t for t in lying if not t[7]] or lying, key=lambda t: t[5])
            T, V, com, man, d, tip, contact = best[:7]
            info["pose"] = "lying"
    if d == 0 and not add_base and info["pose"] == "upright" and "tiltDeg" not in info:
        info.update({"tipDeg": round(tip, 1), "contactMm2": round(contact, 1), "cutMm": 0.0})
        return None, T, info
    out = man.trim_by_plane((0.0, 0.0, 1.0), d) if d > 0 else man
    cut_cm3 = (man.volume() - out.volume()) / 1000.0
    lift = -d
    if add_base:
        # A disc under it, centred under the centre of mass, wide enough to take its footing and steady it.
        c = _zup(com[None])[0]
        foot = [np.asarray(q) for q in out.slice(d + printer.layer_mm / 2).to_polygons()]
        reach = max((float(np.linalg.norm(q - c[:2], axis=1).max()) for q in foot), default=0.0)
        radius = max(reach + 2.0, (c[2] - d + BASE_MM) * np.tan(np.radians(STEADY_TIP_DEG)) + 1.0)
        disc = mf.Manifold.cylinder(BASE_MM + 0.01, radius, radius, 96).translate((c[0], c[1], d - BASE_MM))
        out = mf.Manifold.batch_boolean([out, disc], mf.OpType.Add)
        lift = BASE_MM - d
        tip = _tip_deg(np.asarray(disc.slice(d - BASE_MM / 2).to_polygons()[0]), c[:2], c[2] - d + BASE_MM)
        contact = float(np.pi * radius**2)
        info["base"] = {"diameterMm": round(2 * radius, 1), "heightMm": BASE_MM}
    mesh = out.to_mesh64()
    Vo = _yup(np.array(mesh.vert_properties[:, :3], np.float64))
    Vo[:, 1] += lift
    res = _drop_pockets(trimesh.Trimesh(Vo, np.array(mesh.tri_verts, np.int64), process=False))  # a cut can leave dust
    T = trimesh.transformations.translation_matrix([0.0, lift, 0.0]) @ T
    info.update({"tipDeg": round(tip, 1), "contactMm2": round(contact, 1), "cutMm": round(d, 2),
                 "cutCm3": round(cut_cm3, 3)})
    log(f" stand: {info}")
    return res, T, info


# --- turning for print ---------------------------------------------------------------------------

def _support(pts, nrm, per, down):
    """Support for printing with `down` pointing at the plate, from surface points: (volume mm³, plate contact
    mm², height mm). A point whose face slopes down less than SUPPORT_SLOPE_DEG off flat and is above the plate
    needs a column down to the first face below it in its SUPPORT_CELL_MM cell, or to the plate; the volume is
    the columns under each point's footprint. Against PrusaSlicer on the corpus (auto supports, 0.20 mm
    STRUCTURAL): about 0.41 g of support per cm³ of this, r 0.86."""
    import numpy as np
    import trimesh

    R = trimesh.geometry.align_vectors(down, [0, -1.0, 0])[:3, :3]
    P, N = pts @ R.T, nrm @ R.T
    y = P[:, 1] - P[:, 1].min()
    facing = -N[:, 1]  # 1 straight down
    over = (facing > np.cos(np.radians(SUPPORT_SLOPE_DEG))) & (y > 0.2)
    cell = np.floor(P[:, [0, 2]] / SUPPORT_CELL_MM).astype(np.int64)
    key = (cell[:, 0] - cell[:, 0].min()) * 1_000_003 + (cell[:, 1] - cell[:, 1].min())
    order = np.lexsort((y, key))
    k, yy = key[order], y[order]
    start = np.r_[True, k[1:] != k[:-1]]
    lift = (np.cumsum(start) - 1) * 1e6  # each cell its own range, so the running max doesn't cross cells
    floor = np.maximum.accumulate(np.where(N[order, 1] > 0, yy + lift, lift - 1.0)) - lift  # highest up-facing so far
    below = np.r_[-1.0, floor[:-1]]
    below[start] = -1.0
    column = np.zeros(len(y))
    column[order] = yy - np.maximum(below, 0.0)
    return (float((per * facing * column)[over].sum()), float(per * ((y < 0.2) & (facing > 0.9)).sum()), float(np.ptp(y)))


def print_turn(m, printer: Printer, log: Log = print) -> dict[str, Any]:
    """How to turn the model on the plate to print faster with less plastic. A figure prints as it stands, but an
    object stood or laid for the shelf often needs far less support another way up. Down directions tried: as it
    stands, the 40 biggest faces of its hull, 100 spread over the sphere, each at least TURN_APART_DEG off how it
    stands; turned, it must keep TURN_CONTACT_MM2 on the plate and not topple (FALLS_TIP_DEG). A quick pass on a
    few points picks TURN_POOL, the full estimate (SUPPORT_SAMPLES_PER_MM2: sparse points read trellis2_harbor 15 %
    better on its side, PrusaSlicer says 56 % worse) ranks them, those TURN_APART_DEG apart stay (of two closer ones,
    the steadier if it needs about the same support).
    The estimate finds where to look, and only PrusaSlicer can say if it pays: rodin_spider, trellis2_lattice and
    tripo_blaster all read 40-43 % less support and print +12, +36 and -60 min, as support is only part of the time.
    So the best TURN_TRIED past TURN_TRY_GAIN are sliced, with how it stands, and the one saving the most time is
    suggested if it saves TURN_SAVES_MIN and TURN_SAVES_G (hunyuan31_drill's second pick is 3 min faster than its
    first and far steadier). Without the slicer nothing is suggested. The same model gets the same answer: the
    G-code doesn't change between runs or with the thread count.
    `m` is closed, in mm, Y up as it stands. Returns {"supportCm3": estimate as it stands, and when turns were tried
    "print": {"minutes", "grams"} as it stands, and when turning pays "turned": {"down": the direction to put down
    (unit, the file's axes), "rotation": 3x3 taking the file's axes to the turned ones (down -> -Y), "minutes",
    "grams", "savedMinutes", "savedGrams", "supportCm3", "contactMm2", "heightMm"}}.
    Only for FDM: resin prints hang off the plate on supports whichever way up."""
    import numpy as np
    import trimesh

    from studio_bridge.print_slicer import slice_stats

    t0 = time.time()
    k = np.arange(100) + 0.5
    phi, th = np.arccos(1 - 2 * k / 100), np.pi * (1 + 5**0.5) * k
    hull = m.convex_hull
    downs = np.vstack([[[0, -1.0, 0]], hull.face_normals[np.argsort(-hull.area_faces, kind="stable")[:40]],
                       np.c_[np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)]])
    nrm = np.asarray(m.face_normals, np.float64)
    V = np.asarray(m.vertices, np.float64)
    com = print_com(m, printer)

    def estimate(count, which):
        pts, fi = trimesh.sample.sample_surface(m, count, seed=SEED)
        return {i: _support(pts, nrm[fi], float(m.area) / count, downs[i]) for i in which}

    def tip(i):  # with this way down, how far its weight is inside what it rests on
        R = trimesh.geometry.align_vectors(downs[i], [0, -1.0, 0])[:3, :3]
        P, c = V @ R.T, R @ com
        low = float(P[:, 1].min())
        return _tip_deg(P[P[:, 1] < low + 0.2][:, [0, 2]], c[[0, 2]], float(c[1]) - low)

    quick = estimate(100_000, range(len(downs)))
    apart = np.cos(np.radians(TURN_APART_DEG))
    pool: list[int] = []
    for i in sorted((i for i in quick if i != 0 and quick[i][1] >= TURN_CONTACT_MM2), key=lambda i: (quick[i][0], i)):
        if len(pool) == TURN_POOL:
            break
        if downs[i] @ downs[0] < apart and tip(i) >= FALLS_TIP_DEG:
            pool.append(i)
    full = estimate(int(np.clip(float(m.area) * SUPPORT_SAMPLES_PER_MM2, 100_000, 2_000_000)), [0, *pool])
    stands = full[0][0]
    tried: list[int] = []
    for i in sorted((i for i in pool if full[i][1] >= TURN_CONTACT_MM2), key=lambda i: (round(full[i][0] / 1000, 1), full[i][2], i)):
        if full[i][0] > (1 - TURN_TRY_GAIN) * stands or stands - full[i][0] < TURN_TRY_MIN_CM3 * 1000:
            continue
        twin = next((n for n, j in enumerate(tried) if downs[i] @ downs[j] >= apart), None)
        if twin is None:
            if len(tried) < TURN_TRIED:
                tried.append(i)
        elif full[i][0] <= TURN_TWIN_SUPPORT * full[tried[twin]][0] and tip(i) > tip(tried[twin]):
            tried[twin] = i
    info: dict[str, Any] = {"supportCm3": round(stands / 1000, 1)}
    base = slice_stats(m, ini=printer.slicer_ini) if tried else None
    if base is not None:
        info["print"] = base
        best = None
        for i in tried:
            R = trimesh.geometry.align_vectors(downs[i], [0, -1.0, 0])[:3, :3]
            got = slice_stats(m, R, ini=printer.slicer_ini)
            if (got is not None and base["minutes"] - got["minutes"] >= TURN_SAVES_MIN and base["grams"] - got["grams"] >= TURN_SAVES_G
                    and (best is None or got["minutes"] < best[2]["minutes"])):
                best = (i, R, got)
        if best is not None:
            i, R, got = best
            info["turned"] = {"down": [round(float(v), 4) for v in downs[i]], "rotation": np.round(R, 5).tolist(), **got,
                              "savedMinutes": round(base["minutes"] - got["minutes"], 1), "savedGrams": round(base["grams"] - got["grams"], 1),
                              "supportCm3": round(full[i][0] / 1000, 1), "contactMm2": round(full[i][1]), "heightMm": round(full[i][2], 1)}
    log(f" print turn: {info} ({time.time() - t0:.0f}s)")
    return info


# --- floating pieces -------------------------------------------------------------------------------

def _rests_on_plate(tri, base: float, mm_per_unit: float, layer_mm: float) -> bool:
    """A separate piece prints as its own part only when it starts on the plate and stands there: some of it lies
    within the first layer, and its centre of mass is over that footprint. Otherwise it starts in mid-air or
    leans out past its footing, so it needs supports, and on the shelf it falls over. On rodin_knight three
    0.5 mm strands by the feet, 0.06–0.6 mm above the plate, used to count as parts lying there."""
    import numpy as np
    from scipy.spatial import Delaunay, QhullError

    pts = tri.reshape(-1, 3)
    foot = pts[(pts[:, 1] - base) * mm_per_unit <= layer_mm][:, [0, 2]]
    if len(foot) < 3:
        return False
    vols = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])) / 6
    if vols.sum() <= 0:
        return False
    com = (vols[:, None] * tri.sum(1) / 4).sum(0) / vols.sum()
    try:
        return bool(Delaunay(np.unique(foot, axis=0)).find_simplex(com[[0, 2]][None])[0] >= 0)
    except (QhullError, ValueError):  # all on one line: it would roll
        return False


def split_floating(mesh, mm_per_unit: float, printer: Printer = PRINTERS[DEFAULT_PRINTER]):
    """Pieces hanging in mid-air, apart from the body: a slicer prints them on supports or as spaghetti.
    The body is the biggest shell; a piece that rests on the plate (a sword lying by the feet, see
    _rests_on_plate) or sits inside the body stays with it. Those within the bridge reach were already
    bridged, so these are farther off. The caller decides whether they go (the user picks; the default is
    to remove them).
    Returns (body, pieces, about) with about = one dict per piece, biggest first; pieces is None when there
    are none. Y is up."""
    import igl
    import numpy as np
    import trimesh

    F = np.asarray(mesh.faces)
    lab = trimesh.graph.connected_component_labels(mesh.face_adjacency, node_count=len(F))
    n = int(lab.max()) + 1 if len(lab) else 0
    if n <= 1:
        return _lean(mesh), None, []
    tri = np.asarray(mesh.triangles, np.float64)
    vol = np.bincount(lab, np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])) / 6, n)
    body = int(np.argmax(vol))
    in_body = lab == body
    BV = np.asarray(mesh.vertices, np.float64)
    bF = F[in_body]
    base = float(BV[np.unique(bF), 1].min())
    # each piece's faces, in their order in the mesh; the body's trees are built once for all pieces, not per piece
    order = np.argsort(lab, kind="stable")
    ends = np.cumsum(np.bincount(lab, minlength=n))
    starts = ends - np.bincount(lab, minlength=n)
    faces_of = lambda k: F[order[starts[k]:ends[k]]]  # noqa: E731
    apart = []
    for k in np.argsort(-vol):
        if k == body or vol[k] <= 0:  # inside-out shells are pockets, not pieces
            continue
        if _rests_on_plate(BV[faces_of(k)], base, mm_per_unit, printer.layer_mm):  # a separate part, not debris
            continue
        apart.append(k)
    if apart:  # a vertex of each piece: inside the body or not
        inside = _winding(BV, bF, BV[[int(faces_of(k).min()) for k in apart]], bool(mesh.is_watertight)) > 0.5
        floating = [k for k, i in zip(apart, inside) if not i]
    else:
        floating = []
    if not floating:
        return _lean(mesh), None, []
    about = []
    verts = [BV[np.unique(faces_of(k))] for k in floating]
    probes = [v[:: max(1, len(v) // 500)] for v in verts]
    d2 = igl.point_mesh_squared_distance(np.vstack(probes), BV, bF)[0]
    at = np.cumsum([0] + [len(p) for p in probes])
    for j, (k, v) in enumerate(zip(floating, verts)):
        gap = float(np.sqrt(d2[at[j]:at[j + 1]].min()))
        lo, hi = v.min(0), v.max(0)
        about.append({
            "volumeCm3": round(float(vol[k]) * mm_per_unit**3 / 1000, 3),
            "gapMm": round(gap * mm_per_unit, 1),
            "_center": (lo + hi) / 2,
            "_size": hi - lo,
        })
    away = np.isin(lab, floating)
    parts = trimesh.Trimesh(BV, F[away], process=False)
    parts.remove_unreferenced_vertices()
    keep = trimesh.Trimesh(BV, F[~away], process=False)
    keep.remove_unreferenced_vertices()
    _lean(mesh)
    return keep, parts, about
