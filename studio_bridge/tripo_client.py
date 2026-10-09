"""Tripo Developers API v3 (server-side only).

  POST /generation/image-to-model
  POST /generation/text-to-model
  POST /generation/multiview-to-model
  GET  /tasks/{task_id}
  Authorization: Bearer $TRIPO_API_KEY

Not the consumer Studio wallet. Do not send the key to the browser.
Do not call image-to-multiview (synth img2mv — frozen).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

API_BASE = "https://openapi.tripo3d.ai/v3"
DEFAULT_TIMEOUT_SEC = 60
PROMPT_MAX_CHARS = 1024

TripoTask = Literal["image", "text", "multiview"]

# Studio slots → Tripo view keys (multiview-to-model).
SLOT_TO_VIEW = {
    "front": "front",
    "side": "left",
    "back": "back",
    "extra": "right",
}


class TripoNotConfiguredError(RuntimeError):
    pass


class TripoHttpError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"Tripo HTTP {status}: {body[:300]}")


@dataclass(frozen=True)
class TripoPreset:
    model: str
    eta_sec: int
    label: str
    blurb: str
    series: Literal["h", "p1", "p2"]
    texture_quality: str = "standard"
    # P2-20260801 only — native quad mesh (API docs).
    quad: bool = False

    @property
    def list_usd(self) -> float:
        """Catalog default: image→3D with this slot's texture preset."""
        return vendor_usd(
            "tripo_p2"
            if self.series == "p2"
            else ("tripo_p1" if self.series == "p1" else "tripo")
        )


TRIPO_PRESETS: dict[str, TripoPreset] = {
    "tripo": TripoPreset(
        model="v3.1-20260211",
        eta_sec=180,
        label="Tripo H3.1",
        blurb="Fast image→3D (H-series). PBR. Not the default.",
        series="h",
        texture_quality="standard",
    ),
    "tripo_p1": TripoPreset(
        model="P1-20260311",
        eta_sec=240,
        label="Tripo P1",
        blurb="P-series low-poly / game mesh. Do not confuse with H3.1.",
        series="p1",
        texture_quality="detailed",
    ),
    "tripo_p2": TripoPreset(
        model="P2-20260801",
        eta_sec=150,
        label="Tripo P2",
        blurb="P2 Preview — game-ready mesh with native quad topology.",
        series="p2",
        texture_quality="detailed",
        quad=True,
    ),
}


def api_key() -> str:
    key = os.getenv("TRIPO_API_KEY", "").strip()
    if not key:
        raise TripoNotConfiguredError("TRIPO_API_KEY is not set")
    return key


def is_configured() -> bool:
    return bool(os.getenv("TRIPO_API_KEY", "").strip())


def _ok_code(code: Any) -> bool:
    return code in (0, "0", 200, "200")


def _request(method: str, url: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key()}",
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=DEFAULT_TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8")
            status = getattr(resp, "status", 200)
    except HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise TripoHttpError(exc.code, err) from exc
    except URLError as exc:
        raise TripoHttpError(502, str(exc.reason or exc)) from exc
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise TripoHttpError(status, f"expected object, got {type(parsed).__name__}")
    return parsed


def _unwrap(body: dict[str, Any], context: str) -> dict[str, Any]:
    if not _ok_code(body.get("code")):
        msg = str(body.get("message") or body.get("msg") or body)[:300]
        raise TripoHttpError(502, f"{context}: {msg}")
    data = body.get("data")
    if not isinstance(data, dict):
        raise TripoHttpError(502, f"{context}: missing data")
    return data


def _preset(engine_id: str) -> TripoPreset:
    preset = TRIPO_PRESETS.get(engine_id)
    if preset is None:
        raise ValueError(f"{engine_id} is not a Tripo engine")
    return preset


