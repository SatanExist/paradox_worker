"""HTTP API for AI_MESH Studio (T2 / Hi3DGen / FAL Meshy / Hitem / Tripo / Rodin)."""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import mimetypes
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from urllib.parse import urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
mimetypes.add_type("text/javascript", ".mjs")

from studio_bridge.lab_workspace import (  # noqa: E402
    ALLOWED_IMAGE_SUFFIXES,
    MAX_UPLOAD_BYTES,
    safe_upload_name,
    save_lab_thumbnail,
    workspace_payload,
)
from studio_bridge.credits import credit_catalog  # noqa: E402
from studio_bridge.engines import DEFAULT_ENGINE, engine_catalog  # noqa: E402
from studio_bridge.fal_client import FalHttpError, FalNotConfiguredError  # noqa: E402
from studio_bridge.fal_webhook import (  # noqa: E402
    FalWebhookError,
    store_webhook,
    verify_webhook,
)
from studio_bridge.gateway import (  # noqa: E402
    EngineNotConfiguredError,
    create_studio_job,
    get_studio_job,
)
from studio_bridge.hitem_client import HitemHttpError, HitemNotConfiguredError  # noqa: E402
from studio_bridge.hunyuan_client import HunyuanHttpError, HunyuanNotConfiguredError  # noqa: E402
from studio_bridge.rodin_client import RodinHttpError, RodinNotConfiguredError  # noqa: E402
from studio_bridge.tripo_client import TripoHttpError, TripoNotConfiguredError  # noqa: E402
from studio_bridge.geo import HunyuanGeoBlocked, country_from_headers  # noqa: E402
from studio_bridge.product_multi_ux import studio_copy_bundle  # noqa: E402
from studio_bridge.r2_public import R2NotConfiguredError, upload_public_file  # noqa: E402
from studio_bridge.text2image import Text2ImageNotConfiguredError  # noqa: E402
from studio_bridge.tools_advisor import AdviceError, advise  # noqa: E402
from studio_bridge.tools_jobs import (  # noqa: E402
    ToolsNotConfiguredError,
    create_tool_job,
    get_tool_job,
    is_tool_job,
)
from studio_bridge.tiers import (  # noqa: E402
    DEFAULT_MULTI_IMAGE_MODE,
    DEFAULT_PRESET,
    MAX_MULTI_IMAGES,
    MIN_MULTI_IMAGES,
    MultiImageMode,
    TextureMode,
    TierName,
)

