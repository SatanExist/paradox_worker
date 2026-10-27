// node pose.mjs <in.glb> <out prefix> [frames per clip] [clips]
// How a rigged or morphing model stands in its clips, as three.js draws it (morph targets, then skinning).
// Writes <prefix>.u32 (triangle indices over all meshes) and <prefix>.f32: the file's own vertex positions,
// then the rest pose (bind pose, morphs off) in world space, then each frame in world space — frames
// evenly through each of the first clips. Prints {vertices, triangles, frames: [{clip, time}]} on stdout.
// game_prep uses it to find where a cut breaks when the model moves (tools_ops.py).
import { readFileSync, writeFileSync } from "node:fs";
import { Logger, NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { dequantize } from "@gltf-transform/functions";
import draco3d from "draco3dgltf";
import { MeshoptDecoder } from "meshoptimizer";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

const [input, prefix, framesArg, clipsArg] = process.argv.slice(2);
const FRAMES = Number(framesArg) || 6;
const CLIPS = Number(clipsArg) || 3;

// three's loader would try to decode images in Node and can't read Draco here: textures go, geometry unpacks.
await MeshoptDecoder.ready;
const io = new NodeIO()
  .registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({ "draco3d.decoder": await draco3d.createDecoderModule(), "meshopt.decoder": MeshoptDecoder });
const doc = await io.readBinary(new Uint8Array(readFileSync(input)));
doc.setLogger(new Logger(Logger.Verbosity.ERROR));
for (const texture of doc.getRoot().listTextures()) texture.dispose();
// Plain float positions, as game.mjs makes them: the file's own positions here are the points it keeps.
await doc.transform(dequantize());
for (const ext of doc.getRoot().listExtensionsUsed()) {
  if (["KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_mesh_quantization"].includes(ext.extensionName)) ext.dispose();
}
const glb = (await io.writeBinary(doc)).buffer;
const gltf = await new Promise((ok, bad) => new GLTFLoader().parse(glb.slice(0), "", ok, bad));

const meshes = [];
gltf.scene.traverse((o) => {
  if (o.isMesh) meshes.push(o);
});
const indices = [];
let count = 0;
for (const m of meshes) {
  const n = m.geometry.attributes.position.count;
  const own = m.geometry.index ? m.geometry.index.array : Array.from({ length: n }, (_, i) => i);
  for (const i of own) indices.push(i + count);
  count += n;
}
const clips = gltf.animations.slice(0, CLIPS);
const frames = clips.flatMap((clip) => Array.from({ length: FRAMES }, (_, k) => ({ clip, time: (clip.duration * (k + 0.5)) / FRAMES })));
const out = new Float32Array((2 + frames.length) * count * 3);
let at = 0;
for (const m of meshes) {
  // Element by element: an interleaved attribute's .array is the whole shared buffer (the fox's was),
  // and copying it whole gave junk points that matched nothing.
  const position = m.geometry.attributes.position;
  for (let i = 0; i < position.count; i++) {
    out[at++] = position.getX(i);
    out[at++] = position.getY(i);
    out[at++] = position.getZ(i);
  }
}

const mixer = new THREE.AnimationMixer(gltf.scene);
const v = new THREE.Vector3();
function pose(frame) {
  mixer.stopAllAction();
  gltf.scene.traverse((o) => {
    if (o.isSkinnedMesh) o.skeleton.pose();
    if (o.morphTargetInfluences) o.morphTargetInfluences.fill(0);
  });
  if (frame) {
    mixer.clipAction(frame.clip).play();
    mixer.setTime(frame.time);
  }
  gltf.scene.updateMatrixWorld(true);
  for (const m of meshes) {
    if (m.isSkinnedMesh) m.skeleton.update();
    for (let i = 0; i < m.geometry.attributes.position.count; i++) {
      m.getVertexPosition(i, v).applyMatrix4(m.matrixWorld);
      out[at++] = v.x;
      out[at++] = v.y;
      out[at++] = v.z;
    }
  }
}
pose(null);
for (const frame of frames) pose(frame);

writeFileSync(`${prefix}.u32`, Buffer.from(Uint32Array.from(indices).buffer));
writeFileSync(`${prefix}.f32`, Buffer.from(out.buffer));
process.stdout.write(JSON.stringify({ vertices: count, triangles: indices.length / 3, frames: frames.map((f) => ({ clip: f.clip.name, time: f.time })) }));
