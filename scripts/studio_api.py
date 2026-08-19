"""Minimal HTTP API for AI_MESH Studio integration (image/text → T2 RunPod)."""

from __future__ import annotations

import asyncio
import mimetypes
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
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
from studio_bridge.product_multi_ux import studio_copy_bundle  # noqa: E402
from studio_bridge.r2_public import R2NotConfiguredError, upload_public_file  # noqa: E402
from studio_bridge.service import create_job, get_job  # noqa: E402
from studio_bridge.text2image import Text2ImageNotConfiguredError  # noqa: E402
from studio_bridge.tiers import (  # noqa: E402
    DEFAULT_MULTI_IMAGE_MODE,
    DEFAULT_PRESET,
    MAX_MULTI_IMAGES,
    MIN_MULTI_IMAGES,
    MultiImageMode,
    TextureMode,
    TierName,
)

app = FastAPI(title="AI_MESH Studio Bridge (POC)", version="0.6.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8787",
        "http://localhost:8787",
        "http://127.0.0.1:8765",
        "http://localhost:8765",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ViewSlots(BaseModel):
    """Named real-photo slots (Front required). Empty optional slots omitted."""

    front: str
    side: str | None = None
    back: str | None = None
    extra: str | None = None


class ThumbBody(BaseModel):
    id: str
    image: str


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
    prompt: str | None = None
    seed: int = Field(default=1, ge=0)

    @model_validator(mode="after")
    def _require_image_or_urls(self) -> CreateJobRequest:
        if self.mode == "image" and not self.imageUrl and not self.imageUrls and not self.viewSlots:
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
    request = Request(url, headers={"User-Agent": "paradox-studio-lab"})
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


@app.get("/api/product-copy")
def product_copy() -> dict:
    """Studio copy + slot contract (productMultiUx path A)."""
    return studio_copy_bundle()


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


@app.post("/api/jobs")
def post_job(body: CreateJobRequest) -> dict:
    slots = body.viewSlots.model_dump() if body.viewSlots else None
    try:
        return create_job(
            mode=body.mode,
            tier=body.tier,
            image_url=body.imageUrl,
            image_urls=body.imageUrls,
            view_slots=slots,
            multi_image_mode=body.multiImageMode,
            soft_input=body.softInput,
            soft_input_strength=body.softInputStrength,
            texture_mode=body.textureMode,
            prompt=body.prompt,
            seed=body.seed,
        )
    except Text2ImageNotConfiguredError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str, tier: TierName = DEFAULT_PRESET) -> dict:
    try:
        return get_job(job_id, tier=tier)
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
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
