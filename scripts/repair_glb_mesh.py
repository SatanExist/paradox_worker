"""Repair GLB mesh (holes, non-manifold) before MV-Adapter texture (Track A / W2b).

Uses trimesh; optional pymeshlab if installed for stronger repair.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path


def _load_glb_mesh(path: Path):
    import trimesh

    scene = trimesh.load(path, force="mesh", process=False)
    if isinstance(scene, trimesh.Scene):
        geoms = [g for g in scene.geometry.values() if isinstance(g, trimesh.Trimesh)]
        if not geoms:
            raise ValueError(f"No meshes in GLB: {path}")
        mesh = trimesh.util.concatenate(geoms) if len(geoms) > 1 else geoms[0]
    else:
        mesh = scene
    return mesh


def _repair_trimesh(mesh):
    import trimesh

    mesh = mesh.copy()
    # Newer trimesh dropped remove_*_faces helpers; prefer update_faces masks.
    if hasattr(mesh, "remove_infinite_values"):
        mesh.remove_infinite_values()
    if hasattr(mesh, "nondegenerate_faces"):
        mesh.update_faces(mesh.nondegenerate_faces())
    elif hasattr(mesh, "remove_degenerate_faces"):
        mesh.remove_degenerate_faces()
    if hasattr(mesh, "unique_faces"):
        mesh.update_faces(mesh.unique_faces())
    elif hasattr(mesh, "remove_duplicate_faces"):
        mesh.remove_duplicate_faces()
    if hasattr(mesh, "remove_unreferenced_vertices"):
        mesh.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(mesh)
    trimesh.repair.fix_winding(mesh)
    try:
        trimesh.repair.fill_holes(mesh)
    except Exception as exc:
        print(f"WARN: trimesh fill_holes: {exc}", file=sys.stderr)
    return mesh


def _repair_pymeshlab(in_path: Path, out_path: Path) -> bool:
    try:
        import pymeshlab as pml
    except ImportError:
        return False

    ms = pml.MeshSet()
    ms.load_new_mesh(str(in_path))
    ms.meshing_remove_duplicate_faces()
    ms.meshing_remove_unreferenced_vertices()
    ms.meshing_repair_non_manifold_edges()
    ms.meshing_close_holes(maxholesize=500)
    ms.save_current_mesh(str(out_path))
    return True


def _export_glb_trimesh(mesh, out_path: Path, src_path: Path) -> None:
    """Export mesh; preserve glTF materials from source when possible."""
    import trimesh

    data = src_path.read_bytes()
    off = 12
    json_len = struct.unpack_from("<I", data, off)[0]
    off += 8
    gltf = json.loads(data[off : off + json_len])

    material = None
    if gltf.get("materials"):
        # Keep first material via empty texture visual
        mat = gltf["materials"][0]
        pbr = mat.get("pbrMetallicRoughness", {})
        factor = pbr.get("baseColorFactor", [0.7, 0.7, 0.7, 1.0])
        import numpy as np

        material = trimesh.visual.material.PBRMaterial(
            baseColorFactor=(np.array(factor) * 255).astype(np.uint8),
            metallicFactor=pbr.get("metallicFactor", 0.0),
            roughnessFactor=pbr.get("roughnessFactor", 0.85),
        )

    if material is not None:
        mesh.visual = trimesh.visual.TextureVisuals(material=material)
    mesh.export(out_path)


def main() -> int:
    p = argparse.ArgumentParser(description="Repair GLB mesh for texture pipeline")
    p.add_argument("input", type=Path, help="Input .glb")
    p.add_argument("-o", "--output", type=Path, help="Output .glb (default: *_repaired.glb)")
    p.add_argument("--pymeshlab", action="store_true", help="Prefer pymeshlab repair")
    args = p.parse_args()

    in_path = args.input.resolve()
    if not in_path.is_file():
        print(f"ERROR: not found: {in_path}", file=sys.stderr)
        return 1

    out_path = args.output or in_path.with_name(in_path.stem + "_repaired.glb")

    if args.pymeshlab and _repair_pymeshlab(in_path, out_path):
        print(f"pymeshlab repair -> {out_path} ({out_path.stat().st_size} bytes)")
        return 0

    mesh = _load_glb_mesh(in_path)
    print(f"input: {len(mesh.vertices)} verts, {len(mesh.faces)} faces")
    mesh = _repair_trimesh(mesh)
    print(f"repaired: {len(mesh.vertices)} verts, {len(mesh.faces)} faces")
    _export_glb_trimesh(mesh, out_path, in_path)
    print(f"trimesh repair -> {out_path} ({out_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
