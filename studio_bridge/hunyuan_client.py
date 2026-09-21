"""Tencent HY 3D Global — Professional + Express (server-side only).

  Pro:    SubmitHunyuanTo3DProJob / QueryHunyuanTo3DProJob
  Rapid:  SubmitHunyuanTo3DRapidJob / QueryHunyuanTo3DRapidJob
  Host: hunyuan.intl.tencentcloudapi.com
  Auth: TENCENTCLOUD_SECRET_ID + TENCENTCLOUD_SECRET_KEY (TC3-HMAC-SHA256)

PolyLab: one engine card with lane Pro | Express | LowPoly.
  Pro     → Model 3.1, GenerateType Normal|Geometry|Sketch
  Express → Rapid API (fast draft; no multi-view)
  LowPoly → Pro API Model 3.0 + GenerateType LowPoly
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SERVICE = "hunyuan"
HOST = "hunyuan.intl.tencentcloudapi.com"
API_VERSION = "2023-09-01"
DEFAULT_REGION = "ap-singapore"
DEFAULT_TIMEOUT_SEC = 60
DEFAULT_MODEL = "3.1"
DEFAULT_GENERATE_TYPE = "Normal"
DEFAULT_FACE_COUNT = 500_000
DEFAULT_LANE = "pro"
HUNYUAN_ENGINE_IDS = frozenset({"hunyuan", "hunyuan_pro"})
HunyuanLane = Literal["pro", "express", "lowpoly"]
HunyuanApi = Literal["pro", "rapid"]
GENERATE_TYPES_V31 = frozenset({"Normal", "Geometry", "Sketch"})
GENERATE_TYPES_ALL = GENERATE_TYPES_V31 | frozenset({"LowPoly"})
VIEW_TYPES = frozenset(
    {
        "left",
        "right",
        "back",
        "top",
        "bottom",
        "left_front",
        "right_front",
    }
)
# Prepaid ~$0.015 / vendor credit (billing overview).
VENDOR_CREDIT_USD = 0.015
# Professional prepaid table.
PRO_BASE_CREDITS = {
    "Normal": 25,
    "Sketch": 25,
    "LowPoly": 30,
    "Geometry": 15,
}
# Express (Rapid) prepaid: 15 / call; PBR +10.
EXPRESS_BASE_CREDITS = 15
PBR_EXTRA_CREDITS = 10
LANES = frozenset({"pro", "express", "lowpoly"})


class HunyuanNotConfiguredError(RuntimeError):
    pass


class HunyuanHttpError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"Hunyuan HTTP {status}: {body[:400]}")


@dataclass(frozen=True)
class HunyuanEngineMeta:
    label: str
    blurb: str
    eta_sec: int


HUNYUAN_ENGINE = HunyuanEngineMeta(
    label="Hunyuan 3D",
    blurb="Tencent HY 3D Global — Pro 3.1 / Express / LowPoly, PBR, multi-view on Pro.",
    eta_sec=210,
)


def normalize_lane(raw: Any) -> HunyuanLane:
    s = str(raw or DEFAULT_LANE).strip().lower()
    if s in {"rapid", "express", "draft", "fast"}:
        return "express"
    if s in {"lowpoly", "low_poly", "low-poly"}:
        return "lowpoly"
    return "pro"


def api_for_lane(lane: HunyuanLane) -> HunyuanApi:
    return "rapid" if lane == "express" else "pro"


def credentials() -> tuple[str, str]:
    sid = (os.getenv("TENCENTCLOUD_SECRET_ID") or "").strip().strip("\"'")
    sk = (os.getenv("TENCENTCLOUD_SECRET_KEY") or "").strip().strip("\"'")
    if not sid or not sk:
        raise HunyuanNotConfiguredError(
            "Set TENCENTCLOUD_SECRET_ID and TENCENTCLOUD_SECRET_KEY in .env"
        )
    return sid, sk


def is_configured() -> bool:
    try:
        credentials()
        return True
    except HunyuanNotConfiguredError:
        return False


def is_hunyuan_engine_id(engine_id: str | None) -> bool:
    return (engine_id or "").strip().lower() in HUNYUAN_ENGINE_IDS


def vendor_credits_for_options(options: dict[str, Any] | None) -> tuple[int, tuple[str, ...]]:
    knobs = resolve_options(options)
    lane = knobs["lane"]
    if lane == "express":
        if knobs["enableGeometry"]:
            return EXPRESS_BASE_CREDITS, ("Express Geometry 15",)
        n = EXPRESS_BASE_CREDITS
        lines = ["Express 15"]
        if knobs["enablePbr"]:
            n += PBR_EXTRA_CREDITS
            lines.append(f"PBR +{PBR_EXTRA_CREDITS}")
        return n, tuple(lines)
    if lane == "lowpoly":
        n = PRO_BASE_CREDITS["LowPoly"]
        lines = ["LowPoly 30"]
        if knobs["enablePbr"]:
            n += PBR_EXTRA_CREDITS
            lines.append(f"PBR +{PBR_EXTRA_CREDITS}")
        return n, tuple(lines)
    gen = knobs["generateType"]
    n = PRO_BASE_CREDITS.get(gen, PRO_BASE_CREDITS["Normal"])
    lines = [f"{gen} {n}"]
    if knobs["enablePbr"] and gen != "Geometry":
        n += PBR_EXTRA_CREDITS
        lines.append(f"PBR +{PBR_EXTRA_CREDITS}")
    return n, tuple(lines)


def list_usd_for_options(options: dict[str, Any] | None) -> float:
    n, _ = vendor_credits_for_options(options)
    return round(n * VENDOR_CREDIT_USD, 4)


# Local clock can drift past Tencent's ±5 min TC3 window (SignatureExpire).
_CLOCK_SKEW_SEC = 0


def _now_ts() -> int:
    return int(time.time()) + _CLOCK_SKEW_SEC


def _apply_server_time_hint(message: str) -> bool:
    """Parse 'server time <unix>' from AuthFailure.SignatureExpire and set skew."""
    global _CLOCK_SKEW_SEC
    match = re.search(r"server time\s+(\d{10,})", message or "", flags=re.I)
    if not match:
        return False
    server_ts = int(match.group(1))
    local_ts = int(time.time())
    skew = server_ts - local_ts
    if abs(skew) < 2:
        return False
    _CLOCK_SKEW_SEC = skew
    return True


def _sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _tc3_authorization(
    *,
    secret_id: str,
    secret_key: str,
    action: str,
    payload: str,
    region: str,
    timestamp: int,
) -> dict[str, str]:
    date = time.strftime("%Y-%m-%d", time.gmtime(timestamp))
    canonical_headers = (
        f"content-type:application/json; charset=utf-8\n"
        f"host:{HOST}\n"
        f"x-tc-action:{action.lower()}\n"
    )
    signed_headers = "content-type;host;x-tc-action"
    canonical_request = (
        "POST\n/\n\n"
        f"{canonical_headers}\n"
        f"{signed_headers}\n"
        f"{_sha256_hex(payload)}"
    )
    credential_scope = f"{date}/{SERVICE}/tc3_request"
    string_to_sign = (
        f"TC3-HMAC-SHA256\n{timestamp}\n{credential_scope}\n"
        f"{_sha256_hex(canonical_request)}"
    )
    secret_date = _sign(f"TC3{secret_key}".encode("utf-8"), date)
    secret_service = _sign(secret_date, SERVICE)
    secret_signing = _sign(secret_service, "tc3_request")
    signature = hmac.new(
        secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    authorization = (
        "TC3-HMAC-SHA256 "
        f"Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "Authorization": authorization,
        "Content-Type": "application/json; charset=utf-8",
        "Host": HOST,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": API_VERSION,
        "X-TC-Region": region,
    }


def _request(action: str, params: dict[str, Any]) -> dict[str, Any]:
    secret_id, secret_key = credentials()
    region = (os.getenv("TENCENTCLOUD_REGION") or DEFAULT_REGION).strip()
    payload = json.dumps(params, ensure_ascii=False, separators=(",", ":"))

    def _once(timestamp: int) -> dict[str, Any]:
        headers = _tc3_authorization(
            secret_id=secret_id,
            secret_key=secret_key,
            action=action,
            payload=payload,
            region=region,
            timestamp=timestamp,
        )
        req = Request(
            f"https://{HOST}",
            data=payload.encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(req, timeout=DEFAULT_TIMEOUT_SEC) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                status = getattr(resp, "status", 200)
        except HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise HunyuanHttpError(exc.code, err_body) from exc
        except URLError as exc:
            raise HunyuanHttpError(0, str(exc)) from exc
        if status >= 400:
            raise HunyuanHttpError(status, body)
        data = json.loads(body)
        if not isinstance(data, dict):
            raise HunyuanHttpError(status, body)
        response = data.get("Response")
        if not isinstance(response, dict):
            raise HunyuanHttpError(status, body)
        if response.get("Error"):
            err = response["Error"]
            code = err.get("Code", "Error") if isinstance(err, dict) else "Error"
            msg = err.get("Message", body) if isinstance(err, dict) else body
            raise HunyuanHttpError(400, f"{code}: {msg}")
        return response

    try:
        return _once(_now_ts())
    except HunyuanHttpError as exc:
        text_err = str(exc)
        if "SignatureExpire" in text_err and _apply_server_time_hint(text_err):
            return _once(_now_ts())
        raise

def resolve_options(options: dict[str, Any] | None) -> dict[str, Any]:
    opts = options or {}
    lane = normalize_lane(opts.get("lane") or opts.get("quality") or opts.get("api"))
    enable_pbr = bool(opts.get("enablePbr") or opts.get("enablePBR"))
    polygon = str(opts.get("polygonType") or "triangle").strip().lower()
    if polygon not in {"triangle", "quadrilateral"}:
        polygon = "triangle"
    face_raw = opts.get("faceCount", DEFAULT_FACE_COUNT)
    try:
        face_count = int(face_raw)
    except (TypeError, ValueError):
        face_count = DEFAULT_FACE_COUNT
    face_count = max(3000, min(1_500_000, face_count))

    if lane == "express":
        gen = str(opts.get("generateType") or "Normal").strip()
        enable_geometry = gen == "Geometry" or bool(opts.get("enableGeometry"))
        if enable_geometry:
            enable_pbr = False
        return {
            "lane": "express",
            "api": "rapid",
            "model": "rapid",
            "generateType": "Geometry" if enable_geometry else "Normal",
            "enableGeometry": enable_geometry,
            "enablePbr": enable_pbr,
            "faceCount": face_count,
            "polygonType": polygon,
        }

    if lane == "lowpoly":
        return {
            "lane": "lowpoly",
            "api": "pro",
            "model": "3.0",
            "generateType": "LowPoly",
            "enableGeometry": False,
            "enablePbr": enable_pbr,
            "faceCount": face_count,
            "polygonType": polygon,
        }

    # Pro 3.1
    gen = str(opts.get("generateType") or DEFAULT_GENERATE_TYPE).strip()
    if gen == "LowPoly":
        gen = "Normal"
    if gen not in GENERATE_TYPES_V31:
        gen = DEFAULT_GENERATE_TYPE
    if gen == "Geometry":
        enable_pbr = False
    return {
        "lane": "pro",
        "api": "pro",
        "model": "3.1",
        "generateType": gen,
        "enableGeometry": gen == "Geometry",
        "enablePbr": enable_pbr,
        "faceCount": face_count,
        "polygonType": polygon,
    }


def resolve_pro_options(options: dict[str, Any] | None) -> dict[str, Any]:
    """Backward-compatible alias — prefer resolve_options."""
    return resolve_options(options)


def _slot_to_view(slot: str) -> str | None:
    mapping = {
        "side": "left",
        "left": "left",
        "right": "right",
        "back": "back",
        "top": "top",
        "bottom": "bottom",
        "extra": "right",
        "left_front": "left_front",
        "right_front": "right_front",
    }
    return mapping.get((slot or "").strip().lower())


def submit_pro_job(
    *,
    image_url: str | None = None,
    prompt: str | None = None,
    view_slots: dict[str, str] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    knobs = resolve_options(options)
    if knobs["lane"] == "express":
        return submit_rapid_job(
            image_url=image_url,
            prompt=prompt,
            view_slots=view_slots,
            options=knobs,
        )
    params: dict[str, Any] = {
        "Model": knobs["model"],
        "GenerateType": knobs["generateType"],
        "EnablePBR": knobs["enablePbr"],
        "FaceCount": knobs["faceCount"],
    }
    if knobs["generateType"] == "LowPoly":
        params["PolygonType"] = knobs["polygonType"]

    text = (prompt or "").strip()
    front = (image_url or "").strip()
    slots = {k: (v or "").strip() for k, v in (view_slots or {}).items() if (v or "").strip()}
    if not front and slots.get("front"):
        front = slots["front"]

    multi: list[dict[str, str]] = []
    for slot, url in slots.items():
        if slot == "front":
            continue
        view = _slot_to_view(slot)
        if not view or view not in VIEW_TYPES:
            continue
        if knobs["model"] == "3.0" and view in {
            "top",
            "bottom",
            "left_front",
            "right_front",
        }:
            continue
        multi.append({"ViewType": view, "ViewImageUrl": url})

    if knobs["generateType"] == "Sketch":
        if not front and not text:
            raise ValueError("Sketch needs image and/or prompt")
        if front:
            params["ImageUrl"] = front
        if text:
            params["Prompt"] = text[:1024]
    elif text and not front and not multi:
        params["Prompt"] = text[:1024]
    elif front:
        params["ImageUrl"] = front
        if multi:
            params["MultiViewImages"] = multi
    elif multi:
        raise ValueError("multi-view requires a front image")
    else:
        raise ValueError("Provide image_url, prompt, or view_slots.front")

    response = _request("SubmitHunyuanTo3DProJob", params)
    job_id = str(response.get("JobId") or "").strip()
    if not job_id:
        raise HunyuanHttpError(502, json.dumps(response)[:400])
    return {
        "jobId": job_id,
        "api": "pro",
        "requestId": response.get("RequestId"),
        "knobs": knobs,
        "raw": response,
    }


def submit_rapid_job(
    *,
    image_url: str | None = None,
    prompt: str | None = None,
    view_slots: dict[str, str] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Express / Rapid — image XOR prompt; no multi-view."""
    knobs = resolve_options({**(options or {}), "lane": "express"})
    text = (prompt or "").strip()
    front = (image_url or "").strip()
    slots = {k: (v or "").strip() for k, v in (view_slots or {}).items() if (v or "").strip()}
    if not front and slots.get("front"):
        front = slots["front"]
    extra_views = [k for k in slots if k != "front"]
    if extra_views:
        raise ValueError("Express does not support multi-view — use Pro lane")

    params: dict[str, Any] = {
        "ResultFormat": "GLB",
        "EnablePBR": bool(knobs["enablePbr"] and not knobs["enableGeometry"]),
        "EnableGeometry": bool(knobs["enableGeometry"]),
    }
    if text and front:
        raise ValueError("Express: prompt and image are mutually exclusive")
    if front:
        params["ImageUrl"] = front
    elif text:
        params["Prompt"] = text[:200]
    else:
        raise ValueError("Express needs image_url or prompt")

    response = _request("SubmitHunyuanTo3DRapidJob", params)
    job_id = str(response.get("JobId") or "").strip()
    if not job_id:
        raise HunyuanHttpError(502, json.dumps(response)[:400])
    return {
        "jobId": job_id,
        "api": "rapid",
        "requestId": response.get("RequestId"),
        "knobs": knobs,
        "raw": response,
    }


