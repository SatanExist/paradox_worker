"""RunPod handler: image URL -> Pixal3D -> GLB on volume (optional R2 URL / base64).

Pixal3D is TRELLIS.2 with pixel-aligned conditioning (`ElasticSLatFlowModel`,
`image_attn_mode=proj`), so it needs its own fork and a camera FOV estimate from
MoGe. Everything else — sampler shape, cascade pipeline types, o-voxel export —
matches worker_trellis2.py.

Deploy via Dockerfile.pixal3d on a dedicated 24GB+ endpoint.
"""

from __future__ import annotations

import base64
import math
import os
import tempfile
import time
import traceback
import urllib.request
from pathlib import Path

import runpod

MODEL_ID = os.environ.get("PIXAL3D_MODEL_ID", "TencentARC/Pixal3D")
DEFAULT_OUTPUT_DIR = "/runpod-volume/outputs"
DEFAULT_BASE64_MAX_BYTES = 8 * 1024 * 1024

# 1536 is the upstream default; low-VRAM cards should ask for 1024.
VALID_RESOLUTIONS = (512, 1024, 1536)

# Upstream defaults from pipeline.json, exposed so jobs can override them.
SAMPLER_DEFAULTS = {
    "ss": {"steps": 12, "guidance_strength": 7.5, "guidance_rescale": 0.7, "rescale_t": 5.0},
    "shape": {"steps": 12, "guidance_strength": 7.5, "guidance_rescale": 0.5, "rescale_t": 3.0},
    "tex": {"steps": 12, "guidance_strength": 1.0, "guidance_rescale": 0.0, "rescale_t": 3.0},
}

# Non-gated DINOv3 mirror the upstream inference script uses.
IMAGE_COND_CONFIGS = {
    "ss": {"image_size": 512, "grid_resolution": 16},
    "shape_512": {
        "image_size": 512,
        "grid_resolution": 32,
        "use_naf_upsample": True,
        "naf_target_size": 512,
    },
    "shape_1024": {
        "image_size": 1024,
        "grid_resolution": 64,
        "use_naf_upsample": True,
        "naf_target_size": 512,
    },
    "tex_1024": {
        "image_size": 1024,
        "grid_resolution": 64,
        "use_naf_upsample": True,
        "naf_target_size": 1024,
    },
}

_PIPELINE = None


def _dino_model_name() -> str:
    """Local converted weights if the volume has them, else a non-gated mirror."""
    local = Path(
        os.environ.get(
            "PIXAL3D_DINOV3_PATH", "/runpod-volume/dinov3-vitl16-pretrain-lvd1689m"
        )
    )
    if (local / "config.json").is_file():
        return str(local)
    return os.environ.get(
        "PIXAL3D_DINOV3_MODEL", "camenduru/dinov3-vitl16-pretrain-lvd1689m"
    )


def _rewrite_pipeline_json(model_path: str) -> None:
    """Swap the two gated repos upstream's pipeline.json points at.

    `facebook/dinov3-*` and `briaai/RMBG-2.0` both need an accepted licence, and
    RMBG is CC BY-NC on top of that. Same substitution worker_trellis2.py makes.

    The file usually arrives as a symlink into the HF cache blobs, so it is
    unlinked before writing: overwriting in place would corrupt the blob shared
    with any other snapshot.
    """
    import json

    pipeline_json = Path(model_path) / "pipeline.json"
    if not pipeline_json.is_file():
        print(f"pipeline.json not found under {model_path}; skip rewrites")
        return

    data = json.loads(pipeline_json.read_text(encoding="utf-8"))
    args = data.get("args") or data
    changed = False

    for key, wanted in (
        ("image_cond_model", _dino_model_name()),
        ("rembg_model", os.environ.get("PIXAL3D_REMBG_MODEL", "ZhengPeng7/BiRefNet")),
    ):
        entry = args.get(key)
        if not isinstance(entry, dict):
            continue
        entry_args = entry.setdefault("args", {})
        old = entry_args.get("model_name")
        if old != wanted:
            entry_args["model_name"] = wanted
            print(f"{key} model_name: {old!r} -> {wanted!r}")
            changed = True

    if changed:
        if pipeline_json.is_symlink():
            pipeline_json.unlink()
        pipeline_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _low_vram() -> bool:
    return os.environ.get("PIXAL3D_LOW_VRAM", "").strip().lower() in ("1", "true", "yes")


