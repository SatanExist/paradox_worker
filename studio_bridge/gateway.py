"""Studio job gateway: RunPod T2/Hi3DGen + FAL Meshy + Hitem/Tripo/Rodin direct.

FAL_KEY, HITEM_CLIENT_*, TRIPO_API_KEY, RODIN_API_KEY/HYPER3D_API_KEY, RUNPOD_API_KEY
stay on the server. Job ids:

  <runpod-uuid>              TRELLIS.2 (backward compatible)
  rp:hi3dgen:<runpod-uuid>   Hi3DGen
  fal:<engine>:<request_id>  FAL queue (live shelf = Meshy only)
  hitem:<engine>:<task_id>   Hitem Open Platform
  tripo:<engine>:<task_id>   Tripo Developers
  rodin:<engine>:<uuid>|<subscription_key>  Rodin / Hyper3D
"""

from __future__ import annotations

import os
from typing import Any

from studio_bridge.credits import quote_engine, refund_payload
from studio_bridge.engines import (
    DEFAULT_ENGINE,
    FAL_SHELF_IDS,
    build_fal_arguments,
    extract_glb_url,
    get_engine,
    is_hunyuan_engine,
    on_fal_shelf,
)
from studio_bridge.fal_client import (
    FalHttpError,
    FalNotConfiguredError,
    get_result,
    get_status,
    submit,
)
from studio_bridge.geo import HunyuanGeoBlocked, assert_hunyuan_allowed
from studio_bridge.hitem_client import (
    HitemHttpError,
    HitemNotConfiguredError,
    map_hitem_state,
    query_task as query_hitem_task,
    submit_image_to_3d as submit_hitem,
)
from studio_bridge.rodin_client import (
    DEFAULT_RODIN_QUALITY,
    RODIN_QUALITY_TIERS,
    RodinHttpError,
    RodinNotConfiguredError,
    download_urls as download_rodin,
    map_rodin_jobs,
    pick_glb as pick_rodin_glb,
    query_status as query_rodin_status,
    submit_image_to_3d as submit_rodin,
)
from studio_bridge.tripo_client import (
    TripoHttpError,
    TripoNotConfiguredError,
    map_tripo_status,
    pick_glb as pick_tripo_glb,
    query_task as query_tripo_task,
    submit_image_to_3d as submit_tripo,
)
from studio_bridge.normalize import map_runpod_status, normalize_job_payload
from studio_bridge.product_multi_ux import status_line
from studio_bridge.service import (
    JobMode,
    create_job as create_t2_job,
    get_job as get_t2_job,
    resolve_source_urls,
)
from runpod_queue_watchdog import get_status as runpod_status, submit_job
from studio_bridge.tiers import DEFAULT_PRESET, TextureMode, TierName

HI3DGEN_PREFIX = "rp:hi3dgen:"
FAL_PREFIX = "fal:"
HITEM_PREFIX = "hitem:"
TRIPO_PREFIX = "tripo:"
RODIN_PREFIX = "rodin:"


class EngineNotConfiguredError(RuntimeError):
    pass


def encode_fal_job_id(engine_id: str, request_id: str) -> str:
    return f"{FAL_PREFIX}{engine_id}:{request_id}"


def parse_fal_job_id(job_id: str) -> tuple[str, str] | None:
    raw = (job_id or "").strip()
    if not raw.startswith(FAL_PREFIX):
        return None
    rest = raw[len(FAL_PREFIX) :]
    engine_id, sep, request_id = rest.partition(":")
    if not sep or not engine_id or not request_id:
        raise ValueError("malformed FAL job id")
    return engine_id, request_id


def encode_hitem_job_id(engine_id: str, task_id: str) -> str:
    return f"{HITEM_PREFIX}{engine_id}:{task_id}"


def parse_hitem_job_id(job_id: str) -> tuple[str, str] | None:
    raw = (job_id or "").strip()
    if not raw.startswith(HITEM_PREFIX):
        return None
    rest = raw[len(HITEM_PREFIX) :]
    engine_id, sep, task_id = rest.partition(":")
    if not sep or not engine_id or not task_id:
        raise ValueError("malformed Hitem job id")
    return engine_id, task_id


