"""Minimal HTTP API for AI_MESH Studio integration (image/text → T2 RunPod)."""

from __future__ import annotations

import mimetypes
import os
import sys
from pathlib import Path
from typing import Literal

from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
mimetypes.add_type("text/javascript", ".mjs")

from studio_bridge.product_multi_ux import studio_copy_bundle  # noqa: E402
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

app = FastAPI(title="AI_MESH Studio Bridge (POC)", version="0.5.0")

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


@app.get("/api/proxy-glb")
def proxy_glb(url: str) -> StreamingResponse:
    """Local-only helper so the browser can inspect an R2/https GLB."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(status_code=400, detail="url must be https")
    request = Request(url, headers={"User-Agent": "paradox-studio-lab"})
    try:
        upstream = urlopen(request, timeout=90)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    content_type = upstream.headers.get("Content-Type") or "model/gltf-binary"

    def _chunks():
        try:
            while True:
                chunk = upstream.read(256 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            upstream.close()

    return StreamingResponse(_chunks(), media_type=content_type)


@app.get("/api/product-copy")
def product_copy() -> dict:
    """Studio copy + slot contract (productMultiUx path A)."""
    return studio_copy_bundle()


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


def main() -> None:
    import uvicorn

    host = os.getenv("STUDIO_API_HOST", "127.0.0.1")
    port = int(os.getenv("STUDIO_API_PORT", "8787"))
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
