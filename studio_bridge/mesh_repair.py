"""Post-export mesh repair for mid-prop holes gate (G1/G2).

Runs on CPU; no TRELLIS model load. Used by worker repair_mode jobs and local scripts.
"""

from __future__ import annotations

import tempfile
import urllib.request
from pathlib import Path


def _boundary_edges(mesh) -> int:
    import trimesh

    return int(
        len(mesh.edges[trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1)])
    )


def load_glb_mesh(path: Path):
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


def mesh_stats(mesh) -> dict:
    return {
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "watertight": bool(mesh.is_watertight),
        "boundary_edges": _boundary_edges(mesh),
    }


def download_mesh(url: str) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".glb")
    with urllib.request.urlopen(req) as resp:
        tmp.write(resp.read())
    tmp.close()
    return Path(tmp.name)


def repair_voxel(
    mesh,
    *,
    resolution: int = 256,
    pitch: float = 0.0,
):
    """Voxel fill + marching cubes — closes thin see-through gaps (G1b)."""
    import numpy as np
    import trimesh

    longest = float(np.max(mesh.extents))
    voxel_pitch = pitch if pitch > 0 else longest / float(resolution)
    vox = mesh.voxelized(voxel_pitch)
    try:
        vox = vox.fill()
    except Exception as exc:
        print(f"WARN: voxel fill skipped: {exc}")
    solid = vox.marching_cubes
    solid.merge_vertices()
    if hasattr(solid, "remove_unreferenced_vertices"):
        solid.remove_unreferenced_vertices()
    solid.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(
            baseColorFactor=np.array([180, 180, 180, 255], dtype=np.uint8),
            metallicFactor=0.0,
            roughnessFactor=0.85,
        )
    )
    return solid, {"resolution": resolution, "pitch": voxel_pitch}


def repair_pymeshlab(in_path: Path, out_path: Path, *, max_hole_size: int = 5000) -> Path:
    import pymeshlab as pml

    ms = pml.MeshSet()
    ms.load_new_mesh(str(in_path))
    ms.meshing_remove_duplicate_faces()
    ms.meshing_remove_unreferenced_vertices()
    try:
        ms.meshing_repair_non_manifold_edges()
    except Exception as exc:
        print(f"WARN: repair_non_manifold_edges: {exc}")
    try:
        ms.meshing_repair_non_manifold_vertices()
    except Exception:
        pass
    ms.meshing_close_holes(maxholesize=int(max_hole_size))
    ms.meshing_remove_duplicate_faces()
    ms.meshing_remove_unreferenced_vertices()
    ms.save_current_mesh(str(out_path))
    return out_path


def run_repair(
    mesh_url: str,
    *,
    mode: str = "voxel",
    resolution: int = 256,
    max_hole_size: int = 5000,
) -> tuple[Path, dict]:
    """Download GLB, repair, return (output_path, metadata)."""
    mode = mode.strip().lower()
    in_path = download_mesh(mesh_url)
    try:
        mesh = load_glb_mesh(in_path)
        before = mesh_stats(mesh)
        meta = {"mode": mode, "before": before}

        if mode == "voxel":
            repaired, extra = repair_voxel(mesh, resolution=resolution)
            meta.update(extra)
        elif mode == "pymeshlab":
            out_tmp = Path(tempfile.mkstemp(suffix=".glb")[1])
            repair_pymeshlab(in_path, out_tmp, max_hole_size=max_hole_size)
            repaired = load_glb_mesh(out_tmp)
            meta["max_hole_size"] = max_hole_size
        elif mode == "trimesh":
            import trimesh

            repaired = mesh.copy()
            trimesh.repair.fix_normals(repaired)
            trimesh.repair.fill_holes(repaired)
        else:
            raise ValueError(f"Unknown repair_mode: {mode}")

        meta["after"] = mesh_stats(repaired)
        out_path = Path(tempfile.mkstemp(suffix=".glb")[1])
        repaired.export(out_path)
        return out_path, meta
    finally:
        if in_path.is_file():
            in_path.unlink(missing_ok=True)
