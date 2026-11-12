"""Collision for game_prep (collision: true): convex pieces that hug the model, for game physics.

Engines collide with a few simple convex shapes, not with the model's triangles. CoACD (MIT, deterministic with a
fixed seed) cuts the model into up to 16 convex pieces of up to 32 points each (Unreal's own auto-collision limit is
16 pieces; small pieces keep physics cheap).

The pieces are made from the ORIGINAL, in a separate process that starts together with the job, so it runs while the
model is cut and baked. Trial 2026-11-12 (drill, skeleton, mech): the bake wasn't slowed, the wait added was only what
CoACD ran past the bake (0 / ~25 / ~75 s), and the pieces fit as well as pieces made from the finished model.

Out: extraFiles["collision.glb"] (one mesh per piece, nodes UCX_model_00, UCX_model_01, ...: Unreal's collision
naming; in Unity, a convex Mesh Collider per piece), after.collision, and the pieces themselves for the Godot package.
Known weak spot: thin parts sticking out (the drill's chuck) can stay outside every piece.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

MAX_PIECES = 16
MAX_POINTS = 32
LIMIT_S = 900  # from the job's start; a slow server gets this long, then the job goes on without collision


class Collision:
    """Started with the job; finish() collects the pieces once the model is done."""

    def __init__(self, in_path: Path):
        fd, name = tempfile.mkstemp(suffix=".npz")
        os.close(fd)
        self.out = Path(name)
        self.started = time.time()
        self.proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), str(in_path), str(self.out)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
        )

    def stop(self) -> None:
        """The job failed or is done: no process left behind, no temp file."""
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.communicate()
        self.out.unlink(missing_ok=True)

    def finish(self, report: dict[str, Any], shift: list[float] | None) -> list | None:
        """Waits for the pieces, moves them where the job moved the model, writes collision.glb. Returns the pieces
        (a list of (points, triangles)) for the Godot package, or None with a step that says why. Never fails the job."""
        import numpy as np

        after, steps = report["after"], report["steps"]
        if shift is None:  # every cut reports it; without it the pieces can't be put on the model
            self.stop()
            after["collision"] = {"why": "the job didn't say where it put the model"}
            steps.append("no collision: the job didn't say where it put the model")
            return None
        job_done = time.time()
        try:
            _, err = self.proc.communicate(timeout=max(1.0, LIMIT_S - (job_done - self.started)))
        except subprocess.TimeoutExpired:
            self.stop()
            after["collision"] = {"why": f"took over {LIMIT_S} s"}
            steps.append(f"no collision: making it took over {LIMIT_S} s")
            return None
        waited = round(time.time() - job_done, 1)
        if self.proc.returncode != 0:
            why = (err or "").strip().splitlines()[-1:] or ["it stopped"]
            self.out.unlink(missing_ok=True)
            after["collision"] = {"why": why[0][:160]}
            steps.append(f"no collision: {why[0][:160]}")
            return None
        with np.load(self.out) as z:
            pieces = [(z[f"v{i}"] + np.asarray(shift, float), z[f"f{i}"]) for i in range(int(z["n"]))]
            made_s = float(z["seconds"])
        self.out.unlink(missing_ok=True)
        path = _write_glb(pieces)
        report.setdefault("extraFiles", {})["collision.glb"] = str(path)
        after["collision"] = {"file": "collision.glb", "pieces": len(pieces), "points": int(sum(len(v) for v, _ in pieces)),
                              "seconds": round(made_s, 1), "waitedS": waited}
        steps.append(f"collision.glb: {len(pieces)} convex pieces made from the original alongside the job "
                     f"({round(made_s)} s, {waited} s of it after the model was done)")
        return pieces


def _write_glb(pieces: list) -> Path:
    import trimesh

    scene = trimesh.Scene()
    for i, (v, f) in enumerate(pieces):
        scene.add_geometry(trimesh.Trimesh(v, f, process=False), node_name=f"UCX_model_{i:02d}", geom_name=f"collision_{i:02d}")
    fd, name = tempfile.mkstemp(suffix=".glb")
    os.close(fd)
    Path(name).write_bytes(scene.export(file_type="glb"))
    return Path(name)


def _make(in_path: Path, out: Path) -> None:
    """In the separate process: the original in, the pieces out (in the original's place)."""
    import numpy as np
    import coacd

    from studio_bridge.tools_ops import _load

    began = time.time()
    coacd.set_log_level("error")
    mesh = _load(in_path)  # unpacks Draco / meshopt; refuses an empty or flat model
    pieces = coacd.run_coacd(coacd.Mesh(np.asarray(mesh.vertices, float), np.asarray(mesh.faces, np.int64)),
                             max_convex_hull=MAX_PIECES, max_ch_vertex=MAX_POINTS, decimate=True, seed=0)
    pieces = [(np.asarray(v, float), np.asarray(f, np.int64)) for v, f in pieces if len(v) >= 4 and len(f) >= 4]
    if not pieces:
        raise RuntimeError("CoACD found no pieces")
    arrays = {"n": np.array(len(pieces)), "seconds": np.array(time.time() - began)}
    for i, (v, f) in enumerate(pieces):
        arrays[f"v{i}"], arrays[f"f{i}"] = v, f
    np.savez(out, **arrays)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    _make(Path(sys.argv[1]), Path(sys.argv[2]))