def encode_tripo_job_id(engine_id: str, task_id: str) -> str:
    return f"{TRIPO_PREFIX}{engine_id}:{task_id}"


def parse_tripo_job_id(job_id: str) -> tuple[str, str] | None:
    raw = (job_id or "").strip()
    if not raw.startswith(TRIPO_PREFIX):
        return None
    rest = raw[len(TRIPO_PREFIX) :]
    engine_id, sep, task_id = rest.partition(":")
    if not sep or not engine_id or not task_id:
        raise ValueError("malformed Tripo job id")
    return engine_id, task_id


def encode_rodin_job_id(engine_id: str, task_uuid: str, subscription_key: str) -> str:
    return f"{RODIN_PREFIX}{engine_id}:{task_uuid}|{subscription_key}"


def parse_rodin_job_id(job_id: str) -> tuple[str, str, str] | None:
    raw = (job_id or "").strip()
    if not raw.startswith(RODIN_PREFIX):
        return None
    rest = raw[len(RODIN_PREFIX) :]
    engine_id, sep, tail = rest.partition(":")
    if not sep or not engine_id or not tail:
        raise ValueError("malformed Rodin job id")
    task_uuid, bar, subscription_key = tail.partition("|")
    if not bar or not task_uuid or not subscription_key:
        raise ValueError("malformed Rodin job id")
    return engine_id, task_uuid, subscription_key


def encode_hi3dgen_job_id(runpod_id: str) -> str:
    return f"{HI3DGEN_PREFIX}{runpod_id}"


def parse_hi3dgen_job_id(job_id: str) -> str | None:
    raw = (job_id or "").strip()
    if not raw.startswith(HI3DGEN_PREFIX):
        return None
    rid = raw[len(HI3DGEN_PREFIX) :]
    if not rid:
        raise ValueError("malformed Hi3DGen job id")
    return rid


def _hi3dgen_endpoint() -> str:
    endpoint = os.getenv("RUNPOD_ENDPOINT_ID_HI3DGEN", "").strip()
    if not endpoint:
        raise EngineNotConfiguredError("RUNPOD_ENDPOINT_ID_HI3DGEN is not set")
    return endpoint


def _runpod_key() -> str:
    key = os.getenv("RUNPOD_API_KEY", "").strip()
    if not key:
        raise ValueError("RUNPOD_API_KEY is not set")
    return key


def _credit_fields(
    engine_id: str,
    *,
    tier: str,
    rodin_quality: str | None = None,
    charged: int | None = None,
) -> dict[str, Any]:
    quote = quote_engine(engine_id, tier=tier, rodin_quality=rodin_quality)
    return {
        "engine": engine_id,
        "creditsQuoted": quote.credits,
        "creditsColdSurcharge": quote.credits_cold_surcharge,
        "creditsCharged": quote.credits if charged is None else charged,
        "creditsRefunded": False,
        "creditUsd": quote.usd_user / quote.credits if quote.credits else None,
    }


