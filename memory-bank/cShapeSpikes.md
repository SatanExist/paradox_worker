# C-spikes — alternate shape (after / beside path B)

> Linked from `memory-bank/sideBackUnblock.md`. Not MIT-img2mv→T2.

## C1 — Wonder3D++ end-to-end

| | |
|--|--|
| Repo | https://github.com/xxlong0/Wonder3D/tree/Wonder3D_Plus |
| Input | `ref_gold_armor` (same as T0) |
| Output | **own GLB** — do **not** pipe views into T2 |
| Compare | Side/Back vs `preview_textures/t0_armor_ultra_s42.glb` |
| Status | ❌ **ABORT** 2026-08-10 — RunPod deps hell (no GLB); pod terminated |
| License | **AGPL-3.0** — spike/eyes only; **не** в AI_MESH prod без open-source всего продукта |
| Pod | create only with explicit GO; terminate same session |

Gate: better / same / worse Side/Back. Soft-NO-GO if blob like v1.

## C2 — Hi3DGen

| | |
|--|--|
| Role | next-tier character **geometry** (normal bridging) |
| Code | [Stable-X/Stable3DGen](https://github.com/Stable-X/Stable3DGen) MIT (не ByteDance stub) |
| Weights | `trellis-normal-v0-1` + YOSO normal + BiRefNet |
| Output | mesh GLB (геометрия; ~7.5 MB у нас, не «40 MB демо») |
| Input | same armor ref |
| Compare | vs High T2 **меш** (каркас) |
| Spike | `scripts/hi3dgen_h0_spike.md` |
| Status | 🟡 H0/H0b1 глаза: мыло (MC). Next **H0c FlexiCubes** |

Start after B eyes, or parallel if B clearly fails. B = soft-NO-GO → H0 is the live C2.

## Order

1. Finish **B** Gemini→T2 eyes  
2. C1 one pod smoke  
3. C2 research + smoke  
4. Document winners in `sideBackUnblock.md`
