"""Cheap CPU delight + optional bump-from-albedo on an existing textured GLB.

Does NOT remesh or re-UV. Replaces albedo PNG in-place and can append a
tangent-space normal map derived from albedo luminance.

This is a hypothesis test before a 48GB MVPainter pod: if retinex flattening
does nothing useful on the gold knight, neural delight may still help, but
we should not burn A6000 install time blindly.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glb_webp_to_png import _read_glb, _write_glb  # noqa: E402


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    return buf.getvalue()


def _append_png(gltf: dict, blob: bytearray, png: bytes) -> int:
    """Append a PNG bufferView + image + texture. Returns texture index."""
    views = gltf.setdefault("bufferViews", [])
    images = gltf.setdefault("images", [])
    textures = gltf.setdefault("textures", [])
    while len(blob) % 4:
        blob += b"\x00"
    offset = len(blob)
    blob += png
    views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(png)})
    images.append({"mimeType": "image/png", "bufferView": len(views) - 1})
    textures.append({"source": len(images) - 1})
    gltf["buffers"] = [{"byteLength": len(blob)}]
    return len(textures) - 1


def _replace_image_png(gltf: dict, blob: bytearray, image_index: int, png: bytes) -> bytearray:
    """Rebuild BIN replacing one image bufferView with new PNG bytes."""
    views = gltf.get("bufferViews") or []
    im = (gltf.get("images") or [])[image_index]
    target = int(im["bufferView"])
    new_blob = bytearray()
    new_views: list[dict] = []
    for i, bv in enumerate(views):
        start = int(bv.get("byteOffset") or 0)
        length = int(bv["byteLength"])
        raw = png if i == target else bytes(blob[start : start + length])
        offset = len(new_blob)
        new_blob += raw
        while len(new_blob) % 4:
            new_blob += b"\x00"
        nv = dict(bv)
        nv["byteOffset"] = offset
        nv["byteLength"] = len(raw)
        new_views.append(nv)
    gltf["bufferViews"] = new_views
    gltf["buffers"] = [{"byteLength": len(new_blob)}]
    im["mimeType"] = "image/png"
    im.pop("uri", None)
    return new_blob


def delight_rgb(img: Image.Image, *, strength: float, blur_px: int) -> Image.Image:
    """Single-scale retinex on luminance; keep chroma. strength 0 = no-op."""
    rgba = img.convert("RGBA")
    rgb = np.asarray(rgba.convert("RGB"), dtype=np.float32) / 255.0
    alpha = np.asarray(rgba.split()[-1])
    lum = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    lum_img = Image.fromarray(np.clip(lum * 255.0, 0, 255).astype(np.uint8), mode="L")
    blur = np.asarray(
        lum_img.filter(ImageFilter.GaussianBlur(radius=max(1, blur_px))),
        dtype=np.float32,
    ) / 255.0
    blur = np.clip(blur, 1e-3, 1.0)
    scale = np.power(np.clip(lum, 1e-4, 1.0) / blur, strength)
    # Keep mean luminance so gold does not go muddy-dark.
    out_lum = np.clip(lum * scale, 0.0, 1.0)
    mean_in = float(np.mean(lum) + 1e-6)
    mean_out = float(np.mean(out_lum) + 1e-6)
    out_lum *= mean_in / mean_out
    chroma = rgb / np.clip(lum[:, :, None], 1e-4, None)
    out = np.clip(chroma * out_lum[:, :, None], 0.0, 1.0)
    rgb8 = (out * 255.0 + 0.5).astype(np.uint8)
    out_img = Image.fromarray(rgb8, mode="RGB").convert("RGBA")
    out_img.putalpha(Image.fromarray(alpha, mode="L"))
    return out_img


def bump_from_albedo(img: Image.Image, *, strength: float) -> Image.Image:
    """OpenGL tangent normal from luminance Sobel. strength ~0.6–1.5."""
    gray = np.asarray(img.convert("L"), dtype=np.float32) / 255.0
    # Sobel
    kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float32)
    ky = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=np.float32)
    pad = np.pad(gray, 1, mode="edge")
    gx = (
        kx[0, 0] * pad[0:-2, 0:-2]
        + kx[0, 1] * pad[0:-2, 1:-1]
        + kx[0, 2] * pad[0:-2, 2:]
        + kx[1, 0] * pad[1:-1, 0:-2]
        + kx[1, 1] * pad[1:-1, 1:-1]
        + kx[1, 2] * pad[1:-1, 2:]
        + kx[2, 0] * pad[2:, 0:-2]
        + kx[2, 1] * pad[2:, 1:-1]
        + kx[2, 2] * pad[2:, 2:]
    )
    gy = (
        ky[0, 0] * pad[0:-2, 0:-2]
        + ky[0, 1] * pad[0:-2, 1:-1]
        + ky[0, 2] * pad[0:-2, 2:]
        + ky[1, 0] * pad[1:-1, 0:-2]
        + ky[1, 1] * pad[1:-1, 1:-1]
        + ky[1, 2] * pad[1:-1, 2:]
        + ky[2, 0] * pad[2:, 0:-2]
        + ky[2, 1] * pad[2:, 1:-1]
        + ky[2, 2] * pad[2:, 2:]
    )
    nx = -gx * strength
    ny = gy * strength
    nz = np.ones_like(nx)
    n = np.stack([nx, ny, nz], axis=-1)
    n /= np.clip(np.linalg.norm(n, axis=-1, keepdims=True), 1e-6, None)
    rgb = ((n * 0.5 + 0.5) * 255.0 + 0.5).astype(np.uint8)
    return Image.fromarray(rgb, mode="RGB")


def _load_image(gltf: dict, blob: bytes, index: int) -> Image.Image:
    views = gltf["bufferViews"]
    im = gltf["images"][index]
    bv = views[int(im["bufferView"])]
    start = int(bv.get("byteOffset") or 0)
    raw = blob[start : start + int(bv["byteLength"])]
    return Image.open(io.BytesIO(raw))


def process(
    src: Path,
    dest: Path,
    *,
    strength: float,
    blur_px: int,
    bump: bool,
    bump_strength: float,
    dump_dir: Path | None,
) -> None:
    gltf, blob_in = _read_glb(src)
    images = gltf.get("images") or []
    if not images:
        raise SystemExit("GLB has no images")
    mats = gltf.get("materials") or []
    if not mats:
        raise SystemExit("GLB has no materials")
    pbr = mats[0].setdefault("pbrMetallicRoughness", {})
    albedo_tex = (pbr.get("baseColorTexture") or {}).get("index")
    if albedo_tex is None:
        raise SystemExit("No baseColorTexture")
    albedo_src = int((gltf["textures"][int(albedo_tex)]).get("source", albedo_tex))
    albedo = _load_image(gltf, blob_in, albedo_src)
    delighted = delight_rgb(albedo, strength=strength, blur_px=blur_px)
    blob = _replace_image_png(gltf, bytearray(blob_in), albedo_src, _png_bytes(delighted))

    if bump:
        nrm = bump_from_albedo(delighted, strength=bump_strength)
        tex_i = _append_png(gltf, blob, _png_bytes(nrm))
        mats[0]["normalTexture"] = {"index": tex_i, "scale": 1.0}

    if dump_dir is not None:
        dump_dir.mkdir(parents=True, exist_ok=True)
        delighted.convert("RGB").resize((1024, 1024)).save(dump_dir / f"{src.stem}_delight_albedo.png")
        if bump:
            nrm.resize((1024, 1024)).save(dump_dir / f"{src.stem}_delight_normal.png")

    _write_glb(dest, gltf, bytes(blob))
    print(f"Wrote {dest} bytes={dest.stat().st_size} delight={strength} bump={bump}")


def main() -> int:
    p = argparse.ArgumentParser(description="Retinex-delight albedo (+ optional bump) in a GLB")
    p.add_argument("glb", type=Path)
    p.add_argument("-o", "--out", type=Path, default=None)
    p.add_argument("--strength", type=float, default=0.45)
    p.add_argument("--blur", type=int, default=48)
    p.add_argument("--bump", action="store_true")
    p.add_argument("--bump-strength", type=float, default=0.9)
    p.add_argument("--dump-maps", action="store_true")
    args = p.parse_args()
    src = args.glb
    dest = args.out or src.with_name(src.stem + "_delight.glb")
    process(
        src,
        dest,
        strength=args.strength,
        blur_px=args.blur,
        bump=args.bump,
        bump_strength=args.bump_strength,
        dump_dir=src.parent if args.dump_maps else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
