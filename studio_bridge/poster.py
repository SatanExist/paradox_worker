"""CPU poster frame from a textured GLB for library cards.

Not the product viewer. One 3/4 studio still → JPEG. Safe to skip on failure.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def _load_trimesh(path: Path):
    import trimesh

    loaded = trimesh.load(str(path), force="scene")
    geoms = []
    if hasattr(loaded, "geometry"):
        for geom in loaded.geometry.values():
            if hasattr(geom, "faces") and hasattr(geom, "vertices"):
                geoms.append(geom)
    elif hasattr(loaded, "faces"):
        geoms.append(loaded)
    if not geoms:
        raise ValueError(f"no mesh in {path}")
    if len(geoms) == 1:
        return geoms[0]
    return trimesh.util.concatenate(geoms)


def _decimate(mesh, face_cap: int = 16000):
    if len(mesh.faces) <= face_cap:
        return mesh
    for kwargs in (
        {"face_count": face_cap},
        {"percent": max(0.02, face_cap / max(len(mesh.faces), 1))},
    ):
        try:
            simplified = mesh.simplify_quadric_decimation(**kwargs)
            if simplified is not None and len(simplified.faces) > 12:
                return simplified
        except TypeError:
            continue
        except Exception:
            break
    try:
        return mesh.simplify_quadric_decimation(face_cap)
    except Exception:
        return mesh


def _albedo_image(mesh) -> Image.Image | None:
    visual = getattr(mesh, "visual", None)
    if visual is None:
        return None
    material = getattr(visual, "material", None)
    for attr in ("baseColorTexture", "image"):
        img = getattr(material, attr, None) if material is not None else None
        if img is None and attr == "image":
            img = getattr(visual, "image", None)
        if img is None:
            continue
        if isinstance(img, Image.Image):
            return img.convert("RGB")
        if isinstance(img, np.ndarray):
            arr = img
            if arr.dtype != np.uint8:
                arr = np.clip(arr, 0, 255).astype(np.uint8)
            if arr.ndim == 2:
                arr = np.stack([arr, arr, arr], axis=-1)
            return Image.fromarray(arr[..., :3])
    return None


def _face_colors(mesh, albedo: Image.Image | None, ndotl: np.ndarray) -> np.ndarray:
    n = len(mesh.faces)
    base = np.full((n, 3), 180.0, dtype=np.float64)
    uv = getattr(getattr(mesh, "visual", None), "uv", None)
    if albedo is not None and uv is not None and len(uv) >= mesh.vertices.shape[0]:
        w, h = albedo.size
        pix = np.asarray(albedo, dtype=np.float64)
        face_uv = uv[mesh.faces].mean(axis=1)
        u = np.clip(face_uv[:, 0], 0.0, 1.0)
        v = np.clip(1.0 - face_uv[:, 1], 0.0, 1.0)
        xs = np.clip((u * (w - 1)).astype(np.int32), 0, w - 1)
        ys = np.clip((v * (h - 1)).astype(np.int32), 0, h - 1)
        base = pix[ys, xs, :3]
    shade = 0.22 + 0.78 * ndotl.reshape(-1, 1)
    return np.clip(base * shade, 0, 255).astype(np.uint8)


def render_trimesh_poster(mesh, *, size: int = 512) -> Image.Image:
    """3/4 studio still. Background matches lab cards (#2a2a30)."""
    mesh = mesh.copy()
    mesh = _decimate(mesh)
    center = mesh.bounds.mean(axis=0)
    verts = mesh.vertices - center
    extent = float(np.max(np.abs(verts))) or 1.0
    verts = verts / extent

    yaw = np.deg2rad(32)
    pitch = np.deg2rad(18)
    cy, sy = np.cos(yaw), np.sin(yaw)
    cp, sp = np.cos(pitch), np.sin(pitch)
    rot_y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rot_x = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    cam = verts @ rot_y.T @ rot_x.T

    z = cam[:, 2] + 3.2
    z = np.clip(z, 0.4, None)
    px = (cam[:, 0] / z) * (size * 0.42) + size * 0.5
    py = (-cam[:, 1] / z) * (size * 0.42) + size * 0.52
    pts = np.stack([px, py], axis=1)

    normals = mesh.face_normals @ rot_y.T @ rot_x.T
    light = np.array([0.45, 0.75, 0.48], dtype=np.float64)
    light /= np.linalg.norm(light)
    ndotl = np.clip(normals @ light, 0.0, 1.0)
    facing = normals[:, 2] < 0.02
    colors = _face_colors(mesh, _albedo_image(mesh), ndotl)

    depth = cam[mesh.faces].mean(axis=1)[:, 2]
    order = np.argsort(depth)

    img = Image.new("RGB", (size, size), (42, 42, 48))
    draw = ImageDraw.Draw(img)
    faces = mesh.faces
    for idx in order:
        if not facing[idx]:
            continue
        tri = pts[faces[idx]]
        if not np.isfinite(tri).all():
            continue
        coords = [(float(x), float(y)) for x, y in tri]
        rgb = tuple(int(c) for c in colors[idx])
        draw.polygon(coords, fill=rgb)

    return img


def render_glb_poster(path: str | Path, *, size: int = 512) -> Image.Image:
    mesh = _load_trimesh(Path(path))
    return render_trimesh_poster(mesh, size=size)
