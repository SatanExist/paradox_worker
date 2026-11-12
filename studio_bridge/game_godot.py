"""Godot package for game_prep (godot: true, with lods: true): the LOD levels ready to drop into a Godot 4 project.

Godot imports lods.glb's levels (model_LOD0, model_LOD1, ...) as plain nodes and draws them all at once, one over
the other. The package adds a scene whose root script gives each level a visibility range, from the switch sizes in
the report (after.lod.levels[k].maxScreenPx), so each level is drawn only while the model is that small on screen.

godot.zip holds one folder, polylab_model/: model.glb (lods.glb as is), model.tscn (the scene to use),
lod_switch.gd, README.txt. The scene points at its files by relative paths, so the folder can be renamed or put
anywhere in the project. Checked on Godot 4.7.2 (2026-11-11): the drill, LOD0 white / LOD1 green / LOD2 blue at
the right sizes. Same report in -> same zip out (fixed dates and order).

With collision pieces the scene gets them as a StaticBody3D; with moving: true too, the root is a RigidBody3D instead
(moving_body.gd): the prop falls and can be pushed, its centre of mass set from the pieces' volumes, its size set by
Size (Godot Physics resets a moving body's own scale). Checked on Godot 4.7 (2026-11-12), Godot Physics and Jolt:
drill, mech and skeleton at Size 1 and 2 fall on their side, rest, move when pushed, the LOD distances follow Size.
"""
from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

FOLDER = "polylab_model"

LOD_SWITCH_GD = '''@tool
extends Node3D
## PolyLab LOD switch. The model holds its levels as nodes named <name>_LOD0, <name>_LOD1, ...
## Each level is drawn only at the distances it was made for: LOD k (k >= 1) while the model is no more than
## lod_screen_px[k - 1] pixels across on screen (its diagonal, on a screen screen_height pixels tall, seen
## through a camera with a vertical field of view of camera_fov degrees). Godot's visibility ranges do the switching.

## Switch sizes from PolyLab (after.lod.levels[k].maxScreenPx in the report), for LOD1, LOD2, ...
@export var lod_screen_px: PackedFloat32Array = PackedFloat32Array():
	set(v):
		lod_screen_px = v
		apply()
## Vertical field of view of your camera, degrees (Godot's Camera3D default is 75).
@export_range(1.0, 179.0) var camera_fov := 75.0:
	set(v):
		camera_fov = v
		apply()
## Screen height in pixels the sizes are for; 0 = the project's viewport height.
@export var screen_height := 0:
	set(v):
		screen_height = v
		apply()
## A level hands over this share of its distance later than it took over, so it doesn't flicker on the edge.
@export_range(0.0, 0.3) var margin := 0.05:
	set(v):
		margin = v
		apply()

const PX_FRAME := 1.05  # PolyLab measures a level in a frame 5 % wider than the model's diagonal

var _scale := Vector3.ONE


func _ready() -> void:
	set_notify_transform(true)
	apply()


func _notification(what: int) -> void:
	# Scaled up, the model is as big on screen from farther off: the distances follow.
	if what == NOTIFICATION_TRANSFORM_CHANGED and not global_transform.basis.get_scale().is_equal_approx(_scale):
		apply()


## The level nodes, LOD0 first.
func levels() -> Array:
	var found := {}
	_find(self, found)
	var out := []
	for k in range(found.size()):
		if not found.has(k):
			break
		out.append(found[k])
	return out


func _find(n: Node, found: Dictionary) -> void:
	var name := String(n.name)
	var at := name.rfind("_LOD")
	if at >= 0 and name.substr(at + 4).is_valid_int():
		found[int(name.substr(at + 4))] = n
		return
	for c in n.get_children():
		_find(c, found)


func _meshes(n: Node, out: Array) -> void:
	if n is GeometryInstance3D:
		out.append(n)
	for c in n.get_children():
		_meshes(c, out)


## Distance from the camera at which a model with this diagonal is `px` PolyLab pixels across.
func distance_for(px: float, diagonal: float) -> float:
	var h := float(screen_height if screen_height > 0 else ProjectSettings.get_setting("display/window/size/viewport_height", 1080))
	return diagonal * h / (2.0 * tan(deg_to_rad(camera_fov) / 2.0) * (px / PX_FRAME))


## The diagonal of LOD0's box in world units (this node's scale counts, its turn doesn't).
func diagonal() -> float:
	var lv := levels()
	if lv.is_empty() or not is_inside_tree():
		return 0.0
	var box := AABB()
	var first := true
	var meshes := []
	_meshes(lv[0], meshes)
	var to_self := global_transform.affine_inverse()
	for m in meshes:
		var b: AABB = (to_self * m.global_transform) * m.get_aabb()
		box = b if first else box.merge(b)
		first = false
	return (box.size * global_transform.basis.get_scale()).length()


## Sets each level's visibility range; call it again after changing the levels by hand.
func apply() -> void:
	if not is_inside_tree():
		return
	_scale = global_transform.basis.get_scale()
	var lv := levels()
	var d := diagonal()
	if lv.size() < 2 or d <= 0.0:
		return
	for k in range(lv.size()):
		var begin := 0.0 if k == 0 or k - 1 >= lod_screen_px.size() else distance_for(lod_screen_px[k - 1], d)
		var end := 0.0 if k + 1 >= lv.size() or k >= lod_screen_px.size() else distance_for(lod_screen_px[k], d)
		var meshes := []
		_meshes(lv[k], meshes)
		for m in meshes:
			m.visibility_range_begin = begin
			m.visibility_range_begin_margin = begin * margin
			m.visibility_range_end = end
			m.visibility_range_end_margin = end * margin
			m.visibility_range_fade_mode = GeometryInstance3D.VISIBILITY_RANGE_FADE_DISABLED
'''

