"""Fal queue webhooks: verify the ED25519 signature and keep the body.

Submit with ``?fal_webhook=`` (see fal_client.submit). Fal then POSTs the
finished payload here, so a 504 on GET /requests/{id} does not lose the mesh.

https://fal.ai/docs/documentation/model-apis/inference/webhooks
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "preview_textures" / "fal_inbox"
JWKS_URL = "https://rest.fal.ai/.well-known/jwks.json"
_JWKS_MAX_AGE_SEC = 24 * 60 * 60
_TIMESTAMP_SKEW_SEC = 300

_jwks_cache: dict[str, Any] = {"keys": [], "fetched": 0.0}


class FalWebhookError(ValueError):
    """Rejected webhook: bad signature, stale timestamp, or a bad request id."""


def webhook_url() -> str:
    """Public URL Fal should POST. Empty means keep polling."""
    return os.getenv("FAL_WEBHOOK_URL", "").strip()


def _b64url(raw: str) -> bytes:
    pad = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + pad)


def _load_public_keys() -> list[bytes]:
    now = time.time()
    cached = _jwks_cache["keys"]
    if cached and now - float(_jwks_cache["fetched"]) < _JWKS_MAX_AGE_SEC:
        return cached
    req = urllib.request.Request(JWKS_URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    keys: list[bytes] = []
    for item in body.get("keys") or []:
        raw = item.get("x")
        if isinstance(raw, str) and raw:
            keys.append(_b64url(raw))
    if not keys:
        raise FalWebhookError("Fal JWKS has no keys")
    _jwks_cache["keys"] = keys
    _jwks_cache["fetched"] = now
    return keys


def _header(headers: Mapping[str, str], name: str) -> str:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return str(value or "").strip()
    return ""


def verify_webhook(body: bytes, headers: Mapping[str, str]) -> None:
    """Raise FalWebhookError unless the body was signed by Fal."""
    request_id = _header(headers, "X-Fal-Webhook-Request-Id")
    user_id = _header(headers, "X-Fal-Webhook-User-Id")
    timestamp = _header(headers, "X-Fal-Webhook-Timestamp")
    signature = _header(headers, "X-Fal-Webhook-Signature")
    if not (request_id and user_id and timestamp and signature):
        raise FalWebhookError("missing Fal webhook signature headers")
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise FalWebhookError("bad Fal webhook timestamp") from exc
    if abs(time.time() - ts) > _TIMESTAMP_SKEW_SEC:
        raise FalWebhookError("Fal webhook timestamp is outside ±5 minutes")
    digest = hashlib.sha256(body).hexdigest()
    message = f"{request_id}\n{user_id}\n{timestamp}\n{digest}".encode("utf-8")
    try:
        sig = bytes.fromhex(signature)
    except ValueError as exc:
        raise FalWebhookError("bad Fal webhook signature") from exc
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    for raw_key in _load_public_keys():
        try:
            Ed25519PublicKey.from_public_bytes(raw_key).verify(sig, message)
            return
        except (InvalidSignature, ValueError):
            continue
    raise FalWebhookError("Fal webhook signature did not match")


def _safe_id(request_id: str) -> str:
    rid = (request_id or "").strip()
    if not rid or len(rid) > 128 or any(ch in rid for ch in "/\\"):
        raise FalWebhookError("bad Fal request id")
    return rid


def store_webhook(body: dict[str, Any]) -> str:
    """Persist one delivery. Same request_id overwrites (Fal retries)."""
    rid = _safe_id(str(body.get("request_id") or ""))
    INBOX.mkdir(parents=True, exist_ok=True)
    path = INBOX / f"{rid}.json"
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return rid


def load_webhook(request_id: str) -> dict[str, Any] | None:
    try:
        rid = _safe_id(request_id)
    except FalWebhookError:
        return None
    path = INBOX / f"{rid}.json"
    if not path.is_file():
        return None
    parsed = json.loads(path.read_text(encoding="utf-8"))
    return parsed if isinstance(parsed, dict) else None
