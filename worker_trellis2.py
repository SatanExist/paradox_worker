"""
RunPod handler: image URL -> TRELLIS.2 -> GLB on volume (optional R2 URL / base64).

Separate from worker.py (TRELLIS v1 / CUDA 11.8).
Deploy via Dockerfile.trellis2 on a dedicated 24GB+ endpoint.
"""

from __future__ import annotations

import base64
import copy
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
VALID_MULTI_IMAGE_MODES = frozenset({"stochastic", "multidiffusion"})
VALID_QUALITY_TIERS = frozenset({"preview", "quality", "ultra"})
DEFAULT_TEXTURE_MODE = "clay"
DEFAULT_MULTI_IMAGE_MODE = "multidiffusion"
DEFAULT_QUALITY_TIER = "quality"
MAX_MULTI_IMAGES = 8

# Product tiers (Meshy-like): default = quality; ultra = rt6 best-effort + OOM downgrade.
# Explicit job_input knobs still override after the tier preset is applied.
TIER_PRESETS: dict[str, dict] = {
    "preview": {
        "pipeline_type": "512",
        "decimation_target": 300_000,
        "preprocess_image": True,
        "remesh": True,
        "max_num_tokens": 49_152,
        "sparse_structure_sampler_params": {
            "steps": 12,
            "guidance_strength": 7.5,
            "guidance_rescale": 0.7,
            "rescale_t": 5.0,
            "guidance_interval": [0.6, 1.0],
        },
        "shape_slat_sampler_params": {
            "steps": 12,
            "guidance_strength": 7.5,
            "guidance_rescale": 0.5,
            "rescale_t": 3.0,
            "guidance_interval": [0.6, 1.0],
        },
    },
    "quality": {
        "pipeline_type": "1024_cascade",
        "decimation_target": 500_000,
        "preprocess_image": True,
        "remesh": True,
        "max_hole_perimeter": 0.1,
        "max_num_tokens": 49_152,
        "sparse_structure_sampler_params": {
            "steps": 12,
            "guidance_strength": 7.5,
            "guidance_rescale": 0.7,
            "rescale_t": 5.0,
            "guidance_interval": [0.6, 1.0],
        },
        "shape_slat_sampler_params": {
            "steps": 12,
            "guidance_strength": 7.5,
            "guidance_rescale": 0.5,
            "rescale_t": 3.0,
            "guidance_interval": [0.6, 1.0],
        },
    },
    "ultra": {
        # Product front rt6 recipe.
        "pipeline_type": "1536_cascade",
        "decimation_target": 700_000,
        "preprocess_image": True,
        "remesh": True,
        "max_num_tokens": 65_536,
        "sparse_structure_sampler_params": {
            "steps": 50,
            "guidance_strength": 8.0,
            "guidance_rescale": 0.7,
            "rescale_t": 6.0,
            "guidance_interval": [0.0, 1.0],
        },
        "shape_slat_sampler_params": {
            "steps": 50,
            "guidance_strength": 8.5,
            "guidance_rescale": 0.5,
            "rescale_t": 6.0,
            "guidance_interval": [0.0, 1.0],
        },
    },
}


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


def _coerce_float(value, default: float, *, min_val: float, max_val: float) -> float:
    if value is None:
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return max(min_val, min(max_val, out))


def _sampler_params_from_input(raw, defaults: dict) -> dict:
    """Merge job sampler overrides into TRELLIS.2 sampler kwargs (steps/guidance/…)."""
    out = dict(defaults)
    if not isinstance(raw, dict):
        return out
    if "steps" in raw:
        out["steps"] = _coerce_int(raw.get("steps"), out["steps"], min_val=1, max_val=100)
    if "guidance_strength" in raw:
        out["guidance_strength"] = _coerce_float(
            raw.get("guidance_strength"), out["guidance_strength"], min_val=0.0, max_val=20.0
        )
    if "guidance_rescale" in raw:
        out["guidance_rescale"] = _coerce_float(
            raw.get("guidance_rescale"), out["guidance_rescale"], min_val=0.0, max_val=1.0
        )
    if "rescale_t" in raw:
        out["rescale_t"] = _coerce_float(
            raw.get("rescale_t"), out["rescale_t"], min_val=1.0, max_val=6.0
        )
    if "guidance_interval" in raw:
        interval = _coerce_guidance_interval(
            raw.get("guidance_interval"), out.get("guidance_interval", [0.6, 1.0])
        )
        if interval is not None:
            out["guidance_interval"] = interval
    return out


