"""Build-time smoke for the Direct3D-S2 image (no GPU required)."""
from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import pathlib
import sys
import traceback

os.environ.setdefault("SPARSE_BACKEND", "torchsparse")
os.environ.setdefault("SPARSE_ATTN_BACKEND", "xformers")
os.environ.setdefault("ATTN_BACKEND", "xformers")

BUILT_PACKAGES: tuple[tuple[str, str], ...] = (
    ("torchsparse", "torchsparse"),
    ("udf_ext", "udf_ext"),
    ("xformers", "xformers"),
    ("flash-attn", "flash_attn"),
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
    return "(no dist metadata)"


def verify_built_package(dist_name: str, import_name: str) -> None:
    """Prove the extension is on disk. Do not import CUDA extensions here:
    torchsparse.backends.init() needs a GPU driver, and udf_ext needs
    libc10.so on LD_LIBRARY_PATH (set in the Dockerfile after torch install).
    """
    version = _dist_version(dist_name)
    root = _package_root(import_name)
    shared_objects = list(root.rglob("*.so"))
    if not shared_objects and import_name != "xformers":
        raise RuntimeError(f"{import_name}: no compiled .so under {root}")
    print(f"{import_name}=={version} ({len(shared_objects)} .so): OK")

    if import_name in ("torchsparse", "udf_ext", "flash_attn"):
        return
    __import__(import_name)


def verify_pipeline_tree() -> None:
    import direct3d_s2  # noqa: F401

    root = _package_root("direct3d_s2")
    path = root / "pipeline.py"
    needle = "class Direct3DS2Pipeline"
    if needle not in path.read_text(encoding="utf-8"):
        raise RuntimeError(f"{needle!r} not found in {path}")
    print(f"{path.relative_to(root.parent)} has {needle!r}: OK")


def verify_pipeline_import() -> None:
    """May fail on CI if a native dep pulls CUDA at import time; tree check remains."""
    from direct3d_s2.pipeline import Direct3DS2Pipeline

    print(f"Direct3DS2Pipeline ({Direct3DS2Pipeline.__module__}): OK")


def main() -> int:
    checks = [
        *[(name, lambda d=dist, n=name: verify_built_package(d, n)) for dist, name in BUILT_PACKAGES],
        ("pipeline_tree", verify_pipeline_tree),
        ("pipeline_import", verify_pipeline_import),
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

    # torchsparse / udf_ext / the class on disk are fatal. A GPU-less pipeline
    # import is not: same triton landmine as Pixal3D.
    hard = [name for name in failed if name != "pipeline_import"]
    if hard:
        print(f"SMOKE SUMMARY: failed = {', '.join(failed)}", file=sys.stderr)
        return 1
    if failed:
        print("pipeline import skipped on this runner; native deps OK")
    print("all build checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
