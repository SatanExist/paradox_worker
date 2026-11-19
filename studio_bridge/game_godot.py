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

A rigged model (auto-rig): lods.glb already has every level on LOD0's one skeleton (lod.mjs). Godot then puts all
the levels' meshes under that skeleton, so each mesh carries its level in its name and lod_switch.gd reads it there
(a mesh's own name first, else its nearest parent's: plain models switch as before). With standard
human bone names model.glb.import maps it to Godot's humanoid profile (Bone Map written inline, so the folder can
move), so ready-made humanoid animations play on it.
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
## PolyLab LOD switch. The model holds its levels as nodes named <name>_LOD0, <name>_LOD1, ... (or meshes so named)
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


## Each level's meshes, LOD0 first. A mesh belongs to the level in its own name (<name>_LOD<k>), else in its
## nearest parent's: a rigged model's levels all sit under LOD0's skeleton, each mesh named by its level.
func levels() -> Array:
	var found := {}
	_find(self, -1, found)
	var out := []
	for k in range(found.size()):
		if not found.has(k):
			break
		out.append(found[k])
	return out


func _find(n: Node, level: int, found: Dictionary) -> void:
	var name := String(n.name)
	var at := name.rfind("_LOD")
	if at >= 0 and name.substr(at + 4).is_valid_int():
		level = int(name.substr(at + 4))
	if n is GeometryInstance3D and level >= 0:
		if not found.has(level):
			found[level] = []
		found[level].append(n)
	for c in n.get_children():
		_find(c, level, found)


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
	var to_self := global_transform.affine_inverse()
	for m in lv[0]:
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
		for m in lv[k]:
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

PARALLAX_GD = '''@tool
extends Node
## PolyLab height map: parallax on LOD0, so grooves, vents and seams the light model has no triangles for look deep
## up close. The height map (white: the model's surface, black: the deepest groove) was baked from the original, and
## Depth Scale is that depth as Godot's height scale wants it. Far levels are too small on screen for it to show.

@export var height_map: Texture2D:
	set(v):
		height_map = v
		apply()
## Godot's Height Scale for this model: its deepest groove, measured by PolyLab. Larger exaggerates, 0 is flat.
@export var depth_scale := 1.0:
	set(v):
		depth_scale = v
		apply()
@export var enabled := true:
	set(v):
		enabled = v
		apply()


func _ready() -> void:
	apply()


func apply() -> void:
	if not is_inside_tree():
		return
	for m in _lod0(get_parent(), false, []):
		for s in m.mesh.get_surface_count():
			var base := m.mesh.surface_get_material(s) as BaseMaterial3D
			if base == null:
				continue
			if not enabled or height_map == null:
				m.set_surface_override_material(s, null)
				continue
			var mat: BaseMaterial3D = base.duplicate()
			mat.heightmap_enabled = true
			mat.heightmap_texture = height_map
			mat.heightmap_scale = depth_scale
			mat.heightmap_deep_parallax = true
			m.set_surface_override_material(s, mat)


## LOD0's meshes: named <name>_LOD0 themselves or under a node so named (lod_switch.gd reads the levels the same way).
func _lod0(n: Node, inside: bool, out: Array) -> Array:
	var name := String(n.name)
	var at := name.rfind("_LOD")
	if at >= 0 and name.substr(at + 4).is_valid_int():
		inside = int(name.substr(at + 4)) == 0
	if inside and n is MeshInstance3D and n.mesh:
		out.append(n)
	for c in n.get_children():
		_lod0(c, inside, out)
	return out
'''

# Godot compresses a texture a 3D material uses (VRAM, 4x4 blocks): on a height map the steps would show as parallax
# terraces. Kept lossless, with mipmaps.
HEIGHT_IMPORT = ('[remap]\n\nimporter="texture"\ntype="CompressedTexture2D"\n\n[params]\n\n'
                 'compress/mode=0\ndetect_3d/compress_to=0\nmipmaps/generate=true\n')

PARALLAX_NODE = ('\n[node name="parallax" type="Node" parent="."]\nscript = ExtResource("4_par")\n'
                 'height_map = ExtResource("5_height")\ndepth_scale = {scale:g}\n')
