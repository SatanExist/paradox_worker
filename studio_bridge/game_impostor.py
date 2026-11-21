"""Impostor for game_prep (impostor: true): the model as pictures, for when it is only a few dozen pixels on screen.

Far off, a prop takes a few dozen pixels and its triangles are wasted. An impostor stands in for it there: a square of
two triangles that faces the camera and shows the model as pictured from that side, three nearest pictures blended,
lit by the game's own light from the pictures' normals, with their depth for a little parallax. This is Ryan Brucks'
octahedral impostor (Fortnite); Amplify Impostors (Unity) and Godot's impostor plugins do the same. Our own code: the
Godot plugins' licences read differently on different pages (MIT, AGPL, credit required).

tools_blender/impostor.py pictures the light model (LOD0, with its baked textures) from 12 x 12 directions over the
upper half-sphere into atlases: colour, depth, occlusion / roughness / metalness, and the normals under each pixel in
12 bins (mean normal + share per bin, each bin lit as its own lobe: one averaged normal per pixel lit the mech's front
6-9 % too bright and its back 31-55 % too dark; with the bins 4.5 % on average, 9 % at worst). The impostor takes
over when the model is under maxScreenPx across (PolyLab's measure, as the LOD levels): the size at which one atlas
pixel is one screen pixel. Not for a rigged model: a picture can't move with its skeleton.
The Godot package (game_godot) adds it after the last LOD level. Never fails the job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

FRAMES = 12  # 144 pictures, as Brucks' and Amplify's defaults go: about 8 degrees apart
FRAME_PX = 85  # 12 x 85 = a 1020 px atlas; see after.impostor.maxScreenPx for the size it serves
PX_FRAME = 1.05  # PolyLab measures a model in a frame 5 % wider than its diagonal (game_godot.LOD_SWITCH_GD)
FILES = ("color", "depth", "orm", "bins")


def add_impostor(model: Path, report: dict[str, Any]) -> None:
    """Adds extraFiles impostor_color.png, impostor_depth.png, impostor_orm.png, impostor_bins.png and
    after.impostor, or a step saying why not."""
    from studio_bridge import tools_ops as t

    steps, after = report["steps"], report["after"]
    if any("skin" in node for node in t._glb_json(model).get("nodes", [])):
        steps.append("no impostor: the model has a skeleton, and a picture of it can't move with it")
        return
    if not t._blender():
        steps.append("no impostor: it is pictured in Blender, and there is none here")
        return
    work = Path(tempfile.mkdtemp(prefix="impostor-"))
    try:
        done = subprocess.run(
            [t._blender(), "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(t.TOOLS_BLENDER / "impostor.py"),
             "--", str(model), str(work), json.dumps({"frames": FRAMES, "framePx": FRAME_PX})],
            capture_output=True, text=True, timeout=900)
        lines = [line for line in done.stdout.splitlines() if line.startswith('{"impostor"')]
        if done.returncode != 0 or not lines or not all((work / f"{k}.png").is_file() for k in FILES):
            steps.append(f"no impostor: {(done.stderr or done.stdout).strip()[-200:]}")
            return
        info = json.loads(lines[-1])["impostor"]
        extra = report.setdefault("extraFiles", {})
        for k in FILES:
            fd, kept = tempfile.mkstemp(suffix=".png")
            os.close(fd)  # copied by name; an open handle would lock it on Windows
            shutil.copyfile(work / f"{k}.png", kept)
            extra[f"impostor_{k}.png"] = kept
    except subprocess.TimeoutExpired:
        steps.append("no impostor: picturing it took too long")
        return
    finally:
        shutil.rmtree(work, ignore_errors=True)
    # One atlas pixel per screen pixel: the bounding sphere (2 * radius) framePx pixels across.
    px = info["framePx"] * PX_FRAME * info["diagonal"] / (2 * info["radius"])
    after["impostor"] = {"frames": info["frames"], "framePx": info["framePx"], "atlasPx": info["frames"] * info["framePx"],
                         "normalBins": info["bins"], "radius": round(info["radius"], 6),
                         "centre": [round(c, 6) for c in info["centre"]], "maxScreenPx": round(px, 1),
                         "seconds": info["seconds"]}
    steps.append(f"impostor for the farthest view: the model pictured from {info['frames'] ** 2} sides "
                 f"({info['frames'] * info['framePx']} px atlases: colour, depth, occlusion/roughness/metalness, and the "
                 f"normals in {info['bins']} direction bins for its own light), for an engine to draw on 2 triangles when "
                 f"the model is under {round(px)} px across (impostor_color.png, impostor_depth.png, impostor_orm.png, "
                 f"impostor_bins.png; {info['seconds']:.0f} s)")