def _coerce_guidance_interval(raw, default):
    """Parse [lo, hi] in [0, 1] with lo <= hi (TRELLIS.2 CFG window on t)."""
    fallback = list(default) if isinstance(default, (list, tuple)) and len(default) == 2 else [0.6, 1.0]
    if raw is None:
        return fallback
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return fallback
    try:
        lo = float(raw[0])
        hi = float(raw[1])
    except (TypeError, ValueError):
        return fallback
    lo = max(0.0, min(1.0, lo))
    hi = max(0.0, min(1.0, hi))
    if lo > hi:
        lo, hi = hi, lo
    return [lo, hi]


# Community / issue #92 quality-first defaults (hard-surface leaning).
# guidance_interval matches HF pipeline.json defaults for SS/shape.
DEFAULT_SS_SAMPLER = {
    "steps": 12,
    "guidance_strength": 7.5,
    "guidance_rescale": 0.7,
    "rescale_t": 5.0,
    "guidance_interval": [0.6, 1.0],
}
DEFAULT_SHAPE_SLAT_SAMPLER = {
    "steps": 12,
    "guidance_strength": 7.5,
    "guidance_rescale": 0.5,
    "rescale_t": 3.0,
    "guidance_interval": [0.6, 1.0],
}
DEFAULT_TEX_SLAT_SAMPLER = {
    "steps": 12,
    "guidance_strength": 1.0,
    "guidance_rescale": 0.0,
    "rescale_t": 3.0,
    "guidance_interval": [0.6, 0.9],
}
MAXQ_SS_SAMPLER = {
    "steps": 50,
    "guidance_strength": 8.0,
    "guidance_rescale": 0.7,
    "rescale_t": 6.0,
    "guidance_interval": [0.6, 1.0],
}
MAXQ_SHAPE_SLAT_SAMPLER = {
    "steps": 50,
    "guidance_strength": 8.5,
    "guidance_rescale": 0.5,
    "rescale_t": 6.0,
    "guidance_interval": [0.6, 1.0],
}