PARALLAX_RES = ('[ext_resource type="Script" path="parallax.gd" id="4_par"]\n'
                '[ext_resource type="Texture2D" path="height.png" id="5_height"]\n')

IMPOSTOR_GDSHADER = '''// PolyLab impostor (octahedral): a quad that faces the camera and shows the model from the atlas pictures.
// Three nearest pictures are blended (a triangle of the grid), each one looked up where the view ray meets
// that picture's plane, then moved once along the ray by the picture's depth (parallax), as in Ryan Brucks'
// impostors. Pictures cover the upper half-sphere (hemi-octahedral map), glTF axes, Y up. It lights itself from
// the pictures' normals, occlusion, roughness and metalness, and writes the pictures' depth, so the sun's shadow map
// holds the model's shape: it shades itself and casts a real shadow (pixel depth offset, as in Brucks' impostors).
shader_type spatial;
render_mode world_vertex_coords, cull_disabled;

uniform sampler2D color_atlas : source_color, filter_linear_mipmap, repeat_disable;
uniform sampler2D normal_atlas : filter_linear_mipmap, repeat_disable;
uniform sampler2D orm_atlas : filter_linear_mipmap, repeat_disable;
uniform float frames = 12.0;
uniform float radius = 1.0;
uniform vec3 centre = vec3(0.0);
uniform bool parallax = true;
uniform bool occlusion = true;
// Light from the averaged normal (see light()); off = Godot's own light, for comparing.
uniform bool filtered = true;

// How much the normals under this pixel agree: 1 all the same, less the more they differ (length of their average).
varying float normal_len;

void vertex() {
	vec3 c = (MODEL_MATRIX * vec4(centre, 1.0)).xyz;
	bool ortho = PROJECTION_MATRIX[3][3] == 1.0;
	vec3 to = INV_VIEW_MATRIX[3].xyz - c;
	float d = length(to);
	vec3 f = ortho ? normalize(INV_VIEW_MATRIX[2].xyz) : to / d;
	vec3 ref = abs(f.y) < 0.999 ? vec3(0.0, 1.0, 0.0) : vec3(0.0, 0.0, -1.0);
	vec3 r = normalize(cross(ref, f));
	vec3 u = cross(f, r);
	float R = radius * length(MODEL_MATRIX[0].xyz);
	float q = ortho ? R : R * d / sqrt(max(d * d - R * R, 1e-8));  // the sphere's outline seen in perspective
	VERTEX = c + (r * (UV.x * 2.0 - 1.0) + u * (1.0 - UV.y * 2.0)) * q;
	NORMAL = f;
}

vec3 frame_dir(vec2 ij) {
	vec2 g = ij / (frames - 1.0) * 2.0 - 1.0;
	float x = (g.x - g.y) * 0.5;
	float z = (g.x + g.y) * 0.5;
	return normalize(vec3(x, 1.0 - abs(x) - abs(z), z));
}

// Pixel of picture ij hit by the ray o + t*rd (model space); plane at `lift` along the picture's direction.
vec2 lookup(vec2 ij, vec3 o, vec3 rd, float lift, out vec3 f, out vec3 hit) {
	f = frame_dir(ij);
	vec3 ref = abs(f.y) < 0.999 ? vec3(0.0, 1.0, 0.0) : vec3(0.0, 0.0, -1.0);
	vec3 r = normalize(cross(ref, f));
	vec3 u = cross(f, r);
	vec3 p0 = centre + f * lift;
	float t = dot(p0 - o, f) / dot(rd, f);
	hit = o + rd * t;
	vec3 h = hit - centre;
	vec2 st = clamp(vec2(dot(h, r), dot(h, u)) / (2.0 * radius) + 0.5, 0.0, 1.0);
	return (ij + vec2(st.x, 1.0 - st.y)) / frames;
}

void sample_frame(vec2 ij, vec3 o, vec3 rd, out vec4 col, out vec4 nd, out vec4 orm, out vec3 hit) {
	vec3 f;
	vec2 uv = lookup(ij, o, rd, 0.0, f, hit);
	if (parallax) {
		// depth 0 = the sphere's near side (lift R), 1 = its far side (lift -R)
		float dep = textureLod(normal_atlas, uv, 0.0).a;
		uv = lookup(ij, o, rd, radius - dep * 2.0 * radius, f, hit);
	}
	col = texture(color_atlas, uv);
	nd = texture(normal_atlas, uv);
	orm = texture(orm_atlas, uv);
}

void fragment() {
	mat4 inv = inverse(MODEL_MATRIX);
	bool ortho = PROJECTION_MATRIX[3][3] == 1.0;
	vec3 p = (inv * (INV_VIEW_MATRIX * vec4(VERTEX, 1.0))).xyz;
	vec3 rd = ortho ? normalize((inv * vec4(-INV_VIEW_MATRIX[2].xyz, 0.0)).xyz) : normalize(p - (inv * INV_VIEW_MATRIX[3]).xyz);
	vec3 o = p - rd * 4.0 * radius;  // a point on the ray before the model
	vec3 dir = -rd;
	if (!ortho) {
		dir = normalize((inv * INV_VIEW_MATRIX[3]).xyz - centre);
	}
	dir.y = max(dir.y, 0.0);
	dir = normalize(dir);
	float s = abs(dir.x) + abs(dir.y) + abs(dir.z);
	vec2 g = (vec2(dir.x + dir.z, dir.z - dir.x) / s * 0.5 + 0.5) * (frames - 1.0);
	vec2 cell = clamp(floor(g), vec2(0.0), vec2(frames - 2.0));
	vec2 fr = g - cell;
	vec2 a; vec2 b; vec2 c; vec3 w;
	if (fr.x + fr.y <= 1.0) {
		a = cell; b = cell + vec2(1.0, 0.0); c = cell + vec2(0.0, 1.0);
		w = vec3(1.0 - fr.x - fr.y, fr.x, fr.y);
	} else {
		a = cell + vec2(1.0, 1.0); b = cell + vec2(0.0, 1.0); c = cell + vec2(1.0, 0.0);
		w = vec3(fr.x + fr.y - 1.0, 1.0 - fr.x, 1.0 - fr.y);
	}
	vec4 ca; vec4 cb; vec4 cc; vec4 na; vec4 nb; vec4 nc; vec4 oa; vec4 ob; vec4 oc;
	vec3 ha; vec3 hb; vec3 hc;
	sample_frame(a, o, rd, ca, na, oa, ha);
	sample_frame(b, o, rd, cb, nb, ob, hb);
	sample_frame(c, o, rd, cc, nc, oc, hc);
	vec3 wa = w * vec3(ca.a, cb.a, cc.a);
	float cover = wa.x + wa.y + wa.z;
	// True depth of the surface under the pixel (the pictures' depth), as Brucks' impostors do with pixel depth
	// offset: the sun's shadow map then holds the model's shape, so it shades itself and casts a real shadow.
	vec3 hit = (ha * wa.x + hb * wa.y + hc * wa.z) / max(cover, 1e-4);
	vec3 hv = (VIEW_MATRIX * (MODEL_MATRIX * vec4(hit, 1.0))).xyz;
	vec4 clip = PROJECTION_MATRIX * vec4(hv, 1.0);
	DEPTH = clip.z / clip.w;
	LIGHT_VERTEX = hv;  // light and shadow are taken there, not on the flat card
	ALBEDO = (ca.rgb * wa.x + cb.rgb * wa.y + cc.rgb * wa.z) / max(cover, 1e-4);
	vec3 n = (na.rgb * 2.0 - 1.0) * wa.x + (nb.rgb * 2.0 - 1.0) * wa.y + (nc.rgb * 2.0 - 1.0) * wa.z;
	NORMAL = normalize((VIEW_MATRIX * (MODEL_MATRIX * vec4(normalize(n + vec3(0.0, 1e-5, 0.0)), 0.0))).xyz);
	vec3 m = (oa.rgb * wa.x + ob.rgb * wa.y + oc.rgb * wa.z) / max(cover, 1e-4);
	if (occlusion) {
		AO = m.r;
	}
	normal_len = filtered ? clamp(length(n) / max(cover, 1e-4), 1e-3, 1.0) : 1.0;
	// Toksvig: normals that differ under one pixel spread a highlight like a rougher surface would (Real-Time
	// Rendering, 4th ed., 9.13.1: GGX alpha^2 + (1 - |n|) / |n|).
	float alpha = m.g * m.g;
	ROUGHNESS = sqrt(sqrt(alpha * alpha + (1.0 - normal_len) / normal_len));
	METALLIC = m.b;
	ALPHA = w.x * ca.a + w.y * cb.a + w.z * cc.a;
	ALPHA_SCISSOR_THRESHOLD = 0.5;
}

// Average of max(0, n.L) over normals spread as a von Mises-Fisher lobe of sharpness kappa around the unit normal,
// t = n.L: Stephen Hill's fit of the clamped cosine convolved with a spherical Gaussian (M. Pettineo, "SG Series
// Part 3: Diffuse Lighting From an SG Light Source", 2016), within 0.01 of the exact average. Sharp lobes give
// max(0, t); spread ones keep some light past the edge, where some of the small parts under the pixel still face it.
float lobe_diffuse(float t, float kappa) {
	float eml = exp(-kappa);
	float em2l = eml * eml;
	float rl = 1.0 / kappa;
	float scale = 1.0 + 2.0 * em2l - rl;
	float bias = (eml - em2l) * rl - em2l;
	float x = sqrt(max(1.0 - scale, 0.0));
	float x0 = 0.36 * t;
	float x1 = x / (4.0 * 0.36);
	float n = x0 + x1;
	float y = abs(x0) <= x1 ? n * n / max(x, 1e-6) : clamp(t, 0.0, 1.0);
	return scale * y + bias;
}

float schlick(float u) {
	float m = 1.0 - u;
	float m2 = m * m;
	return m2 * m2 * m;
}

// Godot 4's own light (Burley diffuse, Schlick-GGX specular, as in scene_forward_lights_inc.glsl), with one change:
// a pixel of the atlas holds the average of the normals under it, and the light of many normals is not the light of
// their average. As in Han et al. 2007 ("Frequency domain normal map filtering"), the normals under the pixel are
// taken as a von Mises-Fisher lobe around their average, its sharpness from the average's length (Banerjee et al.
// 2005), and diffuse light is that lobe's average.
void light() {
	float cNdotL = max(min(dot(NORMAL, LIGHT), 1.0), 0.0);
	float cNdotV = max(dot(NORMAL, VIEW), 1e-4);
	vec3 H = normalize(VIEW + LIGHT);
	float cLdotH = clamp(dot(LIGHT, H), 0.0, 1.0);
	float cNdotH = clamp(dot(NORMAL, H), 0.0, 1.0);
	if (METALLIC < 1.0) {
		float fd90 = 2.0 * cLdotH * cLdotH * ROUGHNESS - 0.5;
		float burley = (1.0 + fd90 * schlick(cNdotV)) * (1.0 + fd90 * schlick(cNdotL));  // Burley's shape, without n.L
		float r = min(normal_len, 0.999);  // a unit average is a lobe of one normal (kappa ~ 1000 here)
		float kappa = r * (3.0 - r * r) / (1.0 - r * r);
		float e = filtered ? lobe_diffuse(dot(NORMAL, LIGHT), kappa) : cNdotL;
		DIFFUSE_LIGHT += LIGHT_COLOR * ATTENUATION * burley * e / PI;
	}
	if (ROUGHNESS > 0.0) {
		float a = ROUGHNESS * ROUGHNESS;
		float ah = cNdotH * a;
		float k = a / (1.0 - cNdotH * cNdotH + ah * ah);
		float d = k * k / PI;
		float g = 0.5 / mix(2.0 * cNdotL * cNdotV, cNdotL + cNdotV, a);
		vec3 f0 = mix(vec3(0.16 * 0.5 * 0.5), ALBEDO, METALLIC);  // Godot's F0 at its default specular 0.5
		float f90 = clamp(dot(f0, vec3(50.0 * 0.33)), METALLIC, 1.0);
		vec3 f = f0 + (f90 - f0) * schlick(cLdotH);
		SPECULAR_LIGHT += cNdotL * d * f * g * LIGHT_COLOR * ATTENUATION * SPECULAR_AMOUNT;
	}
}
'''

