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
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from studio_bridge.mesh_repair import load_glb_mesh, mesh_stats


TOOLS_NODE = Path(os.getenv("TOOLS_NODE_DIR", Path(__file__).resolve().parents[1] / "tools_node"))
PACKED = {"KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_mesh_quantization"}
DEFAULT_PRINT_HEIGHT_MM = 120.0
SOLID_STEPS = {
    "repair": "made one closed solid (holes patched)",
    "solidify": "made one closed solid (hollow skin filled)",
    "wrap": "made one closed solid (wrapped 0.5 mm)",
}


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
    verts, faces, normals, offset, moved = [], [], [], 0, False
    for node in scene.graph.nodes_geometry:
        matrix, name = scene.graph[node]
        geom = scene.geometry.get(name)
        if not isinstance(geom, trimesh.Trimesh) or len(geom.faces) == 0:
            continue
        moved = moved or not np.allclose(matrix, np.eye(4))
        turned = np.asarray(geom.vertex_normals) @ matrix[:3, :3].T
        normals.append(turned / np.linalg.norm(turned, axis=1, keepdims=True).clip(1e-12))
        verts.append(trimesh.transform_points(geom.vertices, matrix))
        faces.append(np.asarray(geom.faces) + offset)
        offset += len(geom.vertices)
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


