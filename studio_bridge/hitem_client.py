"""Hitem3D / Hi3D Open Platform client (server-side only).

Official flow:
  https://docs.hi3d.ai/en/api/getting-started/quickstart
  POST /open-api/v1/auth/token     Basic client_id:client_secret
  POST /open-api/v1/submit-task    Bearer + multipart (images or multi_images)
  GET  /open-api/v1/query-task     Bearer + task_id

Never send HITEM_CLIENT_ID / HITEM_CLIENT_SECRET to the browser.
Does not wrap hi3d.ai consumer Pro/Max. Image-to-3D only (no relief/split).
"""

from __future__ import annotations

import json
import os
import uuid
from base64 import b64encode
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

API_BASE = "https://api.hitem3d.ai"
DEFAULT_TIMEOUT_SEC = 60
IMAGE_FETCH_TIMEOUT_SEC = 45
MAX_IMAGE_BYTES = 20 * 1024 * 1024
# Their multi_images order: front, back, left, right.
BIT_SLOTS: tuple[str, ...] = ("front", "back", "side", "extra")
_TOKEN_CACHE: dict[str, str] = {}


class HitemNotConfiguredError(RuntimeError):
    pass


class HitemHttpError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"Hitem HTTP {status}: {body[:300]}")


@dataclass(frozen=True)
class HitemPreset:
    model: str
    resolution: str
    face: int
    eta_sec: int
    list_usd: float
    label: str
    blurb: str
    role: str = "print"


# Public Image-to-3D nets from create-task docs (PBR SKUs only).
# Skip v1.5 (no PBR), v2.0 (superseded by 2.1), 2048master ($9.10).
HITEM_PRESETS: dict[str, HitemPreset] = {
    "hitem3d": HitemPreset(
        model="hitem3dv2.1",
        resolution="1536fast",
        face=2_000_000,
        eta_sec=240,
        list_usd=0.50,
        label="Hitem3D v2.1 fast",
        blurb="Печать / деталь. Прямой API, не FAL. PBR on.",
        role="print",
    ),
    "hitem3d_pro": HitemPreset(
        model="hitem3dv2.1",
        resolution="1536pro",
        face=2_000_000,
        eta_sec=360,
        list_usd=0.90,
        label="Hitem3D v2.1 pro",
        blurb="Печать / деталь, 1536pro. Прямой API.",
        role="print",
    ),
    "hitem3d_v3": HitemPreset(
        model="hi3dv3.0",
        resolution="2048quality",
        face=2_000_000,
        eta_sec=480,
        list_usd=2.10,
        label="Hitem3D v3.0 quality",
        blurb="2048³ quality. Дорого (~$2.10). Не default.",
        role="print",
    ),
    "hitem3d_portrait": HitemPreset(
        model="scene-portraitv2.1",
        resolution="1536profast",
        face=2_000_000,
        eta_sec=240,
        list_usd=0.50,
        label="Hitem3D portrait fast",
        blurb="Сцена-портрет v2.1. Не персонаж-рыцарь по умолчанию.",
        role="portrait",
    ),
}


def credentials() -> tuple[str, str]:
    client_id = os.getenv("HITEM_CLIENT_ID", "").strip()
    secret = os.getenv("HITEM_CLIENT_SECRET", "").strip()
    bundled = os.getenv("HITEM_API_KEY", "").strip()
    if (not client_id or not secret) and bundled and ":" in bundled:
        client_id, secret = bundled.split(":", 1)
        client_id, secret = client_id.strip(), secret.strip()
    if not client_id or not secret:
        raise HitemNotConfiguredError(
            "HITEM_CLIENT_ID and HITEM_CLIENT_SECRET are not set "
            "(Open Platform API key, not hi3d.ai Pro)"
        )
    return client_id, secret


def _ok_code(code: Any) -> bool:
    return code in (200, "200", 0, "0")


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: bytes | None = None,
    timeout: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            status = getattr(resp, "status", 200)
    except HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise HitemHttpError(exc.code, err_body) from exc
    except URLError as exc:
        raise HitemHttpError(502, str(exc.reason or exc)) from exc
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HitemHttpError(status, raw[:300]) from exc
    if not isinstance(parsed, dict):
        raise HitemHttpError(status, f"expected JSON object, got {type(parsed).__name__}")
    return parsed


def _unwrap(body: dict[str, Any], context: str) -> dict[str, Any]:
    if not _ok_code(body.get("code")):
        msg = str(body.get("msg") or body.get("message") or body)[:300]
        raw_code = body.get("code")
        status = int(raw_code) if str(raw_code).isdigit() else 502
        raise HitemHttpError(status, f"{context}: {msg}")
    data = body.get("data")
    if not isinstance(data, dict):
        raise HitemHttpError(502, f"{context}: missing data object")
    return data


def access_token(*, force: bool = False) -> str:
    client_id, secret = credentials()
    cache_key = client_id
    if not force and _TOKEN_CACHE.get(cache_key):
        return _TOKEN_CACHE[cache_key]
    basic = b64encode(f"{client_id}:{secret}".encode("utf-8")).decode("ascii")
    body = _request(
        "POST",
        f"{API_BASE}/open-api/v1/auth/token",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        body=b"{}",
    )
    data = _unwrap(body, "token")
    token = str(data.get("accessToken") or "").strip()
    if not token:
        raise HitemHttpError(502, "token response missing accessToken")
    _TOKEN_CACHE[cache_key] = token
    return token