# Colour and occlusion/roughness/metalness as Godot compresses textures for 3D (VRAM, with mipmaps): a far view needs
# no more, a quarter of the memory. Normal + depth kept lossless: compressed, its smaller copies lit white patches on
# the mech at 60 and 40 px (2026-11-18; Godot 4.7, block compression of three free normal components plus depth).
IMPOSTOR_IMPORT = {k: ('[remap]\n\nimporter="texture"\ntype="CompressedTexture2D"\n\n[params]\n\n'
                       f'compress/mode={0 if k == "normal" else 2}\ndetect_3d/compress_to=0\nmipmaps/generate=true\n')
                   for k in ("color", "normal", "orm")}
IMPOSTOR_RES = ('[ext_resource type="Shader" path="impostor.gdshader" id="6_imp"]\n'
                '[ext_resource type="Texture2D" path="impostor_color.png" id="7_imc"]\n'
                '[ext_resource type="Texture2D" path="impostor_normal.png" id="8_imn"]\n'
                '[ext_resource type="Texture2D" path="impostor_orm.png" id="9_imo"]\n')
IMPOSTOR_SUB = ('\n[sub_resource type="QuadMesh" id="imp_quad"]\nsize = Vector2(2, 2)\n'
                '\n[sub_resource type="ShaderMaterial" id="imp_mat"]\nrender_priority = 0\nshader = ExtResource("6_imp")\n'
                'shader_parameter/color_atlas = ExtResource("7_imc")\nshader_parameter/normal_atlas = ExtResource("8_imn")\n'
                'shader_parameter/orm_atlas = ExtResource("9_imo")\nshader_parameter/frames = {frames}.0\n'
                'shader_parameter/radius = {radius:g}\nshader_parameter/centre = Vector3({centre})\n')
