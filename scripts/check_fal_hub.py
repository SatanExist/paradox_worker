"""Offline checks for FAL hub: geo gate, credits 2.5x, official input fields."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studio_bridge.credits import (  # noqa: E402
    CREDIT_USD,
    FAL_MARKUP,
    credit_catalog,
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
from studio_bridge.gateway import (  # noqa: E402
    EngineNotConfiguredError,
    create_studio_job,
    encode_fal_job_id,
    encode_hitem_job_id,
    encode_rodin_job_id,
    encode_tripo_job_id,
    parse_fal_job_id,
    parse_hitem_job_id,
    parse_rodin_job_id,
    parse_tripo_job_id,
)
from studio_bridge.hitem_client import HITEM_PRESETS, map_hitem_state, view_plan  # noqa: E402
from studio_bridge.rodin_client import RODIN_PRESETS, map_rodin_jobs  # noqa: E402
from studio_bridge.tripo_client import TRIPO_PRESETS, map_tripo_status  # noqa: E402
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
    assert "hunyuan" not in ru_ids
    assert "rodin" in ru_ids
    assert "tripo" in ru_ids
    assert "hitem3d" in ru_ids
    catalog_ids = {e["id"] for e in engine_catalog(country="US")}
    assert catalog_ids == {
        "trellis2",
        "hi3dgen",
        "meshy",
        "hitem3d",
        "hitem3d_pro",
        "hitem3d_v3",
        "hitem3d_portrait",
        "tripo",
        "tripo_p1",
        "rodin",
        "rodin_extreme",
    }
    assert "trellis2_fal" not in catalog_ids
    assert get_engine("hitem3d").provider == "hitem"
    assert get_engine("tripo").provider == "tripo"
    assert get_engine("rodin").provider == "rodin"
    assert get_engine("tripo_p1").provider == "tripo"
    assert "configured" in engine_catalog()[0]

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
    try:
        build_fal_arguments("rodin", image_urls=["https://a.png"])
        raise AssertionError("rodin is not a FAL engine")
    except ValueError:
        pass
    try:
        build_fal_arguments("tripo", image_urls=["https://a.png"], seed=7)
        raise AssertionError("tripo is not a FAL engine")
    except ValueError:
        pass
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
    hitem_job = encode_hitem_job_id(
        "hitem3d", "528f172b66554be2a2d1e95db4454a5a.jjewelry-aigc-api.7qbh5Z0wfR"
    )
    assert parse_hitem_job_id(hitem_job)[0] == "hitem3d"
    assert parse_hitem_job_id(hitem_job)[1].endswith("7qbh5Z0wfR")
    tripo_job = encode_tripo_job_id("tripo_p1", "task_abc123")
    assert parse_tripo_job_id(tripo_job) == ("tripo_p1", "task_abc123")
    rodin_job = encode_rodin_job_id("rodin_extreme", "uuid-1", "sub-key")
    assert parse_rodin_job_id(rodin_job) == ("rodin_extreme", "uuid-1", "sub-key")

    bit, ordered = view_plan(image_urls=["https://front.png"])
    assert bit is None and ordered == [("front", "https://front.png")]
    bit, ordered = view_plan(
        image_urls=["https://front.png"],
        view_slots={
            "front": "https://front.png",
            "back": "https://back.png",
            "side": "https://left.png",
        },
    )
    assert bit == "1110"
    assert [s for s, _ in ordered] == ["front", "back", "side"]
    assert map_hitem_state("queueing") == "queued"
    assert map_hitem_state("success") == "ready"

    hitem_q = quote_engine("hitem3d")
    assert hitem_q.kind == "hitem"
    assert hitem_q.credits == 50
    assert hitem_q.usd_cogs == 0.50
    assert quote_engine("hitem3d_v3").credits == 210
    assert quote_engine("tripo").kind == "tripo"
    assert quote_engine("tripo").credits == 30
    assert quote_engine("tripo_p1").credits == 50
    assert quote_engine("rodin").kind == "rodin"
    assert quote_engine("rodin").credits == 30
    assert quote_engine("rodin_extreme").credits == 60
    assert set(HITEM_PRESETS) == {
        "hitem3d",
        "hitem3d_pro",
        "hitem3d_v3",
        "hitem3d_portrait",
    }
    assert set(TRIPO_PRESETS) == {"tripo", "tripo_p1"}
    assert set(RODIN_PRESETS) == {"rodin", "rodin_extreme"}
    assert map_tripo_status("success") == "ready"
    assert map_tripo_status("cancelled") == "failed"
    assert map_rodin_jobs({"jobs": [{"status": "Done"}]}) == "ready"

    tariffs = {row["engineId"] for row in credit_catalog()["tariffs"]}
    assert "meshy" in tariffs
    assert "hitem3d" in tariffs
    assert "hitem3d_v3" in tariffs
    assert "tripo" in tariffs
    assert "tripo_p1" in tariffs
    assert "rodin" in tariffs
    assert "rodin_extreme" in tariffs
    assert "hunyuan" not in tariffs

    try:
        create_studio_job(engine="hunyuan", image_url="https://a.png")
        raise AssertionError("hunyuan must be off the FAL shelf")
    except EngineNotConfiguredError:
        pass

    bundle = studio_copy_bundle(country="DE")
    assert bundle["defaultEngine"] == "trellis2"
    assert bundle["credits"]["refundOnFail"] is True
    assert bundle["credits"]["unlimitedOff"] is True
    bundle_ids = {e["id"] for e in bundle["engines"]}
    assert "meshy" in bundle_ids
    assert "hitem3d" in bundle_ids
    assert "tripo" in bundle_ids
    assert "rodin" in bundle_ids
    assert "hunyuan" not in bundle_ids

    print("fal hub checks: OK")


if __name__ == "__main__":
    main()
