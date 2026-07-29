"""Batch TRELLIS.2 clay/textured runs with multiple seeds (Track A shape pick).

Example (armor clay, best-of-N):
  python scripts/upload_r2_asset.py preview_textures/ref_gold_armor.png
  python scripts/batch_seeds_trellis2.py \\
    --image-file preview_textures/ref_gold_armor.png \\
    --seeds 1 7 42 123 \\
    --texture-mode clay \\
    --out-prefix model-armor-clay-seed
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _resolve_image_url(args: argparse.Namespace) -> str:
    if args.image_url:
        return args.image_url
    if not args.image_file:
        raise ValueError("Provide --image-url or --image-file")

    image_file = Path(args.image_file)
    if not image_file.is_file():
        raise FileNotFoundError(image_file)

    upload_script = ROOT / "scripts" / "upload_r2_asset.py"
    py = sys.executable
    proc = subprocess.run(
        [py, str(upload_script), str(image_file)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise RuntimeError(
            "R2 upload failed. Add R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY to .env"
        )
    url = proc.stdout.strip().splitlines()[-1].strip()
    if not url.startswith("http"):
        raise RuntimeError(f"Unexpected upload output: {proc.stdout!r}")
    print(f"Uploaded {image_file.name} -> {url}")
    return url


def main() -> int:
    p = argparse.ArgumentParser(description="Batch TRELLIS.2 jobs across seeds")
    p.add_argument("--image-url", help="Public HTTP(S) image URL for worker")
    p.add_argument(
        "--image-file",
        type=Path,
        help="Local image; uploads to R2 via scripts/upload_r2_asset.py first",
    )
    p.add_argument("--seeds", type=int, nargs="+", default=[1, 7, 42, 123])
    p.add_argument(
        "--pipeline-type",
        default="1024_cascade",
        choices=["512", "1024", "1024_cascade", "1536_cascade"],
    )
    p.add_argument("--texture-mode", default="clay", choices=["clay", "textured"])
    p.add_argument("--texture-size", type=int, default=2048, choices=[1024, 2048, 4096])
    p.add_argument("--decimation-target", type=int, default=500_000)
    p.add_argument("--out-prefix", default="model-armor-clay-seed")
    p.add_argument("--no-remesh", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if not args.image_url and not args.image_file:
        p.error("one of --image-url or --image-file is required")

    image_url = _resolve_image_url(args) if not args.dry_run else (
        args.image_url or f"<upload:{args.image_file}>"
    )

    test_script = ROOT / "test_req_trellis2.py"
    py = sys.executable
    failed: list[int] = []

    for seed in args.seeds:
        out = ROOT / f"{args.out_prefix}{seed}.glb"
        cmd = [
            py,
            str(test_script),
            "--image-url",
            image_url,
            "--pipeline-type",
            args.pipeline_type,
            "--texture-mode",
            args.texture_mode,
            "--decimation-target",
            str(args.decimation_target),
            "--seed",
            str(seed),
            "--save",
            str(out),
        ]
        if args.texture_mode == "textured":
            cmd.extend(["--texture-size", str(args.texture_size)])
        if args.no_remesh:
            cmd.append("--no-remesh")

        print(f"\n{'[dry-run] ' if args.dry_run else ''}=== seed={seed} -> {out.name} ===")
        if args.dry_run:
            print(" ".join(cmd))
            continue

        rc = subprocess.call(cmd, cwd=ROOT)
        if rc != 0:
            failed.append(seed)
            print(f"WARN: seed={seed} failed (exit {rc})", file=sys.stderr)

    if args.dry_run:
        return 0
    if failed:
        print(f"Failed seeds: {failed}", file=sys.stderr)
        return 1
    print("\nDone. Open each GLB in preview_glb_local.html with Wireframe enabled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
