"""Render the PhantomClick 3D mark with Blender (headless).

The mark: a phantom cursor. An ice-glass arrow with a fading ghost trail,
locking into four corner brackets over a slate plate. Same palette as
``ui/theme.py`` (slate surfaces, ice-blue selection, green for live).

Outputs, all with a transparent background so ``make_icon.py`` and
``make_splash.py`` can compose them:

    packaging/render/mark_1024.png        still, square, for the icon
    packaging/render/boot/frame_000.png   48 frames, 2:1, for the boot animation
    ...

Run::

    "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b -P packaging/blender_mark.py -- [--still] [--anim] [--quick]

``--quick`` renders at half size with fewer samples for iteration.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
OUT = HERE / "render"
OUT.mkdir(exist_ok=True)

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
QUICK = "--quick" in ARGS
DO_STILL = "--still" in ARGS or not ("--anim" in ARGS)
DO_ANIM = "--anim" in ARGS or not ("--still" in ARGS)

# Palette (sRGB hex from ui/theme.py), converted to linear for Blender.
def lin(hexstr: str) -> tuple[float, float, float, float]:
    h = hexstr.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    def c(v: float) -> float:
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return (c(r), c(g), c(b), 1.0)

SLATE = lin("#151A21")
SLATE_DEEP = lin("#0E1116")
BORDER = lin("#34414F")
ICE = lin("#7CC4F2")
ICE_HI = lin("#BFE3FA")
RUN = lin("#4ADE80")

FRAMES = 48
FPS = 30


# -- Scene ---------------------------------------------------------------------

def reset() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def material(name: str, color, *, emission=None, strength: float = 0.0,
             roughness: float = 0.5, metallic: float = 0.0, alpha: float = 1.0,
             transmission: float = 0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nodes = m.node_tree.nodes
    p = nodes.get("Principled BSDF")
    p.inputs["Base Color"].default_value = color
    p.inputs["Roughness"].default_value = roughness
    p.inputs["Metallic"].default_value = metallic
    p.inputs["Alpha"].default_value = alpha
    if "Transmission Weight" in p.inputs:
        p.inputs["Transmission Weight"].default_value = transmission
    if emission is not None:
        p.inputs["Emission Color"].default_value = emission
        p.inputs["Emission Strength"].default_value = strength
    if alpha < 1.0 and hasattr(m, "surface_render_method"):
        m.surface_render_method = "BLENDED"
    elif alpha < 1.0:
        m.blend_method = "BLEND"
    return m


def extrude_polygon(name: str, points, depth: float, bevel: float = 0.0):
    """Flat polygon in XY extruded along Z into a solid."""
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    verts = [(x, y, 0.0) for x, y in points]
    mesh.from_pydata(verts, [], [list(range(len(points)))])
    mesh.update()
    solid = obj.modifiers.new("solid", "SOLIDIFY")
    solid.thickness = depth
    solid.offset = 1.0
    if bevel > 0:
        b = obj.modifiers.new("bevel", "BEVEL")
        b.width = bevel
        b.segments = 3
    return obj


# Classic arrow cursor outline, unit height, tip at the origin, y down.
CURSOR = [(0.0, 0.0), (0.0, 1.0), (0.27, 0.77), (0.46, 1.16), (0.62, 1.09),
          (0.44, 0.71), (0.78, 0.71)]


def cursor_points(scale: float):
    return [(x * scale, -y * scale) for x, y in CURSOR]


def build(anim: bool, cursor_scale: float = 0.82, ortho: float = 2.35):
    reset()
    scene = bpy.context.scene
    scene.render.film_transparent = True
    scene.render.fps = FPS
    scene.frame_start = 0
    scene.frame_end = FRAMES - 1

    # Renderer: Eevee (fast, good enough for an emissive mark); Blender 4.2+
    # names it BLENDER_EEVEE_NEXT, 5.x plain BLENDER_EEVEE.
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = eng
            break
        except TypeError:
            continue
    ee = getattr(scene, "eevee", None)
    if ee is not None:
        ee.taa_render_samples = 16 if QUICK else 64
        for attr in ("use_bloom",):
            if hasattr(ee, attr):
                setattr(ee, attr, True)
    scene.view_settings.view_transform = "Standard"

    # World: black, no light (the plate and mark light themselves).
    world = bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0, 0, 0, 1)
    bg.inputs[1].default_value = 0.0

    # Plate: rounded slate square, slightly recessed centre.
    bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0, 0, -0.06))
    plate = bpy.context.active_object
    plate.name = "plate"
    b = plate.modifiers.new("bevel", "BEVEL")
    b.width = 0.12
    b.segments = 8
    b.affect = "VERTICES"
    sol = plate.modifiers.new("solid", "SOLIDIFY")
    sol.thickness = 0.12
    plate.data.materials.append(material("slate", SLATE_DEEP, roughness=0.85))

    # Hairline grid on the plate: thin emissive strips.
    grid_mat = material("grid", BORDER, emission=BORDER, strength=1.2)
    for i in range(-3, 4):
        for axis in ("x", "y"):
            bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0, 0, -0.058))
            g = bpy.context.active_object
            g.name = f"grid_{axis}{i}"
            if axis == "x":
                g.scale = (0.004, 0.86, 1.0)
                g.location.x = i * 0.28
            else:
                g.scale = (0.86, 0.004, 1.0)
                g.location.y = i * 0.28
            g.data.materials.append(grid_mat)

    # Cursor body: ice glass with a soft emissive core.
    body_mat = material("ice", ICE, emission=ICE, strength=0.55, roughness=0.12,
                        metallic=0.15)
    cursor = extrude_polygon("cursor", cursor_points(cursor_scale), depth=0.14, bevel=0.018)
    cursor.data.materials.append(body_mat)
    cursor.location = (-0.30 * cursor_scale / 0.82, 0.42 * cursor_scale / 0.82, 0.0)
    cursor.rotation_euler = (0, 0, 0)

    # Ghost trail: three fading copies offset back along the travel line.
    ghosts = []
    for k in range(1, 4):
        gm = material(f"ghost{k}", ICE, emission=ICE, strength=0.5 / k,
                      roughness=0.3, alpha=0.30 / k)
        g = extrude_polygon(f"ghost{k}", cursor_points(cursor_scale), depth=0.05, bevel=0.018)
        g.data.materials.append(gm)
        g.location = (cursor.location.x + 0.10 * k, cursor.location.y - 0.10 * k, -0.02 * k)
        ghosts.append(g)

    # Corner brackets, ice, sitting a little above the plate.
    br_mat = material("bracket", ICE, emission=ICE, strength=1.1, roughness=0.2)
    brackets = []
    arm, thick = 0.26, 0.035
    for (sx, sy) in ((-1, 1), (1, 1), (-1, -1), (1, -1)):
        pts_h = [(0, 0), (arm, 0), (arm, thick), (0, thick)]
        pts_v = [(0, 0), (thick, 0), (thick, arm), (0, arm)]
        h = extrude_polygon(f"br_h_{sx}_{sy}", pts_h, depth=0.05)
        v = extrude_polygon(f"br_v_{sx}_{sy}", pts_v, depth=0.05)
        for o in (h, v):
            o.data.materials.append(br_mat)
            o.scale = (sx, sy, 1.0)
            o.location = (sx * 0.78, sy * 0.78, 0.02)
        brackets.append((h, v, sx, sy))

    # Camera: orthographic, looking down with a slight tilt for depth.
    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ortho
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = (0.0, -0.9, 3.2)
    cam.rotation_euler = (math.radians(15), 0, 0)
    scene.camera = cam

    # Key light and a cool fill.
    bpy.ops.object.light_add(type="AREA", location=(1.6, -1.2, 2.6))
    key = bpy.context.active_object
    key.data.energy = 140
    key.data.size = 2.5
    key.rotation_euler = (math.radians(35), math.radians(20), 0)
    bpy.ops.object.light_add(type="AREA", location=(-2.0, 1.4, 2.0))
    fill = bpy.context.active_object
    fill.data.energy = 50
    fill.data.size = 3.0
    fill.data.color = (0.6, 0.8, 1.0)

    if anim:
        animate(cursor, ghosts, brackets)
    return scene, cursor


def ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def animate(cursor, ghosts, brackets) -> None:
    """Cursor sweeps in from the lower right and settles; the ghosts lag
    behind it; the brackets start wide and lock in around frame 34; a
    final soft pulse on the brackets says 'armed'."""
    end = (-0.30, 0.42, 0.0)
    start = (1.25, -1.15, 0.0)
    settle = 30
    for f in range(FRAMES):
        t = ease_out(min(1.0, f / settle))
        pos = tuple(s + (e - s) * t for s, e in zip(start, end))
        cursor.location = pos
        cursor.keyframe_insert("location", frame=f)
        for k, g in enumerate(ghosts, start=1):
            lag = ease_out(min(1.0, max(0.0, (f - 2 * k) / settle)))
            gp = tuple(s + (e - s) * lag for s, e in zip(start, end))
            g.location = (gp[0] + 0.04 * k, gp[1] - 0.04 * k, -0.02 * k)
            g.keyframe_insert("location", frame=f)
            # Ghosts fade out once the cursor has settled.
            fade = 1.0 if f < settle else max(0.0, 1.0 - (f - settle) / 10.0)
            mat = g.data.materials[0]
            p = mat.node_tree.nodes.get("Principled BSDF")
            p.inputs["Alpha"].default_value = (0.32 / k) * fade
            p.inputs["Alpha"].keyframe_insert("default_value", frame=f)
        # Brackets: from 1.35 out to 0.78, locking between frames 18 and 36.
        bt = ease_out(min(1.0, max(0.0, (f - 18) / 18)))
        off = 1.35 + (0.78 - 1.35) * bt
        for h, v, sx, sy in brackets:
            for o in (h, v):
                o.location = (sx * off, sy * off, 0.02)
                o.keyframe_insert("location", frame=f)
                mat = o.data.materials[0]
                p = mat.node_tree.nodes.get("Principled BSDF")
                pulse = 1.1 + (1.2 if 36 <= f <= 40 else 0.0)
                p.inputs["Emission Strength"].default_value = pulse
                p.inputs["Emission Strength"].keyframe_insert("default_value", frame=f)


def render_still(scene) -> None:
    size = 512 if QUICK else 1024
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.frame_set(FRAMES - 1)
    scene.render.filepath = str(OUT / "mark_1024.png")
    bpy.ops.render.render(write_still=True)
    print("wrote", scene.render.filepath)


def render_anim(scene) -> None:
    (OUT / "boot").mkdir(exist_ok=True)
    # Square, wide enough that the brackets' start position (1.35) is in
    # frame; make_boot.py places it on the 2:1 splash ground.
    scene.render.resolution_x = 240 if QUICK else 480
    scene.render.resolution_y = 240 if QUICK else 480
    scene.render.resolution_percentage = 100
    scene.camera.data.ortho_scale = 3.1
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(OUT / "boot" / "frame_")
    bpy.ops.render.render(animation=True)
    print("wrote", FRAMES, "frames to", OUT / "boot")


if __name__ == "__main__":
    if DO_STILL:
        # Icon variant: bigger cursor, tighter crop, so it still reads at 32 px.
        scene, _ = build(anim=False, cursor_scale=1.0, ortho=2.15)
        render_still(scene)
    if DO_ANIM:
        scene, _ = build(anim=True)
        render_anim(scene)
