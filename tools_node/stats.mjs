// What a game dev reads off a model, shared by game.mjs and repair.mjs.
import { statSync } from "node:fs";
import { ImageUtils } from "@gltf-transform/core";

export const TRIANGLES = 4;

/** What a game dev looks at: triangles drawn, vertices, materials, how big the textures are. */
export function stats(doc, path) {
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
