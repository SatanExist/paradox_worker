"""CPU poster frame from a textured GLB for library cards.

Not the product viewer. One 3/4 studio still → JPEG. Safe to skip on failure.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

# Rodin-like studio still. Overlays (heart, user) stay in the product UI, not here.
_BG = (16, 16, 18)
_FACE_CAP = 40_000
_SSAA = 2


def _blur01(arr: np.ndarray, sigma: float) -> np.ndarray:
    try:
        from scipy.ndimage import gaussian_filter

        return gaussian_filter(arr.astype(np.float32), sigma=sigma)
    except Exception:
        im = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), "L")
        im = im.filter(ImageFilter.GaussianBlur(radius=max(1.0, float(sigma) * 0.55)))
        return np.asarray(im, dtype=np.float32) / 255.0


def _studio_backdrop(size: int) -> np.ndarray:
    """Charcoal cove + vignette. Matches library cards, not a flat hex."""
    y = np.linspace(0.0, 1.0, size, dtype=np.float32)[:, None]
    top = np.array([34.0, 34.0, 38.0], dtype=np.float32)
    bot = np.array([8.0, 8.0, 10.0], dtype=np.float32)
    bg = top * (1.0 - y) + bot * y
    x = np.linspace(-1.0, 1.0, size, dtype=np.float32)
    xx, yy = np.meshgrid(x, x)
    r2 = xx * xx + (yy * 0.9) ** 2
    vig = np.clip(1.08 - 0.48 * r2, 0.48, 1.0)
    return bg * vig[..., None]


def _contact_shadow(
    canvas: np.ndarray,
    pts: np.ndarray,
    cam_y: np.ndarray,
    vis_idx: np.ndarray,
    size: int,
) -> np.ndarray:
    """Soft oval on the implied floor — the Rodin 'weight' under the model."""
    out = canvas.copy()
    if vis_idx.size < 3:
        return out
    ys = cam_y[vis_idx]
    ymin = float(ys.min())
    height = max(float(ys.max() - ymin), 1e-6)
    feet = vis_idx[ys < ymin + 0.16 * height]
    if feet.size < 3:
        feet = vis_idx
    fp = pts[feet]
    cx = float(fp[:, 0].mean())
    cy = float(np.percentile(fp[:, 1], 88))
    rx = max(size * 0.06, float(fp[:, 0].max() - fp[:, 0].min()) * 0.62)
    ry = max(size * 0.025, rx * 0.30)
    yy, xx = np.ogrid[0:size, 0:size]
    ell = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
    blob = np.clip(np.exp(-ell * 1.55), 0.0, 1.0)
    blob = _blur01(blob, sigma=max(1.2, size * 0.016))
    out *= 1.0 - blob[..., None] * 0.62
    return out


def _load_trimesh(path: Path):
    import trimesh

    loaded = trimesh.load(str(path), force="scene")
    geoms = []
    if hasattr(loaded, "dump"):
        dumped = loaded.dump(concatenate=False)
        if not isinstance(dumped, (list, tuple)):
            dumped = [dumped]
        for geom in dumped:
            if hasattr(geom, "faces") and hasattr(geom, "vertices"):
                geoms.append(geom)
    elif hasattr(loaded, "geometry"):
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


def _cluster_decimate(mesh, face_cap: int):
    """Vertex-grid LOD. No extra deps (worker trimesh has no fast_simplification)."""
    import trimesh

    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    uv = getattr(getattr(mesh, "visual", None), "uv", None)
    uv_arr = np.asarray(uv, dtype=np.float64) if uv is not None and len(uv) == len(verts) else None

    target_v = max(400, int(face_cap * 0.55))
    extent = float(np.max(verts.max(axis=0) - verts.min(axis=0))) or 1.0
    origin = verts.min(axis=0)
    bins = int(max(32, min(96, round(target_v ** (1.0 / 3.0) * 4.5))))

    chosen = None
    for _ in range(8):
        q = np.floor((verts - origin) * (bins / (extent + 1e-12))).astype(np.int32)
        q = np.clip(q, 0, bins - 1)
        keys = q[:, 0] * (bins * bins) + q[:, 1] * bins + q[:, 2]
        uniq, inv = np.unique(keys, return_inverse=True)
        new_verts = np.zeros((len(uniq), 3), dtype=np.float64)
        np.add.at(new_verts, inv, verts)
        counts = np.maximum(np.bincount(inv, minlength=len(uniq)), 1)
        new_verts /= counts[:, None]
        new_faces = inv[faces]
        keep = (
            (new_faces[:, 0] != new_faces[:, 1])
            & (new_faces[:, 1] != new_faces[:, 2])
            & (new_faces[:, 0] != new_faces[:, 2])
        )
        new_faces = new_faces[keep]
        _, first = np.unique(np.sort(new_faces, axis=1), axis=0, return_index=True)
        new_faces = new_faces[np.sort(first)]
        chosen = (new_verts, new_faces, inv)
        if len(new_faces) <= face_cap or bins <= 16:
            break
        bins = max(16, int(bins * 0.82))

    new_verts, new_faces, inv = chosen
    kwargs = {}
    if uv_arr is not None:
        new_uv = np.zeros((len(new_verts), 2), dtype=np.float64)
        np.add.at(new_uv, inv, uv_arr)
        counts = np.maximum(np.bincount(inv, minlength=len(new_verts)), 1)
        new_uv /= counts[:, None]
        kwargs["visual"] = trimesh.visual.TextureVisuals(
            uv=new_uv,
            material=getattr(getattr(mesh, "visual", None), "material", None),
        )
    out = trimesh.Trimesh(vertices=new_verts, faces=new_faces, process=True, **kwargs)
    if "visual" not in kwargs and getattr(mesh, "visual", None) is not None:
        out.visual = mesh.visual
    return out


def _decimate(mesh, face_cap: int = _FACE_CAP):
    if len(mesh.faces) <= face_cap:
        return mesh
    for kwargs in (
        {"face_count": face_cap},
        {"percent": max(0.02, face_cap / max(len(mesh.faces), 1))},
    ):
        try:
            simplified = mesh.simplify_quadric_decimation(**kwargs)
            if simplified is not None and 12 < len(simplified.faces) <= face_cap * 2:
                return simplified
        except TypeError:
            continue
        except Exception:
            break
    try:
        simplified = mesh.simplify_quadric_decimation(face_cap)
        if simplified is not None and len(simplified.faces) > 12:
            return simplified
    except Exception:
        pass
    return _cluster_decimate(mesh, face_cap)


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


def _factor_rgb(mesh) -> np.ndarray:
    visual = getattr(mesh, "visual", None)
    material = getattr(visual, "material", None) if visual is not None else None
    raw = None
    if material is not None:
        raw = getattr(material, "baseColorFactor", None)
        if raw is None:
            raw = getattr(material, "main_color", None)
    if raw is None:
        return np.array([210.0, 210.0, 214.0], dtype=np.float64)
    arr = np.asarray(raw, dtype=np.float64).reshape(-1)[:3]
    if arr.max() <= 1.0:
        arr = arr * 255.0
    # Clay 180 looks white in the studio viewer (IBL + key). Lift it toward that.
    if arr.max() < 200 and np.std(arr) < 8:
        arr = arr * 1.18 + 28.0
    return np.clip(arr, 0, 255)


def _vertex_colors(mesh, albedo: Image.Image | None, shade: np.ndarray) -> np.ndarray:
    n = len(mesh.vertices)
    vc = getattr(getattr(mesh, "visual", None), "vertex_colors", None)
    if vc is not None and len(vc) >= n:
        base = np.asarray(vc, dtype=np.float64)[:n, :3]
        if base.max() <= 1.0:
            base = base * 255.0
    else:
        base = np.broadcast_to(_factor_rgb(mesh), (n, 3)).copy()
        uv = getattr(getattr(mesh, "visual", None), "uv", None)
        if albedo is not None and uv is not None and len(uv) >= n:
            w, h = albedo.size
            pix = np.asarray(albedo, dtype=np.float64)
            u = np.clip(np.asarray(uv)[:n, 0], 0.0, 1.0)
            v = np.clip(1.0 - np.asarray(uv)[:n, 1], 0.0, 1.0)
            xs = np.clip((u * (w - 1)).astype(np.int32), 0, w - 1)
            ys = np.clip((v * (h - 1)).astype(np.int32), 0, h - 1)
            base = pix[ys, xs, :3]
    return np.clip(base * shade.reshape(-1, 1), 0, 255).astype(np.float32)


def _bake_albedo_vertices(mesh):
    """Quadric LOD drops UVs; vertex colors survive. Bake before simplify."""
    import trimesh

    albedo = _albedo_image(mesh)
    uv = getattr(getattr(mesh, "visual", None), "uv", None)
    n = len(mesh.vertices)
    if albedo is None or uv is None or len(uv) < n:
        return mesh
    ones = np.ones((n, 1), dtype=np.float64)
    rgb = _vertex_colors(mesh, albedo, ones[:, 0])
    rgba = np.concatenate([rgb, ones * 255.0], axis=1).astype(np.uint8)
    mesh.visual = trimesh.visual.ColorVisuals(vertex_colors=rgba)
    return mesh


def _raster_zbuffer(
    pts: np.ndarray,
    zs: np.ndarray,
    faces: np.ndarray,
    vcolors: np.ndarray,
    facing: np.ndarray,
    canvas: np.ndarray,
) -> np.ndarray:
    img = canvas.copy()
    size = int(img.shape[0])
    zbuf = np.full((size, size), np.inf, dtype=np.float32)
    vis = np.nonzero(facing)[0]
    for idx in vis:
        f = faces[idx]
        p = pts[f]
        z = zs[f]
        col = vcolors[f]
        minx = int(np.floor(p[:, 0].min()))
        maxx = int(np.ceil(p[:, 0].max()))
        miny = int(np.floor(p[:, 1].min()))
        maxy = int(np.ceil(p[:, 1].max()))
        minx = max(minx, 0)
        maxx = min(maxx, size - 1)
        miny = max(miny, 0)
        maxy = min(maxy, size - 1)
        if minx > maxx or miny > maxy:
            continue
        a, b, c = p
        v0x, v0y = b[0] - a[0], b[1] - a[1]
        v1x, v1y = c[0] - a[0], c[1] - a[1]
        den = v0x * v1y - v1x * v0y
        if abs(den) < 1e-8:
            continue
        xs = np.arange(minx, maxx + 1, dtype=np.float32) + 0.5
        ys = np.arange(miny, maxy + 1, dtype=np.float32) + 0.5
        xx, yy = np.meshgrid(xs, ys)
        v2x, v2y = xx - a[0], yy - a[1]
        w1 = (v2x * v1y - v1x * v2y) / den
        w2 = (v0x * v2y - v2x * v0y) / den
        w0 = 1.0 - w1 - w2
        inside = (w0 >= -1e-5) & (w1 >= -1e-5) & (w2 >= -1e-5)
        if not np.any(inside):
            continue
        zpix = w0 * z[0] + w1 * z[1] + w2 * z[2]
        sl_y = slice(miny, maxy + 1)
        sl_x = slice(minx, maxx + 1)
        better = inside & (zpix < zbuf[sl_y, sl_x])
        if not np.any(better):
            continue
        zbuf[sl_y, sl_x][better] = zpix[better]
        rgb = w0[..., None] * col[0] + w1[..., None] * col[1] + w2[..., None] * col[2]
        img[sl_y, sl_x][better] = rgb[better]
    return img


def render_trimesh_poster(mesh, *, size: int = 512) -> Image.Image:
    """Elevated 3/4 studio still: cove, contact shadow, padding. Not a live viewer."""
    mesh = mesh.copy()
    mesh = _bake_albedo_vertices(mesh)
    mesh = _decimate(mesh)
    center = mesh.bounds.mean(axis=0)
    verts = mesh.vertices - center
    extent = float(np.max(np.abs(verts))) or 1.0
    verts = verts / extent

    # Slightly above, 3/4 — Rodin library, not worm's-eye.
    yaw = np.deg2rad(34)
    pitch = np.deg2rad(-18)
    cy, sy = np.cos(yaw), np.sin(yaw)
    cp, sp = np.cos(pitch), np.sin(pitch)
    rot_y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rot_x = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    cam = verts @ rot_y.T @ rot_x.T

    z = cam[:, 2] + 3.2
    z = np.clip(z, 0.4, None)
    px = cam[:, 0] / z
    py = -cam[:, 1] / z
    pts = np.stack([px, py], axis=1)

    face_n = mesh.face_normals @ rot_y.T @ rot_x.T
    vert_n = mesh.vertex_normals @ rot_y.T @ rot_x.T
    facing = face_n[:, 2] < 0.35
    if int(facing.sum()) < 12:
        facing = np.ones(len(mesh.faces), dtype=bool)

    vis_idx = np.unique(mesh.faces[facing].ravel())
    vis_pts = pts[vis_idx]
    span = float(np.max(vis_pts.max(axis=0) - vis_pts.min(axis=0))) or 1.0
    mid = (vis_pts.min(axis=0) + vis_pts.max(axis=0)) * 0.5
    work = size * _SSAA
    # Leave margin; sit a bit high so the floor shadow has room.
    scale = (work * 0.70) / span
    pts = (pts - mid) * scale + np.array([work * 0.50, work * 0.46], dtype=np.float64)

    canvas = _studio_backdrop(work)
    canvas = _contact_shadow(canvas, pts, cam[:, 1], vis_idx, work)

    key = np.array([0.48, 0.72, -0.50], dtype=np.float64)
    fill = np.array([-0.58, 0.22, -0.32], dtype=np.float64)
    rim = np.array([-0.22, 0.38, 0.90], dtype=np.float64)
    key /= np.linalg.norm(key)
    fill /= np.linalg.norm(fill)
    rim /= np.linalg.norm(rim)
    shade = (
        0.40
        + 0.78 * np.clip(vert_n @ key, 0.0, 1.0)
        + 0.26 * np.clip(vert_n @ fill, 0.0, 1.0)
        + 0.20 * np.clip(vert_n @ rim, 0.0, 1.0)
    )
    vcolors = _vertex_colors(mesh, _albedo_image(mesh), np.clip(shade, 0.30, 1.35))
    raster = _raster_zbuffer(
        pts.astype(np.float32),
        z.astype(np.float32),
        np.asarray(mesh.faces, dtype=np.int32),
        vcolors,
        facing,
        canvas.astype(np.float32),
    )
    hi = Image.fromarray(np.clip(raster, 0, 255).astype(np.uint8), "RGB")
    if _SSAA <= 1:
        return hi
    lo = hi.resize((size, size), Image.Resampling.LANCZOS)
    return Image.fromarray(np.clip(np.asarray(lo), 0, 255).astype(np.uint8), "RGB")


def render_glb_poster(path: str | Path, *, size: int = 512) -> Image.Image:
    mesh = _load_trimesh(Path(path))
    return render_trimesh_poster(mesh, size=size)


def render_glb_poster_set(
    path: str | Path,
    *,
    size: int = 768,
) -> dict[str, Image.Image]:
    """Studio stills for the library card. GPU full-mesh if possible, else one CPU frame."""
    try:
        from studio_bridge.poster_gpu import render_poster_set
    except ImportError:
        from poster_gpu import render_poster_set  # type: ignore

    frames = None
    try:
        frames = render_poster_set(path, size=size)
    except Exception as exc:
        print(f"WARN: GPU poster set failed ({exc}); CPU studio still")
        frames = None
    if frames:
        return frames
    return {"studio": render_glb_poster(path, size=min(size, 512))}
