"""Backfill timing + polycount table for front clay A/B artifacts.

Reads local GLBs + matching track_a_*.log executionTime / inference_ms when present.
"""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# label, glb, optional log
ARTIFACTS = [
    ("Track A seed42", "model-armor-clay-seed42.glb", None),
    ("D' 1024+50+500k", "model-armor-clay-sampler50-pro42.glb", "track_a_axis_d_pro.log"),
    ("F@D' project0.5", "model-armor-clay-sampler50-pro-rp05.glb", "track_a_axis_f_dprime_rp05.log"),
    ("E 1024+700k", "model-armor-clay-sampler50-pro-e700.glb", "track_a_axis_e_dprime_700.log"),
    ("C@D' 1536+500k", "model-armor-clay-sampler50-pro-1536.glb", "track_a_axis_c_dprime_1536.log"),
    ("C+E best 1536+700k", "model-armor-clay-sampler50-pro-1536-e700.glb", "track_a_axis_ce_1536_700.log"),
    ("tokens 98k", "model-armor-clay-sampler50-pro-1536-tok98k.glb", "track_a_axis_tokens_98k.log"),
    ("G maxq no-remesh", "model-armor-clay-maxq-pro42.glb", "track_a_axis_g_maxq_pro.log"),
    ("G+F remesh+p0.9", "model-armor-clay-maxq-remesh42.glb", "track_a_axis_g_remesh_project.log"),
]


def glb_stats(path: Path) -> tuple[int, int, int]:
    data = path.read_bytes()
    json_len = struct.unpack_from("<I", data, 12)[0]
    chunk = json.loads(data[20 : 20 + json_len])
    accessors = chunk.get("accessors") or []
    verts = faces = 0
    for mesh in chunk.get("meshes") or []:
        for prim in mesh.get("primitives") or []:
            attrs = prim.get("attributes") or {}
            pos = attrs.get("POSITION")
            if pos is not None and pos < len(accessors):
                verts += int(accessors[pos].get("count") or 0)
            idx = prim.get("indices")
            if idx is not None and idx < len(accessors):
                faces += int(accessors[idx].get("count") or 0) // 3
    return verts, faces, path.stat().st_size


def read_log_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")
    return raw.decode("utf-8", errors="replace")


def parse_log_timing(path: Path) -> dict:
    text = read_log_text(path)
    out: dict = {}
    patterns = {
        "execution_ms": r"executionTime['\"]?\s*:\s*(\d+)",
        "delay_ms": r"delayTime['\"]?\s*:\s*(\d+)",
        "inference_ms": r"inference_ms['\"]?\s*:\s*(\d+)",
        "model_load_ms": r"model_load_ms['\"]?\s*:\s*(\d+)",
        "glb_export_ms": r"glb_export_ms['\"]?\s*:\s*(\d+)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            out[key] = int(m.group(1))
    return out


def main() -> None:
    print(
        f"{'label':<24} {'verts':>8} {'faces':>8} {'MB':>6} "
        f"{'infer_s':>8} {'exec_s':>8} {'load_s':>7}"
    )
    for label, glb_name, log_name in ARTIFACTS:
        glb = ROOT / glb_name
        if not glb.is_file():
            print(f"{label:<24} MISSING {glb_name}")
            continue
        verts, faces, size = glb_stats(glb)
        timing = {}
        if log_name:
            log_path = ROOT / log_name
            if log_path.is_file():
                timing = parse_log_timing(log_path)
        infer = timing.get("inference_ms")
        exec_ = timing.get("execution_ms")
        load = timing.get("model_load_ms")
        print(
            f"{label:<24} {verts:8d} {faces:8d} {size/1e6:6.2f} "
            f"{(infer/1000) if infer else float('nan'):8.1f} "
            f"{(exec_/1000) if exec_ else float('nan'):8.1f} "
            f"{(load/1000) if load else float('nan'):7.1f}"
        )


if __name__ == "__main__":
    main()
