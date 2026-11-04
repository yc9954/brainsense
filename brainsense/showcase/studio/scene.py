"""Blender-side builder for the photoreal interior loop. Run by studio.py:
    Blender -b --python scene.py -- spec.json out.png
Spec (JSON) — everything optional except objects/camera:
  room: {w, d, h, floor_tex, wall_tex, wall_color, ceiling_color, baseboard, floor_scale, wall_scale}
  window: {wall: "left"|"back", x, z, w, h, frame_color, curtain_color|null, sill}
  world: {hdri, strength, rotation_deg}       sun: {strength, elevation_deg, azimuth_deg, kelvin}
  lights: [{type: "area"|"point", pos:[x,y,z], size, power, kelvin}]   practical: {lamp_object_id, power, kelvin}
  objects: [{asset, pos:[x,y], rot_deg, scale}]   (asset = Poly Haven model id; sits on the floor)
     ORIENTATION (verified on Sofa_01/sofa_02/sofa_03): at rot_deg 0 a seat FACES −Y, i.e. toward the camera. A sofa against
     the back wall must keep rot_deg 0 (NOT 180 — that shows its back). An armchair beside the group angled toward it uses
     rot_deg −60…−30 (left side) or 30…60 (right side).
  rug: {x, y, w, d, color|tex}                  (thin textured rug on the floor, e.g. under the coffee table)
  floor_lamp: {x, y, height, shade_color, kelvin, power}   (pole + fabric shade with a warm bulb inside)
  art: {wall: "back"|"right", x, z, w, h, color|tex, frame_color}   (framed canvas on a wall)
  camera: {pos:[x,y,z], look_at:[x,y,z], lens_mm, fstop, focus_object}
  render: {samples, w, h, exposure, look}
Lighting that reads as a photo: world.strength 0.6–1.2 (sky seen through the glass must not blow out), sun 4–8 for light
patches on floor/wall, exposure 0.2–0.8, one warm area light 60–150 W near the sofa.
Room frame: floor y from -d/2 (camera side, open) to +d/2 (back wall); x from -w/2 (left wall) to +w/2 (right wall)."""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1 :]
SPEC = json.loads(Path(args[0]).read_text())
OUT = args[1]
ASSETS = Path(args[2]) if len(args) > 2 else Path.home() / "brainsense-hackathon/brainsense/assets/polyhaven"
R = SPEC.get("room", {})
W, D, HGT = float(R.get("w", 5.0)), float(R.get("d", 5.0)), float(R.get("h", 2.8))


