"""Golden check: run each tool on a fixed set of models and compare fingerprints (md5) with the stored ones.

Same input must give the same bytes (project rule). This script checks it by machine instead of by memory:
run it before every commit that touches a tool.

  python scripts/golden.py                 # check: "same" or which case changed and what (file / extras / report)
  python scripts/golden.py --update        # after an intended change: store the new fingerprints (say why in the commit)
  python scripts/golden.py --only game     # just the cases whose name starts with "game"
  python scripts/golden.py --rig           # also auto_rig (needs the local rig tools, slow)

Fingerprints depend on the platform (Blender, numeric libraries), so they are stored per platform:
scripts/golden/<platform>.json. The models are read from GOLDEN_MODELS (default: the Desktop test set).
Exit code: 0 all same, 1 something changed or failed, 2 no fingerprints stored yet for this platform.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studio_bridge.tools_ops import run_operation  # noqa: E402

MODELS = Path(os.environ.get("GOLDEN_MODELS", "C:/Users/Admin/Desktop/game_prep_corpus"))
STORE = ROOT / "scripts" / "golden" / f"{platform.system().lower()}.json"

# (name, operation, model file, params): small models, but every main path of each tool is used once
CASES = [
    ("game_sword_cut", "game_prep", "tripo_sword.glb", {"targetTris": 2000, "textureSize": 512}),
    ("game_mech_package", "game_prep", "hunyuan31_mech.glb",
     {"targetTris": 20000, "textureSize": 1024, "bake": True, "lods": True, "collision": True, "godot": True}),  # LODs need bake
    ("game_dog_quality", "game_prep", "hi3dgen_dog.glb", {"targetTris": 50000, "textureSize": 1024, "maxErrorPct": 0.5}),
    ("print_sword", "print_prep", "tripo_sword.glb", {"heightMm": 80}),
    ("print_drill", "print_prep", "hunyuan31_drill.glb", {"heightMm": 120}),
]
RIG_CASES = [
    ("rig_operative", "auto_rig", "hunyuan_operative.glb", {"rigType": "human"}),
]
# report fields that change from run to run on their own (clock time, temp paths) are left out of its fingerprint
VOLATILE = ("sec", "time", "path", "tmp", "waited")
SECONDS = __import__("re").compile(r"\d+(?:\.\d+)? ?s(?![a-z])")  # "(155 s, 146.0 s of it ...)" in step texts


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def stable(report):
    if isinstance(report, dict):
        return {k: stable(v) for k, v in sorted(report.items()) if not any(w in k.lower() for w in VOLATILE)}
    if isinstance(report, list):
        return [stable(v) for v in report]
    if isinstance(report, str):
        return SECONDS.sub("# s", report)
    return report


def flat(d, p: str = "") -> dict:
    if isinstance(d, dict):
        return {k: v for key, val in d.items() for k, v in flat(val, f"{p}{key}.").items()}
    if isinstance(d, list):
        return {k: v for i, val in enumerate(d) for k, v in flat(val, f"{p}{i}.").items()}
    return {p[:-1]: d}


def fingerprint(operation: str, model: Path, params: dict) -> dict:
    out, report, extras = run_operation(operation, model, dict(params))
    try:
        fp = {
            "file": md5(out),
            "extras": {name: md5(p) for name, p in sorted(extras.items())},
            "report": flat(stable(report)),  # stored whole, so a change names the field that moved
            "triangles": (report.get("after") or {}).get("triangles"),
        }
    finally:
        for p in [out, *extras.values()]:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:  # Windows: run_operation's temp file can still be open
                pass
    return fp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--update", action="store_true", help="store the new fingerprints")
    ap.add_argument("--only", default="", help="run only cases whose name starts with this")
    ap.add_argument("--rig", action="store_true", help="also run auto_rig")
    a = ap.parse_args()
    stored = json.loads(STORE.read_text()) if STORE.exists() else {}
    cases = [c for c in CASES + (RIG_CASES if a.rig else []) if c[0].startswith(a.only)]
    new, bad = dict(stored), 0
    for name, op, model, params in cases:
        t = time.time()
        try:
            fp = fingerprint(op, MODELS / model, params)
        except Exception as e:  # a tool that fails is a change too
            fp = {"error": f"{type(e).__name__}: {e}"[:300]}
        sec = time.time() - t
        old = stored.get(name)
        if old is None:
            verdict = "new (no fingerprint stored)"
        elif old == fp:
            verdict = "same"
        else:
            changed = [k for k in sorted(set(old) | set(fp)) if old.get(k) != fp.get(k)]
            if "report" in changed and isinstance(old.get("report"), dict) and isinstance(fp.get("report"), dict):
                o, n = old["report"], fp["report"]
                moved = [f"{k}: {o.get(k)!r} -> {n.get(k)!r}"[:160] for k in sorted(set(o) | set(n)) if o.get(k) != n.get(k)]
                changed[changed.index("report")] = "report (" + "; ".join(moved[:6]) + (" ..." if len(moved) > 6 else "") + ")"
            verdict = "CHANGED: " + ", ".join(changed)
            bad += 1
        print(f"{name:20s} {sec:6.1f} s  {verdict}", flush=True)
        new[name] = fp
    if a.update:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        STORE.write_text(json.dumps(new, indent=1, sort_keys=True) + "\n")
        print("stored", STORE)
        return 0
    if not stored:
        print("no fingerprints for this platform yet: run with --update once on a known good state")
        return 2
    print("all same" if not bad else f"{bad} case(s) changed: if intended, run --update and say why in the commit")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
