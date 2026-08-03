"""Smoke test for TRELLIS.2 RunPod endpoint (quality tier).

Uses runpod_queue_watchdog for zombie IN_QUEUE detect → heal ghosts → retry.
"""

from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from runpod_billing import estimate_from_status_payload
from runpod_queue_watchdog import run_with_zombie_retries

load_dotenv()

ENDPOINT_ID = os.getenv("RUNPOD_ENDPOINT_ID_TRELLIS2", "")
ENDPOINT_ID_SECONDARY = os.getenv("RUNPOD_ENDPOINT_ID_TRELLIS2_SECONDARY", "").strip()
API_KEY = os.getenv("RUNPOD_API_KEY")

DEFAULT_IMAGE_URL = (
    "https://raw.githubusercontent.com/microsoft/TRELLIS/main/assets/example_image/"
    "typical_misc_monster_chest.png"
)

DEFAULT_ZOMBIE_AFTER_S = float(os.getenv("TRELLIS2_ZOMBIE_AFTER_S", "90"))
DEFAULT_ZOMBIE_RETRIES = int(os.getenv("TRELLIS2_ZOMBIE_RETRIES", "2"))

if not API_KEY:
    raise ValueError("RUNPOD_API_KEY not found in .env")
if not ENDPOINT_ID:
    raise ValueError("Set RUNPOD_ENDPOINT_ID_TRELLIS2 in .env (dedicated quality endpoint)")


def sanitize(payload: dict) -> dict:
    out = dict(payload)
    job_out = out.get("output")
    if isinstance(job_out, dict) and isinstance(job_out.get("model_base64"), str):
        job_out = dict(job_out)
        job_out["model_base64"] = f"<omitted base64, len={len(job_out['model_base64'])}>"
        out["output"] = job_out
    return out


def _sampler_dict(
    *,
    steps,
    guidance,
    guidance_rescale,
    rescale_t,
    guidance_interval,
    default_steps: int,
    default_guidance: float,
    default_rescale: float,
    default_rescale_t: float,
    default_interval: list[float],
) -> dict:
    out = {
        "steps": steps if steps is not None else default_steps,
        "guidance_strength": guidance if guidance is not None else default_guidance,
        "guidance_rescale": (
            guidance_rescale if guidance_rescale is not None else default_rescale
        ),
        "rescale_t": rescale_t if rescale_t is not None else default_rescale_t,
    }
    if guidance_interval is not None:
        out["guidance_interval"] = guidance_interval
    else:
        out["guidance_interval"] = list(default_interval)
    return out


