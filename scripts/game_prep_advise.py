"""Ask the game_prep advisor (Claude) about runs from a bench folder.

  python scripts/game_prep_advise.py --bench <out of game_prep_bench.py> --model mech --mode 5k
  python scripts/game_prep_advise.py ... --view "original, front=orig.png" --view "5k, front=5k.png" --goal "mobile game"

Needs ANTHROPIC_API_KEY (or an `ant auth login` profile). Costs a few cents per call.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studio_bridge.tools_advisor import advise  # noqa: E402


def as_report(row: dict) -> dict:
    """A bench row back in the shape game_prep reports have."""
    run = row["new"]
    return {
        "operation": "game_prep",
        "mode": row["mode"],
        "steps": run.get("steps", []),
        "before": {"triangles": row["trisBefore"]},
        "after": {
            "triangles": run["tris"],
            "fileMb": run.get("fileMb"),
            "deviation": {k: run[k] for k in ("meanPct", "maxPct", "normalMeanDeg", "normalP95Deg") if k in run},
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench", type=Path, required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--mode", required=True, help="the run to advise on: 5k, 20k or q0.5%%")
    ap.add_argument("--view", action="append", default=[], help='"label=path.png", repeatable')
    ap.add_argument("--goal")
    args = ap.parse_args()

    rows = json.loads((args.bench / "report.json").read_text())
    runs = [r for r in rows if r["model"] == args.model]
    latest = next((r for r in runs if r["mode"] == args.mode), None)
    if latest is None:
        sys.exit(f"no {args.model} {args.mode} in {args.bench}")
    # The other runs on the same model go first, as history.
    reports = [as_report(r) for r in runs if r is not latest] + [as_report(latest)]
    views = []
    for spec in args.view:
        label, _, path = spec.rpartition("=")
        views.append((label, Path(path).read_bytes()))
    print(json.dumps(advise(reports, views, args.goal), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
