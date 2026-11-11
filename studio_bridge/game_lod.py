"""LOD chain for game_prep: lighter copies of the model for when it is seen from farther off.

Each level is its own cut of the original, baked onto its own textures, half as big as the level before's (1024,
512, 256 px under a 2048 model). Way B of the trial (2026-11-11): cutting the levels from LOD0 and keeping its
textures stretched triangles over the empty texture between UV islands (the spider at 1752 triangles: black
patches, 28.6% of the picture off even at 192 px; at 2498 already black slivers), and weighing the UVs in the cut
changed nothing (28.4 -> 28.6). Baked again from the original, the spider's 2500 read 3.15% (6.75 cut from LOD0).

A level is looked at as big as it will be drawn: LOD k at the regular view's size >> k (192, 96, 48 px across
for the 384 px one), i.e. 2^k times farther off, and kept when it looks like the original there
(the baked limit). It tries half the triangles of the level before, then a third when half passes; when half
fails the chain ends: a level less than twice as light saves too little for its textures (the user's rule,
2026-11-11: the scorpion's and rover's only level was 70% of LOD0, for a file 40% heavier).
On six bench models (2026-11-11): drill 10000 -> 3332 -> 1108, skeleton 10000 -> 3332, spider 5000 -> 2500,
mech 20000 -> 10000; scorpion and rover none.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

LEVELS = 3
MIN_TEXTURE = 256
MIN_TRIS = 200  # under this a level isn't worth a draw call of its own


def add_lods(in_path: Path, out_path: Path, params: dict[str, Any], report: dict[str, Any]) -> None:
    """Adds the levels to `report` (after.lod, a step, extraFiles["lods.glb"]: LOD0 and the levels in one file,
    nodes model_LOD0, model_LOD1, ...). The main file stays LOD0 alone. Never fails the job: a level that can't be
    made ends the chain, and the report says why."""
    from studio_bridge import tools_ops as t

    after, steps = report["after"], report["steps"]
    if not after.get("textureMaxPx") or "shift" not in report:
        steps.append("no LOD levels: they are baked, and this cut wasn't")
        return
    purpose_name, purpose = t._purpose(params)
    ok = float(params.get("maxNoticeablePct") or purpose["bakeOkPct"])
    size0, res0 = int(after["textureMaxPx"]), int(purpose["res"])
    keep = {k: params[k] for k in ("purpose", "regularize") if k in params}
    levels = [{"level": 0, "triangles": after["triangles"], "textureMaxPx": size0}]
    files: list[tuple[Path, list[float]]] = [(out_path, [0.0, 0.0, 0.0])]
    tried: list[dict[str, Any]] = []
    why = "three levels made"
    prev = after["triangles"]
    try:
        for k in range(1, LEVELS + 1):
            size, res = max(MIN_TEXTURE, size0 >> k), res0 >> k
            pick = None
            for n in (prev // 2, prev // 3):
                if n < MIN_TRIS:
                    break
                fd, name = tempfile.mkstemp(suffix=".glb")
                os.close(fd)  # written by name; an open handle would lock it on Windows
                path = Path(name)
                try:
                    made = t._game_prep(in_path, path, {**keep, "targetTris": n, "textureSize": size, "forBake": True, "fill": True, "lookRes": res})
                except Exception as exc:  # a bake that failed or ran too long: no level here
                    path.unlink(missing_ok=True)
                    tried.append({"level": k, "targetTris": n, "failed": str(exc)[:120]})
                    break
                for extra in (made.get("extraFiles") or {}).values():
                    Path(extra).unlink(missing_ok=True)
                seen = made["after"].get("look", {}).get("noticeablePct")
                tried.append({"level": k, "targetTris": n, "triangles": made["after"]["triangles"], "noticeablePct": seen})
                if seen is None or seen > ok:
                    path.unlink(missing_ok=True)
                    break
                if pick:
                    pick[1].unlink(missing_ok=True)
                pick = (made, path, seen)
            if pick is None:
                why = (f"LOD{k} at half the triangles looked off at its size" if prev // 2 >= MIN_TRIS
                       else f"LOD{k} would be under {MIN_TRIS} triangles")
                break
            made, path, seen = pick
            offset = [a - b for a, b in zip(report["shift"], made["shift"])]  # onto LOD0: each cut sits on the floor its own way
            files.append((path, offset))
            levels.append({"level": k, "triangles": made["after"]["triangles"], "textureMaxPx": size, "maxScreenPx": res,
                           "noticeablePct": seen, "fileMb": made["after"].get("fileMb")})
            prev = made["after"]["triangles"]
        if len(files) == 1:
            steps.append(f"no LOD levels: {why}")
            after["lod"] = {"levels": levels, "tried": tried}
            return
        fd, name = tempfile.mkstemp(suffix=".glb")
        os.close(fd)
        packed = Path(name)
        node = shutil.which("node") or "node"
        done = subprocess.run([node, str(t.TOOLS_NODE / "lod.mjs"), str(packed), "model",
                               *(f"{p}@{','.join(f'{x:.6g}' for x in off)}" for p, off in files)],
                              capture_output=True, text=True, timeout=300)
        if done.returncode != 0:
            packed.unlink(missing_ok=True)
            steps.append(f"LOD levels made but not packed: {done.stderr.strip()[-200:]}")
            after["lod"] = {"levels": levels, "tried": tried}
            return
        nodes = json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])["nodes"]
        report.setdefault("extraFiles", {})["lods.glb"] = str(packed)
        after["lod"] = {"levels": levels, "tried": tried, "file": "lods.glb", "nodes": nodes,
                        "fileMb": round(packed.stat().st_size / 1048576, 2)}
        chain = " -> ".join(str(level["triangles"]) for level in levels)
        switch = ", ".join(f"LOD{level['level']} under {level['maxScreenPx']} px" for level in levels[1:])
        steps.append(f"LOD levels {chain} triangles, each baked on its own smaller textures; switch when the model is "
                     f"this big across on screen: {switch}" + ("" if len(levels) > LEVELS else f" ({why})"))
    finally:
        for path, _ in files[1:]:
            path.unlink(missing_ok=True)
