"""Patch glTF PBR factors inside a GLB (no GPU).

TRELLIS.2 texturing often exports metallicFactor=1.0 which makes muddy
albedo look like oily metal. Default: clamp metallic to 0.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


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
    # Pad JSON to 4-byte boundary with spaces
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


def patch_pbr(
    path: Path,
    *,
    metallic: float | None,
    roughness: float | None,
    out: Path | None = None,
) -> Path:
    gltf, bin_blob = _read_glb(path)
    mats = gltf.get("materials") or []
    if not mats:
        raise ValueError("No materials in GLB")
    for mat in mats:
        pbr = mat.setdefault("pbrMetallicRoughness", {})
        if metallic is not None:
            pbr["metallicFactor"] = float(metallic)
        if roughness is not None:
            pbr["roughnessFactor"] = float(roughness)
    dest = out or path
    _write_glb(dest, gltf, bin_blob)
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description="Clamp GLB metallic/roughness factors")
    parser.add_argument("glb", type=Path)
    parser.add_argument("--metallic", type=float, default=0.0)
    parser.add_argument("--roughness", type=float, default=None)
    parser.add_argument("-o", "--out", type=Path, default=None)
    args = parser.parse_args()
    dest = patch_pbr(
        args.glb,
        metallic=args.metallic,
        roughness=args.roughness,
        out=args.out,
    )
    print(f"Patched -> {dest.resolve()} metallic={args.metallic} roughness={args.roughness}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
