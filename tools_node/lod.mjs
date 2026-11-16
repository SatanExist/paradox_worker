// LOD levels in one file: node lod.mjs <out.glb> <base> <lod0.glb> <lod1.glb>@dx,dy,dz ...
// One scene with nodes <base>_LOD0, <base>_LOD1, ... (the names Unity and Unreal group as levels), each holding that
// level's own nodes, meshes, materials and textures. The offset moves a level onto LOD0: each cut was placed on the
// floor its own way, a hair apart (up to 0.3% of the size on the bench).
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { mergeDocuments, prune, unpartition } from "@gltf-transform/functions";

const [out, base, ...levels] = process.argv.slice(2);
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
const doc = await io.read(levels[0].split("@")[0]);
const sceneOf = (d) => d.getRoot().getDefaultScene() ?? d.getRoot().listScenes()[0];
const scene = sceneOf(doc);
const wraps = [];
const wrap = (nodes, k, offset) => {
  const lod = doc.createNode(`${base}_LOD${k}`).setTranslation(offset);
  for (const n of nodes) {
    for (const s of doc.getRoot().listScenes()) s.removeChild(n);
    lod.addChild(n);
  }
  scene.addChild(lod);
  wraps.push(lod);
};
wrap(scene.listChildren(), 0, [0, 0, 0]);
for (let k = 1; k < levels.length; k++) {
  const [file, offset] = levels[k].split("@");
  const src = await io.read(file);
  const map = mergeDocuments(doc, src);
  wrap(sceneOf(src).listChildren().map((n) => map.get(n)), k, offset ? offset.split(",").map(Number) : [0, 0, 0]);
}

// A rigged model: every level is a cut of the same rigged original and brings its own copy of the skeleton. The
// levels' meshes are put on LOD0's bones and the copies dropped, so one skeleton moves every level (glTF lets meshes
// share joints; Unreal's and Unity's LODs share one skeleton the same way). Only when each of a level's bones has a
// LOD0 bone of the same name in the same place (after the level's offset) and holds nothing but bones; otherwise
// that level keeps its own skeleton and the output says so.
const under = (root) => {
  const out = [];
  root.traverse((n) => out.push(n));
  return out;
};
const skinsUnder = (root) => [...new Set(under(root).map((n) => n.getSkin()).filter(Boolean))];
const bones0 = new Map();
for (const s of skinsUnder(wraps[0])) for (const j of s.listJoints()) bones0.set(j.getName(), j);
const ext = (() => {
  const p = [...bones0.values()].map((j) => j.getWorldTranslation());
  return p.length ? Math.max(...[0, 1, 2].map((a) => Math.max(...p.map((v) => v[a])) - Math.min(...p.map((v) => v[a])))) : 0;
})();
const same = (a, b) => {
  const m = a.getWorldMatrix(), n = b.getWorldMatrix();
  return m.every((x, i) => Math.abs(x - n[i]) <= (i >= 12 ? 1e-4 * ext : 1e-4));
};
const skeleton = { levels: 0, shared: 0, own: [] };
if (bones0.size) {
  skeleton.levels = wraps.length;
  for (let k = 1; k < wraps.length; k++) {
    const skins = skinsUnder(wraps[k]);
    const old = new Set(skins.flatMap((s) => s.listJoints()));
    const fits = [...old].every((j) => bones0.has(j.getName()) && same(j, bones0.get(j.getName()))
      && j.listChildren().every((c) => old.has(c)));
    if (!skins.length || !fits) {
      skeleton.own.push(k);
      continue;
    }
    for (const s of skins) {
      const joints = s.listJoints();
      for (const j of joints) s.removeJoint(j);
      for (const j of joints) s.addJoint(bones0.get(j.getName()));
      s.setSkeleton(bones0.get(joints[0].getName()));
    }
    for (const j of old) j.dispose();
    skeleton.shared++;
  }
  // Engines put meshes on one skeleton under it (Godot moves them all under LOD0's), so each mesh carries its level
  // in its own name, <name>_<i>_LOD<k> (Unity's convention), unique so no engine renames one into another level.
  if (skeleton.shared) {
    wraps.forEach((w, k) => {
      let i = 0;
      for (const n of under(w)) if (n.getMesh()) n.setName(`${n.getName() || "mesh"}_${i++}_LOD${k}`);
    });
  }
}
for (const s of doc.getRoot().listScenes()) if (s !== scene) s.dispose();
doc.getRoot().setDefaultScene(scene);
await doc.transform(unpartition(), prune());
await io.write(out, doc);
console.log(JSON.stringify({ out, levels: levels.length, nodes: scene.listChildren().map((n) => n.getName()),
  ...(skeleton.levels ? { skeleton } : {}) }));
