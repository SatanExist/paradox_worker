"""
RunPod handler: image URL -> TRELLIS.2 -> GLB on volume (optional R2 URL / base64).

Separate from worker.py (TRELLIS v1 / CUDA 11.8).
Deploy via Dockerfile.trellis2 on a dedicated 24GB+ endpoint.
"""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import tempfile
import time
import traceback
import urllib.request
from pathlib import Path

import runpod
import torch
from PIL import Image

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("ATTN_BACKEND", "sdpa")
os.environ.setdefault("SPARSE_ATTN_BACKEND", "xformers")
os.environ.setdefault("SPARSE_CONV_BACKEND", "flex_gemm")
os.environ.setdefault("HF_HOME", "/runpod-volume/huggingface_cache")

pipeline = None

DEFAULT_PIPELINE_TYPE = "1024_cascade"
DEFAULT_TEXTURE_SIZE = 2048
DEFAULT_DECIMATION_TARGET = 500_000
DEFAULT_SEED = 1
NVDIFFRAST_FACE_LIMIT = 16_777_216
DEFAULT_OUTPUT_DIR = "/runpod-volume/outputs"
# Keep JSON responses under typical RunPod status payload limits.
DEFAULT_BASE64_MAX_BYTES = 5 * 1024 * 1024

VALID_PIPELINE_TYPES = frozenset({"512", "1024", "1024_cascade", "1536_cascade"})
VALID_TEXTURE_SIZES = frozenset({1024, 2048, 4096})
VALID_TEXTURE_MODES = frozenset({"clay", "textured"})
DEFAULT_TEXTURE_MODE = "clay"


def _runpod_billing_metadata(handler_ms: dict) -> dict:
    gpu_type = None
    for key in (
        "RUNPOD_WEBHOOK_POST_OUTPUT",
        "RUNPOD_WEBHOOK_GET_JOB",
        "RUNPOD_WEBHOOK_PING",
    ):
        url = os.environ.get(key, "")
        if "?gpu=" in url:
            gpu_type = url.split("?gpu=", 1)[1].split("&", 1)[0].replace("+", " ")
            break
    return {
        "gpu_type": gpu_type,
        "gpu_pool": os.environ.get("RUNPOD_GPU_SIZE"),
        "datacenter": os.environ.get("RUNPOD_DC_ID"),
        "worker_id": os.environ.get("RUNPOD_POD_ID"),
        "handler_ms": handler_ms,
        "worker_variant": "trellis2",
    }


def _coerce_int(value, default: int, *, min_val: int, max_val: int) -> int:
    if value is None:
        return default
    try:
        out = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_val, min(max_val, out))


def _generation_params(job_input: dict) -> dict:
    pipeline_type = job_input.get("pipeline_type") or DEFAULT_PIPELINE_TYPE
    if pipeline_type not in VALID_PIPELINE_TYPES:
        pipeline_type = DEFAULT_PIPELINE_TYPE

    texture_mode = str(job_input.get("texture_mode") or DEFAULT_TEXTURE_MODE).strip().lower()
    if texture_mode not in VALID_TEXTURE_MODES:
        texture_mode = DEFAULT_TEXTURE_MODE

    texture_size = DEFAULT_TEXTURE_SIZE
    if texture_mode == "textured":
        texture_size = _coerce_int(
            job_input.get("texture_size"),
            DEFAULT_TEXTURE_SIZE,
            min_val=1024,
            max_val=4096,
        )
        if texture_size not in VALID_TEXTURE_SIZES:
            texture_size = min(VALID_TEXTURE_SIZES, key=lambda x: abs(x - texture_size))

    decimation_target = _coerce_int(
        job_input.get("decimation_target"),
        DEFAULT_DECIMATION_TARGET,
        min_val=50_000,
        max_val=1_000_000,
    )
    seed = _coerce_int(job_input.get("seed"), DEFAULT_SEED, min_val=0, max_val=2**31 - 1)
    preprocess_image = bool(job_input.get("preprocess_image", True))
    remesh = bool(job_input.get("remesh", True))
    verbose = bool(job_input.get("verbose", True))

    return {
        "pipeline_type": pipeline_type,
        "texture_mode": texture_mode,
        "texture_size": texture_size,
        "decimation_target": decimation_target,
        "seed": seed,
        "preprocess_image": preprocess_image,
        "remesh": remesh,
        "verbose": verbose,
    }