MOVING_BODY_GD = """@tool
extends RigidBody3D
## PolyLab moving prop: falls, rolls and can be pushed. Godot Physics sets a moving body's own Scale back to 1 when
## the game runs, so its size is set here: Size scales the model and the collision pieces inside the body, and the
## centre of mass with them. Leave this node's Scale at 1. Mass stays what you set.

## How big the prop is, 1 = as PolyLab made it.
@export_range(0.01, 100.0, 0.01, "or_greater") var size := 1.0:
	set(v):
		size = v
		apply()
## Where each piece sits at size 1 (piece_00, piece_01, ...), and the centre of mass at size 1: Size works from these.
@export var piece_centres := PackedVector3Array()
@export var mass_centre := Vector3.ZERO


func _ready() -> void:
	apply()


func apply() -> void:
	if not is_inside_tree():
		return
	for c in get_children():
		if c is CollisionShape3D and String(c.name).begins_with("piece_"):
			var k := int(String(c.name).substr(6))
			if k < piece_centres.size():
				c.position = piece_centres[k] * size
				c.scale = Vector3.ONE * size
		elif String(c.name) == "levels":
			c.scale = Vector3.ONE * size
	center_of_mass = mass_centre * size
"""

SCENE_TSCN = """[gd_scene load_steps={steps} format=3]

[ext_resource type="Script" path="lod_switch.gd" id="1_lod"]
[ext_resource type="PackedScene" path="model.glb" id="2_model"]
{more}{shapes}
[node name="model" type="{root}"]
{props}
[node name="levels" parent="." instance=ExtResource("2_model")]
{levels}{bodies}"""

LOD_PROPS = 'script = ExtResource("1_lod")\nlod_screen_px = PackedFloat32Array({px})\n'