def _load_pipeline():
    """Load once per cold start; mirrors upstream inference.init_pipeline."""
    global _PIPELINE
    if _PIPELINE is not None:
        return _PIPELINE

    import torch
    from huggingface_hub import snapshot_download
    from pixal3d.pipelines import Pixal3DImageTo3DPipeline
    from pixal3d.trainers.flow_matching.mixins.image_conditioned_proj import (
        DinoV3ProjFeatureExtractor,
    )

    print(f"paradox_worker pixal3d build: {os.environ.get('PARADOX_BUILD_SHA', 'dev')}")
    model_path = snapshot_download(
        repo_id=MODEL_ID,
        token=os.environ.get("HF_TOKEN") or None,
    )
    _rewrite_pipeline_json(model_path)

    print(f"Loading Pixal3D from {model_path}...")
    pipeline = Pixal3DImageTo3DPipeline.from_pretrained(model_path)

    dino = _dino_model_name()
    for attr, config in (
        ("image_cond_model_ss", IMAGE_COND_CONFIGS["ss"]),
        ("image_cond_model_shape_512", IMAGE_COND_CONFIGS["shape_512"]),
        ("image_cond_model_shape_1024", IMAGE_COND_CONFIGS["shape_1024"]),
        ("image_cond_model_tex_1024", IMAGE_COND_CONFIGS["tex_1024"]),
    ):
        model = DinoV3ProjFeatureExtractor(model_name=dino, **config)
        model.eval()
        setattr(pipeline, attr, model)

    cond_attrs = (
        "image_cond_model_ss",
        "image_cond_model_shape_512",
        "image_cond_model_shape_1024",
        "image_cond_model_tex_1024",
    )
    if _low_vram():
        # Keep weights on CPU and page them in per stage: peak VRAM becomes one
        # flow model plus one DinoV3 instead of the full ~18 GB.
        for attr in cond_attrs:
            model = getattr(pipeline, attr, None)
            if model is not None and getattr(model, "use_naf_upsample", False):
                model._load_naf()
        pipeline._device = torch.device("cuda")
        pipeline.low_vram = True
        print("Pixal3D pipeline ready (low-VRAM staging).")
    else:
        pipeline.low_vram = False
        pipeline.cuda()
        for attr in cond_attrs:
            getattr(pipeline, attr).cuda()
        print("Pixal3D pipeline ready in VRAM.")

    _PIPELINE = pipeline
    return pipeline


def _download_image(image_url: str) -> str:
    req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_img:
        with urllib.request.urlopen(req) as response:
            temp_img.write(response.read())
        return temp_img.name