# The shader places the square around the centre, facing the camera, a little over the radius from it in perspective:
# Godot culls by this box, which holds it from any side.
IMPOSTOR_NODE = ('\n[node name="impostor_LOD{level}" type="MeshInstance3D" parent="{parent}"]\n'
                 'custom_aabb = AABB({corner}, {side:g}, {side:g}, {side:g})\n'
                 'mesh = SubResource("imp_quad")\nmaterial_override = SubResource("imp_mat")\n')

SCENE_TSCN = """[gd_scene load_steps={steps} format=3]

[ext_resource type="Script" path="lod_switch.gd" id="1_lod"]
[ext_resource type="PackedScene" path="model.glb" id="2_model"]
{more}{shapes}
[node name="model" type="{root}"]
{props}
[node name="levels" parent="." instance=ExtResource("2_model")]
{levels}{bodies}"""

LOD_PROPS = 'script = ExtResource("1_lod")\nlod_screen_px = PackedFloat32Array({px})\n'


def _scene(px: list[float], pieces: list | None, moving: bool = False, depth: float | None = None,
           impostor: dict | None = None, level: int = 0) -> str:
    """model.tscn; with collision pieces, a StaticBody3D "collision" holding one convex shape per piece. moving: the
    root is a RigidBody3D instead (moving_body.gd, with Size), the pieces right under it and the LOD switch on
    "levels", so the model falls and can be pushed. depth: with a height map, a "parallax" node (parallax.gd) with
    this Height Scale. impostor (after.impostor): a square "impostor_LOD<level>" after the last level, which the LOD
    switch shows from px's last size down (px has its size already)."""
    scene = _scene_body(px, pieces, moving)
    if depth is None and impostor is None:
        return scene
    head, _, rest = scene.partition("\n")
    steps = int(head.split("load_steps=")[1].split()[0])
    more = (2 if depth is not None else 0) + (6 if impostor else 0)
    head = head.replace(f"load_steps={steps}", f"load_steps={steps + more}")
    at = rest.index("[ext_resource type=\"PackedScene\"")
    rest = rest[:at] + (PARALLAX_RES if depth is not None else "") + (IMPOSTOR_RES if impostor else "") + rest[at:]
    if impostor:
        r, c = impostor["radius"], np.asarray(impostor["centre"], float)
        at = rest.index("\n[node ")
        rest = rest[:at] + IMPOSTOR_SUB.format(frames=impostor["frames"], radius=r, centre=_vec(c)) + rest[at:]
        rest += IMPOSTOR_NODE.format(level=level, parent="levels" if 'type="RigidBody3D"' in rest else ".",
                                     corner=_vec(c - 1.5 * r), side=float(f"{3 * r:.6g}"))
    return head + "\n" + rest + (PARALLAX_NODE.format(scale=depth) if depth is not None else "")


