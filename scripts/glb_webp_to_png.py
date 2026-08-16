"""Rewrite GLB image/webp (EXT_texture_webp) to image/png. No GPU.

TRELLIS.2 textured export often stores albedo + metallicRoughness as WebP.
Studio / some three.js / Blender paths miss those maps unless the extension
is handled. PNG is larger but loads as plain glTF.
"""

from __future__ import annotations

import argparse
import io
import json
import struct
from pathlib import Path

from PIL import Image


def _read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        raise ValueError(f"Not a GLB: {path}")
    json_len, json_type = struct.unpack_from("<II", data, 12)
    if json_type != 0x4E4F534A:
        raise ValueError("First GLB chunk is not JSON")
    json_start = 20
    json_end = json_start + json_len
    gltf = json.loads(data[json_start:json_end])
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
    bin_padded = bin_blob
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


def webp_to_png(src: Path, dest: Path) -> dict:
    gltf, blob = _read_glb(src)
    views = gltf.get("bufferViews") or []
    images = gltf.get("images") or []
    image_views = {int(im["bufferView"]) for im in images if "bufferView" in im}

    new_blob = bytearray()
    new_views: list[dict] = []
    converted = 0
    for i, bv in enumerate(views):
        start = int(bv.get("byteOffset") or 0)
        length = int(bv["byteLength"])
        raw = blob[start : start + length]
        if i in image_views:
            img = Image.open(io.BytesIO(raw))
            buf = io.BytesIO()
            img.save(buf, format="PNG", compress_level=6)
            raw = buf.getvalue()
            converted += 1
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
    for im in images:
        im["mimeType"] = "image/png"
        im.pop("uri", None)
    for tex in gltf.get("textures") or []:
        ext = (tex.get("extensions") or {}).get("EXT_texture_webp")
        if ext and "source" in ext:
            tex["source"] = ext["source"]
        if "extensions" in tex:
            tex["extensions"].pop("EXT_texture_webp", None)
            if not tex["extensions"]:
                tex.pop("extensions")
    used = [e for e in (gltf.get("extensionsUsed") or []) if e != "EXT_texture_webp"]
    if used:
        gltf["extensionsUsed"] = used
    else:
        gltf.pop("extensionsUsed", None)
    req = [e for e in (gltf.get("extensionsRequired") or []) if e != "EXT_texture_webp"]
    if req:
        gltf["extensionsRequired"] = req
    else:
        gltf.pop("extensionsRequired", None)

    _write_glb(dest, gltf, bytes(new_blob))
    return {
        "images": converted,
        "src_bytes": src.stat().st_size,
        "dst_bytes": dest.stat().st_size,
    }


def dump_maps(src: Path, out_dir: Path, max_edge: int = 1024) -> list[Path]:
    gltf, blob = _read_glb(src)
    views = gltf.get("bufferViews") or []
    written: list[Path] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, im in enumerate(gltf.get("images") or []):
        bv = views[int(im["bufferView"])]
        raw = blob[int(bv.get("byteOffset") or 0) : int(bv.get("byteOffset") or 0) + int(bv["byteLength"])]
        img = Image.open(io.BytesIO(raw))
        img.thumbnail((max_edge, max_edge))
        dest = out_dir / f"{src.stem}_map{i}.png"
        img.save(dest, format="PNG")
        written.append(dest)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert GLB WebP textures to PNG")
    parser.add_argument("glb", type=Path)
    parser.add_argument("-o", "--out", type=Path, default=None)
    parser.add_argument("--dump-maps", action="store_true")
    args = parser.parse_args()
    src = args.glb
    dest = args.out or src.with_name(src.stem + "_png.glb")
    stats = webp_to_png(src, dest)
    print(f"Wrote {dest} images={stats['images']} {stats['src_bytes']} -> {stats['dst_bytes']}")
    if args.dump_maps:
        paths = dump_maps(src, src.parent)
        for p in paths:
            print(f"map {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