def _rewrite_pipeline_json(model_path: str) -> None:
    """Rewrite TRELLIS.2 pipeline.json for RunPod: local DINOv3 + non-gated rembg."""
    import json
    from pathlib import Path

    pipeline_json = Path(model_path) / "pipeline.json"
    if not pipeline_json.is_file():
        print(f"pipeline.json not found under {model_path}; skip rewrites")
        return

    data = json.loads(pipeline_json.read_text(encoding="utf-8"))
    args = data.get("args") or data
    changed = False

    # DINOv3: Meta/HF gated — use converted local weights on the network volume.
    dinov3_path = os.environ.get(
        "TRELLIS2_DINOV3_PATH",
        "/runpod-volume/dinov3-vitl16-pretrain-lvd1689m",
    )
    root = Path(dinov3_path)
    image_cond = args.get("image_cond_model")
    if isinstance(image_cond, dict) and (root / "config.json").is_file():
        image_args = image_cond.setdefault("args", {})
        old = image_args.get("model_name")
        image_args["model_name"] = str(root)
        print(f"DINOv3 model_name: {old!r} -> {root}")
        changed = True
    elif isinstance(image_cond, dict):
        print(f"DINOv3 local path missing or incomplete: {root}")

    # rembg: briaai/RMBG-2.0 is gated + CC BY-NC — prefer public BiRefNet for POC/commercial.
    rembg_model = args.get("rembg_model")
    rembg_id = os.environ.get("TRELLIS2_REMBG_MODEL", "ZhengPeng7/BiRefNet")
    if isinstance(rembg_model, dict):
        rembg_args = rembg_model.setdefault("args", {})
        old_rembg = rembg_args.get("model_name")
        if old_rembg != rembg_id:
            rembg_args["model_name"] = rembg_id
            print(f"rembg model_name: {old_rembg!r} -> {rembg_id!r}")
            changed = True

    if changed:
        pipeline_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_model():
    global pipeline
    build_sha = os.environ.get("PARADOX_BUILD_SHA", "unknown")
    print(f"paradox_worker trellis2 image build: {build_sha}")

    if pipeline is not None:
        return

    print("Loading TRELLIS.2-4B onto network volume cache...")
    from huggingface_hub import snapshot_download
    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    model_id = os.environ.get("TRELLIS2_MODEL_ID", "microsoft/TRELLIS.2-4B")
    model_path = snapshot_download(
        model_id,
        local_dir="/runpod-volume/trellis2-weights",
    )
    _rewrite_pipeline_json(model_path)

    pipeline = Trellis2ImageTo3DPipeline.from_pretrained(model_path)
    pipeline.cuda()
    print("TRELLIS.2 pipeline ready in VRAM.")


def _download_image(image_url: str) -> str:
    req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_img:
        with urllib.request.urlopen(req) as response:
            temp_img.write(response.read())
        return temp_img.name


