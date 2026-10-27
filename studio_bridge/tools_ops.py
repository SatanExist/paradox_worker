"""Tools on a finished model — the work itself, shared by the RunPod tools worker and local runs.

Each tool takes a GLB on disk and writes a new GLB plus a report (checks before and after).
No GPU and no network here: the caller downloads the input and uploads the result.

Compressed GLBs (Draco, meshopt, quantized — what Tripo, Meshy and our own showcase ship) are
unpacked first with gltf-transform (tools_node/decode.mjs): trimesh would read them as zeros.

  print_prep  weld, then make it one closed solid that keeps its surface (print_solid: patch the holes,
              fill a hollow skin, or a 0.5 mm wrap, whichever lost nothing and filled more); the voxel rebuild
              (print_remesh) is the fallback; optionally scale to a height in mm, stand the model
              on the plate (Y up, base at 0). Pieces hanging in mid-air are reported and removed unless
              params["floating"] is "keep"; the other choice is written too, as the "alternate" file
  game_prep   cut triangles to a budget and shrink textures, keeping materials and UVs
              (gltf-transform: tools_node/game.mjs), stand the model on the floor
"""

from __future__ import annotations

import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from studio_bridge.mesh_repair import load_glb_mesh, mesh_stats


TOOLS_NODE = Path(os.getenv("TOOLS_NODE_DIR", Path(__file__).resolve().parents[1] / "tools_node"))
TOOLS_BLENDER = Path(__file__).resolve().parents[1] / "tools_blender"
PACKED = {"KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_mesh_quantization"}
DEFAULT_PRINT_HEIGHT_MM = 120.0
SOLID_STEPS = {
    "repair": "made one closed solid (holes patched)",
    "solidify": "made one closed solid (hollow skin filled)",
    "wrap": "made one closed solid (wrapped 0.5 mm)",
}


def _glb_json(path: Path) -> dict[str, Any]:
    with open(path, "rb") as fh:
        head = fh.read(20)
        if len(head) < 20 or head[:4] != b"glTF":
            raise ValueError("not a GLB file")
        return json.loads(fh.read(struct.unpack("<I", head[12:16])[0]))


def _world_node(path: Path):
    """The transform of a root node named "world", which trimesh takes for its own base frame and drops
    (TRELLIS, TripoSR, Step1X and Hi3DGen name their root so); None when there is none or it does nothing."""
    import numpy as np
    import trimesh

    meta = _glb_json(path)
    nodes = meta.get("nodes") or []
    for node in nodes:
        if node.get("name") != "world":
            continue
        if "matrix" in node:
            m = np.asarray(node["matrix"], float).reshape(4, 4).T  # glTF stores columns
        else:
            m = trimesh.transformations.quaternion_matrix(np.roll(np.asarray(node.get("rotation", [0, 0, 0, 1]), float), 1))
            m[:3, :3] = m[:3, :3] * np.asarray(node.get("scale", [1, 1, 1]), float)
            m[:3, 3] = node.get("translation", [0, 0, 0])
        return None if np.allclose(m, np.eye(4)) else m
    return None


OVERLAP_MAX_TRIS = 3_000_000  # above this the cut and the measuring setup run one after the other


def _triangles_in_file(path: Path) -> int:
    """Triangles the file declares (index counts in its JSON), without reading the geometry."""
    meta = _glb_json(path)
    accessors = meta.get("accessors") or []
    total = 0
    for mesh in meta.get("meshes") or []:
        for prim in mesh.get("primitives") or []:
            if prim.get("mode", 4) != 4:
                continue
            idx = prim.get("indices")
            if idx is not None and idx < len(accessors):
                total += accessors[idx].get("count", 0) // 3
            elif "POSITION" in (prim.get("attributes") or {}):
                total += accessors[prim["attributes"]["POSITION"]].get("count", 0) // 3
    return total


def _glb_extensions(path: Path) -> set[str]:
    with open(path, "rb") as fh:
        head = fh.read(20)
        if len(head) < 20 or head[:4] != b"glTF":
            raise ValueError("not a GLB file")
        length = struct.unpack("<I", head[12:16])[0]
        meta = json.loads(fh.read(length))
    return set(meta.get("extensionsUsed") or [])


