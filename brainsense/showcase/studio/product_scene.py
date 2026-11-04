"""Blender product / set renders the art director can call mid-loop. Presets:
  popup_booth  — a pop-up store booth: brand-colour back panel with 3D-text signage, counter, shelves with Poly Haven props,
                 spot lights, studio floor; camera hero_34 | front | topdown
  display_table — a table-top product display: plinths in brand colours, props, soft studio light; camera hero_34 | macro
  plinth_bottle — a cosmetic bottle (glass + label in brand colour) on a stone plinth; camera macro | hero_34
  device_mockup — a desk with a monitor whose screen shows spec.screen_image (live page / asset); camera hero_34 | front | macro | topdown
  abstract_sculpture — brand-colour glass + metal primitives on a plinth (infrastructure / research / dev products); camera hero_34 | macro | front
Run:  Blender -b --python product_scene.py -- spec.json out.png assets_root
spec: {preset, brand: {primary, secondary, accent, text}, props: [poly haven ids], camera, samples, w, h, backdrop: "studio"|"warm"}"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1 :]
S = json.loads(Path(args[0]).read_text())
OUT, ASSETS = args[1], Path(args[2])
B = {"primary": "#2456ff", "secondary": "#ffffff", "accent": "#9fe1cf", "text": "sweetspot"} | S.get("brand", {})


def hex_rgb(h, a=1.0):
    """#rrggbb (sRGB) → linear RGBA. Blender colour sockets are linear; feeding sRGB values directly washes every brand colour out."""
    h = h.lstrip("#")
    def lin(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return (lin(int(h[0:2], 16)), lin(int(h[2:4], 16)), lin(int(h[4:6], 16)), a)


def mat(name, color, rough=0.5, metal=0.0, emit=0.0, transmission=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = hex_rgb(color) if isinstance(color, str) else color
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if transmission:
        b.inputs["Transmission Weight"].default_value = transmission
        b.inputs["IOR"].default_value = 1.45
    if emit:
        b.inputs["Emission Color"].default_value = hex_rgb(color) if isinstance(color, str) else color
        b.inputs["Emission Strength"].default_value = emit
    return m


def mat_gradient(name, c_bottom, c_top, rough=0.9):
    """Vertical two-colour gradient (world Z) for a cyclorama: gives a horizon and depth behind a product."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = rough
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    rng = nt.nodes.new("ShaderNodeMapRange")
    rng.inputs["From Min"].default_value = 0.0
    rng.inputs["From Max"].default_value = 3.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = hex_rgb(c_bottom)
    ramp.color_ramp.elements[1].color = hex_rgb(c_top)
    nt.links.new(tc.outputs["Object"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Z"], rng.inputs["Value"])
    nt.links.new(rng.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    return m


def box(name, loc, dim, m, rot=(0, 0, 0), bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.object
    o.name = name
    o.scale = dim
    o.data.materials.append(m)
    if bevel:
        bpy.ops.object.modifier_add(type="BEVEL")
        o.modifiers["Bevel"].width = bevel
        o.modifiers["Bevel"].segments = 3
    return o


def look_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def import_prop(aid, pos, rot=0.0, scale=1.0, max_h=None):
    d = ASSETS / "models" / aid
    g = next(d.glob("*.gltf"), None) if d.exists() else None
    if not g:
        print("MISSING_ASSET", aid)
        return None
    before = set(bpy.data.objects)
    try:
        bpy.ops.import_scene.gltf(filepath=str(g))
    except Exception as e:  # noqa: BLE001
        print("IMPORT_FAILED", aid, type(e).__name__)
        return None
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    bpy.ops.object.empty_add(location=(0, 0, 0))
    root = bpy.context.object
    for o in new:
        if o.parent is None:
            o.parent = root
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    h = max(p.z for p in pts) - min(p.z for p in pts)
    if max_h and h > max_h:
        scale = scale * max_h / h
    root.scale = (scale, scale, scale)
    root.rotation_euler = (0, 0, math.radians(rot))
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    root.location = (pos[0] - (min(p.x for p in pts) + max(p.x for p in pts)) / 2, pos[1] - (min(p.y for p in pts) + max(p.y for p in pts)) / 2, pos[2] - min(p.z for p in pts))
    return root


def text3d(txt, loc, size, m, rot=(math.pi / 2, 0, 0), extrude=0.01, bold=True):
    bpy.ops.object.text_add(location=loc, rotation=rot)
    t = bpy.context.object
    t.data.body = txt
    t.data.size = size
    t.data.extrude = extrude
    t.data.align_x = "CENTER"
    try:
        t.data.font = bpy.data.fonts.load("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf")
    except Exception:  # noqa: BLE001
        pass
    t.data.materials.append(m)
    return t


bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.samples = int(S.get("samples", 96))
sc.cycles.use_denoising = True
sc.render.resolution_x, sc.render.resolution_y = int(S.get("w", 1600)), int(S.get("h", 1000))
sc.render.filepath = OUT
try:
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
except TypeError:
    pass
PRESET0 = S.get("preset", "popup_booth")
sc.view_settings.exposure = float(S.get("exposure", -0.6 if PRESET0 == "plinth_bottle" else -0.25))

# studio world
world = bpy.data.worlds.new("w")
sc.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
hdri = None
for h in S.get("hdris", ["brown_photostudio_02", "studio_small_09", "blocky_photo_studio"]):
    c = list((ASSETS / "hdri").glob(f"{h}_*.hdr"))
    if c:
        hdri = c[0]
        break
if hdri:
    env = world.node_tree.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(str(hdri))
    world.node_tree.links.new(env.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = float(S.get("hdri_strength", 0.45))
else:
    bg.inputs["Color"].default_value = (0.9, 0.9, 0.9, 1)
    bg.inputs["Strength"].default_value = 1.0

warm = S.get("backdrop", "studio") == "warm"
floor_m = mat("floor", "#efe9df" if warm else "#e9e9ea", 0.55)
box("floor", (0, 0, -0.05), (14, 14, 0.1), floor_m)
cyc = box("cyc", (0, 5.0, 3.0), (14, 0.1, 6), mat_gradient("cyc", "#d9cbb6", "#f6f1e8") if warm else mat("cyc", "#f0f0f1", 0.9))
box("cyc_l", (-7, 0, 3.0), (0.1, 14, 6), mat("cycl", "#f0f0f1", 0.9))
box("cyc_r", (7, 0, 3.0), (0.1, 14, 6), mat("cycr", "#f0f0f1", 0.9))

preset = S.get("preset", "popup_booth")
props = S.get("props", ["potted_plant_01", "ceramic_vase_01", "brass_vase_01", "decorative_book_set_01"])
cam_target = (0, 0.6, 1.0)
if preset == "popup_booth":
    prim = mat("primary", B["primary"], 0.35)
    sec = mat("secondary", B["secondary"], 0.45)
    acc = mat("accent", B["accent"], 0.4)
    # back panel + side wing, counter, shelves, signage
    box("panel", (0, 2.2, 1.4), (3.6, 0.12, 2.8), prim, bevel=0.01)
    box("wing", (-1.9, 1.4, 1.4), (0.12, 1.8, 2.8), sec, bevel=0.01)
    box("counter", (0.2, 0.6, 0.5), (2.2, 0.7, 1.0), sec, bevel=0.012)
    box("counter_top", (0.2, 0.6, 1.01), (2.3, 0.78, 0.04), acc, bevel=0.005)
    box("shelf1", (0.0, 2.0, 1.75), (2.4, 0.3, 0.04), sec)
    box("shelf2", (0.0, 2.0, 1.25), (2.4, 0.3, 0.04), sec)
    text3d(B["text"], (0, 2.13, 2.25), 0.34, mat("sign", B["secondary"], 0.3, emit=0.0), extrude=0.02)
    text3d(S.get("tagline", "POP-UP STORE"), (0, 2.13, 1.98), 0.11, mat("tag", B["accent"], 0.4), extrude=0.005, bold=False)
    slots = [(-0.8, 2.0, 1.77), (0.0, 2.0, 1.77), (0.8, 2.0, 1.77), (-0.6, 2.0, 1.27), (0.6, 2.0, 1.27), (0.9, 0.55, 1.03), (-0.5, 0.5, 1.03), (-1.3, 1.0, 0.0)]
    maxh = [0.45, 0.45, 0.45, 0.42, 0.42, 0.35, 0.35, 1.3]
    for i, aid in enumerate(props[:8]):
        import_prop(aid, slots[i], rot=(-15 + 10 * i) % 40, max_h=maxh[i])
    cam_target = (0.1, 1.2, 1.15)
    presets = {"hero_34": ((3.4, -3.0, 1.75), 32), "front": ((0.1, -4.2, 1.45), 35), "topdown": ((0.2, 0.9, 5.2), 28)}
elif preset == "display_table":
    sec = mat("secondary", B["secondary"], 0.45)
    prim = mat("primary", B["primary"], 0.35)
    acc = mat("accent", B["accent"], 0.4)
    box("table", (0, 0.6, 0.72), (2.4, 0.9, 0.06), mat("oak", "#c9a97a", 0.4), bevel=0.006)
    for i, x in enumerate((-0.9, -0.45, 0.45, 0.9)):
        box(f"leg{i}", (x, 0.6 + (0.35 if i % 2 else -0.35), 0.35), (0.05, 0.05, 0.7), mat("leg", "#2b2b2b", 0.4))
    box("plinth_a", (-0.6, 0.6, 0.86), (0.5, 0.5, 0.22), prim, bevel=0.01)
    box("plinth_b", (0.1, 0.55, 0.81), (0.4, 0.4, 0.12), acc, bevel=0.01)
    box("plinth_c", (0.75, 0.65, 0.92), (0.35, 0.35, 0.34), sec, bevel=0.01)
    for i, (aid, pos, mh) in enumerate(zip(props[:3], [(-0.6, 0.6, 0.97), (0.1, 0.55, 0.87), (0.75, 0.65, 1.09)], [0.45, 0.4, 0.4])):
        import_prop(aid, pos, rot=20 * i, max_h=mh)
    text3d(B["text"], (0, 4.9, 2.1), 0.5, mat("sign", B["primary"], 0.4), extrude=0.01)
    cam_target = (0.05, 0.6, 0.98)
    presets = {"hero_34": ((1.9, -1.6, 1.45), 50), "macro": ((0.9, -0.9, 1.15), 70), "front": ((0.05, -2.4, 1.2), 50)}
elif preset == "device_mockup":
    # a desk scene: monitor whose screen shows S["screen_image"] (the live page or a harvested asset), keyboard-ish slab, props
    desk = box("desk", (0, 0.9, 0.72), (2.6, 1.1, 0.05), mat("walnut", "#6b4a2e", 0.35), bevel=0.006)
    for i, x in enumerate((-1.15, 1.15)):
        box(f"leg{i}", (x, 0.9, 0.35), (0.06, 0.9, 0.7), mat("legm", "#1d1d1f", 0.35, metal=0.6))
    box("stand", (0, 1.15, 0.80), (0.22, 0.16, 0.12), mat("stand", "#2a2a2c", 0.3, metal=0.7), bevel=0.004)
    box("neck", (0, 1.19, 0.95), (0.06, 0.03, 0.25), mat("neck", "#2a2a2c", 0.3, metal=0.7))
    box("bezel", (0, 1.21, 1.22), (1.30, 0.03, 0.78), mat("bezel", "#0e0e10", 0.25, metal=0.3), bevel=0.006)
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 1.193, 1.22), rotation=(math.pi / 2, 0, 0))
    screen = bpy.context.object
    screen.scale = (1.24, 0.72, 1)
    sm = bpy.data.materials.new("screen")
    sm.use_nodes = True
    nt = sm.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.15
    img_path = S.get("screen_image")
    if img_path and Path(img_path).exists():
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(str(img_path))
        tex.extension = "CLIP"
        mapn = nt.nodes.new("ShaderNodeMapping")
        tc = nt.nodes.new("ShaderNodeTexCoord")
        iw, ih = tex.image.size
        # fit the top of the page to a 16:9.3 screen: crop width to screen aspect, anchor at the top
        sa = 1.24 / 0.72
        ia = iw / ih
        if ia >= sa:   # image wider than screen: crop sides
            mapn.inputs["Scale"].default_value = (sa / ia, 1, 1)
            mapn.inputs["Location"].default_value = ((1 - sa / ia) / 2, 0, 0)
        else:          # image taller (full-page): show the top
            mapn.inputs["Scale"].default_value = (1, ia / sa, 1)
            mapn.inputs["Location"].default_value = (0, 1 - ia / sa, 0)
        nt.links.new(tc.outputs["UV"], mapn.inputs["Vector"])
        nt.links.new(mapn.outputs["Vector"], tex.inputs["Vector"])
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = float(S.get("screen_emit", 1.6))
    else:
        bsdf.inputs["Base Color"].default_value = hex_rgb(B["primary"])
        bsdf.inputs["Emission Color"].default_value = hex_rgb(B["primary"])
        bsdf.inputs["Emission Strength"].default_value = 1.2
    screen.data.materials.append(sm)
    box("keyboard", (0.0, 0.62, 0.755), (0.62, 0.2, 0.012), mat("alu", "#c9c9cc", 0.3, metal=0.8), bevel=0.003)
    box("mouse", (0.5, 0.62, 0.765), (0.06, 0.11, 0.03), mat("alu2", "#d4d4d7", 0.3, metal=0.6), bevel=0.01)
    box("notebook", (-0.75, 0.75, 0.755), (0.26, 0.36, 0.015), mat("paper", B["accent"], 0.7), bevel=0.003)
    slots = [(0.95, 1.05, 0.745), (-1.0, 1.05, 0.745), (0.72, 0.8, 0.745)]
    for i, aid in enumerate(props[:3]):
        import_prop(aid, slots[i], rot=15 * i, max_h=[0.42, 0.38, 0.14][i])
    cam_target = (0, 1.1, 1.08)
    presets = {"hero_34": ((1.8, -1.35, 1.45), 42), "front": ((0, -1.9, 1.2), 45), "macro": ((0.7, -0.6, 1.25), 60), "topdown": ((0.2, 0.9, 3.4), 35)}
elif preset == "abstract_sculpture":
    # brand-colour glass / metal primitives on a plinth: a hero object for infrastructure, research and developer products
    stone = mat("stone", "#d6d1c8", 0.75)
    box("plinth", (0, 0.6, 0.35), (1.2, 1.2, 0.7), stone, bevel=0.008)
    glass = mat("glass", B["primary"], 0.03, transmission=0.92)
    metal = mat("metal", B["secondary"], 0.22, metal=1.0)
    accent = mat("acc", B["accent"], 0.3)
    bpy.ops.mesh.primitive_torus_add(location=(-0.15, 0.6, 1.05), rotation=(math.radians(70), 0, math.radians(20)), major_radius=0.32, minor_radius=0.075, major_segments=96, minor_segments=32)
    bpy.context.object.data.materials.append(glass)
    bpy.ops.object.shade_smooth()
    bpy.ops.mesh.primitive_ico_sphere_add(radius=0.2, subdivisions=4, location=(0.32, 0.45, 0.9))
    bpy.context.object.data.materials.append(metal)
    bpy.ops.object.shade_smooth()
    bpy.ops.mesh.primitive_cylinder_add(radius=0.09, depth=0.9, location=(-0.45, 0.85, 1.15), rotation=(0, math.radians(12), 0), vertices=64)
    bpy.context.object.data.materials.append(accent)
    bpy.ops.object.shade_smooth()
    bpy.ops.mesh.primitive_cube_add(size=0.26, location=(0.1, 0.95, 0.83), rotation=(math.radians(15), math.radians(30), 0))
    bpy.context.object.data.materials.append(mat("cube", B["primary"], 0.4))
    for i, aid in enumerate(props[:2]):
        import_prop(aid, (-1.2 + 2.4 * i, 1.6, 0.0), rot=30 * i, max_h=1.2)
    cam_target = (0, 0.6, 1.0)
    presets = {"hero_34": ((1.6, -1.5, 1.35), 50), "macro": ((0.9, -0.9, 1.15), 70), "front": ((0, -2.1, 1.05), 55)}
else:  # plinth_bottle — a cosmetic bottle hero: brand-coloured label, tinted glass, accent cap, props behind out of focus
    stone = mat("stone", "#cfc7bb", 0.7)
    box("plinth", (0, 0.4, 0.45), (0.5, 0.5, 0.9), stone, bevel=0.008)
    box("plinth_back", (0.45, 0.9, 0.38), (0.8, 0.5, 0.76), mat("stone2", "#c4bbae", 0.75), bevel=0.008)
    glass_kind = S.get("glass", "frosted")
    glass_col = S.get("glass_colour") or B["primary"]
    if glass_kind == "clear":
        glass_m = mat("glass", glass_col, 0.04, transmission=0.95)
    else:
        glass_m = mat("glass", glass_col, 0.35, transmission=0.8)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.055, depth=0.2, location=(0, 0.4, 1.0), vertices=96)
    bottle = bpy.context.object
    bottle.data.materials.append(glass_m)
    bpy.ops.object.shade_smooth()
    bpy.ops.object.modifier_add(type="BEVEL")
    bottle.modifiers["Bevel"].width = 0.006
    bottle.modifiers["Bevel"].segments = 4
    bpy.ops.mesh.primitive_cylinder_add(radius=0.0565, depth=0.09, location=(0, 0.4, 0.985), vertices=96)
    label = bpy.context.object
    label_m = mat("label", B["primary"], 0.85)
    label_m.node_tree.nodes["Principled BSDF"].inputs["Specular IOR Level"].default_value = 0.15   # matte paper label: brand colour stays saturated, no specular wash
    label.data.materials.append(label_m)
    bpy.ops.object.shade_smooth()
    bpy.ops.mesh.primitive_cylinder_add(radius=0.032, depth=0.05, location=(0, 0.4, 1.125), vertices=64)
    cap = bpy.context.object
    cap.data.materials.append(mat("cap", B["accent"], 0.2, metal=0.15))
    bpy.ops.object.shade_smooth()
    cam_target = (0, 0.4, 1.0)
    presets = {"macro": ((0.82, -0.78, 1.1), 85), "hero_34": ((0.78, -0.72, 1.22), 60), "front": ((0, -1.45, 1.02), 70)}
    if S.get("camera") not in presets:
        S["camera"] = "macro"
    # label text on the camera-facing tangent of the band, centred, small enough to stay on the flat-ish part of the curve
    cpos = presets[S["camera"]][0]
    az = math.atan2(cpos[1] - 0.4, cpos[0] - 0.0)
    rr = 0.0578
    lbl = B["text"][:12].upper()
    tsize = 0.02 if len(lbl) <= 6 else 0.015
    rr = 0.0566
    t = text3d(lbl, (rr * math.cos(az), 0.4 + rr * math.sin(az), 0.975), tsize, mat("lbl_txt", B["accent"], 0.4),
               rot=(math.pi / 2, 0, az + math.pi / 2), extrude=0.0012)
    # wrap the text around the band so the letter ends do not float off the cylinder
    bpy.context.view_layer.objects.active = t
    bpy.ops.object.modifier_add(type="SIMPLE_DEFORM")
    bend = t.modifiers["SimpleDeform"]
    bend.deform_method = "BEND"
    bend.deform_axis = "Y"
    bend.angle = float(S.get("label_bend_sign", 1)) * (len(lbl) * tsize * 0.62) / rr
    # props behind-right of the bottle (screen right for hero_34), on a lower plinth
    slots = [(0.3, 0.82, 0.76), (0.62, 0.9, 0.76)]
    for i, aid in enumerate(props[:2]):
        import_prop(aid, slots[i], rot=30 * i, max_h=[0.42, 0.36][i])

# lights: key spot + soft fill + rim
bpy.ops.object.light_add(type="AREA", location=(2.2, -1.5, 3.2))
key = bpy.context.object
key.data.energy = float(S.get("key_power", 500 if preset == "plinth_bottle" else 650))
key.data.size = 1.2 if preset == "plinth_bottle" else 2.0
key.data.color = (1.0, 0.95, 0.88) if warm else (1, 1, 1)
look_at(key, cam_target)
bpy.ops.object.light_add(type="AREA", location=(-2.5, -1.0, 2.4))
fill = bpy.context.object
fill.data.energy = float(S.get("fill_power", 120 if preset == "plinth_bottle" else 300))
fill.data.size = 3.0
look_at(fill, cam_target)
bpy.ops.object.light_add(type="AREA", location=(-1.0, 3.5, 3.0))
rim = bpy.context.object
rim.data.energy = 400
rim.data.size = 1.5
rim.data.color = hex_rgb(B["accent"])[:3]
look_at(rim, cam_target)

cam_name = S.get("camera", "macro" if preset == "plinth_bottle" else "hero_34")
pos, lens = presets.get(cam_name, list(presets.values())[0])
bpy.ops.object.camera_add(location=pos)
cam = bpy.context.object
cam.data.lens = lens
look_at(cam, cam_target)
cam.data.dof.use_dof = True
cam.data.dof.aperture_fstop = float(S.get("fstop", 4.0 if preset != "plinth_bottle" else 2.8))
cam.data.dof.focus_distance = (Vector(cam_target) - cam.location).length
sc.camera = cam
bpy.ops.render.render(write_still=True)
print("RENDERED", OUT)
