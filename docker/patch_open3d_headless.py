"""Patch Open3D __init__.py for headless UV-atlas use (no dash/plotly/ml GUI).

Must not import open3d — visualization/ml fail without optional deps.
"""
from __future__ import annotations

import importlib.util
import re
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


def _comment_line(text: str, needle: str, reason: str) -> str:
    if f"# paradox: skip {reason}" in text:
        return text
    if needle not in text:
        raise SystemExit(f"patch target missing ({needle!r})")
    return text.replace(
        needle,
        f"# paradox: skip {reason}\n# {needle}",
        1,
    )


def main() -> None:
    init_path = _find_open3d_init()
    text = init_path.read_text(encoding="utf-8")
    if "# paradox: headless uv-atlas" in text:
        print(f"already patched: {init_path}")
        return

    # Mark file so smoke can detect the patch set.
    text = "# paradox: headless uv-atlas\n" + text

    text = _comment_line(text, "import open3d.visualization", "visualization")
    text = _comment_line(text, "import open3d.ml", "ml")

    # Jupyter block may still reference open3d.visualization.* — disable it.
    text = re.sub(
        r'if _build_config\["BUILD_JUPYTER_EXTENSION"\]',
        'if False and _build_config["BUILD_JUPYTER_EXTENSION"]  # paradox: skip jupyter',
        text,
        count=1,
    )

    init_path.write_text(text, encoding="utf-8")
    print(f"patched: {init_path}")


if __name__ == "__main__":
    main()