def _scene_body(px: list[float], pieces: list | None, moving: bool = False) -> str:
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
README_PARALLAX = ('  parallax.gd    parallax on LOD0 from height.png, so grooves look deep up close (Height Scale\n'
                   '                 measured from the original; set Enabled off on the "parallax" node to drop it)\n'
                   '  height.png     the height map: white the surface, black the deepest groove (16-bit)\n')
README_IMPOSTOR = ('  impostor.gdshader, impostor_*.png  the farthest view: the model as pictures on 2 triangles\n'
                   '                 (node impostor_LOD{level}), shown when the model is under {px:g} px across\n')
SCALING = "Scaling the scene is fine: the switch distances follow its size."
SCALING_MOVING = ("To make the prop bigger or smaller, set Size on the root and leave its Scale at 1 (Godot Physics sets a\n"
                  "moving body's Scale back to 1 when the game runs); the switch distances follow the size.")


README_RIG = '''  {n}. Animation: the model has a skeleton ({bones} bones){levels}.
'''
README_HUMANOID = '''  {n}. Animation: the model has a human skeleton with standard bone names ({bones} bones), and model.glb.import
     maps them to Godot's humanoid profile (Retarget > Bone Map), so ready-made humanoid animations play on it:
     LOD0's skeleton becomes %GeneralSkeleton, the name Godot's retargeted animations look for. Import an animation
     pack with the same humanoid Bone Map, then add its AnimationLibrary to an AnimationPlayer under the model.
     {levels_cap}. Cloth such as capes follows the legs and arms; give it spring bones or cloth in Godot if it
     needs to swing.
'''