def _distance_from_fov(
    camera_angle_x: float, mesh_scale: float, image_resolution: int, extend_pixel: int
) -> float:
    """Upstream camera placement: solve for distance that frames the object."""
    import torch

    rotation = torch.tensor([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
    grid_point = torch.tensor([-1.0, 0.0, 0.0]) @ rotation.T
    grid_point = grid_point / mesh_scale / 2
    xw, yw = float(grid_point[0]), float(grid_point[1])

    focal_length = 16.0 / math.tan(camera_angle_x / 2.0)
    f_pixels = focal_length * image_resolution / 32.0
    x_ndc = float(-extend_pixel) - image_resolution / 2.0
    return f_pixels * xw / x_ndc - yw


def _camera_params(
    image_path: str, manual_fov: float, mesh_scale: float, image_resolution: int, extend_pixel: int
) -> dict:
    """FOV from MoGe unless the job pins it; MoGe is freed right after."""
    import torch

    if manual_fov > 0:
        camera_angle_x = float(manual_fov)
    else:
        import numpy as np
        from moge.model.v2 import MoGeModel
        from PIL import Image

        moge = MoGeModel.from_pretrained(
            os.environ.get("PIXAL3D_MOGE_MODEL", "Ruicheng/moge-2-vitl")
        ).cuda()
        moge.eval()
        try:
            image = Image.open(image_path).convert("RGB")
            tensor = torch.from_numpy(
                np.array(image).astype("float32") / 255.0
            ).permute(2, 0, 1).cuda()
            with torch.no_grad():
                intrinsics = moge.infer(tensor)["intrinsics"].squeeze().cpu().numpy()
            fx = float(intrinsics[0, 0]) * image.size[0]
            camera_angle_x = 2 * math.atan(image.size[0] / (2 * fx))
        finally:
            moge.cpu()
            del moge
            torch.cuda.empty_cache()

    distance = _distance_from_fov(camera_angle_x, mesh_scale, image_resolution, extend_pixel)
    print(f"camera_angle_x={camera_angle_x:.4f} rad, distance={distance:.4f}")
    return {
        "camera_angle_x": camera_angle_x,
        "distance": distance,
        "mesh_scale": mesh_scale,
    }


def _sampler_overrides(job_input: dict, stage: str) -> dict:
    defaults = SAMPLER_DEFAULTS[stage]
    return {
        key: job_input.get(f"{stage}_{key}", value) for key, value in defaults.items()
    }


def _upload_r2(local_path: Path, key: str) -> str | None:
    endpoint = os.environ.get("R2_ENDPOINT_URL", "").strip()
    bucket = os.environ.get("R2_BUCKET", "").strip()
    access_key = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
    public_base = os.environ.get("R2_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not all((endpoint, bucket, access_key, secret_key, public_base)):
        return None

    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=os.environ.get("R2_REGION", "auto"),
    )
    client.upload_file(
        str(local_path), bucket, key, ExtraArgs={"ContentType": "model/gltf-binary"}
    )
    return f"{public_base}/{key}"


def handler(job):
    started = time.time()
    job_input = job.get("input") or {}
    image_url = job_input.get("image_url")
    if not image_url:
        return {"error": "image_url is required"}

    resolution = int(job_input.get("resolution", 1024 if _low_vram() else 1536))
    if resolution not in VALID_RESOLUTIONS:
        return {
            "error": f"resolution must be one of {VALID_RESOLUTIONS}, got {resolution}"
        }

    seed = int(job_input.get("seed", 42))
    mesh_scale = float(job_input.get("mesh_scale", 1.0))
    extend_pixel = int(job_input.get("extend_pixel", 0))
    image_resolution = int(job_input.get("image_resolution", 512))
    manual_fov = float(job_input.get("manual_fov", -1.0))
    max_num_tokens = int(job_input.get("max_num_tokens", 49152))
    decimation_target = int(job_input.get("decimation_target", 1_000_000))
    texture_size = int(job_input.get("texture_size", 4096))
    remesh = bool(job_input.get("remesh", True))

    image_path = None
    try:
        import numpy as np
        import o_voxel
        import torch
        from PIL import Image

        pipeline = _load_pipeline()
        load_done = time.time()

        image_path = _download_image(image_url)
        image = pipeline.preprocess_image(Image.open(image_path))

        # MoGe reads the preprocessed (background-removed) image, like upstream.
        prepped_path = image_path + ".prep.png"
        image.save(prepped_path)
        camera_params = _camera_params(
            prepped_path, manual_fov, mesh_scale, image_resolution, extend_pixel
        )
        os.remove(prepped_path)

        torch.manual_seed(seed)
        pipeline_type = f"{resolution}_cascade"
        print(f"Running Pixal3D pipeline_type={pipeline_type} seed={seed}")
        mesh_list, (_shape_slat, _tex_slat, res) = pipeline.run(
            image,
            camera_params=camera_params,
            seed=seed,
            sparse_structure_sampler_params=_sampler_overrides(job_input, "ss"),
            shape_slat_sampler_params=_sampler_overrides(job_input, "shape"),
            tex_slat_sampler_params=_sampler_overrides(job_input, "tex"),
            preprocess_image=False,
            return_latent=True,
            pipeline_type=pipeline_type,
            max_num_tokens=max_num_tokens,
        )
        infer_done = time.time()

        mesh = mesh_list[0]
        glb = o_voxel.postprocess.to_glb(
            vertices=mesh.vertices,
            faces=mesh.faces,
            attr_volume=mesh.attrs,
            coords=mesh.coords,
            attr_layout=pipeline.pbr_attr_layout,
            grid_size=res,
            aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target=decimation_target,
            texture_size=texture_size,
            remesh=remesh,
            remesh_band=1,
            remesh_project=0,
            use_tqdm=False,
        )
        # Upstream orientation fix: Pixal3D exports Z-up mirrored.
        glb.apply_transform(
            np.array(
                [[-1, 0, 0, 0], [0, 0, -1, 0], [0, -1, 0, 0], [0, 0, 0, 1]],
                dtype=np.float64,
            )
        )

        output_dir = Path(os.environ.get("PIXAL3D_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
        output_dir.mkdir(parents=True, exist_ok=True)
        name = f"pixal3d_{int(time.time())}_{seed}_{resolution}.glb"
        dest = output_dir / name
        glb.export(str(dest), extension_webp=True)
        size = dest.stat().st_size
        print(f"GLB saved: {dest} ({size / 2**20:.1f} MB)")

        result = {
            "model_path": str(dest),
            "size_bytes": size,
            "resolution": resolution,
            "grid_size": int(res) if not hasattr(res, "__len__") else list(map(int, res)),
            "seed": seed,
            "camera_angle_x": camera_params["camera_angle_x"],
            "worker_variant": "pixal3d",
            "build_sha": os.environ.get("PARADOX_BUILD_SHA", "dev"),
            "timings_s": {
                "load": round(load_done - started, 1),
                "inference": round(infer_done - load_done, 1),
                "export": round(time.time() - infer_done, 1),
                "total": round(time.time() - started, 1),
            },
        }

        model_url = _upload_r2(dest, f"pixal3d/{name}")
        if model_url:
            result["model_url"] = model_url
        elif size <= int(
            os.environ.get("PIXAL3D_BASE64_MAX_BYTES", str(DEFAULT_BASE64_MAX_BYTES))
        ):
            result["model_base64"] = base64.b64encode(dest.read_bytes()).decode()
        else:
            result["note"] = (
                "GLB too large for base64 and R2_* env is not configured; "
                "read model_path from the network volume."
            )
        return result

    except Exception as exc:
        traceback.print_exc()
        return {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        if image_path and os.path.exists(image_path):
            os.remove(image_path)


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