def _lost_detail(original, lost, target_tris: int):
    """A few vertices to keep where a cut lost the most: the farthest of each lost spot.

    Spots are where an original vertex ended up over 1% of the model's size from the new
    surface — antennas, barrels, edges cut off. One vertex per spot, spaced at least 1% apart,
    at most 2% of the triangle budget, so the budget is still met.
    """
    import numpy as np

    ov = original[0]
    size = float((ov.max(0) - ov.min(0)).max()) or 1.0
    order = np.argsort(-lost)
    order = order[lost[order] > 1.0][:20_000]
    cap = max(20, target_tris // 50)
    chosen: list[int] = []
    for v in order:
        if len(chosen) >= cap:
            break
        if not chosen or np.linalg.norm(ov[chosen] - ov[v], axis=1).min() > 0.01 * size:
            chosen.append(int(v))
    return ov[chosen]


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
    result = json.loads(done.stdout)
    if result["after"]["triangles"] == 0:
        raise ValueError("could not read the model's geometry")
    return result


# The budgets the auto budget chooses from, and the share of the picture that may differ at a glance
# (game_look.noticeablePct) for a cut to count as not noticeable. The threshold is set by eye on the bench
# models: a person marks, per model, the first budget that looks fine; see scripts/game_prep_bench.py.
AUTO_BUDGETS = (2000, 5000, 10000, 20000, 35000, 50000, 100000, 200000)
NOTICEABLE_OK_PCT = 2.0


def _auto_budget(in_path: Path, texture_size: int, ok_pct: float) -> dict[str, Any]:
    """The smallest budget whose cut looks like the original (noticeablePct ≤ ok_pct), by halving the
    ladder: a few quick cuts (no second pass) looked at from the six views. Bigger budgets look at least
    as good, so the search can skip. Returns the pick and every budget tried, in order."""
    from studio_bridge.game_look import compare as look

    faces = _shaded(in_path)[1]
    ladder = [b for b in AUTO_BUDGETS if b < len(faces)] + [len(faces)]
    tried: list[dict[str, Any]] = []
    lo, hi = 0, len(ladder) - 1  # ladder[hi] is the whole model: it always passes
    while lo < hi:
        mid = (lo + hi) // 2
        fd, name = tempfile.mkstemp(suffix=".glb")
        os.close(fd)
        try:
            cut = _game_mjs(in_path, Path(name), {"targetTris": ladder[mid], "textureSize": texture_size})
            seen = look(in_path, Path(name), cut["shift"])
        finally:
            try:
                Path(name).unlink(missing_ok=True)
            except OSError:  # Windows: still held
                pass
        tried.append({"targetTris": ladder[mid], "triangles": cut["after"]["triangles"], "noticeablePct": seen["noticeablePct"]})
        if seen["noticeablePct"] <= ok_pct:
            hi = mid
        else:
            lo = mid + 1
    return {"picked": ladder[lo], "okPct": ok_pct, "tried": tried}


def game_prep(in_path: Path, out_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    """With autoBudget, first the smallest budget that doesn't look noticeably different, then the cut."""
    if not params.get("autoBudget"):
        return _game_prep(in_path, out_path, params)
    ok_pct = float(params.get("maxNoticeablePct") or NOTICEABLE_OK_PCT)
    texture_size = int(params.get("textureSize") or 2048)
    auto = _auto_budget(in_path, texture_size, ok_pct)
    plain = {k: v for k, v in params.items() if k not in ("autoBudget", "maxErrorPct", "maxNoticeablePct")}
    report = _game_prep(in_path, out_path, {**plain, "targetTris": auto["picked"]})
    report["after"]["autoBudget"] = auto
    report["steps"].insert(1, f"budget picked: {auto['picked']} triangles, the fewest that don't look noticeably different")
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
    # The cut runs in node while this process gets the original ready to measure against.
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        cutting = pool.submit(_game_mjs, in_path, out_path, job)
        original = _shaded(in_path)
        reference = _Reference(original)
        result = cutting.result()
    to_budget = "maxErrorPct" not in job
    deviation, lost = reference.compare(out_path, result["shift"], find_lost=to_budget and not original[3])
    steps = list(result["steps"])

    # To a budget a whole part can go (the error limit is off). When the worst spot stands out,
    # keep a vertex at each place that went missing and cut again; take it only if it measures
    # better: the worst spot clearly smaller, the shape on the whole no worse.
    if lost is not None and deviation["maxPct"] > max(1.0, 4 * deviation["meanPct"]):
        keep = _lost_detail(original, lost, job["targetTris"])
        if len(keep):
            fd, keep_name = tempfile.mkstemp(suffix=".f32")
            os.close(fd)
            fd, second_name = tempfile.mkstemp(suffix=".glb")
            os.close(fd)
            keep_path, second_path = Path(keep_name), Path(second_name)
            try:
                keep_path.write_bytes(np.asarray(keep, dtype=np.float32).tobytes())
                second = _game_mjs(in_path, second_path, {**job, "keepFile": str(keep_path)})
                again, _ = reference.compare(second_path, second["shift"])
                if again["maxPct"] < 0.9 * deviation["maxPct"] and again["meanPct"] <= 1.15 * deviation["meanPct"]:
                    shutil.copyfile(second_path, out_path)
                    result, deviation, steps = second, again, list(second["steps"])
                else:
                    steps.append(f"tried keeping {len(keep)} lost spots: no better, first cut kept")
            finally:
                keep_path.unlink(missing_ok=True)
                try:
                    second_path.unlink(missing_ok=True)
                except OSError:  # Windows: trimesh may still hold it
                    pass

    after = {
        **result["after"],
        "targetTris": job["targetTris"],
        "budgetReached": result["budgetReached"],
        "deviation": deviation,
    }
    if "maxErrorPct" in job:
        after["maxErrorPct"] = job["maxErrorPct"]
    if result["specks"]["pieces"]:
        after["specksRemoved"] = result["specks"]
    report: dict[str, Any] = {"operation": "game_prep", "steps": steps, "before": result["before"], "after": after}

    # How it looks next to the original from six fixed views, and the picture of it for the page.
    from studio_bridge.game_look import compare as look

    fd, preview_name = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        after["look"] = look(in_path, out_path, result["shift"], Path(preview_name))
        report["extraFiles"] = {"preview.png": preview_name}
        if after["look"]["noticeablePct"] > NOTICEABLE_OK_PCT and not params.get("maxErrorPct"):
            steps.append(
                f"looks noticeably different from the original ({after['look']['noticeablePct']:g}% of the picture): "
                "the auto budget picks the fewest triangles that don't"
            )
    except Exception as exc:  # a report extra: never worth failing the tool for
        Path(preview_name).unlink(missing_ok=True)
        steps.append(f"look not measured: {str(exc)[:120]}")
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