app = FastAPI(title="AI_MESH Studio Bridge (POC)", version="0.7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8787",
        "http://localhost:8787",
        "http://127.0.0.1:8765",
        "http://localhost:8765",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Once the lab is public, the site's /api/studio proxy is its only door: the proxy checks who is
# asking and what was paid for, then sends this secret along. Without STUDIO_BRIDGE_SECRET the
# lab answers only this machine, as in local development.
BRIDGE_SECRET = os.getenv("STUDIO_BRIDGE_SECRET", "").strip()
SECRET_HEADER = "x-studio-secret"
OPEN_PATHS = {"/health"}


def _from_this_machine(request: Request) -> bool:
    if request.headers.get("x-forwarded-for"):
        return False  # came through a proxy, whatever address it shows
    try:
        return ipaddress.ip_address(request.client.host if request.client else "").is_loopback
    except ValueError:
        return False


@app.middleware("http")
async def require_site_secret(request: Request, call_next):
    if request.url.path in OPEN_PATHS:
        return await call_next(request)
    if BRIDGE_SECRET:
        given = request.headers.get(SECRET_HEADER, "")
        allowed = hmac.compare_digest(given.encode("utf-8"), BRIDGE_SECRET.encode("utf-8"))
    else:
        allowed = _from_this_machine(request)
    if not allowed:
        return Response(
            content=json.dumps({"detail": "Forbidden"}),
            status_code=403,
            media_type="application/json",
        )
    return await call_next(request)


class ViewSlots(BaseModel):
    """Named real-photo slots (Front required). Empty optional slots omitted."""

    front: str
    side: str | None = None
    back: str | None = None
    extra: str | None = None


class ThumbBody(BaseModel):
    id: str
    image: str


class ToolJobRequest(BaseModel):
    operation: str
    modelUrl: str
    params: dict = Field(default_factory=dict)
    outputKey: str


class AdviceView(BaseModel):
    label: str = Field(max_length=80)
    png: str = Field(max_length=6_000_000)  # base64


class AdviceRequest(BaseModel):
    reports: list[dict] = Field(min_length=1, max_length=10)
    views: list[AdviceView] = Field(default_factory=list, max_length=8)
    goal: str | None = Field(default=None, max_length=300)


class CreateJobRequest(BaseModel):
    mode: Literal["image", "text"] = "image"
    tier: TierName = DEFAULT_PRESET
    imageUrl: str | None = None
    imageUrls: list[str] | None = Field(
        default=None,
        description=f"Multi-view refs ({MIN_MULTI_IMAGES}–{MAX_MULTI_IMAGES} public https URLs).",
        min_length=MIN_MULTI_IMAGES,
        max_length=MAX_MULTI_IMAGES,
    )
    viewSlots: ViewSlots | None = Field(
        default=None,
        description="Preferred Studio shape: front + optional side/back/extra real photos.",
    )
    multiImageMode: MultiImageMode | None = None
    softInput: bool | None = None
    softInputStrength: float = Field(default=0.75, ge=0.0, le=1.0)
    textureMode: TextureMode | None = Field(
        default=None,
        description="Override. Product default is textured (official T2 PBR). clay = debug only.",
    )
    preprocessImage: bool | None = Field(
        default=None,
        description="T2: maps to worker preprocess_image. Default follows tier preset.",
    )
    prompt: str | None = None
    seed: int = Field(default=1, ge=0)
    engine: str = Field(
        default=DEFAULT_ENGINE,
        description="trellis2 (default), hi3dgen, meshy, hitem3d*, tripo*, rodin, hunyuan.",
    )
    rodinQualityTier: str | None = Field(
        default=None,
        description="Rodin Gen-2.5 UI tier: lowest | low | medium | high | ultra.",
    )
    rodinOptions: dict | None = Field(
        default=None,
        description=(
            "Rodin Gen-2.5 knobs: material, textureMode, geometryMode, meshMode, "
            "facePreset, highPack, hdTexture, textureDelight, taPose, "
            "useOriginalAlpha, seed."
        ),
    )
    meshyOptions: dict | None = Field(
        default=None,
        description=(
            "Meshy 7.1 knobs: lane standard|game-ready, geometryResolution "
            "standard|2k|4k, topology, shouldTexture, enablePbr, shouldRemesh, pose."
        ),
    )
    tripoOptions: dict | None = Field(
        default=None,
        description=(
            "Tripo knobs: topology (P2), material, textureQuality, geometryQuality "
            "(H3 Ultra +20), smartLowPoly (H3 +10), facePreset, textureAlign, "
            "orientation (textured only), autofix, seed (omit = vendor random). "
            "Text mode skips OpenAI — native text-to-model. Credits stack from PAYG table."
        ),
    )
    hunyuanOptions: dict | None = Field(
        default=None,
        description=(
            "Hunyuan: lane pro|express|lowpoly; generateType Normal|Geometry|Sketch "
            "(Pro); enablePbr; faceCount; polygonType (LowPoly). Express=Rapid API."
        ),
    )
    hitemOptions: dict | None = Field(
        default=None,
        description="Hitem knobs: sku (fast|pro|v3), pbr, facePreset / face, shading (0.0–1.0).",
    )
    hi3dgenOptions: dict | None = Field(
        default=None,
        description="Hi3DGen RunPod knobs: detail, ssSteps, slatSteps, normalModel, seed.",
    )
    country: str | None = Field(
        default=None,
        description="ISO 3166-1 alpha-2. Required for Hunyuan; else CF-IPCountry.",
    )

    @model_validator(mode="after")
    def _require_image_or_urls(self) -> CreateJobRequest:
        if self.mode == "text":
            if not (self.prompt or "").strip():
                raise ValueError("prompt is required for mode=text")
            return self
        if not self.imageUrl and not self.imageUrls and not self.viewSlots:
            raise ValueError("imageUrl, imageUrls, or viewSlots is required for mode=image")
        return self


@app.get("/")
def lab_index() -> RedirectResponse:
    return RedirectResponse("/scripts/studio_lab.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


PROXY_GLB_TIMEOUT_SEC = 8


def _fetch_glb_bytes(url: str) -> bytes:
    request = UrlRequest(url, headers={"User-Agent": "paradox-studio-lab"})
    with urlopen(request, timeout=PROXY_GLB_TIMEOUT_SEC) as upstream:
        return upstream.read()


@app.get("/api/proxy-glb")
async def proxy_glb(url: str) -> Response:
    """Same-origin fetch for an R2/https GLB. Short timeout so DNS cannot freeze the lab."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(status_code=400, detail="url must be https")
    try:
        data = await asyncio.to_thread(_fetch_glb_bytes, url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc
    if len(data) < 12 or data[:4] != b"glTF":
        raise HTTPException(status_code=502, detail="upstream did not return a GLB")
    return Response(
        content=data,
        media_type="model/gltf-binary",
        headers={
            "Content-Length": str(len(data)),
            "Cache-Control": "private, max-age=3600",
        },
    )


def _country_from(request: Request, explicit: str | None = None) -> str | None:
    return country_from_headers(request.headers, explicit=explicit)


@app.get("/api/product-copy")
def product_copy(request: Request, country: str | None = None) -> dict:
    """Studio copy + slot contract (productMultiUx path A) + engine/credit catalog."""
    return studio_copy_bundle(country=_country_from(request, country))


@app.get("/api/engines")
def list_engines(request: Request, country: str | None = None) -> dict:
    resolved = _country_from(request, country)
    return {
        "country": resolved,
        "defaultEngine": DEFAULT_ENGINE,
        "engines": engine_catalog(country=resolved),
    }


@app.get("/api/credits")
def list_credits() -> dict:
    return credit_catalog()


@app.get("/api/lab/workspace")
def lab_workspace() -> dict:
    """Local generation shelf + smoke refs. Not the public site contract."""
    return workspace_payload()


@app.post("/api/lab/upload-image")
def lab_upload_image(file: UploadFile = File(...)) -> dict:
    """Upload a local image to R2 so RunPod can fetch it. Lab-only."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"image type must be one of {sorted(ALLOWED_IMAGE_SUFFIXES)}",
        )

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="image larger than 20 MB")
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    name = safe_upload_name(file.filename or "image.png")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    object_key = f"lab/{stamp}_{name}"

    uploads = ROOT / "preview_textures" / "lab_uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    local_copy = uploads / f"{stamp}_{name}"

    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(name).suffix) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        local_copy.write_bytes(data)
        url = upload_public_file(tmp_path, object_key)
    except R2NotConfiguredError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    return {
        "url": url,
        "key": object_key,
        "localPath": f"/preview_textures/lab_uploads/{local_copy.name}",
        "bytes": len(data),
    }