def _generation_params(job_input: dict) -> dict:
    quality_max = bool(job_input.get("quality_max", False))

    raw_tier = job_input.get("quality_tier")
    quality_tier = None
    if isinstance(raw_tier, str) and raw_tier.strip():
        quality_tier = raw_tier.strip().lower()
        if quality_tier not in VALID_QUALITY_TIERS:
            quality_tier = None

    # Tier preset fills defaults; explicit job_input keys still win.
    tier_preset = dict(TIER_PRESETS[quality_tier]) if quality_tier else {}

    # Explicit pipeline_type wins; else tier; else quality_max → 1536; else default.
    if job_input.get("pipeline_type"):
        pipeline_type = job_input.get("pipeline_type")
        if pipeline_type not in VALID_PIPELINE_TYPES:
            pipeline_type = DEFAULT_PIPELINE_TYPE
    elif tier_preset.get("pipeline_type"):
        pipeline_type = tier_preset["pipeline_type"]
    elif quality_max:
        pipeline_type = "1536_cascade"
    else:
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

    default_decim = tier_preset.get(
        "decimation_target",
        800_000 if quality_max else DEFAULT_DECIMATION_TARGET,
    )
    decimation_target = _coerce_int(
        job_input.get("decimation_target"),
        default_decim,
        min_val=50_000,
        max_val=1_000_000,
    )
    seed = _coerce_int(job_input.get("seed"), DEFAULT_SEED, min_val=0, max_val=2**31 - 1)

    default_preprocess = tier_preset.get("preprocess_image", not quality_max)
    preprocess_image = bool(job_input.get("preprocess_image", default_preprocess))

    if "remesh" in job_input:
        remesh = bool(job_input.get("remesh"))
    elif "remesh" in tier_preset:
        remesh = bool(tier_preset["remesh"])
    else:
        remesh = False if quality_max else True

    verbose = bool(job_input.get("verbose", True))
    remesh_project = _coerce_float(
        job_input.get("remesh_project"), 0.0, min_val=0.0, max_val=1.0
    )
    default_tokens = tier_preset.get(
        "max_num_tokens",
        65_536 if quality_max else 49_152,
    )
    max_num_tokens = _coerce_int(
        job_input.get("max_num_tokens"),
        default_tokens,
        min_val=16_384,
        max_val=98_304,
    )
    remesh_band = _coerce_float(
        job_input.get("remesh_band"), 1.0, min_val=0.5, max_val=4.0
    )
    max_hole_perimeter = _coerce_float(
        job_input.get("max_hole_perimeter"),
        tier_preset.get("max_hole_perimeter", 3e-2),
        min_val=0.0,
        max_val=1.0,
    )
    remove_small_cc = _coerce_float(
        job_input.get("remove_small_cc"), 1e-5, min_val=0.0, max_val=1e-2
    )

    # Post-export mesh repair (G1/G2 holes gate). Off by default until eyes GO.
    raw_repair = str(job_input.get("mesh_repair") or "none").strip().lower()
    if raw_repair in ("", "0", "false", "off", "none", "null"):
        mesh_repair = "none"
    elif raw_repair in ("voxel", "pymeshlab", "trimesh"):
        mesh_repair = raw_repair
    else:
        mesh_repair = "none"
    mesh_repair_resolution = _coerce_int(
        job_input.get("mesh_repair_resolution") or job_input.get("repair_resolution"),
        256,
        min_val=64,
        max_val=512,
    )
    mesh_repair_max_hole_size = _coerce_int(
        job_input.get("mesh_repair_max_hole_size") or job_input.get("max_hole_size"),
        5000,
        min_val=10,
        max_val=50_000,
    )

    # Soft-norm: lift dark grooves on input RGB (G1d mid-prop holes). Opt-in.
    soft_input = bool(job_input.get("soft_input", False))
    soft_input_strength = _coerce_float(
        job_input.get("soft_input_strength"),
        0.75,
        min_val=0.0,
        max_val=1.0,
    )

    if quality_tier == "ultra":
        ss_defaults = tier_preset["sparse_structure_sampler_params"]
        shape_defaults = tier_preset["shape_slat_sampler_params"]
    elif quality_tier and tier_preset.get("sparse_structure_sampler_params"):
        ss_defaults = tier_preset["sparse_structure_sampler_params"]
        shape_defaults = tier_preset["shape_slat_sampler_params"]
    else:
        ss_defaults = MAXQ_SS_SAMPLER if quality_max else DEFAULT_SS_SAMPLER
        shape_defaults = MAXQ_SHAPE_SLAT_SAMPLER if quality_max else DEFAULT_SHAPE_SLAT_SAMPLER

    tex_defaults = DEFAULT_TEX_SLAT_SAMPLER

    multi_image_mode = str(
        job_input.get("multi_image_mode") or DEFAULT_MULTI_IMAGE_MODE
    ).strip().lower()
    if multi_image_mode not in VALID_MULTI_IMAGE_MODES:
        multi_image_mode = DEFAULT_MULTI_IMAGE_MODE

    allow_downgrade = bool(job_input.get("allow_downgrade", True))

    # Infer effective tier label for response when only raw knobs were sent.
    if quality_tier is None:
        if (
            pipeline_type == "1536_cascade"
            and remesh
            and decimation_target >= 650_000
            and _sampler_params_from_input(
                job_input.get("sparse_structure_sampler_params"), ss_defaults
            ).get("steps", 0)
            >= 40
        ):
            quality_tier_label = "ultra"
        elif pipeline_type in ("512",):
            quality_tier_label = "preview"
        else:
            quality_tier_label = "quality"
    else:
        quality_tier_label = quality_tier

    return {
        "pipeline_type": pipeline_type,
        "texture_mode": texture_mode,
        "texture_size": texture_size,
        "decimation_target": decimation_target,
        "seed": seed,
        "preprocess_image": preprocess_image,
        "remesh": remesh,
        "remesh_project": remesh_project,
        "remesh_band": remesh_band,
        "max_hole_perimeter": max_hole_perimeter,
        "remove_small_cc": remove_small_cc,
        "mesh_repair": mesh_repair,
        "mesh_repair_resolution": mesh_repair_resolution,
        "mesh_repair_max_hole_size": mesh_repair_max_hole_size,
        "soft_input": soft_input,
        "soft_input_strength": soft_input_strength,
        "verbose": verbose,
        "quality_max": quality_max,
        "quality_tier": quality_tier_label,
        "allow_downgrade": allow_downgrade,
        "max_num_tokens": max_num_tokens,
        "multi_image_mode": multi_image_mode,
        "sparse_structure_sampler_params": _sampler_params_from_input(
            job_input.get("sparse_structure_sampler_params"), ss_defaults
        ),
        "shape_slat_sampler_params": _sampler_params_from_input(
            job_input.get("shape_slat_sampler_params"), shape_defaults
        ),
        "tex_slat_sampler_params": _sampler_params_from_input(
            job_input.get("tex_slat_sampler_params"), tex_defaults
        ),
    }


