// node game.mjs <in.glb> <out.glb> '{"targetTris":20000,"textureSize":2048,"maxErrorPct":0.5}'
// Makes a model fit for a game engine without losing what trimesh would drop (materials, UVs,
// textures, separate meshes): unpack, weld, drop floating specks, cut triangles, shrink
// textures, stand it on the floor. Prints {steps, before, after, ...} as JSON on stdout.
//
// Two ways to cut: to a triangle budget (targetTris), or — with maxErrorPct — to as few
// triangles as keep the surface within that share of the model's size, targetTris then
// being the most it may keep.
import { readFileSync, statSync } from "node:fs";
import { ImageUtils, Logger, NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { center, compactPrimitive, dedup, dequantize, getBounds, prune, textureCompress, weld } from "@gltf-transform/functions";
import draco3d from "draco3dgltf";
import { MeshoptDecoder, MeshoptSimplifier } from "meshoptimizer";
import sharp from "sharp";

const [input, output, rawParams] = process.argv.slice(2);
if (!input || !output) {
  console.error("usage: node game.mjs <in.glb> <out.glb> [params-json]");
  process.exit(2);
}
const params = JSON.parse(rawParams || "{}");
const targetTris = Number(params.targetTris) || 20000;
const textureSize = Number(params.textureSize) || 2048;
const maxError = Number(params.maxErrorPct) > 0 ? Number(params.maxErrorPct) / 100 : null;
// regularize: "light" or "full" asks meshopt for more even triangles. Off by default: the cuts have 2-10%
// needles (quality < 0.1) where originals have ~0, and "full" brings that to ~0, but on the bench props it
// cost looks (mech 10k baked 6.55 -> 9.9% noticeable, its antenna lost again; drill 0.6 -> 1.3%) and
// "light" was mixed. Kept for rigged models, where even triangles bend better.
const EVEN = { light: ["RegularizeLight"], full: ["Regularize"] }[params.regularize] ?? [];
// Points (float32 x,y,z) where an earlier cut lost detail: vertices there are kept (tools_ops.py).
// Copied into a buffer of its own: a small file's Buffer is a slice of Node's shared pool, and reading
// its .buffer whole gave 16384 floats of whatever else was in the pool (no point ever matched).
const keep = params.keepFile ? new Float32Array(new Uint8Array(readFileSync(params.keepFile)).buffer) : null;

const TRIANGLES = 4;
/** Pieces smaller than this share of the model are specks the generator left floating around it. */
const SPECK = 0.005;
/**
 * In the quality mode normals and UVs count too: with the shape alone meshopt's error estimate
 * ran 2–4x under the measured deviation, with these it lands close to what was asked.
 */
const NORMAL_WEIGHT = 0.5;
const UV_WEIGHT = 1.0;
/** To a budget: enough normal weight to keep the shading, UVs left to the locked seams. */
const BUDGET_NORMAL_WEIGHT = 0.2;
/** How much a rigged vertex's pull (skinPull) counts, in both modes: of 0.5, 1, 2 and 4, 1 bent best over the clips. */
const SKIN_WEIGHT = 1.0;

/** What a game dev looks at: triangles drawn, vertices, materials, how big the textures are. */
function stats(doc, path) {
  let triangles = 0;
  let vertices = 0;
  for (const scene of doc.getRoot().listScenes()) {
    scene.traverse((node) => {
      const mesh = node.getMesh();
      if (!mesh) return;
      for (const prim of mesh.listPrimitives()) {
        if (prim.getMode() !== TRIANGLES) continue;
        const position = prim.getAttribute("POSITION");
        const indices = prim.getIndices();
        triangles += Math.floor((indices ? indices.getCount() : position ? position.getCount() : 0) / 3);
        vertices += position ? position.getCount() : 0;
      }
    });
  }
  let textureMax = 0;
  let textureBytes = 0;
  const textures = doc.getRoot().listTextures();
  for (const texture of textures) {
    const image = texture.getImage();
    if (!image) continue;
    textureBytes += image.byteLength;
    const size = ImageUtils.getSize(image, texture.getMimeType());
    if (size) textureMax = Math.max(textureMax, size[0], size[1]);
  }
  return {
    triangles,
    vertices,
    meshes: doc.getRoot().listMeshes().length,
    materials: doc.getRoot().listMaterials().length,
    textures: textures.length,
    textureMaxPx: textureMax,
    textureMb: Math.round((textureBytes / 1048576) * 100) / 100,
    fileMb: path ? Math.round((statSync(path).size / 1048576) * 100) / 100 : undefined,
  };
}

/**
 * Where a mesh sits in the model: the world matrix of the node that shows it biggest (a mesh can be
 * shown by several nodes, or none). Column-major, as glTF keeps it.
 */
function placement(mesh) {
  let best = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
  let bestScale = -1;
  for (const node of mesh.listParents()) {
    if (node.propertyType !== "Node") continue;
    const m = node.getWorldMatrix();
    const scale = Math.max(Math.hypot(m[0], m[1], m[2]), Math.hypot(m[4], m[5], m[6]), Math.hypot(m[8], m[9], m[10]));
    if (scale > bestScale) [best, bestScale] = [m, scale];
  }
  return best;
}

/** Column-major affine 4x4 inverse's translation: where the matrix's origin maps back to. */
function originOfInverse(m) {
  const [a, b, c, d, e, f, g, h, i] = [m[0], m[4], m[8], m[1], m[5], m[9], m[2], m[6], m[10]];
  const det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g) || 1e-30;
  const inv = [(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det,
    (f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det,
    (d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det];
  const [tx, ty, tz] = [m[12], m[13], m[14]];
  return [-(inv[0] * tx + inv[1] * ty + inv[2] * tz), -(inv[3] * tx + inv[4] * ty + inv[5] * tz), -(inv[6] * tx + inv[7] * ty + inv[8] * tz)];
}

/**
 * Where the bones pull each vertex of a rigged primitive: its joints' bind positions averaged by its
 * weights, over the mesh's size. On one bone, one value; blended over a joint, in between. Weighed in
 * the cut it keeps vertices that bend differently from merging: cut by shape alone, CesiumMan at 2000
 * triangles stood within 0.3% of the original at rest but 2.3% off in its walk, the fox 1.0% -> 5.7%.
 * Null for a primitive without a skin.
 */
function skinPull(prim, mesh, positions) {
  const node = mesh.listParents().find((n) => n.propertyType === "Node" && n.getSkin());
  const skin = node?.getSkin();
  if (!skin) return null;
  const sets = [0, 1, 2].map((k) => [prim.getAttribute(`JOINTS_${k}`), prim.getAttribute(`WEIGHTS_${k}`)]).filter(([j, w]) => j && w);
  if (!sets.length) return null;
  // A joint's bind position in the mesh's own space: the inverse bind matrix maps the mesh to the joint.
  const ibm = skin.getInverseBindMatrices();
  const joints = skin.listJoints().map((joint, j) => {
    if (ibm) return originOfInverse(ibm.getElement(j, []));
    const w = joint.getWorldMatrix();
    return [w[12], w[13], w[14]];
  });
  const size = MeshoptSimplifier.getScale(positions, 3) || 1;
  const count = positions.length / 3;
  const pull = new Float32Array(count * 3);
  const js = [];
  const ws = [];
  for (let v = 0; v < count; v++) {
    let total = 0;
    const at = [0, 0, 0];
    for (const [jointsAccessor, weightsAccessor] of sets) {
      jointsAccessor.getElement(v, js);
      weightsAccessor.getElement(v, ws);
      for (let k = 0; k < js.length; k++) {
        if (!ws[k] || !joints[js[k]]) continue;
        for (let c = 0; c < 3; c++) at[c] += ws[k] * joints[js[k]][c];
        total += ws[k];
      }
    }
    for (let c = 0; c < 3; c++) pull[v * 3 + c] = total ? at[c] / total / size : 0;
  }
  return pull;
}

/**
 * Each indexed triangle primitive with flat copies of its positions and of normals + UVs (+ skin pull
 * for a rigged one) side by side.
 */
function triangleMeshes(doc) {
  const out = [];
  for (const mesh of doc.getRoot().listMeshes()) {
    const matrix = placement(mesh);
    for (const prim of mesh.listPrimitives()) {
      const position = prim.getAttribute("POSITION");
      const indices = prim.getIndices();
      if (prim.getMode() !== TRIANGLES || !position || !indices) continue;
      const count = position.getCount();
      const positions = Float32Array.from(position.getArray());
      const read = (accessor) => {
        if (!accessor) return null;
        const size = accessor.getElementSize();
        const data = new Float32Array(count * size);
        const element = [];
        for (let i = 0; i < count; i++) {
          accessor.getElement(i, element);
          for (let k = 0; k < size; k++) data[i * size + k] = element[k];
        }
        return data;
      };
      const parts = [
        ["normal", read(prim.getAttribute("NORMAL")), 3, NORMAL_WEIGHT, BUDGET_NORMAL_WEIGHT],
        ["uv", read(prim.getAttribute("TEXCOORD_0")), 2, UV_WEIGHT, 0],
        ["skin", skinPull(prim, mesh, positions), 3, SKIN_WEIGHT, SKIN_WEIGHT],
      ].filter(([, data]) => data);
      const stride = parts.reduce((n, [, , size]) => n + size, 0);
      const attributes = new Float32Array(count * stride);
      const weights = [];
      const budgetWeights = [];
      const channels = {};
      let offset = 0;
      for (const [name, data, size, weight, budgetWeight] of parts) {
        channels[name] = offset;
        for (let i = 0; i < count; i++) for (let k = 0; k < size; k++) attributes[i * stride + offset + k] = data[i * size + k];
        for (let k = 0; k < size; k++) {
          weights.push(weight);
          budgetWeights.push(budgetWeight);
        }
        offset += size;
      }
      out.push({
        prim,
        positions,
        attributes,
        stride,
        weights,
        budgetWeights,
        channels,
        matrix,
        indices: Uint32Array.from(indices.getArray()),
        scale: MeshoptSimplifier.getScale(positions, 3),
      });
    }
  }
  return out;
}

/** Separate pieces, joined by position (UV seams split vertices, not the surface). */
function pieces(p) {
  const remap = MeshoptSimplifier.generatePositionRemap(p.positions, 3);
  const parent = Uint32Array.from(remap.keys());
  const find = (x) => {
    while (parent[x] !== x) x = parent[x] = parent[parent[x]];
    return x;
  };
  for (let i = 0; i < p.indices.length; i += 3) {
    const a = find(remap[p.indices[i]]);
    for (const v of [p.indices[i + 1], p.indices[i + 2]]) {
      const r = find(remap[v]);
      if (r !== a) parent[r] = a;
    }
  }
  const roots = new Set();
  for (const v of p.indices) roots.add(find(remap[v]));
  return roots.size;
}

/** Drop pieces smaller than SPECK of the model: triangles spent on them are lost to the model itself. */
function dropSpecks(prims, modelScale) {
  let removedPieces = 0;
  let removedTriangles = 0;
  for (const p of prims) {
    const before = p.indices.length / 3;
    const piecesBefore = pieces(p);
    p.indices = MeshoptSimplifier.simplifyPrune(p.indices, p.positions, 3, (SPECK * modelScale) / p.scale);
    removedTriangles += before - p.indices.length / 3;
    removedPieces += piecesBefore - pieces(p);
  }
  return { pieces: removedPieces, triangles: removedTriangles };
}

/**
 * Collapse triangles to `ratio` of them. Mostly the shape is weighed, normals a little: with the
 * shape alone the light fell wrong (models looked chrome), with full weights the shape error
 * doubled. How far the surface really moved is measured afterwards (tools_ops.py).
 */
/** Mark the vertices sitting exactly on the points to keep (seams split one point into several). */
function keepPoints(prims) {
  const wanted = new Set();
  for (let i = 0; i + 2 < keep.length; i += 3) wanted.add(`${keep[i]},${keep[i + 1]},${keep[i + 2]}`);
  let kept = 0;
  for (const p of prims) {
    p.lock = new Uint8Array(p.positions.length / 3);
    for (let v = 0; v < p.lock.length; v++) {
      if (wanted.has(`${p.positions[v * 3]},${p.positions[v * 3 + 1]},${p.positions[v * 3 + 2]}`)) {
        p.lock[v] = 1;
        kept++;
      }
    }
  }
  return kept;
}

function cut(prims, ratio, flags = []) {
  if (prims.length > 1) return cutTogether(prims, { targetTris: Math.floor(triangleCount(prims) * ratio), flags });
  for (const p of prims) {
    const target = Math.floor((p.indices.length / 3) * ratio) * 3;
    // Plain simplify takes no locks: with points to keep and nothing else to weigh, one zero attribute.
    const [attributes, stride, weights] = p.stride ? [p.attributes, p.stride, p.budgetWeights] : [new Float32Array(p.positions.length / 3), 1, [0]];
    [p.indices] = p.stride || p.lock
      ? MeshoptSimplifier.simplifyWithAttributes(p.indices, p.positions, 3, attributes, stride, weights, p.lock ?? null, target, Number.MAX_VALUE, flags)
      : MeshoptSimplifier.simplify(p.indices, p.positions, 3, target, Number.MAX_VALUE, flags);
  }
}

/**
 * Several parts are cut as one: a single simplification over all of them, placed where they sit in
 * the model, so each collapse anywhere is weighed against every other and the triangles stay where
 * they hold the most shape. Cut one by one to the same share, a small detailed part (a sword next to
 * a drill) lost as big a share as a big smooth one. Normals, then UVs, side by side for every part
 * (zeros where a part has none); vertices of different parts are never merged.
 */
function cutTogether(prims, { targetTris = 0, error = Number.MAX_VALUE, budget = true, flags = [] }) {
  const LAYOUT = { normal: 0, uv: 3, skin: 5 };
  const STRIDE = 8;
  const offsets = [];
  let vertices = 0;
  for (const p of prims) {
    offsets.push(vertices);
    vertices += p.positions.length / 3;
  }
  const positions = new Float32Array(vertices * 3);
  const attributes = new Float32Array(vertices * STRIDE);
  const lock = prims.some((p) => p.lock) ? new Uint8Array(vertices) : null;
  const indices = new Uint32Array(prims.reduce((n, p) => n + p.indices.length, 0));
  let at = 0;
  prims.forEach((p, k) => {
    const m = p.matrix;
    const base = offsets[k];
    for (let v = 0; v < p.positions.length / 3; v++) {
      const [x, y, z] = [p.positions[v * 3], p.positions[v * 3 + 1], p.positions[v * 3 + 2]];
      positions[(base + v) * 3] = m[0] * x + m[4] * y + m[8] * z + m[12];
      positions[(base + v) * 3 + 1] = m[1] * x + m[5] * y + m[9] * z + m[13];
      positions[(base + v) * 3 + 2] = m[2] * x + m[6] * y + m[10] * z + m[14];
      for (const [name, size] of [["normal", 3], ["uv", 2], ["skin", 3]]) {
        if (p.channels[name] === undefined) continue;
        for (let c = 0; c < size; c++) attributes[(base + v) * STRIDE + LAYOUT[name] + c] = p.attributes[v * p.stride + p.channels[name] + c];
      }
    }
    if (lock && p.lock) lock.set(p.lock, base);
    for (const i of p.indices) indices[at++] = i + base;
  });
  const skin = [SKIN_WEIGHT, SKIN_WEIGHT, SKIN_WEIGHT];
  const weights = budget
    ? [BUDGET_NORMAL_WEIGHT, BUDGET_NORMAL_WEIGHT, BUDGET_NORMAL_WEIGHT, 0, 0, ...skin]
    : [NORMAL_WEIGHT, NORMAL_WEIGHT, NORMAL_WEIGHT, UV_WEIGHT, UV_WEIGHT, ...skin];
  const [kept] = MeshoptSimplifier.simplifyWithAttributes(indices, positions, 3, attributes, STRIDE, weights, lock, targetTris * 3, error, flags);
  // back to the parts: each triangle belongs to the part of its first vertex
  const owner = (v) => {
    let lo = 0;
    let hi = offsets.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (offsets[mid] <= v) lo = mid;
      else hi = mid - 1;
    }
    return lo;
  };
  const lists = prims.map(() => []);
  for (let i = 0; i < kept.length; i += 3) {
    const k = owner(kept[i]);
    lists[k].push(kept[i] - offsets[k], kept[i + 1] - offsets[k], kept[i + 2] - offsets[k]);
  }
  prims.forEach((p, k) => (p.indices = Uint32Array.from(lists[k])));
}

/** As few triangles as keep the surface (normals and UVs counted) within `error` of the model's size. */
function cutWithin(prims, error, modelScale) {
  if (prims.length > 1) return cutTogether(prims, { error, budget: false });
  for (const p of prims) {
    const limit = (error * modelScale) / p.scale;
    [p.indices] = p.stride
      ? MeshoptSimplifier.simplifyWithAttributes(p.indices, p.positions, 3, p.attributes, p.stride, p.weights, null, 0, limit)
      : MeshoptSimplifier.simplify(p.indices, p.positions, 3, 0, limit);
  }
}

const triangleCount = (prims) => prims.reduce((n, p) => n + p.indices.length / 3, 0);

await MeshoptDecoder.ready;
await MeshoptSimplifier.ready;
const io = new NodeIO()
  .registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({
    "draco3d.decoder": await draco3d.createDecoderModule(),
    "meshopt.decoder": MeshoptDecoder,
  });

const doc = await io.read(input);
// stdout carries the JSON result: gltf-transform's own notes ("prune: Removed …") would corrupt it.
doc.setLogger(new Logger(Logger.Verbosity.ERROR));
const before = stats(doc, input);
const steps = [];

// Plain geometry out: engines and our FBX export read it without decoders.
await doc.transform(dequantize());
const UNPACK = new Set(["KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_mesh_quantization"]);
for (const ext of doc.getRoot().listExtensionsUsed()) {
  if (UNPACK.has(ext.extensionName)) ext.dispose();
}

// Welding only merges identical vertices, so UV seams stay split and textures stay put.
await doc.transform(dedup(), weld());
steps.push("welded");

const prims = triangleMeshes(doc);
if (params.forBake) {
  // The textures will be baked afterwards onto new UVs, so the old seams need not hold: the
  // triangles go where the shape is, joined across seams, with nothing but positions weighed.
  for (const p of prims) {
    const remap = MeshoptSimplifier.generatePositionRemap(p.positions, 3);
    p.indices = p.indices.map((i) => remap[i]);
    if (p.channels.skin === undefined) {
      p.stride = 0;
      p.channels = {};
      continue;
    }
    // A rigged part keeps only its skin pull: where the bones bend it still matters, the old UVs don't.
    const count = p.positions.length / 3;
    const pull = new Float32Array(count * 3);
    for (let v = 0; v < count; v++) for (let c = 0; c < 3; c++) pull[v * 3 + c] = p.attributes[v * p.stride + p.channels.skin + c];
    [p.attributes, p.stride, p.channels] = [pull, 3, { skin: 0 }];
    p.weights = p.budgetWeights = [SKIN_WEIGHT, SKIN_WEIGHT, SKIN_WEIGHT];
  }
  steps.push("UV seams ignored: textures are baked afterwards");
}
// meshopt measures error against each primitive's own size; we speak of the whole model.
const modelScale = Math.max(...prims.map((p) => p.scale), 1e-9);

const specks = dropSpecks(prims, modelScale);
if (specks.triangles) steps.push(`removed ${specks.pieces} floating specks (${specks.triangles} triangles)`);

const cleaned = triangleCount(prims);
if (maxError !== null) {
  cutWithin(prims, maxError, modelScale);
  steps.push(`triangles cut within ${maxError * 100}% of the model's size`);
}
if (keep) steps.push(`kept ${keepPoints(prims)} vertices where a first cut lost detail`);
if (triangleCount(prims) > targetTris) {
  // The budget is what was asked for, so the error limit is off. UV seams stay locked, which
  // keeps textures in place; AI models are so full of seams that this can stop well short.
  // Joined across seams (forBake), only Permissive gets far: without it meshopt stalled at 8x the budget.
  cut(prims, targetTris / triangleCount(prims), [...(params.forBake ? ["Permissive"] : []), ...EVEN]);
  steps.push(`triangles cut to ${targetTris}`);
  if (triangleCount(prims) > targetTris * 1.05) {
    // Only then let it collapse across seams: the budget is met, textures near seams may shift.
    cut(prims, targetTris / triangleCount(prims), ["Permissive", ...EVEN]);
    steps.push("UV seams loosened to reach the budget");
  }
}
let emptied = 0;
for (const p of prims) {
  if (!p.indices.length) {
    // cut away entirely: a primitive with no triangles is not valid glTF, readers refuse the file
    p.prim.dispose();
    emptied++;
    continue;
  }
  p.prim.setIndices(p.prim.getIndices().setArray(p.indices));
  compactPrimitive(p.prim);
}
if (emptied) steps.push(`${emptied} parts too small for the budget left out`);

if (before.textureMaxPx > textureSize) {
  await doc.transform(textureCompress({ encoder: sharp, resize: [textureSize, textureSize] }));
  steps.push(`textures shrunk to ${textureSize}px`);
}

// On the floor: centred on X/Z, lowest point at Y=0 (glTF is Y up, metres).
await doc.transform(prune());
const scene = doc.getRoot().getDefaultScene() ?? doc.getRoot().listScenes()[0];
const lowBefore = getBounds(scene).min;
await doc.transform(center({ pivot: "below" }));
const lowAfter = getBounds(scene).min;
steps.push("placed on floor");
// TRELLIS, TripoSR, Step1X and Hi3DGen name their root node "world", trimesh's own name for the base
// frame: reading the file, trimesh drops that node's transform — the move to the floor done just above.
for (const node of doc.getRoot().listNodes()) {
  if (node.getName() === "world") node.setName("root");
}

await io.write(output, doc);
const after = stats(doc, output);
process.stdout.write(
  JSON.stringify({
    steps,
    before,
    after,
    budgetReached: after.triangles <= targetTris * 1.05,
    specks,
    trianglesAfterCleanup: cleaned,
    // How far the model was moved, so the caller can lay the original over it and measure.
    shift: lowAfter.map((v, i) => v - lowBefore[i]),
  }),
);
