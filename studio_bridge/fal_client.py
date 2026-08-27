"""FAL Queue REST client (server-side only).

Official pattern from each model API tab +
https://fal.ai/docs/documentation/development/calling-your-endpoints

  POST https://queue.fal.run/{model_id}
  Authorization: Key $FAL_KEY
  body = model input fields (not wrapped in {input: ...})

  GET  .../requests/{request_id}/status
  GET  .../requests/{request_id}          # result when COMPLETED

Never send FAL_KEY to the browser.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

QUEUE_BASE = "https://queue.fal.run"
DEFAULT_TIMEOUT_SEC = 60


class FalNotConfiguredError(RuntimeError):
    pass


class FalHttpError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"FAL HTTP {status}: {body[:300]}")


def fal_key() -> str:
    key = os.getenv("FAL_KEY", "").strip()
    if not key:
        raise FalNotConfiguredError("FAL_KEY is not set")
    return key


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Key {fal_key()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise FalHttpError(exc.code, err_body) from exc
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise FalHttpError(200, f"expected JSON object, got {type(parsed).__name__}")
    return parsed


def submit(model_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Queue a job. Returns request_id / status_url / response_url."""
    model = (model_id or "").strip().strip("/")
    if not model:
        raise ValueError("FAL model_id is required")
    return _request("POST", f"{QUEUE_BASE}/{model}", payload=arguments)


def get_status(model_id: str, request_id: str) -> dict[str, Any]:
    model = (model_id or "").strip().strip("/")
    rid = (request_id or "").strip()
    if not rid:
        raise ValueError("FAL request_id is required")
    return _request("GET", f"{QUEUE_BASE}/{model}/requests/{rid}/status")


def get_result(model_id: str, request_id: str) -> dict[str, Any]:
    model = (model_id or "").strip().strip("/")
    rid = (request_id or "").strip()
    if not rid:
        raise ValueError("FAL request_id is required")
    return _request("GET", f"{QUEUE_BASE}/{model}/requests/{rid}")
