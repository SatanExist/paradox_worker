"""How a lighter model looks next to the original: the same fixed views rendered on the CPU, compared.

The numbers in game_prep's report measure the surface; this measures the picture a person sees. Both
models are drawn from six fixed views (Embree rays through libigl, no GPU) with their base colour
texture, normal map and metal/roughness, under one fixed light and sky, and compared pixel by pixel:

  silhouettePct  outline that differs: parts gone or grown (pixels in one outline only / both)
  lookPct        mean colour difference where both are drawn, everything on
  texturePct     the same with the texture alone (no light): UVs shifted, seams moved, blurred texture
  lightPct       the same with the light alone (no texture): normals and shape, the "crumpled" look
  noticeablePct  share of the picture that differs at a glance: outline mismatches, and pixels whose
                 colour differs by more than NOTICE after a 5 px blur (so texel noise doesn't count).
                 Means spread a local flaw thin; this one keeps a crumpled lens visible. Mean over
                 views, and noticeableMaxPct for the worst one.

Every run draws the same rays, so a model always gets the same numbers. What it doesn't see: the
viewer's reflections of a room (the sky here is simple), so a result can look shinier in the viewer
than these numbers say.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

RES = 384  # pixels per view side for a model seen at ordinary size; game_prep passes others by purpose
NOTICE = 0.10  # colour difference (0..1) that stands out at a glance, after the blur
TEX = 512  # textures are compared at the size a 384 px view shows them; bigger views get bigger textures
VIEWS = {  # where the camera looks from; the model is Y up
    "front": (0.0, 0.0, 1.0),
    "back": (0.0, 0.0, -1.0),
    "left": (-1.0, 0.0, 0.0),
    "right": (1.0, 0.0, 0.0),
    "top": (0.0, 1.0, 0.0),
    "three-quarter": (0.6, 0.45, 0.66),
}


def _load(path: Path, tex: int = TEX) -> dict[str, Any]:
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
    from studio_bridge.tools_ops import _as_drawn, _world_node

    world = _world_node(path)

    def image(t):
        return None if t is None else np.asarray(t.convert("RGB").resize((tex, tex), Image.BOX), np.float32) / 255

    verts, faces, normals, uvs, owner, mats, offset = [], [], [], [], [], [], 0
    for node in scene.graph.nodes_geometry:
        matrix, name = scene.graph[node]
        if world is not None:
            matrix = world @ matrix
        geom = scene.geometry.get(name)
        if not isinstance(geom, trimesh.Trimesh) or len(geom.faces) == 0:
            continue
        gv, gf, gn, corner = _as_drawn(geom)
        n = gn @ matrix[:3, :3].T
        verts.append(trimesh.transform_points(gv, matrix))
        normals.append(n / np.linalg.norm(n, axis=1, keepdims=True).clip(1e-12))
        faces.append(gf + offset)
        uv = getattr(geom.visual, "uv", None)
        uvs.append(np.asarray(uv, float)[corner] if uv is not None and len(uv) == len(geom.vertices) else np.zeros((len(gv), 2)))
        owner.append(np.full(len(geom.faces), len(mats)))
        mat = getattr(geom.visual, "material", None)
        factor = getattr(mat, "baseColorFactor", None)
        metal, rough = getattr(mat, "metallicFactor", None), getattr(mat, "roughnessFactor", None)
        glow = getattr(mat, "emissiveFactor", None)
        mats.append({
            # Light a part gives off: Rodin's models carry all their colour there (black base colour), and
            # unread, the pump looked plain white to every check.
            "glowFactor": np.asarray(glow if glow is not None else [0, 0, 0], np.float32)[:3],
            "glow": image(getattr(mat, "emissiveTexture", None)),
            "factor": np.asarray(factor if factor is not None else [255, 255, 255, 255], np.float32)[:3] / 255,
            "base": image(getattr(mat, "baseColorTexture", None)),
            "normal": image(getattr(mat, "normalTexture", None)),
            "mr": image(getattr(mat, "metallicRoughnessTexture", None)),
            "metal": 1.0 if metal is None else float(metal),
            "rough": 1.0 if rough is None else float(rough),
        })
        offset += len(gv)
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


def _draw(m: dict[str, Any], centre, radius: float, view, res: int = RES) -> tuple[Any, dict[str, Any]]:
    """One view: the outline and three pictures (everything, texture alone, light alone)."""
    import igl.embree
    import numpy as np

    d = -np.asarray(view, float)
    d /= np.linalg.norm(d)
    up = np.array([0.0, 1.0, 0.0]) if abs(d[1]) < 0.9 else np.array([0.0, 0.0, -1.0])
    right = np.cross(d, up)
    right /= np.linalg.norm(right)
    up = np.cross(right, d)
    s = (np.arange(res) + 0.5) / res * 2 - 1
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
    glow = np.zeros((len(f), 3), np.float32)
    metal, rough = np.zeros(len(f)), np.ones(len(f))
    for i, mat in enumerate(m["mats"]):
        sel = m["owner"][f] == i
        if not sel.any():
            continue
        albedo[sel] = mat["factor"]
        if mat["glowFactor"].any():
            glow[sel] = mat["glowFactor"] * (_sample(mat["glow"], uv[sel]) if mat["glow"] is not None else 1)
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
        ("look", (albedo * (1 - metal[:, None]) * lambert + shiny + glow).clip(0, 1)),
        ("texture", (albedo + glow).clip(0, 1) if glow.any() else albedo),
        ("light", np.repeat(lambert * 0.7, 3, 1)),
    ):
        img = np.zeros((len(origins), 3), np.float32)
        img[seen] = colour
        pictures[key] = img.reshape(res, res, 3)
    return seen.reshape(res, res), pictures


def _sphere(k: int):
    """k directions spread evenly over the sphere (a Fibonacci spiral: the same every run)."""
    import numpy as np

    i = np.arange(k) + 0.5
    phi = np.arccos(1 - 2 * i / k)
    theta = np.pi * (1 + 5**0.5) * i
    return np.stack([np.cos(theta) * np.sin(phi), np.cos(phi), np.sin(theta) * np.sin(phi)], 1)


def _origins(centre, radius: float, view, res: int):
    """Where the rays of one view start, a pixel each, row by row (as _draw lays them out)."""
    import numpy as np

    d = -np.asarray(view, float)
    d /= np.linalg.norm(d)
    up = np.array([0.0, 1.0, 0.0]) if abs(d[1]) < 0.9 else np.array([0.0, 0.0, -1.0])
    right = np.cross(d, up)
    right /= np.linalg.norm(right)
    up = np.cross(right, d)
    s = (np.arange(res) + 0.5) / res * 2 - 1
    xs, ys = np.meshgrid(s, -s)
    return (centre - d * (2 * radius) + (xs[..., None] * right + ys[..., None] * up) * radius).reshape(-1, 3)


def _drawn(m: dict[str, Any], centre, radius: float, view, res: int):
    """Where a view meets the model at all, and which face turned towards it it meets (-1: none): a viewer
    draws glTF faces one side only, so where it meets the model but no such face, it shows what is behind."""
    import igl.embree
    import numpy as np

    d = -np.asarray(view, float)
    d /= np.linalg.norm(d)
    origins = _origins(centre, radius, view, res)
    rays = np.repeat(d[None], len(origins), 0)
    V, F = m["V"], m["F"]
    facing = np.flatnonzero(np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]) @ d < 0)
    met = igl.embree.line_mesh_intersection(origins, rays, V, F)[:, 0] >= 0
    shown = np.full(len(origins), -1, np.int64)
    if len(facing):
        hit = igl.embree.line_mesh_intersection(origins, rays, V, F[facing])[:, 0].astype(np.int64)
        shown[hit >= 0] = facing[hit[hit >= 0]]
    return met.reshape(res, res), shown.reshape(res, res)


SEE_THROUGH_VIEWS = 26  # all round: a slit shows through from a few angles only (the knight's, from above)


def see_through(original: Path, result: Path, shift, res: int = RES) -> dict[str, int]:
    """Pixels where a viewer would see through the result (it has only back faces there) while the original
    is drawn, over SEE_THROUGH_VIEWS views; the six views above draw both sides and miss them. A face left
    out as hidden that showed through a slit after all leaves exactly this, as does a triangle a cut folded
    over. Returns the total, the biggest patch of them in one view (a hole is a patch: single pixels
    scattered over the views are an edge grazed), and the original's faces drawn there (numbered as
    tools_ops._shaded numbers them)."""
    import numpy as np
    from scipy import ndimage

    a, b = _load(Path(original)), _load(Path(result))
    b["V"] = b["V"] - np.asarray(shift, float)
    lo, hi = a["V"].min(0), a["V"].max(0)
    centre, radius = (lo + hi) / 2, float(np.linalg.norm(hi - lo)) / 2 * 1.05
    total, biggest, faces = 0, 0, set()
    for view in _sphere(SEE_THROUGH_VIEWS):
        _, drawn = _drawn(a, centre, radius, view, res)
        met, shown = _drawn(b, centre, radius, view, res)
        inside = ndimage.binary_erosion(drawn >= 0, iterations=1)  # not the outline's edge pixels
        through = inside & met & (shown < 0)
        total += int(through.sum())
        faces.update(int(f) for f in drawn[through])
        patches, count = ndimage.label(through, structure=np.ones((3, 3)))
        if count:
            biggest = max(biggest, int(np.bincount(patches.reshape(-1))[1:].max()))
    return {"seeThroughPx": total, "seeThroughPatchPx": biggest, "originalFaces": sorted(faces)}


TORN_STRETCH = 4.0  # a triangle whose texture is this many times bigger or smaller than the original's there


def torn(original: Path, result: Path, shift) -> dict[str, float] | None:
    """How much of the result's surface (%) shows its texture stretched or squeezed TORN_STRETCH times or
    more against the original at the same spot: texture pixels per area of each result triangle over the
    original's on the face nearest it, each material's usual ratio taken as 1 (a baked atlas has a scale
    of its own). A cut that joins pieces of a texture laid out apart ("UV seams loosened") lays triangles
    across the gap and draws the gap's strip on them: the Rodin pump at 20k and 10k, 1.3 and 2.5% of it
    in streaks up close, against 0.2% at most on cuts that kept their seams or were baked. The six views
    above blur the streaks into their surroundings. None when the original has no texture."""
    import igl
    import numpy as np

    a, b = _load(Path(original)), _load(Path(result))
    if not any(m["base"] is not None or m["glow"] is not None for m in a["mats"]):
        return None
    b["V"] = b["V"] - np.asarray(shift, float)

    def density(m):
        p, t = m["V"][m["F"]], m["UV"][m["F"]]
        area = np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1) / 2
        d1, d2 = t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]
        return area, np.abs(d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]) / 2

    area_a, uv_a = density(a)
    area_b, uv_b = density(b)
    _, near, _ = igl.point_mesh_squared_distance(b["V"][b["F"]].mean(1), a["V"], a["F"])
    seen = (area_b > 0) & (area_a[near] > 0) & (uv_a[near] > 0)
    ratio = np.zeros(len(area_b))
    ratio[seen] = (uv_b[seen] / area_b[seen]) / (uv_a[near][seen] / area_a[near][seen])
    off = seen & (ratio == 0)  # texture squeezed to a line: a streak of one colour
    for owner in np.unique(b["owner"]):
        mine = seen & (b["owner"] == owner) & (ratio > 0)
        if not mine.any():
            continue
        order = np.argsort(ratio[mine])  # the usual ratio: the area-weighted median
        weights = np.cumsum(area_b[mine][order])
        usual = ratio[mine][order][np.searchsorted(weights, weights[-1] / 2)]
        rel = ratio[mine] / usual
        off[np.flatnonzero(mine)] = (rel > TORN_STRETCH) | (rel < 1 / TORN_STRETCH)
    total = area_b[seen].sum()
    return {"tornPct": round(100 * float(area_b[off].sum() / total), 2) if total > 0 else 0.0}


# How sharply light turns between neighbouring pixels (0..1 picture, Sobel / 8) for a crease to count:
# camera, drill and watch at 10k (marked crumpled by eye) had new creases on 1.3-2.1% of their surface,
# at 20k (marked fine) 0.45-0.67%, the Rodin pump crumpled at 10-20k 3-3.6%; the low-poly dragon at 2k,
# faceted like its original, 0.8% (2026-10-29).
CREASE = 0.01


def _sharpness(img):
    import numpy as np
    from scipy import ndimage

    g = img.mean(-1)
    return np.hypot(ndimage.sobel(g, 0), ndimage.sobel(g, 1)) / 8


def compare(original: Path, result: Path, shift, preview: Path | None = None, res: int = RES) -> dict[str, Any]:
    """The look numbers (in %), and a picture original | result | difference per view when `preview`
    is given. `shift` is how far game.mjs moved the result; it is moved back over the original."""
    import numpy as np
    from scipy import ndimage

    tex = TEX if res <= RES else 2 * TEX  # the blur that judges "at a glance" stays 5 screen pixels at any size
    a, b = _load(Path(original), tex), _load(Path(result), tex)
    b["V"] = b["V"] - np.asarray(shift, float)
    lo, hi = a["V"].min(0), a["V"].max(0)
    centre, radius = (lo + hi) / 2, float(np.linalg.norm(hi - lo)) / 2 * 1.05
    per_view, rows = {}, []
    for name, view in VIEWS.items():
        ma, pa = _draw(a, centre, radius, view, res)
        mb, pb = _draw(b, centre, radius, view, res)
        both, union = ma & mb, ma | mb
        diff = {k: float(np.abs(pa[k] - pb[k]).mean(-1)[both].mean()) if both.any() else 0.0 for k in pa}
        glance = np.where(ma ^ mb, 1.0, np.abs(pa["look"] - pb["look"]).mean(-1))
        glance = ndimage.uniform_filter(glance, 5)
        # Creases the original hasn't: light that turns sharply on the result where the original's is smooth
        # (its sharpness spread over 5 px, so a crease moved by a pixel or two is the same crease).
        inner = ndimage.binary_erosion(both, iterations=2)
        new = ndimage.uniform_filter(_sharpness(pb["light"]), 3) - ndimage.maximum_filter(_sharpness(pa["light"]), 5)
        per_view[name] = {
            "silhouette": float((ma ^ mb).sum() / max(union.sum(), 1)),
            "noticeable": float((glance[union] > NOTICE).mean()) if union.any() else 0.0,
            "crease": float((new[inner] > CREASE).mean()) if inner.any() else 0.0,
            **diff,
        }
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
        "noticeablePct": pct("noticeable"),
        "noticeableMaxPct": round(100 * max(v["noticeable"] for v in per_view.values()), 2),
        "creasePct": pct("crease"),
        "worstView": worst,
    }