# Our auto-rig's standard bone names (Mixamo style) -> Godot's SkeletonProfileHumanoid.
HUMANOID_BONES = {"Hips": "Hips", "Spine": "Spine", "Spine1": "Chest", "Spine2": "UpperChest", "Neck": "Neck", "Head": "Head"}
for _s in ("Left", "Right"):
    HUMANOID_BONES.update({_s + "Shoulder": _s + "Shoulder", _s + "Arm": _s + "UpperArm", _s + "ForeArm": _s + "LowerArm",
                           _s + "Hand": _s + "Hand", _s + "UpLeg": _s + "UpperLeg", _s + "Leg": _s + "LowerLeg",
                           _s + "Foot": _s + "Foot", _s + "ToeBase": _s + "Toes"})
    for _i, _part in enumerate(("Metacarpal", "Proximal", "Distal"), 1):
        HUMANOID_BONES[f"{_s}HandThumb{_i}"] = f"{_s}Thumb{_part}"
    for _f, _g in (("Index", "Index"), ("Middle", "Middle"), ("Ring", "Ring"), ("Pinky", "Little")):
        for _i, _part in enumerate(("Proximal", "Intermediate", "Distal"), 1):
            HUMANOID_BONES[f"{_s}Hand{_f}{_i}"] = f"{_s}{_g}{_part}"
HUMANOID_CORE = {"Hips", "Spine", "Head", "LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand",
                 "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot"}


