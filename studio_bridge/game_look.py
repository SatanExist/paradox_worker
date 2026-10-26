"""How a lighter model looks next to the original: the same fixed views rendered on the CPU, compared.

The numbers in game_prep's report measure the surface; this measures the picture a person sees. Both
models are drawn from six fixed views (Embree rays through libigl, no GPU) with their base colour
texture, normal map and metal/roughness, under one fixed light and sky, and compared pixel by pixel:

  silhouettePct  outline that differs: parts gone or grown (pixels in one outline only / both)
  lookPct        mean colour difference where both are drawn, everything on
  texturePct     the same with the texture alone (no light): UVs shifted, seams moved, blurred texture
  lightPct       the same with the light alone (no texture): normals and shape, the "crumpled" look

Every run draws the same rays, so a model always gets the same numbers. What it doesn't see: the
viewer's reflections of a room (the sky here is simple), so a result can look shinier in the viewer
than these numbers say.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

RES = 384  # pixels per view side
TEX = 512  # textures are compared at the size a view of this resolution shows them
VIEWS = {  # where the camera looks from; the model is Y up
    "front": (0.0, 0.0, 1.0),
    "back": (0.0, 0.0, -1.0),
    "left": (-1.0, 0.0, 0.0),
    "right": (1.0, 0.0, 0.0),
    "top": (0.0, 1.0, 0.0),
    "three-quarter": (0.6, 0.45, 0.66),
}


def _load(path: Path) -> dict[str, Any]:
    """Vertices, faces, the file's normals and UVs, per-face material, and per-face tangent frames."""
    import numpy as np
    import trimesh
    from PIL import Image

    from studio_bridge.tools_ops import _unpacked

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

    def image(tex):
        return None if tex is None else np.asarray(tex.convert("RGB").resize((TEX, TEX), Image.BOX), np.float32) / 255

    verts, faces, normals, uvs, owner, mats, offset = [], [], [], [], [], [], 0
    for node in scene.graph.nodes_geometry:
        matrix, name = scene.graph[node]
        geom = scene.geometry.get(name)
        if not isinstance(geom, trimesh.Trimesh) or len(geom.faces) == 0:
            continue
        n = np.asarray(geom.vertex_normals) @ matrix[:3, :3].T
        verts.append(trimesh.transform_points(geom.vertices, matrix))
        normals.append(n / np.linalg.norm(n, axis=1, keepdims=True).clip(1e-12))
        faces.append(np.asarray(geom.faces) + offset)
        uv = getattr(geom.visual, "uv", None)
        uvs.append(np.asarray(uv, float) if uv is not None and len(uv) == len(geom.vertices) else np.zeros((len(geom.vertices), 2)))
        owner.append(np.full(len(geom.faces), len(mats)))
        mat = getattr(geom.visual, "material", None)
        factor = getattr(mat, "baseColorFactor", None)
        metal, rough = getattr(mat, "metallicFactor", None), getattr(mat, "roughnessFactor", None)
        mats.append({
            "factor": np.asarray(factor if factor is not None else [255, 255, 255, 255], np.float32)[:3] / 255,
            "base": image(getattr(mat, "baseColorTexture", None)),
            "normal": image(getattr(mat, "normalTexture", None)),
            "mr": image(getattr(mat, "metallicRoughnessTexture", None)),
            "metal": 1.0 if metal is None else float(metal),
            "rough": 1.0 if rough is None else float(rough),
        })
        offset += len(geom.vertices)
    if not faces:
        raise ValueError("could not read the model's geometry")
    V, F = np.vstack(verts), np.vstack(faces)
    UV = np.vstack(uvs)
    # A tangent frame per face from the UVs, as a viewer builds one for a file without tangents.
    p, t = V[F], UV[F]
    e1, e2 = p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]
    d1, d2 = t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]
    det = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    det = np.where(np.abs(det) < 1e-12, 1e-12, det)
    T = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) / det[:, None]
    B = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) / det[:, None]
    return {"V": V, "F": F, "N": np.vstack(normals), "UV": UV, "owner": np.concatenate(owner), "mats": mats, "T": T, "B": B}


def _sample(img, uv):
    """Nearest texel; trimesh's UV origin is bottom-left; textures repeat."""
    import numpy as np

    h, w = img.shape[:2]
    x = np.floor((uv[:, 0] % 1.0) * w).astype(int).clip(0, w - 1)
    y = np.floor((1 - uv[:, 1] % 1.0) * h).astype(int).clip(0, h - 1)
    return img[y, x]


