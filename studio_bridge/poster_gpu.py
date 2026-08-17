"""GPU library stills (nvdiffrast) — full mesh, several studio environments.

Rodin-style: one sharp JPEG per light rig. Grid swaps stills on hover.
Never a live GLB in the card. CPU poster.py is the fallback.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

# Same names as studio_viewer.js LIGHT_RIGS. Cycle = hover order.
POSTER_ENVS = ("studio", "outdoor", "gallery", "neon", "night")

_ENV = {
    "studio": {
        "top": (0.15, 0.14, 0.13),
        "bot": (0.035, 0.035, 0.04),
        "ambient": (0.22, 0.20, 0.18),
        "key_dir": (0.42, 0.82, 0.38),
        "key_col": (1.00, 0.95, 0.86),
        "key": 1.85,
        "fill_dir": (-0.68, 0.28, 0.18),
        "fill_col": (0.62, 0.77, 1.00),
        "fill": 0.48,
        "rim_dir": (-0.18, 0.42, -0.88),
        "rim_col": (1.00, 0.48, 0.24),
        "rim": 1.05,
    },
    "outdoor": {
        "top": (0.42, 0.62, 0.92),
        "bot": (0.28, 0.24, 0.16),
        "ambient": (0.35, 0.40, 0.48),
        "key_dir": (0.35, 0.88, 0.32),
        "key_col": (1.00, 0.95, 0.78),
        "key": 2.15,
        "fill_dir": (-0.55, 0.15, 0.35),
        "fill_col": (0.55, 0.72, 1.00),
        "fill": 0.40,
        "rim_dir": (-0.25, 0.20, -0.94),
        "rim_col": (1.00, 1.00, 0.95),
        "rim": 0.22,
    },
    "gallery": {
        "top": (0.72, 0.71, 0.68),
        "bot": (0.38, 0.37, 0.39),
        "ambient": (0.55, 0.55, 0.56),
        "key_dir": (0.30, 0.90, 0.30),
        "key_col": (1.00, 1.00, 1.00),
        "key": 0.95,
        "fill_dir": (-0.60, 0.40, 0.20),
        "fill_col": (1.00, 1.00, 1.00),
        "fill": 0.55,
        "rim_dir": (-0.10, 0.50, -0.85),
        "rim_col": (1.00, 1.00, 1.00),
        "rim": 0.28,
    },
    "neon": {
        "top": (0.08, 0.04, 0.10),
        "bot": (0.02, 0.015, 0.03),
        "ambient": (0.08, 0.04, 0.10),
        "key_dir": (0.55, 0.40, 0.40),
        "key_col": (1.00, 0.40, 0.68),
        "key": 0.70,
        "fill_dir": (-0.75, 0.20, 0.25),
        "fill_col": (0.00, 0.90, 1.00),
        "fill": 1.45,
        "rim_dir": (-0.15, 0.55, -0.82),
        "rim_col": (1.00, 0.18, 0.85),
        "rim": 1.80,
    },
    "night": {
        "top": (0.05, 0.07, 0.12),
        "bot": (0.02, 0.025, 0.04),
        "ambient": (0.10, 0.14, 0.22),
        "key_dir": (0.25, 0.75, 0.40),
        "key_col": (0.78, 0.85, 1.00),
        "key": 0.55,
        "fill_dir": (-0.50, 0.25, 0.30),
        "fill_col": (0.24, 0.36, 1.00),
        "fill": 0.40,
        "rim_dir": (-0.20, 0.45, -0.87),
        "rim_col": (0.55, 0.70, 1.00),
        "rim": 1.55,
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


def _shade(albedo, normal, env: dict):
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
    return col.clamp(0.0, 1.0)


def render_poster_set(path: str | Path, *, size: int = 768) -> dict[str, Image.Image] | None:
    """Full-mesh GPU stills. None if CUDA/nvdiffrast is unavailable."""
    try:
        import torch
        import nvdiffrast.torch as dr
        import torch.nn.functional as F
    except Exception:
        return None
    if not torch.cuda.is_available():
        return None

    device = torch.device("cuda")
    verts_np, faces_np, nrm_np, vcol_np, uvs_np, tex_np = _load_numpy(Path(path))
    work = int(size * 2)

    eye = np.array([1.55, 1.12, 1.85], dtype=np.float32)
    view = _look_at(eye, (0.0, -0.05, 0.0), (0.0, 1.0, 0.0))
    proj = _perspective(32.0, 0.05, 20.0)
    mvp = proj @ view

    v = np.concatenate([verts_np, np.ones((len(verts_np), 1), dtype=np.float32)], axis=1)
    clip_np = v @ mvp.T

    pos = torch.from_numpy(clip_np).to(device)[None]
    tri = torch.from_numpy(faces_np).to(device)
    nrm = torch.from_numpy(nrm_np).to(device)[None]
    vcol = torch.from_numpy(vcol_np).to(device)[None]

    glctx = dr.RasterizeCudaContext(device=device)
    rast, _ = dr.rasterize(glctx, pos, tri, (work, work))
    mask = (rast[..., 3:4] > 0).float()
    nrm_img = dr.interpolate(nrm, rast, tri)[0]
    nrm_img = F.normalize(nrm_img, dim=-1, eps=1e-6)

    if tex_np is not None and uvs_np is not None:
        uv = torch.from_numpy(uvs_np).to(device)[None]
        uv_img = dr.interpolate(uv, rast, tri)[0]
        tex = torch.from_numpy(tex_np).to(device)[None]
        albedo = dr.texture(tex, uv_img, filter_mode="linear")
    else:
        albedo = dr.interpolate(vcol, rast, tri)[0]

    mask_aa = dr.antialias(mask, rast, pos, tri)[0, ..., 0]
    albedo = dr.antialias(albedo, rast, pos, tri)[0]
    nrm_img = dr.antialias(nrm_img, rast, pos, tri)[0]

    mask_np = mask_aa.detach().float().cpu().numpy()
    ys, xs = np.where(mask_np > 0.15)
    shadow = np.zeros((work, work), dtype=np.float32)
    if ys.size > 8:
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

    frames: dict[str, Image.Image] = {}
    m = mask_aa[..., None]
    sh = torch.from_numpy(shadow).to(device)[..., None]
    for name in POSTER_ENVS:
        env = _ENV[name]
        bg = torch.from_numpy(_backdrop(work, work, env)).to(device)
        lit = _shade(albedo, nrm_img, env)
        rgb = bg * (1.0 - sh * 0.55) * (1.0 - m) + lit * m
        rgb = rgb.clamp(0.0, 1.0)
        hi = (rgb.detach().cpu().numpy() * 255.0).astype(np.uint8)
        img = Image.fromarray(hi, "RGB").resize((size, size), Image.Resampling.LANCZOS)
        frames[name] = img

    del rast, pos, glctx
    torch.cuda.empty_cache()
    return frames
