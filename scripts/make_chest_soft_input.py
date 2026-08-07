"""CLI wrapper: soft-norm a local image (see studio_bridge.soft_input)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image

from studio_bridge.soft_input import DEFAULT_SOFT_STRENGTH, soften


def main() -> int:
    p = argparse.ArgumentParser(description="Soft-norm image for T2 mid-prop holes gate")
    p.add_argument(
        "--input",
        type=Path,
        default=Path("preview_textures/ref_chest.png"),
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("preview_textures/ref_chest_soft.png"),
    )
    p.add_argument("--strength", type=float, default=DEFAULT_SOFT_STRENGTH)
    args = p.parse_args()

    im = Image.open(args.input)
    out = soften(im, strength=args.strength)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.save(args.output)
    print(f"wrote {args.output} size={out.size} strength={args.strength}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
