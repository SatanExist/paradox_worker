"""Run game_prep's auto budget over a folder of models, one process each, and flag what looks wrong.

  python scripts/game_prep_corpus.py --models <folder of .glb> --out <folder> [--purpose regular] [--only a b]

Each model runs in its own process with a time limit and its peak memory (process tree) watched, so one
bad model can't take the run down. Writes the result GLB and its before/after picture per model,
rows.jsonl (one row per model, appended as it goes; a rerun skips models already there) and prints
a table with flags: failed, slow (> 120 s), heavy (> 6 GB), kept the whole model, budget not reached,
still noticeably different after the auto budget, or a warning step.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
LIMIT_S = 10 * 60

ONE = r"""
import json, shutil, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from studio_bridge.tools_ops import run_operation
src, out_dir, purpose = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
out, rep, extra = run_operation("game_prep", src, {"autoBudget": True, "textureSize": 1024, "purpose": purpose})
shutil.copyfile(out, out_dir / f"{src.stem}.glb")
if "preview.png" in extra:
    shutil.copyfile(extra["preview.png"], out_dir / f"{src.stem}.preview.png")
print("@@REPORT " + json.dumps(rep))
"""


def run_one(src: Path, out_dir: Path, purpose: str) -> dict:
    t0 = time.time()
    proc = subprocess.Popen([sys.executable, "-u", "-c", ONE, str(ROOT), str(src), str(out_dir), purpose],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    ps, peak, report, tail = psutil.Process(proc.pid), 0, None, []

    def watch():
        nonlocal peak
        while proc.poll() is None:
            try:
                peak = max(peak, sum(p.memory_info().rss for p in [ps, *ps.children(recursive=True)] if p.is_running()))
            except psutil.Error:
                pass
            time.sleep(0.3)

    def kill():
        for p in [*ps.children(recursive=True), ps]:
            try:
                p.kill()
            except psutil.Error:
                pass

    threading.Thread(target=watch, daemon=True).start()
    timer = threading.Timer(LIMIT_S, kill)
    timer.start()
    for line in proc.stdout:
        if line.startswith("@@REPORT "):
            report = json.loads(line[len("@@REPORT "):])
        else:
            tail = (tail + [line.rstrip()])[-5:]
    proc.wait()
    timer.cancel()
    secs = round(time.time() - t0, 1)
    row = {"model": src.stem, "secs": secs, "peakGb": round(peak / 2**30, 2), "ok": report is not None}
    if report is None:
        row["error"] = "timeout" if secs >= LIMIT_S else (tail[-1] if tail else "crash")[:300]
        return row
    after = report["after"]
    row.update({
        "trisBefore": report["before"]["triangles"],
        "tris": after["triangles"],
        "picked": after["autoBudget"]["picked"],
        "tried": after["autoBudget"]["tried"],
        "budgetReached": after.get("budgetReached"),
        "look": after.get("look"),
        "deviation": after.get("deviation"),
        "fileMbBefore": report["before"].get("fileMb"),
        "fileMb": after.get("fileMb"),
        "meshes": [report["before"].get("meshes"), after.get("meshes")],
        "materials": [report["before"].get("materials"), after.get("materials")],
        "steps": report["steps"],
    })
    return row


def flags(r: dict, ok_pct: float) -> list[str]:
    if not r["ok"]:
        return ["FAILED: " + r.get("error", "")]
    out = []
    if r["secs"] > 120:
        out.append("slow")
    if r["peakGb"] > 6:
        out.append("heavy")
    if r["trisBefore"] > 20000 and r["tris"] >= r["trisBefore"]:
        out.append("kept whole model")
    if r.get("budgetReached") is False:
        out.append("budget not reached")
    look = r.get("look") or {}
    if look.get("noticeablePct", 0) > ok_pct:
        out.append(f"still noticeable {look.get('noticeablePct')}%")
    if not look:
        out.append("no look")
    if any(s.startswith(("look not measured", "looks noticeably", "under ")) for s in r["steps"]):
        out.append("warning step")
    if r["meshes"][0] != r["meshes"][1] or r["materials"][0] != r["materials"][1]:
        out.append(f"meshes {r['meshes']} materials {r['materials']}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--purpose", default="regular")
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    sys.path.insert(0, str(ROOT))
    from studio_bridge.tools_ops import PURPOSES

    ok_pct = PURPOSES[args.purpose]["okPct"]
    args.out.mkdir(parents=True, exist_ok=True)
    rows_file = args.out / "rows.jsonl"
    done = {json.loads(l)["model"] for l in rows_file.read_text(encoding="utf-8").splitlines()} if rows_file.exists() else set()
    models = sorted(p for p in args.models.glob("*.glb") if not args.only or p.stem in args.only)
    for src in models:
        if src.stem in done:
            continue
        r = run_one(src, args.out, args.purpose)
        with open(rows_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(r) + "\n")
        look = r.get("look") or {}
        print(f"{r['model']:22} {r['secs']:6.1f}s {r['peakGb']:5.2f}GB  "
              + (f"{r['trisBefore']:>8} -> {r['tris']:>6}  noticeable {look.get('noticeablePct', '-'):>5}  " if r["ok"] else "")
              + "; ".join(flags(r, ok_pct)), flush=True)


if __name__ == "__main__":
    main()
