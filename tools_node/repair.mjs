// node repair.mjs <in.glb> <out.glb>
// Mends what a broken model shows as holes before anything else looks at it: T-junctions are stitched and
// triangles turned inside out are turned back (one-way per piece, closed pieces outward); exact duplicate
// triangles are dropped. Run first by
// game_prep (tools_ops.py), so the search for hidden faces, the cut, the bake and the look check all see the
// mended model, as mesh tools do (Blender's Recalculate Outside, CGAL's repair before processing).
// Writes <out.glb> only when it mended something; prints {before, duplicates, stitched, turned, wrote} as JSON,
// `before` being the original as the user uploaded it.
import { Logger, NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { dedup, dequantize, weld } from "@gltf-transform/functions";
import draco3d from "draco3dgltf";
import { MeshoptDecoder, MeshoptSimplifier } from "meshoptimizer";
import { stats, TRIANGLES } from "./stats.mjs";

const [input, output] = process.argv.slice(2);
if (!input || !output) {
  console.error("usage: node repair.mjs <in.glb> <out.glb>");
  process.exit(2);
}

/**
 * T-junctions: a vertex lies on another triangle's edge without being one of its corners (pieces meshed
 * apart and laid side by side, CAD and boolean exports). Both edges look open, so meshopt guards them as
 * the rim of a hole: in the zoo a box with such seams barely simplified and the budget was met by eating
 * the whole sphere beside it. Stitched as mesh repair does (CGAL's snap_borders): the triangle is split
 * at that vertex, so the edge is shared and the surface is closed there; nothing moves. Only open edges
 * are searched, so a closed mesh is not touched. ON: a point counts as on an edge within a millionth of
 * the part's size, a few float32 steps (positions are stored as float32), not a tuned distance.
 */
const ON = 1e-6;

/** Stable counting sort of corners `order` by keys[c] (0..n-1): linear, typed arrays. */
function byKey(keys, order, n) {
  const start = new Uint32Array(n + 1);
  for (let i = 0; i < order.length; i++) start[keys[order[i]] + 1]++;
  for (let v = 0; v < n; v++) start[v + 1] += start[v];
  const out = new Uint32Array(order.length);
  for (let i = 0; i < order.length; i++) out[start[keys[order[i]]]++] = order[i];
  return out;
}

/**
 * Duplicate triangles: the same three points in the same order, twice (AI meshes have up to 0.3 % of
 * them, the lattice 282). They draw on top of each other (flicker, z-fighting) and spend budget for
 * nothing; the cut keeps them, as it keeps everything that isn't merged. Dropped as mesh tools do
 * (trimesh's unique_faces, MeshLab's Remove Duplicate Faces), but only a copy that runs the same way:
 * a pair that runs opposite ways is a two-sided sheet (a leaf, a cape, a thin blade drawn from both
 * sides) and stays. Points count as the same by position, as for the edges below. The first copy is kept.
 */
function dropDuplicates(doc) {
  let dropped = 0;
  for (const mesh of doc.getRoot().listMeshes()) {
    for (const prim of mesh.listPrimitives()) {
      const position = prim.getAttribute("POSITION");
      const indexAccessor = prim.getIndices();
      if (prim.getMode() !== TRIANGLES || !position || !indexAccessor) continue;
      const idx = indexAccessor.getArray();
      const remap = MeshoptSimplifier.generatePositionRemap(Float32Array.from(position.getArray()), 3);
      const seen = new Set();
      const keep = [];
      for (let t = 0; t < idx.length; t += 3) {
        const a = remap[idx[t]], b = remap[idx[t + 1]], c = remap[idx[t + 2]];
        // the same way round, from its lowest point: a->b->c, b->c->a and c->a->b are one key
        const key = a <= b && a <= c ? `${a},${b},${c}` : b <= c ? `${b},${c},${a}` : `${c},${a},${b}`;
        if (a === b || b === c || a === c || !seen.has(key)) {
          seen.add(key);
          keep.push(idx[t], idx[t + 1], idx[t + 2]);
        }
      }
      if (keep.length === idx.length) continue;
      dropped += (idx.length - keep.length) / 3;
      indexAccessor.setArray(new idx.constructor(keep)); // same index type: the kept values are the old ones
    }
  }
  return dropped;
}

/**
 * Triangles turned inside out: an engine draws only the front, so through them the model shows holes (the
 * zoo's sphere with its front half turned, or a third of all triangles at random; the cut kept them, and
 * merged the random ones into bigger holes). Put right the way Blender's Recalculate Outside and libigl's
 * bfs_orient + orient_outward do: neighbours across an edge must run along it in opposite directions, so
 * each piece (joined by edges two triangles share) is made one-way, its larger area setting the way; a
 * closed piece is then turned outward by the sign of its volume. An open piece (a cape, a leaf) has no
 * outside to find, so it only gets made one-way. A vertex normal that points against the triangles
 * around it after that is turned too. A piece already one-way and outward is not touched.
 */
function orientOutward(doc) {
  let turned = 0;
  for (const mesh of doc.getRoot().listMeshes()) {
    for (const prim of mesh.listPrimitives()) {
      const position = prim.getAttribute("POSITION");
      const indexAccessor = prim.getIndices();
      if (prim.getMode() !== TRIANGLES || !position || !indexAccessor) continue;
      const pos = Float32Array.from(position.getArray());
      const idx = Uint32Array.from(indexAccessor.getArray());
      const n = position.getCount();
      const T = idx.length / 3;
      const remap = MeshoptSimplifier.generatePositionRemap(pos, 3);
      // edges two triangles share: corners sorted by the edge's (lower, higher) end, then equal runs of two
      const lo = new Uint32Array(idx.length);
      const hi = new Uint32Array(idx.length);
      let edges = 0;
      for (let c = 0; c < idx.length; c++) {
        const a = remap[idx[c]];
        const b = remap[idx[c - (c % 3) + ((c % 3) + 1) % 3]];
        lo[c] = Math.min(a, b);
        hi[c] = Math.max(a, b);
        if (a !== b) edges++;
      }
      const real = new Uint32Array(edges);
      for (let c = 0, k = 0; c < idx.length; c++) if (lo[c] !== hi[c]) real[k++] = c;
      const order = byKey(lo, byKey(hi, real, n), n);
      const across = new Int32Array(idx.length).fill(-1); // the other triangle's corner on this corner's edge
      for (let i = 0; i < order.length; ) {
        let j = i + 1;
        while (j < order.length && lo[order[j]] === lo[order[i]] && hi[order[j]] === hi[order[i]]) j++;
        if (j - i === 2 && ((order[i] / 3) | 0) !== ((order[i + 1] / 3) | 0)) {
          across[order[i]] = order[i + 1];
          across[order[i + 1]] = order[i];
        }
        i = j;
      }
      const area = new Float64Array(T);
      const vol = new Float64Array(T);
      for (let t = 0; t < T; t++) {
        const a = idx[t * 3] * 3;
        const b = idx[t * 3 + 1] * 3;
        const c = idx[t * 3 + 2] * 3;
        const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2];
        const vx = pos[c] - pos[a], vy = pos[c + 1] - pos[a + 1], vz = pos[c + 2] - pos[a + 2];
        const x = uy * vz - uz * vy, y = uz * vx - ux * vz, z = ux * vy - uy * vx;
        area[t] = Math.hypot(x, y, z);
        vol[t] = pos[a] * x + pos[a + 1] * y + pos[a + 2] * z;
      }
      const flip = new Uint8Array(T);
      const side = new Int8Array(T); // 0 unseen, +1 / -1 way relative to the piece's first triangle
      const piece = new Uint32Array(T); // reused queue
      let changed = 0;
      for (let s = 0; s < T; s++) {
        if (side[s]) continue;
        let size = 1;
        piece[0] = s;
        side[s] = 1;
        let open = false;
        for (let q = 0; q < size; q++) {
          const t = piece[q];
          let paired = 0;
          for (let k = 0; k < 3; k++) {
            const c = t * 3 + k;
            const o = across[c];
            if (o < 0) continue;
            paired++;
            const u = (o / 3) | 0;
            if (side[u]) continue;
            // both run a->b over the shared edge: one of them is turned
            side[u] = remap[idx[c]] === remap[idx[o]] ? -side[t] : side[t];
            piece[size++] = u;
          }
          if (paired < 3) open = true;
        }
        // one way: the larger area sets it
        let plus = 0;
        let minus = 0;
        for (let q = 0; q < size; q++) side[piece[q]] > 0 ? (plus += area[piece[q]]) : (minus += area[piece[q]]);
        const keep = plus >= minus ? 1 : -1;
        let volume = 0;
        for (let q = 0; q < size; q++) volume += side[piece[q]] === keep ? vol[piece[q]] : -vol[piece[q]];
        const outward = !open && volume < 0 ? -keep : keep;
        for (let q = 0; q < size; q++) {
          if (side[piece[q]] !== outward) {
            flip[piece[q]] = 1;
            changed++;
          }
        }
      }
      if (!changed) continue;
      for (let t = 0; t < T; t++) {
        if (flip[t]) [idx[t * 3 + 1], idx[t * 3 + 2]] = [idx[t * 3 + 2], idx[t * 3 + 1]];
      }
      const own = indexAccessor.listParents().filter((p) => p.propertyType !== "Root").length > 1 ? indexAccessor.clone() : indexAccessor;
      if (own !== indexAccessor) prim.setIndices(own);
      own.setArray(idx);
      // vertex normals that now point against every triangle around them
      const normal = prim.getAttribute("NORMAL");
      if (normal) {
        const sum = new Float64Array(n * 3);
        for (let t = 0; t < T; t++) {
          const a = idx[t * 3], b = idx[t * 3 + 1], c = idx[t * 3 + 2];
          const ux = pos[b * 3] - pos[a * 3], uy = pos[b * 3 + 1] - pos[a * 3 + 1], uz = pos[b * 3 + 2] - pos[a * 3 + 2];
          const vx = pos[c * 3] - pos[a * 3], vy = pos[c * 3 + 1] - pos[a * 3 + 1], vz = pos[c * 3 + 2] - pos[a * 3 + 2];
          const x = uy * vz - uz * vy, y = uz * vx - ux * vz, z = ux * vy - uy * vx;
          for (const w of [a * 3, b * 3, c * 3]) {
            sum[w] += x;
            sum[w + 1] += y;
            sum[w + 2] += z;
          }
        }
        const ownNormal = normal.listParents().filter((p) => p.propertyType !== "Root").length > 1 ? normal.clone() : normal;
        if (ownNormal !== normal) prim.setAttribute("NORMAL", ownNormal);
        const arr = Float32Array.from(ownNormal.getArray());
        for (let v = 0; v < n; v++) {
          const d = arr[v * 3] * sum[v * 3] + arr[v * 3 + 1] * sum[v * 3 + 1] + arr[v * 3 + 2] * sum[v * 3 + 2];
          if (d < 0) for (let k = 0; k < 3; k++) arr[v * 3 + k] = -arr[v * 3 + k];
        }
        ownNormal.setArray(arr);
      }
      turned += changed;
    }
  }
  return turned;
}

