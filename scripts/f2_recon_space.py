"""F2 wave-0 recon: run our reference images through official HF Space demos.

No infra: no Dockerfile, no volume, no endpoint. Goal is a same-input gallery
across many nets before spending money on integration.

Usage:
    # 1. look at what the Space exposes
    python scripts/f2_recon_space.py --net triposg --inspect

    # 2. run our reference through it
    python scripts/f2_recon_space.py --net triposg --subject knight

Anonymous ZeroGPU quota is small; long jobs need HF_TOKEN in the environment.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "preview_textures"

load_dotenv(REPO / ".env")

SUBJECTS = {
    "knight": OUT_DIR / "ref_gold_armor.png",
    "knight_bust": OUT_DIR / "ref_gold_armor_bust.png",
    "chest": OUT_DIR / "ref_chest.png",
}


@dataclass
class Net:
    """One candidate net reachable through a public Space."""

    space: str
    note: str
    api_name: str | None = None
    # Extra kwargs merged into the predict call after the image argument.
    params: dict = field(default_factory=dict)
    main_args: tuple = ()
    # Some Spaces expect a background-removed image; their UI runs that step
    # implicitly on upload, so the API has to be chained by hand.
    pre_api: str | None = None
    # Positional: older Spaces expose unnamed parameters only.
    pre_args: tuple = ()
    # Spaces with per-session state reject calls until a session exists.
    needs_session: bool = False
    # "trellis" = preprocess -> generate_3d (returns state) -> extract_glb_api.
    chain: str | None = None
    extract: dict = field(default_factory=dict)


NETS: dict[str, Net] = {
    "triposg": Net(
        space="VAST-AI/TripoSG",
        note="MIT, 1.5B rectified flow, >8GB VRAM, geometry only",
        api_name="/image_to_3d",
        pre_api="/run_segmentation",
        needs_session=True,
        # Space defaults on purpose: recon should show what the net gives
        # out of the box, before we start tuning anything.
        params={
            "seed": 42,
            "num_inference_steps": 50,
            "guidance_scale": 7.0,
            "simplify": True,
            "target_face_num": 100_000,
        },
    ),
    "direct3d_s2": Net(
        space="wushuang98/Direct3D-S2-v1.0-demo",
        note="MIT, sdf_resolution up to 1024 = explicit quality lever",
    ),
    "step1x3d": Net(
        space="stepfun-ai/Step1X-3D",
        note="Apache-2.0, geometry + texture, training code public",
    ),
    "pixal3d": Net(
        space="TencentARC/Pixal3D",
        note="MIT code, TRELLIS.2 backbone; weights card flags EU gating",
        chain="trellis",
        params={"seed": 42, "resolution": 1024},
        extract={"decimation_target": 200_000, "texture_size": 2048},
    ),
    "sf3d": Net(
        space="stabilityai/stable-fast-3d",
        note="fast tier candidate, seconds per mesh",
    ),
    "triposr": Net(
        space="stabilityai/TripoSR",
        note="fast tier candidate, older",
        api_name="/generate",
        main_args=(320,),
        pre_api="/preprocess",
        pre_args=(True, 0.85),
    ),
}


def make_client(space: str):
    from gradio_client import Client

    token = hf_token()
    if not token:
        print("[warn] no HF_TOKEN in .env -> anonymous ZeroGPU quota (~5 min/day)")
    else:
        print(f"[auth] HF token loaded ({token[:6]}…)")
    # download_files=False: some Spaces return intermediate previews that are
    # not publicly served (403), and auto-download kills an otherwise good run.
    return Client(space, token=token, download_files=False)


def hf_token() -> str | None:
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")


def fetch(url: str, target: Path) -> bool:
    """Pull one artifact ourselves, tolerating Spaces that hide extras."""
    import httpx

    headers = {}
    token = hf_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.stream("GET", url, headers=headers, timeout=300, follow_redirects=True) as resp:
            resp.raise_for_status()
            with target.open("wb") as handle:
                for chunk in resp.iter_bytes():
                    handle.write(chunk)
    except Exception as exc:
        print(f"[warn] could not fetch {url}: {exc}")
        return False
    return True


def inspect(net: Net) -> None:
    client = make_client(net.space)
    print(f"\n=== {net.space} ===\n{net.note}\n")
    print(client.view_api(return_format="str"))


ARTIFACT_SUFFIXES = {".glb", ".obj", ".ply", ".png", ".jpg", ".jpeg"}


def collect_outputs(result) -> list[str]:
    """Return artifact locations: remote urls (download_files=False) or local paths.

    Shape of a Gradio result varies per Space: bare str, tuple, or nested dicts.
    """
    found: list[str] = []

    def walk(node) -> None:
        if isinstance(node, str):
            if Path(node).suffix.lower() in ARTIFACT_SUFFIXES and Path(node).exists():
                found.append(node)
        elif isinstance(node, dict):
            url = node.get("url")
            if isinstance(url, str) and Path(url.split("?")[0]).suffix.lower() in ARTIFACT_SUFFIXES:
                found.append(url)
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    walk(result)
    return found


def materialise(location: str, target: Path) -> bool:
    """Bring one artifact to `target`, whether it is a url or a local file."""
    if location.startswith("http"):
        return fetch(location, target)
    shutil.copy2(location, target)
    return True


def run(net_key: str, net: Net, subject: str, reuse_state: bool = False) -> None:
    from gradio_client import handle_file

    image = SUBJECTS[subject]
    if not image.exists():
        raise SystemExit(f"reference image missing: {image}")

    client = make_client(net.space)
    call_kwargs = dict(net.params)
    if net.api_name:
        call_kwargs["api_name"] = net.api_name

    print(f"[run] {net_key} <- {image.name}")
    started = time.time()

    if net.needs_session:
        try:
            client.predict(api_name="/start_session")
        except Exception as exc:  # session endpoint is best-effort
            print(f"[warn] start_session failed: {exc}")

    image_arg = handle_file(str(image))
    if net.pre_api:
        print(f"[pre] {net.pre_api}")
        pre = client.predict(image_arg, *net.pre_args, api_name=net.pre_api)
        pre_locations = collect_outputs(pre)
        if not pre_locations:
            raise SystemExit(f"{net.pre_api} returned no file: {pre!r}")
        suffix = Path(pre_locations[0].split("?")[0]).suffix or ".png"
        prepped = OUT_DIR / f"f2_{net_key}_{subject}_prep{suffix}"
        if not materialise(pre_locations[0], prepped):
            raise SystemExit(f"could not fetch preprocessed image: {pre_locations[0]}")
        print(f"[pre] segmented -> {prepped.name}")
        image_arg = handle_file(str(prepped))

    if net.chain == "trellis":
        state_file = OUT_DIR / f"f2_{net_key}_{subject}_state.txt"
        if reuse_state and state_file.exists():
            state_path = state_file.read_text(encoding="utf-8").strip()
            print(f"[gen] reusing state from {state_file.name} (no GPU spent)")
        else:
            print("[gen] /generate_3d")
            state = client.predict(image_arg, api_name="/generate_3d", **net.params)
            dump = OUT_DIR / f"f2_{net_key}_{subject}_state.json"
            dump.write_text(
                json.dumps(state, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            print(f"[gen] state dumped -> {dump.name}")
            state_path = state.get("state_path") if isinstance(state, dict) else None
            if not state_path:
                raise SystemExit(f"/generate_3d gave no state_path: {state!r}")
            state_file.write_text(state_path, encoding="utf-8")
        print(f"[gen] state ok, extracting glb ({net.extract})")
        result = client.predict(
            state_path, api_name="/extract_glb_api", **net.extract
        )
    else:
        result = client.predict(image_arg, *net.main_args, **call_kwargs)
    elapsed = time.time() - started

    saved: list[str] = []
    for location in collect_outputs(result):
        suffix = Path(location.split("?")[0]).suffix.lower()
        target = OUT_DIR / f"f2_{net_key}_{subject}{suffix}"
        if not materialise(location, target):
            continue
        saved.append(f"{target.name} ({target.stat().st_size / 1_048_576:.1f} MB)")

    log = OUT_DIR / f"f2_{net_key}_{subject}.json"
    log.write_text(
        json.dumps(
            {
                "net": net_key,
                "space": net.space,
                "subject": subject,
                "seconds": round(elapsed, 1),
                "saved": saved,
                "raw_result": str(result)[:2000],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"[done] {elapsed:.1f}s")
    for line in saved:
        print(f"  saved {line}")
    if not saved:
        print(f"  no recognised artifact; raw result in {log.name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--net", required=True, choices=sorted(NETS))
    parser.add_argument("--subject", default="knight", choices=sorted(SUBJECTS))
    parser.add_argument("--inspect", action="store_true", help="dump Space API and exit")
    parser.add_argument(
        "--reuse-state",
        action="store_true",
        help="skip generation and re-export from the saved state (saves GPU quota)",
    )
    parser.add_argument("--decimation-target", type=int)
    parser.add_argument("--texture-size", type=int)
    args = parser.parse_args()

    net = NETS[args.net]
    if args.decimation_target:
        net.extract["decimation_target"] = args.decimation_target
    if args.texture_size:
        net.extract["texture_size"] = args.texture_size

    if args.inspect:
        inspect(net)
    else:
        run(args.net, net, args.subject, reuse_state=args.reuse_state)


if __name__ == "__main__":
    main()
