import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

/**
 * One-shot GLB snapshot for gallery cards. Reuses a small renderer.
 * Not the product viewer — no orbit, no cove.
 */

let shared = null;

function getShared(size) {
  if (shared && shared.size === size) return shared;
  if (shared) {
    shared.renderer.dispose();
    shared.renderer.domElement.remove();
  }
  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: false,
    preserveDrawingBuffer: true,
  });
  renderer.setPixelRatio(1);
  renderer.setSize(size, size, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.12;
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envRT = pmrem.fromScene(new RoomEnvironment(), 0.04);
  pmrem.dispose();
  shared = { renderer, env: envRT.texture, envRT, size };
  return shared;
}

function disposeObject(root) {
  root.traverse((node) => {
    if (node.geometry) node.geometry.dispose();
    const mats = node.material
      ? Array.isArray(node.material)
        ? node.material
        : [node.material]
      : [];
    for (const mat of mats) {
      if (!mat) continue;
      for (const value of Object.values(mat)) {
        if (value && value.isTexture) value.dispose();
      }
      mat.dispose();
    }
  });
}

export async function captureGlbThumb(url, { size = 256 } = {}) {
  const { renderer, env } = getShared(size);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x2a2a30);
  scene.environment = env;
  scene.environmentIntensity = 1.2;
  const camera = new THREE.PerspectiveCamera(32, 1, 0.01, 80);
  scene.add(new THREE.HemisphereLight(0xe8f0ff, 0x1a120c, 0.4));
  const key = new THREE.DirectionalLight(0xfff2dc, 2.05);
  key.position.set(2.4, 3.4, 3.6);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0x9ec5ff, 0.45);
  fill.position.set(-3, 2, 1);
  scene.add(fill);

  const gltf = await new GLTFLoader().loadAsync(url);
  const root = gltf.scene;
  scene.add(root);

  const box = new THREE.Box3().setFromObject(root);
  const center = box.getCenter(new THREE.Vector3());
  const sizeVec = box.getSize(new THREE.Vector3());
  const dim = Math.max(sizeVec.x, sizeVec.y, sizeVec.z, 0.001);
  camera.position.set(center.x + dim * 0.35, center.y + dim * 0.22, center.z + dim * 2.05);
  camera.lookAt(center);
  renderer.render(scene, camera);
  const dataUrl = renderer.domElement.toDataURL("image/jpeg", 0.84);

  scene.remove(root);
  disposeObject(root);
  return dataUrl;
}
