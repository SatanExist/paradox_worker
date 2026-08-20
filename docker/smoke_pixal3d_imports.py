"""Build-time smoke test for the Pixal3D image (no GPU / libcuda required)."""
from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import pathlib
import sys
import traceback

# Match worker env before importing the pipeline (config is read at import time).
os.environ.setdefault("ATTN_BACKEND", "sdpa")
os.environ.setdefault("SPARSE_ATTN_BACKEND", "xformers")
os.environ.setdefault("SPARSE_CONV_BACKEND", "flex_gemm")

# pip distribution name -> import name
BUILT_PACKAGES: tuple[tuple[str, str], ...] = (
    ("cumesh", "cumesh"),
    ("flex_gemm", "flex_gemm"),
    ("o_voxel", "o_voxel"),
    ("xformers", "xformers"),
)


def _package_root(import_name: str) -> pathlib.Path:
    spec = importlib.util.find_spec(import_name)
    if spec is None:
        raise ImportError(f"find_spec({import_name!r}) returned None")
    if spec.submodule_search_locations:
        return pathlib.Path(next(iter(spec.submodule_search_locations)))
    if spec.origin:
        return pathlib.Path(spec.origin).parent
    raise ImportError(f"cannot resolve package root for {import_name!r}")


def _dist_version(dist_name: str) -> str:
    candidates = {dist_name, dist_name.replace("-", "_"), dist_name.replace("_", "-")}
    for candidate in candidates:
        try:
            return importlib.metadata.version(candidate)
        except importlib.metadata.PackageNotFoundError:
            continue
    raise importlib.metadata.PackageNotFoundError(dist_name)


def verify_built_package(dist_name: str, import_name: str) -> None:
    version = _dist_version(dist_name)
    root = _package_root(import_name)
    shared_objects = list(root.rglob("*.so"))
    if not shared_objects:
        raise RuntimeError(f"{import_name}: no compiled .so under {root}")
    print(f"{import_name}=={version} ({len(shared_objects)} .so): OK")


def verify_pixal3d() -> None:
    """The whole point of this image: the fork's own pipeline and proj mixin."""
    from pixal3d.pipelines import Pixal3DImageTo3DPipeline
    from pixal3d.trainers.flow_matching.mixins.image_conditioned_proj import (
        DinoV3ProjFeatureExtractor,
    )

    print(f"Pixal3DImageTo3DPipeline: {Pixal3DImageTo3DPipeline.__module__}: OK")
    print(f"DinoV3ProjFeatureExtractor: {DinoV3ProjFeatureExtractor.__module__}: OK")


def verify_moge() -> None:
    from moge.model.v2 import MoGeModel

    print(f"moge ({MoGeModel.__module__}): OK")


def main() -> int:
    checks = [
        *[(name, lambda d=dist, n=name: verify_built_package(d, n)) for dist, name in BUILT_PACKAGES],
        ("pixal3d", verify_pixal3d),
        ("moge", verify_moge),
    ]
    for label, check in checks:
        try:
            check()
        except Exception:
            traceback.print_exc()
            print(f"verify failed: {label}", file=sys.stderr)
            return 1

    print("all build checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
