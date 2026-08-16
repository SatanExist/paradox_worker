"""CPU material polish on a textured GLB (no remesh, same UVs).

Not TRELLIS.2 Stage 3. After official PBR bake: mild retinex on albedo
(less baked photo lighting) + optional tangent bump from luminance.

Eyes (gold knight, 2026-08-16): more convincing metal than raw T2 maps.
Not a learned normal; game engines may disagree with the viewer.
"""

from __future__ import annotations

import io
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


def _read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    magic, _version, length = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        raise ValueError(f"Not a GLB: {path}")
    json_len, json_type = struct.unpack_from("<II", data, 12)
    if json_type != 0x4E4F534A:
        raise ValueError("First GLB chunk is not JSON")
    json_end = 20 + json_len
    gltf = json.loads(data[20:json_end])
    bin_blob = b""
    if json_end + 8 <= length:
        bin_len, bin_type = struct.unpack_from("<II", data, json_end)
        if bin_type == 0x004E4942:
            bin_blob = data[json_end + 8 : json_end + 8 + bin_len]
    return gltf, bin_blob


def _write_glb(path: Path, gltf: dict, bin_blob: bytes) -> None:
    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(json_bytes) % 4:
        json_bytes += b" "
    bin_padded = bytearray(bin_blob)
    while len(bin_padded) % 4:
        bin_padded += b"\x00"
    total = 12 + 8 + len(json_bytes) + (8 + len(bin_padded) if bin_padded else 0)
    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, total)
    out += struct.pack("<II", len(json_bytes), 0x4E4F534A)
    out += json_bytes
    if bin_padded:
        out += struct.pack("<II", len(bin_padded), 0x004E4942)
        out += bin_padded
    path.write_bytes(out)


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    return buf.getvalue()


def _append_png(gltf: dict, blob: bytearray, png: bytes) -> int:
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
    rgba = img.convert("RGBA")
    rgb = np.asarray(rgba.convert("RGB"), dtype=np.float32) / 255.0
    alpha = np.asarray(rgba.split()[-1])
    lum = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    lum_img = Image.fromarray(np.clip(lum * 255.0, 0, 255).astype(np.uint8), mode="L")
    blur = (
        np.asarray(
            lum_img.filter(ImageFilter.GaussianBlur(radius=max(1, blur_px))),
            dtype=np.float32,
        )
        / 255.0
    )
    blur = np.clip(blur, 1e-3, 1.0)
    scale = np.power(np.clip(lum, 1e-4, 1.0) / blur, strength)
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
    gray = np.asarray(img.convert("L"), dtype=np.float32) / 255.0
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


def polish_glb_file(
    src: Path,
    dest: Path | None = None,
    *,
    strength: float = 0.45,
    blur_px: int = 48,
    bump: bool = True,
    bump_strength: float = 0.9,
) -> Path:
    dest = dest or src
    gltf, blob_in = _read_glb(src)
    if not (gltf.get("images") or []):
        raise ValueError("GLB has no images")
    mats = gltf.get("materials") or []
    if not mats:
        raise ValueError("GLB has no materials")
    pbr = mats[0].setdefault("pbrMetallicRoughness", {})
    albedo_tex = (pbr.get("baseColorTexture") or {}).get("index")
    if albedo_tex is None:
        raise ValueError("No baseColorTexture")
    tex = gltf["textures"][int(albedo_tex)]
    albedo_src = int(tex.get("source", albedo_tex))
    views = gltf["bufferViews"]
    im = gltf["images"][albedo_src]
    bv = views[int(im["bufferView"])]
    start = int(bv.get("byteOffset") or 0)
    raw = blob_in[start : start + int(bv["byteLength"])]
    albedo = Image.open(io.BytesIO(raw))
    delighted = delight_rgb(albedo, strength=strength, blur_px=blur_px)
    blob = _replace_image_png(gltf, bytearray(blob_in), albedo_src, _png_bytes(delighted))
    if bump:
        nrm = bump_from_albedo(delighted, strength=bump_strength)
        tex_i = _append_png(gltf, blob, _png_bytes(nrm))
        mats[0]["normalTexture"] = {"index": tex_i, "scale": 1.0}
    _write_glb(dest, gltf, bytes(blob))
    return dest
