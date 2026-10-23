"""Regression corpus for print prep: every model through the lab's print_prep, one row per model.

usage:
  python run.py                 all models not yet run with the current recipe
  python run.py statue crown    only ids containing these words
  python run.py --again ...     re-run even if this recipe already has a row
  python run.py --max-faces=200000   only models up to that many triangles (the light ones)
  python run.py --min-faces=300001   only models from that many triangles (the heavy ones)

Each model runs in its own process at low priority (so the PC stays usable), with a time limit.
Rows go to results.jsonl, tagged with the recipe = the last paradox_worker commit that touched the print files (+ "-dirty" when it has
uncommitted changes to the print files), so recipe changes can be compared model by model.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import psutil

from faces import glb_faces

HERE = Path(__file__).resolve().parent
LAB = HERE.parent  # the corpus lives inside paradox_worker
PRINT_FILES = ["studio_bridge/print_solid.py", "studio_bridge/print_remesh.py", "studio_bridge/tools_ops.py"]
TIME_LIMIT_S = 30 * 60

ONE = r"""
import sys, json
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from studio_bridge.tools_ops import print_prep
rep = print_prep(Path(sys.argv[2]), Path(sys.argv[3]), {"heightMm": float(sys.argv[4])})
import trimesh
out = trimesh.load(sys.argv[3], force="mesh"); out.apply_scale(1000)  # glTF is metres
rep["afterWallMm"] = round(2 * abs(out.volume) / out.area, 2) if out.is_watertight and out.area > 0 else None
print("@@REPORT " + json.dumps(rep))
"""


def recipe() -> str:
    sha = subprocess.run(["git", "-C", str(LAB), "log", "-1", "--format=%h", "--", *PRINT_FILES], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(LAB), "status", "--porcelain", "--", *PRINT_FILES], capture_output=True, text=True).stdout.strip()
    return sha + ("-dirty" if dirty else "")


def manifest() -> list[dict]:
    rows = []
    for line in (HERE / "manifest.tsv").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        mid, engine, kind, height, _src = line.split("\t")
        rows.append({"id": mid, "engine": engine, "kind": kind, "heightMm": float(height)})
    return rows


def done_ids(rec: str) -> set[str]:
    path = HERE / "results.jsonl"
    if not path.is_file():
        return set()
    return {r["id"] for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if r.get("recipe") == rec}


def run_one(m: dict, rec: str) -> dict:
    out = HERE / "out" / f"{m['id']}.glb"
    log = HERE / "out" / f"{m['id']}.log"
    t0 = time.time()
    with open(log, "w", encoding="utf-8") as lf:
        proc = subprocess.Popen(
            [sys.executable, "-u", "-c", ONE, str(LAB), str(HERE / "models" / f"{m['id']}.glb"), str(out), str(m["heightMm"])],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS,
        )
        ps, peak, report = psutil.Process(proc.pid), 0, None
        import threading

        def watch():
            nonlocal peak
            while proc.poll() is None:
                try:  # a venv python.exe on Windows is a launcher: the work happens in its child
                    procs = [ps, *ps.children(recursive=True)]
                    peak = max(peak, sum(p.memory_info().rss for p in procs if p.is_running()))
                except psutil.Error:
                    pass
                time.sleep(0.5)

        threading.Thread(target=watch, daemon=True).start()
        def kill_tree():
            for p in [*ps.children(recursive=True), ps]:
                try:
                    p.kill()
                except psutil.Error:
                    pass

        timer = threading.Timer(TIME_LIMIT_S, kill_tree)
        timer.start()
        for line in proc.stdout:
            if line.startswith("@@REPORT "):
                report = json.loads(line[len("@@REPORT "):])
            else:
                lf.write(line)
                lf.flush()
        proc.wait()
        timer.cancel()
    row = {**m, "inFaces": glb_faces(HERE / "models" / f"{m['id']}.glb"), "recipe": rec, "secs": round(time.time() - t0), "peakGb": round(peak / 2**30, 2), "ok": report is not None}
    if report is None:
        row["error"] = "timeout" if time.time() - t0 >= TIME_LIMIT_S else (log.read_text(encoding="utf-8").strip().splitlines() or ["crash"])[-1][:300]
        return row
    solid = report.get("solid") or {}
    before, after = report["before"], report["after"]
    row.update({
        "before": {k: before.get(k) for k in ("faces", "watertight", "components")},
        "watertight": after.get("watertight"), "parts": after.get("components"),
        "volumeCm3": after.get("volumeCm3"), "faces": after.get("faces"),
        "method": solid.get("method") or ("voxel" if report.get("remesh") else "none"),
        "wallMm": solid.get("wallMm"), "afterWallMm": report.get("afterWallMm"), "cameClosed": solid.get("cameClosed"),
        "candidates": [{k: c.get(k) for k in ("method", "parts", "volumeCm3", "changedShare", "changedHiddenShare", "lostShare", "secs", "stages")}
                       for c in solid.get("candidates", [])],
        "timings": {**(report.get("timings") or {}), **(solid.get("stages") or {})},
        "steps": report["steps"],
        "floating": report.get("floating"),
    })
    pick = next((c for c in solid.get("candidates", []) if c.get("method") == row["method"]), {})
    row["changedShare"], row["lostShare"] = pick.get("changedShare"), pick.get("lostShare")
    return row


def main() -> None:
    args = sys.argv[1:]
    again = "--again" in args
    words = [a for a in args if not a.startswith("--")]
    max_faces = next((int(a.split("=")[1]) for a in args if a.startswith("--max-faces=")), None)
    min_faces = next((int(a.split("=")[1]) for a in args if a.startswith("--min-faces=")), None)
    rec = recipe()
    (HERE / "out").mkdir(exist_ok=True)
    skip = set() if again else done_ids(rec)
    todo = [m for m in manifest() if m["id"] not in skip and (not words or any(w in m["id"] for w in words))
            and (max_faces is None or glb_faces(HERE / "models" / f"{m['id']}.glb") <= max_faces)
            and (min_faces is None or glb_faces(HERE / "models" / f"{m['id']}.glb") >= min_faces)]
    print(f"recipe {rec}: {len(todo)} to run", flush=True)
    for i, m in enumerate(todo, 1):
        row = run_one(m, rec)
        with open(HERE / "results.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        verdict = (f"{row['method']:8} watertight={row['watertight']} parts={row['parts']} "
                   f"changed={row['changedShare']} lost={row['lostShare']}") if row["ok"] else f"FAILED {row['error']}"
        print(f"[{i}/{len(todo)}] {m['id']:24} {row['secs']:5}s {row['peakGb']:5}GB  {verdict}", flush=True)


if __name__ == "__main__":
    main()