def _rigged(glb: bytes) -> tuple[str, list[str], bool] | None:
    """For a rigged lods.glb: LOD0's skeleton path in Godot, its bone names, and whether every level is on that one
    skeleton (lod.mjs shares it when the levels' bones match). None when the model has no skeleton."""
    import json
    import struct

    n = struct.unpack("<I", glb[12:16])[0]
    j = json.loads(glb[20:20 + n])
    if not j.get("skins"):
        return None
    nodes = j["nodes"]
    parent = {c: i for i, nd in enumerate(nodes) for c in nd.get("children", [])}
    joints = j["skins"][0]["joints"]  # LOD0's: the file starts from LOD0
    chain, i = [], parent.get(joints[0])
    while i is not None:  # the armature = the first bone's parent (Godot puts Skeleton3D under it)
        chain.append(nodes[i].get("name", ""))
        i = parent.get(i)
    one = all(s["joints"] == joints for s in j["skins"])
    return "/".join(reversed(chain)) + "/Skeleton3D", [nodes[i].get("name", "") for i in joints], one


def _import_file(path: str) -> str:
    """model.glb.import: Godot's humanoid Bone Map on the skeleton (written inline, so the folder can move), plus Godot's
    own Rest Fixer > Fix Silhouette: AI models stand in an A-pose or other rest pose while humanoid animations are made
    on a T-pose, so without it the arms of every retargeted animation land wrong (punch at the hips, sword swing with
    the arms down) and fingers splay. It turns the rest pose to the profile's T-pose at import (Godot's retargeting
    docs advise it for models not in a T-pose)."""
    pairs = ",".join(f'"bone_map/{g}":&"{ours}"' for ours, g in HUMANOID_BONES.items())
    bone_map = f'Object(BoneMap,"profile":Object(SkeletonProfileHumanoid,"script":null),{pairs},"script":null)'
    return ('[remap]\n\nimporter="scene"\nimporter_version=1\ntype="PackedScene"\n\n[params]\n\n'
            '_subresources={\n"nodes": {\n"PATH:' + path + '": {\n"retarget/bone_map": ' + bone_map + ",\n"
            '"retarget/rest_fixer/fix_silhouette/enable": true\n}\n}\n}\n')


