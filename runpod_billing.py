"""
Estimate RunPod Serverless job cost from API responses.

RunPod does not expose per-request USD in GET /status. This module combines:
  - delayTime + executionTime from https://api.runpod.ai/v2/{endpoint}/status/{job_id}
  - gpu_type from worker output (or endpoint GPU list fallback)
  - idleTimeout from https://rest.runpod.io/v1/endpoints/{endpoint_id}

For accounting reconciliation use GET https://rest.runpod.io/v1/billing/endpoints
(hourly buckets, not per job).
"""

from __future__ import annotations

import math
import os
from typing import Any, Mapping, Optional
from urllib.parse import unquote, urlparse, parse_qs

import requests

REST_BASE = "https://rest.runpod.io/v1"

# Serverless flex worker rates by GPU pool (USD per second).
# Source: https://docs.runpod.io/serverless/endpoints/endpoint-configurations
POOL_RATE_USD_PER_SEC: dict[str, float] = {
    "AMPERE_16": 0.00016,
    "AMPERE_24": 0.00019,
    "ADA_24": 0.00031,
    "AMPERE_48": 0.00034,
    "ADA_48_PRO": 0.00053,
    "AMPERE_80": 0.00076,
    "ADA_80_PRO": 0.00116,
    "ADA_96_PRO": 0.00111,
    "HOPPER_141": 0.00155,
    "BLACKWELL_180": 0.00240,
}

# Map RunPod gpuTypeId strings to billing pool.
GPU_TYPE_TO_POOL: dict[str, str] = {
    "NVIDIA RTX A4000": "AMPERE_16",
    "NVIDIA RTX A4500": "AMPERE_16",
    "NVIDIA RTX 4000 Ada Generation": "AMPERE_16",
    "NVIDIA RTX 4000 SFF Ada Generation": "AMPERE_16",
    "NVIDIA RTX 2000 Ada Generation": "AMPERE_16",
    "NVIDIA GeForce RTX 4000": "AMPERE_16",
    "NVIDIA L4": "AMPERE_24",
    "NVIDIA RTX A5000": "AMPERE_24",
    "NVIDIA GeForce RTX 3090": "AMPERE_24",
    "NVIDIA GeForce RTX 3090 Ti": "AMPERE_24",
    "NVIDIA GeForce RTX 4090": "ADA_24",
    "NVIDIA RTX A6000": "AMPERE_48",
    "NVIDIA A40": "AMPERE_48",
    "NVIDIA L40": "ADA_48_PRO",
    "NVIDIA L40S": "ADA_48_PRO",
    "NVIDIA RTX 6000 Ada Generation": "ADA_48_PRO",
    "NVIDIA A100-SXM4-80GB": "AMPERE_80",
    "NVIDIA A100 80GB PCIe": "AMPERE_80",
    "NVIDIA H100 80GB HBM3": "ADA_80_PRO",
    "NVIDIA H100 PCIe": "ADA_80_PRO",
    "NVIDIA H100 NVL": "ADA_80_PRO",
    "NVIDIA H200": "HOPPER_141",
    "NVIDIA H200 NVL": "HOPPER_141",
    "NVIDIA RTX PRO 6000 Blackwell Server Edition": "ADA_96_PRO",
    "NVIDIA B200": "BLACKWELL_180",
    "NVIDIA GeForce RTX 5090": "BLACKWELL_180",
}

DEFAULT_IDLE_TIMEOUT_SEC = 5
DEFAULT_POOL = "AMPERE_24"