@app.post("/api/lab/thumbnail")
def lab_save_thumbnail(body: ThumbBody) -> dict:
    """Save a client-rendered GLB snapshot for the gallery. Lab-only."""
    try:
        url = save_lab_thumbnail(body.id, body.image)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"thumb": url}


@app.post("/api/fal/webhook")
async def fal_webhook(request: Request) -> dict:
    """Fal queue completion. Verified ED25519; body kept for job polling."""
    body = await request.body()
    try:
        verify_webhook(body, request.headers)
        parsed = json.loads(body.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise FalWebhookError("webhook body must be an object")
        store_webhook(parsed)
    except FalWebhookError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="webhook body is not JSON") from exc
    return {"ok": True}


@app.post("/api/jobs")
def post_job(body: CreateJobRequest, request: Request) -> dict:
    slots = body.viewSlots.model_dump() if body.viewSlots else None
    country = _country_from(request, body.country)
    try:
        return create_studio_job(
            mode=body.mode,
            engine=body.engine,
            tier=body.tier,
            image_url=body.imageUrl,
            image_urls=body.imageUrls,
            view_slots=slots,
            multi_image_mode=body.multiImageMode,
            soft_input=body.softInput,
            soft_input_strength=body.softInputStrength,
            texture_mode=body.textureMode,
            preprocess_image=body.preprocessImage,
            prompt=body.prompt,
            seed=body.seed,
            country=country,
            rodin_quality_tier=body.rodinQualityTier,
            rodin_options=body.rodinOptions,
            meshy_options=body.meshyOptions,
            tripo_options=body.tripoOptions,
            hunyuan_options=body.hunyuanOptions,
            hitem_options=body.hitemOptions,
            hi3dgen_options=body.hi3dgenOptions,
        )
    except HunyuanGeoBlocked as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Text2ImageNotConfiguredError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except (
        FalNotConfiguredError,
        EngineNotConfiguredError,
        HitemNotConfiguredError,
        TripoNotConfiguredError,
        RodinNotConfiguredError,
        HunyuanNotConfiguredError,
    ) as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except (
        FalHttpError,
        HitemHttpError,
        TripoHttpError,
        RodinHttpError,
        HunyuanHttpError,
    ) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/tools/jobs")