def _opt(opts: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in opts and opts[key] is not None:
            return opts[key]
    return default


def _material_flags(opts: dict[str, Any]) -> tuple[bool, bool]:
    material = str(_opt(opts, "material", default="PBR") or "PBR").strip()
    if material not in {"PBR", "Shaded", "None"}:
        material = "PBR"
    texture = material != "None"
    pbr = material == "PBR"
    return texture, pbr


def _texture_quality(engine_id: str, opts: dict[str, Any]) -> str:
    preset = _preset(engine_id)
    raw = str(
        _opt(opts, "textureQuality", "texture_quality", default=preset.texture_quality)
        or preset.texture_quality
    ).strip().lower()
    allowed = {"standard", "detailed"}
    if preset.series in {"h", "p2"}:
        allowed.add("extreme")
    if raw not in allowed:
        return preset.texture_quality
    return raw


def _use_quad(engine_id: str, opts: dict[str, Any]) -> bool:
    preset = _preset(engine_id)
    if not preset.quad:
        return False
    topology = str(_opt(opts, "topology", default="quads") or "quads").strip().lower()
    return topology in {"quads", "quad", "true", "1"}


def _face_limit(engine_id: str, opts: dict[str, Any], *, use_quad: bool) -> int | None:
    override = _opt(opts, "faceLimit", "face_limit")
    if override is not None and str(override).strip():
        try:
            return int(str(override).strip())
        except ValueError as exc:
            raise ValueError(f"invalid face_limit {override!r}") from exc

    face_limits: dict[str, dict[str, tuple[int, int] | int]] = {
        "tripo_p2": {
            "low": (5_000, 8_000),
            "medium": (12_000, 20_000),
            "high": (25_000, 50_000),
        },
        "tripo_p1": {
            "low": 5_000,
            "medium": 12_000,
            "high": 20_000,
        },
        "tripo": {
            # Docs: game-ready 50k–100k; web 10k–50k. Auto (omit) is adaptive up to 1.5M / 2M Ultra.
            "low": 50_000,
            "medium": 100_000,
            "high": 500_000,
        },
    }
    if engine_id == "tripo" and _smart_low_poly(opts):
        # Official H-series: smart_low_poly triangles 500–20,000 (quad 500–10,000; we never send H3 quad).
        face_limits["tripo"] = {
            "low": 5_000,
            "medium": 10_000,
            "high": 20_000,
        }
    table = face_limits.get(engine_id, {})
    face_preset = str(_opt(opts, "facePreset", "face_preset", default="auto") or "auto").strip().lower()
    if face_preset not in table:
        return None
    limit = table[face_preset]
    if isinstance(limit, tuple):
        quad_n, tri_n = limit
        return quad_n if use_quad else tri_n
    return int(limit)


def _optional_int(opts: dict[str, Any], *keys: str, label: str = "seed") -> int | None:
    """Official: omit seed → vendor random. Only send if the user typed a number."""
    raw = _opt(opts, *keys)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return int(str(raw).strip())
    except ValueError as exc:
        raise ValueError(f"invalid Tripo {label} {raw!r}") from exc


def _model_seed(opts: dict[str, Any]) -> int | None:
    return _optional_int(opts, "seed", "modelSeed", "model_seed", label="seed")


def _texture_seed(opts: dict[str, Any]) -> int | None:
    return _optional_int(opts, "textureSeed", "texture_seed", label="texture_seed")


def _smart_low_poly(opts: dict[str, Any]) -> bool:
    """H3 only. Official: +10 cr; best on simple shapes. Not generate_parts."""
    return bool(_opt(opts, "smartLowPoly", "smart_low_poly", default=False))


def generation_knobs(
    engine_id: str,
    *,
    seed: int = 1,
    options: dict[str, Any] | None = None,
    image_only: bool = True,
) -> dict[str, Any]:
    """Shared knobs for image / text / multiview (v3 `model`, not v2 `model_version`).

    Omit official defaults so Tripo applies them: geometry_quality=standard,
    texture_alignment=original_image, orientation=default, model_seed=random,
    auto_size=false. `seed=` on this function is unused — Studio seed lives
    in options.seed / options.textureSeed.
    """
    del seed  # gateway jobSeed must not become Tripo model_seed
    preset = _preset(engine_id)
    opts = options or {}
    texture, pbr = _material_flags(opts)
    use_quad = _use_quad(engine_id, opts)
    tq = _texture_quality(engine_id, opts)

    body: dict[str, Any] = {
        "model": preset.model,
        "texture": texture,
        "pbr": pbr if texture else False,
    }
    # Docs: pbr=true forces texture=true. Clay = texture=false, pbr=false.
    # standard + texture=false + pbr=false is rejected — omit texture_quality on clay.
    if texture:
        body["texture_quality"] = tq

    model_seed = _model_seed(opts)
    texture_seed = _texture_seed(opts)
    if model_seed is not None:
        body["model_seed"] = model_seed
    if texture:
        if texture_seed is not None:
            body["texture_seed"] = texture_seed
        elif model_seed is not None:
            body["texture_seed"] = model_seed

    # H3 quad=true forces FBX — never send on H3/P1. P2 only.
    if preset.quad:
        body["quad"] = bool(use_quad)

    face_limit = _face_limit(engine_id, opts, use_quad=use_quad)
    if face_limit is not None:
        body["face_limit"] = face_limit

    # Official: auto_size only on textured models (P1 / P2 / H3 docs).
    if texture and bool(_opt(opts, "autoSize", "auto_size", default=False)):
        body["auto_size"] = True

    if image_only:
        if texture:
            align = str(
                _opt(opts, "textureAlign", "texture_alignment", default="original_image")
                or "original_image"
            ).strip()
            if align == "geometry":
                body["texture_alignment"] = align
            orient = str(_opt(opts, "orientation", default="default") or "default").strip()
            if orient == "align_image":
                # Official: only takes effect when texture=true.
                body["orientation"] = orient
        if bool(_opt(opts, "autofix", "enable_image_autofix", default=False)):
            body["enable_image_autofix"] = True

    if preset.series == "h":
        smart = _smart_low_poly(opts)
        gq = str(
            _opt(opts, "geometryQuality", "geometry_quality", default="standard") or "standard"
        ).strip().lower()
        if smart:
            body["smart_low_poly"] = True
        elif gq == "detailed":
            body["geometry_quality"] = "detailed"

    return body


def vendor_credits(
    engine_id: str,
    *,
    task: TripoTask = "image",
    options: dict[str, Any] | None = None,
) -> tuple[int, tuple[str, ...]]:
    """Stacked Tripo PAYG credits (1 cr = $0.01).

    H3 base: docs.tripo3d.ai/get-started/pricing.html
      image/multiview clay 20 / +tex 30; text clay 10 / +tex 20.
    H3 add-ons (same page + H3 image-to-model):
      texture_quality=detailed +10; geometry_quality=detailed +20;
      smart_low_poly +10. quad=+5 but we never send it (FBX).
    P1 is all-in (H add-ons do not apply). P2: 100/110/120/130 changelog.
    """
    preset = _preset(engine_id)
    opts = options or {}
    texture, _pbr = _material_flags(opts)
    tq = _texture_quality(engine_id, opts) if texture else "standard"
    lines: list[str] = []

    if preset.series == "h":
        n = {"text": 10, "image": 20, "multiview": 20}[task]
        smart = _smart_low_poly(opts)
        if texture:
            n += 10
            lines.append(f"{task} + tex {n}")
            if tq == "detailed":
                n += 10
                lines.append("HD tex +10")
            elif tq == "extreme":
                n += 20
                lines.append("8K tex +20")
        else:
            lines.append(f"{task} {n}")
        gq = str(
            _opt(opts, "geometryQuality", "geometry_quality", default="standard") or "standard"
        ).strip().lower()
        # Ultra (~2M) vs smart low-poly (500–20k) — don't stack. Smart wins if both set.
        if smart:
            n += 10
            lines.append("smart low-poly +10")
        elif gq == "detailed":
            n += 20
            lines.append("Ultra geo +20")
        return n, tuple(lines)

    if preset.series == "p1":
        n = {"text": 30, "image": 40, "multiview": 40}[task]
        if texture:
            n += 10
            lines.append(f"{task} + tex {n}")
            if tq == "detailed":
                n += 10
                lines.append("HD tex +10")
        else:
            lines.append(f"{task} {n}")
        return n, tuple(lines)

    n = 100
    lines.append(f"{task} 100")
    if texture:
        n = {"standard": 110, "detailed": 120, "extreme": 130}.get(tq, 110)
        lines.append(f"{tq} tex +{n - 100}")
    return n, tuple(lines)


def task_credits_consumed(task: dict[str, Any]) -> float | None:
    """Official poll field: v3 `credits_consumed`, legacy `consumed_credit`."""
    for key in ("credits_consumed", "consumed_credit", "consumed_credits"):
        raw = task.get(key)
        if raw is None or raw == "":
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def vendor_usd(
    engine_id: str,
    *,
    task: TripoTask = "image",
    options: dict[str, Any] | None = None,
) -> float:
    """PAYG USD. PolyLab user price is ≥2.5× in credits.py."""
    n, _lines = vendor_credits(engine_id, task=task, options=options)
    return round(n * 0.01, 2)


def tripo_view_inputs(
    view_slots: dict[str, str | None] | None,
    image_urls: list[str] | None = None,
) -> list[dict[str, str]]:
    """Named views for POST /generation/multiview-to-model. Front required, min 2."""
    slots: dict[str, str] = {}
    if view_slots:
        for studio_key, view_key in SLOT_TO_VIEW.items():
            val = (view_slots.get(studio_key) or "").strip()
            if val:
                slots[view_key] = val
    urls = [u.strip() for u in (image_urls or []) if isinstance(u, str) and u.strip()]
    if "front" not in slots and urls:
        slots["front"] = urls[0]
        extras = ("left", "back", "right")
        for url, key in zip(urls[1:], extras):
            slots.setdefault(key, url)
    if "front" not in slots:
        raise ValueError("Tripo multiview needs a front image")
    if len(slots) < 2:
        raise ValueError("Tripo multiview needs at least 2 real photos")
    return [{key: slots[key]} for key in ("front", "left", "back", "right") if key in slots]


def filled_view_count(
    view_slots: dict[str, str | None] | None,
    image_urls: list[str] | None = None,
) -> int:
    if view_slots:
        n = sum(1 for key in SLOT_TO_VIEW if (view_slots.get(key) or "").strip())
        if n:
            return n
    return len([u for u in (image_urls or []) if isinstance(u, str) and u.strip()])


def build_image_payload(
    engine_id: str,
    *,
    image_url: str,
    seed: int = 1,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = (image_url or "").strip()
    if not url:
        raise ValueError("image URL required")
    body = generation_knobs(engine_id, seed=seed, options=options, image_only=True)
    body["input"] = url
    return body


def build_text_payload(
    engine_id: str,
    *,
    prompt: str,
    seed: int = 1,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = (prompt or "").strip()
    if not text:
        raise ValueError("prompt is required for Tripo text mode")
    if len(text) > PROMPT_MAX_CHARS:
        text = text[:PROMPT_MAX_CHARS]
    body = generation_knobs(engine_id, seed=seed, options=options, image_only=False)
    body["prompt"] = text
    return body


def build_multiview_payload(
    engine_id: str,
    *,
    view_slots: dict[str, str | None] | None = None,
    image_urls: list[str] | None = None,
    seed: int = 1,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = generation_knobs(engine_id, seed=seed, options=options, image_only=True)
    body["inputs"] = tripo_view_inputs(view_slots, image_urls)
    return body


def _submit(path: str, body: dict[str, Any], context: str) -> dict[str, Any]:
    data = _unwrap(
        _request("POST", f"{API_BASE}/generation/{path}", payload=body),
        context,
    )
    task_id = str(data.get("task_id") or "").strip()
    if not task_id:
        raise TripoHttpError(502, f"missing task_id: {data}")
    return {"task_id": task_id, "model": body.get("model"), "options": body}


def submit_image_to_3d(
    engine_id: str,
    *,
    image_urls: list[str],
    seed: int = 1,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not image_urls:
        raise ValueError("image URL required")
    body = build_image_payload(
        engine_id, image_url=image_urls[0], seed=seed, options=options
    )
    return _submit("image-to-model", body, "image-to-model")


def submit_text_to_3d(
    engine_id: str,
    *,
    prompt: str,
    seed: int = 1,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = build_text_payload(engine_id, prompt=prompt, seed=seed, options=options)
    return _submit("text-to-model", body, "text-to-model")


def submit_multiview_to_3d(
    engine_id: str,
    *,
    view_slots: dict[str, str | None] | None = None,
    image_urls: list[str] | None = None,
    seed: int = 1,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = build_multiview_payload(
        engine_id,
        view_slots=view_slots,
        image_urls=image_urls,
        seed=seed,
        options=options,
    )
    return _submit("multiview-to-model", body, "multiview-to-model")


def query_task(task_id: str) -> dict[str, Any]:
    tid = quote((task_id or "").strip(), safe="")
    if not tid:
        raise ValueError("task_id required")
    return _unwrap(_request("GET", f"{API_BASE}/tasks/{tid}"), "task")


def query_balance() -> dict[str, Any]:
    return _unwrap(_request("GET", f"{API_BASE}/account/balance"), "balance")


def pick_glb(task: dict[str, Any]) -> tuple[str | None, str | None]:
    """Pick a downloadable model URL + poster.

    Prefers GLB; falls back to FBX if P2 quad (or convert) returns FBX only.
    Studio viewer still requires GLB — gateway fails closed on FBX.
    """
    output = task.get("output") if isinstance(task.get("output"), dict) else {}
    poster = None
    for key in ("rendered_image_url", "rendered_image", "preview"):
        val = output.get(key)
        if isinstance(val, str) and val.startswith("https://"):
            poster = val
            break
        if isinstance(val, dict):
            url = val.get("url")
            if isinstance(url, str) and url.startswith("https://"):
                poster = url
                break
    glb = None
    fbx = None
    for key in ("pbr_model", "model_url", "model", "base_model"):
        val = output.get(key)
        url = None
        if isinstance(val, str):
            url = val
        elif isinstance(val, dict):
            maybe = val.get("url")
            if isinstance(maybe, str):
                url = maybe
        if not url or not url.startswith("https://"):
            continue
        path = url.split("?", 1)[0].lower()
        if path.endswith(".fbx"):
            fbx = fbx or url
            continue
        glb = url
        if path.endswith(".glb") or key in {"pbr_model", "model_url"}:
            break
    return glb or fbx, poster


def map_tripo_status(raw: str | None) -> str:
    status = (raw or "").strip().lower()
    if status in {"queued", "pending", "waiting"}:
        return "queued"
    if status in {"running", "processing", "in_progress"}:
        return "running"
    if status == "success":
        return "ready"
    return "failed"