def build_input(args: argparse.Namespace) -> dict:
    job_input = {
        "pipeline_type": args.pipeline_type,
        "texture_mode": args.texture_mode,
        "seed": args.seed,
        "decimation_target": args.decimation_target,
        "return_base64": args.return_base64,
    }
    if args.image_urls:
        job_input["image_urls"] = list(args.image_urls)
        # Keep first as image_url for older logs / compatibility.
        job_input["image_url"] = args.image_urls[0]
    else:
        job_input["image_url"] = args.image_url
    if args.multi_image_mode:
        job_input["multi_image_mode"] = args.multi_image_mode
    if args.texture_mode == "textured":
        job_input["texture_size"] = args.texture_size
    if args.no_preprocess:
        job_input["preprocess_image"] = False
    if args.no_remesh:
        job_input["remesh"] = False
    if args.remesh_project is not None:
        job_input["remesh_project"] = args.remesh_project
    if args.remesh_band is not None:
        job_input["remesh_band"] = args.remesh_band
    if args.max_hole_perimeter is not None:
        job_input["max_hole_perimeter"] = args.max_hole_perimeter
    if args.remove_small_cc is not None:
        job_input["remove_small_cc"] = args.remove_small_cc
    if args.quality_max:
        job_input["quality_max"] = True
        # Full tutorial/community preset; CLI flags still override when set.
        if args.pipeline_type == "1024_cascade" and not args.force_pipeline:
            job_input["pipeline_type"] = "1536_cascade"
        if args.decimation_target == 500_000 and not args.force_decimation:
            job_input["decimation_target"] = 800_000
        if not args.no_remesh:
            job_input["remesh"] = False
        if not args.no_preprocess:
            job_input["preprocess_image"] = False
        job_input["max_num_tokens"] = args.max_num_tokens
        job_input["sparse_structure_sampler_params"] = _sampler_dict(
            steps=args.ss_steps,
            guidance=args.ss_guidance,
            guidance_rescale=args.ss_guidance_rescale,
            rescale_t=args.ss_rescale_t,
            guidance_interval=args.ss_guidance_interval,
            default_steps=50,
            default_guidance=8.0,
            default_rescale=0.7,
            default_rescale_t=6.0,
            default_interval=[0.6, 1.0],
        )
        job_input["shape_slat_sampler_params"] = _sampler_dict(
            steps=args.shape_steps,
            guidance=args.shape_guidance,
            guidance_rescale=args.shape_guidance_rescale,
            rescale_t=args.shape_rescale_t,
            guidance_interval=args.shape_guidance_interval,
            default_steps=50,
            default_guidance=8.5,
            default_rescale=0.5,
            default_rescale_t=6.0,
            default_interval=[0.6, 1.0],
        )
    elif (
        args.ss_steps is not None
        or args.shape_steps is not None
        or args.ss_guidance_interval is not None
        or args.shape_guidance_interval is not None
    ):
        job_input["max_num_tokens"] = args.max_num_tokens
        job_input["sparse_structure_sampler_params"] = _sampler_dict(
            steps=args.ss_steps,
            guidance=args.ss_guidance,
            guidance_rescale=args.ss_guidance_rescale,
            rescale_t=args.ss_rescale_t,
            guidance_interval=args.ss_guidance_interval,
            default_steps=12,
            default_guidance=7.5,
            default_rescale=0.7,
            default_rescale_t=5.0,
            default_interval=[0.6, 1.0],
        )
        job_input["shape_slat_sampler_params"] = _sampler_dict(
            steps=args.shape_steps,
            guidance=args.shape_guidance,
            guidance_rescale=args.shape_guidance_rescale,
            rescale_t=args.shape_rescale_t,
            guidance_interval=args.shape_guidance_interval,
            default_steps=12,
            default_guidance=7.5,
            default_rescale=0.5,
            default_rescale_t=3.0,
            default_interval=[0.6, 1.0],
        )
    return job_input


def glb_mesh_stats(path: Path) -> dict:
    """Count vertices/faces from GLB without heavy deps (JSON chunk accessors)."""
    import json
    import struct

    data = path.read_bytes()
    if len(data) < 20 or data[0:4] != b"glTF":
        raise ValueError(f"Not a GLB: {path}")
    json_len = struct.unpack_from("<I", data, 12)[0]
    chunk = json.loads(data[20 : 20 + json_len])
    accessors = chunk.get("accessors") or []
    meshes = chunk.get("meshes") or []
    verts = 0
    faces = 0
    for mesh in meshes:
        for prim in mesh.get("primitives") or []:
            attrs = prim.get("attributes") or {}
            pos = attrs.get("POSITION")
            if pos is not None and pos < len(accessors):
                verts += int(accessors[pos].get("count") or 0)
            idx = prim.get("indices")
            if idx is not None and idx < len(accessors):
                faces += int(accessors[idx].get("count") or 0) // 3
            elif pos is not None and pos < len(accessors):
                # triangle soup without indices
                faces += int(accessors[pos].get("count") or 0) // 3
    return {"vertices": verts, "faces": faces, "bytes": path.stat().st_size}