def _resolve_image_urls(job_input: dict) -> list[str]:
    """Prefer image_urls[]; else single image_url. Dedup while preserving order."""
    urls: list[str] = []
    raw_list = job_input.get("image_urls")
    if isinstance(raw_list, (list, tuple)):
        for item in raw_list:
            if isinstance(item, str) and item.strip():
                urls.append(item.strip())
    single = job_input.get("image_url")
    if isinstance(single, str) and single.strip():
        if single.strip() not in urls:
            urls.insert(0, single.strip())
    # Cap to keep VRAM/time bounded (multidiffusion scales with N).
    return urls[:MAX_MULTI_IMAGES]


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
    try:
        from trellis2_multi_image import patch_pipeline
    except ImportError:
        from studio_bridge.trellis2_multi_image import patch_pipeline
    patch_pipeline(pipeline)
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
    max_hole_perimeter = float(gen_params.get("max_hole_perimeter", 3e-2))
    remove_small_cc = float(gen_params.get("remove_small_cc", 1e-5))
    remesh_band = float(gen_params.get("remesh_band", 1.0))
    aabb = torch.tensor(
        [[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        dtype=torch.float32,
        device=mesh.vertices.device if hasattr(mesh.vertices, "device") else "cuda",
    )

    vertices = mesh.vertices.cuda()
    faces = mesh.faces.cuda()
    cm = cumesh.CuMesh()
    cm.init(vertices, faces)
    cm.fill_holes(max_hole_perimeter=max_hole_perimeter)
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
        remesh_project = float(gen_params.get("remesh_project", 0.0))
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
        cm.remove_duplicate_faces()
        cm.repair_non_manifold_edges()
        cm.remove_small_connected_components(remove_small_cc)
        cm.fill_holes(max_hole_perimeter=max_hole_perimeter)
        if verbose:
            print(
                f"Clay after post-remesh repair: {cm.num_vertices} verts, "
                f"{cm.num_faces} faces"
            )
    else:
        cm.simplify(decimation_target * 3, verbose=verbose)
        cm.remove_duplicate_faces()
        cm.repair_non_manifold_edges()
        cm.remove_small_connected_components(remove_small_cc)
        cm.fill_holes(max_hole_perimeter=max_hole_perimeter)
        cm.simplify(decimation_target, verbose=verbose)
        cm.remove_duplicate_faces()
        cm.repair_non_manifold_edges()
        cm.remove_small_connected_components(remove_small_cc)
        cm.fill_holes(max_hole_perimeter=max_hole_perimeter)
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
    clay = trimesh.Trimesh(
        vertices=vertices_np,
        faces=faces_np,
        process=False,
        visual=trimesh.visual.TextureVisuals(material=material),
    )
    return _apply_mesh_repair(clay, gen_params)


def _apply_mesh_repair(mesh, gen_params: dict):
    """Optional CPU post-repair after CuMesh clay export (holes gate G2)."""
    mode = str(gen_params.get("mesh_repair") or "none").strip().lower()
    if mode in ("", "none", "off", "false"):
        return mesh
    verbose = bool(gen_params.get("verbose", True))
    try:
        from studio_bridge.mesh_repair import mesh_stats, repair_pymeshlab, repair_voxel
    except ImportError:
        from mesh_repair import mesh_stats, repair_pymeshlab, repair_voxel  # type: ignore

    before = mesh_stats(mesh)
    if verbose:
        print(f"mesh_repair={mode} before={before}")

    if mode == "voxel":
        repaired, extra = repair_voxel(
            mesh,
            resolution=int(gen_params.get("mesh_repair_resolution") or 256),
        )
        if verbose:
            print(f"mesh_repair voxel extra={extra} after={mesh_stats(repaired)}")
        return repaired
    if mode == "trimesh":
        import trimesh as _trimesh

        repaired = mesh.copy()
        _trimesh.repair.fix_normals(repaired)
        try:
            _trimesh.repair.fill_holes(repaired)
        except Exception as exc:
            print(f"WARN: trimesh fill_holes: {exc}")
        if verbose:
            print(f"mesh_repair trimesh after={mesh_stats(repaired)}")
        return repaired
    if mode == "pymeshlab":
        import tempfile
        from pathlib import Path

        try:
            from studio_bridge.mesh_repair import load_glb_mesh as _load
        except ImportError:
            from mesh_repair import load_glb_mesh as _load  # type: ignore

        in_tmp = Path(tempfile.mkstemp(suffix=".glb")[1])
        out_tmp = Path(tempfile.mkstemp(suffix=".glb")[1])
        try:
            mesh.export(in_tmp)
            repair_pymeshlab(
                in_tmp,
                out_tmp,
                max_hole_size=int(gen_params.get("mesh_repair_max_hole_size") or 5000),
            )
            repaired = _load(out_tmp)
        finally:
            in_tmp.unlink(missing_ok=True)
            out_tmp.unlink(missing_ok=True)
        if verbose:
            print(f"mesh_repair pymeshlab after={mesh_stats(repaired)}")
        return repaired

    print(f"WARN: unknown mesh_repair={mode!r}; skipping")
    return mesh


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
        remesh_band=float(gen_params.get("remesh_band", 1.0)),
        remesh_project=float(gen_params.get("remesh_project", 0.0)),
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


def _is_oom_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    markers = (
        "out of memory",
        "oom",
        "cuda error: 2",
        "error code: 2",
        "cudnn_status_alloc_failed",
        "cuda out of memory",
    )
    return any(m in text for m in markers)


def _cuda_cleanup() -> None:
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception as cleanup_exc:
        print(f"cuda cleanup warning: {cleanup_exc}")


def _quality_ladder_params(gen_params: dict) -> list[dict]:
    """Ordered full re-infer attempts. Export remesh OOM is handled separately."""
    ladder = [copy.deepcopy(gen_params)]
    if not gen_params.get("allow_downgrade", True):
        return ladder

    heavy = (
        gen_params.get("quality_tier") == "ultra"
        or gen_params.get("pipeline_type") == "1536_cascade"
    )
    if not heavy:
        return ladder

    soft = copy.deepcopy(gen_params)
    quality_preset = dict(TIER_PRESETS["quality"])
    soft["pipeline_type"] = quality_preset["pipeline_type"]
    soft["decimation_target"] = min(
        int(soft.get("decimation_target") or quality_preset["decimation_target"]),
        quality_preset["decimation_target"],
    )
    soft["remesh"] = quality_preset["remesh"]
    soft["max_hole_perimeter"] = quality_preset.get("max_hole_perimeter", 0.1)
    soft["max_num_tokens"] = min(
        int(soft.get("max_num_tokens") or quality_preset["max_num_tokens"]),
        quality_preset["max_num_tokens"],
    )
    soft["quality_tier"] = "quality"
    soft["sparse_structure_sampler_params"] = dict(
        quality_preset["sparse_structure_sampler_params"]
    )
    soft["shape_slat_sampler_params"] = dict(
        quality_preset["shape_slat_sampler_params"]
    )
    soft["tex_slat_sampler_params"] = dict(DEFAULT_TEX_SLAT_SAMPLER)
    ladder.append(soft)
    return ladder


def _run_inference(images: list, gen_params: dict):
    multi = len(images) >= 2
    if multi:
        try:
            from trellis2_multi_image import run_multi_image
        except ImportError:
            from studio_bridge.trellis2_multi_image import run_multi_image
        return run_multi_image(
            pipeline,
            images,
            seed=gen_params["seed"],
            preprocess_image=gen_params["preprocess_image"],
            pipeline_type=gen_params["pipeline_type"],
            sparse_structure_sampler_params=gen_params["sparse_structure_sampler_params"],
            shape_slat_sampler_params=gen_params["shape_slat_sampler_params"],
            tex_slat_sampler_params=gen_params["tex_slat_sampler_params"],
            max_num_tokens=gen_params["max_num_tokens"],
            fusion_mode=gen_params["multi_image_mode"],
        )
    return pipeline.run(
        images[0],
        seed=gen_params["seed"],
        preprocess_image=gen_params["preprocess_image"],
        pipeline_type=gen_params["pipeline_type"],
        sparse_structure_sampler_params=gen_params["sparse_structure_sampler_params"],
        shape_slat_sampler_params=gen_params["shape_slat_sampler_params"],
        tex_slat_sampler_params=gen_params["tex_slat_sampler_params"],
        max_num_tokens=gen_params["max_num_tokens"],
    )


def _export_glb_with_remesh_fallback(mesh, gen_params: dict, attempts: list) -> tuple:
    """Try export; on CuMesh/export OOM with remesh, retry once with remesh=false."""
    try:
        return _mesh_to_glb(mesh, gen_params), gen_params
    except Exception as exc:
        if not gen_params.get("allow_downgrade", True) or not gen_params.get("remesh"):
            raise
        if not _is_oom_error(exc):
            raise
        print(f"OOM during GLB export with remesh=true; retry remesh=false. err={exc}")
        attempts.append(
            {
                "stage": "export",
                "pipeline_type": gen_params.get("pipeline_type"),
                "remesh": True,
                "error": str(exc),
                "action": "retry_remesh_false",
            }
        )
        _cuda_cleanup()
        soft = copy.deepcopy(gen_params)
        soft["remesh"] = False
        return _mesh_to_glb(mesh, soft), soft


def _handler_mesh_repair(
    job_input: dict, repair_mode: str, mesh_url: str, *, job_id: str = ""
) -> dict:
    """Fast path: mesh repair without loading TRELLIS (G1/G2 holes gate)."""
    t0 = time.perf_counter()
    return_base64 = bool(job_input.get("return_base64", False))
    job_id = job_id or f"repair-{int(time.time())}"
    resolution = int(job_input.get("repair_resolution") or job_input.get("resolution") or 256)
    max_hole_size = int(job_input.get("max_hole_size") or 5000)
    glb_path: str | None = None

    try:
        from studio_bridge.mesh_repair import run_repair

        glb_path_str, meta = run_repair(
            mesh_url,
            mode=repair_mode,
            resolution=resolution,
            max_hole_size=max_hole_size,
        )
        glb_path = glb_path_str
        handler_ms = {"total_ms": int((time.perf_counter() - t0) * 1000)}
        delivery = _deliver_glb(glb_path, job_id, return_base64=return_base64)
        return {
            "status": "success",
            "message": f"Mesh repair ({repair_mode}) completed",
            "repair_mode": repair_mode,
            "repair_meta": meta,
            "mesh_stats": meta.get("after"),
            "billing": _runpod_billing_metadata(handler_ms),
            **delivery,
        }
    except Exception as exc:
        tb = traceback.format_exc()
        print(f"REPAIR ERROR: {exc}")
        print(tb)
        return {"error": f"Mesh repair failed: {exc}", "repair_mode": repair_mode}
    finally:
        if glb_path and os.path.exists(glb_path):
            os.remove(glb_path)


def handler(job):
    job_input = job.get("input", {})
    repair_mode = str(job_input.get("repair_mode") or "").strip().lower()
    mesh_url = job_input.get("mesh_url") or job_input.get("glb_url")
    if repair_mode and mesh_url:
        return _handler_mesh_repair(
            job_input, repair_mode, str(mesh_url), job_id=str(job.get("id") or "")
        )

    image_urls = _resolve_image_urls(job_input)
    gen_params = _generation_params(job_input)
    return_base64 = bool(job_input.get("return_base64", False))
    job_id = str(job.get("id") or f"local-{int(time.time())}")
    quality_tier_requested = gen_params.get("quality_tier")

    if not image_urls:
        return {"error": "Missing image_url or image_urls in job input"}

    img_paths: list[str] = []
    glb_path = None

    try:
        t0 = time.perf_counter()
        handler_ms = {}
        downgrade_attempts: list[dict] = []

        t_load = time.perf_counter()
        load_model()
        handler_ms["model_load_ms"] = int((time.perf_counter() - t_load) * 1000)

        gen_params["num_images"] = len(image_urls)
        print(
            "TRELLIS.2 params: "
            f"quality_tier={gen_params.get('quality_tier')}, "
            f"pipeline_type={gen_params['pipeline_type']}, "
            f"texture_mode={gen_params['texture_mode']}, "
            f"texture_size={gen_params['texture_size']}, "
            f"decimation_target={gen_params['decimation_target']}, "
            f"seed={gen_params['seed']}, "
            f"quality_max={gen_params.get('quality_max')}, "
            f"remesh={gen_params['remesh']}, "
            f"soft_input={gen_params.get('soft_input')}"
            f"(strength={gen_params.get('soft_input_strength')}), "
            f"allow_downgrade={gen_params.get('allow_downgrade')}, "
            f"num_images={len(image_urls)}, "
            f"multi_image_mode={gen_params['multi_image_mode'] if len(image_urls) >= 2 else 'n/a'}, "
            f"ss={gen_params['sparse_structure_sampler_params']}, "
            f"shape_slat={gen_params['shape_slat_sampler_params']}"
        )

        images = []
        for i, url in enumerate(image_urls):
            print(f"Downloading image[{i}]: {url}")
            path = _download_image(url)
            img_paths.append(path)
            images.append(Image.open(path).convert("RGB"))

        if gen_params.get("soft_input"):
            strength = float(gen_params.get("soft_input_strength") or 0.75)
            try:
                from studio_bridge.soft_input import soften_images
            except ImportError:
                from soft_input import soften_images  # type: ignore
            print(f"Applying soft_input strength={strength} to {len(images)} image(s)")
            images = soften_images(images, strength=strength)

        ladder = _quality_ladder_params(gen_params)
        last_error: BaseException | None = None
        used_params = gen_params
        mesh = None
        glb = None
        infer_ms_total = 0
        export_ms_total = 0

        for attempt_idx, attempt_params in enumerate(ladder):
            attempt_params = copy.deepcopy(attempt_params)
            attempt_params["num_images"] = len(image_urls)
            print(
                f"TRELLIS.2 attempt {attempt_idx + 1}/{len(ladder)}: "
                f"tier={attempt_params.get('quality_tier')} "
                f"pipeline={attempt_params['pipeline_type']} "
                f"remesh={attempt_params['remesh']} "
                f"decim={attempt_params['decimation_target']}"
            )
            if attempt_idx > 0:
                _cuda_cleanup()

            try:
                t_infer = time.perf_counter()
                meshes = _run_inference(images, attempt_params)
                infer_ms_total += int((time.perf_counter() - t_infer) * 1000)
                mesh = meshes[0]

                t_glb = time.perf_counter()
                glb, used_params = _export_glb_with_remesh_fallback(
                    mesh, attempt_params, downgrade_attempts
                )
                export_ms_total += int((time.perf_counter() - t_glb) * 1000)
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                is_oom = _is_oom_error(exc)
                print(f"Attempt {attempt_idx + 1} failed (oom={is_oom}): {exc}")
                downgrade_attempts.append(
                    {
                        "stage": "infer_or_export",
                        "pipeline_type": attempt_params.get("pipeline_type"),
                        "remesh": attempt_params.get("remesh"),
                        "quality_tier": attempt_params.get("quality_tier"),
                        "error": str(exc),
                        "oom": is_oom,
                    }
                )
                if not is_oom or not attempt_params.get("allow_downgrade", True):
                    raise
                if attempt_idx + 1 >= len(ladder):
                    raise
                print("OOM/retryable failure — trying safer profile…")
                continue

        if glb is None or last_error is not None:
            raise last_error or RuntimeError("Generation failed with no GLB")

        handler_ms["inference_ms"] = infer_ms_total
        handler_ms["glb_export_ms"] = export_ms_total

        mesh_stats = {
            "vertices": int(len(glb.vertices)),
            "faces": int(len(glb.faces)),
        }

        glb_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".glb")
        glb_path = glb_temp.name
        glb_temp.close()
        if used_params["texture_mode"] == "clay":
            glb.export(glb_path)
        else:
            glb.export(glb_path, extension_webp=True)

        t_deliver = time.perf_counter()
        delivery = _deliver_glb(glb_path, job_id, return_base64=return_base64)
        handler_ms["deliver_ms"] = int((time.perf_counter() - t_deliver) * 1000)
        handler_ms["total_ms"] = int((time.perf_counter() - t0) * 1000)

        tier_used = used_params.get("quality_tier") or quality_tier_requested
        downgraded = bool(downgrade_attempts) or (
            tier_used != quality_tier_requested
            or used_params.get("remesh") != gen_params.get("remesh")
            or used_params.get("pipeline_type") != gen_params.get("pipeline_type")
        )
        downgrade_reason = None
        if downgraded:
            downgrade_reason = "oom_or_vram_pressure"
            if downgrade_attempts:
                downgrade_reason = downgrade_attempts[-1].get("error") or downgrade_reason

        return {
            "status": "success",
            "message": (
                "TRELLIS.2 model generated successfully"
                + (" (downgraded after OOM)" if downgraded else "")
            ),
            "generation": used_params,
            "quality_tier_requested": quality_tier_requested,
            "quality_tier_used": tier_used,
            "downgraded": downgraded,
            "downgrade_reason": downgrade_reason,
            "downgrade_attempts": downgrade_attempts,
            "mesh_stats": mesh_stats,
            "billing": _runpod_billing_metadata(handler_ms),
            **delivery,
        }

    except Exception as exc:
        tb = traceback.format_exc()
        print(f"CRITICAL ERROR: {exc}")
        print(tb)
        err = {"error": f"Generation failed: {exc}"}
        if _is_oom_error(exc):
            err["error_class"] = "oom"
            err["retryable"] = True
            err["suggestion"] = (
                "Retry with quality_tier=quality or allow_downgrade=true "
                "(ultra remesh can OOM on complex inputs / 24GB)."
            )
        return err

    finally:
        for img_path in img_paths:
            if img_path and os.path.exists(img_path):
                os.remove(img_path)
        if glb_path and os.path.exists(glb_path):
            os.remove(glb_path)


runpod.serverless.start({"handler": handler})