def create_studio_job(
    *,
    mode: JobMode = "image",
    engine: str = DEFAULT_ENGINE,
    tier: TierName = DEFAULT_PRESET,
    image_url: str | None = None,
    image_urls: list[str] | None = None,
    view_slots: dict[str, str | None] | None = None,
    prompt: str | None = None,
    seed: int = 1,
    multi_image_mode=None,
    soft_input: bool | None = None,
    soft_input_strength: float = 0.75,
    texture_mode: TextureMode | None = None,
    preprocess_image: bool | None = None,
    country: str | None = None,
    rodin_quality_tier: str | None = None,
) -> dict[str, Any]:
    spec = get_engine(engine)
    if spec.provider == "fal" and not on_fal_shelf(spec.id):
        raise EngineNotConfiguredError(
            f"{spec.id} is off the FAL shelf ({sorted(FAL_SHELF_IDS)}). "
            "Use the vendor API; Hunyuan waits on Tencent."
        )
    if is_hunyuan_engine(spec.id):
        assert_hunyuan_allowed(country)

    if spec.id == "trellis2":
        payload = create_t2_job(
            mode=mode,
            tier=tier,
            image_url=image_url,
            image_urls=image_urls,
            view_slots=view_slots,
            prompt=prompt,
            seed=seed,
            multi_image_mode=multi_image_mode,
            soft_input=soft_input,
            soft_input_strength=soft_input_strength,
            texture_mode=texture_mode,
            preprocess_image=preprocess_image,
        )
        payload.update(_credit_fields("trellis2", tier=str(payload.get("tier") or tier)))
        payload["engine"] = "trellis2"
        payload["provider"] = "runpod"
        return payload

    urls, text_prompt, _suggested = resolve_source_urls(
        mode=mode,
        image_url=image_url,
        image_urls=image_urls,
        prompt=prompt,
        view_slots=view_slots,
    )
    primary = urls[0]
    quote_bits = _credit_fields(spec.id, tier=str(tier))

    if spec.id == "hi3dgen":
        job_id = submit_job(
            _hi3dgen_endpoint(),
            _runpod_key(),
            {
                "image_url": primary,
                "seed": seed,
                "ss_steps": 50,
                "slat_steps": 6,
                "normal_model": "yoso",
            },
        )
        return {
            "jobId": encode_hi3dgen_job_id(job_id),
            "mode": mode,
            "engine": spec.id,
            "provider": "runpod",
            "tier": "draft",
            "imageUrl": primary,
            "imageUrls": urls,
            "viewCount": len(urls),
            "statusLine": status_line(len(urls)),
            "prompt": text_prompt,
            "etaSecondsCold": 120,
            "etaSecondsWarm": spec.eta_sec,
            "status": "queued",
            **quote_bits,
        }

    if spec.provider == "hitem":
        queued = submit_hitem(
            spec.id,
            image_urls=urls,
            view_slots=view_slots,
        )
        task_id = str(queued.get("task_id") or "").strip()
        if not task_id:
            raise HitemHttpError(502, f"Hitem submit missing task_id: {queued}")
        return {
            "jobId": encode_hitem_job_id(spec.id, task_id),
            "hitemTaskId": task_id,
            "hitemModel": queued.get("model"),
            "hitemResolution": queued.get("resolution"),
            "mode": mode,
            "engine": spec.id,
            "provider": "hitem",
            "vendor": spec.vendor,
            "imageUrl": primary,
            "imageUrls": urls,
            "viewCount": len(urls),
            "statusLine": status_line(len(urls)),
            "prompt": text_prompt,
            "etaSecondsCold": spec.eta_sec,
            "etaSecondsWarm": spec.eta_sec,
            "status": "queued",
            **quote_bits,
        }

    if spec.provider == "tripo":
        queued = submit_tripo(spec.id, image_urls=urls, seed=seed)
        task_id = str(queued.get("task_id") or "").strip()
        if not task_id:
            raise TripoHttpError(502, f"Tripo submit missing task_id: {queued}")
        return {
            "jobId": encode_tripo_job_id(spec.id, task_id),
            "tripoTaskId": task_id,
            "tripoModel": queued.get("model"),
            "mode": mode,
            "engine": spec.id,
            "provider": "tripo",
            "vendor": spec.vendor,
            "imageUrl": primary,
            "imageUrls": urls,
            "viewCount": len(urls),
            "statusLine": status_line(len(urls)),
            "prompt": text_prompt,
            "etaSecondsCold": spec.eta_sec,
            "etaSecondsWarm": spec.eta_sec,
            "status": "queued",
            **quote_bits,
        }

    if spec.provider == "rodin":
        effective_quality = rodin_quality_tier or (
            "ultra" if spec.id == "rodin_extreme" else DEFAULT_RODIN_QUALITY
        )
        queued = submit_rodin(
            spec.id,
            image_urls=urls,
            view_slots=view_slots,
            quality_tier=effective_quality,
        )
        task_uuid = str(queued.get("uuid") or "").strip()
        subscription_key = str(queued.get("subscription_key") or "").strip()
        if not task_uuid or not subscription_key:
            raise RodinHttpError(502, f"Rodin submit missing uuid/key: {queued}")
        quality_id = str(queued.get("qualityTier") or effective_quality)
        quality_row = RODIN_QUALITY_TIERS.get(quality_id)
        quote_bits = _credit_fields(
            "rodin",
            tier=str(tier),
            rodin_quality=quality_id,
        )
        return {
            "jobId": encode_rodin_job_id("rodin", task_uuid, subscription_key),
            "rodinUuid": task_uuid,
            "rodinTier": queued.get("tier"),
            "rodinQualityTier": quality_id,
            "mode": mode,
            "engine": "rodin",
            "provider": "rodin",
            "vendor": spec.vendor,
            "imageUrl": primary,
            "imageUrls": urls,
            "viewCount": len(urls),
            "statusLine": status_line(len(urls)),
            "prompt": text_prompt,
            "etaSecondsCold": quality_row.eta_sec if quality_row else spec.eta_sec,
            "etaSecondsWarm": quality_row.eta_sec if quality_row else spec.eta_sec,
            "status": "queued",
            **quote_bits,
        }

    arguments = build_fal_arguments(
        spec.id,
        image_urls=urls,
        view_slots=view_slots,
        seed=seed,
    )
    queued = submit(spec.fal_model or "", arguments)
    request_id = str(queued.get("request_id") or queued.get("requestId") or "").strip()
    if not request_id:
        raise FalHttpError(502, f"FAL submit missing request_id: {queued}")
    return {
        "jobId": encode_fal_job_id(spec.id, request_id),
        "falRequestId": request_id,
        "falModel": spec.fal_model,
        "mode": mode,
        "engine": spec.id,
        "provider": "fal",
        "vendor": spec.vendor,
        "imageUrl": primary,
        "imageUrls": urls,
        "viewCount": len(urls),
        "statusLine": status_line(len(urls)),
        "prompt": text_prompt,
        "etaSecondsCold": spec.eta_sec,
        "etaSecondsWarm": spec.eta_sec,
        "status": "queued",
        **quote_bits,
    }


