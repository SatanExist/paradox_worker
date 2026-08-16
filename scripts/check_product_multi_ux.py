"""Offline checks for product multi UX helpers (no RunPod)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studio_bridge.product_multi_ux import (  # noqa: E402
    normalize_view_slots,
    resolve_image_sources,
    status_line,
    studio_copy_bundle,
)
from studio_bridge.tiers import (  # noqa: E402
    build_runpod_input,
    preset_tier,
    resolve_preset_id,
)


def main() -> int:
    assert resolve_preset_id("preview") == "low"
    assert resolve_preset_id("quality") == "medium"
    assert resolve_preset_id("ultra") == "high"
    assert resolve_preset_id("realistic") == "realistic"

    low = build_runpod_input(
        preset_tier("low"), image_url="https://a.png"
    )
    assert low["texture_mode"] == "textured"
    assert low["quality_tier"] == "preview"
    assert low["texture_size"] == 1024
    assert "soft_input" not in low

    med = build_runpod_input(
        preset_tier("medium"), image_url="https://a.png"
    )
    assert med["quality_tier"] == "quality"
    assert med["soft_input"] is True
    assert med["texture_size"] == 2048

    hi = build_runpod_input(
        preset_tier("high"), image_url="https://a.png"
    )
    assert hi["quality_tier"] == "ultra"
    assert hi["texture_size"] == 2048
    assert "soft_input" not in hi

    real = build_runpod_input(
        preset_tier("realistic"), image_url="https://a.png"
    )
    assert real["texture_size"] == 4096
    assert real["quality_tier"] == "ultra"
    assert real["material_polish"] is True
    assert "material_polish" not in med or med["material_polish"] is False
    assert hi.get("material_polish") is True

    alias = build_runpod_input(
        preset_tier("preview"), image_url="https://a.png"
    )
    assert alias["quality_tier"] == "preview"

    clay = build_runpod_input(
        preset_tier("medium"),
        image_url="https://a.png",
        texture_mode="clay",
        soft_input=False,
    )
    assert clay["texture_mode"] == "clay"
    assert "texture_size" not in clay
    assert "soft_input" not in clay


def main() -> None:
    assert normalize_view_slots({"front": "https://a"}) == ["https://a"]
    assert normalize_view_slots(
        {"front": "https://a", "back": "https://b", "side": "https://c"}
    ) == ["https://a", "https://c", "https://b"]

    urls, mode = resolve_image_sources(
        view_slots={"front": "https://a", "extra": "https://d"}
    )
    assert urls == ["https://a", "https://d"]
    assert mode == "stochastic"

    urls1, mode1 = resolve_image_sources(image_url="https://only")
    assert urls1 == ["https://only"] and mode1 is None

    assert status_line(1) == "Собрано с 1 фото"
    assert status_line(3) == "Собрано с 3 ракурсов"

    bundle = studio_copy_bundle()
    assert bundle["aiSheetNotSupported"] is True
    assert "front" in bundle["slotOrder"]
    assert bundle["defaultQualityPreset"] == "medium"
    ids = [p["id"] for p in bundle["qualityPresets"]]
    assert ids == ["low", "medium", "high", "realistic"]
    assert bundle["qualityPresets"][3]["textureSize"] == 4096

    try:
        normalize_view_slots({"side": "https://x"})
        raise AssertionError("expected missing front")
    except ValueError:
        pass

    print("product_multi_ux checks: OK")


if __name__ == "__main__":
    main()