def _unpacked(path: Path) -> Path:
    """The same model with plain geometry; the file itself when it already is."""
    if not (_glb_extensions(path) & PACKED):
        return path
    node = shutil.which("node")
    if not node or not (TOOLS_NODE / "decode.mjs").is_file():
        raise RuntimeError("compressed model, and no gltf-transform here to unpack it")
    fd, name = tempfile.mkstemp(suffix=".glb")
    os.close(fd)
    out = Path(name)
    done = subprocess.run(
        [node, str(TOOLS_NODE / "decode.mjs"), str(path), str(out)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if done.returncode != 0:
        out.unlink(missing_ok=True)
        raise RuntimeError(f"could not unpack the model: {done.stderr.strip()[-300:]}")
    return out


def _load(path: Path):
    """Load for mesh work, refusing a model that came out empty or flat rather than 'fixing' it."""
    plain = _unpacked(path)
    try:
        mesh = load_glb_mesh(plain)
    finally:
        if plain != path:
            try:
                plain.unlink(missing_ok=True)
            except OSError:  # Windows keeps it open while trimesh holds the scene; Linux workers don't
                pass
    if len(mesh.faces) == 0 or float(max(mesh.extents)) <= 0:
        raise ValueError("could not read the model's geometry")
    return mesh


def _components(mesh) -> int:
    """Separate pieces, counted on the face graph (mesh.split builds a mesh per piece: minutes on 1M faces)."""
    import numpy as np
    import trimesh

    if len(mesh.faces) == 0:
        return 0
    labels = trimesh.graph.connected_component_labels(mesh.face_adjacency, node_count=len(mesh.faces))
    return int(len(np.unique(labels)))


def _print_checks(mesh) -> dict[str, Any]:
    """What a print person wants to know: closed, one piece, how big, how much plastic."""
    stats = mesh_stats(mesh)
    extents = [float(v) for v in mesh.extents]  # metres: glTF units
    stats["components"] = _components(mesh)
    stats["sizeMm"] = [round(v * 1000, 1) for v in extents]
    stats["heightMm"] = round(extents[1] * 1000, 1)
    stats["volumeCm3"] = round(float(mesh.volume) * 1e6, 2) if mesh.is_watertight else None
    return stats


def _close_holes_pymeshlab(mesh, max_hole_size: int):
    """Close holes with pymeshlab when the image has it; trimesh's fill_holes only fixes small ones."""
    try:
        import pymeshlab  # noqa: F401
    except ImportError:
        return mesh, False
    from studio_bridge.mesh_repair import repair_pymeshlab

    tmp_dir = Path(tempfile.mkdtemp(prefix="tools-"))
    src, dst = tmp_dir / "in.ply", tmp_dir / "out.ply"
    mesh.export(src)
    repair_pymeshlab(src, dst, max_hole_size=max_hole_size)
    import trimesh

    closed = trimesh.load(dst, force="mesh", process=False)
    return closed, True


def print_prep(in_path: Path, out_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    import numpy as np
    import trimesh

    mesh = _load(in_path)
    steps: list[str] = []

    # Merge by position only: seams split by UVs and normals would otherwise stay open edges.
    # Welding doesn't change the shape, so "before" is measured after it — on raw GLB triangle
    # soup every face would count as its own piece with three open edges.
    mesh.merge_vertices(merge_tex=True, merge_norm=True)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    before = _print_checks(mesh)
    steps.append("welded")

    height_mm = params.get("heightMm")
    remesh = solid = None
    # The solid is made at a print scale: the tolerances (a 3 mm ball, 0.5 mm wrap, 1 mm loss) are physical.
    # Without a height the model is taken as a typical figurine; very small or large prints are worked at
    # the nearest sane size, so the tolerances scale with them.
    current = float(mesh.extents[1])
    work_mm = min(max(float(height_mm or DEFAULT_PRINT_HEIGHT_MM), 40.0), 250.0)
    mm_per_unit = work_mm / current if current > 0 else 1000.0
    try:
        from studio_bridge.print_solid import make_solid

        mesh, solid = make_solid(mesh, mm_per_unit)
        solid["atHeightMm"] = work_mm
        steps.append(SOLID_STEPS.get(solid["method"], "made one closed solid"))
        if solid.get("thinWalls"):
            steps.append(f"walls stay thin (about {solid['resultWallMm']:g} mm): it may print as a fragile shell")
    except Exception as exc:  # the old path: close holes, and rebuild from voxels when that falls short
        print(f"print_solid failed, voxel fallback: {exc}")
        if not mesh.is_watertight:
            original = mesh.copy()
            mesh, used = _close_holes_pymeshlab(mesh, int(params.get("maxHoleSize") or 5000))
            if used:
                steps.append("holes closed (pymeshlab)")
            trimesh.repair.fill_holes(mesh)
            if not mesh.is_watertight:
                from studio_bridge.print_remesh import remesh_solid

                mesh, remesh = remesh_solid(mesh, mm_per_unit, compare_to=original)
                steps.append(f"rebuilt as a closed solid ({remesh['voxelMm']:g} mm detail)")
    trimesh.repair.fix_normals(mesh)
    steps.append("normals fixed")

    # Pieces hanging in mid-air: the user chooses, the default is to remove them. Both files are made, so
    # the choice is instant; the main one follows params["floating"], the other goes out as "alternate".
    from studio_bridge.print_solid import split_floating

    try:
        body, pieces, about = split_floating(mesh, mm_per_unit)
    except Exception as exc:  # a report extra: never worth failing the print for
        print(f"floating pieces not checked: {exc}")
        body, pieces, about = mesh, None, []
    keep = str(params.get("floating") or "remove") == "keep"

    # Scale and plate placement come from the body alone, so both files line up and the body sits on Y=0.
    s = 1.0
    if height_mm and float(body.extents[1]) > 0:
        s = float(height_mm) / 1000.0 / float(body.extents[1])
        steps.append(f"scaled to {float(height_mm):g} mm")
    lo, hi = body.bounds * s
    shift = np.array([-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2])
    for m in (body, pieces):
        if m is not None:
            m.apply_scale(s)
            m.apply_translation(shift)
    steps.append("placed on plate")

    floating = None
    if pieces is not None:
        unit_mm = 1000.0  # glTF is metres
        floating = {
            "count": len(about),
            "volumeCm3": round(sum(p["volumeCm3"] for p in about), 3),
            "pieces": [
                {
                    "volumeCm3": p["volumeCm3"],
                    "gapMm": p["gapMm"],
                    "centerMm": [round(float(v), 1) for v in (p["_center"] * s + shift) * unit_mm],
                    "sizeMm": [round(float(v), 1) for v in p["_size"] * s * unit_mm],
                }
                for p in about
            ],
            "default": "remove",
            "file": "keep" if keep else "remove",
            "alternate": "remove" if keep else "keep",
        }
        n = floating["count"]
        what = f"{n} floating piece{'s' if n != 1 else ''} ({floating['volumeCm3']:g} cm³)"
        steps.append(f"kept {what}" if keep else f"removed {what}")

    with_pieces = {"body": body, "floating": pieces} if pieces is not None else {"body": body}
    main = with_pieces if keep else {"body": body}
    _export_print(main, out_path)
    report = {"operation": "print_prep", "steps": steps, "before": before, "after": _print_checks(_joined(main))}
    if floating:
        alt = out_path.with_name(out_path.stem + "-alternate.glb")
        _export_print({"body": body} if keep else with_pieces, alt)
        report["floating"] = floating
        report["extraFiles"] = {"alternate": str(alt)}
    if solid:
        report["solid"] = solid
    if remesh:
        report["remesh"] = remesh
    return report


def _joined(parts: dict[str, Any]):
    import trimesh

    meshes = [m for m in parts.values() if m is not None]
    return meshes[0] if len(meshes) == 1 else trimesh.util.concatenate(meshes)


def _export_print(parts: dict[str, Any], path: Path) -> None:
    """One node per part ("body", "floating"), so the studio can tint the pieces the user may remove.
    One plain material: a print has no texture, and a clay look shows the shape best."""
    import numpy as np
    import trimesh

    scene = trimesh.Scene()
    for name, m in parts.items():
        if m is None:
            continue
        m.visual = trimesh.visual.TextureVisuals(
            material=trimesh.visual.material.PBRMaterial(
                baseColorFactor=np.array([200, 196, 188, 255], dtype=np.uint8),
                metallicFactor=0.0,
                roughnessFactor=0.9,
            )
        )
        scene.add_geometry(m, geom_name=name, node_name=name)
    scene.export(path, file_type="glb", include_normals=True)  # without normals three.js renders it black


def _as_drawn(geom):
    """Vertices, faces and normals of a trimesh geometry as a viewer draws them, plus which file vertex
    each drawn vertex is (to carry UVs over). A file without normals is drawn flat, as glTF says; trimesh
    would make up smooth ones that change with how the vertices happen to be welded."""
    import numpy as np

    if "vertex_normals" in geom._cache.cache:  # the file's own
        return np.asarray(geom.vertices), np.asarray(geom.faces), np.asarray(geom.vertex_normals), np.arange(len(geom.vertices))
    corner = np.asarray(geom.faces).reshape(-1)
    flat = np.repeat(np.asarray(geom.face_normals), 3, axis=0)
    return np.asarray(geom.vertices)[corner], np.arange(len(corner)).reshape(-1, 3), flat, corner


def _shaded(path: Path):
    """Vertices, faces and the file's own vertex normals (what the light uses), in model space,
    and whether any node moves its mesh (then positions differ from the mesh's own).

    `_load` merges into one trimesh and recomputes normals; a scene keeps the ones the file has.
    """
    import numpy as np
    import trimesh

    plain = _unpacked(path)
    try:
        scene = trimesh.load(plain, process=False)
    finally:
        if plain != path:
            try:
                plain.unlink(missing_ok=True)
            except OSError:  # Windows keeps it open while trimesh holds the scene
                pass
    if isinstance(scene, trimesh.Trimesh):
        scene = trimesh.Scene(scene)
    world = _world_node(path)
    verts, faces, normals, offset, moved = [], [], [], 0, False
    for node in scene.graph.nodes_geometry:
        matrix, name = scene.graph[node]
        if world is not None:
            matrix = world @ matrix
        geom = scene.geometry.get(name)
        if not isinstance(geom, trimesh.Trimesh) or len(geom.faces) == 0:
            continue
        moved = moved or not np.allclose(matrix, np.eye(4))
        gv, gf, gn, _ = _as_drawn(geom)
        turned = gn @ matrix[:3, :3].T
        normals.append(turned / np.linalg.norm(turned, axis=1, keepdims=True).clip(1e-12))
        verts.append(trimesh.transform_points(gv, matrix))
        faces.append(gf + offset)
        offset += len(gv)
    if not faces:
        raise ValueError("could not read the model's geometry")
    return np.vstack(verts), np.vstack(faces), np.vstack(normals), moved


class _Reference:
    """The original, ready to measure lighter versions against, built once per job.

    Everything that only depends on the original — a mesh ready for meshlab, the face corners and normals,
    the search trees over face centres and over points spread on its surface — is made here, so
    a second cut is measured without rebuilding any of it. Results are moved back by the shift
    `game.mjs` applied, rather than moving the original, so nothing here depends on the cut.
    """

    SPREAD_MIN, SPREAD_MAX = 200_000, 1_000_000

    def __init__(self, original):
        import numpy as np
        import pymeshlab
        from scipy.spatial import cKDTree

        self.ov, self.of, self.on, self.moved = original
        self.size = float((self.ov.max(0) - self.ov.min(0)).max()) or 1.0
        self.mesh = pymeshlab.Mesh(self.ov, self.of)
        self.tri = self.ov[self.of]
        self.cross = np.cross(self.tri[:, 1] - self.tri[:, 0], self.tri[:, 2] - self.tri[:, 0])
        area = np.linalg.norm(self.cross, axis=1)
        rng = np.random.default_rng(1)
        spread = int(min(self.SPREAD_MAX, max(self.SPREAD_MIN, 2 * len(self.of))))
        self.spread_face = rng.choice(len(self.of), spread, p=area / area.sum())
        a, b = rng.random(spread), rng.random(spread)
        over = a + b > 1
        a[over], b[over] = 1 - a[over], 1 - b[over]
        spread_points = (self.tri[self.spread_face] * np.stack([1 - a - b, a, b], axis=1)[:, :, None]).sum(1)
        self.by_centre = cKDTree(self.tri.mean(1))
        self.by_spread = cKDTree(spread_points)
        # Each vertex stands for a third of the area of the faces around it: the mean over
        # vertices then counts surface, not how densely the generator happened to mesh a spot.
        self.vertex_area = np.zeros(len(self.ov))
        for corner in range(3):
            np.add.at(self.vertex_area, self.of[:, corner], area / 6)

    def compare(self, out_path: Path, shift: list[float], find_lost: bool = False):
        """How much the lighter model differs from the original, in shape and in shading.

        Shape, as % of the model's largest side, both ways and the same every time for the same
        model (no random samples, so a decision on it can't flip between runs):
        - old → new (did a part go missing): every vertex of the original against the new surface;
          the mean weighs each vertex by the surface it stands for.
        - new → old (did it bulge or sink): the new model's vertices and fixed points spread over
          its faces against the original surface.
        Shading: the angle between the normals the light uses on the new surface and on the old
        one nearby. Shape alone missed it when a cut model looked chrome; this catches that.
        With `find_lost`, also returns how far each original vertex is from the new surface (% of
        size): where that is large, a part went missing. Otherwise the second value is None.
        """
        import numpy as np
        import pymeshlab
        import trimesh

        rv, rf, rn, _ = _shaded(out_path)
        rv = rv - np.asarray(shift)
        # A fresh set each time (meshlab crashes when meshes are taken out of one), with the
        # original's ready-made copy.
        ms = pymeshlab.MeshSet()
        ms.add_mesh(self.mesh)
        ms.add_mesh(pymeshlab.Mesh(rv, rf))

        # Old → new: every original vertex. Meshlab gives them back in vertex order.
        ms.get_hausdorff_distance(
            sampledmesh=0, targetmesh=1, samplevert=True, sampleface=False, samplenum=len(self.ov), savesample=True
        )
        saved = {ms.mesh(i).label(): ms.mesh(i).vertex_matrix() for i in range(2, ms.mesh_number())}
        sampled, nearest = saved["Hausdorff Sample Point"], saved["Hausdorff Closest Points"]
        if sampled.shape != self.ov.shape or not np.allclose(sampled, self.ov, atol=1e-6 * self.size):
            raise RuntimeError("meshlab changed the order of the original's vertices")
        to_new = np.linalg.norm(sampled - nearest, axis=1)

        # New → old: the new vertices plus points on its faces at fixed spots (same seed every run).
        tri = rv[rf]
        cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        area = np.linalg.norm(cross, axis=1)
        fixed = np.random.default_rng(2)
        on_faces = 200_000
        pick = fixed.choice(len(rf), on_faces, p=area / area.sum())
        a, b = fixed.random(on_faces), fixed.random(on_faces)
        over = a + b > 1
        a[over], b[over] = 1 - a[over], 1 - b[over]
        cloud = np.vstack([rv, (tri[pick] * np.stack([1 - a - b, a, b], axis=1)[:, :, None]).sum(1)])
        ms.add_mesh(pymeshlab.Mesh(cloud))
        to_old = ms.get_hausdorff_distance(
            sampledmesh=ms.mesh_number() - 1, targetmesh=0, samplevert=True, sampleface=False, samplenum=len(cloud)
        )

        mean_to_new = float((to_new * self.vertex_area).sum() / self.vertex_area.sum())
        shape = {
            "meanPct": round(max(mean_to_new, to_old["mean"]) / self.size * 100, 3),
            "maxPct": round(max(float(to_new.max()), to_old["max"]) / self.size * 100, 2),
        }
        lost = to_new / self.size * 100 if find_lost else None

        # Points spread over the new surface by area, with the normal the light sees there.
        rng = np.random.default_rng(0)
        count = 50_000
        pick = rng.choice(len(rf), count, p=area / area.sum())
        u, v = rng.random(count), rng.random(count)
        over = u + v > 1
        u[over], v[over] = 1 - u[over], 1 - v[over]
        bary = np.stack([1 - u - v, u, v], axis=1)[:, :, None]
        points = (tri[pick] * bary).sum(1)
        seen = (rn[rf[pick]] * bary).sum(1)
        facing = cross[pick] / area[pick, None].clip(1e-30)

        # The old surface nearby: the closest point on the faces found around it, preferring
        # faces on the same side (on a thin part the back face can be closer), and the normal
        # there blended from its corners as the light would. Candidate faces come two ways:
        # nearest face centres (right on dense meshes) and points spread over the surface by area
        # (on a long thin face a point can be far from its centre). Meshlab's own transfer
        # recomputes the normals, so it can't be used.
        _, by_centre = self.by_centre.query(points, k=min(16, len(self.of)), workers=-1)
        _, around = self.by_spread.query(points, k=16, workers=-1)
        near = np.hstack([by_centre.reshape(count, -1), self.spread_face[around]])
        k = near.shape[1]
        repeated = np.repeat(points, k, axis=0)
        closest = trimesh.triangles.closest_point(self.tri[near.reshape(-1)], repeated)
        dist = np.linalg.norm(closest - repeated, axis=1).reshape(count, k)
        same_side = np.einsum("nkd,nd->nk", self.cross[near], facing) > 0
        dist = np.where(same_side | ~same_side.any(1, keepdims=True), dist, np.inf)
        best = dist.argmin(1)
        face = near[np.arange(count), best]
        at = closest.reshape(count, k, 3)[np.arange(count), best]
        o_bary = trimesh.triangles.points_to_barycentric(self.tri[face], at)[:, :, None]
        old = (self.on[self.of[face]] * o_bary).sum(1)

        cos = np.einsum("nd,nd->n", seen, old) / (np.linalg.norm(seen, axis=1) * np.linalg.norm(old, axis=1)).clip(1e-12)
        angle = np.degrees(np.arccos(cos.clip(-1, 1)))
        deviation = {
            **shape,
            "normalMeanDeg": round(float(angle.mean()), 1),
            "normalP95Deg": round(float(np.percentile(angle, 95)), 1),
        }
        return deviation, lost


# What no one can see from outside: the body under armour plates, the inner sheet of a thin plate, shells
# inside shells. Generators leave a lot of it (the TRELLIS knight: over a quarter of its 670k triangles),
# and a cut spends triangles on it, then pushes it out through the plates over it: cut to 100k, 13% of the
# knight's triangles pierced another (0.2% in the original), spikes and dents up close; cut to 20k, 52%.
# Left out before the cut (99.6k triangles): 4.4% and 41%, the look at 100k 2.72 -> 0.76%, and the triangles
# go where they show. Also gone: a bottle's insides that broke through its glass when cut (look 35.8 -> 0%).
# A face is seen when, from one of HIDDEN_DIRECTIONS fixed directions on its front side, a ray from far off
# meets it first at its centre. Some faces show only through a narrow slit at angles between those, so
# everything within HIDDEN_RINGS rings of a seen face stays too. Drawn as a viewer does (back faces not
# drawn), 100 views of the knight at 100k: see-through pixels 245 before, 168 with 3 rings (one slit by the
# fist opened: 66 px from above), 104 with 5 (that one 1 px); 512 more directions near the seen ones, 97,
# at three times the time. A huge model gets fewer directions to stay within time; a model that moves
# keeps everything (a bend can open what rest hides).
HIDDEN_DIRECTIONS = 128
HIDDEN_DIRECTIONS_HUGE = 64
HIDDEN_HUGE_TRIS = 1_500_000
HIDDEN_RINGS = 5
HIDDEN_MIN_SHARE = 0.005  # less than this left out isn't worth a step
HIDDEN_RAYS_PER_CALL = 3_000_000  # rays cast together (a few hundred MB at most)
_HIDDEN: dict[tuple, dict[str, Any]] = {}  # per job: the original's file → what of it is hidden, how tangled

# Spikes up close: triangles of a cut piercing other triangles of it (tangledPct, % of its triangles, over
# the original's own). The six-view look missed them: the knight at 100k looked 2.7% off, yet clay up close
# its plates were torn. Eye-marked baked cuts sit at 0.2-3.4% over originals with none (camera, drill,
# watch, mech, scorpion, 5k-20k, crumpled or fine). The knight baked, marked by eye (2026-10-27): 20k at 30%
# spotted (black blotches where the bake met the wrong layer), 35k at 10.8% and 50k at 4.5% fine; cut plain
# to 100k at 13.2% fine as textured, 30k at 41% "crumpled, with holes" bare in Mixamo. Over this, the auto
# budget takes the next rung. One model's marks: provisional.
TANGLED_OK_PCT = 15.0


def _job_cache(in_path: Path) -> dict[str, Any]:
    stat = in_path.stat()
    return _HIDDEN.setdefault((str(in_path), stat.st_mtime_ns, stat.st_size), {})


def _tangled(V, F) -> float:
    """% of the triangles that pierce another one of the same model."""
    import numpy as np
    import pymeshlab

    ms = pymeshlab.MeshSet()
    ms.add_mesh(pymeshlab.Mesh(np.asarray(V, np.float64), np.asarray(F, np.int32)))
    ms.meshing_merge_close_vertices(threshold=pymeshlab.PercentageValue(0.0001))  # UV seams split corners
    count = ms.current_mesh().face_number()
    ms.compute_selection_by_self_intersections_per_face()
    return round(100 * ms.current_mesh().selected_face_number() / max(count, 1), 2)


def _tangled_over(in_path: Path, cut_path: Path) -> dict[str, float]:
    """How tangled a cut is, and its original (the part a cut keeps; worked out once per job)."""
    cache = _job_cache(in_path)
    if "tangled" not in cache:
        original = _shaded(in_path)
        cache["tangled"] = _tangled(*_visible(original, _hidden(in_path, original))[:2])
    return {"tangledPct": _tangled(*_shaded(cut_path)[:2]), "originalTangledPct": cache["tangled"]}


def _sphere(k: int):
    """k directions spread evenly over the sphere (a Fibonacci spiral: the same every run)."""
    import numpy as np

    i = np.arange(k) + 0.5
    phi = np.arccos(1 - 2 * i / k)
    theta = np.pi * (1 + 5**0.5) * i
    return np.stack([np.cos(theta) * np.sin(phi), np.cos(phi), np.sin(theta) * np.sin(phi)], 1)


def _seen_faces(V, F, directions: int):
    """Which faces a ray from far off meets first at their centre, from one of `directions` directions on
    their front side."""
    import igl.embree
    import numpy as np

    centre = V[F].mean(1)
    normal = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    area2 = np.linalg.norm(normal, axis=1)
    normal = normal / area2[:, None].clip(1e-30)
    span = float(np.linalg.norm(V.max(0) - V.min(0)))
    seen = area2 <= 0  # degenerate: draws as nothing, kept as it was
    # Several directions per call: each call builds its own search tree over the whole model (most of the
    # time on a 1.5M-triangle one). Seen is "from any direction", so batching changes nothing in the result.
    batch: list[tuple[Any, Any]] = []

    def cast():
        todo = np.concatenate([t for t, _ in batch])
        ray = np.concatenate([np.repeat(d[None], len(t), 0) for t, d in batch])
        hit = igl.embree.line_mesh_intersection(centre[todo] + ray * 2 * span, -ray, V, F)
        face = hit[:, 0].astype(np.int64)
        ok = face == todo
        other = ~ok & (face >= 0)  # met first on a twin of the same spot (a duplicate face): seen too
        if other.any():
            w = np.stack([1 - hit[other, 1] - hit[other, 2], hit[other, 1], hit[other, 2]], 1)
            at = (V[F[face[other]]] * w[:, :, None]).sum(1)
            ok[other] = np.linalg.norm(at - centre[todo[other]], axis=1) < span * 1e-5
        seen[todo[ok]] = True
        batch.clear()

    for d in _sphere(directions):
        todo = np.flatnonzero(~seen & (normal @ d > 0.02))
        if len(todo):
            batch.append((todo, d))
        if sum(len(t) for t, _ in batch) >= HIDDEN_RAYS_PER_CALL:
            cast()
    if batch:
        cast()
    return seen


def _hidden(in_path: Path, original=None) -> dict[str, Any] | None:
    """What of the original no one sees, worked out once per job: the points (model space) whose every face
    is hidden, written for game.mjs to leave out triangles with all three corners on them, and which faces
    of `original` (`_shaded`) stay. None for a model that moves or with next to nothing hidden."""
    import numpy as np
    from scipy import sparse

    cache = _job_cache(in_path)
    if "found" in cache:
        return cache["found"]
    found = None
    if not _animated(in_path):
        original = original or _shaded(in_path)
        V, F = original[0], np.asarray(original[1], np.int64)
        seen = _seen_faces(V, F, HIDDEN_DIRECTIONS_HUGE if len(F) > HIDDEN_HUGE_TRIS else HIDDEN_DIRECTIONS)
        # Rings over shared positions: a UV seam splits a vertex, not the surface.
        _, spot = np.unique(V, axis=0, return_inverse=True)
        spot = spot.reshape(-1)
        touches = sparse.csr_matrix((np.ones(F.size, np.float32), (np.repeat(np.arange(len(F)), 3), spot[F].reshape(-1))), shape=(len(F), spot.max() + 1))

        def grown(faces, rings):
            for _ in range(rings):
                faces = faces | ((touches @ ((touches.T @ faces.astype(np.float32)) > 0).astype(np.float32)) > 0)
            return faces

        seen = grown(seen, HIDDEN_RINGS)
        shown = (touches.T @ seen.astype(np.float32)) > 0
        stays = ~(~shown[spot[F]]).all(1)
        if (~stays).mean() >= HIDDEN_MIN_SHARE:
            first = np.zeros(spot.max() + 1, np.int64)
            first[spot[::-1]] = np.arange(len(spot))[::-1]
            fd, name = tempfile.mkstemp(suffix=".f32")
            os.close(fd)
            Path(name).write_bytes(np.asarray(V[first[~shown]], np.float32).tobytes())
            found = {"file": name, "stays": stays, "faces": int((~stays).sum())}
    cache["found"] = found
    return found


def _forget_hidden(in_path: Path) -> None:
    for key in [k for k in _HIDDEN if k[0] == str(in_path)]:
        found = _HIDDEN.pop(key).get("found")
        if found:
            Path(found["file"]).unlink(missing_ok=True)


def _visible(original, found):
    """The original without the faces game.mjs leaves out, vertices renumbered: what a cut is measured against."""
    import numpy as np

    if not found:
        return original
    V, F, N, moved = original
    F = np.asarray(F)[found["stays"]]
    used, F = np.unique(F, return_inverse=True)
    return V[used], F.reshape(-1, 3), N[used], moved


# Parts a cut to a budget lost: where an original vertex ends up over KEEP_LOST_PCT of the model's size
# from the new surface (antennas, rocket tips, thin barrels). Up to KEEP_ROUNDS times a vertex is kept at
# the worst spots and the model cut again with the same budget: fixing one spot can open another.
# Mech at 10k: an antenna gone (5.17%) -> 0.93%, vertices over 0.5% off 8714 -> 2605; scorpion 7.85 -> 1.69%.
KEEP_LOST_PCT = 0.5
KEEP_ROUNDS = 3


def _lost_detail(original, lost, target_tris: int, kept):
    """More vertices to keep where a cut lost the most: the farthest of each lost spot, spaced at least
    1% of the model's size apart and from those already kept. All of them together stay within 2% of
    the triangle budget, half of what is left going each round, so later rounds have room for what
    they find."""
    import numpy as np

    ov = original[0]
    size = float((ov.max(0) - ov.min(0)).max()) or 1.0
    order = np.argsort(-lost)
    order = order[lost[order] > KEEP_LOST_PCT][:50_000]
    room = max(20, target_tris // 50) - len(kept)
    chosen: list[int] = list(kept)
    added = 0
    for v in order:
        if added >= max(1, room // 2) or room <= 0:
            break
        if not chosen or np.linalg.norm(ov[chosen] - ov[v], axis=1).min() > 0.01 * size:
            chosen.append(int(v))
            added += 1
    return chosen[len(kept):]


# A rigged or morphing model with clips is also looked at moving: POSE_FRAMES frames through each of its
# first POSE_CLIPS clips (tools_node/pose.mjs, three.js). A cut that stands right can still break where it
# bends: CesiumMan at 2000 triangles, 0.30% off at rest, 1.70% in its walk.
POSE_FRAMES = 6
POSE_CLIPS = 3
# A model that moves is seen moving: a round that mends its frames may cost a little at rest. The fox at 300
# triangles: worst frame 5.7 -> 1.93%, the mean at rest 0.135 -> 0.177%.
MOVING_REST_SLACK = 1.35
# A near-whole cut sits so close at rest that the ratio alone forbids every mend: the fox at 500 of 576
# triangles, worst frame 1.87 -> 0.58% turned down for a rest mean of 0.002 -> 0.003%. Up to this much
# more (% of size, a third of a millimetre on a 1.8 m figure) the ratio doesn't apply.
MOVING_REST_EPS_PCT = 0.02
# How much more a cut may be off moving than at rest (bendPct, % of size) before the auto budget gives it
# more triangles. Provisional, not marked by eye yet: cuts that look right sit at 0.1-0.9 (CesiumMan 1000
# baked 0.88, BrainStem 15000 0.32, fox 450 baked 0.91), ones that don't at 1.4-2.9 (CesiumMan 1000 plain
# 1.41, fox 300 1.78, fox 150 2.89).
MOVING_BEND_OK_PCT = 1.0


def _animated(path: Path) -> bool:
    gltf = _glb_json(path)
    moving_parts = gltf.get("skins") or any(p.get("targets") for m in gltf.get("meshes", []) for p in m.get("primitives", []))
    return bool(gltf.get("animations")) and bool(moving_parts)


def _poses(path: Path):
    """Faces, the file's own vertex positions, the rest pose and every frame (world space), from pose.mjs."""
    import numpy as np

    node = shutil.which("node")
    if not node:
        raise RuntimeError("no node here to pose the model")
    fd, prefix = tempfile.mkstemp()
    os.close(fd)
    try:
        done = subprocess.run(
            [node, str(TOOLS_NODE / "pose.mjs"), str(path), prefix, str(POSE_FRAMES), str(POSE_CLIPS)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
        if done.returncode != 0 or not lines:
            raise RuntimeError(f"could not pose the model: {done.stderr.strip()[-300:]}")
        n = json.loads(lines[-1])["vertices"]
        faces = np.fromfile(prefix + ".u32", dtype=np.uint32).reshape(-1, 3)
        stack = np.fromfile(prefix + ".f32", dtype=np.float32).reshape(-1, n, 3)
        return faces, stack[0], stack[1].astype(np.float64), stack[2:].astype(np.float64)
    finally:
        for path_ in (prefix, prefix + ".u32", prefix + ".f32"):
            Path(path_).unlink(missing_ok=True)


class _Moves:
    """The original in its clips, posed once per job, to measure cuts against frame by frame."""

    def __init__(self, path: Path):
        self.faces, self.raw, self.rest, self.frames = _poses(path)
        self.size = float((self.rest.max(0) - self.rest.min(0)).max()) or 1.0

    def compare(self, cut_path: Path):
        """How far each original vertex ends up from the cut's surface in the worst of the frames (% of
        size), the mean and max of that, and bendPct: the most any vertex is further off moving than at rest,
        what bending alone breaks (a spot the cut rounds off at rest is the look's to judge, not this)."""
        import numpy as np
        import pymeshlab

        faces, _, rest, frames = _poses(cut_path)
        offset = rest.min(0) - self.rest.min(0)  # game_prep stood the cut on the floor

        def apart(mine, theirs):
            ms = pymeshlab.MeshSet()
            ms.add_mesh(pymeshlab.Mesh(mine, self.faces.astype(np.int32)))
            ms.add_mesh(pymeshlab.Mesh(theirs - offset, faces.astype(np.int32)))
            ms.get_hausdorff_distance(sampledmesh=0, targetmesh=1, samplevert=True, sampleface=False, samplenum=len(mine), savesample=True)
            saved = {ms.mesh(i).label(): ms.mesh(i).vertex_matrix() for i in range(2, ms.mesh_number())}
            sampled, nearest = saved["Hausdorff Sample Point"], saved["Hausdorff Closest Points"]
            if sampled.shape != mine.shape or not np.allclose(sampled, mine, atol=1e-6 * self.size):
                raise RuntimeError("meshlab changed the order of the posed vertices")
            return np.linalg.norm(sampled - nearest, axis=1)

        at_rest = apart(self.rest, rest)
        worst = np.zeros(len(self.rest))
        for mine, theirs in zip(self.frames, frames):
            worst = np.maximum(worst, apart(mine, theirs))
        lost = worst / self.size * 100
        bend = (worst - at_rest).max(initial=0.0) / self.size * 100
        return {"meanPct": round(float(lost.mean()), 3), "maxPct": round(float(lost.max()), 2), "bendPct": round(float(bend), 2)}, lost


def _game_mjs(in_path: Path, out_path: Path, job: dict[str, Any]) -> dict[str, Any]:
    node = shutil.which("node")
    if not node or not (TOOLS_NODE / "game.mjs").is_file():
        raise RuntimeError("no gltf-transform here to prepare the model")
    done = subprocess.run(
        [node, str(TOOLS_NODE / "game.mjs"), str(in_path), str(out_path), json.dumps(job)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if done.returncode != 0:
        raise RuntimeError(f"could not prepare the model: {done.stderr.strip()[-300:]}")
    # The result is the last line; anything a library printed before it is not ours to parse.
    lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
    if not lines:
        raise RuntimeError(f"could not prepare the model: no result ({done.stdout.strip()[-200:]})")
    result = json.loads(lines[-1])
    if result["after"]["triangles"] == 0:
        raise ValueError("could not read the model's geometry")
    return result


def _blender() -> str | None:
    """Blender for baking: BLENDER_BIN, else one on the PATH; None where there is none (the tools image)."""
    return os.getenv("BLENDER_BIN") or shutil.which("blender")


def _bake(in_path: Path, out_path: Path, shift: list[float], size: int, high: Path | None = None) -> dict[str, Any]:
    """Bake the original's look onto the cut in place: Blender (tools_blender/bake.py) makes new UVs and
    bakes base colour, roughness, metalness and a normal map carrying the shape the cut took away, then
    tools_node/graft.mjs puts them into the cut itself, so its nodes, skins, clips and morph targets stay
    as they were. Deterministic: Cycles on the CPU, fixed seed and samples (two runs, the same bytes).
    `high`: the original already unpacked, when the caller bakes several times."""
    plain = high or _unpacked(in_path)
    work = Path(tempfile.mkdtemp(prefix="bake-"))
    fd, name = tempfile.mkstemp(suffix=".glb")
    os.close(fd)
    baked = Path(name)
    try:
        done = subprocess.run(
            [_blender(), "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(TOOLS_BLENDER / "bake.py"), "--",
             str(plain), str(out_path), str(work), json.dumps({"size": size, "shift": shift, "normalOnly": not _glb_json(in_path).get("textures")})],
            capture_output=True,
            text=True,
            timeout=900,
        )
        lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
        if done.returncode != 0 or not lines:
            raise RuntimeError(f"could not bake the textures: {(done.stderr or done.stdout).strip()[-300:]}")
        info = json.loads(lines[-1])["bake"]
        grafted = subprocess.run(
            [shutil.which("node") or "node", str(TOOLS_NODE / "graft.mjs"), str(out_path), str(work), str(baked)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if grafted.returncode != 0:
            raise RuntimeError(f"could not put the baked textures on the model: {grafted.stderr.strip()[-300:]}")
        shutil.copyfile(baked, out_path)
        return info
    finally:
        shutil.rmtree(work, ignore_errors=True)
        for path in {baked, plain} - {in_path, high}:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


# The auto budget, set by eye (2026-10-26): on the six bench models a person marked the first budget that
# looks fine in a game. Below 20k every model looked crumpled however few pixels differed, so 20k is the
# floor (a model already lighter is left as it is); above it, the budget grows until no more than 5.5% of the
# picture differs at a glance (game_look.noticeablePct). That reproduces all six marks: camera, drill and
# watch 20k, mech and scorpion 35k, the sword untouched. With normal-map baking the floor should come down.
AUTO_FLOOR_TRIS = 20000
AUTO_BUDGETS = (20000, 35000, 50000, 75000, 100000, 150000, 200000)
NOTICEABLE_OK_PCT = 5.5

# What the model is for decides how big it shows on screen, so how much of it can be seen: the look is
# judged at that size (px per view side). Marked by eye on the bench models (2026-10-26):
# - "regular" is the calibration above;
# - "hero" (a close-up) got exactly the same marks as regular, so it is regular;
# - "background" (a prop far off, judged at 128 px): camera and drill fine at 5k, mech, scorpion and watch at
#   20k, watch 10k not. One threshold can't hold all six (mech 20k 8.82% fine, watch 10k 8.89% not,
#   scorpion 20k 10.97% fine), so it errs on the side of looks: 8.85%, scorpion gets 35k.
# With baking (bake: true) a normal map carries the shape the cut takes away, so the ladder starts lower.
# Baked cuts marked by eye (2026-10-26), regular: fine at camera 5k (1.13%), drill 5k (1.89%), watch 10k
# (4.67%), mech 10k (6.64%), scorpion 20k (6.32%); crumpled at watch 5k (9.18%), mech 5k (14.95%),
# scorpion 10k (13.84%). Any threshold from 6.7 to 9.1% splits them; 7% keeps to the safe side.
# Background with baking is not marked yet: its plain threshold stands in.
PURPOSES: dict[str, dict[str, Any]] = {
    "regular": {"res": 384, "floor": AUTO_FLOOR_TRIS, "okPct": NOTICEABLE_OK_PCT, "ladder": AUTO_BUDGETS,
                "bakeFloor": 5000, "bakeOkPct": 7.0, "bakeLadder": (5000, 10000, *AUTO_BUDGETS)},
    "background": {"res": 128, "floor": 5000, "okPct": 8.85, "ladder": (5000, 10000, 20000, 35000, 50000, 100000),
                   "bakeFloor": 2000, "bakeOkPct": 8.85, "bakeLadder": (2000, 5000, 10000, 20000, 35000, 50000, 100000)},
}
PURPOSES["hero"] = PURPOSES["regular"]


def _purpose(params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    name = str(params.get("purpose") or "regular")
    return (name, PURPOSES[name]) if name in PURPOSES else ("regular", PURPOSES["regular"])


# A quick cut (no second pass) a little over the threshold is looked at again as the full game_prep makes
# it: the marks were made on full cuts, and the second pass can bring a borderline cut back under.
RECHECK_MARGIN = 1.15


# A quick bake is looked at with textures at game_look.TEX (512): baking it bigger shows nothing more.
QUICK_BAKE_PX = 1024


def _quick_look(in_path: Path, budget: int, texture_size: int, res: int, bake: bool, high: Path | None = None) -> dict[str, Any]:
    """A quick cut (no second pass) looked at from the six views, baked when baking is on."""
    from studio_bridge.game_look import compare as look

    step: dict[str, Any] = {"targetTris": budget}
    for kind in ("baked",) if bake else ("plain",):
        fd, name = tempfile.mkstemp(suffix=".glb")
        os.close(fd)
        try:
            job = {"targetTris": budget, "textureSize": texture_size, **({"forBake": True} if kind == "baked" else {})}
            if found := _hidden(in_path):
                job["dropFile"] = found["file"]
            cut = _game_mjs(in_path, Path(name), job)
            if kind == "baked":
                _bake(in_path, Path(name), cut["shift"], min(texture_size, QUICK_BAKE_PX), high)
            seen = look(in_path, Path(name), cut["shift"], res=res)["noticeablePct"]
            tangles = _tangled_over(in_path, Path(name))
        finally:
            try:
                Path(name).unlink(missing_ok=True)
            except OSError:  # Windows: still held
                pass
        if "noticeablePct" not in step or seen < step["noticeablePct"]:
            step.update({"triangles": cut["after"]["triangles"], "noticeablePct": seen, "baked": kind == "baked", **tangles})
    return step


def _too_tangled(measured: dict[str, Any]) -> bool:
    return measured.get("tangledPct", 0) - measured.get("originalTangledPct", 0) > TANGLED_OK_PCT


def _auto_budget(in_path: Path, texture_size: int, ok_pct: float, purpose_name: str, purpose: dict[str, Any],
                 bake: bool = False, bake_ok_pct: float | None = None) -> dict[str, Any]:
    """The smallest budget whose cut looks like the original (noticeablePct ≤ ok_pct, or bake_ok_pct for a
    baked cut: each was marked by eye on its own), by halving the ladder: a few quick cuts (no second pass)
    looked at from the six views, a borderline one redone in full. Bigger budgets look at least as good,
    so the search can skip. Returns the pick and every budget tried, in order."""
    original = _shaded(in_path)
    faces = original[1]
    _hidden(in_path, original)  # once for every quick cut
    original = None
    floor, ladder = (purpose["bakeFloor"], purpose["bakeLadder"]) if bake else (purpose["floor"], purpose["ladder"])
    if len(faces) <= floor:  # already light: nothing to cut
        return {"picked": len(faces), "okPct": ok_pct, "tried": []}
    ladder = [b for b in ladder if b < len(faces)] + [len(faces)]
    high = _unpacked(in_path) if bake else None  # unpacked once for every quick bake
    try:
        return _search(in_path, texture_size, ok_pct, purpose_name, purpose, bake, bake_ok_pct, ladder, high)
    finally:
        if high is not None and high != in_path:
            try:
                high.unlink(missing_ok=True)
            except OSError:
                pass


def _search(in_path: Path, texture_size: int, ok_pct: float, purpose_name: str, purpose: dict[str, Any],
            bake: bool, bake_ok_pct: float | None, ladder: list[int], high: Path | None) -> dict[str, Any]:
    tried: list[dict[str, Any]] = []
    lo, hi = 0, len(ladder) - 1  # ladder[hi] is the whole model: it always passes
    while lo < hi:
        mid = (lo + hi) // 2
        step = _quick_look(in_path, ladder[mid], texture_size, purpose["res"], bake, high)
        seen = step["noticeablePct"]
        limit = bake_ok_pct if step.get("baked") and bake_ok_pct else ok_pct
        if limit < seen <= limit * RECHECK_MARGIN:
            fd, name = tempfile.mkstemp(suffix=".glb")
            os.close(fd)
            full: dict[str, Any] = {}
            try:
                full = _best_of(in_path, Path(name), {"targetTris": ladder[mid], "textureSize": texture_size, "purpose": purpose_name, "bake": bake})
            finally:
                for extra in [name, *(full.get("extraFiles") or {}).values()]:
                    try:
                        Path(extra).unlink(missing_ok=True)
                    except OSError:
                        pass
            seen = step["fullNoticeablePct"] = full["after"]["look"]["noticeablePct"]
            limit = bake_ok_pct if full["after"].get("bake", {}).get("used") and bake_ok_pct else ok_pct
            step.update({k: full["after"][k] for k in ("tangledPct", "originalTangledPct") if k in full["after"]})
        tried.append(step)
        if seen <= limit and not _too_tangled(step):
            hi = mid
        else:
            lo = mid + 1
    return {"picked": ladder[lo], "okPct": ok_pct, **({"bakeOkPct": bake_ok_pct} if bake else {}), "tried": tried}


# A model this light is cut both ways, plain and baked, and the closer kept: it takes seconds, and on
# tiny ones baking can lose (RiggedFigure, 256 triangles cut to 128: 27% noticeable plain, 40% baked).
BOTH_UNDER_TRIS = 100_000


def _best_of(in_path: Path, out_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    """With bake: the cut by shape alone, baked. Made side by side with the plain cut at first, the baked
    one was closer to the original at every budget on all six bench models once its UVs were packed
    tightly (16 of 16: camera 5k 3.44 -> 1.13%, drill 20k 0.45 -> 0.28%, mech 20k 12.98 -> 2.41%), so on
    a heavy model the plain one is made only when baking can't be done or fails; a light one gets both."""
    plain = {k: v for k, v in params.items() if k not in ("bake", "forBake")}
    if not params.get("bake"):
        return _game_prep(in_path, out_path, plain)
    triangles = _triangles_in_file(in_path)
    why_not = ("no Blender here" if not _blender()
               else "nothing was cut" if triangles <= int(params.get("targetTris") or 20000)
               else None)
    if not why_not:
        fd, name = tempfile.mkstemp(suffix=".glb")
        os.close(fd)
        baked_path = Path(name)
        try:
            baked = _game_prep(in_path, baked_path, {**plain, "forBake": True})
            if triangles <= BOTH_UNDER_TRIS:
                first = _game_prep(in_path, out_path, plain)
                seen = [r["after"].get("look", {}).get("noticeablePct", math.inf) for r in (first, baked)]
                # Alike to the eye (CesiumMan at 2000 judged at 128 px: 0% both), the one that bends better.
                bend = [(r["after"].get("moving") or {}).get("bendPct", 0) for r in (first, baked)]
                if (seen[0], bend[0]) <= (seen[1], bend[1]):
                    for extra in (baked.get("extraFiles") or {}).values():
                        Path(extra).unlink(missing_ok=True)
                    first["after"]["bake"] = {"used": False, "noticeablePct": {"plain": seen[0], "baked": seen[1]}}
                    first["steps"].append(f"kept the plain cut: it looks closer to the original ({seen[0]:g}% of the picture differs, baked {seen[1]:g}%)")
                    return first
                for extra in (first.get("extraFiles") or {}).values():
                    Path(extra).unlink(missing_ok=True)
                baked["after"]["bake"] = {"used": True, "noticeablePct": {"plain": seen[0], "baked": seen[1]}}
            else:
                baked["after"]["bake"] = {"used": True}
            shutil.copyfile(baked_path, out_path)
            return baked
        except RuntimeError as exc:
            why_not = str(exc)[:160]
        finally:
            try:
                baked_path.unlink(missing_ok=True)
            except OSError:  # Windows: trimesh may still hold it
                pass
    report = _game_prep(in_path, out_path, plain)
    report["after"]["bake"] = {"used": False, "why": why_not}
    report["steps"].append(f"baking skipped: {why_not}")
    return report


def game_prep(in_path: Path, out_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    """With autoBudget, first the smallest budget that doesn't look noticeably different, then the cut.
    With bake, each cut is also made baked, and the one that looks closer is kept."""
    try:
        return _game_prep_job(in_path, out_path, params)
    finally:
        _forget_hidden(in_path)  # what's hidden was worked out once for every cut of this job


def _game_prep_job(in_path: Path, out_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    if not params.get("autoBudget"):
        return _best_of(in_path, out_path, params)
    purpose_name, purpose = _purpose(params)
    ok_pct = float(params.get("maxNoticeablePct") or purpose["okPct"])
    texture_size = int(params.get("textureSize") or 2048)
    bake = bool(params.get("bake")) and _blender() is not None
    bake_ok_pct = float(params.get("maxNoticeablePct") or purpose["bakeOkPct"])
    auto = _auto_budget(in_path, texture_size, ok_pct, purpose_name, purpose, bake=bake, bake_ok_pct=bake_ok_pct)
    auto["purpose"] = purpose_name
    plain = {k: v for k, v in params.items() if k not in ("autoBudget", "maxErrorPct", "maxNoticeablePct")}
    report = _best_of(in_path, out_path, {**plain, "targetTris": auto["picked"]})
    # The look is judged standing still. A model that moves also has to bend right: while it breaks more than
    # MOVING_BEND_OK_PCT, the next rung up is cut (the whole model always passes). Not a halving search:
    # bending isn't steady in the budget (the fox broke worse at 450 triangles than at 300).
    looked = auto["picked"]
    whole = _triangles_in_file(in_path)
    ladder = purpose["bakeLadder" if bake else "ladder"]
    bent: list[dict[str, Any]] = []
    while (report["after"].get("moving") or {}).get("bendPct", 0) > MOVING_BEND_OK_PCT and auto["picked"] < whole:
        bent.append({"targetTris": auto["picked"], "bendPct": report["after"]["moving"]["bendPct"]})
        for extra in (report.get("extraFiles") or {}).values():
            Path(extra).unlink(missing_ok=True)
        auto["picked"] = next((b for b in ladder if auto["picked"] < b < whole), whole)
        report = _best_of(in_path, out_path, {**plain, "targetTris": auto["picked"]})
    if bent:
        auto["bentAt"] = bent
    report["after"]["autoBudget"] = auto
    report["steps"].insert(1, f"budget picked: {auto['picked']} triangles, the fewest that don't look noticeably different"
                           + (f" and bend right in motion ({looked} looked right but broke {bent[0]['bendPct']:g}% where it bends)" if bent else ""))
    return report


def _game_prep(in_path: Path, out_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    # trimesh would flatten the model into one mesh and drop its textures; a game needs both,
    # so the whole job runs in gltf-transform, which also unpacks Draco / meshopt on the way in.
    # trimesh only reads both files afterwards, to measure how much the shape and shading changed.
    import numpy as np

    job: dict[str, Any] = {
        "targetTris": int(params.get("targetTris") or 20000),
        "textureSize": int(params.get("textureSize") or 2048),
    }
    if params.get("maxErrorPct"):
        job["maxErrorPct"] = float(params["maxErrorPct"])
    if params.get("forBake"):
        job["forBake"] = True
    if params.get("regularize") in ("light", "full"):
        job["regularize"] = params["regularize"]
    # What no one sees is found first: the cut leaves it out, and the cut is measured against the rest.
    # Then the cut runs in node while this process gets the original ready to measure against; a huge
    # model is done one after the other, so the two copies of it don't sit in memory at once.
    from concurrent.futures import ThreadPoolExecutor

    original = _shaded(in_path)
    found = _hidden(in_path, original)
    if found:
        job["dropFile"] = found["file"]
    if _triangles_in_file(in_path) > OVERLAP_MAX_TRIS:
        original = None
        result = _game_mjs(in_path, out_path, job)
        original = _visible(_shaded(in_path), found)
        reference = _Reference(original)
    else:
        original = _visible(original, found)
        with ThreadPoolExecutor(max_workers=1) as pool:
            cutting = pool.submit(_game_mjs, in_path, out_path, job)
            reference = _Reference(original)
            result = cutting.result()
    to_budget = "maxErrorPct" not in job
    deviation, lost = reference.compare(out_path, result["shift"], find_lost=to_budget and not original[3])
    steps = list(result["steps"])

    # To a budget a whole part can go (the error limit is off): find what went missing, keep a vertex
    # there, cut again, all in this one run. A round stays only if the shape came closer: the worst
    # spot smaller or the whole closer, and the whole no more than 5% further off than the first cut.
    first_mean, kept, tried = deviation["meanPct"], [], 0
    while lost is not None and tried < KEEP_ROUNDS and (lost > KEEP_LOST_PCT).any():
        more = _lost_detail(original, lost, job["targetTris"], kept)
        if not more:
            break
        tried += 1
        fd, keep_name = tempfile.mkstemp(suffix=".f32")
        os.close(fd)
        fd, second_name = tempfile.mkstemp(suffix=".glb")
        os.close(fd)
        keep_path, second_path = Path(keep_name), Path(second_name)
        try:
            keep_path.write_bytes(np.asarray(original[0][kept + more], dtype=np.float32).tobytes())
            second = _game_mjs(in_path, second_path, {**job, "keepFile": str(keep_path)})
            again, again_lost = reference.compare(second_path, second["shift"], find_lost=True)
            closer = again["maxPct"] < 0.97 * deviation["maxPct"] or again["meanPct"] < 0.97 * deviation["meanPct"]
            if closer and again["maxPct"] <= deviation["maxPct"] and again["meanPct"] <= 1.05 * first_mean:
                shutil.copyfile(second_path, out_path)
                kept += more
                result, deviation, lost = second, again, again_lost
            else:
                break
        finally:
            keep_path.unlink(missing_ok=True)
            try:
                second_path.unlink(missing_ok=True)
            except OSError:  # Windows: trimesh may still hold it
                pass
    steps = list(result["steps"])
    if kept:
        steps.append(f"lost details found and kept: {len(kept)} spots in {tried} rounds, worst spot now {deviation['maxPct']:g}% off")

    # The same for a model that moves, over the frames of its clips: where a cut breaks as it bends (a knee,
    # an elbow), keep vertices there too. Rounds as above, the frames deciding, the shape at rest no more
    # than MOVING_REST_SLACK further off on the whole.
    moving = None
    if to_budget and _animated(in_path):
        moves = _Moves(in_path)
        moving, moving_lost = moves.compare(out_path)
        rest_keep = original[0][kept] if kept else np.zeros((0, 3))
        # Each round adds points where the last cut tried broke worst, kept or not: a round can mend the
        # frames on the whole yet open a new worst spot (the plain fox at 300: mean 0.428 -> 0.366%, worst
        # 3.06 -> 3.73%), and the next one mends that. A cut is taken only if better than the best so far.
        kept_moving, trying, trial_lost, tried_moving = [], [], moving_lost, 0
        while tried_moving < KEEP_ROUNDS and (trial_lost > KEEP_LOST_PCT).any():
            more = _lost_detail((moves.rest,), trial_lost, job["targetTris"], trying)
            if not more:
                break
            tried_moving += 1
            trying = trying + more
            fd, keep_name = tempfile.mkstemp(suffix=".f32")
            os.close(fd)
            fd, second_name = tempfile.mkstemp(suffix=".glb")
            os.close(fd)
            keep_path, second_path = Path(keep_name), Path(second_name)
            try:
                points = np.vstack([rest_keep, moves.raw[trying]])
                keep_path.write_bytes(np.asarray(points, dtype=np.float32).tobytes())
                second = _game_mjs(in_path, second_path, {**job, "keepFile": str(keep_path)})
                again_moving, trial_lost = moves.compare(second_path)
                again, _ = reference.compare(second_path, second["shift"])
                closer = again_moving["maxPct"] < 0.97 * moving["maxPct"] or again_moving["meanPct"] < 0.97 * moving["meanPct"]
                rest_ok = again["meanPct"] <= max(MOVING_REST_SLACK * first_mean, first_mean + MOVING_REST_EPS_PCT)
                if closer and again_moving["maxPct"] <= moving["maxPct"] and rest_ok:
                    shutil.copyfile(second_path, out_path)
                    kept_moving = trying
                    result, deviation, moving = second, again, again_moving
                    steps = list(result["steps"])
            finally:
                keep_path.unlink(missing_ok=True)
                try:
                    second_path.unlink(missing_ok=True)
                except OSError:  # Windows: trimesh may still hold it
                    pass
        if kept_moving:
            if kept:  # the steps came back with the new cut
                steps.append(f"lost details found and kept: {len(kept)} spots, worst spot now {deviation['maxPct']:g}% off")
            steps.append(f"breaks in motion found and kept: {len(kept_moving)} spots in {tried_moving} rounds, worst frame now {moving['maxPct']:g}% off")
        if moving["bendPct"] > MOVING_BEND_OK_PCT and not params.get("maxErrorPct"):
            steps.append(f"still breaks where it bends ({moving['bendPct']:g}% of its size further off moving than at rest): "
                         "the auto budget gives a moving model the triangles it needs")

    if job.get("forBake"):
        baked = _bake(in_path, out_path, result["shift"], job["textureSize"])
        steps.append(f"normal map baked from the original onto new UVs, the model's own colours kept ({baked['seconds']:g} s)" if baked.get("normalOnly")
                     else f"textures baked from the original onto new UVs: colour, roughness, metalness, normal map ({baked['seconds']:g} s)")
        result["after"] = {**result["after"], "textures": len(_glb_json(out_path).get("textures", [])), "textureMaxPx": baked["size"], "fileMb": round(out_path.stat().st_size / 1048576, 2)}

    after = {
        **result["after"],
        "targetTris": job["targetTris"],
        "budgetReached": result["budgetReached"],
        "deviation": deviation,
        **({"moving": moving} if moving else {}),
    }
    if "maxErrorPct" in job:
        after["maxErrorPct"] = job["maxErrorPct"]
    if result["specks"]["pieces"]:
        after["specksRemoved"] = result["specks"]
    report: dict[str, Any] = {"operation": "game_prep", "steps": steps, "before": result["before"], "after": after}

    # How it looks next to the original from six fixed views, and the picture of it for the page. The
    # shape measuring is done: let its copy of the original go first, or a huge model sits in memory twice.
    import gc

    from studio_bridge.game_look import compare as look

    reference = original = lost = None  # noqa: F841
    gc.collect()

    fd, preview_name = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        purpose_name, purpose = _purpose(params)
        after["look"] = {**look(in_path, out_path, result["shift"], Path(preview_name), res=purpose["res"]), "purpose": purpose_name}
        report["extraFiles"] = {"preview.png": preview_name}
        if not params.get("maxErrorPct"):
            if after["look"]["noticeablePct"] > purpose["bakeOkPct" if job.get("forBake") else "okPct"]:
                steps.append(
                    f"looks noticeably different from the original ({after['look']['noticeablePct']:g}% of the picture): "
                    "the auto budget picks the fewest triangles that don't"
                )
            # The asked budget, not the count: a 20k cut can land a few triangles short of 20000.
            elif after["targetTris"] < (floor := purpose["bakeFloor" if job.get("forBake") else "floor"]) < result["before"]["triangles"]:
                steps.append(f"under {floor // 1000}k triangles detailed models tend to look crumpled at this size")
    except Exception as exc:  # a report extra: never worth failing the tool for
        Path(preview_name).unlink(missing_ok=True)
        steps.append(f"look not measured: {str(exc)[:120]}")
    try:
        after.update(_tangled_over(in_path, out_path))
        if _too_tangled(after) and not params.get("maxErrorPct"):
            steps.append(f"pierces itself in {after['tangledPct']:g}% of its triangles, the original in {after['originalTangledPct']:g}%: "
                         "spikes and dents up close; the auto budget picks more triangles")
    except Exception as exc:  # as above
        steps.append(f"spikes not measured: {str(exc)[:120]}")
    return report


OPERATIONS: dict[str, Callable[[Path, Path, dict[str, Any]], dict[str, Any]]] = {
    "print_prep": print_prep,
    "game_prep": game_prep,
}


def extra_key(output_key: str, name: str) -> str:
    """Where an extra file goes: next to the main one, tools/abc.glb -> tools/abc-alternate.glb; a name with
    its own extension keeps it, tools/abc.glb + preview.png -> tools/abc-preview.png."""
    ext = "" if "." in name else ".glb"
    return f"{output_key[:-4]}-{name}{ext}" if output_key.endswith(".glb") else f"{output_key}-{name}"


def run_operation(operation: str, in_path: Path, params: dict[str, Any]) -> tuple[Path, dict[str, Any], dict[str, Path]]:
    """Run one tool; returns the output GLB path, its report, and any extra files by name (the caller
    uploads them next to the main one and deletes them)."""
    fn = OPERATIONS.get(operation)
    if fn is None:
        raise ValueError(f"unknown operation: {operation}")
    fd, name = tempfile.mkstemp(suffix=".glb")
    os.close(fd)  # the tool writes it by name; an open handle would lock it on Windows
    out_path = Path(name)
    report = fn(in_path, out_path, params or {})
    extra = {name: Path(p) for name, p in (report.pop("extraFiles", None) or {}).items()}
    return out_path, report, extra
