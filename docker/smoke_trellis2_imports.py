"""Build-time smoke test for TRELLIS.2 Docker image (no GPU / libcuda required)."""
from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import pathlib
import sys
import traceback

# Match worker env before importing trellis2 (config is read at import time).
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


def verify_trellis2() -> None:
    import trellis2
    from trellis2.modules.attention import config as attn_config
    from trellis2.modules.sparse import config as sparse_config

    if attn_config.BACKEND != "sdpa":
        raise RuntimeError(f"ATTN_BACKEND expected sdpa, got {attn_config.BACKEND}")
    if sparse_config.ATTN != "xformers":
        raise RuntimeError(f"SPARSE_ATTN_BACKEND expected xformers, got {sparse_config.ATTN}")
    if sparse_config.CONV != "flex_gemm":
        raise RuntimeError(f"SPARSE_CONV_BACKEND expected flex_gemm, got {sparse_config.CONV}")
    print(f"trellis2 ({pathlib.Path(trellis2.__file__).parent}): OK")


def main() -> int:
    for dist_name, import_name in BUILT_PACKAGES:
        try:
            verify_built_package(dist_name, import_name)
        except Exception:
            traceback.print_exc()
            print(f"verify failed: {import_name}", file=sys.stderr)
            return 1

    try:
        verify_trellis2()
    except Exception:
        traceback.print_exc()
        print("verify failed: trellis2", file=sys.stderr)
        return 1

    print("all build checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
