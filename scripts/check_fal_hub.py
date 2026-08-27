"""Offline checks for FAL hub: geo gate, credits 2.5x, official input fields."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studio_bridge.credits import (  # noqa: E402
    CREDIT_USD,
    FAL_MARKUP,
    fal_user_credits,
    quote_engine,
    refund_payload,
)
from studio_bridge.engines import (  # noqa: E402
    build_fal_arguments,
    engine_catalog,
    extract_glb_url,
    get_engine,
)
from studio_bridge.gateway import encode_fal_job_id, parse_fal_job_id  # noqa: E402
from studio_bridge.geo import (  # noqa: E402
    HunyuanGeoBlocked,
    assert_hunyuan_allowed,
    country_from_headers,
    hunyuan_allowed,
)
from studio_bridge.product_multi_ux import studio_copy_bundle  # noqa: E402


def main() -> None:
    assert hunyuan_allowed("RU") is True
    assert hunyuan_allowed("US") is True
    assert hunyuan_allowed("DE") is False
    assert hunyuan_allowed("GB") is False
    assert hunyuan_allowed("UK") is False
    assert hunyuan_allowed("KR") is False
    assert hunyuan_allowed(None) is False
    assert hunyuan_allowed("XX") is False

    try:
        assert_hunyuan_allowed("DE")
        raise AssertionError("DE must be blocked")
    except HunyuanGeoBlocked:
        pass

    assert country_from_headers({"CF-IPCountry": "de"}) == "DE"
    assert country_from_headers({"cf-ipcountry": "FR"}, explicit="RU") == "RU"

    assert fal_user_credits(0.80) == 80  # 0.80 * 2.5 / 0.025
    assert fal_user_credits(0.40) == 40
    assert fal_user_credits(0.225) == 23
    meshy = quote_engine("meshy")
    assert meshy.kind == "fal"
    assert meshy.credits == 80
    assert meshy.usd_user + 1e-9 >= meshy.usd_cogs * FAL_MARKUP
    t2 = quote_engine("trellis2", tier="medium")
    assert t2.credits == 10
    assert t2.credits_cold_surcharge == 12
    draft = quote_engine("trellis2", tier="low")
    assert draft.credits == 4
    refund = refund_payload(meshy, error="boom")
    assert refund["creditsRefunded"] is True
    assert refund["creditsCharged"] == 0
    assert CREDIT_USD == 0.025

    de_ids = {e["id"] for e in engine_catalog(country="DE") if e["visible"]}
    assert "hunyuan" not in de_ids
    assert "hunyuan_pro" not in de_ids
    assert "meshy" in de_ids
    assert "trellis2" in de_ids
    ru_ids = {e["id"] for e in engine_catalog(country="RU") if e["visible"]}
    assert "hunyuan" in ru_ids
    catalog_ids = {e["id"] for e in engine_catalog(country="US")}
    assert "trellis2_fal" not in catalog_ids

    meshy_in = build_fal_arguments("meshy", image_urls=["https://a.png"])
    assert meshy_in["image_url"] == "https://a.png"
    assert meshy_in["enable_pbr"] is True
    hun = build_fal_arguments(
        "hunyuan",
        image_urls=["https://front.png"],
        view_slots={"front": "https://front.png", "back": "https://back.png", "side": "https://side.png"},
    )
    assert hun["input_image_url"] == "https://front.png"
    assert hun["back_image_url"] == "https://back.png"
    assert hun["left_image_url"] == "https://side.png"
    assert "image_url" not in hun
    rodin = build_fal_arguments("rodin", image_urls=["https://a.png"])
    assert rodin["input_image_urls"] == ["https://a.png"]
    hitem = build_fal_arguments("hitem3d", image_urls=["https://a.png"])
    assert hitem["resolution"] == "1536fast"
    tripo = build_fal_arguments("tripo", image_urls=["https://a.png"], seed=7)
    assert tripo["image_url"] == "https://a.png" and tripo["seed"] == 7
    assert get_engine("hunyuan").fal_model.endswith("rapid/image-to-3d")

    glb, poster, size = extract_glb_url(
        {
            "model_glb": {"url": "https://x/model.glb", "file_size": 12},
            "thumbnail": {"url": "https://x/preview.png"},
        }
    )
    assert glb.endswith(".glb") and poster.endswith(".png") and size == 12
    obj_only, _, _ = extract_glb_url(
        {"model_glb": {"url": "https://x/model.obj", "file_name": "model.obj"}}
    )
    assert obj_only is None

    job = encode_fal_job_id("meshy", "abc-123")
    assert parse_fal_job_id(job) == ("meshy", "abc-123")

    bundle = studio_copy_bundle(country="DE")
    assert bundle["defaultEngine"] == "trellis2"
    assert bundle["credits"]["refundOnFail"] is True
    assert bundle["credits"]["unlimitedOff"] is True
    hunyuan_row = next(e for e in bundle["engines"] if e["id"] == "hunyuan")
    assert hunyuan_row["visible"] is False

    print("fal hub checks: OK")


if __name__ == "__main__":
    main()
