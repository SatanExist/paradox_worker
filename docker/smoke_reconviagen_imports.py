"""Build-time smoke test for ReconViaGen Docker image (no GPU / HF weights)."""
from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import pathlib
import sys
import traceback

os.environ.setdefault("XFORMERS_DISABLED", "1")
os.environ.setdefault("SPCONV_ALGO", "native")
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("ATTN_BACKEND", "flash_attn")
os.environ.setdefault("SPARSE_ATTN_BACKEND", "flash_attn")

RVG = pathlib.Path(os.environ.get("RVG_REPO", "/app/ReconViaGen"))
TRELLIS2 = RVG / "wheels" / "TRELLIS.2"
for p in (str(TRELLIS2), str(RVG)):
    if p not in sys.path:
        sys.path.insert(0, p)

BUILT_PACKAGES: tuple[tuple[str, str], ...] = (
    ("cumesh", "cumesh"),
    ("flex_gemm", "flex_gemm"),
    ("o_voxel", "o_voxel"),
    ("xformers", "xformers"),
    ("flash_attn", "flash_attn"),
    ("spconv", "spconv"),
    ("kaolin", "kaolin"),
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


def verify_torch_pin() -> None:
    import torch

    ver = torch.__version__
    if not ver.startswith("2.6.0"):
        raise RuntimeError(f"expected torch 2.6.0*, got {ver}")
    print(f"torch=={ver}: OK")


def verify_rvg_imports() -> None:
    import o_voxel  # noqa: F401

    import trellis  # noqa: F401
    import trellis2  # noqa: F401

    print(f"ReconViaGen repo: {RVG}")
    print(f"trellis: {pathlib.Path(trellis.__file__).parent}")
    print(f"trellis2: {pathlib.Path(trellis2.__file__).parent}")
    print("trellis + trellis2 import: OK")


def main() -> int:
    try:
        verify_torch_pin()
    except Exception:
        traceback.print_exc()
        print("verify failed: torch", file=sys.stderr)
        return 1

    for dist_name, import_name in BUILT_PACKAGES:
        try:
            verify_built_package(dist_name, import_name)
        except Exception:
            traceback.print_exc()
            print(f"verify failed: {import_name}", file=sys.stderr)
            return 1

    try:
        verify_rvg_imports()
    except Exception:
        traceback.print_exc()
        print("verify failed: ReconViaGen imports", file=sys.stderr)
        return 1

    print("all ReconViaGen build checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
