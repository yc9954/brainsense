"""Blender-side script: build a parametric living-room corner from a params JSON and render it.
Run by interior.py:  Blender -b --python interior_scene.py -- params.json out.png
Params (all optional): wall_color, floor_color, floor_roughness, accent_color, sofa_color, rug (bool), rug_color,
plant (bool), art (bool), art_color, lamp (bool), light_temp_k (2700–6500), key_energy (W), sun_strength,
clutter (0–8 small objects), camera ("corner"|"front"), samples."""
import json
import math
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1 :]
P = json.loads(open(args[0]).read())
OUT = args[1]
g = lambda k, d: P.get(k, d)  # noqa: E731


def hex_rgb(h, a=1.0):
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)


def mat(name, color, rough=0.6, metal=0.0, emit=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = hex_rgb(color) if isinstance(color, str) else color
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit:
        b.inputs["Emission Color"].default_value = hex_rgb(color) if isinstance(color, str) else color
        b.inputs["Emission Strength"].default_value = emit
    return m


def box(name, loc, dim, m, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.object
    o.name = name
    o.scale = (dim[0], dim[1], dim[2])
    o.data.materials.append(m)
    return o


def kelvin_rgb(k):
    # Tanner Helland approximation, normalised
    t = k / 100.0
    r = 255 if t <= 66 else 329.698727446 * ((t - 60) ** -0.1332047592)
    gg = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * ((t - 60) ** -0.0755148492)
    b = 255 if t >= 66 else (0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307)
    c = [max(0, min(255, x)) / 255 for x in (r, gg, b)]
    return (c[0], c[1], c[2])


bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.samples = int(g("samples", 48))
sc.cycles.use_denoising = True
sc.render.resolution_x, sc.render.resolution_y = 960, 600
sc.render.filepath = OUT
sc.view_settings.view_transform = "AgX" if "AgX" in [i.identifier for i in sc.view_settings.bl_rna.properties["view_transform"].enum_items] else "Filmic"

# room: floor 5x5, back wall (+y) and left wall (-x), ceiling height 2.8
walls = mat("walls", g("wall_color", "#d9d9d9"), rough=0.9)
floor_m = mat("floor", g("floor_color", "#b08860"), rough=float(g("floor_roughness", 0.5)))
box("floor", (0, 0, -0.05), (6, 6, 0.1), floor_m)
box("wall_back", (0, 3, 1.4), (6, 0.1, 2.8), walls)
box("wall_left", (-3, 0, 1.4), (0.1, 6, 2.8), walls)
box("wall_right", (3, 0, 1.4), (0.1, 6, 2.8), walls)   # closes the room for the front camera
box("ceiling", (0, 0, 2.85), (6, 6, 0.1), mat("ceil", "#f2f2f2", 0.95))
# window on the left wall (emissive panel = daylight)
win = box("window", (-2.94, 0.3, 1.5), (0.02, 1.8, 1.4), mat("glass", (1, 1, 1, 1), emit=float(g("sun_strength", 6.0))))

sofa = mat("sofa", g("sofa_color", "#6b6b6b"), rough=0.8)
box("sofa_base", (0.2, 2.2, 0.25), (2.2, 0.9, 0.5), sofa)
box("sofa_back", (0.2, 2.6, 0.7), (2.2, 0.25, 0.5), sofa)
box("sofa_arm_l", (-0.95, 2.2, 0.45), (0.25, 0.9, 0.4), sofa)
box("sofa_arm_r", (1.35, 2.2, 0.45), (0.25, 0.9, 0.4), sofa)
accent = mat("accent", g("accent_color", "#c8a04a"), rough=0.5)
box("cushion", (-0.3, 2.3, 0.6), (0.45, 0.4, 0.15), accent, rot=(0, 0, 0.2))
box("table", (0.2, 0.9, 0.22), (1.1, 0.6, 0.06), mat("table", g("table_color", "#3a2a1e"), 0.3))
for i in range(4):
    box(f"leg{i}", (0.2 + (-0.5 if i % 2 else 0.5), 0.9 + (-0.25 if i < 2 else 0.25), 0.1), (0.05, 0.05, 0.2), mat("leg", "#222222", 0.4))
if g("rug", True):
    box("rug", (0.2, 1.2, 0.006), (2.8, 2.0, 0.012), mat("rug", g("rug_color", "#8a6f5a"), 0.95))
if g("art", True):
    box("art", (0.2, 2.93, 1.65), (1.0, 0.03, 0.7), mat("art", g("art_color", "#2d4a6b"), 0.6))
    box("frame", (0.2, 2.95, 1.65), (1.08, 0.02, 0.78), mat("frame", "#111111", 0.4))
if g("plant", True):
    box("pot", (-2.2, 2.3, 0.25), (0.4, 0.4, 0.5), mat("pot", "#8d8d8d", 0.7))
    bpy.ops.mesh.primitive_ico_sphere_add(radius=0.55, subdivisions=2, location=(-2.2, 2.3, 1.0))
    bpy.context.object.data.materials.append(mat("leaves", "#3f7a3a", 0.8))
if g("lamp", True):
    box("lamp_pole", (1.9, 2.4, 0.8), (0.04, 0.04, 1.6), mat("pole", "#222222", 0.4))
    bpy.ops.mesh.primitive_cylinder_add(radius=0.25, depth=0.3, location=(1.9, 2.4, 1.7))
    bpy.context.object.data.materials.append(mat("shade", "#f3e6c8", emit=float(g("lamp_emit", 4.0))))
for i in range(int(g("clutter", 0))):
    box(f"clutter{i}", (-1.5 + (i % 4) * 0.9, 0.2 + (i // 4) * 0.5, 0.15 + 0.05 * i), (0.25, 0.2, 0.3), mat("c", ["#ff3b30", "#34c759", "#007aff", "#ffcc00"][i % 4], 0.5), rot=(0, 0, 0.4 * i))

bpy.ops.object.light_add(type="AREA", location=(1.0, -1.0, 2.6))
key = bpy.context.object
key.data.energy = float(g("key_energy", 300))
key.data.size = 2.5
key.data.color = kelvin_rgb(float(g("light_temp_k", 4000)))

cam_pos = {"corner": ((3.2, -3.4, 1.7), (math.radians(78), 0, math.radians(42))), "front": ((0.3, -3.8, 1.5), (math.radians(84), 0, 0))}[g("camera", "corner")]
bpy.ops.object.camera_add(location=cam_pos[0], rotation=cam_pos[1])
cam = bpy.context.object
cam.data.lens = 28
sc.camera = cam
bpy.ops.render.render(write_still=True)
print("RENDERED", OUT)