def parse_gpu_type_from_runpod_env(environ: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Read exact GPU model from RunPod worker webhook env vars."""
    env = environ or os.environ
    for key in (
        "RUNPOD_WEBHOOK_POST_OUTPUT",
        "RUNPOD_WEBHOOK_GET_JOB",
        "RUNPOD_WEBHOOK_PING",
        "RUNPOD_WEBHOOK_POST_STREAM",
    ):
        url = env.get(key, "")
        if not url:
            continue
        query = parse_qs(urlparse(url).query)
        gpu_values = query.get("gpu")
        if gpu_values:
            return unquote(gpu_values[0])
    return None


def get_runpod_gpu_info(environ: Optional[Mapping[str, str]] = None) -> dict[str, Optional[str]]:
    env = environ or os.environ
    return {
        "gpu_pool": env.get("RUNPOD_GPU_SIZE"),
        "gpu_type": parse_gpu_type_from_runpod_env(env),
        "datacenter": env.get("RUNPOD_DC_ID"),
        "worker_id": env.get("RUNPOD_POD_ID"),
    }


def pool_for_gpu_type(gpu_type: str) -> Optional[str]:
    return GPU_TYPE_TO_POOL.get(gpu_type)


def rate_usd_per_sec(
    *,
    gpu_type: Optional[str] = None,
    gpu_pool: Optional[str] = None,
    endpoint_gpu_types: Optional[list[str]] = None,
) -> tuple[float, str]:
    """
    Return (rate_usd_per_sec, source_label).

    Uses exact GPU type when known, else pool, else highest configured endpoint tier.
    """
    if gpu_type:
        pool = pool_for_gpu_type(gpu_type)
        if pool:
            return POOL_RATE_USD_PER_SEC[pool], f"gpu_type:{gpu_type}"

    if gpu_pool and gpu_pool in POOL_RATE_USD_PER_SEC:
        return POOL_RATE_USD_PER_SEC[gpu_pool], f"gpu_pool:{gpu_pool}"

    if endpoint_gpu_types:
        rates = []
        for gt in endpoint_gpu_types:
            pool = pool_for_gpu_type(gt)
            if pool:
                rates.append((POOL_RATE_USD_PER_SEC[pool], gt))
        if rates:
            rate, gt = max(rates, key=lambda item: item[0])
            return rate, f"endpoint_max_gpu:{gt}"

    return POOL_RATE_USD_PER_SEC[DEFAULT_POOL], f"default_pool:{DEFAULT_POOL}"


def fetch_endpoint_config(endpoint_id: str, api_key: str, timeout: float = 30.0) -> dict[str, Any]:
    url = f"{REST_BASE}/endpoints/{endpoint_id}"
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def get_idle_timeout_sec(endpoint_id: str, api_key: str, timeout: float = 30.0) -> int:
    try:
        config = fetch_endpoint_config(endpoint_id, api_key, timeout=timeout)
        idle = config.get("idleTimeout")
        if idle is not None:
            return int(idle)
    except Exception:
        pass
    return DEFAULT_IDLE_TIMEOUT_SEC


def estimate_billable_seconds(
    *,
    delay_time_ms: int = 0,
    execution_time_ms: int = 0,
    idle_timeout_sec: int = DEFAULT_IDLE_TIMEOUT_SEC,
) -> dict[str, Any]:
    """
    Estimate billed GPU seconds for a completed/failed job.

    RunPod bills from worker start until scale-down (includes idle timeout after job).
    delayTime + executionTime is the best per-job approximation from the status API.
    """
    delay_sec = max(0, int(delay_time_ms)) / 1000.0
    execution_sec = max(0, int(execution_time_ms)) / 1000.0
    worker_active_sec = delay_sec + execution_sec
    billable_sec = math.ceil(worker_active_sec) + max(0, int(idle_timeout_sec))
    return {
        "delay_time_ms": int(delay_time_ms),
        "execution_time_ms": int(execution_time_ms),
        "delay_sec": round(delay_sec, 3),
        "execution_sec": round(execution_sec, 3),
        "worker_active_sec": round(worker_active_sec, 3),
        "idle_timeout_sec": int(idle_timeout_sec),
        "billable_sec": int(billable_sec),
    }


def estimate_job_cost_usd(
    *,
    delay_time_ms: int = 0,
    execution_time_ms: int = 0,
    gpu_type: Optional[str] = None,
    gpu_pool: Optional[str] = None,
    endpoint_id: Optional[str] = None,
    api_key: Optional[str] = None,
    idle_timeout_sec: Optional[int] = None,
    endpoint_gpu_types: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Estimate USD cost for one Serverless job.

    Set endpoint_id + api_key to load idleTimeout from RunPod REST API.
    """
    if idle_timeout_sec is None and endpoint_id and api_key:
        idle_timeout_sec = get_idle_timeout_sec(endpoint_id, api_key)
    if idle_timeout_sec is None:
        idle_timeout_sec = DEFAULT_IDLE_TIMEOUT_SEC

    if endpoint_gpu_types is None and endpoint_id and api_key:
        try:
            config = fetch_endpoint_config(endpoint_id, api_key)
            endpoint_gpu_types = config.get("gpuTypeIds") or []
        except Exception:
            endpoint_gpu_types = []

    timing = estimate_billable_seconds(
        delay_time_ms=delay_time_ms,
        execution_time_ms=execution_time_ms,
        idle_timeout_sec=idle_timeout_sec,
    )
    rate, rate_source = rate_usd_per_sec(
        gpu_type=gpu_type,
        gpu_pool=gpu_pool,
        endpoint_gpu_types=endpoint_gpu_types,
    )
    cost_usd = round(timing["billable_sec"] * rate, 6)

    return {
        "cost_usd": cost_usd,
        "cost_usd_formatted": f"${cost_usd:.4f}",
        "rate_usd_per_sec": rate,
        "rate_source": rate_source,
        "gpu_type": gpu_type,
        "gpu_pool": gpu_pool or (pool_for_gpu_type(gpu_type) if gpu_type else None),
        "estimate": True,
        "note": (
            "Estimate from RunPod status timings + published serverless rates. "
            "Not an official invoice line item."
        ),
        **timing,
    }


def estimate_from_status_payload(
    status_payload: Mapping[str, Any],
    *,
    endpoint_id: str,
    api_key: str,
) -> dict[str, Any]:
    """
    Build a cost estimate from GET /v2/{endpoint}/status/{job_id} JSON.

    Reads gpu_type/gpu_pool from handler output.billing when present.
    """
    output = status_payload.get("output") or {}
    billing_meta = output.get("billing") if isinstance(output, dict) else None
    gpu_type = None
    gpu_pool = None
    if isinstance(billing_meta, dict):
        gpu_type = billing_meta.get("gpu_type")
        gpu_pool = billing_meta.get("gpu_pool")

    result = estimate_job_cost_usd(
        delay_time_ms=int(status_payload.get("delayTime") or 0),
        execution_time_ms=int(status_payload.get("executionTime") or 0),
        gpu_type=gpu_type,
        gpu_pool=gpu_pool,
        endpoint_id=endpoint_id,
        api_key=api_key,
    )
    result["job_id"] = status_payload.get("id")
    result["status"] = status_payload.get("status")
    result["worker_id"] = status_payload.get("workerId")
    if isinstance(billing_meta, dict):
        result["handler_timing_ms"] = billing_meta.get("handler_ms")
    return result


def fetch_endpoint_billing(
    api_key: str,
    *,
    endpoint_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    bucket_size: str = "hour",
    grouping: str = "gpuTypeId",
) -> list[dict[str, Any]]:
    """Aggregate billing from RunPod REST API (reconciliation, not per job)."""
    params: dict[str, Any] = {
        "bucketSize": bucket_size,
        "grouping": grouping,
    }
    if endpoint_id:
        params["endpointId"] = endpoint_id
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time

    response = requests.get(
        f"{REST_BASE}/billing/endpoints",
        headers={"Authorization": f"Bearer {api_key}"},
        params=params,
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()