def _map_fal_status(raw: str | None) -> str:
    if raw in {"IN_QUEUE", "IN_QUEUE_PRIORITY"}:
        return "queued"
    if raw == "IN_PROGRESS":
        return "running"
    if raw == "COMPLETED":
        return "ready"
    return "failed"


def get_studio_job(
    job_id: str,
    *,
    tier: TierName = DEFAULT_PRESET,
    country: str | None = None,
) -> dict[str, Any]:
    fal_parsed = parse_fal_job_id(job_id)
    if fal_parsed:
        return _get_fal_job(job_id, fal_parsed[0], fal_parsed[1], country=country)

    hitem_parsed = parse_hitem_job_id(job_id)
    if hitem_parsed:
        return _get_hitem_job(job_id, hitem_parsed[0], hitem_parsed[1])

    tripo_parsed = parse_tripo_job_id(job_id)
    if tripo_parsed:
        return _get_tripo_job(job_id, tripo_parsed[0], tripo_parsed[1])

    rodin_parsed = parse_rodin_job_id(job_id)
    if rodin_parsed:
        return _get_rodin_job(job_id, rodin_parsed[0], rodin_parsed[1], rodin_parsed[2])

    hi3d = parse_hi3dgen_job_id(job_id)
    if hi3d:
        return _get_hi3dgen_job(job_id, hi3d)

    payload = get_t2_job(job_id, tier=tier)
    payload.update(_credit_fields("trellis2", tier=str(tier)))
    if payload.get("status") == "failed":
        payload.update(
            refund_payload(
                quote_engine("trellis2", tier=str(tier)),
                error=str(payload.get("error") or "job_failed"),
            )
        )
    elif payload.get("status") == "ready" and payload.get("isWarm") is False:
        quote = quote_engine("trellis2", tier=str(tier))
        payload["creditsCharged"] = quote.credits + quote.credits_cold_surcharge
        payload["creditsColdApplied"] = True
    payload["engine"] = "trellis2"
    payload["provider"] = "runpod"
    payload["jobId"] = job_id
    return payload


