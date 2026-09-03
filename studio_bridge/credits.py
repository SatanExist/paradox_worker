"""Studio credit quotes. Wallet lives in AI_MESH; this repo only quotes and refunds.

T2: draft / quality / cold as separate rows (not the TZ 5.0 98% fantasy).
FAL: user price >= 2.5x public list (live shelf = Meshy). Fail → refund signal (creditsRefunded).
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Literal

CREDIT_USD = 0.025  # $25 / 1000 credits
FAL_MARKUP = 2.5

TariffKind = Literal["t2", "fal", "hitem", "tripo", "rodin"]


@dataclass(frozen=True)
class CreditQuote:
    engine_id: str
    credits: int
    credits_cold_surcharge: int
    usd_user: float
    usd_cogs: float
    kind: TariffKind
    label: str

    def as_dict(self) -> dict:
        return {
            "engineId": self.engine_id,
            "credits": self.credits,
            "creditsColdSurcharge": self.credits_cold_surcharge,
            "usdUser": round(self.usd_user, 4),
            "usdCogs": round(self.usd_cogs, 4),
            "kind": self.kind,
            "label": self.label,
            "creditUsd": CREDIT_USD,
            "falMarkup": FAL_MARKUP if self.kind != "t2" else None,
        }


def credits_from_usd(usd: float) -> int:
    return max(1, int(ceil(usd / CREDIT_USD - 1e-12)))


def fal_user_credits(list_usd: float) -> int:
    return credits_from_usd(list_usd * FAL_MARKUP)


# Own GPU (warm COGS from our T2 timings). Cold is extra, not mixed into warm.
_T2_QUOTES: dict[str, CreditQuote] = {
    "hi3dgen": CreditQuote(
        engine_id="hi3dgen",
        credits=4,
        credits_cold_surcharge=8,
        usd_user=4 * CREDIT_USD,
        usd_cogs=0.02,
        kind="t2",
        label="Draft (Hi3DGen) warm",
    ),
    "trellis2": CreditQuote(
        engine_id="trellis2",
        credits=10,
        credits_cold_surcharge=12,
        usd_user=10 * CREDIT_USD,
        usd_cogs=0.08,
        kind="t2",
        label="Quality (TRELLIS.2) warm",
    ),
}

# FAL public list (playground 2026-08-27) × 2.5, rounded up to whole credits.
_FAL_LIST_USD: dict[str, float] = {
    "meshy": 0.80,
    "hunyuan": 0.225,
    "hunyuan_pro": 0.375,
    "trellis2_fal": 0.30,
}

_FAL_LABELS: dict[str, str] = {
    "meshy": "Meshy 6 (FAL)",
    "hunyuan": "Hunyuan Rapid (FAL)",
    "hunyuan_pro": "Hunyuan Pro (FAL)",
    "trellis2_fal": "TRELLIS.2 backup (FAL, not vitrine)",
}


def _fal_quote(engine_id: str) -> CreditQuote:
    list_usd = _FAL_LIST_USD[engine_id]
    credits = fal_user_credits(list_usd)
    return CreditQuote(
        engine_id=engine_id,
        credits=credits,
        credits_cold_surcharge=0,
        usd_user=credits * CREDIT_USD,
        usd_cogs=list_usd,
        kind="fal",
        label=_FAL_LABELS[engine_id],
    )


def t2_quote_for_preset(preset: str) -> CreditQuote:
    """low → draft-priced T2; medium/high/realistic → quality T2."""
    key = (preset or "medium").strip().lower()
    if key in {"low", "preview", "hi3dgen", "draft"}:
        base = _T2_QUOTES["hi3dgen"]
        return CreditQuote(
            engine_id="trellis2",
            credits=base.credits,
            credits_cold_surcharge=base.credits_cold_surcharge,
            usd_user=base.usd_user,
            usd_cogs=0.03,
            kind="t2",
            label="Draft (T2 Low) warm",
        )
    high = key in {"high", "ultra", "realistic"}
    credits = 16 if high else _T2_QUOTES["trellis2"].credits
    label = "High/Realistic (T2) warm" if high else _T2_QUOTES["trellis2"].label
    cogs = 0.17 if high else 0.08
    return CreditQuote(
        engine_id="trellis2",
        credits=credits,
        credits_cold_surcharge=12,
        usd_user=credits * CREDIT_USD,
        usd_cogs=cogs,
        kind="t2",
        label=label,
    )


def quote_rodin(quality_tier: str = "medium") -> CreditQuote:
    from studio_bridge.rodin_client import resolve_rodin_quality

    tier = resolve_rodin_quality("rodin", quality_tier)
    return _direct_quote(
        "rodin",
        tier.list_usd,
        "rodin",
        f"Rodin 2.5 {tier.label} (direct)",
    )


def quote_engine(
    engine_id: str,
    *,
    tier: str = "medium",
    rodin_quality: str | None = None,
) -> CreditQuote:
    eid = (engine_id or "trellis2").strip().lower()
    if eid == "trellis2":
        return t2_quote_for_preset(tier)
    if eid == "hi3dgen":
        return _T2_QUOTES["hi3dgen"]
    from studio_bridge.hitem_client import HITEM_PRESETS
    from studio_bridge.tripo_client import TRIPO_PRESETS
    from studio_bridge.rodin_client import is_rodin_engine

    hitem = HITEM_PRESETS.get(eid)
    if hitem is not None:
        return _direct_quote(eid, hitem.list_usd, "hitem", f"{hitem.label} (direct)")
    tripo = TRIPO_PRESETS.get(eid)
    if tripo is not None:
        return _direct_quote(eid, tripo.list_usd, "tripo", f"{tripo.label} (direct)")
    if is_rodin_engine(eid):
        from studio_bridge.rodin_client import DEFAULT_RODIN_QUALITY

        q = rodin_quality or ("ultra" if eid == "rodin_extreme" else DEFAULT_RODIN_QUALITY)
        return quote_rodin(q)
    if eid in _FAL_LIST_USD:
        return _fal_quote(eid)
    raise ValueError(f"unknown engine {engine_id!r}")


def _direct_quote(engine_id: str, list_usd: float, kind: TariffKind, label: str) -> CreditQuote:
    credits = fal_user_credits(list_usd)
    return CreditQuote(
        engine_id=engine_id,
        credits=credits,
        credits_cold_surcharge=0,
        usd_user=credits * CREDIT_USD,
        usd_cogs=list_usd,
        kind=kind,
        label=label,
    )


def credit_catalog() -> dict:
    rows = [
        t2_quote_for_preset("low").as_dict(),
        t2_quote_for_preset("medium").as_dict(),
        t2_quote_for_preset("high").as_dict(),
        _T2_QUOTES["hi3dgen"].as_dict(),
    ]
    for eid in ("meshy",):
        rows.append(_fal_quote(eid).as_dict())
    from studio_bridge.hitem_client import HITEM_PRESETS
    from studio_bridge.tripo_client import TRIPO_PRESETS
    from studio_bridge.rodin_client import RODIN_QUALITY_TIERS

    for eid in (*HITEM_PRESETS, *TRIPO_PRESETS):
        rows.append(quote_engine(eid).as_dict())
    for qid in RODIN_QUALITY_TIERS:
        row = quote_rodin(qid).as_dict()
        row["rodinQualityTier"] = qid
        rows.append(row)
    return {
        "creditUsd": CREDIT_USD,
        "falMarkup": FAL_MARKUP,
        "unlimitedOff": True,
        "refundOnFail": True,
        "tariffs": rows,
    }


def refund_payload(quoted: CreditQuote, *, error: str) -> dict:
    return {
        "creditsCharged": 0,
        "creditsQuoted": quoted.credits,
        "creditsRefunded": True,
        "refundReason": "job_failed",
        "error": error,
    }
