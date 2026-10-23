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
    import time

    import numpy as np
    import trimesh

    t0 = time.time()
    timings: dict[str, float] = {}
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
    timings["load"] = round(time.time() - t0, 1)
    t = time.time()

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
    timings["solid"] = round(time.time() - t, 1)
    t = time.time()

    # Pieces hanging in mid-air: the user chooses, the default is to remove them. Both files are made, so
    # the choice is instant; the main one follows params["floating"], the other goes out as "alternate".
    from studio_bridge.print_solid import split_floating

    try:
        body, pieces, about = split_floating(mesh, mm_per_unit)
    except Exception as exc:  # a report extra: never worth failing the print for
        print(f"floating pieces not checked: {exc}")
        body, pieces, about = mesh, None, []
    keep = str(params.get("floating") or "remove") == "keep"
    timings["floating"] = round(time.time() - t, 1)
    t = time.time()

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
    timings["export"] = round(time.time() - t, 1)
    report["timings"] = timings
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


OPERATIONS: dict[str, Callable[[Path, Path, dict[str, Any]], dict[str, Any]]] = {
    "print_prep": print_prep,
}


def extra_key(output_key: str, name: str) -> str:
    """Where an extra file goes: next to the main one, tools/abc.glb -> tools/abc-alternate.glb."""
    return f"{output_key[:-4]}-{name}.glb" if output_key.endswith(".glb") else f"{output_key}-{name}"


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