def submit_job(
    *,
    image_url: str | None = None,
    prompt: str | None = None,
    view_slots: dict[str, str] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return submit_pro_job(
        image_url=image_url,
        prompt=prompt,
        view_slots=view_slots,
        options=options,
    )


def query_pro_job(job_id: str) -> dict[str, Any]:
    jid = (job_id or "").strip()
    if not jid:
        raise ValueError("job_id required")
    return _request("QueryHunyuanTo3DProJob", {"JobId": jid})


def query_rapid_job(job_id: str) -> dict[str, Any]:
    jid = (job_id or "").strip()
    if not jid:
        raise ValueError("job_id required")
    return _request("QueryHunyuanTo3DRapidJob", {"JobId": jid})


def query_job(job_id: str, *, api: HunyuanApi = "pro") -> dict[str, Any]:
    if api == "rapid":
        return query_rapid_job(job_id)
    return query_pro_job(job_id)


def map_status(raw: str | None) -> str:
    s = (raw or "").strip().upper()
    if s in {"WAIT", "WAITING"}:
        return "queued"
    if s in {"RUN", "RUNNING"}:
        return "running"
    if s in {"DONE", "SUCCESS"}:
        return "completed"
    if s in {"FAIL", "FAILED", "ERROR"}:
        return "failed"
    return "running"


def pick_glb(result_files: Any) -> tuple[str | None, str | None]:
    """Return (glb_url, preview_url) from ResultFile3Ds."""
    if not isinstance(result_files, list):
        return None, None
    glb = None
    preview = None
    for item in result_files:
        if not isinstance(item, dict):
            continue
        url = (
            item.get("Url")
            or item.get("FileUrl")
            or item.get("ModelUrl")
            or ""
        )
        url = str(url).strip()
        typ = str(item.get("Type") or item.get("FileType") or "").upper()
        preview = preview or (
            str(item.get("PreviewImageUrl") or item.get("PreviewUrl") or "").strip()
            or None
        )
        if not url:
            continue
        if "GLB" in typ or url.lower().split("?", 1)[0].endswith(".glb"):
            glb = url
            break
        if glb is None:
            glb = url
    return glb, preview