def post_tool_job(body: ToolJobRequest) -> dict:
    """A tool on a finished model (print prep, …). The site makes the version row; we do the work."""
    try:
        return create_tool_job(
            operation=body.operation,
            model_url=body.modelUrl,
            params=body.params,
            output_key=body.outputKey,
        )
    except ToolsNotConfiguredError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc


@app.post("/api/tools/advise")
def post_tool_advice(body: AdviceRequest) -> dict:
    """Claude's advice on a game_prep result: verdict, issues, the run to try next. Advice only."""
    import base64
    import binascii

    import anthropic

    try:
        views = [(v.label, base64.b64decode(v.png, validate=True)) for v in body.views]
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="views must be base64 PNG") from exc
    try:
        return advise(body.reports, views, body.goal)
    except anthropic.AuthenticationError as exc:
        raise HTTPException(status_code=501, detail="Claude API key is not set up") from exc
    except (AdviceError, anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}")
def get_job_status(
    job_id: str,
    request: Request,
    tier: TierName = DEFAULT_PRESET,
    country: str | None = None,
) -> dict:
    if is_tool_job(job_id):
        try:
            return get_tool_job(job_id)
        except ToolsNotConfiguredError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc
    try:
        return get_studio_job(
            job_id,
            tier=tier,
            country=_country_from(request, country),
        )
    except HunyuanGeoBlocked as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (
        FalNotConfiguredError,
        EngineNotConfiguredError,
        HitemNotConfiguredError,
        TripoNotConfiguredError,
        RodinNotConfiguredError,
    ) as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except (FalHttpError, HitemHttpError, TripoHttpError, RodinHttpError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


_preview_dir = ROOT / "preview_textures"
if _preview_dir.is_dir():
    app.mount(
        "/preview_textures",
        StaticFiles(directory=_preview_dir),
        name="preview_textures",
    )
app.mount("/scripts", StaticFiles(directory=ROOT / "scripts"), name="scripts")


def _assert_ctypes() -> None:
    """Fail fast on the broken 3.14.0 venv (ctypes DLL mismatch after 3.14.6)."""
    try:
        import ctypes  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "This interpreter cannot import ctypes (typical when .venv was "
            "created with Python 3.14.0 and the install was upgraded to 3.14.6).\n"
            "Start the lab with:  .\\scripts\\studio_lab.ps1\n"
            "or:  .\\.venv-studio\\Scripts\\python.exe scripts\\studio_api.py"
        ) from exc


def main() -> None:
    _assert_ctypes()
    import uvicorn

    host = os.getenv("STUDIO_API_HOST", "127.0.0.1")
    port = int(os.getenv("STUDIO_API_PORT", "8787"))
    if host not in ("127.0.0.1", "localhost", "::1") and not BRIDGE_SECRET:
        raise SystemExit(
            f"Refusing to listen on {host} without STUDIO_BRIDGE_SECRET: "
            "anyone could start paid jobs past the site."
        )
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
