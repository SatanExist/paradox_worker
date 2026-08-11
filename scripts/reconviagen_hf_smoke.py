#!/usr/bin/env python3
"""Smoke test: ReconViaGen v0.5 on Hugging Face Space (Gradio 6 API).

Uses stdlib HTTP only (no gradio_client). Two calls in one session:
  1) /image_to_3d
  2) /extract_glb → download GLB

Space: https://stable-x-reconviagen-v0-5.hf.space/
API docs: https://stable-x-reconviagen-v0-5.hf.space/?view=api
OpenAPI: https://stable-x-reconviagen-v0-5.hf.space/gradio_api/openapi.json

Example:
  python scripts/reconviagen_hf_smoke.py \\
    --image preview_textures/gemini_mv/front.png \\
    --image preview_textures/gemini_mv/back.png \\
    --seed 42 --pipeline 1024_cascade \\
    --save preview_textures/reconviagen/r_hf_armor.glb
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPACE = "https://stable-x-reconviagen-v0-5.hf.space"
DEFAULT_STRATEGY = "adaptive_guidance_weight"


def _file_ref(path_or_url: str, *, upload_dir: str | None = None) -> dict:
    """Build Gradio FileData dict. Local paths must be uploaded first."""
    name = Path(path_or_url).name
    if path_or_url.startswith(("http://", "https://")):
        return {
            "path": path_or_url,
            "url": path_or_url,
            "orig_name": name,
            "meta": {"_type": "gradio.FileData"},
        }
    if not upload_dir:
        raise ValueError(f"Local file needs upload: {path_or_url}")
    server_path = f"{upload_dir.rstrip('/')}/{name}"
    return {
        "path": server_path,
        "url": server_path,
        "orig_name": name,
        "meta": {"_type": "gradio.FileData"},
    }


def _upload_file(base: str, local_path: Path) -> str:
    """Upload one file; return server directory prefix for FileData.path."""
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    mime = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{local_path.name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode() + local_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{base}/gradio_api/upload",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "paradox_worker/reconviagen_hf_smoke",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        uploaded = json.load(resp)
    # Gradio returns list of server paths
    if isinstance(uploaded, list) and uploaded:
        return str(Path(uploaded[0]).parent).replace("\\", "/")
    raise RuntimeError(f"Unexpected upload response: {uploaded!r}")


def _call(
    base: str,
    api_name: str,
    data: list,
    session_hash: str,
    *,
    timeout_sec: float = 20 * 60,
    poll_sec: float = 3.0,
) -> list:
    """POST /gradio_api/call/{api_name} and poll until complete."""
    payload = {"data": data, "session_hash": session_hash}
    req = urllib.request.Request(
        f"{base}/gradio_api/call/{api_name}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "paradox_worker/reconviagen_hf_smoke"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        meta = json.load(resp)
    event_id = meta.get("event_id")
    if not event_id:
        raise RuntimeError(f"No event_id from {api_name}: {meta}")

    deadline = time.time() + timeout_sec
    url = f"{base}/gradio_api/call/{api_name}/{event_id}"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=max(30, poll_sec + 5)) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (503, 502, 504):
                time.sleep(poll_sec)
                continue
            raise
        # SSE: lines like "event: complete\ndata: [...]"
        for line in raw.splitlines():
            if line.startswith("data: "):
                chunk = line[6:]
                if chunk == "[DONE]":
                    continue
                try:
                    parsed = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, dict) and parsed.get("error"):
                    raise RuntimeError(parsed["error"])
        time.sleep(poll_sec)
    raise TimeoutError(f"{api_name} timed out after {timeout_sec}s")


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "paradox_worker/reconviagen_hf_smoke"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        dest.write_bytes(resp.read())


def main() -> int:
    p = argparse.ArgumentParser(description="ReconViaGen HF Space smoke (Gradio API)")
    p.add_argument("--space", default=DEFAULT_SPACE, help="Gradio Space base URL")
    p.add_argument("--image", action="append", required=True, help="Local path or https URL (repeat)")
    p.add_argument("--strategy", default=DEFAULT_STRATEGY)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--pipeline", default="1024_cascade", choices=["512", "1024", "1024_cascade", "1536_cascade"])
    p.add_argument("--ss-source", default="mesh", choices=["direct", "mesh", "mvtrellis2"])
    p.add_argument("--decimation", type=int, default=700_000)
    p.add_argument("--texture-size", type=int, default=2048)
    p.add_argument("--save", type=Path, required=True, help="Output GLB path")
    p.add_argument("--timeout", type=float, default=25 * 60)
    args = p.parse_args()

    base = args.space.rstrip("/")
    session = uuid.uuid4().hex[:12]
    print(f"Space: {base}")
    print(f"Session: {session}")
    print(f"Images: {args.image}")

    upload_dir: str | None = None
    refs: list[dict] = []
    for img in args.image:
        if img.startswith(("http://", "https://")):
            refs.append(_file_ref(img))
        else:
            local = Path(img)
            if not local.is_file():
                print(f"Not found: {local}", file=sys.stderr)
                return 1
            if upload_dir is None:
                print(f"Uploading {local.name}...")
                upload_dir = _upload_file(base, local)
            else:
                _upload_file(base, local)
            refs.append(_file_ref(str(local.resolve()), upload_dir=upload_dir))

    # Gradio Gallery: list of images (one row)
    gallery = refs

    print("Calling image_to_3d (may take several minutes on ZeroGPU queue)...")
    _call(
        base,
        "image_to_3d",
        [
            gallery,
            args.strategy,
            args.seed,
            args.pipeline,
            args.ss_source,
            7.5, 0.7, 12, 5.0,  # ss stage
            7.5, 0.5, 12, 3.0,  # slat stage (ReconViaGen)
            7.5, 0.5, 8, 3.0,   # shape slat T2
            1.0, 0.0, 8, 3.0,   # tex slat T2
        ],
        session,
        timeout_sec=args.timeout,
    )
    print("image_to_3d done. Calling extract_glb...")
    out = _call(
        base,
        "extract_glb",
        [args.decimation, args.texture_size],
        session,
        timeout_sec=min(args.timeout, 10 * 60),
    )
    print("extract_glb result keys/types:", type(out), len(out) if isinstance(out, list) else out)

    # Returns: [Extracted GLB preview, Download GLB file ref]
    glb_ref = None
    if isinstance(out, list):
        for item in reversed(out):
            if isinstance(item, dict) and (item.get("url") or item.get("path")):
                glb_ref = item
                break
    if not glb_ref:
        print("Could not find GLB in response:", json.dumps(out, indent=2)[:2000], file=sys.stderr)
        return 1

    url = glb_ref.get("url") or glb_ref.get("path")
    if not url.startswith("http"):
        url = f"{base}/gradio_api/file={url.lstrip('/')}"
    print(f"Downloading GLB from {url}")
    _download(url, args.save)
    print(f"Saved -> {args.save.resolve()} ({args.save.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
