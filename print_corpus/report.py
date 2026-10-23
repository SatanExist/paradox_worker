"""Summary of results.jsonl: one line per model for a recipe, and a comparison when given two.

usage:
  python report.py                 the latest recipe
  python report.py e596348         that recipe
  python report.py e596348 abc1234 before -> after, per model
  python report.py --times 3769d84 where the time goes: each candidate, and the rest (local repair, measuring, export)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOST_GATE = 0.001
PAPER_MM = 1.0  # mean wall 2V/A of the result below this = a hollow skin the slicer turns into paper walls


def rows() -> list[dict]:
    path = HERE / "results.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def by_recipe(rec: str) -> dict[str, dict]:
    return {r["id"]: r for r in rows() if r["recipe"] == rec}  # the last row of a model wins


def verdict(r: dict) -> str:
    if not r.get("ok"):
        return "FAIL " + r.get("error", "")[:60]
    bad = []
    if not r.get("watertight"):
        bad.append("not closed")
    if (r.get("parts") or 0) != 1:
        bad.append(f"{r['parts']} parts")
    if (r.get("lostShare") or 0) > LOST_GATE:
        bad.append(f"lost {r['lostShare']:.1%}")
    if r.get("afterWallMm") is not None and r["afterWallMm"] < PAPER_MM:
        bad.append(f"paper walls {r['afterWallMm']} mm")
    return "ok" if not bad else "BAD " + ", ".join(bad)


def pct(x) -> str:
    return "—" if x is None else f"{x:.1%}"


def show(rec: str) -> None:
    res = by_recipe(rec)
    print(f"recipe {rec}: {len(res)} models\n")
    print(f"{'model':24} {'faces':>9} {'came in':14} {'method':9} {'wall mm':>7} {'after':>6} {'changed':>8} {'lost':>7} {'secs':>5} {'GB':>5}  verdict")
    for r in sorted(res.values(), key=lambda r: (r["engine"], r["id"])):
        b = r.get("before") or {}
        came = ("closed" if b.get("watertight") else "open") + (f", {b['components']} pcs" if b.get("components") else "")
        wall = "—" if r.get("wallMm") is None else f"{r['wallMm']:.2f}"
        print(f"{r['id']:24} {r.get('inFaces', 0):>9} {came:14} {r.get('method', '—'):9} {wall:>7} {r.get('afterWallMm') or '—':>6} "
              f"{pct(r.get('changedShare')):>8} {pct(r.get('lostShare')):>7} {r['secs']:>5} {r['peakGb']:>5}  {verdict(r)}")
    ok = sum(verdict(r) == "ok" for r in res.values())
    print(f"\npassed {ok} of {len(res)}")


def times(rec: str) -> None:
    res = [r for r in by_recipe(rec).values() if r.get("candidates")]
    print(f"{'model':24} {'faces':>9} {'secs':>5} {'cands':>6} {'rest':>5}  picked    candidates")
    for r in sorted(res, key=lambda r: -r["secs"]):
        spent = sum(c["secs"] for c in r["candidates"])
        cands = " ".join(f"{c['method']}={c['secs']:.0f}" for c in r["candidates"])
        print(f"{r['id']:24} {r.get('inFaces', 0):>9} {r['secs']:>5} {spent:>6.0f} {r['secs'] - spent:>5.0f}  {r.get('method', '—'):9} {cands}")
    lost = sum(c["secs"] for r in res for c in r["candidates"] if c["method"] != r.get("method"))
    print(f"\nlosing candidates took {lost:.0f} s of {sum(r['secs'] for r in res)} s in all")


def compare(a: str, b: str) -> None:
    ra, rb = by_recipe(a), by_recipe(b)
    print(f"{'model':24} {'verdict ' + a:28} {'verdict ' + b:28} {'changed':>17} {'secs':>11}")
    for mid in sorted(set(ra) & set(rb)):
        x, y = ra[mid], rb[mid]
        print(f"{mid:24} {verdict(x)[:27]:28} {verdict(y)[:27]:28} "
              f"{pct(x.get('changedShare')):>7} → {pct(y.get('changedShare')):>7} {x['secs']:>4} → {y['secs']:>4}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--times"]:
        times(args[1] if len(args) > 1 else rows()[-1]["recipe"])
    elif len(args) == 2:
        compare(*args)
    else:
        show(args[0] if args else rows()[-1]["recipe"])
