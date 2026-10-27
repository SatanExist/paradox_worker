"""Bake a heavy model's look onto its light game version, in Blender (headless).

  blender -b --factory-startup -P tools_blender/bake.py -- <high.glb> <low.glb> <out dir> '{"size":2048}'

The light version gets new UVs of its own (its cut ignored the old seams) and textures baked from the
heavy one, ray by ray: base colour, roughness, metalness and a tangent normal map that carries the shape
the cut took away. Writes the maps (PNG) and the light model's triangle corners with their new UVs and
normals into <out dir>, for tools_node/graft.mjs to put into the light model. Same files and settings
give the same pixels: Cycles on the CPU with a fixed seed and sample count. Prints a JSON line on stdout.
"""

import json
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
HIGH, LOW, OUT = argv[:3]
PARAMS = json.loads(argv[3]) if len(argv) > 3 else {}
SIZE = int(PARAMS.get("size", 2048))
SAMPLES = int(PARAMS.get("samples", 8))
# How far rays look for the heavy surface, as a share of the model's size: the cut moved the surface
# by well under 1% on our models, a little more covers thin parts without catching the far side.
REACH = float(PARAMS.get("reach", 0.02))
# Baked this many times bigger, then shrunk: new UVs spend the texture less thriftily than the
# generator's own, and fine engraving came out noisy at the final size.
SUPER = int(PARAMS.get("supersample", 1))
BAKE = SIZE * SUPER
# Islands lie GAP texels apart and the bake paints MARGIN texels past their edges, filling the gaps so
# mip-maps don't bleed the background in. The gap is per island: smart_project's own margin (32 px a side
# at 2048) left 1-16% of the texture to the model once a cut had thousands of islands, and the more
# triangles, the blurrier it got.
GAP = max(2, BAKE // 512)
MARGIN = 2 * GAP

t0 = time.time()
bpy.ops.wm.read_factory_settings(use_empty=True)


def imported(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    # Meshes of the model only: for a rigged model the importer adds a sphere to draw the bones with, in a
    # collection it keeps out of renders (glTF_not_exported).
    return [o for o in bpy.data.objects if o not in before and o.type == "MESH" and o.data.polygons
            and not o.hide_render and not any(c.hide_render for c in o.users_collection)]


high = imported(HIGH)
# game.mjs stood the light one on the floor: move the heavy one the same way (glTF's Y up is Blender's Z).
sx, sy, sz = PARAMS.get("shift", [0, 0, 0])
for o in bpy.data.objects:
    if o.parent is None:
        o.location += Vector((sx, -sz, sy))
bpy.context.view_layer.update()
low = imported(LOW)
if not high or not low:
    raise SystemExit("no meshes to bake")

# Rigged and morphing models are baked as they stand at rest: bones in their bind pose, shape keys off.
armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
for arm in armatures:
    arm.data.pose_position = "REST"
for o in high + low:
    o.show_only_shape_key = bool(o.data.shape_keys)
    o.active_shape_key_index = 0
bpy.context.view_layer.update()

corners = [o.matrix_world @ Vector(c) for o in high for c in o.bound_box]
extent = max(max(c[i] for c in corners) - min(c[i] for c in corners) for i in range(3)) or 1.0

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = SAMPLES
scene.cycles.seed = 0
scene.cycles.use_denoising = False
bake = scene.render.bake
bake.use_selected_to_active = True
bake.use_cage = False
bake.cage_extrusion = REACH * extent
bake.max_ray_distance = 2 * REACH * extent
bake.margin = MARGIN
bake.margin_type = "EXTEND"

# The light version: smooth normals from its own shape (what the normal map is measured against),
# new UVs shared by all its parts, old UVs gone.
bpy.ops.object.select_all(action="DESELECT")
for o in low:
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    o.data.shade_smooth()
    if o.data.has_custom_normals:
        bpy.context.view_layer.objects.active = o
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
    for layer in list(o.data.uv_layers):
        o.data.uv_layers.remove(layer)
    o.data.uv_layers.new(name="UVMap")
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.0, area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
bpy.ops.uv.pack_islands(rotate=True, rotate_method="ANY", scale=True, margin_method="FRACTION", margin=GAP / BAKE, shape_method="CONCAVE")
bpy.ops.object.mode_set(mode="OBJECT")


def image(name, colour):
    img = bpy.data.images.new(name, BAKE, BAKE, alpha=False, float_buffer=False)
    img.colorspace_settings.name = "sRGB" if colour else "Non-Color"
    return img


# Every light part gets one material whose active node is the image being baked into.
target = bpy.data.materials.new("baked")
target.use_nodes = True
nodes = target.node_tree.nodes
slot = nodes.new("ShaderNodeTexImage")
nodes.active = slot
for o in low:
    o.data.materials.clear()
    o.data.materials.append(target)


def principled(material):
    return next((n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if material and material.use_nodes else None


def run(kind, img, **extra):
    slot.image = img
    bpy.ops.object.select_all(action="DESELECT")
    for o in high:
        o.select_set(True)
    for i, o in enumerate(low):
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.bake(type=kind, use_clear=(i == 0), margin=MARGIN, **extra)
        o.select_set(False)


def shine(socket_name):
    """Make the heavy model glow with one of its inputs (as it is, texture or value) and nothing else."""
    for o in high:
        for material in o.data.materials:
            p = principled(material)
            if not p:
                continue
            tree = material.node_tree
            for link in list(p.inputs["Emission Color"].links):
                tree.links.remove(link)
            given = p.inputs[socket_name]
            if given.links:
                tree.links.new(given.links[0].from_socket, p.inputs["Emission Color"])
            else:
                v = given.default_value
                p.inputs["Emission Color"].default_value = tuple(v) if hasattr(v, "__len__") else (v, v, v, 1)
            p.inputs["Emission Strength"].default_value = 1.0


timings = {}
maps = {}
for name, kind, colour, extra in [
    ("roughness", "ROUGHNESS", False, {}),
    ("normal", "NORMAL", False, {"normal_space": "TANGENT"}),
]:
    t = time.time()
    maps[name] = image(name, colour)
    run(kind, maps[name], **extra)
    timings[name] = round(time.time() - t, 1)

# Base colour and metalness are baked as light the heavy model gives off: Cycles' diffuse colour pass
# is base colour x (1 - metalness), which turned metal parts black.
for name, socket_name, colour in [("baseColor", "Base Color", True), ("metallic", "Metallic", False)]:
    t = time.time()
    shine(socket_name)
    maps[name] = image(name, colour)
    run("EMIT", maps[name])
    timings[name] = round(time.time() - t, 1)

# glTF keeps roughness in G and metalness in B of one texture.
for img in maps.values():
    if SUPER > 1:
        img.scale(SIZE, SIZE)


def pixels(img):
    a = np.empty(SIZE * SIZE * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(-1, 4)


packed = np.zeros((SIZE * SIZE, 4), dtype=np.float32)
packed[:, 1] = pixels(maps["roughness"])[:, 0]
packed[:, 2] = pixels(maps["metallic"])[:, 0]
packed[:, 3] = 1.0
mr = bpy.data.images.new("metallicRoughness", SIZE, SIZE, alpha=False, float_buffer=False)
mr.colorspace_settings.name = "Non-Color"
mr.pixels.foreach_set(packed.ravel())
for img in (maps["baseColor"], mr, maps["normal"]):
    img.pack()

# Out go the baked maps and, for every light mesh, each triangle corner as Blender holds it: position,
# normal (the smooth ones the normal map was baked against) and new UV. tools_node/graft.mjs puts them
# into the light model itself; exporting from Blender instead redid rigs: CesiumMan stood 57% off.
for name, img in (("baseColor", maps["baseColor"]), ("metallicRoughness", mr), ("normal", maps["normal"])):
    img.filepath_raw = os.path.join(OUT, name + ".png")
    img.file_format = "PNG"
    img.save()
meshes = []
corners = []
for o in low:
    mesh = o.data
    if any(len(poly.vertices) != 3 for poly in mesh.polygons):
        raise SystemExit("the light model came in with faces that aren't triangles")
    n = len(mesh.loops)
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co)
    loop_vertex = np.empty(n, dtype=np.int64)
    mesh.loops.foreach_get("vertex_index", loop_vertex)
    normals = np.empty(n * 3, dtype=np.float32)
    mesh.corner_normals.foreach_get("vector", normals)
    uv = np.empty(n * 2, dtype=np.float32)
    mesh.uv_layers.active.data.foreach_get("uv", uv)
    corners.append(np.hstack([co.reshape(-1, 3)[loop_vertex], normals.reshape(-1, 3), uv.reshape(-1, 2)]).astype(np.float32))
    meshes.append({"name": mesh.name, "corners": n})
np.vstack(corners).tofile(os.path.join(OUT, "corners.f32"))
with open(os.path.join(OUT, "corners.json"), "w") as fh:
    json.dump(meshes, fh)
print(json.dumps({"bake": {"size": SIZE, "supersample": SUPER, "samples": SAMPLES, "reachPct": REACH * 100, "seconds": round(time.time() - t0, 1), "passes": timings}}))
