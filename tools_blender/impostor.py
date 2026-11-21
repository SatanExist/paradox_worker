"""Octahedral impostor of the light model, for game_prep's impostor: true (studio_bridge/game_impostor.py).

blender -b --factory-startup --python impostor.py -- <model.glb> <out dir> '{"frames": 12, "framePx": 85}'

An impostor stands in for the model when it is only a few dozen pixels on screen: a square of two triangles
that faces the camera and shows the model as pictured from that side. Pictures from frames x frames directions
over the upper half-sphere, laid out by the hemi-octahedral map (Ryan Brucks' impostors, Fortnite): grid point
(i, j) -> u, v in [-1, 1] -> x = (u - v) / 2, z = (u + v) / 2, y = 1 - |x| - |z| (glTF axes, Y up). Each picture is
an orthographic view of the model's bounding sphere, one render each: base colour as light, the rest as extra passes.
Writes color.png (base colour, sRGB, alpha = coverage), depth.png (grey: 0 the sphere's near side, 1 its far side),
orm.png (as glTF: R occlusion, G roughness, B metalness; alpha = coverage), bins.png and prints a JSON line.

bins.png: the normals under each pixel, sorted into 12 bins by the nearest of 12 fixed model-space directions (an
icosahedron's corners). One atlas per bin, stacked top to bottom: RGB the bin's mean normal (glTF axes, * 0.5 + 0.5;
its length tells how much the normals in it agree), A the bin's share of the pixel. A pixel's light is the sum of its
bins' lights, each bin its own lobe: one averaged normal can't light a pixel that holds panels facing different ways
(the mech's front 6-9 % too bright, its back lit 31-55 % too dark; 2026-11-20). Multi-lobe normal distributions as
in Tan et al. 2005 and Han et al. 2007, with fixed directions so filtering and blending of the bins stay exact.
Stored as mean + share, not as sums: 8-bit sums round small bins away.
Cycles on the CPU, fixed seed and samples: the same pixels each run.
"""
import json
import os
import shutil
import struct
import sys
import time
import zlib

import bpy
import numpy as np
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, OUT = argv[0], os.path.abspath(argv[1])
PARAMS = json.loads(argv[2]) if len(argv) > 2 else {}
N = int(PARAMS.get("frames", 12))
F = int(PARAMS.get("framePx", 85))
SAMPLES = 16
# Bin directions, glTF axes: the 12 corners of an icosahedron, evenly spread (6 cube faces were too coarse: panels
# 45 degrees between two axes split between bins and lit wrong; 26 directions lit hardly better, 2026-11-20).
_G = (1 + 5 ** 0.5) / 2
BINS = np.array([p for a in (1, -1) for b in (_G, -_G) for p in ([0, a, b], [a, b, 0], [b, 0, a])], float)
BINS /= np.linalg.norm(BINS, axis=1, keepdims=True)
K = len(BINS)
GROUPS = (K + 2) // 3  # shares go 3 to a colour pass
os.makedirs(OUT, exist_ok=True)
t0 = time.time()

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.data.polygons and not o.hide_render
          and not any(c.hide_render for c in o.users_collection)]
for o in meshes:
    o.show_only_shape_key = bool(o.data.shape_keys)
bpy.context.view_layer.update()

# Bounding sphere: box centre, farthest vertex.
pts = []
for o in meshes:
    co = np.empty(len(o.data.vertices) * 3)
    o.data.vertices.foreach_get("co", co)
    m = np.array(o.matrix_world)
    pts.append(co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3])
pts = np.concatenate(pts)
centre = (pts.min(0) + pts.max(0)) / 2
R = float(np.linalg.norm(pts - centre, axis=1).max())
D = 2 * R  # camera distance from the centre

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = SAMPLES
scene.cycles.seed = 0
scene.cycles.use_denoising = False
scene.cycles.max_bounces = 0
scene.render.use_persistent_data = True
scene.render.film_transparent = True
scene.render.resolution_x = scene.render.resolution_y = F
scene.render.resolution_percentage = 100
scene.view_settings.view_transform = "Standard"
scene.render.image_settings.file_format = "OPEN_EXR"
scene.render.image_settings.color_mode = "RGBA"
scene.render.image_settings.color_depth = "32"
scene.world = bpy.data.worlds.new("none")
scene.world.color = (0, 0, 0)

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
cam.data.type = "ORTHO"
cam.data.ortho_scale = 2 * R
cam.data.clip_start = R * 0.01
cam.data.clip_end = D + 2 * R
scene.collection.objects.link(cam)
scene.camera = cam

