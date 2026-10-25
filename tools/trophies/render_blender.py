"""Blender (5.x) studio renders of generated trophies. Called by build.py:

  blender -b --factory-startup -P render_blender.py -- [--each] [--lineup out.png]
          [--samples N] <trophy dir> [<trophy dir> ...]

Look: the app's dark background (#0d1113) with a teal accent glow, socle in
graphite PLA, medallion in the trophy finish (teal / gold / silver / bronze
silk PLA), subtle 0.2 mm layer lines so it reads as a real print.
"""

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

LAYER_MM = 0.2

FINISHES = {
    # name: (sRGB hex, metallic, roughness)
    "teal": ("#54beab", 0.25, 0.32),
    "gold": ("#e3c27a", 1.0, 0.24),
    "silver": ("#dfe3e6", 1.0, 0.22),
    "bronze": ("#c98c62", 1.0, 0.28),
    "white": ("#edf2f4", 0.0, 0.4),
    "ink": ("#2a3237", 0.0, 0.42),
}
SOCLE_FINISH = "ink"
BG_HEX = "#0d1113"
ACCENT_HEX = "#54beab"


def srgb(hex_):
    h = hex_.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return (*lin, 1.0)


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    opts = {"each": False, "lineup": None, "samples": 160, "dirs": [], "res": (1600, 2000), "transparent": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--each":
            opts["each"] = True
        elif a == "--lineup":
            opts["lineup"] = argv[i + 1]
            i += 1
        elif a == "--samples":
            opts["samples"] = int(argv[i + 1])
            i += 1
        elif a == "--res":
            opts["res"] = (int(argv[i + 1]), int(argv[i + 2]))
            i += 2
        elif a == "--transparent":
            opts["transparent"] = True
        else:
            opts["dirs"].append(Path(a))
        i += 1
    return opts


# ------------------------------------------------------------------ scene
def reset_scene(samples):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for backend in ("METAL", "OPTIX", "CUDA", "HIP"):
        try:
            prefs.compute_device_type = backend
            prefs.get_devices()
            if any(d.type != "CPU" for d in prefs.devices):
                for d in prefs.devices:
                    d.use = True
                scene.cycles.device = "GPU"
                break
        except TypeError:
            continue
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 8
    scene.view_settings.view_transform = "AgX"
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = srgb(BG_HEX)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.15
    scene.world = world
    return scene


def make_material(name, hex_, metallic, roughness, layer_axis):
    """Principled PLA with layer-line bump along an object axis (0=x,1=y,2=z)."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = srgb(hex_)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if "Coat Weight" in bsdf.inputs and metallic < 0.5:
        bsdf.inputs["Coat Weight"].default_value = 0.15

    tex = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = 2 * math.pi / (LAYER_MM / 1000)
    sine = nt.nodes.new("ShaderNodeMath")
    sine.operation = "SINE"
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.22
    bump.inputs["Distance"].default_value = 0.00002
    nt.links.new(tex.outputs["Object"], sep.inputs[0])
    nt.links.new(sep.outputs[layer_axis], mul.inputs[0])
    nt.links.new(mul.outputs[0], sine.inputs[0])
    nt.links.new(sine.outputs[0], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def import_stl(path, mat, offset=Vector((0, 0, 0))):
    bpy.ops.wm.stl_import(filepath=str(path), global_scale=0.001)
    obj = bpy.context.selected_objects[0]
    obj.location += offset
    obj.data.materials.append(mat)
    bev = obj.modifiers.new("bevel", "BEVEL")
    bev.width = 0.00025
    bev.segments = 3
    bev.limit_method = "ANGLE"
    bev.angle_limit = math.radians(40)
    bev.harden_normals = False
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier="bevel")
    # flat shading: STL triangulation + smooth normals gives streaks on flat faces
    bpy.ops.object.shade_flat()
    return obj


def add_trophy(d: Path, offset: Vector):
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    fin = FINISHES[meta.get("finish", "teal")]
    socle_mat = make_material(f"socle_{d.name}", *FINISHES[SOCLE_FINISH], layer_axis=2)
    # the emblem prints flat: its layers run through the plate thickness (world Y)
    emb_mat = make_material(f"emb_{d.name}", *fin, layer_axis=1)
    objs = [import_stl(d / f"{d.name}_socle.stl", socle_mat, offset),
            import_stl(d / "render" / "embleme_pose.stl", emb_mat, offset)]
    return objs


def add_studio(width):
    """Cyclorama backdrop + key / fill / accent lights, scaled to `width` (m)."""
    w = max(width * 3, 1.2)
    depth = 0.6
    r = 0.25
    prof = [(-depth * 2, 0.0)]
    prof += [(depth, 0.0)]
    for i in range(1, 13):
        a = math.radians(90 * i / 12)
        prof.append((depth + r * math.sin(a), r - r * math.cos(a)))
    prof.append((depth + r, 1.2))
    verts, faces = [], []
    for x in (-w / 2, w / 2):
        for y, z in prof:
            verts.append((x, y, z))
    n = len(prof)
    for i in range(n - 1):
        faces.append((i, i + 1, n + i + 1, n + i))
    mesh = bpy.data.meshes.new("cyc")
    mesh.from_pydata(verts, [], faces)
    obj = bpy.data.objects.new("cyclorama", mesh)
    bpy.context.collection.objects.link(obj)
    for p in mesh.polygons:
        p.use_smooth = True
    mat = bpy.data.materials.new("backdrop")
    mat.use_nodes = True
    b = mat.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = srgb("#11171a")
    b.inputs["Roughness"].default_value = 0.55
    mesh.materials.append(mat)

    def area(name, loc, energy, size, color="#ffffff", target=(0, 0, 0.06)):
        light = bpy.data.lights.new(name, "AREA")
        light.energy = energy
        light.size = size
        light.color = srgb(color)[:3]
        o = bpy.data.objects.new(name, light)
        o.location = loc
        bpy.context.collection.objects.link(o)
        direction = Vector(target) - Vector(loc)
        o.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        return o

    k = max(1.0, width / 0.12)
    area("key", (-0.32 * k, -0.42 * k, 0.42 * k), 9 * k * k, 0.3 * k, "#fff4e8")
    area("fill", (0.45 * k, -0.3 * k, 0.15 * k), 1.6 * k * k, 0.5 * k, "#e8f4ff")
    area("rim", (0.22 * k, 0.3 * k, 0.32 * k), 5 * k * k, 0.12 * k, ACCENT_HEX,
         target=(0, 0, 0.08))
    area("top", (0, 0, 0.6 * k), 3 * k * k, 0.4 * k)
    # soft teal glow on the backdrop, the app accent
    area("glow", (0, 0.2 * k, 0.02), 1.2 * k * k, 0.3 * k, ACCENT_HEX,
         target=(0, depth + r, 0.3 * k))


def add_reflection_card(cam, center, k):
    """Large soft card behind the camera: metals need something to reflect."""
    light = bpy.data.lights.new("card", "AREA")
    light.shape = "RECTANGLE"
    light.size, light.size_y = 0.6 * k, 0.35 * k
    light.energy = 4 * k * k
    light.color = srgb("#f4f1ea")[:3]
    o = bpy.data.objects.new("card", light)
    d = (cam.location - center)
    o.location = center + d * 1.15 + Vector((0, 0, 0.12 * k))
    o.rotation_euler = (center - o.location).to_track_quat("-Z", "Y").to_euler()
    o.visible_camera = False
    bpy.context.collection.objects.link(o)


def bbox(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def add_camera(objs, azimuth=-24, elevation=12, lens=85, margin=1.18, aspect=0.8):
    scene = bpy.context.scene
    lo, hi = bbox(objs)
    center = (lo + hi) / 2
    size = hi - lo
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = lens
    cam_data.dof.use_dof = True
    cam_data.dof.aperture_fstop = 8
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam
    if aspect < 1:  # portrait: the sensor height drives the field of view
        cam_data.sensor_fit = "VERTICAL"
        fov_h = 2 * math.atan(cam_data.sensor_height / 2 / lens)
        fov_w = 2 * math.atan(math.tan(fov_h / 2) * aspect)
    else:
        cam_data.sensor_fit = "HORIZONTAL"
        fov_w = 2 * math.atan(cam_data.sensor_width / 2 / lens)
        fov_h = 2 * math.atan(math.tan(fov_w / 2) / aspect)
    half_w = math.hypot(size.x, size.y) / 2
    half_h = size.z / 2
    dist = margin * max(half_w / math.tan(fov_w / 2), half_h / math.tan(fov_h / 2)) + size.y / 2
    az, el = math.radians(azimuth), math.radians(elevation)
    offset = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el))) * dist
    cam.location = center + offset
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam_data.dof.focus_distance = (center - cam.location).length
    return cam


def render(path, res):
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.filepath = str(path)
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    print(f"[render] {path} ({scene.cycles.device})")


def main():
    opts = parse_args()
    dirs = opts["dirs"]
    if opts["each"]:
        for d in dirs:
            reset_scene(opts["samples"])
            objs = add_trophy(d, Vector((0, 0, 0)))
            add_studio(0.12)
            cam = add_camera(objs)
            lo, hi = bbox(objs)
            add_reflection_card(cam, (lo + hi) / 2, 1.0)
            if opts["transparent"]:
                # App assets: alpha background, backdrop kept for light bounces but hidden from the camera.
                bpy.context.scene.render.film_transparent = True
                bpy.context.scene.render.image_settings.color_mode = "RGBA"
                backdrop = bpy.data.objects.get("cyclorama")
                if backdrop is not None:
                    backdrop.visible_camera = False
            render(d / f"{d.name}.png", opts["res"])
    if opts["lineup"]:
        reset_scene(opts["samples"])
        per_row = 5
        sx, sy = 0.105, 0.11
        objs = []
        rows = math.ceil(len(dirs) / per_row)
        for i, d in enumerate(dirs):
            row, col = divmod(i, per_row)
            n_in_row = min(per_row, len(dirs) - row * per_row)
            x = (col - (n_in_row - 1) / 2) * sx + (sx / 2 if row % 2 else 0)
            y = row * sy
            objs += add_trophy(d, Vector((x, y, 0)))
        lo, hi = bbox(objs)
        add_studio(hi.x - lo.x)
        cam = add_camera(objs, azimuth=0, elevation=24, lens=70, margin=1.06, aspect=16 / 9)
        add_reflection_card(cam, (lo + hi) / 2, max(1.0, (hi.x - lo.x) / 0.12))
        bpy.context.scene.camera.data.dof.aperture_fstop = 16
        render(Path(opts["lineup"]), (2560, 1440))


main()
