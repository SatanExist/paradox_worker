# Print corpus

Regression set for print prep (`studio_bridge/print_solid.py` via `tools_ops.print_prep`).
Every change to the print recipe is run over all models here, so a fix for one model can't quietly
break another. A change is judged by its effect on all models, by the numbers, never tuned to one model.
Plan and reasoning: `POLY_LAB/memory-bank/handoff-print.md` (start here) and
`POLY_LAB/memory-bank/print-repair-research-2026-10.md`.

- `manifest.tsv`: one model per line: id, engine, kind, print height in mm, where it came from (paths relative to the
  author's D:/AI_HUB, for the record only).
- `models/`: frozen copies of the inputs, in Git LFS (`git lfs pull`). Never edit them; a new problem model is added as
  a new line.
- `run.py`: runs every model not yet run with the current recipe (the last paradox_worker commit that touched the print files, + `-dirty` when the print
  files have changes), one process each, low priority, 30 min limit, peak RAM over the process tree.
  Rows go to `results.jsonl` (kept in git), the output GLBs and logs to `out/` (not kept).
- `report.py`: a table for one recipe, or two recipes side by side; `--times` shows where the time goes.
- `heat.py <id>`: the result coloured by how far it moved from the original, into `view/`; open `view/index.html`
  over http (`python -m http.server 8765` in `view/`).
- `logs/`: the stdout of every corpus run so far.

```
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt

.venv/Scripts/python.exe run.py                      # everything new for this recipe
.venv/Scripts/python.exe run.py crown knight         # just these
.venv/Scripts/python.exe run.py --max-faces=300000   # the light ones (~15, minutes each, <= 2.5 GB)
.venv/Scripts/python.exe run.py --min-faces=300001   # the heavy ones (27, hours, up to 14 GB)
.venv/Scripts/python.exe report.py 3769d84           # one recipe
.venv/Scripts/python.exe report.py ca68824-dirty 3769d84
.venv/Scripts/python.exe report.py --times 3769d84   # time per candidate + the rest
```

What counts as a pass: watertight, 1 part, lost ≤ 0.1%, result wall 2V/A ≥ 1 mm, and as little changed (where it can
be seen) as possible.

42 models from 11 engines (TRELLIS.2, Hunyuan 2 and 3.1, Hi3DGen, Direct3D-S2, Step1X-3D, Pixal3D, TripoSR, Rodin,
Meshy, Tripo), all from our own showcase and engine trials. Still to add: real studio generations, more jewelry,
hair/fur, thin blades.
