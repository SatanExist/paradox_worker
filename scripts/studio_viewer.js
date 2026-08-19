import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { GroundedSkybox } from "three/addons/objects/GroundedSkybox.js";

const DRACO_DECODER = "https://cdn.jsdelivr.net/npm/three@0.176.0/examples/jsm/libs/draco/gltf/";

/**
 * Shared GLB viewer: studio card (IBL + floor + orbit) and standard inspect.
 * Does not destroy native PBR — matte / albedo-only restore from mesh.userData.
 */
export function createStudioViewer(container, options = {}) {
  const onStatus = options.onStatus || (() => {});
  let mode = options.initialMode === "inspect" ? "inspect" : "studio";

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 80);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.autoRotateSpeed = 1.1;

  const hemi = new THREE.HemisphereLight(0xe8f0ff, 0x1a120c, 0.35);
  scene.add(hemi);
  const key = new THREE.DirectionalLight(0xfff2dc, 2.2);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.bias = -0.00025;
  scene.add(key);
  const fill = new THREE.DirectionalLight(0x9ec5ff, 0.55);
  fill.position.set(-4, 2, 1);
  scene.add(fill);
  const rim = new THREE.DirectionalLight(0xff7a3d, 1.35);
  rim.position.set(-1.2, 2.4, -4);
  scene.add(rim);
  const inspectFill = new THREE.DirectionalLight(0xffffff, 0.85);
  inspectFill.position.set(-2, 3, 2);
  scene.add(inspectFill);

  const pmrem = new THREE.PMREMGenerator(renderer);
  const envRT = pmrem.fromScene(new RoomEnvironment(), 0.04);
  scene.environment = envRT.texture;
  pmrem.dispose();

  function makeCoveTexture(topHex, horizonHex, floorHex) {
    const c = document.createElement("canvas");
    c.width = 1024;
    c.height = 512;
    const ctx = c.getContext("2d");
    const g = ctx.createLinearGradient(0, 0, 0, c.height);
    g.addColorStop(0, `#${topHex.toString(16).padStart(6, "0")}`);
    g.addColorStop(0.46, `#${horizonHex.toString(16).padStart(6, "0")}`);
    g.addColorStop(0.52, `#${floorHex.toString(16).padStart(6, "0")}`);
    g.addColorStop(1, `#${floorHex.toString(16).padStart(6, "0")}`);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, c.width, c.height);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.needsUpdate = true;
    return tex;
  }

  const COVE_TEX = {
    studio: makeCoveTexture(0xb8b0a6, 0x8a847c, 0x5c5a60),
    gallery: makeCoveTexture(0xd8d6d2, 0xb0aea8, 0x6e6c70),
    outdoor: makeCoveTexture(0x9ec5ff, 0xc4b49a, 0x6a5a40),
    neon: makeCoveTexture(0x1a1020, 0x120818, 0x0a060c),
    night: makeCoveTexture(0x0e1420, 0x0a1018, 0x080a10),
  };

  const SKY_HEIGHT = 12;
  const SKY_RADIUS = 64;
  const skybox = new GroundedSkybox(COVE_TEX.studio, SKY_HEIGHT, SKY_RADIUS, 48);
  skybox.position.y = SKY_HEIGHT;
  skybox.renderOrder = -1;
  scene.add(skybox);

  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(1, 1),
    new THREE.ShadowMaterial({ opacity: 0.32, color: 0x000000 }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  scene.add(floor);

  const LIGHT_RIGS = {
    studio: {
      exposure: 1.15,
      ibl: 1.15,
      voidBg: false,
      hemi: [0xe8f0ff, 0x1a120c, 0.32],
      key: [0xfff2dc, 2.15],
      fill: [0x9ec5ff, 0.5],
      rim: [0xff7a3d, 1.25],
    },
    gallery: {
      exposure: 1.02,
      ibl: 1.45,
      voidBg: false,
      hemi: [0xf4f4f8, 0x3a3a40, 0.7],
      key: [0xffffff, 0.85],
      fill: [0xffffff, 0.55],
      rim: [0xffffff, 0.25],
    },
    outdoor: {
      exposure: 1.2,
      ibl: 0.7,
      voidBg: false,
      hemi: [0x9ec5ff, 0x3d2a18, 0.95],
      key: [0xfff1c4, 2.6],
      fill: [0x87b6ff, 0.35],
      rim: [0xffffff, 0.15],
    },
    neon: {
      exposure: 1.05,
      ibl: 0.45,
      voidBg: true,
      hemi: [0x1a1020, 0x08060c, 0.2],
      key: [0xff66aa, 0.55],
      fill: [0x00e5ff, 1.7],
      rim: [0xff2bd6, 2.1],
    },
    night: {
      exposure: 0.92,
      ibl: 0.4,
      voidBg: true,
      hemi: [0x6ea8ff, 0x0a0c12, 0.22],
      key: [0xc8d8ff, 0.45],
      fill: [0x3d5cff, 0.35],
      rim: [0x8eb4ff, 1.7],
    },
  };

  const grid = new THREE.GridHelper(8, 16, 0x5a5a62, 0x2e2e34);
  grid.material.transparent = true;
  grid.material.opacity = 0.55;
  scene.add(grid);

  let root = null;
  let loadSeq = 0;
  const dracoLoader = new DRACOLoader();
  dracoLoader.setDecoderPath(DRACO_DECODER);

  function makeGltfLoader() {
    const loader = new GLTFLoader();
    loader.setDRACOLoader(dracoLoader);
    return loader;
  }
  let framed = { center: new THREE.Vector3(), maxDim: 1 };
  let objectUrl = null;
  let iblOn = true;
  let autoOrbit = mode === "studio";
  let wireframe = false;
  let albedoOnly = false;
  let previewShade = false;
  let lightRig = "studio";
  let running = true;
  const previewMat = new THREE.MeshNormalMaterial({ flatShading: true });

  function rememberPbr(mesh) {
    const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    mesh.userData.origPbr = mats.map((m) =>
      m
        ? {
            metalness: m.metalness,
            roughness: m.roughness,
            envMapIntensity: m.envMapIntensity,
            wireframe: !!m.wireframe,
          }
        : null,
    );
  }

  function applyMaterialFlags() {
    if (!root) return;
    root.traverse((c) => {
      if (!c.isMesh) return;
      if (!c.userData.origPbr) rememberPbr(c);
      if (!c.userData.stdMat) c.userData.stdMat = c.material;
      if (previewShade) {
        c.material = previewMat;
        return;
      }
      c.material = c.userData.stdMat;
      const mats = Array.isArray(c.material) ? c.material : [c.material];
      mats.forEach((m, i) => {
        const orig = c.userData.origPbr[i];
        if (!m || !orig) return;
        m.wireframe = wireframe;
        if (albedoOnly) {
          m.metalness = 0;
          m.roughness = 1;
          m.envMapIntensity = 0;
        } else {
          m.metalness = orig.metalness;
          m.roughness = orig.roughness;
          m.envMapIntensity = orig.envMapIntensity ?? 1;
        }
        m.needsUpdate = true;
      });
    });
  }

  function colorInt(hex) {
    return typeof hex === "number" ? hex : new THREE.Color(hex).getHex();
  }

  function applyLightRig() {
    const rig = LIGHT_RIGS[lightRig] || LIGHT_RIGS.studio;
    hemi.color.setHex(colorInt(rig.hemi[0]));
    hemi.groundColor.setHex(colorInt(rig.hemi[1]));
    key.color.setHex(colorInt(rig.key[0]));
    fill.color.setHex(colorInt(rig.fill[0]));
    rim.color.setHex(colorInt(rig.rim[0]));
    return rig;
  }

  function applyMode() {
    const studio = mode === "studio";
    const rig = applyLightRig();
    if (studio) {
      const voidLook = !!rig.voidBg;
      skybox.material.map = COVE_TEX[lightRig] || COVE_TEX.studio;
      skybox.material.needsUpdate = true;
      skybox.visible = !voidLook;
      scene.background = voidLook ? new THREE.Color(0x050508) : null;
      scene.backgroundBlurriness = 0;
      scene.backgroundIntensity = 1;
      scene.fog = null;
      scene.environmentIntensity = iblOn ? rig.ibl : 0;
      renderer.toneMappingExposure = rig.exposure;
      hemi.intensity = rig.hemi[2];
      key.intensity = rig.key[1];
      fill.intensity = rig.fill[1];
      rim.intensity = rig.rim[1];
      inspectFill.intensity = 0;
      floor.material.opacity = voidLook ? 0.45 : 0.28;
    } else {
      skybox.visible = false;
      scene.background = new THREE.Color(0x1c1c22);
      scene.backgroundBlurriness = 0;
      scene.backgroundIntensity = 1;
      scene.fog = null;
      scene.environmentIntensity = 0;
      renderer.toneMappingExposure = 1.0;
      hemi.color.setHex(0xffffff);
      hemi.groundColor.setHex(0x444444);
      hemi.intensity = 0.55;
      key.color.setHex(0xffffff);
      key.intensity = 1.05;
      fill.intensity = 0.15;
      rim.intensity = 0;
      inspectFill.intensity = 0.7;
    }
    floor.visible = studio;
    grid.visible = !studio;
    controls.autoRotate = studio && autoOrbit;
    key.castShadow = studio;
  }

  function resize() {
    const w = Math.max(1, container.clientWidth);
    const h = Math.max(1, container.clientHeight);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  function setView(kind) {
    const { center, maxDim } = framed;
    const d = maxDim * 2.15;
    const y = center.y + maxDim * 0.12;
    if (kind === "front") camera.position.set(center.x, y, center.z + d);
    else if (kind === "side") camera.position.set(center.x + d, y, center.z);
    else camera.position.set(center.x, y, center.z - d);
    controls.target.copy(center);
    controls.update();
  }

  function frameObject(obj) {
    const box = new THREE.Box3().setFromObject(obj);
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z, 0.001);
    framed = { center: center.clone(), maxDim };
    const groundY = box.min.y + 0.002;
    skybox.position.set(center.x, box.min.y + SKY_HEIGHT, center.z);
    const skyScale = Math.max(1, (maxDim * 14) / SKY_RADIUS);
    skybox.scale.setScalar(skyScale);
    floor.position.set(center.x, groundY, center.z);
    floor.scale.setScalar(Math.max(8, maxDim * 18));
    grid.position.set(center.x, box.min.y, center.z);
    grid.scale.setScalar(Math.max(0.6, maxDim * 0.45));
    key.position.set(
      center.x + maxDim * 2.2,
      center.y + maxDim * 2.8,
      center.z + maxDim * 1.4,
    );
    key.target.position.copy(center);
    key.target.updateMatrixWorld();
    const e = maxDim * 2.4;
    key.shadow.camera.near = maxDim / 40;
    key.shadow.camera.far = maxDim * 18;
    key.shadow.camera.left = -e;
    key.shadow.camera.right = e;
    key.shadow.camera.top = e;
    key.shadow.camera.bottom = -e;
    key.shadow.camera.updateProjectionMatrix();
    camera.near = maxDim / 120;
    camera.far = Math.max(SKY_RADIUS * skyScale * 2.2, maxDim * 80);
    setView("front");
  }

  function disposeObject(obj) {
    obj.traverse((c) => {
      if (c.geometry) c.geometry.dispose();
      const mat = c.material;
      if (!mat) return;
      for (const m of Array.isArray(mat) ? mat : [mat]) {
        for (const value of Object.values(m)) {
          if (value && value.isTexture) value.dispose();
        }
        m.dispose();
      }
    });
  }

  function clearRoot() {
    if (!root) return;
    scene.remove(root);
    disposeObject(root);
    root = null;
  }

  async function loadFromUrl(url, label) {
    const seq = ++loadSeq;
    onStatus("Loading…");
    const loader = makeGltfLoader();
    try {
      let gltf;
      if (url.startsWith("blob:")) {
        gltf = await loader.loadAsync(url);
      } else {
        const ac = new AbortController();
        const timer = setTimeout(() => ac.abort(), 120000);
        let res;
        try {
          res = await fetch(url, { signal: ac.signal });
        } finally {
          clearTimeout(timer);
        }
        if (!res.ok) throw new Error(`GLB HTTP ${res.status}`);
        const buf = await res.arrayBuffer();
        if (seq !== loadSeq) return;
        onStatus(`Parsing ${(buf.byteLength / 1e6).toFixed(1)} MB…`);
        gltf = await new Promise((resolve, reject) => {
          loader.parse(buf, "", resolve, reject);
        });
      }
      if (seq !== loadSeq) {
        disposeObject(gltf.scene);
        return;
      }
      clearRoot();
      root = gltf.scene;
      let verts = 0;
      let tris = 0;
      root.traverse((c) => {
        if (!c.isMesh) return;
        c.castShadow = true;
        c.receiveShadow = true;
        rememberPbr(c);
        const g = c.geometry;
        verts += g.attributes.position?.count || 0;
        tris += g.index ? g.index.count / 3 : verts / 3;
      });
      scene.add(root);
      applyMaterialFlags();
      frameObject(root);
      onStatus(
        `${label} · ${Math.round(verts).toLocaleString()} v / ${Math.round(tris).toLocaleString()} t`,
      );
    } catch (err) {
      if (seq !== loadSeq) return;
      const msg = err && err.name === "AbortError" ? "GLB timeout" : (err.message || String(err));
      onStatus(msg);
      throw err;
    }
  }

  function loadFile(file) {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(file);
    return loadFromUrl(objectUrl, file.name);
  }

  applyMode();
  resize();
  const ro = new ResizeObserver(resize);
  ro.observe(container);

  function tick() {
    if (!running) return;
    requestAnimationFrame(tick);
    controls.update();
    renderer.render(scene, camera);
  }
  tick();

  return {
    loadFromUrl,
    loadFile,
    setView,
    setMode(next) {
      mode = next === "inspect" ? "inspect" : "studio";
      if (mode === "studio") autoOrbit = true;
      applyMode();
    },
    setIbl(on) {
      iblOn = !!on;
      applyMode();
    },
    setLightRig(name) {
      lightRig = LIGHT_RIGS[name] ? name : "studio";
      applyMode();
    },
    listLightRigs() {
      return Object.keys(LIGHT_RIGS);
    },
    setAutoOrbit(on) {
      autoOrbit = !!on;
      applyMode();
    },
    setWireframe(on) {
      wireframe = !!on;
      applyMaterialFlags();
    },
    setAlbedoOnly(on) {
      albedoOnly = !!on;
      applyMaterialFlags();
    },
    setPreviewShade(on) {
      previewShade = !!on;
      applyMaterialFlags();
    },
    getMode() {
      return mode;
    },
    dispose() {
      running = false;
      ro.disconnect();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      envRT.dispose();
      Object.values(COVE_TEX).forEach((t) => t.dispose());
      skybox.geometry.dispose();
      skybox.material.dispose();
      floor.geometry.dispose();
      floor.material.dispose();
      dracoLoader.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
}
