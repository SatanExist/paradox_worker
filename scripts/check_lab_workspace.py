"""Offline checks for the local generation workspace (no RunPod)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studio_bridge.lab_workspace import (  # noqa: E402
    list_local_glbs,
    safe_upload_name,
    smoke_image_refs,
    workspace_payload,
)


def main() -> None:
    assert safe_upload_name("Knight Photo.PNG") == "Knight_Photo.png"
    assert safe_upload_name("../x.exe") == "x.png"

    refs = smoke_image_refs()
    assert [r["id"] for r in refs] == ["armor", "chest"]
    assert all(r["url"].startswith("https://") for r in refs)

    tmp = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "preview_textures"
    models = list_local_glbs(tmp, limit=40)
    names = [m["id"] for m in models]
    if (tmp / "h0_armor_hi3dgen.glb").is_file():
        assert names[0] == "h0_armor_hi3dgen.glb"
        assert models[0]["label"].startswith("Hi3DGen H0")
    if (tmp / "preset_high_armor.png.glb").is_file():
        assert names.index("preset_high_armor.png.glb") < names.index(
            "armor_w2b_ultra_tex200k.glb"
        ) if "armor_w2b_ultra_tex200k.glb" in names else True
        assert any(m["pinned"] for m in models)

    payload = workspace_payload(tmp)
    assert "refs" in payload and "models" in payload
    assert "thumb" in models[0]
    assert "poster" not in models[0]
    print(f"lab_workspace checks: OK ({len(models)} glbs)")


if __name__ == "__main__":
    main()