def print_run_metrics(final: dict, save_path: Path | None) -> None:
    output = final.get("output") or {}
    if not isinstance(output, dict):
        return
    billing = output.get("billing") or {}
    handler = billing.get("handler_ms") or {}
    mesh = output.get("mesh_stats") or {}
    print("--- metrics ---")
    if handler:
        print(
            "timing_ms:",
            f"inference={handler.get('inference_ms')}",
            f"glb_export={handler.get('glb_export_ms')}",
            f"model_load={handler.get('model_load_ms')}",
            f"total={handler.get('total_ms')}",
            f"delay={final.get('delayTime')}",
            f"execution={final.get('executionTime')}",
        )
    if mesh:
        print(f"mesh_stats (worker): verts={mesh.get('vertices')} faces={mesh.get('faces')}")
    if save_path and save_path.is_file():
        local = glb_mesh_stats(save_path)
        print(
            f"mesh_stats (local GLB): verts={local['vertices']} "
            f"faces={local['faces']} bytes={local['bytes']}"
        )


def save_output(final: dict, save_path: Path) -> None:
    output = final.get("output") or {}
    if not isinstance(output, dict):
        raise RuntimeError(f"COMPLETED without output dict: {final}")

    model_url = output.get("model_url")
    if isinstance(model_url, str) and model_url.startswith("http"):
        response = requests.get(model_url, timeout=120)
        response.raise_for_status()
        save_path.write_bytes(response.content)
        print(f"Saved from model_url -> {save_path.resolve()} bytes={save_path.stat().st_size}")
        return

    b64 = output.get("model_base64")
    if isinstance(b64, str) and b64:
        save_path.write_bytes(base64.b64decode(b64))
        print(f"Saved from model_base64 -> {save_path.resolve()} bytes={save_path.stat().st_size}")
        return

    model_path = output.get("model_path")
    omitted = output.get("base64_omitted")
    raise RuntimeError(
        "No downloadable artifact in output. "
        f"model_path={model_path!r} model_url={model_url!r} "
        f"hint={omitted!r}. Configure R2_* on the endpoint or pass --return-base64 for small GLBs."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="RunPod TRELLIS.2 smoke test.")
    parser.add_argument("--image-url", default=DEFAULT_IMAGE_URL)
    parser.add_argument(
        "--image-urls",
        nargs="+",
        default=None,
        help="Multi-view refs (2+). Uses TRELLIS.2 multi-image fusion when length>=2.",
    )
    parser.add_argument(
        "--multi-image-mode",
        choices=["stochastic", "multidiffusion"],
        default=None,
        help="Multi-view fusion (default worker: multidiffusion)",
    )
    parser.add_argument(
        "--pipeline-type",
        default="1024_cascade",
        choices=["512", "1024", "1024_cascade", "1536_cascade"],
    )
    parser.add_argument("--texture-size", type=int, default=2048, choices=[1024, 2048, 4096])
    parser.add_argument(
        "--texture-mode",
        default="clay",
        choices=["clay", "textured"],
        help="clay = gray mesh without bake (default); textured = legacy UV bake",
    )
    parser.add_argument("--decimation-target", type=int, default=500_000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--save", help="Save GLB to this path on COMPLETED")
    parser.add_argument(
        "--return-base64",
        action="store_true",
        help="Ask worker to include model_base64 when under size limit",
    )
    parser.add_argument("--no-preprocess", action="store_true")
    parser.add_argument("--no-remesh", action="store_true")
    parser.add_argument(
        "--remesh-project",
        type=float,
        default=None,
        help="project_back for remesh_narrow_band_dc (0..1; official to_glb often 0.9)",
    )
    parser.add_argument(
        "--remesh-band",
        type=float,
        default=None,
        help="narrow-band remesh band (default 1.0)",
    )
    parser.add_argument(
        "--max-hole-perimeter",
        type=float,
        default=None,
        help="CuMesh fill_holes max perimeter (default 0.03)",
    )
    parser.add_argument(
        "--remove-small-cc",
        type=float,
        default=None,
        help="remove_small_connected_components threshold (no-remesh path; default 1e-5)",
    )
    parser.add_argument(
        "--quality-max",
        action="store_true",
        help="Tutorial/community max-quality preset (1536, steps50, high guidance, no remesh)",
    )
    parser.add_argument(
        "--force-pipeline",
        action="store_true",
        help="With --quality-max, keep --pipeline-type as given",
    )
    parser.add_argument(
        "--force-decimation",
        action="store_true",
        help="With --quality-max, keep --decimation-target as given",
    )
    parser.add_argument("--max-num-tokens", type=int, default=65536)
    parser.add_argument("--ss-steps", type=int, default=None)
    parser.add_argument("--ss-guidance", type=float, default=None)
    parser.add_argument("--ss-guidance-rescale", type=float, default=None)
    parser.add_argument("--ss-rescale-t", type=float, default=None)
    parser.add_argument(
        "--ss-guidance-interval",
        type=float,
        nargs=2,
        metavar=("LO", "HI"),
        default=None,
        help="SS CFG interval on t, e.g. 0.0 1.0 (default HF 0.6 1.0)",
    )
    parser.add_argument("--shape-steps", type=int, default=None)
    parser.add_argument("--shape-guidance", type=float, default=None)
    parser.add_argument("--shape-guidance-rescale", type=float, default=None)
    parser.add_argument("--shape-rescale-t", type=float, default=None)
    parser.add_argument(
        "--shape-guidance-interval",
        type=float,
        nargs=2,
        metavar=("LO", "HI"),
        default=None,
        help="Shape SLat CFG interval on t, e.g. 0.0 1.0 (default HF 0.6 1.0)",
    )
    parser.add_argument(
        "--zombie-after",
        type=float,
        default=DEFAULT_ZOMBIE_AFTER_S,
        help="Seconds of IN_QUEUE+idle/ready before heal/retry (default 90)",
    )
    parser.add_argument(
        "--zombie-retries",
        type=int,
        default=DEFAULT_ZOMBIE_RETRIES,
        help="Extra submit attempts after zombie detect (default 2)",
    )
    parser.add_argument(
        "--no-zombie-watch",
        action="store_true",
        help="Disable zombie detect/heal (wait until max timeout only)",
    )
    parser.add_argument(
        "--purge-on-heal",
        action="store_true",
        help="Also POST purge-queue when healing ghosts",
    )
    parser.add_argument(
        "--heal-before-submit",
        action="store_true",
        help="Delete EXITED ghosts before each submit (can kill warm workers)",
    )
    args = parser.parse_args()

    job_input = build_input(args)
    print(f"Endpoint: {ENDPOINT_ID}")
    if ENDPOINT_ID_SECONDARY:
        print(f"Secondary: {ENDPOINT_ID_SECONDARY}")
    print(f"Job input: {job_input}")

    if args.no_zombie_watch:
        from runpod_queue_watchdog import submit_job, wait_for_job

        job_id = submit_job(ENDPOINT_ID, API_KEY, job_input)
        final = wait_for_job(
            ENDPOINT_ID,
            job_id,
            API_KEY,
            zombie_after_s=1e9,
            max_wait_s=30 * 60,
        )
        endpoint_used = ENDPOINT_ID
    else:
        endpoint_used, final = run_with_zombie_retries(
            ENDPOINT_ID,
            API_KEY,
            job_input,
            secondary_endpoint_id=ENDPOINT_ID_SECONDARY or None,
            zombie_after_s=args.zombie_after,
            zombie_retries=args.zombie_retries,
            max_wait_s=30 * 60,
            heal=True,
            heal_before_submit=args.heal_before_submit,
            purge_on_heal=args.purge_on_heal,
        )

    print(f"Final endpoint: {endpoint_used}")
    print("Final status:")
    print(sanitize(final))

    if final.get("status") == "COMPLETED":
        estimate = estimate_from_status_payload(final, endpoint_id=endpoint_used, api_key=API_KEY)
        print(f"Cost estimate: {estimate['cost_usd_formatted']} USD")
        output = final.get("output") or {}
        if isinstance(output, dict):
            print(
                "delivery=",
                output.get("delivery"),
                "bytes=",
                output.get("model_bytes"),
                "path=",
                output.get("model_path"),
                "url=",
                output.get("model_url"),
            )
        if args.save:
            save_path = Path(args.save)
            save_output(final, save_path)
            print_run_metrics(final, save_path)
        else:
            print_run_metrics(final, None)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
