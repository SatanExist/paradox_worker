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
from studio_bridge.text2image import Text2ImageNotConfiguredError, generate_image_url
from studio_bridge.tiers import TierName, build_runpod_input, get_tier

load_dotenv()

JobMode = Literal["image", "text"]


def _api_key() -> str:
    key = os.getenv("RUNPOD_API_KEY", "").strip()
    if not key:
        raise ValueError("RUNPOD_API_KEY is not set")
    return key


def create_job(
    *,
    mode: JobMode,
    tier: TierName = "preview",
    image_url: str | None = None,
    prompt: str | None = None,
    seed: int = 1,
    heal: bool = True,
) -> dict[str, Any]:
    tier_cfg = get_tier(tier)
    api_key = _api_key()

    source_image_url = image_url
    text_prompt = prompt

    if mode == "text":
        if not prompt:
            raise ValueError("prompt is required for mode=text")
        source_image_url = generate_image_url(prompt)
        if not source_image_url.startswith("http"):
            raise RuntimeError(
                "Text→image must return a public https URL for RunPod worker. "
                "Set OPENAI_API_KEY (url response) or implement R2 upload for data URLs."
            )
    elif not source_image_url:
        raise ValueError("imageUrl is required for mode=image")

    if heal:
        heal_endpoint(tier_cfg.endpoint_id, api_key, purge=False)

    job_input = build_runpod_input(tier_cfg, image_url=source_image_url, seed=seed)
    job_id = submit_job(tier_cfg.endpoint_id, api_key, job_input)

    return {
        "jobId": job_id,
        "mode": mode,
        "tier": tier,
        "endpointId": tier_cfg.endpoint_id,
        "imageUrl": source_image_url,
        "prompt": text_prompt,
        "etaSecondsCold": tier_cfg.eta_cold_sec,
        "etaSecondsWarm": tier_cfg.eta_warm_sec,
        "status": "queued",
    }


def create_job_and_wait(
    *,
    mode: JobMode,
    tier: TierName = "preview",
    image_url: str | None = None,
    prompt: str | None = None,
    seed: int = 1,
) -> dict[str, Any]:
    tier_cfg = get_tier(tier)
    api_key = _api_key()

    source_image_url = image_url
    if mode == "text":
        if not prompt:
            raise ValueError("prompt is required for mode=text")
        try:
            source_image_url = generate_image_url(prompt)
        except Text2ImageNotConfiguredError:
            raise
        if not source_image_url.startswith("http"):
            raise RuntimeError("Text→image must yield public https URL for RunPod worker.")

    if not source_image_url:
        raise ValueError("imageUrl is required for mode=image")

    job_input = build_runpod_input(tier_cfg, image_url=source_image_url, seed=seed)
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
    normalized["tier"] = tier
    normalized["imageUrl"] = source_image_url
    normalized["prompt"] = prompt
    return normalized


def get_job(job_id: str, *, tier: TierName = "preview") -> dict[str, Any]:
    tier_cfg = get_tier(tier)
    payload = get_status(tier_cfg.endpoint_id, job_id, _api_key())
    return normalize_job_payload(
        payload,
        tier_cold_eta_sec=tier_cfg.eta_cold_sec,
        tier_warm_eta_sec=tier_cfg.eta_warm_sec,
    )
