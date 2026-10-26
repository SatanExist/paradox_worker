"""Bake a heavy model's look onto its light game version, in Blender (headless).

  blender -b --factory-startup -P tools_blender/bake.py -- <high.glb> <low.glb> <out.glb> '{"size":2048}'

The light version gets new UVs of its own (its cut ignored the old seams) and one material whose
textures are baked from the heavy one, ray by ray: base colour, roughness, metalness and a tangent
normal map that carries the shape the cut took away. Same files and settings give the same pixels:
Cycles on the CPU with a fixed seed and sample count. Prints a JSON line on stdout.
"""

import json
import math
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
MARGIN = max(4, BAKE // 128)  # texels painted past island edges, so mip-maps don't bleed the background

t0 = time.time()
bpy.ops.wm.read_factory_settings(use_empty=True)


def imported(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    return [o for o in bpy.data.objects if o not in before and o.type == "MESH"]


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
bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=2 * MARGIN / BAKE, area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
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

# The final material: the baked maps on a plain Principled BSDF, as the glTF exporter reads it.
nodes.clear()
tree = target.node_tree
out = nodes.new("ShaderNodeOutputMaterial")
bsdf = nodes.new("ShaderNodeBsdfPrincipled")
tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
base = nodes.new("ShaderNodeTexImage")
base.image = maps["baseColor"]
tree.links.new(base.outputs["Color"], bsdf.inputs["Base Color"])
mr_node = nodes.new("ShaderNodeTexImage")
mr_node.image = mr
split = nodes.new("ShaderNodeSeparateColor")
tree.links.new(mr_node.outputs["Color"], split.inputs["Color"])
tree.links.new(split.outputs["Green"], bsdf.inputs["Roughness"])
tree.links.new(split.outputs["Blue"], bsdf.inputs["Metallic"])
nrm = nodes.new("ShaderNodeTexImage")
nrm.image = maps["normal"]
nmap = nodes.new("ShaderNodeNormalMap")
tree.links.new(nrm.outputs["Color"], nmap.inputs["Color"])
tree.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])

bpy.ops.object.select_all(action="DESELECT")
for o in low:
    o.select_set(True)
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=True, export_image_format="AUTO", export_tangents=False, export_yup=True)
print(json.dumps({"bake": {"size": SIZE, "supersample": SUPER, "samples": SAMPLES, "reachPct": REACH * 100, "seconds": round(time.time() - t0, 1), "passes": timings}}))
