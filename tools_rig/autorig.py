"""The auto_rig operation's worker side (studio_bridge.tools_ops.auto_rig runs it as its own process).
Runs in the SkinTokens environment with cwd = the SkinTokens folder (SKINTOKENS_DIR):
  python autorig.py <out dir> [--tries N] [--post] [--kind human|creature] <in.glb> ...
Per model: SkinTokens (any creature) with retry when the network gives no skeleton (it stops on an assert, ~1 in 40),
up to N tries kept and the best one chosen (human rig with standard names first, then the one whose skin distorts
least when each bone bends 30 degrees, judge4.py: published posing + as-rigid-as-possible energy, no cut-offs of ours;
then more named bones), then the honest verdict: "humanoid" (standard names: ready for Mixamo/Godot humanoid
animations) or "creature" (own skeleton, its own animations). Every model gets its rig (like Mixamo/AccuRIG); kind.py
(SigLIP pictures, only where SIGLIP_DIR and Blender are set up) adds a note when it doesn't look like a character.
--kind is the user's switch, as Mixamo / AccuRIG ask it: human (standard names by the humanoid template and plain
signs, no proportion limits) or creature (own skeleton, no names; the default).
Repeatable: same model and switches on the same machine -> the same rig file, byte for byte (repeatable(),
seeded_server.py). judge4 / parts / inner need libigl + scipy: they run in RIG_TOOLS_PYTHON (default: this Python).
Writes <name>_rig.glb (names applied when human) and <name>_report.json; prints timings per stage."""
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.getcwd())
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import grown  # noqa: E402

MAX_ATTEMPTS = 3  # per try: the first run plus up to 2 retries when no skeleton comes out
# judge4 / parts / inner need libigl + scipy; the worker image has them next to SkinTokens, this PC in another venv
TOOLS_PY = os.environ.get("RIG_TOOLS_PYTHON") or sys.executable


def verdict(path, mode="creature"):
    """-> (kind, names map or None, info) from the rigged file. mode: the user's switch human / creature."""
    import numpy as np
    from rename import label, read, skeleton
    j, rest = read(path)
    pos, parents, nodes = skeleton(j, rest)
    res, why = (None, "the user chose Creature") if mode == "creature" else label(pos, parents)
    here = os.path.dirname(os.path.abspath(__file__))
    done = subprocess.run([TOOLS_PY, os.path.join(here, "judge4.py"), os.path.abspath(path)], capture_output=True,
                          text=True, timeout=900, cwd=here, env={**os.environ, "OPENBLAS_NUM_THREADS": "1"})
    bend = json.loads(done.stdout.strip().splitlines()[-1])
    if res is not None:
        return "humanoid", res, {"bones": len(nodes), "bend": bend}
    return "creature", None, {"bones": len(nodes), "whyNotHuman": why, "bend": bend}


def score(kind, res, info):
    named = len(res[0]) if res else 0
    return (kind == "humanoid", -info["bend"]["distortion"], named, info["bones"])


