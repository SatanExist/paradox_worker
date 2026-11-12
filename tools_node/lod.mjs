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
const wrap = (nodes, k, offset) => {
  const lod = doc.createNode(`${base}_LOD${k}`).setTranslation(offset);
  for (const n of nodes) {
    for (const s of doc.getRoot().listScenes()) s.removeChild(n);
    lod.addChild(n);
  }
  scene.addChild(lod);
};
wrap(scene.listChildren(), 0, [0, 0, 0]);
for (let k = 1; k < levels.length; k++) {
  const [file, offset] = levels[k].split("@");
  const src = await io.read(file);
  const map = mergeDocuments(doc, src);
  wrap(sceneOf(src).listChildren().map((n) => map.get(n)), k, offset ? offset.split(",").map(Number) : [0, 0, 0]);
}
for (const s of doc.getRoot().listScenes()) if (s !== scene) s.dispose();
doc.getRoot().setDefaultScene(scene);
await doc.transform(unpartition(), prune());
await io.write(out, doc);
console.log(JSON.stringify({ out, levels: levels.length, nodes: scene.listChildren().map((n) => n.getName()) }));
