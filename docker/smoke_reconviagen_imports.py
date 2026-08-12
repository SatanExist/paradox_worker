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
os.environ.setdefault("ATTN_BACKEND", "sdpa")
os.environ.setdefault("SPARSE_ATTN_BACKEND", "xformers")
os.environ.setdefault("SPARSE_CONV_BACKEND", "flex_gemm")

RVG = pathlib.Path(os.environ.get("RVG_REPO", "/app/ReconViaGen"))
TRELLIS2 = RVG / "wheels" / "TRELLIS.2"
for p in (str(TRELLIS2), str(RVG)):
    if p not in sys.path:
        sys.path.insert(0, p)

# (dist_name_candidates, import_name)
BUILT_PACKAGES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("cumesh",), "cumesh"),
    (("flex_gemm", "flex-gemm"), "flex_gemm"),
    (("o_voxel", "o-voxel"), "o_voxel"),
    (("xformers",), "xformers"),
    (("spconv-cu121", "spconv_cu121", "spconv"), "spconv"),
    (("kaolin",), "kaolin"),
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


def _dist_version(candidates: tuple[str, ...]) -> tuple[str, str]:
    for candidate in candidates:
        for name in (candidate, candidate.replace("-", "_"), candidate.replace("_", "-")):
            try:
                return name, importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                continue
    raise importlib.metadata.PackageNotFoundError(str(candidates))


def verify_built_package(dist_candidates: tuple[str, ...], import_name: str) -> None:
    dist_name, version = _dist_version(dist_candidates)
    root = _package_root(import_name)
    shared_objects = list(root.rglob("*.so"))
    if not shared_objects:
        raise RuntimeError(f"{import_name}: no compiled .so under {root}")
    print(f"{import_name}=={version} (dist={dist_name}, {len(shared_objects)} .so): OK")


def verify_torch_pin() -> None:
    import torch

    ver = torch.__version__
    if not ver.startswith("2.6.0"):
        raise RuntimeError(f"expected torch 2.6.0*, got {ver}")
    print(f"torch=={ver}: OK")


def verify_rvg_imports() -> None:
    trellis_init = RVG / "trellis" / "__init__.py"
    trellis2_init = TRELLIS2 / "trellis2" / "__init__.py"
    hybrid = RVG / "trellis" / "pipelines" / "trellis_hybrid_pipeline.py"
    for path in (trellis_init, trellis2_init, hybrid):
        if not path.is_file():
            raise FileNotFoundError(f"missing required file: {path}")

    # find_spec only — full import pulls CUDA extensions (no libcuda on buildx).
    for name in ("trellis", "trellis2", "o_voxel"):
        spec = importlib.util.find_spec(name)
        if spec is None:
            raise ImportError(f"find_spec({name!r}) returned None")
        print(f"{name}: find_spec OK ({spec.origin or spec.submodule_search_locations})")

    print(f"ReconViaGen repo: {RVG}")
    print(f"hybrid pipeline: {hybrid}")
    print("trellis + trellis2 paths: OK")


def main() -> int:
    try:
        verify_torch_pin()
    except Exception:
        traceback.print_exc()
        print("verify failed: torch", file=sys.stderr)
        return 1

    for dist_candidates, import_name in BUILT_PACKAGES:
        try:
            verify_built_package(dist_candidates, import_name)
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
