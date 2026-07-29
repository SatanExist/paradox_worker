"""Build-time smoke test for MV-Adapter Docker image (no GPU / libcuda required)."""
from __future__ import annotations

import importlib.metadata
import importlib.util
import pathlib
import site
import sys
import traceback

PURE_PACKAGES: tuple[str, ...] = (
    "torch",
    "diffusers",
    "transformers",
    "accelerate",
    "spandrel",
    "imageio",
    "pymeshlab",
    "gltflib",
    "matplotlib",
)

# pip dist names verified without import (opencv can be finicky on buildx)
PIP_DIST_PACKAGES: tuple[tuple[str, ...], ...] = (
    ("opencv-python-headless", "opencv_python_headless"),
)

# import name -> pip dist candidates (git installs may omit metadata)
BUILT_EXTENSIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("nvdiffrast", ("nvdiffrast",)),
    ("cvcuda", ("cvcuda-cu12", "cvcuda")),
)


def _package_root(import_name: str) -> pathlib.Path | None:
    spec = importlib.util.find_spec(import_name)
    if spec is None:
        return None
    if spec.submodule_search_locations:
        return pathlib.Path(next(iter(spec.submodule_search_locations)))
    if spec.origin:
        return pathlib.Path(spec.origin).parent
    return None


def _dist_version(dist_names: tuple[str, ...]) -> str:
    for dist_name in dist_names:
        candidates = {dist_name, dist_name.replace("-", "_"), dist_name.replace("_", "-")}
        for candidate in candidates:
            try:
                return importlib.metadata.version(candidate)
            except importlib.metadata.PackageNotFoundError:
                continue
    return "unknown"


def _find_extension_so(keyword: str) -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    root = _package_root(keyword)
    if root is not None:
        found.extend(root.rglob("*.so"))

    for sp in site.getsitepackages():
        base = pathlib.Path(sp)
        if not base.is_dir():
            continue
        for so in base.rglob("*.so"):
            if keyword.lower() in str(so).lower():
                found.append(so)

    # de-dupe while preserving order
    seen: set[str] = set()
    unique: list[pathlib.Path] = []
    for path in found:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def verify_pip_dist(dist_names: tuple[str, ...]) -> None:
    version = _dist_version(dist_names)
    if version == "unknown":
        raise RuntimeError(f"package not installed: {dist_names[0]}")
    print(f"{dist_names[0]}=={version}: OK")


def verify_pure_import(import_name: str) -> None:
    module = __import__(import_name)
    version = getattr(module, "__version__", "unknown")
    print(f"{import_name}=={version}: OK")


def verify_built_extension(import_name: str, dist_names: tuple[str, ...]) -> None:
    version = _dist_version(dist_names)
    shared_objects = _find_extension_so(import_name)
    if not shared_objects:
        raise RuntimeError(f"{import_name}: no compiled .so found in site-packages")
    print(f"{import_name}=={version} ({len(shared_objects)} .so): OK")


def verify_mvadapter_repo() -> None:
    repo = pathlib.Path("/app/MV-Adapter")
    if not (repo / "scripts" / "texture_i2tex.py").is_file():
        raise RuntimeError(f"MV-Adapter entry script missing under {repo}")
    checkpoints = repo / "checkpoints"
    for name in ("RealESRGAN_x2plus.pth", "big-lama.pt"):
        path = checkpoints / name
        if not path.is_file() or path.stat().st_size < 1024:
            raise RuntimeError(f"checkpoint missing or too small: {path}")
    print("MV-Adapter repo + checkpoints: OK")


def verify_open3d_headless() -> None:
    init_path = None
    spec = importlib.util.find_spec("open3d")
    if spec is not None and spec.origin:
        init_path = pathlib.Path(spec.origin)
    if init_path is None or not init_path.is_file():
        raise RuntimeError("open3d __init__.py not found")

    init_text = init_path.read_text(encoding="utf-8")
    if "# paradox: headless uv-atlas" not in init_text:
        raise RuntimeError("open3d headless patch marker missing")

    import open3d as o3d

    if not hasattr(o3d, "core") or not hasattr(o3d, "t"):
        raise RuntimeError("open3d missing core/t after headless patch")
    # Touch the tensor API used by MV-Adapter mesh_process / UV atlas.
    _ = o3d.core.Device("CPU:0")
    version = getattr(o3d, "__version__", "unknown")
    print(f"open3d=={version} headless core/t: OK")


def main() -> int:
    for dist_names in PIP_DIST_PACKAGES:
        try:
            verify_pip_dist(dist_names)
        except Exception:
            traceback.print_exc()
            print(f"verify failed: {dist_names[0]}", file=sys.stderr)
            return 1

    for import_name in PURE_PACKAGES:
        try:
            verify_pure_import(import_name)
        except Exception:
            traceback.print_exc()
            print(f"verify failed: {import_name}", file=sys.stderr)
            return 1

    for import_name, dist_names in BUILT_EXTENSIONS:
        try:
            verify_built_extension(import_name, dist_names)
        except Exception:
            traceback.print_exc()
            print(f"verify failed: {import_name}", file=sys.stderr)
            return 1

    try:
        verify_open3d_headless()
    except Exception:
        traceback.print_exc()
        print("verify failed: open3d headless", file=sys.stderr)
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
