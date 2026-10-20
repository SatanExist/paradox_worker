// node game.mjs <in.glb> <out.glb> '{"targetTris":20000,"textureSize":2048}'
// Makes a model fit for a game engine without losing what trimesh would drop (materials, UVs,
// textures, separate meshes): unpack, weld, cut triangles to a budget, shrink textures,
// stand it on the floor. Prints {steps, before, after} as JSON on stdout.
import { statSync } from "node:fs";
import { ImageUtils, NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { center, dedup, dequantize, prune, simplify, textureCompress, weld } from "@gltf-transform/functions";
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

const TRIANGLES = 4;

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

const welded = stats(doc).triangles;
if (welded > targetTris) {
  // The budget is what was asked for, so the error limit is off; meshopt still keeps
  // borders and attribute seams, and the report says when it couldn't get all the way down.
  await doc.transform(simplify({ simplifier: MeshoptSimplifier, ratio: targetTris / welded, error: 1 }));
  steps.push(`triangles cut to ${targetTris}`);
}

if (before.textureMaxPx > textureSize) {
  await doc.transform(textureCompress({ encoder: sharp, resize: [textureSize, textureSize] }));
  steps.push(`textures shrunk to ${textureSize}px`);
}

// On the floor: centred on X/Z, lowest point at Y=0 (glTF is Y up, metres).
await doc.transform(prune(), center({ pivot: "below" }));
steps.push("placed on floor");

await io.write(output, doc);
const after = stats(doc, output);
process.stdout.write(JSON.stringify({ steps, before, after, budgetReached: after.triangles <= targetTris * 1.05 }));