function stitchTJunctions(doc) {
  let stitched = 0;
  for (const mesh of doc.getRoot().listMeshes()) {
    for (const prim of mesh.listPrimitives()) {
      const position = prim.getAttribute("POSITION");
      const indexAccessor = prim.getIndices();
      if (prim.getMode() !== TRIANGLES || !position || !indexAccessor) continue;
      const pos = Float32Array.from(position.getArray());
      const idx = indexAccessor.getArray();
      const n = position.getCount();
      const remap = MeshoptSimplifier.generatePositionRemap(pos, 3);
      const key = (c) => {
        const a = remap[idx[c]];
        const b = remap[idx[c - (c % 3) + ((c % 3) + 1) % 3]];
        return a < b ? a * n + b : b * n + a;
      };
      // open edges: met by one triangle only (sorted keys, so a model of millions needs no map of all edges)
      const keys = new Float64Array(idx.length);
      for (let c = 0; c < idx.length; c++) keys[c] = key(c);
      const sorted = keys.slice().sort();
      const single = new Set();
      for (let i = 0; i < sorted.length; i++) {
        if ((i === 0 || sorted[i - 1] !== sorted[i]) && (i === sorted.length - 1 || sorted[i + 1] !== sorted[i])) single.add(sorted[i]);
      }
      const open = [];
      for (let c = 0; c < idx.length; c++) {
        const a = remap[idx[c]];
        const b = remap[idx[c - (c % 3) + ((c % 3) + 1) % 3]];
        if (a !== b && single.has(keys[c])) open.push(c);
      }
      if (!open.length) continue;
      const next = (c) => c - (c % 3) + ((c % 3) + 1) % 3;
      const P = (v, k) => pos[v * 3 + k];
      // the open edges' ends on a grid of about one edge length
      const ends = new Set();
      const lengths = [];
      for (const c of open) {
        ends.add(remap[idx[c]]);
        ends.add(remap[idx[next(c)]]);
        const [a, b] = [idx[c], idx[next(c)]];
        lengths.push(Math.hypot(P(b, 0) - P(a, 0), P(b, 1) - P(a, 1), P(b, 2) - P(a, 2)));
      }
      lengths.sort((x, y) => x - y);
      const cell = lengths[lengths.length >> 1] || 1;
      const tol = ON * MeshoptSimplifier.getScale(pos, 3);
      const grid = new Map();
      const at = (x) => Math.floor(x / cell);
      for (const v of ends) {
        const g = `${at(P(v, 0))},${at(P(v, 1))},${at(P(v, 2))}`;
        if (!grid.has(g)) grid.set(g, []);
        grid.get(g).push(v);
      }
      // the points lying inside each open edge, in order along it
      const onEdge = new Map();
      for (const c of open) {
        const [a, b] = [idx[c], idx[next(c)]];
        const [ra, rb] = [remap[a], remap[b]];
        const d = [P(b, 0) - P(a, 0), P(b, 1) - P(a, 1), P(b, 2) - P(a, 2)];
        const len2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2];
        if (!(len2 > 0)) continue;
        const lo = [0, 1, 2].map((k) => at(Math.min(P(a, k), P(b, k)) - tol));
        const hi = [0, 1, 2].map((k) => at(Math.max(P(a, k), P(b, k)) + tol));
        const found = [];
        for (let x = lo[0]; x <= hi[0]; x++) for (let y = lo[1]; y <= hi[1]; y++) for (let z = lo[2]; z <= hi[2]; z++) {
          for (const v of grid.get(`${x},${y},${z}`) ?? []) {
            if (v === ra || v === rb || v === remap[idx[next(next(c))]]) continue;
            const w = [P(v, 0) - P(a, 0), P(v, 1) - P(a, 1), P(v, 2) - P(a, 2)];
            const s = (w[0] * d[0] + w[1] * d[1] + w[2] * d[2]) / len2;
            if (s <= 0 || s >= 1) continue;
            const off = Math.hypot(w[0] - s * d[0], w[1] - s * d[1], w[2] - s * d[2]);
            if (off <= tol) found.push([s, v]);
          }
        }
        if (found.length) onEdge.set(c, found.sort((x, y) => x[0] - y[0]));
      }
      if (!onEdge.size) continue;
      // At each point on an edge this triangle needs a corner: the neighbour's own corner there when it already
      // carries what this triangle has at that point (taken along the edge: UVs, normals, morphs) to float32
      // precision, else a new vertex at that point exactly (a real seam: the neighbour's UVs differ). A new one
      // made every time split 4073 points of the zoo's box into seams and the cut stalled as before. Bone
      // weights come from the nearer end (joints can't be blended).
      const channels = [];
      for (const semantic of prim.listSemantics()) channels.push([semantic, prim.getAttribute(semantic), null]);
      for (const target of prim.listTargets()) for (const semantic of target.listSemantics()) channels.push([semantic, target.getAttribute(semantic), target]);
      const data = channels.map(([semantic, accessor, target]) => {
        const array = accessor.getArray();
        let big = 1;
        for (let i = 0; i < array.length; i++) big = Math.max(big, Math.abs(array[i]));
        return { semantic, target, array, size: accessor.getElementSize(), same: ON * big };
      });
      const along = (a, b, s, v) =>
        data.map(({ semantic, target, array, size }) => {
          const out = new Float64Array(size);
          const nearer = semantic.startsWith("JOINTS") || semantic.startsWith("WEIGHTS");
          for (let c = 0; c < size; c++) {
            const [x, y] = [array[a * size + c], array[b * size + c]];
            out[c] = semantic === "POSITION" && !target ? array[v * size + c]
              : nearer || (semantic === "TANGENT" && c === 3) ? (s < 0.5 ? x : y) : x + (y - x) * s;
          }
          if (semantic === "NORMAL" || (semantic === "TANGENT" && !target)) {
            const len = Math.hypot(out[0], out[1], out[2]) || 1;
            for (let c = 0; c < 3; c++) out[c] /= len;
          }
          return out;
        });
      const atPoint = new Map(); // vertices at each point used: every corner there (UV seams split a point)
      for (let i = 0; i < n; i++) {
        const r = remap[i];
        if (!ends.has(r)) continue;
        if (!atPoint.has(r)) atPoint.set(r, []);
        atPoint.get(r).push(i);
      }
      const made = []; // values of each new vertex, per channel
      let reused = 0;
      const cornerAt = (a, b, s, v) => {
        const want = along(a, b, s, v);
        for (const u of atPoint.get(v) ?? []) {
          if (data.every(({ array, size, same }, k) => want[k].every((x, c) => Math.abs(array[u * size + c] - x) <= same))) {
            reused++;
            return u;
          }
        }
        made.push(want);
        return n + made.length - 1;
      };
      const triangles = [];
      const split = (tri, lists) => {
        const k = lists.findIndex((l) => l.length);
        if (k < 0) {
          triangles.push(tri[0], tri[1], tri[2]);
          return;
        }
        const l = lists[k];
        const mid = l.length >> 1;
        const m = l[mid];
        const [vk, vk1, vk2] = [tri[k], tri[(k + 1) % 3], tri[(k + 2) % 3]];
        const first = [[], [], []];
        first[0] = l.slice(0, mid);
        first[2] = lists[(k + 2) % 3];
        split([vk, m, vk2], first);
        const second = [[], [], []];
        second[0] = l.slice(mid + 1);
        second[1] = lists[(k + 1) % 3];
        split([m, vk1, vk2], second);
      };
      for (let t = 0; t < idx.length; t += 3) {
        if (![0, 1, 2].some((k) => onEdge.has(t + k))) {
          triangles.push(idx[t], idx[t + 1], idx[t + 2]);
          continue;
        }
        const lists = [0, 1, 2].map((k) => (onEdge.get(t + k) ?? []).map(([s, v]) => cornerAt(idx[t + k], idx[next(t + k)], s, v)));
        split([idx[t], idx[t + 1], idx[t + 2]], lists);
      }
      channels.forEach(([semantic, accessor, target], k) => {
        const own = accessor.listParents().filter((p) => p.propertyType !== "Root").length > 1 ? accessor.clone() : accessor;
        if (own !== accessor) (target ?? prim).setAttribute(semantic, own);
        const { array, size } = data[k];
        const out = new array.constructor((n + made.length) * size);
        out.set(array);
        made.forEach((values, j) => {
          for (let c = 0; c < size; c++) out[(n + j) * size + c] = array instanceof Float32Array ? values[k][c] : Math.round(values[k][c]);
        });
        own.setArray(out);
      });
      const ownIndices = indexAccessor.listParents().filter((p) => p.propertyType !== "Root").length > 1 ? indexAccessor.clone() : indexAccessor;
      if (ownIndices !== indexAccessor) prim.setIndices(ownIndices);
      ownIndices.setArray(Uint32Array.from(triangles));
      stitched += made.length + reused;
    }
  }
  return stitched;
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
doc.setLogger(new Logger(Logger.Verbosity.ERROR));
const before = stats(doc, input);
// as game.mjs reads it: plain geometry, identical vertices merged (UV seams stay split)
await doc.transform(dequantize());
const UNPACK = new Set(["KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_mesh_quantization"]);
for (const ext of doc.getRoot().listExtensionsUsed()) {
  if (UNPACK.has(ext.extensionName)) ext.dispose();
}
await doc.transform(dedup(), weld());
const duplicates = dropDuplicates(doc); // first: a copy would make its edges look shared by three
const stitched = stitchTJunctions(doc);
const turned = orientOutward(doc);
const wrote = duplicates + stitched + turned > 0;
if (wrote) await io.write(output, doc);
console.log(JSON.stringify({ before, duplicates, stitched, turned, wrote }));
