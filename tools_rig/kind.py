"""What the model looks like: character / statue / object, for the auto-rig's report (replaces the "stick of bones" rule).
Google SigLIP 2 (Apache 2.0) zero-shot on two Blender pictures (front, three-quarter), the exact v1 of classify.py:
tested on 57 models (42 known + 15 new, truth set by eye before the runs): no character was ever called a statue or an
object; its misses go the safe way (some props called "character": they just get a rig without a note).
The rig is made either way; this only adds an honest note when the model doesn't look like a character."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
BLENDER = os.environ.get("BLENDER_BIN") or shutil.which("blender")
SIGLIP = os.environ.get("SIGLIP_DIR", "")
LABELS = {"character": "a 3D model of a character: a person, a creature or an animal",
          "statue": "a 3D model of a statue or a bust",
          "object": "a 3D model of an object, a vehicle or a building"}
_model = None


def available():
    """The pictures need Blender and the SigLIP weights; where either is missing the rig comes without the note."""
    return bool(BLENDER and SIGLIP and os.path.isfile(os.path.join(SIGLIP, "config.json")))


def look(glb):
    """-> {"pick": label, <label>: mean score} for one GLB."""
    global _model
    import torch
    from PIL import Image
    from transformers import AutoModel, AutoProcessor
    if _model is None:
        _model = AutoModel.from_pretrained(SIGLIP).eval(), AutoProcessor.from_pretrained(SIGLIP)
    model, proc = _model
    with tempfile.TemporaryDirectory() as tmp:
        pre = os.path.join(tmp, "v")
        subprocess.run([BLENDER, "-b", "-P", str(HERE / "shot2.py"), "--", os.path.abspath(glb), pre],
                       check=True, capture_output=True, timeout=600)
        imgs = [Image.open(f"{pre}_{t}.png").convert("RGB") for t in ("front", "q")]
        with torch.no_grad():
            x = proc(text=list(LABELS.values()), images=imgs, padding="max_length", max_length=64, return_tensors="pt")
            p = torch.sigmoid(model(**x).logits_per_image).mean(0)
    s = {k: round(float(v), 4) for k, v in zip(LABELS, p)}
    return {"pick": max(s, key=s.get), **s}
