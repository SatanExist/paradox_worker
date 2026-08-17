"""Offline poster renderer check (no RunPod). Needs numpy+trimesh+Pillow."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    try:
        import trimesh
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        print(f"poster checks skipped: {exc}")
        return

    from studio_bridge.poster import render_trimesh_poster

    mesh = trimesh.creation.icosphere(subdivisions=2, radius=1.0)
    img = render_trimesh_poster(mesh, size=64)
    assert isinstance(img, Image.Image)
    assert img.size == (64, 64)
    arr = np.asarray(img)
    assert arr.mean() > 8
    print("poster checks: OK (icosphere 64px)")


if __name__ == "__main__":
    main()