def _get_hi3dgen_job(job_id: str, runpod_id: str) -> dict[str, Any]:
    quote = quote_engine("hi3dgen")
    raw = runpod_status(_hi3dgen_endpoint(), runpod_id, _runpod_key())
    mapped = map_runpod_status(raw.get("status"))
    output = raw.get("output") if isinstance(raw.get("output"), dict) else {}
    model_url = output.get("model_url") if isinstance(output, dict) else None
    error = raw.get("error")
    if mapped == "ready" and not model_url:
        mapped = "failed"
        error = error or "COMPLETED without model_url"
    payload: dict[str, Any] = {
        "jobId": job_id,
        "engine": "hi3dgen",
        "provider": "runpod",
        "status": mapped,
        "runpodStatus": raw.get("status"),
        "modelUrl": model_url if isinstance(model_url, str) else None,
        "error": error,
        "etaSecondsWarm": 30,
        "etaSecondsCold": 120,
        **_credit_fields("hi3dgen", tier="draft"),
    }
    if mapped == "failed":
        payload.update(refund_payload(quote, error=str(error or "job_failed")))
    return payload


def _get_fal_job(
    job_id: str,
    engine_id: str,
    request_id: str,
    *,
    country: str | None,
) -> dict[str, Any]:
    spec = get_engine(engine_id)
    if spec.geo_gated:
        assert_hunyuan_allowed(country)
    quote = quote_engine(spec.id)
    status_body = get_status(spec.fal_model or "", request_id)
    raw_status = str(status_body.get("status") or "")
    mapped = _map_fal_status(raw_status)
    payload: dict[str, Any] = {
        "jobId": job_id,
        "engine": spec.id,
        "provider": "fal",
        "vendor": spec.vendor,
        "falModel": spec.fal_model,
        "falRequestId": request_id,
        "status": mapped,
        "falStatus": raw_status,
        "modelUrl": None,
        "posterUrl": None,
        "error": status_body.get("error"),
        "etaSecondsWarm": spec.eta_sec,
        "etaSecondsCold": spec.eta_sec,
        **_credit_fields(spec.id, tier="medium"),
    }
    if mapped != "ready":
        if mapped == "failed":
            nested = status_body.get("payload")
            detail = nested.get("detail") if isinstance(nested, dict) else None
            err = str(status_body.get("error") or detail or raw_status or "job_failed")
            payload.update(refund_payload(quote, error=err))
        return payload

    result = get_result(spec.fal_model or "", request_id)
    glb, poster, size = extract_glb_url(result)
    payload["posterUrl"] = poster
    payload["modelBytes"] = size
    if not glb:
        payload["status"] = "failed"
        payload.update(
            refund_payload(quote, error="FAL completed without a GLB (Studio needs GLB)")
        )
        return payload
    payload["modelUrl"] = glb
    payload["delivery"] = "fal"
    return payload


def _get_hitem_job(job_id: str, engine_id: str, task_id: str) -> dict[str, Any]:
    spec = get_engine(engine_id)
    quote = quote_engine(spec.id)
    data = query_hitem_task(task_id)
    raw_state = str(data.get("state") or "")
    mapped = map_hitem_state(raw_state)
    glb = data.get("url") if isinstance(data.get("url"), str) else None
    poster = data.get("cover_url") if isinstance(data.get("cover_url"), str) else None
    payload: dict[str, Any] = {
        "jobId": job_id,
        "engine": spec.id,
        "provider": "hitem",
        "vendor": spec.vendor,
        "hitemTaskId": task_id,
        "status": mapped,
        "hitemState": raw_state,
        "modelUrl": glb if mapped == "ready" else None,
        "posterUrl": poster,
        "error": None if mapped != "failed" else (data.get("msg") or raw_state or "job_failed"),
        "etaSecondsWarm": spec.eta_sec,
        "etaSecondsCold": spec.eta_sec,
        **_credit_fields(spec.id, tier="medium"),
    }
    if mapped == "ready" and (not glb or not str(glb).lower().endswith(".glb")):
        payload["status"] = "failed"
        payload.update(
            refund_payload(quote, error="Hitem completed without a GLB (Studio needs GLB)")
        )
        return payload
    if mapped == "ready":
        payload["delivery"] = "hitem"
    if mapped == "failed":
        payload.update(refund_payload(quote, error=str(payload.get("error") or "job_failed")))
    return payload


