// node graft.mjs <low.glb> <bake dir> <out.glb>
// Puts what tools_blender/bake.py baked into the light model itself: its triangle corners get the new UVs
// and the smooth normals the normal map was baked against, its vertices are split where the new UV
// seams run, and one material carries the baked maps. Everything else in the file stays as game.mjs left
// it — nodes, skins, animations, morph targets: sent through Blender's exporter, rigs came out redone
// (CesiumMan 57% off its original at rest).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Logger, NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { prune } from "@gltf-transform/functions";

const [lowPath, bakeDir, outPath] = process.argv.slice(2);
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
const doc = await io.read(lowPath);
doc.setLogger(new Logger(Logger.Verbosity.ERROR));
const meshes = JSON.parse(readFileSync(join(bakeDir, "corners.json"), "utf8"));
const data = new Float32Array(new Uint8Array(readFileSync(join(bakeDir, "corners.f32"))).buffer);
const STRIDE = 8; // position 3, normal 3, uv 2
const total = data.length / STRIDE;

// Blender may hold the mesh as the file does or turned Z up; whichever lines the corners up is the one.
const AXES = [
  (x, y, z) => [x, y, z],
  (x, y, z) => [x, z, -y],
];
const TRIANGLES = 4;

// Triangles are found by where their corners are, not by order: Blender joins a mesh's primitives
// into one and drops degenerate triangles, so counting corners went astray (BrainStem, a small fox).
// Corners are bucketed on a fine grid and matched within a cell of it, neighbours included: a point on
// a cell's edge can round either way.
let span = 0;
for (const mesh of doc.getRoot().listMeshes()) {
  for (const prim of mesh.listPrimitives()) {
    const pos = prim.getAttribute("POSITION");
    if (pos) span = Math.max(span, ...pos.getMax([]).map((v, i) => v - pos.getMin([])[i]));
  }
}
const GRID = 1e-5 * (span || 1);

function bakedTriangles(axes) {
  const at = new Float64Array(total * 3);
  const cells = new Map();
  for (let c = 0; c < total; c++) {
    const b = data.subarray(c * STRIDE, c * STRIDE + 3);
    const p = axes(b[0], b[1], b[2]);
    at.set(p, c * 3);
    if (c % 3) continue; // a triangle is filed under its first corner
    const key = p.map((v) => Math.round(v / GRID)).join(",");
    if (!cells.has(key)) cells.set(key, []);
    cells.get(key).push(c / 3);
  }
  return { at, cells };
}

/** The baked triangle over these three points, and which of its corners each point is; null if none. */
function findTriangle(found, points) {
  const close = (corner, p) => Math.abs(found.at[corner * 3] - p[0]) + Math.abs(found.at[corner * 3 + 1] - p[1]) + Math.abs(found.at[corner * 3 + 2] - p[2]) <= 3 * GRID;
  for (const p0 of points) {
    const [i, j, k] = p0.map((v) => Math.round(v / GRID));
    for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) for (let d = -1; d <= 1; d++) {
      for (const t of found.cells.get(`${i + a},${j + b},${k + d}`) ?? []) {
        const which = points.map((p) => [0, 1, 2].find((q) => close(3 * t + q, p)));
        if (which.every((q) => q !== undefined) && new Set(which).size === 3) return { t, which };
      }
    }
  }
  return null;
}

const place = (() => {
  // the axes under which a sample of the model's triangles is found
  let best = null;
  for (const axes of AXES) {
    const found = bakedTriangles(axes);
    let hits = 0;
    let tried = 0;
    for (const mesh of doc.getRoot().listMeshes()) {
      for (const prim of mesh.listPrimitives()) {
        const idx = prim.getIndices()?.getArray();
        const pos = prim.getAttribute("POSITION");
        if (!idx || !pos) continue;
        for (let c = 0; c + 2 < idx.length && tried < 300; c += 3 * 37) {
          hits += findTriangle(found, [0, 1, 2].map((k) => pos.getElement(idx[c + k], []))) ? 1 : 0;
          tried++;
        }
      }
    }
    if (!best || hits > best.hits) best = { hits, tried, found, axes };
  }
  if (best.hits < 0.9 * best.tried) throw new Error(`the baked mesh doesn't line up with the model (${best.hits} of ${best.tried} triangles found)`);
  return best;
})();

