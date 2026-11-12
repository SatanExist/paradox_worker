"""Bench for game_prep: run it over a set of models, measure, and compare with an earlier run.

No change to game_prep goes in without this table and a look in the viewer — the numbers alone
once missed models turning chrome.

  python scripts/game_prep_bench.py --models C:/Users/Admin/Desktop --out bench/v2
  python scripts/game_prep_bench.py --models ... --out bench/v3 --baseline bench/v2
  # then open the viewer: python -m http.server 8765 --directory <parent of out and models>
  #   http://127.0.0.1:8765/<out>/compare.html?models=<models dir>&old=<baseline dir>

Each model gets three versions: 5k and 20k budgets and the quality mode at 0.5%. Writes the
GLBs, report.json (what the viewer reads) and prints a table: triangles, shape deviation
(mean / max % of the model's size), shading (mean / 95th percentile degrees), time.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studio_bridge.tools_ops import run_operation  # noqa: E402

MODES = {
    "5k": {"targetTris": 5000, "textureSize": 1024},
    "20k": {"targetTris": 20000, "textureSize": 1024},
    "q0.5%": {"targetTris": 50000, "textureSize": 1024, "maxErrorPct": 0.5},
}


def side(report: dict, seconds: float) -> dict:
    after = report["after"]
    return {
        "tris": after["triangles"],
        **after["deviation"],
        **{k: v for k, v in (after.get("look") or {}).items() if k != "worstView"},
        "fileMb": after["fileMb"],
        "sec": round(seconds, 1),
        "steps": report["steps"],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", type=Path, required=True, help="folder with the original .glb files")
    ap.add_argument("--out", type=Path, required=True, help="folder for the results (made if missing)")
    ap.add_argument("--baseline", type=Path, help="an earlier --out to compare against")
    ap.add_argument("--only", nargs="*", help="model names to run (default: every .glb in --models)")
    args = ap.parse_args()

    models = sorted(p.stem for p in args.models.glob("*.glb"))
    if args.only:
        models = [m for m in models if m in args.only]
    if not models:
        sys.exit(f"no .glb files in {args.models}")
    args.out.mkdir(parents=True, exist_ok=True)
    old_rows = {}
    if args.baseline:
        for row in json.loads((args.baseline / "report.json").read_text()):
            old_rows[(row["model"], row["mode"])] = row["new"]

    rows = []
    for model in models:
        for mode, params in MODES.items():
            t0 = time.time()
            out, report, extra = run_operation("game_prep", args.models / f"{model}.glb", params)
            shutil.copyfile(out, args.out / f"{model}_{mode}.glb")
            if "preview.png" in extra:
                shutil.copyfile(extra["preview.png"], args.out / f"{model}_{mode}.preview.png")
                extra["preview.png"].unlink(missing_ok=True)
            try:
                out.unlink(missing_ok=True)
            except OSError:  # Windows: run_operation's temp file is still open
                pass
            row = {
                "model": model,
                "mode": mode,
                "trisBefore": report["before"]["triangles"],
                "new": side(report, time.time() - t0),
            }
            if (model, mode) in old_rows:
                row["old"] = old_rows[(model, mode)]
            rows.append(row)
            print_row(row)
    (args.out / "report.json").write_text(json.dumps(rows, indent=1))
    viewer = Path(__file__).with_name("game_prep_compare.html")
    shutil.copyfile(viewer, args.out / "compare.html")
    print(f"\n{len(rows)} runs -> {args.out}")


def fmt(s: dict | None) -> str:
    if not s:
        return " " * 44
    shading = f"{s['normalMeanDeg']:>5.1f}/{s['normalP95Deg']:<5.1f}" if "normalMeanDeg" in s else " " * 11
    look = (f" sil {s['silhouettePct']:>5.2f} look {s['lookPct']:>5.2f} tex {s['texturePct']:>5.2f} light {s['lightPct']:>5.2f}"
            if "lookPct" in s else "")
    return f"{s['tris']:>6} {s['meanPct']:.3f}/{s['maxPct']:<5.2f} {shading}{look} {s.get('sec', 0):>5.1f}s"


def print_row(row: dict) -> None:
    print(f"{row['model']:10}{row['mode']:6}| new {fmt(row['new'])} | old {fmt(row.get('old'))}", flush=True)


if __name__ == "__main__":
    main()
