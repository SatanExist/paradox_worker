"""Convert Meta DINOv3 .pth (ViT-L/16 LVD) to HuggingFace folder for TRELLIS.2.

Uses the same key remapping as transformers' convert_dinov3_vit_to_hf.py,
but loads a *local* Meta checkpoint (HF gated repo is not required).

Example:
  python scripts/convert_dinov3_meta_to_hf.py ^
    --checkpoint \"%USERPROFILE%\\Downloads\\dinov3_vitl16_pretrain_lvd1689m-8aa4cbdd.pth\" ^
    --out-dir weights\\dinov3-vitl16-pretrain-lvd1689m
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import torch
from transformers import DINOv3ViTConfig, DINOv3ViTImageProcessorFast, DINOv3ViTModel

ORIGINAL_TO_CONVERTED_KEY_MAPPING = {
    r"cls_token": r"embeddings.cls_token",
    r"mask_token": r"embeddings.mask_token",
    r"storage_tokens": r"embeddings.register_tokens",
    r"patch_embed.proj": r"embeddings.patch_embeddings",
    r"periods": r"inv_freq",
    r"rope_embed": r"rope_embeddings",
    r"blocks.(\d+).attn.proj": r"layer.\1.attention.o_proj",
    r"blocks.(\d+).attn.": r"layer.\1.attention.",
    r"blocks.(\d+).ls(\d+).gamma": r"layer.\1.layer_scale\2.lambda1",
    r"blocks.(\d+).mlp.fc1": r"layer.\1.mlp.up_proj",
    r"blocks.(\d+).mlp.fc2": r"layer.\1.mlp.down_proj",
    r"blocks.(\d+).mlp": r"layer.\1.mlp",
    r"blocks.(\d+).norm": r"layer.\1.norm",
    r"w1": r"gate_proj",
    r"w2": r"up_proj",
    r"w3": r"down_proj",
}


def convert_old_keys_to_new_keys(state_dict_keys: list[str]) -> dict[str, str]:
    old_text = "\n".join(state_dict_keys)
    new_text = old_text
    for pattern, replacement in ORIGINAL_TO_CONVERTED_KEY_MAPPING.items():
        new_text = re.sub(pattern, replacement, new_text)
    return dict(zip(old_text.split("\n"), new_text.split("\n")))


def split_qkv(state_dict: dict) -> dict:
    for key in [x for x in list(state_dict.keys()) if "qkv" in x]:
        qkv = state_dict.pop(key)
        q, k, v = torch.chunk(qkv, 3, dim=0)
        state_dict[key.replace("qkv", "q_proj")] = q
        state_dict[key.replace("qkv", "k_proj")] = k
        state_dict[key.replace("qkv", "v_proj")] = v
    return state_dict


def vitl16_config() -> DINOv3ViTConfig:
    return DINOv3ViTConfig(
        patch_size=16,
        hidden_size=1024,
        intermediate_size=4096,
        num_hidden_layers=24,
        num_attention_heads=16,
        num_register_tokens=4,
        use_gated_mlp=False,
        hidden_act="gelu",
    )


def convert(checkpoint: Path, out_dir: Path) -> None:
    if not checkpoint.is_file():
        raise FileNotFoundError(checkpoint)

    print(f"Loading Meta checkpoint: {checkpoint} ({checkpoint.stat().st_size / 1e9:.2f} GB)")
    original_state_dict = torch.load(checkpoint, map_location="cpu", weights_only=True)
    original_state_dict = split_qkv(original_state_dict)
    original_keys = list(original_state_dict.keys())
    new_keys = convert_old_keys_to_new_keys(original_keys)

    converted_state_dict: dict[str, torch.Tensor] = {}
    for key in original_keys:
        new_key = new_keys[key]
        weight_tensor = original_state_dict[key]
        if "bias_mask" in key or "attn.k_proj.bias" in key or "local_cls_norm" in key:
            continue
        if key.startswith("projectors."):
            continue
        if "embeddings.mask_token" in new_key:
            weight_tensor = weight_tensor.unsqueeze(1)
        if "inv_freq" in new_key:
            continue
        # Match official convert_dinov3_vit_to_hf.py key layout.
        if new_key.startswith("layer."):
            new_key = f"model.{new_key}"
        converted_state_dict[new_key] = weight_tensor

    config = vitl16_config()
    model = DINOv3ViTModel(config).eval()
    try:
        model.load_state_dict(converted_state_dict, strict=True)
    except RuntimeError:
        # Some transformers builds store layers without the "model." prefix.
        flat = {
            (k[6:] if k.startswith("model.") else k): v
            for k, v in converted_state_dict.items()
        }
        model.load_state_dict(flat, strict=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir)
    image_processor = DINOv3ViTImageProcessorFast(
        do_resize=True,
        size={"height": 224, "width": 224},
        resample=2,
    )
    image_processor.save_pretrained(out_dir)
    print(f"Saved HF DINOv3 folder -> {out_dir.resolve()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path.home() / "Downloads" / "dinov3_vitl16_pretrain_lvd1689m-8aa4cbdd.pth",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("weights/dinov3-vitl16-pretrain-lvd1689m"),
    )
    args = parser.parse_args()
    convert(args.checkpoint, args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
