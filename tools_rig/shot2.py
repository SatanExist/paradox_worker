"""Blender: a model's colour picture, front and three-quarter, 384 px. blender -b -P shot2.py -- in.glb out_prefix"""
import math, sys, bpy
from mathutils import Vector
src, out = sys.argv[sys.argv.index("--") + 1:][:2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"; sc.display.shading.light = "STUDIO"; sc.display.shading.color_type = "TEXTURE"
sc.render.resolution_x = sc.render.resolution_y = 384
sc.world = bpy.data.worlds.new("w"); sc.world.color = (0.5, 0.5, 0.5)
ms = [o for o in sc.objects if o.type == "MESH"]
pts = [o.matrix_world @ Vector(c) for o in ms for c in o.bound_box]
lo = Vector([min(q[i] for q in pts) for i in range(3)]); hi = Vector([max(q[i] for q in pts) for i in range(3)])
C, R = (lo + hi) / 2, (hi - lo).length
cd = bpy.data.cameras.new("c"); cd.type = "ORTHO"; cd.ortho_scale = R * 0.85; cd.clip_end = R * 10
cam = bpy.data.objects.new("c", cd); sc.collection.objects.link(cam); sc.camera = cam
for tag, a in (("front", 0.0), ("q", 40.0)):
    d = Vector((math.sin(math.radians(a)), -math.cos(math.radians(a)), 0.15)).normalized()
    cam.location = C + d * R * 3
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = f"{out}_{tag}.png"
    bpy.ops.render.render(write_still=True)
