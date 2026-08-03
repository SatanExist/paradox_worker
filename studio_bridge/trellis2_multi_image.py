"""
TRELLIS.2 multi-image conditioning (community PR #104 style).

Stock microsoft/TRELLIS.2 main has no inject_sampler_multi_image; we monkeypatch
it onto Trellis2ImageTo3DPipeline at runtime so Docker can stay on main.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import List, Literal, Optional

import torch
from PIL import Image

FusionMode = Literal["stochastic", "multidiffusion"]


def inject_sampler_multi_image(
    self,
    sampler_name: str,
    num_images: int,
    num_steps: int,
    mode: FusionMode = "stochastic",
):
    """
    Context manager: temporarily fuse multi-image cond into a sampler step.

    - stochastic: cycle images across steps (memory efficient)
    - multidiffusion: average predictions from all images (higher quality / VRAM)
    """

    @contextmanager
    def _inject():
        sampler = getattr(self, sampler_name)
        setattr(sampler, "_old_inference_model", sampler._inference_model)

        if mode == "stochastic":
            if num_images > num_steps:
                print(
                    f"Warning: num_images ({num_images}) > steps ({num_steps}) for "
                    f"{sampler_name}; may degrade."
                )
            counter = {"value": 0}

            def _new_inference_model(this, model, x_t, t, cond, **kwargs):
                cond_idx = counter["value"] % num_images
                counter["value"] += 1
                cond_i = cond[cond_idx : cond_idx + 1]
                return this._old_inference_model(model, x_t, t, cond=cond_i, **kwargs)

        elif mode == "multidiffusion":
            from trellis2.pipelines.samplers import FlowEulerSampler

            def _new_inference_model(
                this,
                model,
                x_t,
                t,
                cond,
                neg_cond,
                guidance_strength,
                guidance_interval,
                guidance_rescale=0.0,
                **kwargs,
            ):
                if guidance_interval[0] <= t <= guidance_interval[1]:
                    preds = [
                        FlowEulerSampler._inference_model(
                            this, model, x_t, t, cond[i : i + 1], **kwargs
                        )
                        for i in range(len(cond))
                    ]
                    pred = sum(preds) / len(preds)
                    neg_pred = FlowEulerSampler._inference_model(
                        this, model, x_t, t, neg_cond, **kwargs
                    )
                    pred_cfg = guidance_strength * pred + (1 - guidance_strength) * neg_pred
                    if guidance_rescale > 0:
                        x_0_pos = this._pred_to_xstart(x_t, t, pred)
                        x_0_cfg = this._pred_to_xstart(x_t, t, pred_cfg)
                        std_pos = x_0_pos.std(dim=list(range(1, x_0_pos.ndim)), keepdim=True)
                        std_cfg = x_0_cfg.std(dim=list(range(1, x_0_cfg.ndim)), keepdim=True)
                        x_0_rescaled = x_0_cfg * (std_pos / std_cfg)
                        x_0 = guidance_rescale * x_0_rescaled + (1 - guidance_rescale) * x_0_cfg
                        pred_cfg = this._xstart_to_pred(x_t, t, x_0)
                    return pred_cfg
                preds = [
                    FlowEulerSampler._inference_model(
                        this, model, x_t, t, cond[i : i + 1], **kwargs
                    )
                    for i in range(len(cond))
                ]
                return sum(preds) / len(preds)

        else:
            raise ValueError(f"Unsupported multi-image mode: {mode}")

        sampler._inference_model = _new_inference_model.__get__(sampler, type(sampler))
        try:
            yield
        finally:
            sampler._inference_model = sampler._old_inference_model
            delattr(sampler, "_old_inference_model")

    return _inject()


def patch_pipeline(pipeline) -> None:
    """Attach inject_sampler_multi_image if missing (idempotent)."""
    if getattr(pipeline, "_paradox_multi_image_patched", False):
        return
    # Bound method on this instance (works even if class already has a stub).
    pipeline.inject_sampler_multi_image = inject_sampler_multi_image.__get__(
        pipeline, type(pipeline)
    )
    pipeline._paradox_multi_image_patched = True
    print("TRELLIS.2 multi-image sampler injection patched.")


def _stack_conds(pipeline, images: List[Image.Image], resolution: int) -> dict:
    cond_list = [pipeline.get_cond([img], resolution)["cond"] for img in images]
    stacked = torch.cat(cond_list, dim=0)
    return {
        "cond": stacked,
        "neg_cond": torch.zeros_like(stacked[:1]),
    }


@torch.no_grad()
def run_multi_image(
    pipeline,
    images: List[Image.Image],
    *,
    seed: int = 42,
    preprocess_image: bool = True,
    pipeline_type: Optional[str] = None,
    sparse_structure_sampler_params: Optional[dict] = None,
    shape_slat_sampler_params: Optional[dict] = None,
    tex_slat_sampler_params: Optional[dict] = None,
    max_num_tokens: int = 49152,
    fusion_mode: FusionMode = "multidiffusion",
):
    """
    Multi-view image -> meshes, mirroring example_multi_image.py from PR #104.
    """
    if len(images) < 2:
        raise ValueError("run_multi_image requires at least 2 images")

    patch_pipeline(pipeline)
    pipeline_type = pipeline_type or pipeline.default_pipeline_type
    ss_params = dict(sparse_structure_sampler_params or {})
    shape_params = dict(shape_slat_sampler_params or {})
    tex_params = dict(tex_slat_sampler_params or {})

    prepared = []
    for img in images:
        if preprocess_image:
            prepared.append(pipeline.preprocess_image(img))
        else:
            prepared.append(img)

    torch.manual_seed(seed)
    num_images = len(prepared)
    cond_512 = _stack_conds(pipeline, prepared, 512)
    cond_1024 = None
    if pipeline_type != "512":
        cond_1024 = _stack_conds(pipeline, prepared, 1024)

    ss_res = {"512": 32, "1024": 64, "1024_cascade": 32, "1536_cascade": 32}[pipeline_type]
    ss_steps = int(ss_params.get("steps", pipeline.sparse_structure_sampler_params.get("steps", 12)))
    shape_steps = int(shape_params.get("steps", pipeline.shape_slat_sampler_params.get("steps", 12)))
    tex_steps = int(tex_params.get("steps", pipeline.tex_slat_sampler_params.get("steps", 12)))

    with pipeline.inject_sampler_multi_image(
        "sparse_structure_sampler", num_images, ss_steps, mode=fusion_mode
    ):
        coords = pipeline.sample_sparse_structure(cond_512, ss_res, num_samples=1, sampler_params=ss_params)

    if pipeline_type == "512":
        with pipeline.inject_sampler_multi_image(
            "shape_slat_sampler", num_images, shape_steps, mode=fusion_mode
        ):
            shape_slat = pipeline.sample_shape_slat(
                cond_512, pipeline.models["shape_slat_flow_model_512"], coords, shape_params
            )
        tex_cond = cond_512
        tex_model = pipeline.models["tex_slat_flow_model_512"]
        res = 512
    elif pipeline_type == "1024":
        with pipeline.inject_sampler_multi_image(
            "shape_slat_sampler", num_images, shape_steps, mode=fusion_mode
        ):
            shape_slat = pipeline.sample_shape_slat(
                cond_1024, pipeline.models["shape_slat_flow_model_1024"], coords, shape_params
            )
        tex_cond = cond_1024
        tex_model = pipeline.models["tex_slat_flow_model_1024"]
        res = 1024
    else:
        target_res = 1024 if pipeline_type == "1024_cascade" else 1536
        with pipeline.inject_sampler_multi_image(
            "shape_slat_sampler", num_images, shape_steps, mode=fusion_mode
        ):
            shape_slat, res = pipeline.sample_shape_slat_cascade(
                cond_512,
                cond_1024,
                pipeline.models["shape_slat_flow_model_512"],
                pipeline.models["shape_slat_flow_model_1024"],
                512,
                target_res,
                coords,
                shape_params,
                max_num_tokens=max_num_tokens,
            )
        tex_cond = cond_1024
        tex_model = pipeline.models["tex_slat_flow_model_1024"]

    with pipeline.inject_sampler_multi_image(
        "tex_slat_sampler", num_images, tex_steps, mode=fusion_mode
    ):
        tex_slat = pipeline.sample_tex_slat(tex_cond, tex_model, shape_slat, tex_params)

    torch.cuda.empty_cache()
    return pipeline.decode_latent(shape_slat, tex_slat, res)
