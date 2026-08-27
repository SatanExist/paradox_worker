"""Product multi UX — slot roles + Studio copy (path A).

Spec: memory-bank/productMultiUx.md
Studio (AI_MESH) should map UI slots → viewSlots / imageUrls via these helpers.
Do not accept AI-generated turnaround sheets as a product mode.
"""

from __future__ import annotations

from typing import Any, Mapping

from studio_bridge.tiers import (
    DEFAULT_MULTI_IMAGE_MODE,
    DEFAULT_PRESET,
    MAX_MULTI_IMAGES,
    MIN_MULTI_IMAGES,
    MultiImageMode,
    quality_preset_catalog,
)

# UI role order → RunPod image_urls order
SLOT_ORDER: tuple[str, ...] = ("front", "side", "back", "extra")

COPY_UNDER_FRONT = (
    "3D с одной картинки. Перед будет ближе к фото; бок и зад модель достраивает сама."
)

COPY_UNDER_EXTRA_VIEWS = (
    "Реальные фото того же предмета сбоку и сзади улучшают форму. "
    "Снимки должны быть похожи по свету и размеру. "
    "Картинки „со всех сторон“ из нейросети часто портят результат — лучше одна чёткая фотка."
)

COPY_TOOLTIP = (
    "Нужны: один объект, одна поза, разные углы, чистый фон. Не смешивайте фото и скетч."
)

COPY_STATUS_SINGLE = "Собрано с 1 фото"
COPY_STATUS_MULTI = "Собрано с {n} ракурсов"

HELP_CHECKLIST: tuple[str, ...] = (
    "Один предмет, одна поза",
    "Углы заметно разные (front / side / back)",
    "Похожий свет и размер в кадре",
    "Чистый фон (или удалить фон на всех)",
    "Не два почти одинаковых «почти front»",
    "Не AI-turnaround вместо съёмки",
    "Не фото + скетч вперемешку",
)


COPY_VIEWER = (
    "В 3D-окне включите свет окружения (IBL). Металл без него выглядит как краска."
)


def studio_copy_bundle(*, country: str | None = None) -> dict[str, Any]:
    """JSON-serializable copy for Studio / help pages."""
    from studio_bridge.credits import credit_catalog
    from studio_bridge.engines import DEFAULT_ENGINE, engine_catalog

    return {
        "underFront": COPY_UNDER_FRONT,
        "underExtraViews": COPY_UNDER_EXTRA_VIEWS,
        "tooltip": COPY_TOOLTIP,
        "statusSingle": COPY_STATUS_SINGLE,
        "statusMultiTemplate": COPY_STATUS_MULTI,
        "helpChecklist": list(HELP_CHECKLIST),
        "slotOrder": list(SLOT_ORDER),
        "defaultMultiImageMode": DEFAULT_MULTI_IMAGE_MODE,
        "minMultiImages": MIN_MULTI_IMAGES,
        "maxMultiImages": MAX_MULTI_IMAGES,
        "aiSheetNotSupported": True,
        "viewerIblHint": COPY_VIEWER,
        "defaultQualityPreset": DEFAULT_PRESET,
        "qualityPresets": quality_preset_catalog(),
        "defaultEngine": DEFAULT_ENGINE,
        "engines": engine_catalog(country=country),
        "credits": credit_catalog(),
        "hunyuanGeo": {
            "blockedRegions": ["EU", "GB", "KR"],
            "header": "CF-IPCountry",
            "failClosed": True,
        },
    }


def status_line(num_views: int) -> str:
    n = max(1, int(num_views))
    if n <= 1:
        return COPY_STATUS_SINGLE
    return COPY_STATUS_MULTI.format(n=n)


def normalize_view_slots(slots: Mapping[str, str | None] | None) -> list[str]:
    """Front required when slots used. Empty optional slots dropped. Order fixed.

    Returns 1 URL (single) or 2–4 URLs (multi). Raises ValueError on bad input.
    """
    if not slots:
        raise ValueError("viewSlots is empty")

    raw: dict[str, str] = {}
    for key, value in slots.items():
        role = (key or "").strip().lower()
        if role not in SLOT_ORDER:
            raise ValueError(
                f"unknown viewSlots key {key!r}; expected one of {SLOT_ORDER}"
            )
        url = (value or "").strip()
        if url:
            raw[role] = url

    front = raw.get("front")
    if not front:
        raise ValueError("viewSlots.front is required")

    ordered = [front]
    for role in SLOT_ORDER[1:]:
        if role in raw and raw[role] not in ordered:
            ordered.append(raw[role])

    if len(ordered) > MAX_MULTI_IMAGES:
        raise ValueError(f"at most {MAX_MULTI_IMAGES} view slots allowed")
    return ordered


def resolve_image_sources(
    *,
    image_url: str | None = None,
    image_urls: list[str] | None = None,
    view_slots: Mapping[str, str | None] | None = None,
) -> tuple[list[str], MultiImageMode | None]:
    """Prefer viewSlots when present. Returns (urls, multi_mode_or_none).

    multi_mode is DEFAULT_MULTI_IMAGE_MODE when len(urls) >= 2, else None.
    """
    if view_slots is not None:
        urls = normalize_view_slots(view_slots)
    else:
        cleaned: list[str] = []
        seen: set[str] = set()
        for u in image_urls or []:
            s = (u or "").strip()
            if not s or s in seen:
                continue
            seen.add(s)
            cleaned.append(s)
        if cleaned:
            urls = cleaned
        else:
            single = (image_url or "").strip()
            if not single:
                raise ValueError("imageUrl, imageUrls, or viewSlots is required")
            urls = [single]

    if len(urls) > MAX_MULTI_IMAGES:
        raise ValueError(f"at most {MAX_MULTI_IMAGES} images allowed")
    if len(urls) >= MIN_MULTI_IMAGES:
        return urls, DEFAULT_MULTI_IMAGE_MODE
    if len(urls) == 1:
        return urls, None
    raise ValueError(f"need 1 or {MIN_MULTI_IMAGES}–{MAX_MULTI_IMAGES} images")