def _sniff_image(url: str, payload: bytes, content_type: str) -> tuple[str, str]:
    ctype = (content_type or "").split(";")[0].strip().lower()
    lower = url.lower()
    if payload[:8] == b"\x89PNG\r\n\x1a\n" or ctype == "image/png" or lower.endswith(".png"):
        return "ref.png", "image/png"
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "ref.webp", "image/webp"
    if ctype == "image/webp" or lower.endswith(".webp"):
        return "ref.webp", "image/webp"
    return "ref.jpg", "image/jpeg"


def fetch_image(url: str) -> tuple[str, bytes, str]:
    raw = (url or "").strip()
    if not raw.startswith("https://"):
        raise ValueError("Hitem image URL must be https")
    req = Request(raw, headers={"User-Agent": "paradox-studio-hitem"}, method="GET")
    try:
        with urlopen(req, timeout=IMAGE_FETCH_TIMEOUT_SEC) as resp:
            payload = resp.read(MAX_IMAGE_BYTES + 1)
            ctype = resp.headers.get("Content-Type") or ""
    except HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise HitemHttpError(exc.code, f"fetch image: {err[:200]}") from exc
    except URLError as exc:
        raise HitemHttpError(502, f"fetch image: {exc.reason or exc}") from exc
    if len(payload) > MAX_IMAGE_BYTES:
        raise ValueError("image larger than 20 MB (Hitem limit)")
    if not payload:
        raise ValueError("empty image")
    name, mime = _sniff_image(raw, payload, ctype)
    return name, payload, mime


def view_plan(
    *,
    image_urls: list[str],
    view_slots: dict[str, str | None] | None = None,
) -> tuple[str | None, list[tuple[str, str]]]:
    """Return (multi_images_bit or None for single), ordered (slot, url)."""
    slots: dict[str, str] = {}
    if view_slots:
        for key in BIT_SLOTS:
            val = (view_slots.get(key) or "").strip()
            if val:
                slots[key] = val
    if "front" not in slots and image_urls:
        slots["front"] = image_urls[0]
        extras = ("side", "back", "extra")
        for url, key in zip(image_urls[1:], extras):
            slots.setdefault(key, url)
    if "front" not in slots:
        raise ValueError("Hitem needs a front image")
    ordered = [(key, slots[key]) for key in BIT_SLOTS if key in slots]
    if len(ordered) == 1:
        return None, ordered
    bits = ["0", "0", "0", "0"]
    for key, _url in ordered:
        bits[BIT_SLOTS.index(key)] = "1"
    return "".join(bits), ordered


def _multipart(
    fields: dict[str, str],
    files: list[tuple[str, str, bytes, str]],
) -> tuple[bytes, str]:
    boundary = "----ParadoxHitem" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    for field, filename, content, ctype in files:
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode("utf-8")
        chunks.append(head + content + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def submit_image_to_3d(
    engine_id: str,
    *,
    image_urls: list[str],
    view_slots: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    preset = HITEM_PRESETS.get(engine_id)
    if preset is None:
        raise ValueError(f"{engine_id} is not a Hitem Image-to-3D engine")
    bit, ordered = view_plan(image_urls=image_urls, view_slots=view_slots)
    files: list[tuple[str, str, bytes, str]] = []
    field = "images" if bit is None else "multi_images"
    for slot, url in ordered:
        name, payload, mime = fetch_image(url)
        files.append((field, f"{slot}_{name}", payload, mime))
    fields = {
        "request_type": "3",
        "model": preset.model,
        "resolution": preset.resolution,
        "face": str(preset.face),
        "pbr": "1",
        "shading": "0.5",
        "format": "2",
    }
    if bit is not None:
        fields["multi_images_bit"] = bit
    body, content_type = _multipart(fields, files)

    def _post(token: str) -> dict[str, Any]:
        return _request(
            "POST",
            f"{API_BASE}/open-api/v1/submit-task",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": content_type,
                "Accept": "application/json",
            },
            body=body,
            timeout=120,
        )

    try:
        data = _unwrap(_post(access_token()), "submit-task")
    except HitemHttpError:
        _TOKEN_CACHE.clear()
        data = _unwrap(_post(access_token(force=True)), "submit-task")
    task_id = str(data.get("task_id") or "").strip()
    if not task_id:
        raise HitemHttpError(502, f"submit-task missing task_id: {data}")
    return {"task_id": task_id, "model": preset.model, "resolution": preset.resolution}


def query_task(task_id: str) -> dict[str, Any]:
    tid = (task_id or "").strip()
    if not tid:
        raise ValueError("task_id required")
    token = access_token()
    url = f"{API_BASE}/open-api/v1/query-task?task_id={quote(tid)}"
    parsed = _request(
        "GET",
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    try:
        return _unwrap(parsed, "query-task")
    except HitemHttpError:
        _TOKEN_CACHE.clear()
        token = access_token(force=True)
        parsed = _request(
            "GET",
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        return _unwrap(parsed, "query-task")


def map_hitem_state(state: str | None) -> str:
    raw = (state or "").strip().lower()
    if raw in {"created", "queueing"}:
        return "queued"
    if raw == "processing":
        return "running"
    if raw == "success":
        return "ready"
    return "failed"


def query_balance() -> dict[str, Any]:
    token = access_token()
    parsed = _request(
        "GET",
        f"{API_BASE}/open-api/v1/balance",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    try:
        return _unwrap(parsed, "balance")
    except HitemHttpError:
        _TOKEN_CACHE.clear()
        token = access_token(force=True)
        parsed = _request(
            "GET",
            f"{API_BASE}/open-api/v1/balance",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        return _unwrap(parsed, "balance")
