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

import bmesh
import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
HIGH, LOW, OUT = argv[:3]
PARAMS = json.loads(argv[3]) if len(argv) > 3 else {}
SIZE = int(PARAMS.get("size", 2048))
# A model coloured by its materials alone, no textures: only the normal map is baked, the materials stay.
# Baked into one atlas, BrainStem's 59 flat colours came out 86% of the picture off.
NORMAL_ONLY = bool(PARAMS.get("normalOnly"))
SAMPLES = int(PARAMS.get("samples", 8))
# How far rays look for the heavy surface, as a share of the model's size: they start this far out and
# look as far in. At 2% rays from the Rodin pump's wall met the hose hanging in front of it first and drew
# the hose onto the wall, and a groove's walls drew each other; at 0.5% the pump came out clean (2.62 ->
# 1.89% noticeable) and mech, drill and watch closer too (6.79 -> 6.51, 1.84 -> 1.80, 4.92 -> 4.70).
# A cage per corner, pushed out as far as the heavy surface lay near it, cleaned the pump as well but
# took mech to 13.11% whatever its cap (2026-10-29).
REACH = float(PARAMS.get("reach", 0.005))
# Baked this many times bigger, then shrunk: new UVs spend the texture less thriftily than the
# generator's own, and fine engraving came out noisy at the final size.
SUPER = int(PARAMS.get("supersample", 1))
# The normal map is baked this many times bigger, then shrunk: each texel meets the heavy surface at one point,
# so a thin groove's edge came out in steps of texels (mech, knight). At 2 most steps go; 4 is a little cleaner still,
# but the bake holds about 190 bytes a texel: 15-16 GB, with the other maps at the final size or not. So it is baked
# in four parts: the pistol's peak 3.3 -> 1.3 GB, the watch's 4.7 -> 3.8 (the rest is the model), for 1-7 s, with no
# line at the joins and the same look and light. Look and light stay level (2026-11-04). More samples give the
# normal map nothing: rays pick each texel's point once, and at 1 the pass takes half as long (mech 13.5 -> 6.7 s)
# with no more noise and the same to the eye.
NORMAL_SUPER = int(PARAMS.get("normalSuper", 2))
NORMAL_SAMPLES = 1
BAKE = SIZE * SUPER
# Islands lie GAP texels apart, so one island's edge doesn't take its neighbour's colour, and the bake paints
# MARGIN texels past their edges, so mip-maps don't bleed the background in. The gap is per island and
# thousands of islands pay it: on the pump at 10k, 1 texel left 59% of the texture to the model, 2 left
# 54%, 4 left 49% (none: 63%). smart_project's own margin (32 px a side at 2048) left it 1-16%.
GAP = max(1, BAKE // 2048)
MARGIN = max(2, BAKE // 256)

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

# Morphing models are baked as they stand at rest, shape keys off. Rigged ones come here without their skin (tools_ops._without_skin).
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
# Edges sharper than SHARP degrees stay sharp, and no texture island crosses one: the mesh is split apart there
# before the unwrap, as artists split UVs at hard edges. Crossed by an island, the normal map has to jump along a
# slanted line, which it draws in steps of texels: the white dashes on the snowman and the dragon (2026-11-04).
# Marked as seams instead, the packer ignores them. The computer's panels stay crisp: at 200k it shaded 1.94 ->
# 1.78% off and creases 1.06 -> 0.58% with sharp edges, against smooth ones.
# 60, not 45: split at 45, shallow folds came out as white slashes and wedges, on the skeleton's skull, the
# computer's screen and the snowman's scarf; at 60 they go and hard panels stay hard. Look on 16 models: truck 5.23 ->
# 4.75, statue 3.92 -> 3.71, computer 4.11 -> 3.99, pistol 1.08 -> 1.13, crown 26.36 -> 26.53, the rest within 0.04 (2026-11-05).
SHARP = float(PARAMS.get("sharp", 60))
if SHARP:
    bpy.ops.mesh.select_mode(type="EDGE")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.mesh.edges_select_sharp(sharpness=math.radians(SHARP))
    bpy.ops.mesh.mark_sharp()
    bpy.ops.mesh.edge_split(type="EDGE")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.0, area_weight=0.0, correct_aspect=True, scale_to_bounds=False)


def overlapping():
    """Select the faces whose UVs lie over others' (the selection shared with the mesh), and count them.
    Slivers of next to no area are left out: projected on their own they came out as needles that took
    room on the texture from everything else."""
    bpy.context.scene.tool_settings.use_uv_select_sync = True
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.uv.select_overlap()
    count = 0
    for o in low:
        mesh = bmesh.from_edit_mesh(o.data)
        for f in mesh.faces:
            if f.select and f.calc_area() < 1e-6 * extent**2:
                f.select_set(False)
            count += f.select
        bmesh.update_edit_mesh(o.data)
    return count


# Projected flat, a fold of the light surface lands on itself: where the cut joined the pump's thin spout
# to the wall behind it at 10k, spout and wall shared texels and the wall, baked last, drew dark streaks
# down the spout. Faces lying over others are projected again on their own, once, at a narrower angle: a
# second round met only slivers of no area, which came out as needles across the whole texture.
overlapped = [overlapping()]
if overlapped[0]:
    bpy.ops.uv.smart_project(angle_limit=math.radians(45), island_margin=0.0, area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
# The packer moves selected UVs only, and smart_project leaves none selected: until 2026-10-29 it moved
# nothing and the islands touched.
bpy.context.scene.tool_settings.use_uv_select_sync = False
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.select_all(action="SELECT")
# smart_project spreads what it projects over the whole square: projected again on their own, the pump's
# 104 overlapping faces (1.4% of its surface) came out as big as all the rest and took 43% of the texels.
bpy.ops.uv.average_islands_scale()
# Quarter turns only: turned any way, lettering ran across the texel grid (the pump 2.48% noticeable, 1.61 so).
bpy.ops.uv.pack_islands(rotate=True, rotate_method="CARDINAL", scale=True, margin_method="FRACTION", margin=GAP / BAKE, shape_method="CONCAVE")
overlapped.append(overlapping())
bpy.ops.object.mode_set(mode="OBJECT")
# Each corner's normal leans towards its bigger faces, so long thin triangles don't bend the shading of the big ones
# beside them, which the normal map then has to undo. Light and look level or closer on nearly all (statue look 4.14 ->
# 3.92, pistol 1.09 -> 1.08), files up to 1.5% lighter, no extra time (2026-11-05). A mesh with shape keys can't apply
# a modifier, so it keeps the plain smooth normals.
for o in low:
    if not o.data.shape_keys:
        bpy.context.view_layer.objects.active = o
        weighted = o.modifiers.new("weighted", "WEIGHTED_NORMAL")
        weighted.keep_sharp = True
        weighted.mode = "FACE_AREA"
        weighted.weight = 50
        bpy.ops.object.modifier_apply(modifier=weighted.name)


def image(name, colour, size=None):
    img = bpy.data.images.new(name, size or BAKE, size or BAKE, alpha=False, float_buffer=False)
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


def run(kind, img, margin=None, **extra):
    slot.image = img
    margin = MARGIN * img.size[0] // BAKE if margin is None else margin
    bpy.ops.object.select_all(action="DESELECT")
    for o in high:
        o.select_set(True)
    for i, o in enumerate(low):
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.bake(type=kind, use_clear=(i == 0), margin=margin, **extra)
        o.select_set(False)


def run_in_parts(kind, img, **extra):
    """Into img, a quarter at a time: each part has room around it for the margin, cut off when put together."""
    whole = img.size[0]
    part = whole // 2
    pad = MARGIN * whole // BAKE
    side = part + 2 * pad
    piece = image("normal_part", False, side)
    uvs = []
    for o in low:
        uv = np.empty(len(o.data.loops) * 2, dtype=np.float64)
        o.data.uv_layers.active.data.foreach_get("uv", uv)
        uvs.append(uv)
    done = np.empty((whole, whole, 4), dtype=np.float32)
    got = np.empty((side, side, 4), dtype=np.float32)
    for y in range(2):
        for x in range(2):
            for o, uv in zip(low, uvs):
                moved = uv.copy()
                moved[0::2] = (uv[0::2] * whole - x * part + pad) / side
                moved[1::2] = (uv[1::2] * whole - y * part + pad) / side
                o.data.uv_layers.active.data.foreach_set("uv", moved)
                o.data.update()
            run(kind, piece, margin=pad, **extra)
            piece.pixels.foreach_get(got.ravel())
            done[y * part:(y + 1) * part, x * part:(x + 1) * part] = got[pad:pad + part, pad:pad + part]
    for o, uv in zip(low, uvs):
        o.data.uv_layers.active.data.foreach_set("uv", uv)
        o.data.update()
    img.pixels.foreach_set(done.ravel())
    bpy.data.images.remove(piece)


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


def glows():
    """Whether the heavy model gives off light of its own: Rodin's models carry all their colour that way
    (black base colour, the picture in the emissive texture), and baked without it the pump came out black."""
    for o in high:
        for material in o.data.materials:
            p = principled(material)
            if p and p.inputs["Emission Strength"].default_value > 0 and (
                    p.inputs["Emission Color"].links or any(p.inputs["Emission Color"].default_value[:3])):
                return True
    return False


timings = {}
maps = {}


def set_reach(reach):
    bake.cage_extrusion = reach * extent
    bake.max_ray_distance = 2 * reach * extent


def rgba(img):
    a = np.empty(img.size[0] * img.size[1] * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(img.size[1], img.size[0], 4)


def covered(size):
    """Texels whose centre lies on the light model's new UVs (rows from the bottom, as Blender keeps pixels), one
    texel in from the islands' edges."""
    cov = np.zeros((size, size), dtype=bool)
    for o in low:
        uv = np.empty(len(o.data.loops) * 2, dtype=np.float64)
        o.data.uv_layers.active.data.foreach_get("uv", uv)
        for tri in uv.reshape(-1, 3, 2) * size - 0.5:
            x0, y0 = np.floor(tri.min(0)).astype(int).clip(0, size - 1)
            x1, y1 = np.ceil(tri.max(0)).astype(int).clip(0, size - 1)
            ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
            e = [(tri[(i + 1) % 3, 0] - tri[i, 0]) * (ys - tri[i, 1]) - (tri[(i + 1) % 3, 1] - tri[i, 1]) * (xs - tri[i, 0]) for i in range(3)]
            inside = ((e[0] >= 0) & (e[1] >= 0) & (e[2] >= 0)) | ((e[0] <= 0) & (e[1] <= 0) & (e[2] <= 0))
            cov[ys[inside], xs[inside]] = True
    inner = cov.copy()
    inner[1:] &= cov[:-1]; inner[:-1] &= cov[1:]; inner[:, 1:] &= cov[:, :-1]; inner[:, :-1] &= cov[:, 1:]
    return inner


# Where a ray met nothing within REACH, the texel stays empty in every map: black in base colour (unseen on a black
# hat), but roughness 0 and metalness 0 in the other map, so a viewer drew glossy plastic: a grey patch mirroring the
# room on the dog's matt black hat at 5k, 1134 texels, where the cut left the surface a little past the reach
# (2026-11-10). A missed texel reads exactly flat in the normal map (0.5, 0.5, 1: harmless there) and 0 in roughness:
# both together mark the misses (a met surface that flat and that glossy is rare, and baked again it reads the same),
# and every map is baked again with rays LONG_REACH times as long, taken only for those texels. Longer rays everywhere
# drew a hose onto the pump's wall (see REACH); on texels that would be empty they can only help. Blue under 0.25 is
# not a miss: those are folds whose light face turned over (32k texels on the dog), and the TILT cap below takes them.
# A model baked for its normal map alone keeps its misses: flat there, they change nothing.
LONG_REACH = float(PARAMS.get("longReach", 3))
missed = None
# Only the faces over a missed texel are baked again: Cycles works texel by texel of the image each face bakes into, so
# the others are put aside onto an image of one texel. Their shape stays, so normals and tangents stay too, and the
# missed texels come out the same as from the whole bake, all but one texel on the truck and one on the mech at 10k
# (a shade off, the same run after run: 5 of 7 trials byte for byte). The whole image again took 11 of the dog's 39 s
# with 2 texels missed; on the whole auto budget it saves 5-8 s a bake with misses, the low rungs (2026-11-10).
aside = bpy.data.materials.new("aside")
aside.use_nodes = True
aside.node_tree.nodes.active = aside_slot = aside.node_tree.nodes.new("ShaderNodeTexImage")
aside_slot.image = image("aside", False, 1)


def set_aside():
    """Faces whose UV box holds no missed texel bake into the one-texel image (the box holds every texel covered()
    gives the face)."""
    table = np.zeros((BAKE + 1, BAKE + 1), dtype=np.int64)
    table[1:, 1:] = missed.cumsum(0).cumsum(1)
    for o in low:
        uv = np.empty(len(o.data.loops) * 2, dtype=np.float64)
        o.data.uv_layers.active.data.foreach_get("uv", uv)
        tri = uv.reshape(-1, 3, 2) * BAKE - 0.5
        x0, y0 = np.floor(tri.min(1)).astype(int).clip(0, BAKE - 1).T
        x1, y1 = np.ceil(tri.max(1)).astype(int).clip(0, BAKE - 1).T
        held = table[y1 + 1, x1 + 1] - table[y0, x1 + 1] - table[y1 + 1, x0] + table[y0, x0]
        o.data.materials.append(aside)
        o.data.polygons.foreach_set("material_index", (held == 0).astype(np.int32))
        o.data.update()


def back_from_aside():
    for o in low:
        o.data.polygons.foreach_set("material_index", np.zeros(len(o.data.polygons), dtype=np.int32))
        o.data.materials.pop(index=len(o.data.materials) - 1)
        o.data.update()


def again_longer(name, img, bake_it):
    """Bake img once more with longer rays and take that for the texels the first rays missed."""
    if missed is None or not missed.any():
        return
    side = img.size[0]
    where = np.repeat(np.repeat(missed, side // missed.shape[0], axis=0), side // missed.shape[0], axis=1)
    longer = image(name + "_longer", img.colorspace_settings.name == "sRGB", side)
    set_reach(LONG_REACH * REACH)
    set_aside()
    try:
        bake_it(longer)
    finally:
        set_reach(REACH)
        back_from_aside()
    a, b = rgba(img), rgba(longer)
    a[where] = b[where]
    img.pixels.foreach_set(a.ravel())
    bpy.data.images.remove(longer)


t = time.time()
maps["normal"] = image("normal", False, BAKE * NORMAL_SUPER)
scene.cycles.samples = NORMAL_SAMPLES
bake_normal = lambda img: (run_in_parts if NORMAL_SUPER > 1 else run)("NORMAL", img, normal_space="TANGENT")
bake_normal(maps["normal"])
scene.cycles.samples = SAMPLES
timings["normal"] = round(time.time() - t, 1)
missed_first = missed_left = 0


def misses():
    """Texels (at the base size) flat in the normal map and 0 in roughness."""
    n = rgba(maps["normal"])[..., :3]
    s = n.shape[0] // BAKE
    # Any of the finer normal texels flat: with all of them, the rim of the dog's patch stayed a ring of glossy dots.
    flat = (np.abs(n - (0.5, 0.5, 1.0)) < 0.6 / 255).all(-1).reshape(BAKE, s, BAKE, s).any(axis=(1, 3))
    return covered(BAKE) & flat & (rgba(maps["roughness"])[..., 1] < 0.6 / 255)


if not NORMAL_ONLY:
    t = time.time()
    maps["roughness"] = image("roughness", False)
    run("ROUGHNESS", maps["roughness"])
    missed = misses()
    missed_first = int(missed.sum())
    again_longer("roughness", maps["roughness"], lambda img: run("ROUGHNESS", img))
    timings["roughness"] = round(time.time() - t, 1)
    t = time.time()
    scene.cycles.samples = NORMAL_SAMPLES
    again_longer("normal", maps["normal"], bake_normal)
    scene.cycles.samples = SAMPLES
    missed_left = int((missed & misses()).sum())
    timings["normalLonger"] = round(time.time() - t, 1)

# Its own glow before shine() below rewires the emission to bake the other maps.
if not NORMAL_ONLY and glows():
    t = time.time()
    maps["emissive"] = image("emissive", True)
    run("EMIT", maps["emissive"])
    again_longer("emissive", maps["emissive"], lambda img: run("EMIT", img))
    timings["emissive"] = round(time.time() - t, 1)

# Base colour and metalness are baked as light the heavy model gives off: Cycles' diffuse colour pass
# is base colour x (1 - metalness), which turned metal parts black.
for name, socket_name, colour in [] if NORMAL_ONLY else [("baseColor", "Base Color", True), ("metallic", "Metallic", False)]:
    t = time.time()
    shine(socket_name)
    maps[name] = image(name, colour)
    run("EMIT", maps[name])
    again_longer(name, maps[name], lambda img: run("EMIT", img))
    timings[name] = round(time.time() - t, 1)

# The normal map tilts the light model's surface at most TILT degrees. Steeper texels are rays that met the
# side walls of a groove or a step the cut flattened: they drew white streaks and black rims along the Rodin
# computer's vents and screen bars and ragged spots on its screws, which went at 30 (light 1.78 -> 1.58%,
# creases 0.58 -> 0.28%; 45 and 60 left the black rims). The bench stayed level, the dog's wrinkles too
# (1.17%), the crown came closer (4.00 -> 3.83%); drill and watch moved 0.07 the other way (2026-10-29).
# Round parts a very light cut leaves to the map lose little: at 2k the magnum's cylinder shaded 1.68 -> 1.77%
# off, the same to the eye, and camera and watch came closer. Capping only strips up to 2 or 4 texels wide
# left most of the computer's streaks (light 1.76, 1.71%): they are broader than that.
TILT = float(PARAMS.get("tilt", 30))
steep = np.zeros(0, dtype=bool)
if TILT:
    img = maps["normal"]
    a = np.empty(img.size[0] * img.size[1] * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    a = a.reshape(-1, 4)
    v = a[:, :3] * 2 - 1
    lim = math.cos(math.radians(TILT))
    steep = v[:, 2] < lim
    xy = v[steep, :2]
    v[steep, :2] = xy * (math.sqrt(1 - lim * lim) / np.linalg.norm(xy, axis=1, keepdims=True).clip(1e-6))
    v[steep, 2] = lim
    a[:, :3] = (v + 1) / 2
    img.pixels.foreach_set(a.ravel())

# glTF keeps roughness in G and metalness in B of one texture.
for img in maps.values():
    if img.size[0] != SIZE:
        img.scale(SIZE, SIZE)


def pixels(img):
    a = np.empty(SIZE * SIZE * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(-1, 4)


if not NORMAL_ONLY:
    packed = np.zeros((SIZE * SIZE, 4), dtype=np.float32)
    packed[:, 1] = pixels(maps["roughness"])[:, 0]
    packed[:, 2] = pixels(maps["metallic"])[:, 0]
    packed[:, 3] = 1.0
    maps["metallicRoughness"] = bpy.data.images.new("metallicRoughness", SIZE, SIZE, alpha=False, float_buffer=False)
    maps["metallicRoughness"].colorspace_settings.name = "Non-Color"
    maps["metallicRoughness"].pixels.foreach_set(packed.ravel())

# Out go the baked maps and, for every light mesh, each triangle corner as Blender holds it: position,
# normal (the smooth ones the normal map was baked against) and new UV. tools_node/graft.mjs puts them
# into the light model itself; exporting from Blender instead redid rigs: CesiumMan stood 57% off.
for name in ("normal",) if NORMAL_ONLY else ("baseColor", "metallicRoughness", "normal", *(("emissive",) if "emissive" in maps else ())):
    img = maps[name]
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
print(json.dumps({"bake": {"size": SIZE, "normalOnly": NORMAL_ONLY, "supersample": SUPER, "samples": SAMPLES, "reachPct": REACH * 100, "overlappedFaces": overlapped, "missedTexels": [missed_first, missed_left], "steepPct": round(100 * float(steep.mean()), 3) if steep.size else 0.0, "seconds": round(time.time() - t0, 1), "passes": timings}}))
