"""Install headless Open3D __init__.py without importing the package."""
from __future__ import annotations

import importlib.util
import shutil
import site
from pathlib import Path


def _find_open3d_init() -> Path:
    spec = importlib.util.find_spec("open3d")
    if spec is not None and spec.origin:
        return Path(spec.origin).resolve()

    for root in site.getsitepackages():
        candidate = Path(root) / "open3d" / "__init__.py"
        if candidate.is_file():
            return candidate.resolve()

    raise FileNotFoundError("open3d package not found in site-packages")


def main() -> None:
    init_path = _find_open3d_init()
    replacement = Path("/tmp/open3d_headless_init.py")
    if not replacement.is_file():
        # Local/dev fallback next to this script
        replacement = Path(__file__).resolve().with_name("open3d_headless_init.py")
    if not replacement.is_file():
        raise FileNotFoundError(f"headless init missing: {replacement}")

    backup = init_path.with_suffix(".py.upstream")
    if not backup.exists():
        shutil.copy2(init_path, backup)

    shutil.copy2(replacement, init_path)
    text = init_path.read_text(encoding="utf-8")
    if "# paradox: headless uv-atlas" not in text:
        raise SystemExit(f"replacement missing paradox marker: {init_path}")
    print(f"replaced open3d __init__ with headless loader: {init_path}")


if __name__ == "__main__":
    main()
