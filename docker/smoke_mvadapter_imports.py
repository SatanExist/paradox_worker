"""Build-time smoke test for MV-Adapter Docker image (no GPU / libcuda required)."""
from __future__ import annotations

import importlib.metadata
import importlib.util
import pathlib
import sys
import traceback

# pip distribution name -> import name (CUDA extensions: verify .so, do not import)
BUILT_PACKAGES: tuple[tuple[str, str], ...] = (
    ("nvdiffrast", "nvdiffrast"),
    ("cvcuda-cu12", "cvcuda"),
)

PURE_PACKAGES: tuple[str, ...] = (
    "torch",
    "diffusers",
    "transformers",
    "accelerate",
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


def verify_pure_import(import_name: str) -> None:
    module = __import__(import_name)
    version = getattr(module, "__version__", "unknown")
    print(f"{import_name}=={version}: OK")


def verify_mvadapter_repo() -> None:
    repo = pathlib.Path("/app/MV-Adapter")
    if not (repo / "scripts" / "texture_i2tex.py").is_file():
        raise RuntimeError(f"MV-Adapter entry script missing under {repo}")
    checkpoints = repo / "checkpoints"
    for name in ("RealESRGAN_x2plus.pth", "big-lama.pt"):
        path = checkpoints / name
        if not path.is_file() or path.stat().st_size < 1024:
            raise RuntimeError(f"checkpoint missing or too small: {path}")
    print(f"MV-Adapter repo + checkpoints: OK")


def main() -> int:
    for import_name in PURE_PACKAGES:
        try:
            verify_pure_import(import_name)
        except Exception:
            traceback.print_exc()
            print(f"verify failed: {import_name}", file=sys.stderr)
            return 1

    for dist_name, import_name in BUILT_PACKAGES:
        try:
            verify_built_package(dist_name, import_name)
        except Exception:
            traceback.print_exc()
            print(f"verify failed: {import_name}", file=sys.stderr)
            return 1

    try:
        verify_mvadapter_repo()
    except Exception:
        traceback.print_exc()
        print("verify failed: MV-Adapter repo", file=sys.stderr)
        return 1

    print("all mvadapter build checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
