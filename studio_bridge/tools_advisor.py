"""Advice on a game_prep result: Claude reads the report (and views of the model when there are
some) and says whether it is good enough, what looks wrong, and which run to try next.

Advice only. Claude never touches the geometry: it picks one of our own operations and its
parameters, and the person (or the site) decides whether to run it. Fixing stays with the
algorithms, so a repair never depends on a language model.

  advise([report, ...], views=[("original, front", png_bytes), ("5k, front", png_bytes)],
         goal="mobile game, background prop")

Needs ANTHROPIC_API_KEY (or another credential the anthropic SDK finds) in the lab.
"""

from __future__ import annotations

import base64
import json
from typing import Any

MODEL = "claude-opus-5-5"

# Same limits the site checks (POLY_LAB src/lib/operations.ts), so advice can be run as is.
TRIS = (500, 200_000)
ERROR_PCT = (0.05, 5.0)
TEXTURE_SIZES = (512, 1024, 2048)

SYSTEM = """You review 3D models that PolyLab has made lighter for game engines, and advise the person what to do next. You only advise: the geometry is changed by PolyLab's own algorithms, never by you.

What you get: one or more reports of the game_prep tool, each for one run on the same original model, and sometimes rendered views (original and result from the same camera). A report has:
- before: the original (triangles, file size, textures).
- after.triangles, after.fileMb, after.textureMaxPx; after.targetTris (the budget); after.maxErrorPct when the run was in quality mode.
- after.deviation.meanPct / maxPct: how far the surface moved, as % of the model's largest side, measured both ways. Mean under ~0.15% is invisible; a max far above the mean (over ~1%) means a part went missing — an antenna, a barrel, an edge.
- after.deviation.normalMeanDeg / normalP95Deg: how much the shading normals turned. Under ~12° mean shades like the original; over ~25° the surface looks crumpled or shiny under light even if the shape is right.
- steps: what the tool did ("UV seams loosened to reach the budget" means textures near seams may have shifted; "kept N vertices where a first cut lost detail" means a second pass protected lost spots).

What PolyLab can run (operation game_prep):
- Budget mode: targetTris (500–200000) — exactly that many triangles.
- Quality mode: maxErrorPct (0.05–5) — the fewest triangles that keep the surface within that % of the model's size; targetTris is then the most it may keep.
- textureSize: 512, 1024 or 2048.
There is no normal-map baking yet: below roughly 1% of the original triangle count, models from AI generators (1–2M triangles) look crumpled whatever the settings. Say so plainly when that is the cause, rather than suggesting settings that cannot fix it.

How to judge: what matters is whether the model looks like the original in a game at the distance it will be seen, at the lowest cost. Use the person's goal when given (mobile vs PC, hero vs background prop, how close the camera gets); without one, assume a PC game prop seen at medium distance. Prefer quality mode when the person has no hard triangle limit. Trust the views over the numbers when they disagree, and say which you relied on.

Write the explanation for the person in plain English, two to four short sentences, no jargon beyond "triangles", "texture" and "shading". If the current result is good enough, say so and set next.action to "keep" (the other next fields then repeat the current run's settings; maxErrorPct is 0 in budget mode)."""

ADVICE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["good", "acceptable", "poor"]},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["lost_detail", "shading", "texture", "budget", "other"]},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "note": {"type": "string"},
                },
                "required": ["kind", "severity", "note"],
                "additionalProperties": False,
            },
        },
        "next": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["keep", "run"]},
                "mode": {"type": "string", "enum": ["budget", "quality"]},
                "targetTris": {"type": "integer"},
                "maxErrorPct": {"type": "number"},
                "textureSize": {"type": "integer", "enum": list(TEXTURE_SIZES)},
                "why": {"type": "string"},
            },
            "required": ["action", "mode", "targetTris", "maxErrorPct", "textureSize", "why"],
            "additionalProperties": False,
        },
        "basis": {"type": "string", "enum": ["numbers", "views", "both"]},
        "explanation": {"type": "string"},
    },
    "required": ["verdict", "issues", "next", "basis", "explanation"],
    "additionalProperties": False,
}


class AdviceError(RuntimeError):
    """Claude could not give advice (declined, cut off, or answered outside the schema)."""


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def run_params(advice: dict[str, Any]) -> dict[str, Any] | None:
    """The `params` for POST /api/generations/<id>/versions that carry out the advice, kept
    inside the limits the site accepts; None when the advice is to keep what there is."""
    step = advice.get("next") or {}
    if step.get("action") != "run":
        return None
    params: dict[str, Any] = {
        "targetTris": int(_clamp(int(step["targetTris"]), *TRIS)),
        "textureSize": step["textureSize"] if step["textureSize"] in TEXTURE_SIZES else 2048,
    }
    if step["mode"] == "quality" and step.get("maxErrorPct"):
        params["maxErrorPct"] = round(_clamp(float(step["maxErrorPct"]), *ERROR_PCT), 2)
    return params


def _content(reports: list[dict[str, Any]], views: list[tuple[str, bytes]], goal: str | None) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for label, png in views:
        blocks.append({"type": "text", "text": f"View: {label}"})
        blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(png).decode()},
        })
    blocks.append({
        "type": "text",
        "text": (
            f"Person's goal: {goal or 'not given'}\n\n"
            f"game_prep reports, oldest first:\n{json.dumps(reports, indent=1, ensure_ascii=False)}\n\n"
            "Advise on the latest run."
        ),
    })
    return blocks


def advise(
    reports: list[dict[str, Any]],
    views: list[tuple[str, bytes]] = (),
    goal: str | None = None,
    client: Any = None,
) -> dict[str, Any]:
    """Advice on the latest of `reports` (all runs on one original), as ADVICE_SCHEMA, plus
    `params`: what to send to run the suggested next step (None when there is none)."""
    if not reports:
        raise ValueError("no report to advise on")
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        # Declined requests are re-run on the recommended fallback model instead of failing.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": ADVICE_SCHEMA}},
        cache_control={"type": "ephemeral"},
        system=SYSTEM,
        messages=[{"role": "user", "content": _content(reports, list(views), goal)}],
    )
    if response.stop_reason == "refusal":
        raise AdviceError("the model declined to advise on this model")
    if response.stop_reason == "max_tokens":
        raise AdviceError("the advice was cut off")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        advice = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AdviceError("the advice was not valid JSON") from exc
    advice["params"] = run_params(advice)
    advice["model"] = response.model
    return advice