def hex_rgb(h, a=1.0):
    """#rrggbb (sRGB) → linear RGBA for Blender colour sockets (sRGB fed directly renders washed out)."""
    h = (h or "#cccccc").lstrip("#")
    def lin(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return (lin(int(h[0:2], 16)), lin(int(h[2:4], 16)), lin(int(h[4:6], 16)), a)


def kelvin_rgb(k):
    t = max(1000, min(12000, float(k))) / 100.0
    r = 255 if t <= 66 else 329.698727446 * ((t - 60) ** -0.1332047592)
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * ((t - 60) ** -0.0755148492)
    b = 255 if t >= 66 else (0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307)
    return tuple(max(0, min(255, x)) / 255 for x in (r, g, b))


def tex_files(tid):
    d = ASSETS / "textures" / tid
    if not d.exists():
        return {}
    out = {}
    for f in d.iterdir():
        n = f.name.lower()
        for key, pat in (("diff", "_diff_"), ("rough", "_rough_"), ("nor", "_nor_gl_"), ("arm", "_arm_"), ("disp", "_disp_")):
            if pat in n:
                out[key] = str(f)
    return out


def pbr_material(name, tid=None, color="#cccccc", scale=1.0, rough=0.6):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = rough
    files = tex_files(tid) if tid else {}
    if not files.get("diff"):
        bsdf.inputs["Base Color"].default_value = hex_rgb(color)
        return m
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (scale, scale, scale)
    nt.links.new(coord.outputs["Object"], mapping.inputs["Vector"])

    def img(path, noncolor=False):
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(path)
        node.projection = "BOX"
        node.projection_blend = 0.2
        if noncolor:
            node.image.colorspace_settings.name = "Non-Color"
        nt.links.new(mapping.outputs["Vector"], node.inputs["Vector"])
        return node

    nt.links.new(img(files["diff"]).outputs["Color"], bsdf.inputs["Base Color"])
    if files.get("rough"):
        nt.links.new(img(files["rough"], True).outputs["Color"], bsdf.inputs["Roughness"])
    elif files.get("arm"):
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(img(files["arm"], True).outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
    if files.get("nor"):
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.inputs["Strength"].default_value = 0.6
        nt.links.new(img(files["nor"], True).outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    return m


def box(name, loc, dim, m, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.object
    o.name = name
    o.scale = dim
    o.data.materials.append(m)
    return o


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
RS = SPEC.get("render", {})
sc.render.engine = "CYCLES"
sc.cycles.samples = int(RS.get("samples", 128))
sc.cycles.use_denoising = True
sc.cycles.max_bounces = 8
sc.render.resolution_x, sc.render.resolution_y = int(RS.get("w", 1280)), int(RS.get("h", 800))
sc.render.filepath = OUT
sc.render.film_transparent = False
try:
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = RS.get("look", "AgX - Medium High Contrast")
except TypeError:
    pass
sc.view_settings.exposure = float(RS.get("exposure", 0.0))

# ---- room shell
floor_m = pbr_material("floor", R.get("floor_tex"), R.get("floor_color", "#a8865e"), float(R.get("floor_scale", 0.6)), 0.45)
wall_m = pbr_material("walls", R.get("wall_tex"), R.get("wall_color", "#e8e4dc"), float(R.get("wall_scale", 0.5)), 0.85)
box("floor", (0, 0, -0.05), (W, D, 0.1), floor_m)
box("ceiling", (0, 0, HGT + 0.05), (W, D, 0.1), pbr_material("ceil", None, R.get("ceiling_color", "#f5f3ee"), 1, 0.9))
walls = {"back": ((0, D / 2 + 0.05, HGT / 2), (W, 0.1, HGT)), "left": ((-W / 2 - 0.05, 0, HGT / 2), (0.1, D, HGT)), "right": ((W / 2 + 0.05, 0, HGT / 2), (0.1, D, HGT))}
win = SPEC.get("window", {"wall": "left", "x": 0.3, "z": 1.5, "w": 1.9, "h": 1.5})
for name, (loc, dim) in walls.items():
    if name == win.get("wall", "left"):
        # wall with a hole: 4 slabs around the window
        wx, wz, ww, wh = float(win.get("x", 0)), float(win.get("z", 1.5)), float(win.get("w", 1.8)), float(win.get("h", 1.4))
        along = D if name == "left" else W
        lo, hi = wx - ww / 2, wx + ww / 2
        zlo, zhi = wz - wh / 2, wz + wh / 2
        segs = [((-along / 2 + lo) / 2, (lo + along / 2), HGT / 2, HGT), ((hi + along / 2) / 2, (along / 2 - hi), HGT / 2, HGT), (wx, ww, zlo / 2, zlo), (wx, ww, (zhi + HGT) / 2, HGT - zhi)]
        for i, (c, ln, zc, zh) in enumerate(segs):
            if ln <= 0.01 or zh <= 0.01:
                continue
            if name == "left":
                box(f"wall_left_{i}", (-W / 2 - 0.05, c, zc), (0.1, ln, zh), wall_m)
            else:
                box(f"wall_back_{i}", (c, D / 2 + 0.05, zc), (ln, 0.1, zh), wall_m)
        # frame + glass + exterior light panel
        fc = pbr_material("frame", None, win.get("frame_color", "#f2f2f2"), 1, 0.4)
        glass = bpy.data.materials.new("glass")
        glass.use_nodes = True
        glass.node_tree.nodes["Principled BSDF"].inputs["Transmission Weight"].default_value = 1.0
        glass.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.0
        glass.node_tree.nodes["Principled BSDF"].inputs["IOR"].default_value = 1.45
        glass.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.92, 0.95, 0.97, 1)
        if name == "left":
            box("win_frame_l", (-W / 2 - 0.02, lo - 0.03, wz), (0.08, 0.06, wh + 0.12), fc)
            box("win_frame_r", (-W / 2 - 0.02, hi + 0.03, wz), (0.08, 0.06, wh + 0.12), fc)
            box("win_frame_t", (-W / 2 - 0.02, wx, zhi + 0.03), (0.08, ww + 0.12, 0.06), fc)
            box("win_frame_b", (-W / 2 - 0.02, wx, zlo - 0.03), (0.08, ww + 0.12, 0.06), fc)
            box("win_mullion_v", (-W / 2 - 0.01, wx, wz), (0.05, 0.035, wh), fc)
            box("win_mullion_h", (-W / 2 - 0.01, wx, wz + wh * 0.18), (0.05, ww, 0.035), fc)
            box("win_glass", (-W / 2 - 0.02, wx, wz), (0.006, ww, wh), glass)
            box("win_sill", (-W / 2 + 0.08, wx, zlo - 0.02), (0.24, ww + 0.24, 0.04), fc)
            if win.get("curtain_color"):
                cm = pbr_material("curtain", None, win["curtain_color"], 1, 0.95)
                box("curtain_l", (-W / 2 + 0.12, lo - 0.25, (zlo - 0.3 + HGT - 0.1) / 2), (0.06, 0.5, HGT - 0.1 - zlo + 0.3), cm)
                box("curtain_r", (-W / 2 + 0.12, hi + 0.25, (zlo - 0.3 + HGT - 0.1) / 2), (0.06, 0.5, HGT - 0.1 - zlo + 0.3), cm)
        else:
            box("win_frame", (wx, D / 2 + 0.02, wz), (ww + 0.12, 0.06, wh + 0.12), fc)
            box("win_glass", (wx, D / 2 + 0.02, wz), (ww, 0.01, wh), glass)
    else:
        box(f"wall_{name}", loc, dim, wall_m)
if R.get("baseboard", True):
    bm = pbr_material("baseboard", None, R.get("baseboard_color", "#f4f2ee"), 1, 0.5)
    box("bb_back", (0, D / 2 - 0.01, 0.06), (W, 0.02, 0.12), bm)
    box("bb_left", (-W / 2 + 0.01, 0, 0.06), (0.02, D, 0.12), bm)
    box("bb_right", (W / 2 - 0.01, 0, 0.06), (0.02, D, 0.12), bm)

# ---- world light (HDRI through the window + ambient), sun
world = bpy.data.worlds.new("w")
sc.world = world
world.use_nodes = True
wn = world.node_tree
bg = wn.nodes["Background"]
WS = SPEC.get("world", {})
hdri = None
if WS.get("hdri"):
    cands = list((ASSETS / "hdri").glob(f"{WS['hdri']}_*.hdr")) + list((ASSETS / "hdri").glob(f"{WS['hdri']}_*.exr"))
    hdri = cands[0] if cands else None
if hdri:
    env = wn.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(str(hdri))
    mp = wn.nodes.new("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value = (0, 0, math.radians(float(WS.get("rotation_deg", 0))))
    tc = wn.nodes.new("ShaderNodeTexCoord")
    wn.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
    wn.links.new(mp.outputs["Vector"], env.inputs["Vector"])
    wn.links.new(env.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = float(WS.get("strength", 1.0))
else:
    bg.inputs["Color"].default_value = (0.8, 0.85, 0.95, 1)
    bg.inputs["Strength"].default_value = float(WS.get("strength", 1.0))
SUN = SPEC.get("sun")
if SUN:
    bpy.ops.object.light_add(type="SUN", location=(0, 0, HGT))
    sun = bpy.context.object
    sun.data.energy = float(SUN.get("strength", 3.0))
    sun.data.angle = math.radians(1.5)
    sun.data.color = kelvin_rgb(SUN.get("kelvin", 5200))
    el, az = math.radians(float(SUN.get("elevation_deg", 35))), math.radians(float(SUN.get("azimuth_deg", -60)))
    sun.rotation_euler = (math.pi / 2 - el, 0, az)
for i, L in enumerate(SPEC.get("lights", [])):
    bpy.ops.object.light_add(type=("AREA" if L.get("type", "area") == "area" else "POINT"), location=tuple(L.get("pos", (0, 0, HGT - 0.2))))
    lt = bpy.context.object
    lt.data.energy = float(L.get("power", 150))
    lt.data.color = kelvin_rgb(L.get("kelvin", 3500))
    if lt.data.type == "AREA":
        lt.data.size = float(L.get("size", 1.5))
        look_at(lt, tuple(L.get("look_at", (0, D / 4, 0.5))))
    else:
        lt.data.shadow_soft_size = float(L.get("size", 0.2))

# ---- objects (Poly Haven glTF), grounded on the floor
placed = []
for i, ob in enumerate(SPEC.get("objects", [])):
    aid = ob["asset"]
    d = ASSETS / "models" / aid
    gltf = next(d.glob("*.gltf"), None) if d.exists() else None
    if not gltf:
        print("MISSING_ASSET", aid)
        continue
    before = set(bpy.data.objects)
    try:
        bpy.ops.import_scene.gltf(filepath=str(gltf))
    except Exception as exc:  # a broken glTF must never kill the render
        print("IMPORT_FAILED", aid, type(exc).__name__)
        for o in [o for o in bpy.data.objects if o not in before]:
            bpy.data.objects.remove(o, do_unlink=True)
        continue
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    if not meshes:
        continue
    # group under an empty so we can place/scale the whole model
    bpy.ops.object.empty_add(location=(0, 0, 0))
    root = bpy.context.object
    root.name = f"asset_{i}_{aid}"
    for o in new:
        if o.parent is None:
            o.parent = root
    sc_ = float(ob.get("scale", 1.0))
    root.scale = (sc_, sc_, sc_)
    root.rotation_euler = (0, 0, math.radians(float(ob.get("rot_deg", 0))))
    bpy.context.view_layer.update()
    # bounding box in world space → drop to floor, centre on pos
    pts = [root.matrix_world @ o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box] if False else [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    minz = min(p.z for p in pts)
    cx = (min(p.x for p in pts) + max(p.x for p in pts)) / 2
    cy = (min(p.y for p in pts) + max(p.y for p in pts)) / 2
    x, y = ob.get("pos", [0, 0])
    root.location = (x - cx, y - cy, -minz)
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    placed.append({"asset": aid, "min": [round(min(p.x for p in pts), 2), round(min(p.y for p in pts), 2)], "max": [round(max(p.x for p in pts), 2), round(max(p.y for p in pts), 2)], "top": round(max(p.z for p in pts), 2)})
    # practical lamp: make emissive parts glow if requested
    pr = SPEC.get("practical")
    if pr and pr.get("lamp_object_id") == aid:
        for o in meshes:
            for slot in o.material_slots:
                if slot.material and ("shade" in slot.material.name.lower() or "bulb" in slot.material.name.lower() or "light" in slot.material.name.lower()):
                    b = slot.material.node_tree.nodes.get("Principled BSDF")
                    if b:
                        b.inputs["Emission Color"].default_value = (*kelvin_rgb(pr.get("kelvin", 2700)), 1)
                        b.inputs["Emission Strength"].default_value = float(pr.get("power", 6))

# ---- parametric fixtures the asset library lacks
RUG = SPEC.get("rug")
if RUG:
    rm = pbr_material("rug", RUG.get("tex"), RUG.get("color", "#cfc5b4"), 0.6, 0.95)
    r_ = box("rug", (float(RUG.get("x", 0)), float(RUG.get("y", 0.6)), 0.006), (float(RUG.get("w", 2.4)), float(RUG.get("d", 1.7)), 0.012), rm)
    bpy.ops.object.modifier_add(type="BEVEL")
    r_.modifiers["Bevel"].width = 0.005
FL = SPEC.get("floor_lamp")
if FL:
    lx, ly, lh = float(FL.get("x", 1.8)), float(FL.get("y", 1.6)), float(FL.get("height", 1.6))
    box("lamp_base", (lx, ly, 0.015), (0.3, 0.3, 0.03), pbr_material("lampmetal", None, "#2a2a2a", 1, 0.35))
    box("lamp_pole", (lx, ly, lh / 2), (0.03, 0.03, lh), pbr_material("lamppole", None, "#2a2a2a", 1, 0.35))
    bpy.ops.mesh.primitive_cylinder_add(radius=0.2, depth=0.3, location=(lx, ly, lh + 0.1))
    shade = bpy.context.object
    shade.name = "lamp_shade"
    shm = bpy.data.materials.new("shade")
    shm.use_nodes = True
    sb = shm.node_tree.nodes["Principled BSDF"]
    sb.inputs["Base Color"].default_value = hex_rgb(FL.get("shade_color", "#f1e7d4"))
    sb.inputs["Roughness"].default_value = 0.9
    sb.inputs["Transmission Weight"].default_value = 0.35
    shade.data.materials.append(shm)
    bpy.ops.object.light_add(type="POINT", location=(lx, ly, lh + 0.1))
    bulb = bpy.context.object
    bulb.data.energy = float(FL.get("power", 25))
    bulb.data.color = kelvin_rgb(FL.get("kelvin", 2700))
    bulb.data.shadow_soft_size = 0.08
ART = SPEC.get("art")
if ART:
    aw, ah = float(ART.get("w", 0.9)), float(ART.get("h", 0.7))
    am = pbr_material("art", ART.get("tex"), ART.get("color", "#9a8f7a"), 2.0, 0.7)
    fm = pbr_material("artframe", None, ART.get("frame_color", "#1b1b1b"), 1, 0.4)
    ax, az = float(ART.get("x", 0.2)), float(ART.get("z", 1.65))
    if ART.get("wall", "back") == "back":
        box("art_frame", (ax, D / 2 - 0.02, az), (aw + 0.06, 0.03, ah + 0.06), fm)
        box("art_canvas", (ax, D / 2 - 0.035, az), (aw, 0.01, ah), am)
    else:
        box("art_frame", (W / 2 - 0.02, ax, az), (0.03, aw + 0.06, ah + 0.06), fm)
        box("art_canvas", (W / 2 - 0.035, ax, az), (0.01, aw, ah), am)

# ---- camera
C = SPEC.get("camera", {"pos": [1.6, -2.6, 1.45], "look_at": [0, 1.2, 0.8], "lens_mm": 28, "fstop": 4})
bpy.ops.object.camera_add(location=tuple(C.get("pos", (1.6, -2.6, 1.45))))
cam = bpy.context.object
cam.data.lens = float(C.get("lens_mm", 28))
cam.data.sensor_width = 36
look_at(cam, tuple(C.get("look_at", (0, 1.2, 0.8))))
cam.data.dof.use_dof = True
cam.data.dof.aperture_fstop = float(C.get("fstop", 4.0))
cam.data.dof.focus_distance = (Vector(C.get("look_at", (0, 1.2, 0.8))) - cam.location).length
sc.camera = cam
bpy.ops.render.render(write_still=True)
Path(OUT).with_suffix(".placed.json").write_text(json.dumps(placed))
print("RENDERED", OUT, json.dumps(placed))