/** A new accessor like `accessor`, holding its elements in the order `pick` gives (old vertex per new one). */
function picked(accessor, pick) {
  const size = accessor.getElementSize();
  const old = accessor.getArray();
  const out = new old.constructor(pick.length * size);
  for (let v = 0; v < pick.length; v++) for (let k = 0; k < size; k++) out[v * size + k] = old[pick[v] * size + k];
  return doc.createAccessor().setType(accessor.getType()).setArray(out).setNormalized(accessor.getNormalized()).setBuffer(accessor.getBuffer());
}

function texture(name, mime = "image/png") {
  return doc.createTexture(name).setImage(new Uint8Array(readFileSync(join(bakeDir, `${name}.png`)))).setMimeType(mime);
}
const material = doc.createMaterial("baked")
  .setBaseColorTexture(texture("baseColor"))
  .setMetallicRoughnessTexture(texture("metallicRoughness"))
  .setNormalTexture(texture("normal"))
  .setMetallicFactor(1)
  .setRoughnessFactor(1);

let corners = 0;
let vertices = 0;
let dropped = 0;
for (const mesh of doc.getRoot().listMeshes()) {
  for (const prim of mesh.listPrimitives()) {
    if (prim.getMode() !== TRIANGLES || !prim.getIndices()) continue;
    const idx = prim.getIndices().getArray();
    const pos = prim.getAttribute("POSITION");
    const seen = new Map();
    const pick = [];
    const normals = [];
    const uvs = [];
    const indices = [];
    for (let c = 0; c + 2 < idx.length; c += 3) {
      const points = [0, 1, 2].map((k) => pos.getElement(idx[c + k], []));
      const hit = findTriangle(place.found, points);
      if (!hit) {
        const [p, q, r] = points;
        const cross = [(q[1] - p[1]) * (r[2] - p[2]) - (q[2] - p[2]) * (r[1] - p[1]), (q[2] - p[2]) * (r[0] - p[0]) - (q[0] - p[0]) * (r[2] - p[2]), (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])];
        if (Math.hypot(...cross) > GRID * GRID) throw new Error(`a triangle of mesh "${mesh.getName()}" is missing from the bake`);
        dropped++; // degenerate: Blender dropped it, and there is nothing to draw
        continue;
      }
      for (let k = 0; k < 3; k++) {
        const corner = 3 * hit.t + hit.which[k];
        const b = data.subarray(corner * STRIDE, (corner + 1) * STRIDE);
        const n = place.axes(b[3], b[4], b[5]);
        const key = `${idx[c + k]}|${b[6]}|${b[7]}|${n[0]}|${n[1]}|${n[2]}`;
        let v = seen.get(key);
        if (v === undefined) {
          v = pick.length;
          seen.set(key, v);
          pick.push(idx[c + k]);
          const len = Math.hypot(n[0], n[1], n[2]) || 1;
          normals.push(n[0] / len, n[1] / len, n[2] / len);
          uvs.push(b[6], 1 - b[7]); // Blender's V runs up, glTF's down
        }
        indices.push(v);
      }
    }
    corners += indices.length;
    vertices += pick.length;
    for (const semantic of prim.listSemantics()) {
      const accessor = prim.getAttribute(semantic);
      if (semantic === "NORMAL" || semantic.startsWith("TEXCOORD_")) prim.setAttribute(semantic, null);
      else prim.setAttribute(semantic, picked(accessor, pick));
    }
    for (const target of prim.listTargets()) {
      for (const semantic of target.listSemantics()) target.setAttribute(semantic, picked(target.getAttribute(semantic), pick));
    }
    const buffer = prim.getAttribute("POSITION").getBuffer();
    prim.setAttribute("NORMAL", doc.createAccessor().setType("VEC3").setArray(Float32Array.from(normals)).setBuffer(buffer));
    prim.setAttribute("TEXCOORD_0", doc.createAccessor().setType("VEC2").setArray(Float32Array.from(uvs)).setBuffer(buffer));
    prim.setIndices(doc.createAccessor().setType("SCALAR").setArray(Uint32Array.from(indices)).setBuffer(buffer));
    prim.setMaterial(material);
  }
}
await doc.transform(prune());
await io.write(outPath, doc);
process.stdout.write(JSON.stringify({ graft: { corners, vertices, dropped } }));
