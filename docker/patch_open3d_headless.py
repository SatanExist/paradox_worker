"""Patch Open3D so headless UV-atlas usage does not import dash/plotly GUI stack."""
from __future__ import annotations

from pathlib import Path

import open3d


def main() -> None:
    init_path = Path(open3d.__file__).resolve()
    text = init_path.read_text(encoding="utf-8")
    needle = "import open3d.visualization"
    if needle not in text:
        raise SystemExit(f"patch target missing in {init_path}")
    if "# paradox: skip visualization" in text:
        print(f"already patched: {init_path}")
        return
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
