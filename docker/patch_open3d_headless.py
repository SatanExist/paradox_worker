"""Patch Open3D __init__.py without importing the package (avoids dash/plotly)."""
from __future__ import annotations

import importlib.util
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
    text = init_path.read_text(encoding="utf-8")
    if "# paradox: skip visualization" in text:
        print(f"already patched: {init_path}")
        return

    needle = "import open3d.visualization"
    if needle not in text:
        raise SystemExit(f"patch target missing in {init_path}")

    patched = text.replace(
        needle,
        "# paradox: skip visualization (dash/plotly) — UV atlas only\n"
        "# import open3d.visualization",
        1,
    )
    init_path.write_text(patched, encoding="utf-8")
    print(f"patched: {init_path}")


if __name__ == "__main__":
    main()