def _scene(px: list[float], pieces: list | None, moving: bool = False) -> str:
    """model.tscn; with collision pieces, a StaticBody3D "collision" holding one convex shape per piece. moving: the
    root is a RigidBody3D instead (moving_body.gd, with Size), the pieces right under it and the LOD switch on
    "levels", so the model falls and can be pushed."""
    pieces = pieces or []
    moving = moving and bool(pieces)
    # A moving body needs its centre of mass. Godot Physics takes each shape's node origin for the shape's centre, so
    # with every piece placed at the model's origin a skeleton dropped on its side stood back up (2026-11-12): each
    # piece sits at its own centre, and the body's centre is set from the pieces' volumes. Jolt got it right either way.
    at = [_centre(v, f) for v, f in pieces] if moving else [(np.zeros(3), 0.0)] * len(pieces)
    shapes = "".join(f'\n[sub_resource type="ConvexPolygonShape3D" id="piece_{i:02d}"]\npoints = PackedVector3Array('
                     + ", ".join(f"{c:.6g}" for c in (v - at[i][0]).reshape(-1)) + ")\n" for i, (v, _) in enumerate(pieces))
    parent = "." if moving else "collision"
    bodies = (("" if moving else "\n[node name=\"collision\" type=\"StaticBody3D\" parent=\".\"]\n") + "".join(
        f'\n[node name="piece_{i:02d}" type="CollisionShape3D" parent="{parent}"]\n'
        + (f"transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {_vec(at[i][0])})\n" if moving else "")
        + f'shape = SubResource("piece_{i:02d}")\n'
        for i in range(len(pieces)))) if pieces else ""
    lod = LOD_PROPS.format(px=", ".join(f"{p:g}" for p in px))
    if not moving:
        return SCENE_TSCN.format(steps=3 + len(pieces), more="", shapes=shapes, root="Node3D", props=lod, levels="",
                                 bodies=bodies)
    volume = sum(w for _, w in at)
    centre = sum(c * w for c, w in at) / volume if volume > 0 else np.mean([c for c, _ in at], axis=0)
    props = ('script = ExtResource("3_body")\ncenter_of_mass_mode = 1\n'
             f"center_of_mass = Vector3({_vec(centre)})\n"
             "piece_centres = PackedVector3Array(" + ", ".join(_vec(c) for c, _ in at) + ")\n"
             f"mass_centre = Vector3({_vec(centre)})\n")
    return SCENE_TSCN.format(steps=4 + len(pieces), more='[ext_resource type="Script" path="moving_body.gd" id="3_body"]\n',
                             shapes=shapes, root="RigidBody3D", props=props, levels=lod, bodies=bodies)


def _vec(c) -> str:
    return ", ".join(f"{x:.6g}" for x in c)


def _centre(v, f) -> tuple:
    """A convex piece's centre of mass and volume (even density)."""
    import trimesh

    hull = trimesh.Trimesh(np.asarray(v, float), np.asarray(f), process=False).convex_hull
    return np.asarray(hull.center_mass, float), float(hull.volume)

README = '''PolyLab model for Godot 4, with {count} levels of detail ({chain} triangles).

Inside:
  model.tscn     the scene to use: drag it into your scene, or instance it from code
  model.glb      all the levels in one file (nodes model_LOD0, model_LOD1, ...)
  lod_switch.gd  switches the levels by distance (Godot's visibility ranges)
{more}
How to use:
  1. Unzip into your Godot project (the polylab_model folder can be renamed or moved; keep the files' names).
  2. Use model.tscn. The levels switch by themselves, in the game and in the editor:
{switch}
  3. If your camera's field of view isn't Godot's default 75 degrees, set Camera Fov on the {fov_node}.
     Screen Height 0 means your project's viewport height.
{collision}
{scaling} Checked on Godot 4.7.
'''

README_COLLISION = '''  4. Collision: the "collision" node is a StaticBody3D with {count} convex pieces that hug the model, so
     players and objects bump into it; it stays in place. For a prop that falls or can be pushed, put the
     "levels" node and the pieces under one RigidBody3D instead.
'''

