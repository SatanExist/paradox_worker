// node tangents.mjs <corners.f32> <out.f32>
// MikkTSpace tangents for tools_blender/bake.py: in, every triangle corner apart as [x y z nx ny nz u v] (float32);
// out, [tx ty tz sign] per corner, in the same space and UV convention. The same library graft.mjs puts the tangents
// into the file with, so the normal map is baked against the very tangents an engine reads. Blender's own MikkTSpace
// runs on many threads and came out a hair different each call (3-5 % of the mech's corners, ~1e-7), which now and
// then turned a normal-map texel the other way on a rerun; this one gives the same numbers every time (2026-11-21).
import { readFileSync, writeFileSync } from "node:fs";
import { generateTangents } from "mikktspace";

const [input, output] = process.argv.slice(2);
const corners = new Float32Array(new Uint8Array(readFileSync(input)).buffer);
const n = corners.length / 8;
const position = new Float32Array(3 * n);
const normal = new Float32Array(3 * n);
const uv = new Float32Array(2 * n);
for (let i = 0; i < n; i++) {
  position.set(corners.subarray(8 * i, 8 * i + 3), 3 * i);
  normal.set(corners.subarray(8 * i + 3, 8 * i + 6), 3 * i);
  uv.set(corners.subarray(8 * i + 6, 8 * i + 8), 2 * i);
}
writeFileSync(output, Buffer.from(generateTangents(position, normal, uv).buffer));