def _get_tripo_job(job_id: str, engine_id: str, task_id: str) -> dict[str, Any]:
    spec = get_engine(engine_id)
    quote = quote_engine(spec.id)
    data = query_tripo_task(task_id)
    raw_state = str(data.get("status") or "")
    mapped = map_tripo_status(raw_state)
    glb, poster = pick_tripo_glb(data)
    err = data.get("error_message") or data.get("message")
    payload: dict[str, Any] = {
        "jobId": job_id,
        "engine": spec.id,
        "provider": "tripo",
        "vendor": spec.vendor,
        "tripoTaskId": task_id,
        "status": mapped,
        "tripoStatus": raw_state,
        "modelUrl": glb if mapped == "ready" else None,
        "posterUrl": poster,
        "error": None if mapped != "failed" else (err or raw_state or "job_failed"),
        "etaSecondsWarm": spec.eta_sec,
        "etaSecondsCold": spec.eta_sec,
        **_credit_fields(spec.id, tier="medium"),
    }
    if mapped == "ready" and (not glb or not str(glb).lower().endswith(".glb")):
        payload["status"] = "failed"
        payload.update(
            refund_payload(quote, error="Tripo completed without a GLB (Studio needs GLB)")
        )
        return payload
    if mapped == "ready":
        payload["delivery"] = "tripo"
    if mapped == "failed":
        payload.update(refund_payload(quote, error=str(payload.get("error") or "job_failed")))
    return payload


def _get_rodin_job(
    job_id: str, engine_id: str, task_uuid: str, subscription_key: str
) -> dict[str, Any]:
    spec = get_engine(engine_id)
    quote = quote_engine(spec.id)
    status_body = query_rodin_status(subscription_key)
    mapped = map_rodin_jobs(status_body)
    payload: dict[str, Any] = {
        "jobId": job_id,
        "engine": spec.id,
        "provider": "rodin",
        "vendor": spec.vendor,
        "rodinUuid": task_uuid,
        "status": mapped,
        "modelUrl": None,
        "posterUrl": None,
        "error": None if mapped != "failed" else "job_failed",
        "etaSecondsWarm": spec.eta_sec,
        "etaSecondsCold": spec.eta_sec,
        **_credit_fields(spec.id, tier="medium"),
    }
    if mapped != "ready":
        if mapped == "failed":
            payload.update(refund_payload(quote, error="job_failed"))
        return payload
    glb = pick_rodin_glb(download_rodin(task_uuid))
    if not glb or not str(glb).lower().endswith(".glb"):
        payload["status"] = "failed"
        payload.update(
            refund_payload(quote, error="Rodin completed without a GLB (Studio needs GLB)")
        )
        return payload
    payload["modelUrl"] = glb
    payload["delivery"] = "rodin"
    return payload


# Re-export for tests
__all__ = [
    "EngineNotConfiguredError",
    "FalNotConfiguredError",
    "HitemHttpError",
    "HitemNotConfiguredError",
    "HunyuanGeoBlocked",
    "RodinHttpError",
    "RodinNotConfiguredError",
    "TripoHttpError",
    "TripoNotConfiguredError",
    "create_studio_job",
    "encode_fal_job_id",
    "encode_hitem_job_id",
    "encode_rodin_job_id",
    "encode_tripo_job_id",
    "get_studio_job",
    "parse_fal_job_id",
    "parse_hitem_job_id",
    "parse_rodin_job_id",
    "parse_tripo_job_id",
]
