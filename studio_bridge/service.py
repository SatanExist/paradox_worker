from __future__ import annotations

import os
from typing import Any, Literal

from dotenv import load_dotenv

from runpod_queue_watchdog import (
    get_status,
    heal_endpoint,
    run_with_zombie_retries,
    submit_job,
)
from studio_bridge.normalize import normalize_job_payload
from studio_bridge.product_multi_ux import resolve_image_sources, status_line
from studio_bridge.text2image import Text2ImageNotConfiguredError, generate_image_url
from studio_bridge.tiers import (
    DEFAULT_MULTI_IMAGE_MODE,
    DEFAULT_PRESET,
    MAX_MULTI_IMAGES,
    MIN_MULTI_IMAGES,
    MultiImageMode,
    TextureMode,
    TierName,
    build_runpod_input,
    get_tier,
)

load_dotenv()

JobMode = Literal["image", "text"]


def _api_key() -> str:
    key = os.getenv("RUNPOD_API_KEY", "").strip()
    if not key:
        raise ValueError("RUNPOD_API_KEY is not set")
    return key


def _resolve_source_urls(
    *,
    mode: JobMode,
    image_url: str | None,
    image_urls: list[str] | None,
    prompt: str | None,
    view_slots: dict[str, str | None] | None = None,
) -> tuple[list[str], str | None, MultiImageMode | None]:
    """Return (urls, text_prompt, suggested_multi_mode). Text → single generated URL."""
    if mode == "text":
        if image_urls or view_slots:
            raise ValueError("imageUrls/viewSlots is not supported for mode=text")
        if not prompt:
            raise ValueError("prompt is required for mode=text")
        source = generate_image_url(prompt)
        if not source.startswith("http"):
            raise RuntimeError(
                "Text→image must return a public https URL for RunPod worker. "
                "Set OPENAI_API_KEY (url response) or implement R2 upload for data URLs."
            )
        return [source], prompt, None

    urls, suggested = resolve_image_sources(
        image_url=image_url,
        image_urls=image_urls,
        view_slots=view_slots,
    )
    if len(urls) > 1 and len(urls) < MIN_MULTI_IMAGES:
        raise ValueError(f"imageUrls requires at least {MIN_MULTI_IMAGES} URLs")
    if len(urls) > MAX_MULTI_IMAGES:
        raise ValueError(f"imageUrls allows at most {MAX_MULTI_IMAGES} URLs")
    return urls, None, suggested


def create_job(
    *,
    mode: JobMode,
    tier: TierName = DEFAULT_PRESET,
    image_url: str | None = None,
    image_urls: list[str] | None = None,
    view_slots: dict[str, str | None] | None = None,
    prompt: str | None = None,
    seed: int = 1,
    heal: bool = True,
    multi_image_mode: MultiImageMode | None = None,
    soft_input: bool | None = None,
    soft_input_strength: float = 0.75,
    texture_mode: TextureMode | None = None,
) -> dict[str, Any]:
    tier_cfg = get_tier(tier)
    api_key = _api_key()

    urls, text_prompt, suggested_mode = _resolve_source_urls(
        mode=mode,
        image_url=image_url,
        image_urls=image_urls,
        prompt=prompt,
        view_slots=view_slots,
    )
    primary = urls[0]
    fusion = multi_image_mode or suggested_mode or DEFAULT_MULTI_IMAGE_MODE

    if heal:
        heal_endpoint(tier_cfg.endpoint_id, api_key, purge=False)

    job_input = build_runpod_input(
        tier_cfg,
        image_url=primary if len(urls) < MIN_MULTI_IMAGES else None,
        image_urls=urls if len(urls) >= MIN_MULTI_IMAGES else None,
        seed=seed,
        texture_mode=texture_mode,
        multi_image_mode=fusion,
        soft_input=soft_input,
        soft_input_strength=soft_input_strength,
    )
    job_id = submit_job(tier_cfg.endpoint_id, api_key, job_input)

    return {
        "jobId": job_id,
        "mode": mode,
        "tier": tier_cfg.name,
        "tierRequested": tier,
        "endpointId": tier_cfg.endpoint_id,
        "imageUrl": primary,
        "imageUrls": urls,
        "viewCount": len(urls),
        "statusLine": status_line(len(urls)),
        "multiImageMode": job_input.get("multi_image_mode"),
        "textureMode": job_input.get("texture_mode"),
        "qualityTier": job_input.get("quality_tier"),
        "prompt": text_prompt,
        "etaSecondsCold": tier_cfg.eta_cold_sec,
        "etaSecondsWarm": tier_cfg.eta_warm_sec,
        "status": "queued",
    }


def create_job_and_wait(
    *,
    mode: JobMode,
    tier: TierName = DEFAULT_PRESET,
    image_url: str | None = None,
    image_urls: list[str] | None = None,
    view_slots: dict[str, str | None] | None = None,
    prompt: str | None = None,
    seed: int = 1,
    multi_image_mode: MultiImageMode | None = None,
    soft_input: bool | None = None,
    soft_input_strength: float = 0.75,
    texture_mode: TextureMode | None = None,
) -> dict[str, Any]:
    tier_cfg = get_tier(tier)
    api_key = _api_key()

    try:
        urls, text_prompt, suggested_mode = _resolve_source_urls(
            mode=mode,
            image_url=image_url,
            image_urls=image_urls,
            prompt=prompt,
            view_slots=view_slots,
        )
    except Text2ImageNotConfiguredError:
        raise

    primary = urls[0]
    fusion = multi_image_mode or suggested_mode or DEFAULT_MULTI_IMAGE_MODE
    job_input = build_runpod_input(
        tier_cfg,
        image_url=primary if len(urls) < MIN_MULTI_IMAGES else None,
        image_urls=urls if len(urls) >= MIN_MULTI_IMAGES else None,
        seed=seed,
        texture_mode=texture_mode,
        multi_image_mode=fusion,
        soft_input=soft_input,
        soft_input_strength=soft_input_strength,
    )
    _endpoint, final = run_with_zombie_retries(
        tier_cfg.endpoint_id,
        api_key,
        job_input,
        heal=True,
    )
    normalized = normalize_job_payload(
        final,
        tier_cold_eta_sec=tier_cfg.eta_cold_sec,
        tier_warm_eta_sec=tier_cfg.eta_warm_sec,
    )
    normalized["mode"] = mode
    normalized["tier"] = tier_cfg.name
    normalized["tierRequested"] = tier
    normalized["textureMode"] = job_input.get("texture_mode")
    normalized["qualityTier"] = job_input.get("quality_tier")
    normalized["imageUrl"] = primary
    normalized["imageUrls"] = urls
    normalized["viewCount"] = len(urls)
    normalized["statusLine"] = status_line(len(urls))
    normalized["multiImageMode"] = job_input.get("multi_image_mode")
    normalized["prompt"] = text_prompt
    return normalized


def get_job(job_id: str, *, tier: TierName = DEFAULT_PRESET) -> dict[str, Any]:
    tier_cfg = get_tier(tier)
    payload = get_status(tier_cfg.endpoint_id, job_id, _api_key())
    return normalize_job_payload(
        payload,
        tier_cold_eta_sec=tier_cfg.eta_cold_sec,
        tier_warm_eta_sec=tier_cfg.eta_warm_sec,
    )
