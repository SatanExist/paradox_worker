// node simplify.mjs <vertices.f32> <faces.u32> <error> <out-faces.u32> [locked.u8]
// Collapses triangles while the surface stays within <error> (same units as the vertices) of where it was:
// AI models come with detail far finer than a printer can lay down. Open borders stay locked, so the holes the
// repair has to close are still the holes it would have seen; so do the vertices marked 1 in [locked.u8] (one
// byte a vertex): spots a first pass moved too far. Vertices are kept (the new faces reuse them).
import { readFileSync, writeFileSync } from "node:fs";
import { MeshoptSimplifier } from "meshoptimizer";

const [vPath, fPath, error, outPath, lockPath] = process.argv.slice(2);
if (!vPath || !fPath || !error || !outPath) {
  console.error("usage: node simplify.mjs <vertices.f32> <faces.u32> <error> <out-faces.u32> [locked.u8]");
  process.exit(2);
}

await MeshoptSimplifier.ready;
const V = new Float32Array(readFileSync(vPath).buffer.slice(0));
const F = new Uint32Array(readFileSync(fPath).buffer.slice(0));
const target = Number(error) / MeshoptSimplifier.getScale(V, 3);
let faces;
if (lockPath) {
  // Only the attribute-aware entry point takes a lock list; no attributes are weighed (one zero per vertex).
  MeshoptSimplifier.useExperimentalFeatures = true;
  const lock = new Uint8Array(readFileSync(lockPath).buffer.slice(0));
  [faces] = MeshoptSimplifier.simplifyWithAttributes(F, V, 3, new Float32Array(V.length / 3), 1, [], lock, 0, target, ["LockBorder"]);
} else {
  [faces] = MeshoptSimplifier.simplify(F, V, 3, 0, target, ["LockBorder"]);
}
writeFileSync(outPath, Buffer.from(faces.buffer, faces.byteOffset, faces.byteLength));
