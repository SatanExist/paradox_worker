"""Build-time smoke for the rig image (no GPU at build): everything auto_rig loads imports, the weights are there,
the SDPA change is applied, the handler sees auto_rig. Run with cwd = /app/SkinTokens."""
from __future__ import annotations

import os
import sys
from pathlib import Path

repo = Path(os.environ.get("SKINTOKENS_DIR", "/app/SkinTokens"))
sys.path[:0] = [str(repo), "/app", "/app/tools_rig"]

for name in ("experiments/skin_vae_2_10_32768/last.ckpt",
             "experiments/articulation_xl_quantization_256_token_4/grpo_1400.ckpt",
             "models/Qwen3-0.6B/config.json"):
    assert (repo / name).is_file(), f"missing {name}"
assert 'attn_implementation="sdpa"' in (repo / "src/model/tokenrig.py").read_text(), "SDPA patch not applied"

import bpy  # noqa: F401,E402  Blender as a module: SkinTokens' loader and weight transfer
import igl  # noqa: F401,E402
import scipy.sparse  # noqa: F401,E402
import torch  # noqa: E402

# Michelangelo asks the GPU's name when it is imported (an H100 check for flash-attn 3). The build has no GPU, so this
# import check alone answers "no GPU"; at run time the real GPU answers.
if not torch.cuda.is_available():
    torch.cuda.get_device_name = lambda *a, **k: "no GPU at build"
import demo  # noqa: F401,E402  SkinTokens' entry (model, tokenizer, bpy server client)
import envelope, grown, judge, judge4, kind, ourxfer, rename  # noqa: F401,E401,E402
from studio_bridge.tools_ops import OPERATIONS  # noqa: E402

assert "auto_rig" in OPERATIONS
assert not kind.available(), "the picture note is meant to be off in this image"
print("torch", torch.__version__, "cuda", torch.version.cuda, "bpy", bpy.app.version_string)
print("rig image ok:", sorted(OPERATIONS))