def _draw(m: dict[str, Any], centre, radius: float, view) -> tuple[Any, dict[str, Any]]:
    """One view: the outline and three pictures (everything, texture alone, light alone)."""
    import igl.embree
    import numpy as np

    d = -np.asarray(view, float)
    d /= np.linalg.norm(d)
    up = np.array([0.0, 1.0, 0.0]) if abs(d[1]) < 0.9 else np.array([0.0, 0.0, -1.0])
    right = np.cross(d, up)
    right /= np.linalg.norm(right)
    up = np.cross(right, d)
    s = (np.arange(RES) + 0.5) / RES * 2 - 1
    xs, ys = np.meshgrid(s, -s)
    origins = (centre - d * (2 * radius) + (xs[..., None] * right + ys[..., None] * up) * radius).reshape(-1, 3)
    hit = igl.embree.line_mesh_intersection(origins, np.repeat(d[None], len(origins), 0), m["V"], m["F"])
    face = hit[:, 0].astype(np.int64)
    seen = face >= 0
    f = face[seen]
    w = np.stack([1 - hit[seen, 1] - hit[seen, 2], hit[seen, 1], hit[seen, 2]], 1)[:, :, None]
    corners = m["F"][f]
    n = (m["N"][corners] * w).sum(1)
    n /= np.linalg.norm(n, axis=1, keepdims=True).clip(1e-12)
    uv = (m["UV"][corners] * w).sum(1)

    albedo = np.ones((len(f), 3), np.float32)
    metal, rough = np.zeros(len(f)), np.ones(len(f))
    for i, mat in enumerate(m["mats"]):
        sel = m["owner"][f] == i
        if not sel.any():
            continue
        albedo[sel] = mat["factor"]
        if mat["base"] is not None:
            albedo[sel] *= _sample(mat["base"], uv[sel])
        metal[sel], rough[sel] = mat["metal"], mat["rough"]
        if mat["mr"] is not None:
            mr = _sample(mat["mr"], uv[sel])
            rough[sel] *= mr[:, 1]
            metal[sel] *= mr[:, 2]
        if mat["normal"] is not None:
            tn = _sample(mat["normal"], uv[sel]) * 2 - 1
            T, B, N0 = m["T"][f[sel]], m["B"][f[sel]], n[sel]
            T = T - N0 * (T * N0).sum(1, keepdims=True)
            T /= np.linalg.norm(T, axis=1, keepdims=True).clip(1e-12)
            hand = np.sign((np.cross(N0, T) * B).sum(1, keepdims=True))
            mapped = T * tn[:, 0:1] + np.cross(N0, T) * np.where(hand == 0, 1, hand) * tn[:, 1:2] + N0 * tn[:, 2:3]
            n[sel] = mapped / np.linalg.norm(mapped, axis=1, keepdims=True).clip(1e-12)

    light = -d + up * 0.5 + right * 0.3
    light /= np.linalg.norm(light)
    lambert = np.clip(n @ light, 0, 1)[:, None] * 0.8 + 0.2
    refl = d - 2 * (n @ d)[:, None] * n  # a fixed sky: bright above, a horizon band, dark ground
    y = refl[:, 1]
    sky = (np.clip(0.15 + 0.85 * np.clip(y, 0, 1) ** 0.5, 0, 1) + 0.6 * np.exp(-((y / 0.08) ** 2)))[:, None]
    f0 = 0.04 * (1 - metal[:, None]) + albedo * metal[:, None]
    shiny = f0 * sky * (0.25 + 0.75 * (1 - rough[:, None]) ** 2)

    pictures = {}
    for key, colour in (
        ("look", (albedo * (1 - metal[:, None]) * lambert + shiny).clip(0, 1)),
        ("texture", albedo),
        ("light", np.repeat(lambert * 0.7, 3, 1)),
    ):
        img = np.zeros((len(origins), 3), np.float32)
        img[seen] = colour
        pictures[key] = img.reshape(RES, RES, 3)
    return seen.reshape(RES, RES), pictures


def compare(original: Path, result: Path, shift, preview: Path | None = None) -> dict[str, Any]:
    """The look numbers (in %), and a picture original | result | difference per view when `preview`
    is given. `shift` is how far game.mjs moved the result; it is moved back over the original."""
    import numpy as np

    a, b = _load(Path(original)), _load(Path(result))
    b["V"] = b["V"] - np.asarray(shift, float)
    lo, hi = a["V"].min(0), a["V"].max(0)
    centre, radius = (lo + hi) / 2, float(np.linalg.norm(hi - lo)) / 2 * 1.05
    per_view, rows = {}, []
    for name, view in VIEWS.items():
        ma, pa = _draw(a, centre, radius, view)
        mb, pb = _draw(b, centre, radius, view)
        both = ma & mb
        diff = {k: float(np.abs(pa[k] - pb[k]).mean(-1)[both].mean()) if both.any() else 0.0 for k in pa}
        per_view[name] = {"silhouette": float((ma ^ mb).sum() / max((ma | mb).sum(), 1)), **diff}
        if preview is not None:
            heat = np.abs(pa["look"] - pb["look"]).mean(-1, keepdims=True)
            rows.append(np.hstack([pa["look"], pb["look"], np.concatenate([heat * 4, heat * 1.5, heat * 0.5], -1).clip(0, 1)]))
    if preview is not None:
        from PIL import Image

        Image.fromarray((np.vstack(rows) * 255).astype(np.uint8)).save(preview)

    def pct(key: str) -> float:
        return round(100 * float(np.mean([v[key] for v in per_view.values()])), 2)

    worst = max(per_view, key=lambda k: per_view[k]["silhouette"] + per_view[k]["look"])
    return {
        "silhouettePct": pct("silhouette"),
        "lookPct": pct("look"),
        "texturePct": pct("texture"),
        "lightPct": pct("light"),
        "worstView": worst,
    }