def repeatable(demo, torch):
    """Same model -> same rig, every run (PyTorch "Reproducibility" notes). Two causes were found in SkinTokens itself
    (probe 2026-11-19: equal input, yet both encoders gave other numbers each run):
    - nobody calls model.eval() after loading (only the VAE is put in eval), so the shape encoder runs in training mode
      and picks its points with an unseeded np.random.default_rng();
    - TokenRig.generate() does not pass the seed its VAE encoder takes, so that one picks points from OS entropy too
      (seed=0, as the shape encoder's own eval branch does).
    Plus the usual: deterministic GPU kernels, no loader worker process (its numpy is not seeded on Windows), and a bpy
    server that reseeds every request. Proper home of the two model fixes: SkinTokens upstream (demo / generate)."""
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    _parse = demo.DatasetConfig.parse
    demo.DatasetConfig.parse = lambda **k: _parse(**{**k, "num_workers": 0, "persistent_workers": False})

    def start_bpy_server():
        proc = subprocess.Popen([sys.executable, str(HERE / "seeded_server.py")],
                                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        import atexit
        atexit.register(proc.terminate)
        return proc
    demo.start_bpy_server = start_bpy_server
    _load = demo.load_model

    def load_model(*a, **k):
        r = _load(*a, **k)
        demo.model.eval()
        vcls = type(demo.model.vae.model)
        if not getattr(vcls, "_seeded", False):
            _enc = vcls._encode

            def _encode(self, *ea, **ek):
                if ek.get("seed") is None:
                    ek["seed"] = 0
                return _enc(self, *ea, **ek)
            vcls._encode, vcls._seeded = _encode, True
        return r
    demo.load_model = load_model


if __name__ == "__main__":
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")  # needed by deterministic cuBLAS, before CUDA starts
    import numpy as np
    import torch
    import demo
    from rename import read, write
    repeatable(demo, torch)

    args = sys.argv[1:]
    out = Path(args.pop(0))
    tries, post, mode = 1, False, "creature"
    while args and args[0].startswith("--"):
        a = args.pop(0)
        if a == "--tries":
            tries = int(args.pop(0))
        elif a == "--post":
            post = True
        elif a == "--kind":
            mode = args.pop(0)
            assert mode in ("human", "creature"), mode
    out.mkdir(parents=True, exist_ok=True)
    clock = {}
    _post = demo.post_bpy_payload

    def timed_post(endpoint, payload):
        t = time.time()
        r = _post(endpoint, payload)
        clock[endpoint] = clock.get(endpoint, 0) + time.time() - t
        return r
    demo.post_bpy_payload = timed_post
    demo.start_bpy_server()
    demo.wait_for_bpy_server(timeout=120)
    for src in map(Path, args):
        t0 = time.time()
        steps, kept = [], []
        import kind as looks
        seen = looks.look(src) if looks.available() else None
        print("LOOK", src.stem, seen, flush=True)
        for k in range(tries):
            for attempt in range(MAX_ATTEMPTS):
                seed = 1 + 1000 * k + attempt
                random.seed(seed); np.random.seed(seed); torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)
                dst = out / f"{src.stem}_try{k}.glb"
                clock.clear()
                ts = time.time()
                try:
                    demo.run_cli(SimpleNamespace(input=str(src), output=str(dst), top_k=5, top_p=0.95, temperature=1.0,
                                                 repetition_penalty=2.0, num_beams=10, use_skeleton=False, use_transfer=True,
                                                 use_postprocess=post, model_ckpt=demo.MODEL_CKPTS[0], hf_path=None))
                except Exception as exc:  # no skeleton (assert) or a broken bone sequence (ValueError) etc.
                    steps.append(f"try {k + 1}: the network gave no usable skeleton ({type(exc).__name__}), trying again")
                    print('RETRY', src.stem, type(exc).__name__, str(exc)[:80], flush=True)
                    continue
                if not dst.exists():
                    steps.append(f"try {k + 1}: no file written, trying again")
                    continue
                kind, res, info = verdict(dst, mode)
                total = time.time() - ts
                print(f"STAGE {src.stem} try{k} total {total:.0f}s transfer {clock.get('transfer', 0):.0f}s "
                      f"other(load+network) {total - clock.get('transfer', 0):.0f}s -> {kind} {info}", flush=True)
                kept.append((score(kind, res, info), k, dst, kind, res, info))
                break
        if not kept:
            rep = {"operation": "auto_rig", "steps": steps + ["no rig: the network gave no skeleton in any try"],
                   "before": {}, "after": {"kind": "failed"}}
            json.dump(rep, open(out / f"{src.stem}_report.json", "w"), indent=1)
            print("RIG", src.stem, "FAILED", flush=True)
            continue
        kept.sort(key=lambda x: (x[0], -x[1]), reverse=True)
        sc, k, dst, kind, res, info = kept[0]
        final = out / f"{src.stem}_rig.glb"
        j, rest = read(dst)
        if kind == "humanoid":
            m, extra = res
            nodes = j["skins"][0]["joints"]
            for b, nm in m.items():
                j["nodes"][nodes[b]]["name"] = nm
            info.update(namedBones=len(m), fingers=extra.get("fingers"))
        write(final, j, rest)
        # fused body parts (a fist grown into a thigh, an arm into a pouch): part the skin where two bones may not share
        # it (joint envelopes, parts.py) and cap the openings; runs in the worker venv (numpy + scipy)
        done = subprocess.run([TOOLS_PY, str(HERE / "parts.py"), str(final), str(final)], capture_output=True, text=True,
                              timeout=1800, cwd=str(HERE), env={**os.environ, "OPENBLAS_NUM_THREADS": "1"})
        if done.returncode == 0:
            pp = json.loads(done.stdout.strip().splitlines()[-1])
            info.update(fusedParts=pp)
            parts_msg = (f"fused parts: the skin was parted at {pp['partedPoints']} points where the model had grown "
                         f"parts together that move apart (like a fist on a thigh); {pp['cappedOpenings']} openings "
                         f"closed; {pp['weightMassRemovedPct']} % of the skin weights moved")
        else:
            parts_msg = "fused parts: check failed, the rig is kept as the network made it"
            print("PARTS FAILED", src.stem, done.stderr[-400:], flush=True)
        # grown-together limbs (an arm generated stuck to the flank): measured by inner.py (check only), said by grown.py
        fused_msgs = []
        chk = subprocess.run([TOOLS_PY, str(HERE / "inner.py"), str(final), "-"], capture_output=True, text=True,
                             timeout=900, cwd=str(HERE), env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "CHECK": "1"})
        if chk.returncode == 0:
            groups = json.loads(chk.stdout.strip().splitlines()[-1]).get("parts", [])
            info.update(grownTogether=[g for g in groups if g["sections"] >= grown.NOISE])
            fused_msgs = grown.warnings(groups)
        else:
            print("GROWN CHECK FAILED", src.stem, chk.stderr[-400:], flush=True)
        msg = {"humanoid": "human-like character: bones have standard names, so ready-made humanoid animations "
                           "(Mixamo style, Godot/Unity humanoid) play on it",
               "creature": "creature rig: it can be animated with its own animations; ready-made human animations won't fit"
                           + {"human": f" (no human skeleton found: {info.get('whyNotHuman')})",
                              "creature": " (if it is a person, choose Rig type: Human and the bones get standard names)"
                                          if seen is None or seen["pick"] == "character" else ""}[mode]}[kind]
        steps.append(f"chose try {k + 1} of {len(kept)}: {kind}, {info['bones']} bones; bend test: "
                     f"skin distortion {info['bend']['distortion']} when each bone bends 30 degrees (lower is better)"
                     + ("" if len(kept) < 2 else " (others: " + ", ".join(f"{x[5]['bend']['distortion']}" for x in kept[1:]) + ")"))
        steps.append(msg)
        steps.append(parts_msg)
        steps.extend(fused_msgs)
        # Known limit, said every time (like Mixamo / AccuRIG, we give no bones to loose cloth): long loose parts get no
        # bones of their own and follow the nearest body bone; games swing them with the engine's cloth or spring bones.
        steps.append("note: long loose parts (capes, long skirts, long hair) have no bones of their own and follow the "
                     "nearest body bone, so a cape can stretch with the legs; to make them swing, add cloth physics or "
                     "spring bones in your engine (Godot SpringBoneSimulator3D, Unity cloth, Unreal Chaos Cloth)")
        if seen is not None and seen["pick"] != "character":
            steps.append(f"note: on the pictures this looks like {'a statue' if seen['pick'] == 'statue' else 'an object'}, "
                         "not a character; the rig is there if you want to animate it anyway")
        rep = {"operation": "auto_rig", "steps": steps, "before": {"file": src.name},
               "after": {"kind": kind, "rigType": mode, "looksLike": seen, "tries": len(kept), "chosenTry": k + 1, "seconds": round(time.time() - t0), **info}}
        json.dump(rep, open(out / f"{src.stem}_report.json", "w"), indent=1)
        print("RIG", src.stem, kind, info, round(time.time() - t0), "s", flush=True)
