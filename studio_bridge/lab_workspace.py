"""Local generation workspace helpers (not the public Studio site)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PREVIEW_DIR = ROOT / "preview_textures"

# Pinned first in the shelf. Current H0 work, then the 2026-08-16 T2 ladder.
PINNED_GLBS: tuple[tuple[str, str], ...] = (
    ("p1_hd_character.glb", "P1 HD — archer A-pose"),
    ("p1_studio_car.glb", "P1 Standard — vintage sedan"),
    ("p1_mesh_armor.glb", "P1 clay — spiked cuirass"),
    ("h31_ultra_scorpion.glb", "H3.1 Ultra — mech scorpion"),
    ("h31_hd_drill.glb", "H3.1 HD — cordless drill"),
    ("h31_studio_camera.glb", "H3.1 Studio — vintage camera"),
    ("h0_armor_hi3dgen.glb", "Hi3DGen H0 — knight clay"),
    ("h0b_armor_slat12.glb", "Hi3DGen H0b — slat12"),
    ("h0c_armor_flexicubes.glb", "Hi3DGen H0c — FlexiCubes"),
    ("h0d_armor_space.glb", "Hi3DGen H0d — HF Space"),
    ("h0e_armor_space_attrs.glb", "Hi3DGen H0e — Space vertex_attrs"),
    ("h0e_space_ex0.glb", "Hi3DGen H0e — Space example 0 dragon"),
    ("h0f_armor_bust.glb", "Hi3DGen H0f — knight bust crop"),
    ("h0g_armor_bust_nirne.glb", "Hi3DGen H0g — bust NiRNE"),
    ("h0_space_bust.glb", "Hi3DGen official Space — same bust"),
    ("t2_bust_ultra.glb", "N1 — T2 bust crop (1024_cascade after OOM)"),
    ("n2_pixal3d_knight_1024.glb", "N2 — Pixal3D knight 1024 (low-VRAM)"),
    ("n2_pixal3d_knight_1536.glb", "N2 — Pixal3D knight 1536 (low-VRAM)"),
    ("n3_direct3ds2_knight_1024.glb", "N3 — Direct3D-S2 knight 1024 clay"),
    ("n4_step1x3d_knight.glb", "N4 — Step1X-3D knight geometry 384"),
    ("f2_triposr_knight.glb", "Ф2 recon — TripoSR knight (16s, fast tier)"),
    ("armor_t2_v17_realistic.png.glb", "Knight — Realistic 4K+polish"),
    ("preset_high_armor.png.glb", "Knight — High 2K+polish"),
    ("preset_medium_chest.png.glb", "Chest — Medium 2K+soft"),
    ("preset_low_chest.png.glb", "Chest — Low 1K"),
    ("armor_t2_ultra_native_pbr_delight.glb", "Knight — older local delight"),
    ("armor_t2_ultra_native_pbr_png.glb", "Knight — native PBR PNG"),
    ("armor_t2_ultra_native_pbr.glb", "Knight — native PBR WebP"),
)

SMOKE_IMAGE_REFS: tuple[tuple[str, str, str], ...] = (
    (
        "armor",
        "Рыцарь",
        "https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/ref_gold_armor.png",
    ),
    (
        "chest",
        "Сундук",
        "https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev/smoke/ref_chest.png",
    ),
    # Official microsoft/TRELLIS.2 demo inputs (images only — not GLB).
    ("t2_letter_t", "T2 · Letter T", "/preview_textures/_t2_examples/T.png"),
    (
        "t2_crown",
        "T2 · Crown",
        "/preview_textures/_t2_examples/0a34fae7ba57cb8870df5325b9c30ea474def1b0913c19c596655b85a79fdee4.webp",
    ),
    (
        "t2_chair",
        "T2 · Chair",
        "/preview_textures/_t2_examples/7baa867b4790b8596ee120f9b171b727fd9428c41980577a518505507c99d8a0.webp",
    ),
    (
        "t2_boy",
        "T2 · Steampunk boy",
        "/preview_textures/_t2_examples/454e7d8a30486c0635369936e7bec5677b78ae5f436d0e46af0d533738be859f.webp",
    ),
    (
        "t2_bear",
        "T2 · Bear",
        "/preview_textures/_t2_examples/5c80e5e03a3b60b6f03eaf555ba1dafc0e4230c472d7e8c8e2c5ca0a0dfcef10.webp",
    ),
    (
        "t2_statue",
        "T2 · Winged statue",
        "/preview_textures/_t2_examples/52284bf45134c59a94be150a5b18b9cc3619ada4b30ded8d8d0288383b8c016f.webp",
    ),
    (
        "t2_harbor",
        "T2 · Harbor",
        "/preview_textures/_t2_examples/8aa698c59aab48d4ce69a558d9159107890e3d64e522af404d9635ad0be21f88.webp",
    ),
    (
        "t2_aquarium",
        "T2 · Aquarium",
        "/preview_textures/_t2_examples/901d8de4c2011a8502a0decd0adec0fc7418f26165cd52ced64fd44f720353ef.webp",
    ),
)

ALLOWED_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _public_base() -> str:
    return os.getenv("R2_PUBLIC_BASE_URL", "").strip().rstrip("/") or (
        "https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev"
    )


def smoke_image_refs() -> list[dict[str, str]]:
    base = _public_base()
    out: list[dict[str, str]] = []
    for ref_id, label, url in SMOKE_IMAGE_REFS:
        if url.startswith("/"):
            out.append({"id": ref_id, "label": label, "url": url})
            continue
        if url.startswith("https://pub-c826a97383ba4fadbc6436f422b17bfd.r2.dev"):
            suffix = url.split("/smoke/", 1)[-1]
            url = f"{base}/smoke/{suffix}"
        out.append({"id": ref_id, "label": label, "url": url})
    return out


def _label_for(name: str, pinned: dict[str, str]) -> str:
    if name in pinned:
        return pinned[name]
    stem = name.removesuffix(".glb").replace("_", " ")
    return stem


def _thumb_for(glb_path: Path) -> str | None:
    """Cached 3D snapshot, not the source photo. Stale thumbs are ignored."""
    thumb = glb_path.parent / "thumbs" / f"{glb_path.name}.jpg"
    if not thumb.is_file():
        return None
    if thumb.stat().st_mtime + 1 < glb_path.stat().st_mtime:
        return None
    return f"/preview_textures/thumbs/{glb_path.name}.jpg"


def list_local_glbs(
    preview_dir: Path | None = None,
    *,
    limit: int = 40,
) -> list[dict[str, Any]]:
    """Top-level ``*.glb`` in preview_textures, pinned ladder first."""
    folder = Path(preview_dir) if preview_dir else PREVIEW_DIR
    if not folder.is_dir():
        return []

    pinned = dict(PINNED_GLBS)
    found = {path.name: path for path in folder.glob("*.glb") if path.is_file()}

    ordered: list[Path] = []
    seen: set[str] = set()
    for name, _label in PINNED_GLBS:
        path = found.get(name)
        if path is not None:
            ordered.append(path)
            seen.add(name)

    rest = sorted(
        (path for name, path in found.items() if name not in seen),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    ordered.extend(rest)

    models: list[dict[str, Any]] = []
    for path in ordered[: max(1, limit)]:
        stat = path.stat()
        models.append(
            {
                "id": path.name,
                "label": _label_for(path.name, pinned),
                "url": f"/preview_textures/{path.name}",
                "thumb": _thumb_for(path),
                "bytes": stat.st_size,
                "mtime": int(stat.st_mtime),
                "pinned": path.name in pinned,
            }
        )
    return models


def workspace_payload(preview_dir: Path | None = None) -> dict[str, Any]:
    return {
        "refs": smoke_image_refs(),
        "models": list_local_glbs(preview_dir),
    }


def save_lab_thumbnail(
    glb_id: str,
    image_data_url: str,
    preview_dir: Path | None = None,
) -> str:
    """Persist a jpeg data-URL next to the local GLB. Lab-only."""
    import base64

    folder = Path(preview_dir) if preview_dir else PREVIEW_DIR
    name = Path(glb_id).name
    if name != glb_id or not name.lower().endswith(".glb"):
        raise ValueError("id must be a .glb basename")
    if not (folder / name).is_file():
        raise ValueError("unknown model")
    prefix = "data:image/jpeg;base64,"
    if not image_data_url.startswith(prefix):
        raise ValueError("expected jpeg data URL")
    raw = base64.b64decode(image_data_url.split(",", 1)[1], validate=True)
    if len(raw) < 32 or len(raw) > 400_000:
        raise ValueError("bad thumbnail size")
    if raw[:2] != b"\xff\xd8":
        raise ValueError("not a jpeg")
    dest_dir = folder / "thumbs"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{name}.jpg"
    dest.write_bytes(raw)
    return f"/preview_textures/thumbs/{name}.jpg"


def safe_upload_name(original: str) -> str:
    name = Path(original or "image.png").name
    stem = _SAFE_NAME.sub("_", Path(name).stem)[:80] or "image"
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        suffix = ".png"
    return f"{stem}{suffix}"
