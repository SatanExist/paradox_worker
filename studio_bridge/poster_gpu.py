"""GPU library stills (nvdiffrast) — full mesh, several studio environments.

Rodin-style: one sharp JPEG per light rig. Grid swaps stills on hover.
Never a live GLB in the card. CPU raster is the local/fallback path.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

# Same names as studio_viewer.js LIGHT_RIGS. Cycle = hover order.
POSTER_ENVS = ("studio", "outdoor", "gallery", "neon", "night")

# Object bbox occupies this fraction of the square (rest = padding).
_FRAME_FILL = 0.68
# NDC y shift: object sits a bit high so the floor shadow has room.
_Y_BIAS = 0.08

_ENV = {
    "studio": {
        "top": (0.14, 0.13, 0.12),
        "bot": (0.035, 0.035, 0.04),
        "ambient": (0.16, 0.15, 0.14),
        "key_dir": (0.42, 0.82, 0.38),
        "key_col": (1.00, 0.96, 0.90),
        "key": 0.70,
        "fill_dir": (-0.68, 0.28, 0.18),
        "fill_col": (0.62, 0.77, 1.00),
        "fill": 0.28,
        "rim_dir": (-0.18, 0.42, -0.88),
        "rim_col": (1.00, 0.55, 0.32),
        "rim": 0.32,
    },
    "outdoor": {
        "top": (0.38, 0.55, 0.82),
        "bot": (0.26, 0.22, 0.15),
        "ambient": (0.28, 0.32, 0.38),
        "key_dir": (0.35, 0.88, 0.32),
        "key_col": (1.00, 0.96, 0.82),
        "key": 0.78,
        "fill_dir": (-0.55, 0.15, 0.35),
        "fill_col": (0.55, 0.72, 1.00),
        "fill": 0.22,
        "rim_dir": (-0.25, 0.20, -0.94),
        "rim_col": (1.00, 1.00, 0.95),
        "rim": 0.12,
    },
    "gallery": {
        "top": (0.62, 0.61, 0.58),
        "bot": (0.32, 0.31, 0.33),
        "ambient": (0.40, 0.40, 0.41),
        "key_dir": (0.30, 0.90, 0.30),
        "key_col": (1.00, 1.00, 1.00),
        "key": 0.52,
        "fill_dir": (-0.60, 0.40, 0.20),
        "fill_col": (1.00, 1.00, 1.00),
        "fill": 0.32,
        "rim_dir": (-0.10, 0.50, -0.85),
        "rim_col": (1.00, 1.00, 1.00),
        "rim": 0.16,
    },
    "neon": {
        "top": (0.07, 0.03, 0.09),
        "bot": (0.02, 0.015, 0.03),
        "ambient": (0.06, 0.03, 0.08),
        "key_dir": (0.55, 0.40, 0.40),
        "key_col": (1.00, 0.40, 0.68),
        "key": 0.42,
        "fill_dir": (-0.75, 0.20, 0.25),
        "fill_col": (0.00, 0.90, 1.00),
        "fill": 0.78,
        "rim_dir": (-0.15, 0.55, -0.82),
        "rim_col": (1.00, 0.22, 0.85),
        "rim": 0.85,
    },
    "night": {
        "top": (0.05, 0.07, 0.12),
        "bot": (0.02, 0.025, 0.04),
        "ambient": (0.08, 0.11, 0.18),
        "key_dir": (0.25, 0.75, 0.40),
        "key_col": (0.78, 0.85, 1.00),
        "key": 0.38,
        "fill_dir": (-0.50, 0.25, 0.30),
        "fill_col": (0.24, 0.36, 1.00),
        "fill": 0.26,
        "rim_dir": (-0.20, 0.45, -0.87),
        "rim_col": (0.55, 0.70, 1.00),
        "rim": 0.72,
    },
}


def _load_numpy(path: Path):
    from studio_bridge.poster import (
        _albedo_image,
        _factor_rgb,
        _load_trimesh,
    )

    mesh = _load_trimesh(path)
    center = mesh.bounds.mean(axis=0)
    verts = np.asarray(mesh.vertices, dtype=np.float32) - center.astype(np.float32)
    extent = float(np.max(np.abs(verts))) or 1.0
    verts = verts / extent
    faces = np.asarray(mesh.faces, dtype=np.int32)
    normals = np.asarray(mesh.vertex_normals, dtype=np.float32)
    nlen = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = normals / np.clip(nlen, 1e-6, None)

    albedo_img = _albedo_image(mesh)
    uv = getattr(getattr(mesh, "visual", None), "uv", None)
    tex = None
    if albedo_img is not None and uv is not None and len(uv) >= len(verts):
        tex = np.asarray(albedo_img.convert("RGB"), dtype=np.float32) / 255.0
        uvs = np.asarray(uv, dtype=np.float32)[: len(verts)]
        uvs[:, 1] = 1.0 - uvs[:, 1]
    else:
        uvs = None
        factor = _factor_rgb(mesh).astype(np.float32) / 255.0
        vcolor = np.broadcast_to(factor, (len(verts), 3)).copy()
        return verts, faces, normals, vcolor, None, None

    vcolor = np.broadcast_to((_factor_rgb(mesh) / 255.0).astype(np.float32), (len(verts), 3)).copy()
    return verts, faces, normals, vcolor, uvs, tex


def _look_at(eye, target, up):
    eye = np.asarray(eye, dtype=np.float32)
    target = np.asarray(target, dtype=np.float32)
    up = np.asarray(up, dtype=np.float32)
    z = eye - target
    z = z / (np.linalg.norm(z) + 1e-8)
    x = np.cross(up, z)
    x = x / (np.linalg.norm(x) + 1e-8)
    y = np.cross(z, x)
    view = np.eye(4, dtype=np.float32)
    view[0, :3] = x
    view[1, :3] = y
    view[2, :3] = z
    view[0, 3] = -np.dot(x, eye)
    view[1, 3] = -np.dot(y, eye)
    view[2, 3] = -np.dot(z, eye)
    return view


def _perspective(fovy_deg: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fovy_deg) * 0.5)
    p = np.zeros((4, 4), dtype=np.float32)
    p[0, 0] = f
    p[1, 1] = f
    p[2, 2] = (far + near) / (near - far)
    p[2, 3] = (2.0 * far * near) / (near - far)
    p[3, 2] = -1.0
    return p


def _camera_mvp(verts: np.ndarray) -> np.ndarray:
    """Elevated 3/4, then NDC-fit so the whole mesh sits in frame with padding."""
    radii = np.linalg.norm(verts, axis=1)
    r = float(np.percentile(radii, 98)) if len(radii) else 1.0
    r = max(r, 0.35)
    yaw = math.radians(40.0)
    pitch = math.radians(22.0)
    direction = np.array(
        [
            math.sin(yaw) * math.cos(pitch),
            math.sin(pitch),
            math.cos(yaw) * math.cos(pitch),
        ],
        dtype=np.float32,
    )
    fov = 30.0
    dist = (r * 1.65) / math.tan(math.radians(fov) * 0.5)
    eye = direction * dist
    target = np.array([0.0, -0.05 * r, 0.0], dtype=np.float32)
    near = max(0.05, dist - r * 3.0)
    far = dist + r * 6.0
    view = _look_at(eye, target, (0.0, 1.0, 0.0))
    proj = _perspective(fov, near, far)
    return proj @ view


def _fit_clip(clip: np.ndarray) -> np.ndarray:
    w = np.clip(clip[:, 3:4], 1e-5, None)
    ndc = clip[:, :2] / w
    front = clip[:, 3] > 1e-4
    if int(front.sum()) < 8:
        return clip
    pts = ndc[front]
    lo = pts.min(axis=0)
    hi = pts.max(axis=0)
    span = float(np.max(hi - lo)) or 1.0
    mid = (lo + hi) * 0.5
    scale = (2.0 * _FRAME_FILL) / span
    out = clip.copy()
    out[:, 0] = (ndc[:, 0] - mid[0]) * scale * w[:, 0]
    out[:, 1] = ((ndc[:, 1] - mid[1]) * scale + _Y_BIAS) * w[:, 0]
    return out


def _clip_verts(verts: np.ndarray) -> np.ndarray:
    mvp = _camera_mvp(verts)
    homo = np.concatenate([verts, np.ones((len(verts), 1), dtype=np.float32)], axis=1)
    return _fit_clip(homo @ mvp.T)


def _backdrop(h: int, w: int, env: dict) -> np.ndarray:
    y = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
    top = np.array(env["top"], dtype=np.float32)
    bot = np.array(env["bot"], dtype=np.float32)
    bg = top * (1.0 - y) + bot * y
    xs = np.linspace(-1.0, 1.0, w, dtype=np.float32)
    ys = np.linspace(-1.0, 1.0, h, dtype=np.float32)
    xx, yy = np.meshgrid(xs, ys)
    vig = np.clip(1.06 - 0.46 * (xx * xx + (yy * 0.92) ** 2), 0.45, 1.0)
    return np.clip(bg * vig[..., None], 0.0, 1.0)


def _tonemap(col):
    return col / (1.0 + col * 0.40)


def _shade_np(albedo: np.ndarray, normal: np.ndarray, env: dict) -> np.ndarray:
    nlen = np.linalg.norm(normal, axis=-1, keepdims=True)
    n = normal / np.clip(nlen, 1e-6, None)
    col = albedo * np.array(env["ambient"], dtype=np.float32)
    for prefix in ("key", "fill", "rim"):
        d = np.array(env[f"{prefix}_dir"], dtype=np.float32)
        d = d / (np.linalg.norm(d) + 1e-8)
        c = np.array(env[f"{prefix}_col"], dtype=np.float32)
        nd = np.clip((n * d).sum(axis=-1, keepdims=True), 0.0, 1.0)
        col = col + albedo * nd * c * float(env[prefix])
    return np.clip(_tonemap(col), 0.0, 1.0)


def _shade_torch(albedo, normal, env: dict):
    import torch
    import torch.nn.functional as F

    n = F.normalize(normal, dim=-1, eps=1e-6)
    col = albedo * torch.tensor(env["ambient"], device=albedo.device, dtype=albedo.dtype)
    for prefix in ("key", "fill", "rim"):
        d = torch.tensor(env[f"{prefix}_dir"], device=albedo.device, dtype=albedo.dtype)
        d = F.normalize(d, dim=0)
        c = torch.tensor(env[f"{prefix}_col"], device=albedo.device, dtype=albedo.dtype)
        nd = (n * d).sum(dim=-1, keepdim=True).clamp(0.0, 1.0)
        col = col + albedo * nd * c * float(env[prefix])
    return _tonemap(col).clamp(0.0, 1.0)


def _contact_shadow(mask: np.ndarray) -> np.ndarray:
    work = mask.shape[0]
    shadow = np.zeros((work, work), dtype=np.float32)
    ys, xs = np.where(mask > 0.15)
    if ys.size < 8:
        return shadow
    cx = float(xs.mean())
    cy = float(np.percentile(ys, 90))
    rx = max(work * 0.08, float(xs.max() - xs.min()) * 0.42)
    ry = max(work * 0.03, rx * 0.28)
    yy, xx = np.ogrid[0:work, 0:work]
    ell = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
    shadow = np.exp(-ell * 1.6).astype(np.float32)
    try:
        from scipy.ndimage import gaussian_filter

        shadow = gaussian_filter(shadow, sigma=work * 0.014)
    except Exception:
        pass
    return shadow


def _pixels_from_clip(clip: np.ndarray, work: int) -> tuple[np.ndarray, np.ndarray]:
    w = np.clip(clip[:, 3], 1e-5, None)
    ndc_x = clip[:, 0] / w
    ndc_y = clip[:, 1] / w
    px = (ndc_x * 0.5 + 0.5) * work
    py = (-ndc_y * 0.5 + 0.5) * work
    z = clip[:, 2] / w
    pts = np.stack([px, py], axis=1).astype(np.float32)
    return pts, z.astype(np.float32)


def _decimate_arrays(verts, faces, nrm, vcol, uvs, tex):
    if len(faces) <= 40_000:
        return verts, faces, nrm, vcol
    import trimesh

    from studio_bridge.poster import _decimate

    factor = np.asarray(vcol[0], dtype=np.float32)
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    mesh = _decimate(mesh)
    verts = np.asarray(mesh.vertices, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.int32)
    nrm = np.asarray(mesh.vertex_normals, dtype=np.float32)
    nlen = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = nrm / np.clip(nlen, 1e-6, None)
    cols = np.broadcast_to(factor, (len(verts), 3)).copy()
    return verts, faces, nrm, cols


def _finish_still(img: Image.Image, size: int) -> Image.Image:
    """Drop raster edge bars, keep a square card."""
    w, h = img.size
    mx = max(2, int(w * 0.03))
    my = max(2, int(h * 0.01))
    img = img.crop((mx, my, w - mx, h - my))
    if img.size != (size, size):
        img = img.resize((size, size), Image.Resampling.LANCZOS)
    return img


def _compose_frames(albedo, nrm_img, mask, work: int, size: int) -> dict[str, Image.Image]:
    shadow = _contact_shadow(mask)
    m = mask[..., None]
    sh = shadow[..., None]
    frames: dict[str, Image.Image] = {}
    for name in POSTER_ENVS:
        env = _ENV[name]
        bg = _backdrop(work, work, env)
        lit = _shade_np(albedo, nrm_img, env)
        rgb = bg * (1.0 - sh * 0.55) * (1.0 - m) + lit * m
        rgb = np.clip(rgb, 0.0, 1.0)
        hi = (rgb * 255.0).astype(np.uint8)
        frames[name] = _finish_still(Image.fromarray(hi, "RGB"), size)
    return frames


def _render_cpu(verts, faces, nrm, vcol, size: int) -> dict[str, Image.Image]:
    from studio_bridge.poster import _raster_zbuffer

    verts, faces, nrm, vcol = _decimate_arrays(verts, faces, nrm, vcol, None, None)
    clip = _clip_verts(verts)
    work = int(size)
    pts, z = _pixels_from_clip(clip, work)
    canvas = np.zeros((work, work, 3), dtype=np.float32)
    ones = np.ones((len(verts), 3), dtype=np.float32)
    facing = np.ones(len(faces), dtype=bool)
    id_img = _raster_zbuffer(pts, z, faces, ones, facing, canvas)
    mask = (id_img[..., 0] > 0.04).astype(np.float32)
    nrm_img = _raster_zbuffer(
        pts, z, faces, (nrm * 0.5 + 0.5).astype(np.float32), facing, canvas.copy()
    )
    nrm_img = nrm_img * 2.0 - 1.0
    alb_img = _raster_zbuffer(pts, z, faces, vcol, facing, canvas.copy())
    return _compose_frames(alb_img, nrm_img, mask, work, size)


def _render_gpu(verts, faces, nrm, vcol, uvs, tex, size: int):
    import torch
    import nvdiffrast.torch as dr
    import torch.nn.functional as F

    device = torch.device("cuda")
    work = int(size * 2)
    clip_np = _clip_verts(verts).copy()
    # nvdiffrast image row 0 is top; OpenGL NDC +Y is up — flip or the card is upside-down.
    clip_np[:, 1] *= -1.0
    clip_np = _fit_clip(clip_np)
    pos = torch.from_numpy(clip_np).to(device)[None]
    tri = torch.from_numpy(faces).to(device)
    nrm_t = torch.from_numpy(nrm).to(device)[None]
    vcol_t = torch.from_numpy(vcol).to(device)[None]

    glctx = dr.RasterizeCudaContext(device=device)
    rast, _ = dr.rasterize(glctx, pos, tri, (work, work))
    mask = (rast[..., 3:4] > 0).float()
    nrm_img = dr.interpolate(nrm_t, rast, tri)[0]
    nrm_img = F.normalize(nrm_img, dim=-1, eps=1e-6)

    if tex is not None and uvs is not None:
        uv = torch.from_numpy(uvs).to(device)[None]
        uv_img = dr.interpolate(uv, rast, tri)[0]
        tex_t = torch.from_numpy(tex).to(device)[None]
        albedo = dr.texture(tex_t, uv_img, filter_mode="linear")
    else:
        albedo = dr.interpolate(vcol_t, rast, tri)[0]

    mask_aa = dr.antialias(mask, rast, pos, tri)[0, ..., 0]
    albedo = dr.antialias(albedo, rast, pos, tri)[0]
    nrm_img = dr.antialias(nrm_img, rast, pos, tri)[0]

    mask_np = mask_aa.detach().float().cpu().numpy()
    shadow = _contact_shadow(mask_np)
    m = mask_aa[..., None]
    sh = torch.from_numpy(shadow).to(device)[..., None]
    frames: dict[str, Image.Image] = {}
    for name in POSTER_ENVS:
        env = _ENV[name]
        bg = torch.from_numpy(_backdrop(work, work, env)).to(device)
        lit = _shade_torch(albedo, nrm_img, env)
        rgb = bg * (1.0 - sh * 0.55) * (1.0 - m) + lit * m
        rgb = rgb.clamp(0.0, 1.0)
        hi = (rgb.detach().cpu().numpy() * 255.0).astype(np.uint8)
        img = _finish_still(Image.fromarray(hi, "RGB"), size)
        frames[name] = img

    del rast, pos, glctx
    torch.cuda.empty_cache()
    return frames


def render_poster_set(path: str | Path, *, size: int = 768) -> dict[str, Image.Image] | None:
    """Full-mesh GPU stills, or CPU raster with the same camera if CUDA is missing."""
    verts, faces, nrm, vcol, uvs, tex = _load_numpy(Path(path))
    try:
        import torch
        import nvdiffrast.torch as dr  # noqa: F401

        if torch.cuda.is_available():
            return _render_gpu(verts, faces, nrm, vcol, uvs, tex, size)
    except Exception:
        pass
    try:
        return _render_cpu(verts, faces, nrm, vcol, size)
    except Exception:
        return None
