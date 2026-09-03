"""Engine catalog + FAL input builders from official model API tabs (2026-08-27).

FAL live shelf: Meshy only. Hitem / Tripo / Rodin = direct vendor APIs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

from studio_bridge.credits import quote_engine, quote_rodin
from studio_bridge.engine_showcases import attach_showcases
from studio_bridge.geo import hunyuan_allowed
from studio_bridge.hitem_client import HITEM_PRESETS
from studio_bridge.rodin_client import (
    DEFAULT_RODIN_QUALITY,
    RODIN_ENGINE,
    RODIN_QUALITY_TIERS,
    is_rodin_engine,
)
from studio_bridge.tripo_client import TRIPO_PRESETS

SLOT_ORDER: tuple[str, ...] = ("front", "side", "back", "extra")

Provider = Literal["runpod", "fal", "hitem", "tripo", "rodin"]

DEFAULT_ENGINE = "trellis2"
KNIGHT_GATE_STATUS = "pending"  # eyes before prod; see scripts/fal_knight_ab.py
# Partner FAL we actually sell. Everything else is vendor API or parked.
FAL_SHELF_IDS: frozenset[str] = frozenset({"meshy"})


@dataclass(frozen=True)
class EngineSpec:
    id: str
    label: str
    vendor: str
    provider: Provider
    role: str
    blurb: str
    fal_model: str | None
    geo_gated: bool
    show_in_catalog: bool
    quality_presets: bool
    docs_url: str
    eta_sec: int


_ENGINES: tuple[EngineSpec, ...] = (
    EngineSpec(
        id="trellis2",
        label="TRELLIS.2 — native PBR",
        vendor="AI_MESH / Microsoft TRELLIS.2",
        provider="runpod",
        role="quality",
        blurb="Качество по умолчанию. Единственный слот, прошедший нашего рыцаря.",
        fal_model=None,
        geo_gated=False,
        show_in_catalog=True,
        quality_presets=True,
        docs_url="",
        eta_sec=240,
    ),
    EngineSpec(
        id="hi3dgen",
        label="Hi3DGen — черновик",
        vendor="Stable-X Hi3DGen",
        provider="runpod",
        role="draft",
        blurb="Быстрый clay. Не обещать рыцаря.",
        fal_model=None,
        geo_gated=False,
        show_in_catalog=True,
        quality_presets=False,
        docs_url="",
        eta_sec=30,
    ),
    EngineSpec(
        id="meshy",
        label="Meshy 6",
        vendor="Meshy",
        provider="fal",
        role="other",
        blurb="Партнёр FAL, не ключ meshy.ai. Дорогой слот, не default.",
        fal_model="fal-ai/meshy/v6/image-to-3d",
        geo_gated=False,
        show_in_catalog=True,
        quality_presets=False,
        docs_url="https://fal.ai/models/fal-ai/meshy/v6/image-to-3d/api",
        eta_sec=480,
    ),
    EngineSpec(
        id="hunyuan",
        label="Hunyuan Rapid (Tencent)",
        vendor="Tencent",
        provider="fal",
        role="other",
        blurb="Снят с FAL. Tencent позже. Не default.",
        fal_model="fal-ai/hunyuan-3d/v3.1/rapid/image-to-3d",
        geo_gated=True,
        show_in_catalog=False,
        quality_presets=False,
        docs_url="https://fal.ai/models/fal-ai/hunyuan-3d/v3.1/rapid/image-to-3d/api",
        eta_sec=180,
    ),
    EngineSpec(
        id="hunyuan_pro",
        label="Hunyuan Pro (Tencent)",
        vendor="Tencent",
        provider="fal",
        role="other",
        blurb="Снят с FAL. Tencent позже. Не default.",
        fal_model="fal-ai/hunyuan-3d/v3.1/pro/image-to-3d",
        geo_gated=True,
        show_in_catalog=False,
        quality_presets=False,
        docs_url="https://fal.ai/models/fal-ai/hunyuan-3d/v3.1/pro/image-to-3d/api",
        eta_sec=300,
    ),
    EngineSpec(
        id="hitem3d",
        label=HITEM_PRESETS["hitem3d"].label,
        vendor="Hitem3D",
        provider="hitem",
        role=HITEM_PRESETS["hitem3d"].role,
        blurb=HITEM_PRESETS["hitem3d"].blurb,
        fal_model=None,
        geo_gated=False,
        show_in_catalog=True,
        quality_presets=False,
        docs_url="https://docs.hi3d.ai/en/api/api-reference/list/create-task",
        eta_sec=HITEM_PRESETS["hitem3d"].eta_sec,
    ),
    EngineSpec(
        id="hitem3d_pro",
        label=HITEM_PRESETS["hitem3d_pro"].label,
        vendor="Hitem3D",
        provider="hitem",
        role=HITEM_PRESETS["hitem3d_pro"].role,
        blurb=HITEM_PRESETS["hitem3d_pro"].blurb,
        fal_model=None,
        geo_gated=False,
        show_in_catalog=True,
        quality_presets=False,
        docs_url="https://docs.hi3d.ai/en/api/api-reference/list/create-task",
        eta_sec=HITEM_PRESETS["hitem3d_pro"].eta_sec,
    ),
    EngineSpec(
        id="hitem3d_v3",
        label=HITEM_PRESETS["hitem3d_v3"].label,
        vendor="Hitem3D",
        provider="hitem",
        role=HITEM_PRESETS["hitem3d_v3"].role,
        blurb=HITEM_PRESETS["hitem3d_v3"].blurb,
        fal_model=None,
        geo_gated=False,
        show_in_catalog=True,
        quality_presets=False,
        docs_url="https://docs.hi3d.ai/en/api/api-reference/list/create-task",
        eta_sec=HITEM_PRESETS["hitem3d_v3"].eta_sec,
    ),
    EngineSpec(
        id="hitem3d_portrait",
        label=HITEM_PRESETS["hitem3d_portrait"].label,
        vendor="Hitem3D",
        provider="hitem",
        role=HITEM_PRESETS["hitem3d_portrait"].role,
        blurb=HITEM_PRESETS["hitem3d_portrait"].blurb,
        fal_model=None,
        geo_gated=False,
        show_in_catalog=True,
        quality_presets=False,
        docs_url="https://docs.hi3d.ai/en/api/api-reference/list/create-task",
        eta_sec=HITEM_PRESETS["hitem3d_portrait"].eta_sec,
    ),
    EngineSpec(
        id="rodin",
        label=RODIN_ENGINE.label,
        vendor="Hyper3D / Deemos",
        provider="rodin",
        role="hard_surface",
        blurb=RODIN_ENGINE.blurb,
        fal_model=None,
        geo_gated=False,
        show_in_catalog=True,
        quality_presets=False,
        docs_url="https://docs.hyper3d.ai/en/api-specification/rodin-gen2-5",
        eta_sec=RODIN_ENGINE.eta_sec,
    ),
    EngineSpec(
        id="rodin_extreme",
        label="Rodin 2.5 Extreme",
        vendor="Hyper3D / Deemos",
        provider="rodin",
        role="hard_surface",
        blurb="Legacy engine id — use rodin + ultra quality tier.",
        fal_model=None,
        geo_gated=False,
        show_in_catalog=False,
        quality_presets=False,
        docs_url="https://docs.hyper3d.ai/en/api-specification/rodin-gen2-5",
        eta_sec=RODIN_QUALITY_TIERS["ultra"].eta_sec,
    ),
    EngineSpec(
        id="tripo",
        label=TRIPO_PRESETS["tripo"].label,
        vendor="Tripo / VAST",
        provider="tripo",
        role="fast_other",
        blurb=TRIPO_PRESETS["tripo"].blurb,
        fal_model=None,
        geo_gated=False,
        show_in_catalog=True,
        quality_presets=False,
        docs_url="https://developers.tripo3d.ai/en/docs/generation-image-to-model",
        eta_sec=TRIPO_PRESETS["tripo"].eta_sec,
    ),
    EngineSpec(
        id="tripo_p1",
        label=TRIPO_PRESETS["tripo_p1"].label,
        vendor="Tripo / VAST",
        provider="tripo",
        role="fast_other",
        blurb=TRIPO_PRESETS["tripo_p1"].blurb,
        fal_model=None,
        geo_gated=False,
        show_in_catalog=True,
        quality_presets=False,
        docs_url="https://developers.tripo3d.ai/en/docs/generation-image-to-model/p",
        eta_sec=TRIPO_PRESETS["tripo_p1"].eta_sec,
    ),
    EngineSpec(
        id="tripo_p2",
        label=TRIPO_PRESETS["tripo_p2"].label,
        vendor="Tripo / VAST",
        provider="tripo",
        role="fast_other",
        blurb=TRIPO_PRESETS["tripo_p2"].blurb,
        fal_model=None,
        geo_gated=False,
        show_in_catalog=True,
        quality_presets=False,
        docs_url="https://developers.tripo3d.ai/en/docs/generation-image-to-model/p",
        eta_sec=TRIPO_PRESETS["tripo_p2"].eta_sec,
    ),
    EngineSpec(
        id="trellis2_fal",
        label="TRELLIS.2 (FAL backup)",
        vendor="FAL / TRELLIS.2",
        provider="fal",
        role="backup",
        blurb="Только если наш GPU лёг. Дороже своего T2 — не витрина.",
        fal_model="fal-ai/trellis-2",
        geo_gated=False,
        show_in_catalog=False,
        quality_presets=False,
        docs_url="https://fal.ai/models/fal-ai/trellis-2/api",
        eta_sec=180,
    ),
)

_BY_ID: dict[str, EngineSpec] = {e.id: e for e in _ENGINES}


def get_engine(engine_id: str | None) -> EngineSpec:
    eid = (engine_id or DEFAULT_ENGINE).strip().lower() or DEFAULT_ENGINE
    spec = _BY_ID.get(eid)
    if spec is None:
        allowed = ", ".join(_BY_ID)
        raise ValueError(f"unknown engine {engine_id!r}; expected {allowed}")
    return spec


def is_hunyuan_engine(engine_id: str | None) -> bool:
    return get_engine(engine_id).geo_gated


def on_fal_shelf(engine_id: str | None) -> bool:
    return get_engine(engine_id).id in FAL_SHELF_IDS


def engine_keys_configured(spec: EngineSpec) -> bool:
    if spec.provider == "runpod":
        if spec.id == "hi3dgen":
            return bool(
                os.getenv("RUNPOD_API_KEY", "").strip()
                and os.getenv("RUNPOD_ENDPOINT_ID_HI3DGEN", "").strip()
            )
        return bool(os.getenv("RUNPOD_API_KEY", "").strip())
    if spec.provider == "fal":
        return bool(os.getenv("FAL_KEY", "").strip())
    if spec.provider == "hitem":
        return bool(
            os.getenv("HITEM_CLIENT_ID", "").strip()
            and os.getenv("HITEM_CLIENT_SECRET", "").strip()
        )
    if spec.provider == "tripo":
        return bool(os.getenv("TRIPO_API_KEY", "").strip())
    if spec.provider == "rodin":
        return bool(
            os.getenv("RODIN_API_KEY", "").strip()
            or os.getenv("HYPER3D_API_KEY", "").strip()
        )
    return False


def engine_catalog(*, country: str | None = None, include_hidden: bool = False) -> list[dict]:
    out: list[dict] = []
    for spec in _ENGINES:
        if not spec.show_in_catalog and not include_hidden:
            continue
        visible = True
        if spec.geo_gated:
            visible = hunyuan_allowed(country)
        quote = quote_engine(spec.id)
        out.append(
            {
                "id": spec.id,
                "label": spec.label,
                "vendor": spec.vendor,
                "provider": spec.provider,
                "role": spec.role,
                "blurb": spec.blurb,
                "default": spec.id == DEFAULT_ENGINE,
                "geoGated": spec.geo_gated,
                "visible": visible,
                "qualityPresets": spec.quality_presets,
                "falModel": spec.fal_model,
                "hitemModel": (HITEM_PRESETS[spec.id].model if spec.provider == "hitem" else None),
                "hitemResolution": (
                    HITEM_PRESETS[spec.id].resolution if spec.provider == "hitem" else None
                ),
                "tripoModel": (TRIPO_PRESETS[spec.id].model if spec.provider == "tripo" else None),
                "rodinTier": (
                    RODIN_QUALITY_TIERS[DEFAULT_RODIN_QUALITY].api_tier
                    if spec.id == "rodin"
                    else None
                ),
                "rodinQualityTiers": (
                    [
                        {
                            "id": q.id,
                            "label": q.label,
                            "credits": quote_rodin(q.id).credits,
                            "etaSeconds": q.eta_sec,
                            "apiTier": q.api_tier,
                        }
                        for q in RODIN_QUALITY_TIERS.values()
                    ]
                    if spec.id == "rodin"
                    else None
                ),
                "configured": engine_keys_configured(spec),
                "docsUrl": spec.docs_url,
                "etaSeconds": spec.eta_sec,
                "credits": quote.credits,
                "creditsColdSurcharge": quote.credits_cold_surcharge,
                "knightGate": KNIGHT_GATE_STATUS,
            }
        )
    return attach_showcases(out)


def _slot_urls(view_slots: dict[str, str | None] | None, image_urls: list[str]) -> dict[str, str]:
    slots: dict[str, str] = {}
    if view_slots:
        for key in SLOT_ORDER:
            val = (view_slots.get(key) or "").strip()
            if val:
                slots[key] = val
    if "front" not in slots and image_urls:
        slots["front"] = image_urls[0]
        extra_keys = ("side", "back", "extra")
        for url, key in zip(image_urls[1:], extra_keys):
            slots.setdefault(key, url)
    return slots


def build_fal_arguments(
    engine_id: str,
    *,
    image_urls: list[str],
    view_slots: dict[str, str | None] | None = None,
    seed: int = 1,
) -> dict[str, Any]:
    """Payload for POST queue.fal.run/{model} — field names from each API tab."""
    spec = get_engine(engine_id)
    if spec.provider != "fal" or not spec.fal_model:
        raise ValueError(f"{engine_id} is not a FAL engine")
    if not image_urls:
        raise ValueError("image URL required")
    primary = image_urls[0]
    slots = _slot_urls(view_slots, image_urls)
    eid = spec.id

    if eid == "meshy":
        return {
            "image_url": primary,
            "should_texture": True,
            "enable_pbr": True,
            "enable_safety_checker": True,
        }
    if eid == "hunyuan":
        body: dict[str, Any] = {"input_image_url": primary, "enable_pbr": True}
        if slots.get("back"):
            body["back_image_url"] = slots["back"]
        if slots.get("side"):
            body["left_image_url"] = slots["side"]
        return body
    if eid == "hunyuan_pro":
        body = {
            "input_image_url": primary,
            "generate_type": "Normal",
            "enable_pbr": True,
            "face_count": 500_000,
        }
        if slots.get("back"):
            body["back_image_url"] = slots["back"]
        if slots.get("side"):
            body["left_image_url"] = slots["side"]
        return body
    if eid == "trellis2_fal":
        return {"image_url": primary}
    raise ValueError(f"no FAL builder for {eid}")


def _file_url(node: Any) -> str | None:
    if isinstance(node, str) and node.startswith("https://"):
        return node
    if isinstance(node, dict):
        url = node.get("url")
        if isinstance(url, str) and url.startswith("https://"):
            return url
    return None


def extract_glb_url(fal_result: dict[str, Any]) -> tuple[str | None, str | None, int | None]:
    """Return (glb_url, poster_url, bytes) from mixed Partner output schemas."""
    poster = _file_url(fal_result.get("thumbnail")) or _file_url(
        fal_result.get("rendered_image")
    )
    candidates: list[Any] = [
        fal_result.get("model_glb"),
        (fal_result.get("model_urls") or {}).get("glb")
        if isinstance(fal_result.get("model_urls"), dict)
        else None,
        fal_result.get("pbr_model"),
        fal_result.get("model_mesh"),
        fal_result.get("model"),
    ]
    glb_url = None
    size = None
    for node in candidates:
        url = _file_url(node)
        if not url:
            continue
        name = ""
        if isinstance(node, dict):
            name = str(node.get("file_name") or "")
            if isinstance(node.get("file_size"), int):
                size = node["file_size"]
        if url.lower().endswith(".glb") or name.lower().endswith(".glb"):
            glb_url = url
            break
        if glb_url is None:
            glb_url = url
    if glb_url and not glb_url.lower().endswith(".glb"):
        # Hunyuan Rapid sometimes returns OBJ in model_glb; refuse as Studio GLB.
        if ".obj" in glb_url.lower():
            return None, poster, size
    return glb_url, poster, size
