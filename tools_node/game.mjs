// node game.mjs <in.glb> <out.glb> '{"targetTris":20000,"textureSize":2048,"maxErrorPct":0.5}'
// Makes a model fit for a game engine without losing what trimesh would drop (materials, UVs,
// textures, separate meshes): unpack, weld, drop floating specks, cut triangles, shrink
// textures, stand it on the floor. Prints {steps, before, after, ...} as JSON on stdout.
//
// Two ways to cut: to a triangle budget (targetTris), or — with maxErrorPct — to as few
// triangles as keep the surface within that share of the model's size, targetTris then
// being the most it may keep.
import { statSync } from "node:fs";
import { ImageUtils, NodeIO } from "@gltf-transform/core";
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

const TRIANGLES = 4;
/** Pieces smaller than this share of the model are specks the generator left floating around it. */
const SPECK = 0.005;
/**
 * In the quality mode normals and UVs count too: with the shape alone meshopt's error estimate
 * ran 2–4x under the measured deviation, with these it lands close to what was asked.
 */
const NORMAL_WEIGHT = 0.5;
const UV_WEIGHT = 1.0;

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

/** Each indexed triangle primitive with flat copies of its positions and of normals + UVs side by side. */
function triangleMeshes(doc) {
  const out = [];
  for (const mesh of doc.getRoot().listMeshes()) {
    for (const prim of mesh.listPrimitives()) {
      const position = prim.getAttribute("POSITION");
      const indices = prim.getIndices();
      if (prim.getMode() !== TRIANGLES || !position || !indices) continue;
      const count = position.getCount();
      const parts = [
        [prim.getAttribute("NORMAL"), NORMAL_WEIGHT],
        [prim.getAttribute("TEXCOORD_0"), UV_WEIGHT],
      ].filter(([accessor]) => accessor);
      const stride = parts.reduce((n, [accessor]) => n + accessor.getElementSize(), 0);
      const attributes = new Float32Array(count * stride);
      const weights = [];
      let offset = 0;
      for (const [accessor, weight] of parts) {
        const size = accessor.getElementSize();
        const element = [];
        for (let i = 0; i < count; i++) {
          accessor.getElement(i, element);
          for (let k = 0; k < size; k++) attributes[i * stride + offset + k] = element[k];
        }
        for (let k = 0; k < size; k++) weights.push(weight);
        offset += size;
      }
      const positions = Float32Array.from(position.getArray());
      out.push({
        prim,
        positions,
        attributes,
        stride,
        weights,
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
 * Collapse triangles to `ratio` of them, the shape alone weighed: to a budget, weighing normals
 * and UVs too cost twice the shape error on our test models. How far the surface really moved
 * is measured afterwards (tools_ops.py).
 */
function cut(prims, ratio, flags = []) {
  for (const p of prims) {
    const target = Math.floor((p.indices.length / 3) * ratio) * 3;
    [p.indices] = MeshoptSimplifier.simplify(p.indices, p.positions, 3, target, Number.MAX_VALUE, flags);
  }
}

/** As few triangles as keep the surface (normals and UVs counted) within `error` of the model's size. */
function cutWithin(prims, error, modelScale) {
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
// meshopt measures error against each primitive's own size; we speak of the whole model.
const modelScale = Math.max(...prims.map((p) => p.scale), 1e-9);

const specks = dropSpecks(prims, modelScale);
if (specks.triangles) steps.push(`removed ${specks.pieces} floating specks (${specks.triangles} triangles)`);

const cleaned = triangleCount(prims);
if (maxError !== null) {
  cutWithin(prims, maxError, modelScale);
  steps.push(`triangles cut within ${maxError * 100}% of the model's size`);
}
if (triangleCount(prims) > targetTris) {
  // The budget is what was asked for, so the error limit is off. UV seams stay locked, which
  // keeps textures in place; AI models are so full of seams that this can stop well short.
  cut(prims, targetTris / triangleCount(prims));
  steps.push(`triangles cut to ${targetTris}`);
  if (triangleCount(prims) > targetTris * 1.05) {
    // Only then let it collapse across seams: the budget is met, textures near seams may shift.
    cut(prims, targetTris / triangleCount(prims), ["Permissive"]);
    steps.push("UV seams loosened to reach the budget");
  }
}
for (const p of prims) {
  p.prim.setIndices(p.prim.getIndices().setArray(p.indices));
  compactPrimitive(p.prim);
}

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