def _entry(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(f"{FOLDER}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
    info.external_attr = 0o644 << 16
    return info


def add_godot(report: dict[str, Any], lods_asked: bool = True, pieces: list | None = None, moving: bool = False) -> None:
    """Adds extraFiles["godot.zip"] and after.godot when the job made LOD levels; otherwise a step says why not.
    pieces: the collision pieces (game_collision), already where the model is. moving: a prop that falls and can be
    pushed (the root a RigidBody3D); it needs the pieces. A height map (extraFiles["height.png"], after.height) goes in
    with parallax.gd, which turns parallax on for LOD0. Never fails the job."""
    after, steps = report["after"], report["steps"]
    extra = report.get("extraFiles") or {}
    height = extra.get("height.png")
    imp_files = [extra.get(f"impostor_{k}.png") for k in ("color", "normal", "orm")]
    impostor = after.get("impostor") if all(imp_files) else None
    depth = (after.get("height") or {}).get("godotScale") if height else None
    lods = (report.get("extraFiles") or {}).get("lods.glb")
    levels = (after.get("lod") or {}).get("levels") or []
    if not lods or len(levels) < 2:
        steps.append("no Godot package: it switches LOD levels, and " +
                     ("this job made none (see the LOD step)" if lods_asked else "they come with lods: true"))
        return
    px = [float(level["maxScreenPx"]) for level in levels[1:]]
    imp_px = None
    switch_px = px
    if impostor:
        # Under its own size, but never before the last level: the impostor stands in for the farthest one only.
        imp_px = min(float(impostor["maxScreenPx"]), px[-1])
        switch_px = px + [imp_px]
    chain = " -> ".join(str(level["triangles"]) for level in levels)
    switch = "\n".join(f"       LOD{level['level']} when the model is under {level['maxScreenPx']} px across"
                       for level in levels[1:])
    fd, name = tempfile.mkstemp(suffix=".zip")
    os.close(fd)  # written by name; an open handle would lock it on Windows
    packed = Path(name)
    try:
        glb = Path(lods).read_bytes()
        rig = _rigged(glb)
        humanoid = bool(rig) and HUMANOID_CORE <= set(rig[1])
        with zipfile.ZipFile(packed, "w") as z:
            body = moving and bool(pieces)
            collision = (README_MOVING if body else README_COLLISION).format(count=len(pieces)) if pieces else ""
            if rig:
                one = "All levels are on this one skeleton, so one animation moves them all" if rig[2] else (
                    "Only LOD0 is on this skeleton: the other levels' bones didn't match it, so they keep their own")
                collision += (README_HUMANOID if humanoid else README_RIG).format(
                    n=5 if pieces else 4, bones=len(rig[1]), levels="; " + one[0].lower() + one[1:], levels_cap=one)
            readme = README.format(count=len(levels), chain=chain, switch=switch, collision=collision,
                                   more=("  moving_body.gd the moving body, with Size\n" if body else "")
                                   + ("  model.glb.import  Godot's import settings: the humanoid Bone Map\n" if humanoid else "")
                                   + (README_PARALLAX if depth is not None else "")
                                   + (README_IMPOSTOR.format(level=len(levels), px=imp_px) if impostor else ""),
                                   fov_node='"levels" node' if body else "scene's root node",
                                   scaling=SCALING_MOVING if body else SCALING)
            z.writestr(_entry("README.txt"), readme, zipfile.ZIP_DEFLATED)
            z.writestr(_entry("lod_switch.gd"), LOD_SWITCH_GD, zipfile.ZIP_DEFLATED)
            if body:
                z.writestr(_entry("moving_body.gd"), MOVING_BODY_GD, zipfile.ZIP_DEFLATED)
            if humanoid:
                z.writestr(_entry("model.glb.import"), _import_file(rig[0]), zipfile.ZIP_DEFLATED)
            z.writestr(_entry("model.glb"), glb, zipfile.ZIP_STORED)  # textures inside are already packed
            if depth is not None:
                z.writestr(_entry("parallax.gd"), PARALLAX_GD, zipfile.ZIP_DEFLATED)
                z.writestr(_entry("height.png"), Path(height).read_bytes(), zipfile.ZIP_STORED)  # PNG: packed already
                z.writestr(_entry("height.png.import"), HEIGHT_IMPORT, zipfile.ZIP_DEFLATED)
            if impostor:
                z.writestr(_entry("impostor.gdshader"), IMPOSTOR_GDSHADER, zipfile.ZIP_DEFLATED)
                for k, f in zip(("color", "normal", "orm"), imp_files):
                    z.writestr(_entry(f"impostor_{k}.png"), Path(f).read_bytes(), zipfile.ZIP_STORED)
                    z.writestr(_entry(f"impostor_{k}.png.import"), IMPOSTOR_IMPORT[k], zipfile.ZIP_DEFLATED)
            z.writestr(_entry("model.tscn"), _scene(switch_px, pieces, moving, depth, impostor, len(levels)),
                       zipfile.ZIP_DEFLATED)
    except Exception as exc:  # a full disk or the like: the job's other files are still good
        packed.unlink(missing_ok=True)
        steps.append(f"no Godot package: {str(exc)[:160]}")
        return
    report["extraFiles"]["godot.zip"] = str(packed)
    after["godot"] = {"file": "godot.zip", "scene": f"{FOLDER}/model.tscn", "switchPx": px,
                      "collisionPieces": len(pieces or []), "fileMb": round(packed.stat().st_size / 1048576, 2)}
    if moving and pieces:
        after["godot"]["body"] = "RigidBody3D"
    if impostor:
        after["godot"]["impostorPx"] = imp_px
    if rig:
        after["godot"]["skeleton"] = "humanoid" if humanoid else "own"
    steps.append(f"Godot package godot.zip: {FOLDER}/model.tscn switches the {len(levels)} levels by itself"
                 + (f", with {len(pieces)} collision pieces" if pieces else "")
                 + ("; its skeleton is mapped to Godot's humanoid profile for ready-made animations" if humanoid else "")
                 + ("; LOD0 has parallax from the height map (parallax.gd)" if depth is not None else "")
                 + (f"; under {imp_px:g} px across the impostor stands in (2 triangles)" if impostor else "")
                 + (" (a RigidBody3D: it falls and can be pushed)" if moving and pieces else "")
                 + ("; not a moving body: that needs the collision pieces (collision: true)" if moving and not pieces else ""))
