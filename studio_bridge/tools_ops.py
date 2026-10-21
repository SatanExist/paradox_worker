"""Tools on a finished model — the work itself, shared by the RunPod tools worker and local runs.

Each tool takes a GLB on disk and writes a new GLB plus a report (checks before and after).
No GPU and no network here: the caller downloads the input and uploads the result.

Compressed GLBs (Draco, meshopt, quantized — what Tripo, Meshy and our own showcase ship) are
unpacked first with gltf-transform (tools_node/decode.mjs): trimesh would read them as zeros.

  print_prep  weld, drop broken faces, fix normals, close holes (pymeshlab when present),
              optionally scale to a height in mm, stand the model on the plate (Y up, base at 0)
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
    out = Path(tempfile.mkstemp(suffix=".glb")[1])
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

    if not mesh.is_watertight:
        mesh, used = _close_holes_pymeshlab(mesh, int(params.get("maxHoleSize") or 5000))
        if used:
            steps.append("holes closed (pymeshlab)")
        trimesh.repair.fill_holes(mesh)
    trimesh.repair.fix_normals(mesh)
    steps.append("normals fixed")

    height_mm = params.get("heightMm")
    if height_mm:
        current = float(mesh.extents[1])
        if current > 0:
            mesh.apply_scale(float(height_mm) / 1000.0 / current)
            steps.append(f"scaled to {float(height_mm):g} mm")

    # On the plate: centred on X/Z, lowest point at Y=0.
    lo, hi = mesh.bounds
    mesh.apply_translation([-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2])
    steps.append("placed on plate")

    # One plain material: a print has no texture, and a clay look shows the shape best.
    mesh.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(
            baseColorFactor=np.array([200, 196, 188, 255], dtype=np.uint8),
            metallicFactor=0.0,
            roughnessFactor=0.9,
        )
    )
    mesh.export(out_path)
    return {"operation": "print_prep", "steps": steps, "before": before, "after": _print_checks(mesh)}


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


def game_prep(in_path: Path, out_path: Path, params: dict[str, Any]) -> dict[str, Any]:
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
    return {"operation": "game_prep", "steps": steps, "before": result["before"], "after": after}


OPERATIONS: dict[str, Callable[[Path, Path, dict[str, Any]], dict[str, Any]]] = {
    "print_prep": print_prep,
    "game_prep": game_prep,
}


def run_operation(operation: str, in_path: Path, params: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """Run one tool; returns the output GLB path and its report."""
    fn = OPERATIONS.get(operation)
    if fn is None:
        raise ValueError(f"unknown operation: {operation}")
    out_path = Path(tempfile.mkstemp(suffix=".glb")[1])
    report = fn(in_path, out_path, params or {})
    return out_path, report
