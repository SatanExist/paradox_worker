from __future__ import annotations

from typing import Any, Literal

StudioStatus = Literal["queued", "running", "ready", "failed"]


def map_runpod_status(runpod_status: str | None) -> StudioStatus:
    if runpod_status == "IN_QUEUE":
        return "queued"
    if runpod_status == "IN_PROGRESS":
        return "running"
    if runpod_status == "COMPLETED":
        return "ready"
    return "failed"


def normalize_job_payload(
    runpod_payload: dict[str, Any],
    *,
    tier_cold_eta_sec: int,
    tier_warm_eta_sec: int,
) -> dict[str, Any]:
    output = runpod_payload.get("output") or {}
    billing = output.get("billing") if isinstance(output, dict) else {}
    handler_ms = billing.get("handler_ms") if isinstance(billing, dict) else {}
    model_load_ms = int((handler_ms or {}).get("model_load_ms") or 0)
    warm = model_load_ms == 0 and runpod_payload.get("status") == "COMPLETED"

    status = map_runpod_status(runpod_payload.get("status"))
    model_url = output.get("model_url") if isinstance(output, dict) else None

    result: dict[str, Any] = {
        "jobId": runpod_payload.get("id"),
        "status": status,
        "runpodStatus": runpod_payload.get("status"),
        "modelUrl": model_url if isinstance(model_url, str) else None,
        "delivery": output.get("delivery") if isinstance(output, dict) else None,
        "error": runpod_payload.get("error"),
        "etaSecondsCold": tier_cold_eta_sec,
        "etaSecondsWarm": tier_warm_eta_sec,
        "isWarm": warm,
        "handlerMs": handler_ms or None,
        "delayTimeMs": runpod_payload.get("delayTime"),
        "executionTimeMs": runpod_payload.get("executionTime"),
    }
    if status == "ready" and not result["modelUrl"]:
        result["status"] = "failed"
        result["error"] = result["error"] or "COMPLETED without model_url"
    return result
