"""Build-time smoke for the Step1X-3D geometry image (no GPU required)."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import traceback

REPO = pathlib.Path("/app/Step1X-3D")


def verify_repo_tree() -> None:
    pipeline = REPO / "step1x3d_geometry" / "models" / "pipelines" / "pipeline.py"
    if not pipeline.is_file():
        raise RuntimeError(f"missing {pipeline}")
    needle = "class Step1X3DGeometryPipeline"
    if needle not in pipeline.read_text(encoding="utf-8"):
        raise RuntimeError(f"{needle!r} not found in {pipeline}")
    print(f"{pipeline} has {needle!r}: OK")


def verify_no_texture_stack() -> None:
    """Geometry image must not pull the texture baker into the first CI."""
    forbidden = ("pytorch3d", "kaolin")
    present = [name for name in forbidden if importlib.util.find_spec(name) is not None]
    if present:
        raise RuntimeError(f"geometry image contains texture deps: {present}")
    print("pytorch3d/kaolin absent: OK")


def verify_inference_init() -> None:
    init = REPO / "step1x3d_geometry" / "__init__.py"
    text = init.read_text(encoding="utf-8")
    if "from . import data, models, systems" in text:
        raise RuntimeError("geometry __init__ still imports training data/systems")
    if "from . import models" not in text:
        raise RuntimeError("geometry __init__ does not import models")
    print("inference-only package init: OK")


def verify_cpu_imports() -> None:
    import pymeshlab  # noqa: F401
    import rembg  # noqa: F401
    import torch
    import trimesh  # noqa: F401
    from transformers import BitImageProcessor  # noqa: F401

    print(f"torch=={torch.__version__} cuda_built={torch.version.cuda}: OK")
    print("pymeshlab/rembg/trimesh/transformers: OK")


def main() -> int:
    checks = [
        ("repo_tree", verify_repo_tree),
        ("no_texture_stack", verify_no_texture_stack),
        ("inference_init", verify_inference_init),
        ("cpu_imports", verify_cpu_imports),
    ]
    failed: list[str] = []
    for label, check in checks:
        print(f"--- check: {label}")
        try:
            check()
        except Exception:
            traceback.print_exc()
            print(f"SMOKE FAILED: {label}", file=sys.stderr)
            failed.append(label)
    if failed:
        print(f"SMOKE SUMMARY: failed = {', '.join(failed)}", file=sys.stderr)
        return 1
    print("all build checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