# Every material shows its base colour as light (emission) and hands the rest to the picture as extra passes (AOVs):
# depth, occlusion / roughness / metalness like glTF's ORM texture, and the normal binned. One render per picture.
sources = []
for mat in {s.material for o in meshes for s in o.material_slots if s.material}:
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
    if bsdf is None or out is None:
        continue

    def source(name):
        s = bsdf.inputs[name]
        return s.links[0].from_socket if s.links else None

    emit = nt.nodes.new("ShaderNodeEmission")
    clear = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    alpha = source("Alpha")
    if alpha:
        nt.links.new(alpha, mix.inputs[0])
    else:
        mix.inputs[0].default_value = bsdf.inputs["Alpha"].default_value
    nt.links.new(clear.outputs[0], mix.inputs[1])
    nt.links.new(emit.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    for link in list(out.inputs["Volume"].links) + list(out.inputs["Displacement"].links):
        nt.links.remove(link)

    color = source("Base Color")
    if color is None:
        rgb = nt.nodes.new("ShaderNodeRGB")
        rgb.outputs[0].default_value = bsdf.inputs["Base Color"].default_value
        color = rgb.outputs[0]
    normal = source("Normal") or nt.nodes.new("ShaderNodeNewGeometry").outputs["Normal"]
    depth = nt.nodes.new("ShaderNodeMath")
    depth.operation = "MULTIPLY_ADD"
    nt.links.new(nt.nodes.new("ShaderNodeCameraData").outputs["View Z Depth"], depth.inputs[0])
    depth.inputs[1].default_value = 1 / (2 * R)
    depth.inputs[2].default_value = -(D - R) / (2 * R)
    nt.links.new(color, emit.inputs["Color"])
    # Occlusion as the model's own material has it (glTF occlusion map, strength included; the importer hooks it to
    # its "glTF Material Output" group), else none: the engine gives the model only that, and the impostor's own
    # shadows and the engine's SSAO (it writes depth) do the rest for both alike.
    orm = nt.nodes.new("ShaderNodeCombineXYZ")
    occ = next((n.inputs["Occlusion"] for n in nt.nodes if n.type == "GROUP" and "Occlusion" in n.inputs), None)
    if occ is not None and occ.links:
        nt.links.new(occ.links[0].from_socket, orm.inputs[0])
    else:
        orm.inputs[0].default_value = 1.0
    for k, name in ((1, "Roughness"), (2, "Metallic")):
        src = source(name)
        if src:
            nt.links.new(src, orm.inputs[k])
        else:
            orm.inputs[k].default_value = bsdf.inputs[name].default_value
    for name, sock in (("dep", depth.outputs[0]), ("orm", orm.outputs[0])):
        aov = nt.nodes.new("ShaderNodeOutputAOV")
        aov.aov_name = name
        nt.links.new(sock, aov.inputs["Value" if name == "dep" else "Color"])

    def math(op, a, b):
        node = nt.nodes.new("ShaderNodeMath")
        node.operation = op
        for k, x in enumerate((a, b)):
            if isinstance(x, float):
                node.inputs[k].default_value = x
            else:
                nt.links.new(x, node.inputs[k])
        return node.outputs[0]

    # Each sample puts its normal in the bin of the nearest direction (the first of them on a tie, so a normal right
    # between two always lands in one): dot above every earlier bin's and at least every later one's (running maxima
    # from both ends). Cycles averages the samples, so a pixel gets each bin's sum of normals and its share.
    dots = []
    for b in BINS:
        dp = nt.nodes.new("ShaderNodeVectorMath")
        dp.operation = "DOT_PRODUCT"
        nt.links.new(normal, dp.inputs[0])
        dp.inputs[1].default_value = (b[0], -b[2], b[1])  # glTF -> Blender axes
        dots.append(dp.outputs["Value"])
    before, after = [None] * K, [None] * K
    for j in range(1, K):
        before[j] = dots[0] if j == 1 else math("MAXIMUM", before[j - 1], dots[j - 1])
    for j in range(K - 2, -1, -1):
        after[j] = dots[K - 1] if j == K - 2 else math("MAXIMUM", after[j + 1], dots[j + 1])
    shares = []
    for j in range(K):
        parts = ([math("GREATER_THAN", dots[j], before[j])] if before[j] is not None else []) + (
            [math("SUBTRACT", 1.0, math("LESS_THAN", dots[j], after[j]))] if after[j] is not None else [])
        ind = parts[0] if len(parts) == 1 else math("MULTIPLY", parts[0], parts[1])
        vec = nt.nodes.new("ShaderNodeVectorMath")
        vec.operation = "SCALE"
        nt.links.new(normal, vec.inputs[0])
        nt.links.new(ind, vec.inputs["Scale"])
        aov = nt.nodes.new("ShaderNodeOutputAOV")
        aov.aov_name = f"b{j}"
        nt.links.new(vec.outputs[0], aov.inputs["Color"])
        shares.append(ind)
    for g in range(GROUPS):
        cmb = nt.nodes.new("ShaderNodeCombineXYZ")
        for c in range(3):
            if 3 * g + c < K:
                nt.links.new(shares[3 * g + c], cmb.inputs[c])
        aov = nt.nodes.new("ShaderNodeOutputAOV")
        aov.aov_name = f"s{g}"
        nt.links.new(cmb.outputs[0], aov.inputs["Color"])

vl = scene.view_layers[0]
for name in ["dep", "orm"] + [f"b{j}" for j in range(K)] + [f"s{g}" for g in range(GROUPS)]:
    a = vl.aovs.add()
    a.name = name
    a.type = "VALUE" if name == "dep" else "COLOR"
scene.use_nodes = True
tree = scene.node_tree
for n in list(tree.nodes):
    tree.nodes.remove(n)
layers = tree.nodes.new("CompositorNodeRLayers")
files = tree.nodes.new("CompositorNodeOutputFile")
files.base_path = os.path.join(OUT, "frame")
files.format.file_format = "OPEN_EXR"
files.format.color_mode = "RGBA"
files.format.color_depth = "32"
files.file_slots.clear()
PASSES = {"color": "Image", "depth": "dep", "orm": "orm", **{f"b{j}": f"b{j}" for j in range(K)},
          **{f"s{g}": f"s{g}" for g in range(GROUPS)}}
for kind, sock in PASSES.items():
    files.file_slots.new(kind + "_")
    tree.links.new(layers.outputs[sock], files.inputs[kind + "_"])
comp = tree.nodes.new("CompositorNodeComposite")
tree.links.new(layers.outputs["Image"], comp.inputs["Image"])


def blender(v):
    """glTF axes (Y up) -> Blender's (Z up)."""
    return Vector((v[0], -v[2], v[1]))


def frame_dir(i, j):
    u, v = i / (N - 1) * 2 - 1, j / (N - 1) * 2 - 1
    x, z = (u - v) / 2, (u + v) / 2
    d = np.array([x, 1 - abs(x) - abs(z), z])
    return d / np.linalg.norm(d)


def basis(f):
    """right, up of the picture looking along -f (the shader builds the same)."""
    ref = np.array([0.0, 1.0, 0.0]) if abs(f[1]) < 0.999 else np.array([0.0, 0.0, -1.0])
    r = np.cross(ref, f)
    r /= np.linalg.norm(r)
    return r, np.cross(f, r)


atlas = {k: np.zeros((N, N, F, F, 4), np.float32) for k in PASSES}
for j in range(N):
    for i in range(N):
        f = frame_dir(i, j)
        r, u = basis(f)
        m = Matrix.Identity(4)
        for k, axis in enumerate((r, u, f)):
            m.col[k][:3] = blender(axis)
        m.col[3][:3] = Vector(centre) + blender(f) * D
        cam.matrix_world = m
        bpy.ops.render.render()
        for kind in PASSES:
            path = os.path.join(OUT, "frame", f"{kind}_{scene.frame_current:04d}.exr")
            img = bpy.data.images.load(path)
            px = np.empty(F * F * 4, np.float32)
            img.pixels.foreach_get(px)
            bpy.data.images.remove(img)
            atlas[kind][j, i] = px.reshape(F, F, 4)[::-1]  # rows from the top
shutil.rmtree(os.path.join(OUT, "frame"))

# Cycles gives colour times coverage: divide it out, then pad empty pixels from their neighbours (like a bake
# margin) so filtering at the outline never pulls in black.
cover = atlas["color"][..., 3:4]
vals = {k: atlas[k][..., :3] / np.maximum(cover, 1e-6) for k in atlas}


def pad(vals, have):
    """Each empty pixel takes the mean of its filled 4-neighbours, ring after ring, within each picture. Only the
    ring that grows is worked on (the same sums in the same order as over whole pictures, so the same pixels)."""
    have = have.reshape(N * N, F, F).copy()
    flat = {k: v.reshape(N * N, F, F, -1) for k, v in vals.items()}  # views: written through
    for _ in range(F):
        if have.all():
            break
        near = np.zeros_like(have)
        near[:, 1:] |= have[:, :-1]
        near[:, :-1] |= have[:, 1:]
        near[:, :, 1:] |= have[:, :, :-1]
        near[:, :, :-1] |= have[:, :, 1:]
        p, y, x = np.nonzero(~have & near)
        if not len(p):
            break
        cnt = np.zeros(len(p), np.float32)
        acc = {k: np.zeros((len(p), v.shape[-1]), np.float32) for k, v in flat.items()}
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            yy, xx = y - dy, x - dx
            inside = (yy >= 0) & (yy < F) & (xx >= 0) & (xx < F)
            yy, xx = yy.clip(0, F - 1), xx.clip(0, F - 1)
            w = (inside & have[p, yy, xx]).astype(np.float32)
            cnt += w
            for k, v in flat.items():
                acc[k] += v[p, yy, xx] * w[:, None]
        for k, v in flat.items():
            v[p, y, x] = acc[k] / cnt[:, None]
        have[p, y, x] = True


# Bins: each bin's share of the pixel's covered samples, padded like the colour (at the outline filtering then still
# sums the shares to 1, not to the coverage), and its mean normal (sum / share, glTF axes, no longer than 1), padded
# where the bin is empty from where it isn't, so filtering never pulls a bin's mean toward nothing.
shares = np.ascontiguousarray(np.concatenate([vals[f"s{g}"] for g in range(GROUPS)], -1)[..., :K])
means = []
for j in range(K):
    b, s = vals[f"b{j}"], shares[..., j:j + 1]
    m = np.where(s > 0, np.stack([b[..., 0], b[..., 2], -b[..., 1]], -1) / np.maximum(s, 1e-12), 0.0).astype(np.float32)
    m /= np.maximum(np.linalg.norm(m, axis=-1, keepdims=True), 1.0)
    pad({"m": m}, s[..., 0] > 0)
    means.append(m)
pad({"color": vals["color"], "depth": vals["depth"], "orm": vals["orm"], "shares": shares}, cover[..., 0] > 0)


def srgb(c):
    c = c.clip(0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def tile(a):
    """(N, N, F, F, C) -> (N*F, N*F, C), frame (i, j) at column i, row j from the top."""
    return a.transpose(0, 2, 1, 3, 4).reshape(N * F, N * F, a.shape[-1])


def png(path, px):
    """8-bit PNG: 1 channel grey, 4 RGBA."""
    rows = (px.clip(0, 1) * 255 + 0.5).astype(np.uint8)
    raw = b"".join(b"\x00" + r.tobytes() for r in rows)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    head = struct.pack(">IIBBBBB", px.shape[1], px.shape[0], 8, {1: 0, 4: 6}[px.shape[-1]], 0, 0, 0)
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


png(os.path.join(OUT, "color.png"), tile(np.concatenate([srgb(vals["color"]), cover], -1)))
png(os.path.join(OUT, "depth.png"), tile(vals["depth"][..., :1]))
png(os.path.join(OUT, "orm.png"), tile(np.concatenate([vals["orm"], cover], -1)))
png(os.path.join(OUT, "bins.png"), np.concatenate([tile(np.concatenate([m * 0.5 + 0.5, shares[..., j:j + 1]], -1))
                                                   for j, m in enumerate(means)], 0))
c = [float(centre[0]), float(centre[2]), float(-centre[1])]  # back to glTF axes
box = pts.max(0) - pts.min(0)
info = {"frames": N, "framePx": F, "bins": K, "radius": R, "centre": c, "diagonal": float(np.linalg.norm(box)),
        "seconds": round(time.time() - t0, 1)}
print(json.dumps({"impostor": info}))
