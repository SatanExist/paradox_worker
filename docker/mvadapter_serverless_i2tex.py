"""Serverless-friendly texture_i2tex: lower UV size, no view upscale, fewer steps.

Prod UV path: xatlas unwrap (not Open3D UVAtlas) then bake with uv_unwarp=False.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import time
from pathlib import Path

import numpy as np
import torch
from torchvision import transforms
from transformers import AutoModelForImageSegmentation

from mvadapter.pipelines.pipeline_texture import ModProcessConfig, TexturePipeline
from mvadapter.utils import make_image_grid


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _phase(msg: str, t0: float | None = None) -> float:
    now = time.perf_counter()
    if t0 is None:
        print(f"[i2tex] {msg}", flush=True)
    else:
        print(f"[i2tex] {msg} (+{now - t0:.1f}s)", flush=True)
    return now


def _glb_has_texcoord(path: str) -> bool:
    data = Path(path).read_bytes()
    if len(data) < 20 or data[0:4] != b"glTF":
        return False
    json_len, json_type = struct.unpack_from("<II", data, 12)
    if json_type != 0x4E4F534A:
        return False
    gltf = json.loads(data[20 : 20 + json_len])
    for mesh in gltf.get("meshes") or []:
        for prim in mesh.get("primitives") or []:
            attrs = prim.get("attributes") or {}
            if any(k.startswith("TEXCOORD") for k in attrs):
                return True
    return False


def _load_triangle_mesh(mesh_path: str):
    import trimesh

    loaded = trimesh.load(mesh_path, force="mesh", process=False)
    if isinstance(loaded, trimesh.Scene):
        geoms = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
        if not geoms:
            raise RuntimeError(f"no triangle mesh in {mesh_path}")
        return trimesh.util.concatenate(geoms)
    return loaded


def decimate_mesh(mesh, target_faces: int):
    """Quadric decimate toward target face count (Meshy-like poly budget)."""
    import trimesh

    n_faces = int(len(mesh.faces))
    if target_faces <= 0 or n_faces <= target_faces:
        _phase(f"decimate skip F={n_faces} target={target_faces}")
        return mesh

    t0 = _phase(f"decimate begin F={n_faces} target={target_faces}")
    out = None
    try:
        import open3d as o3d

        o3 = o3d.geometry.TriangleMesh()
        o3.vertices = o3d.utility.Vector3dVector(np.asarray(mesh.vertices, dtype=np.float64))
        o3.triangles = o3d.utility.Vector3iVector(np.asarray(mesh.faces, dtype=np.int32))
        o3 = o3.simplify_quadric_decimation(target_number_of_triangles=int(target_faces))
        out = trimesh.Trimesh(
            vertices=np.asarray(o3.vertices),
            faces=np.asarray(o3.triangles),
            process=False,
        )
    except Exception as exc:
        _phase(f"decimate open3d failed ({exc}); trying trimesh")
        try:
            out = mesh.simplify_quadric_decimation(face_count=int(target_faces))
        except TypeError:
            # Older trimesh: percent in (0, 1]
            percent = min(1.0, float(target_faces) / float(max(n_faces, 1)))
            out = mesh.simplify_quadric_decimation(percent=percent)

    if out is None or len(out.faces) == 0:
        raise RuntimeError("decimate produced empty mesh")
    _phase(f"decimate done V={len(out.vertices)} F={len(out.faces)}", t0)
    return out


def ensure_mesh_uvs(
    mesh_path: str,
    save_dir: str,
    save_name: str,
    *,
    target_faces: int = 80000,
) -> str:
    """Decimate (optional) + xatlas UV. Returns GLB path with TEXCOORD_0."""
    import trimesh
    import xatlas

    # Reuse existing UV only when we are not changing topology.
    if target_faces <= 0 and _glb_has_texcoord(mesh_path):
        _phase(f"mesh already has UV (no decimate): {mesh_path}")
        return mesh_path

    mesh = _load_triangle_mesh(mesh_path)
    mesh = decimate_mesh(mesh, target_faces)

    os.makedirs(save_dir, exist_ok=True)
    decim_path = os.path.join(save_dir, f"{save_name}_decimated.glb")
    mesh.export(decim_path)
    _phase(f"decimated mesh saved {decim_path} ({os.path.getsize(decim_path)} bytes)")

    t0 = _phase(f"xatlas UV begin mesh={decim_path}")
    vertices = np.asarray(mesh.vertices, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.uint32)
    _phase(f"xatlas input V={len(vertices)} F={len(faces)}")

    vmapping, indices, uvs = xatlas.parametrize(vertices, faces)
    vertices_out = vertices[vmapping]
    faces_out = np.asarray(indices, dtype=np.int64)
    uvs_out = np.asarray(uvs, dtype=np.float32)
    _phase(
        f"xatlas done V={len(vertices_out)} F={len(faces_out)} UV={len(uvs_out)}",
        t0,
    )

    out_mesh = trimesh.Trimesh(vertices=vertices_out, faces=faces_out, process=False)
    out_mesh.visual = trimesh.visual.texture.TextureVisuals(uv=uvs_out)

    out_path = os.path.join(save_dir, f"{save_name}_xatlas_uv.glb")
    out_mesh.export(out_path)
    if not _glb_has_texcoord(out_path):
        raise RuntimeError(f"xatlas export missing TEXCOORD: {out_path}")
    _phase(f"xatlas exported {out_path} ({os.path.getsize(out_path)} bytes)")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=str, default="cuda")
    parser.add_argument("--variant", type=str, default="sdxl", choices=["sdxl", "sd21"])
    parser.add_argument("--mesh", type=str, required=True)
    parser.add_argument("--image", type=str, required=True)
    parser.add_argument("--text", type=str, default="high quality")
    parser.add_argument("--seed", type=int, default=-1)
    parser.add_argument("--save_dir", type=str, default="./output")
    parser.add_argument("--save_name", type=str, default="i2tex_sample")
    parser.add_argument("--reference_conditioning_scale", type=float, default=1.0)
    parser.add_argument("--preprocess_mesh", action="store_true")
    parser.add_argument("--remove_bg", action="store_true")
    parser.add_argument(
        "--uv_backend",
        type=str,
        default=os.environ.get("MVADAPTER_UV_BACKEND", "xatlas"),
        choices=["xatlas", "open3d", "none"],
        help="xatlas=prod path; open3d=legacy UVAtlas; none=assume mesh already has UV",
    )
    parser.add_argument(
        "--decimate_faces",
        type=int,
        default=_env_int("MVADAPTER_DECIMATE_FACES", 80000),
        help="Target face count before xatlas (0 = no decimate). Default 80000.",
    )
    args = parser.parse_args()

    t_job = _phase(
        f"start variant={args.variant} mesh={args.mesh} image={args.image} "
        f"remove_bg={args.remove_bg} preprocess_mesh={args.preprocess_mesh} "
        f"uv_backend={args.uv_backend} decimate_faces={args.decimate_faces} "
        f"HF_HOME={os.environ.get('HF_HOME')} "
        f"TORCH_EXTENSIONS_DIR={os.environ.get('TORCH_EXTENSIONS_DIR')}"
    )

    tex_steps = _env_int("MVADAPTER_TEX_STEPS", 30)
    uv_size = _env_int("MVADAPTER_UV_SIZE", 2048)

    if args.variant == "sdxl":
        from scripts.inference_ig2mv_sdxl import prepare_pipeline, remove_bg, run_pipeline

        base_model = "stabilityai/stable-diffusion-xl-base-1.0"
        vae_model = "madebyollin/sdxl-vae-fp16-fix"
        height = width = 768
        if uv_size <= 0:
            uv_size = 2048
    elif args.variant == "sd21":
        from scripts.inference_ig2mv_sd import prepare_pipeline, remove_bg, run_pipeline

        base_model = "stabilityai/stable-diffusion-2-1-base"
        vae_model = None
        height = width = 512
        if uv_size <= 0:
            uv_size = 2048
    else:
        raise ValueError(f"Invalid variant: {args.variant}")

    device = args.device
    num_views = 6
    os.makedirs(args.save_dir, exist_ok=True)

    mesh_for_job = args.mesh
    uv_unwarp = True
    if args.uv_backend == "xatlas":
        mesh_for_job = ensure_mesh_uvs(
            args.mesh,
            args.save_dir,
            args.save_name,
            target_faces=int(args.decimate_faces),
        )
        uv_unwarp = False
    elif args.uv_backend == "none":
        if not _glb_has_texcoord(args.mesh):
            raise RuntimeError(
                f"--uv_backend=none but mesh has no TEXCOORD: {args.mesh}"
            )
        uv_unwarp = False
    else:
        _phase("uv_backend=open3d (legacy UVAtlas; may be very slow)")

    t0 = _phase(f"prepare_pipeline begin base={base_model} adapter=huanngzh/mv-adapter")
    pipe = prepare_pipeline(
        base_model=base_model,
        vae_model=vae_model,
        unet_model=None,
        lora_model=None,
        adapter_path="huanngzh/mv-adapter",
        scheduler=None,
        num_views=num_views,
        device=device,
        dtype=torch.float16,
    )
    _phase("prepare_pipeline done", t0)

    birefnet = None
    if args.remove_bg:
        t0 = _phase("BiRefNet load begin")
        birefnet = AutoModelForImageSegmentation.from_pretrained(
            "ZhengPeng7/BiRefNet", trust_remote_code=True
        )
        birefnet.to(args.device)
        transform_image = transforms.Compose(
            [
                transforms.Resize((1024, 1024)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )
        remove_bg_fn = lambda x: remove_bg(x, birefnet, transform_image, args.device)
        _phase("BiRefNet load done", t0)
    else:
        remove_bg_fn = None

    t0 = _phase("TexturePipeline init begin")
    texture_pipe = TexturePipeline(
        upscaler_ckpt_path="./checkpoints/RealESRGAN_x2plus.pth",
        inpaint_ckpt_path="./checkpoints/big-lama.pt",
        device=device,
    )
    _phase("TexturePipeline init done", t0)
    print(
        f"[i2tex] config steps={tex_steps} uv_size={uv_size} "
        f"view_upscale=False inpaint_mode=uv uv_unwarp={uv_unwarp} "
        f"uv_backend={args.uv_backend} decimate_faces={args.decimate_faces}",
        flush=True,
    )

    t0 = _phase(f"diffusion begin steps={tex_steps}")
    images, _, _, _ = run_pipeline(
        pipe,
        mesh_path=mesh_for_job,
        num_views=num_views,
        text=args.text,
        image=args.image,
        height=height,
        width=width,
        num_inference_steps=tex_steps,
        guidance_scale=3.0,
        seed=args.seed,
        reference_conditioning_scale=args.reference_conditioning_scale,
        negative_prompt="watermark, ugly, deformed, noisy, blurry, low contrast",
        device=device,
        remove_bg_fn=remove_bg_fn,
    )
    mv_path = os.path.join(args.save_dir, f"{args.save_name}.png")
    make_image_grid(images, rows=1).save(mv_path)
    _phase(f"diffusion done saved={mv_path}", t0)

    del pipe
    if birefnet is not None:
        del birefnet
    torch.cuda.empty_cache()
    _phase("VRAM freed before UV bake")

    t0 = _phase(
        f"UV bake begin uv_size={uv_size} preprocess_mesh={args.preprocess_mesh} "
        f"uv_unwarp={uv_unwarp} mesh={mesh_for_job}"
    )
    out = texture_pipe(
        mesh_path=mesh_for_job,
        save_dir=args.save_dir,
        save_name=args.save_name,
        uv_unwarp=uv_unwarp,
        preprocess_mesh=args.preprocess_mesh,
        uv_size=uv_size,
        rgb_path=mv_path,
        rgb_process_config=ModProcessConfig(view_upscale=False, inpaint_mode="uv"),
        camera_azimuth_deg=[x - 90 for x in [0, 90, 180, 270, 180, 180]],
    )
    _phase(f"UV bake done shaded={out.shaded_model_save_path}", t0)
    _phase("job complete", t_job)
    print(f"Output saved to {out.shaded_model_save_path}", flush=True)