README_MOVING = '''  4. Physics: the scene's root is a RigidBody3D with {count} convex pieces that hug the model, so it falls,
     rolls and can be pushed. Its weight is Godot's default 1 kg: set Mass on the root to what the prop weighs.
     The centre of mass is worked out from the pieces.
'''
SCALING = "Scaling the scene is fine: the switch distances follow its size."
SCALING_MOVING = ("To make the prop bigger or smaller, set Size on the root and leave its Scale at 1 (Godot Physics sets a\n"
                  "moving body's Scale back to 1 when the game runs); the switch distances follow the size.")


def _entry(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(f"{FOLDER}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
    info.external_attr = 0o644 << 16
    return info


def add_godot(report: dict[str, Any], lods_asked: bool = True, pieces: list | None = None, moving: bool = False) -> None:
    """Adds extraFiles["godot.zip"] and after.godot when the job made LOD levels; otherwise a step says why not.
    pieces: the collision pieces (game_collision), already where the model is. moving: a prop that falls and can be
    pushed (the root a RigidBody3D); it needs the pieces. Never fails the job."""
    after, steps = report["after"], report["steps"]
    lods = (report.get("extraFiles") or {}).get("lods.glb")
    levels = (after.get("lod") or {}).get("levels") or []
    if not lods or len(levels) < 2:
        steps.append("no Godot package: it switches LOD levels, and " +
                     ("this job made none (see the LOD step)" if lods_asked else "they come with lods: true"))
        return
    px = [float(level["maxScreenPx"]) for level in levels[1:]]
    chain = " -> ".join(str(level["triangles"]) for level in levels)
    switch = "\n".join(f"       LOD{level['level']} when the model is under {level['maxScreenPx']} px across"
                       for level in levels[1:])
    fd, name = tempfile.mkstemp(suffix=".zip")
    os.close(fd)  # written by name; an open handle would lock it on Windows
    packed = Path(name)
    try:
        with zipfile.ZipFile(packed, "w") as z:
            body = moving and bool(pieces)
            collision = (README_MOVING if body else README_COLLISION).format(count=len(pieces)) if pieces else ""
            readme = README.format(count=len(levels), chain=chain, switch=switch, collision=collision,
                                   more="  moving_body.gd the moving body, with Size\n" if body else "",
                                   fov_node='"levels" node' if body else "scene's root node",
                                   scaling=SCALING_MOVING if body else SCALING)
            z.writestr(_entry("README.txt"), readme, zipfile.ZIP_DEFLATED)
            z.writestr(_entry("lod_switch.gd"), LOD_SWITCH_GD, zipfile.ZIP_DEFLATED)
            if body:
                z.writestr(_entry("moving_body.gd"), MOVING_BODY_GD, zipfile.ZIP_DEFLATED)
            z.writestr(_entry("model.glb"), Path(lods).read_bytes(), zipfile.ZIP_STORED)  # textures inside are already packed
            z.writestr(_entry("model.tscn"), _scene(px, pieces, moving), zipfile.ZIP_DEFLATED)
    except Exception as exc:  # a full disk or the like: the job's other files are still good
        packed.unlink(missing_ok=True)
        steps.append(f"no Godot package: {str(exc)[:160]}")
        return
    report["extraFiles"]["godot.zip"] = str(packed)
    after["godot"] = {"file": "godot.zip", "scene": f"{FOLDER}/model.tscn", "switchPx": px,
                      "collisionPieces": len(pieces or []), "fileMb": round(packed.stat().st_size / 1048576, 2)}
    if moving and pieces:
        after["godot"]["body"] = "RigidBody3D"
    steps.append(f"Godot package godot.zip: {FOLDER}/model.tscn switches the {len(levels)} levels by itself"
                 + (f", with {len(pieces)} collision pieces" if pieces else "")
                 + (" (a RigidBody3D: it falls and can be pushed)" if moving and pieces else "")
                 + ("; not a moving body: that needs the collision pieces (collision: true)" if moving and not pieces else ""))