def _mesh_to_clay_glb(mesh, gen_params: dict):
    """Remesh/simplify without UV unwrap or texture bake — solid gray clay GLB."""
    import cumesh
    import numpy as np
    import trimesh

    verbose = gen_params["verbose"]
    remesh = gen_params["remesh"]
    decimation_target = gen_params["decimation_target"]
    aabb = torch.tensor(
        [[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        dtype=torch.float32,
        device=mesh.vertices.device if hasattr(mesh.vertices, "device") else "cuda",
    )

    vertices = mesh.vertices.cuda()
    faces = mesh.faces.cuda()
    cm = cumesh.CuMesh()
    cm.init(vertices, faces)
    cm.fill_holes(max_hole_perimeter=3e-2)
    if verbose:
        print(f"Clay after fill_holes: {cm.num_vertices} verts, {cm.num_faces} faces")

    if remesh:
        voxel_size = mesh.voxel_size
        if isinstance(voxel_size, float):
            voxel_size_t = torch.tensor(
                [voxel_size, voxel_size, voxel_size],
                dtype=torch.float32,
                device=vertices.device,
            )
        elif not isinstance(voxel_size, torch.Tensor):
            voxel_size_t = torch.tensor(
                voxel_size, dtype=torch.float32, device=vertices.device
            )
        else:
            voxel_size_t = voxel_size.to(device=vertices.device, dtype=torch.float32)
        grid_size = ((aabb[1] - aabb[0]) / voxel_size_t).round().int()
        verts_now, faces_now = cm.read()
        bvh = cumesh.cuBVH(verts_now, faces_now)
        remesh_band = 1.0
        remesh_project = 0.0
        center = aabb.mean(dim=0)
        scale = (aabb[1] - aabb[0]).max().item()
        resolution = grid_size.max().item()
        cm.init(
            *cumesh.remeshing.remesh_narrow_band_dc(
                verts_now,
                faces_now,
                center=center,
                scale=(resolution + 3 * remesh_band) / resolution * scale,
                resolution=resolution,
                band=remesh_band,
                project_back=remesh_project,
                verbose=verbose,
                bvh=bvh,
            )
        )
        if verbose:
            print(f"Clay after remesh: {cm.num_vertices} verts, {cm.num_faces} faces")
        cm.simplify(decimation_target, verbose=verbose)
    else:
        cm.simplify(decimation_target * 3, verbose=verbose)
        cm.remove_duplicate_faces()
        cm.repair_non_manifold_edges()
        cm.remove_small_connected_components(1e-5)
        cm.fill_holes(max_hole_perimeter=3e-2)
        cm.simplify(decimation_target, verbose=verbose)
        cm.remove_duplicate_faces()
        cm.repair_non_manifold_edges()
        cm.remove_small_connected_components(1e-5)
        cm.fill_holes(max_hole_perimeter=3e-2)
        cm.unify_face_orientations()

    if verbose:
        print(f"Clay final: {cm.num_vertices} verts, {cm.num_faces} faces")

    out_vertices, out_faces = cm.read()
    vertices_np = out_vertices.detach().cpu().numpy()
    faces_np = out_faces.detach().cpu().numpy()
    # Same Y/Z swap as o_voxel.to_glb for GLB orientation
    vertices_np = vertices_np.copy()
    vertices_np[:, 1], vertices_np[:, 2] = (
        vertices_np[:, 2].copy(),
        -vertices_np[:, 1].copy(),
    )

    material = trimesh.visual.material.PBRMaterial(
        baseColorFactor=np.array([180, 180, 180, 255], dtype=np.uint8),
        metallicFactor=0.0,
        roughnessFactor=0.85,
        doubleSided=False if remesh else True,
    )
    return trimesh.Trimesh(
        vertices=vertices_np,
        faces=faces_np,
        process=False,
        visual=trimesh.visual.TextureVisuals(material=material),
    )


def _mesh_to_glb(mesh, gen_params: dict):
    mesh.simplify(NVDIFFRAST_FACE_LIMIT)

    if gen_params.get("texture_mode", DEFAULT_TEXTURE_MODE) == "clay":
        return _mesh_to_clay_glb(mesh, gen_params)

    import o_voxel

    return o_voxel.postprocess.to_glb(
        vertices=mesh.vertices,
        faces=mesh.faces,
        attr_volume=mesh.attrs,
        coords=mesh.coords,
        attr_layout=mesh.layout,
        voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=gen_params["decimation_target"],
        texture_size=gen_params["texture_size"],
        remesh=gen_params["remesh"],
        remesh_band=1,
        remesh_project=0,
        verbose=gen_params["verbose"],
    )


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _upload_r2(local_path: str, object_key: str) -> str | None:
    """Upload to Cloudflare R2 (S3 API). Returns public URL or None if not configured."""
    endpoint = os.environ.get("R2_ENDPOINT_URL", "").strip()
    bucket = os.environ.get("R2_BUCKET", "").strip()
    access_key = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
    public_base = os.environ.get("R2_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not all([endpoint, bucket, access_key, secret_key, public_base]):
        return None

    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        print("boto3 not installed; skip R2 upload")
        return None

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=os.environ.get("R2_REGION", "auto"),
        config=Config(signature_version="s3v4"),
    )
    extra = {"ContentType": "model/gltf-binary"}
    client.upload_file(local_path, bucket, object_key, ExtraArgs=extra)
    url = f"{public_base}/{object_key}"
    print(f"Uploaded GLB to R2: {url}")
    return url


def _deliver_glb(temp_glb_path: str, job_id: str, *, return_base64: bool) -> dict:
    """
    Persist GLB off the JSON hot path:
      1) always copy to network volume
      2) optional R2 -> model_url
      3) optional base64 only when small enough for RunPod status API
    """
    output_dir = Path(os.environ.get("TRELLIS2_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in job_id) or "job"
    dest = output_dir / f"{safe_id}.glb"
    shutil.copy2(temp_glb_path, dest)

    size = dest.stat().st_size
    sha = _sha256_file(str(dest))
    object_key = f"trellis2/{safe_id}.glb"
    model_url = _upload_r2(str(dest), object_key)

    delivery = {
        "model_path": str(dest),
        "model_bytes": size,
        "model_sha256": sha,
        "model_url": model_url,
        "delivery": "r2" if model_url else "volume",
    }

    max_b64 = int(os.environ.get("TRELLIS2_BASE64_MAX_BYTES", str(DEFAULT_BASE64_MAX_BYTES)))
    include_b64 = return_base64 or (model_url is None and size <= max_b64)
    if include_b64 and size <= max_b64:
        with open(dest, "rb") as handle:
            delivery["model_base64"] = base64.b64encode(handle.read()).decode("utf-8")
    elif return_base64 and size > max_b64:
        delivery["base64_omitted"] = (
            f"GLB is {size} bytes; exceeds TRELLIS2_BASE64_MAX_BYTES={max_b64}. "
            "Use model_url (R2) or model_path on the network volume."
        )
    elif model_url is None and size > max_b64:
        delivery["base64_omitted"] = (
            f"GLB is {size} bytes; skipped base64 to keep RunPod status payload small. "
            "Configure R2_* env for model_url, or copy model_path from the volume."
        )

    return delivery


def handler(job):
    job_input = job.get("input", {})
    image_url = job_input.get("image_url")
    gen_params = _generation_params(job_input)
    return_base64 = bool(job_input.get("return_base64", False))
    job_id = str(job.get("id") or f"local-{int(time.time())}")

    if not image_url:
        return {"error": "Missing image_url in job input"}

    img_path = None
    glb_path = None

    try:
        t0 = time.perf_counter()
        handler_ms = {}

        t_load = time.perf_counter()
        load_model()
        handler_ms["model_load_ms"] = int((time.perf_counter() - t_load) * 1000)

        print(
            "TRELLIS.2 params: "
            f"pipeline_type={gen_params['pipeline_type']}, "
            f"texture_mode={gen_params['texture_mode']}, "
            f"texture_size={gen_params['texture_size']}, "
            f"decimation_target={gen_params['decimation_target']}, "
            f"seed={gen_params['seed']}"
        )

        print(f"Downloading image: {image_url}")
        img_path = _download_image(image_url)
        image = Image.open(img_path)

        t_infer = time.perf_counter()
        meshes = pipeline.run(
            image,
            seed=gen_params["seed"],
            preprocess_image=gen_params["preprocess_image"],
            pipeline_type=gen_params["pipeline_type"],
        )
        handler_ms["inference_ms"] = int((time.perf_counter() - t_infer) * 1000)

        mesh = meshes[0]

        t_glb = time.perf_counter()
        glb = _mesh_to_glb(mesh, gen_params)

        glb_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".glb")
        glb_path = glb_temp.name
        glb_temp.close()
        if gen_params["texture_mode"] == "clay":
            glb.export(glb_path)
        else:
            glb.export(glb_path, extension_webp=True)
        handler_ms["glb_export_ms"] = int((time.perf_counter() - t_glb) * 1000)

        t_deliver = time.perf_counter()
        delivery = _deliver_glb(glb_path, job_id, return_base64=return_base64)
        handler_ms["deliver_ms"] = int((time.perf_counter() - t_deliver) * 1000)
        handler_ms["total_ms"] = int((time.perf_counter() - t0) * 1000)

        return {
            "status": "success",
            "message": "TRELLIS.2 model generated successfully",
            "generation": gen_params,
            "billing": _runpod_billing_metadata(handler_ms),
            **delivery,
        }

    except Exception as exc:
        tb = traceback.format_exc()
        print(f"CRITICAL ERROR: {exc}")
        print(tb)
        return {"error": f"Generation failed: {exc}"}

    finally:
        if img_path and os.path.exists(img_path):
            os.remove(img_path)
        if glb_path and os.path.exists(glb_path):
            os.remove(glb_path)


runpod.serverless.start({"handler": handler})
