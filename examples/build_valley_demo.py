"""Build an overcast valley demo for EzDepthHaze: a glacial valley (ValleyTerrain.blink) under an
HDRI sky, with a sun above the cloud breaking through gaps in it as beams of light.

Run from a terminal (needs EzAtmosScatter and EzDepthHaze on the plugin path):

    Nuke15.1.exe --nukex -i --gpu -t examples/build_valley_demo.py <hdri.exr> <output folder>

The HDRI gives the sky and its light; the sun is set by hand (high and in front of the camera),
since beams through cloud gaps need a sun well above the horizon. The terrain is rendered once,
lit mostly by the sky (it is overcast); EzDepthHaze adds the sunlight that gets through the
gaps, on the haze and on the ground. Tested with Poly Haven's Kloppenheim 06 (CC0,
https://polyhaven.com/a/kloppenheim_06).
"""

import base64
import math
import os
import sys

import nuke

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HDRI = sys.argv[1].replace("\\", "/")
OUT = (sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "examples", "valley_demo")).replace("\\", "/")
LOOK = sys.argv[3] if len(sys.argv) > 3 else None
CAMERA = [1000.0, 1350.0, 1500.0]
# Sun: degrees up, and degrees left of where the camera looks.
SUN_UP, SUN_LEFT = 40.0, 15.0


def build():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    root = nuke.root()
    root.begin()
    nuke.addFormat("1920 1080 1 HD_1080")
    root["format"].setValue("HD_1080")

    # Gizmos first, inputs after (see build_hdri_demo.py).
    atmos = nuke.nodes.EzAtmosScatter(name="Atmos")
    haze = nuke.nodes.EzDepthHaze(name="EzDepthHaze1")
    hdri = nuke.nodes.Read(name="HDRI", file=HDRI, xpos=0, ypos=-150)
    atmos.setInput(0, hdri)

    cam = nuke.nodes.Camera3(name="ValleyCamera", xpos=600, ypos=0)
    cam["translate"].setValue(CAMERA)
    cam["rotate"].setValue([-13, 24, 0])
    cam["focal"].setValue(24)
    cam["haperture"].setValue(36)
    cam["vaperture"].setValue(20.25)
    atmos.setInput(3, cam)

    # The camera looks 24 deg round towards -X; the sun sits a little left of that.
    az = math.radians(-24.0 - SUN_LEFT)
    up = math.radians(SUN_UP)
    sun = [math.sin(az) * math.cos(up), math.sin(up), -math.cos(az) * math.cos(up)]
    atmos["sun_from"].setValue("Manual")
    atmos["sun_direction"].setValue(sun)
    atmos["light_from_hdri"].setValue(False)
    atmos["sun_color"].setValue([1.0, 0.86, 0.68])
    atmos["sun_strength"].setValue(1.0)
    atmos["passes"].setValue("Depth Haze")
    atmos["camera_height"].setValue(CAMERA[1])
    atmos["view_output"].setValue("Scatter")

    ref = nuke.nodes.Constant(name="Frame", format="HD_1080", xpos=300, ypos=-200)
    terrain = nuke.nodes.BlinkScript(name="ValleyTerrain", xpos=300, ypos=-100)
    terrain.setInput(0, ref)
    # Under cloud the sky light is grey: the terrain takes a desaturated copy of the HDRI.
    overcast = nuke.nodes.Saturation(name="OvercastSky", saturation=0.25, xpos=150, ypos=-150)
    overcast.setInput(0, hdri)
    terrain.setInput(1, overcast)
    terrain["kernelSourceFile"].setValue(os.path.join(ROOT, "examples", "ValleyTerrain.blink").replace("\\", "/"))
    terrain["reloadKernelSourceFile"].execute()
    terrain["recompile"].execute()
    k = "ValleyTerrain_"
    for row in range(3):
        for col in range(3):
            terrain[k + "cam_row%d" % row].setExpression("ValleyCamera.world_matrix.%d" % (row * 4 + col), col)
    for i in range(3):
        terrain[k + "cam_position"].setExpression("ValleyCamera.world_matrix.%d" % (3 + 4 * i), i)
        terrain[k + "sun_direction"].setExpression("Atmos.sun_direction.%s" % "xyz"[i], i)
    for knob in ("focal", "haperture", "vaperture"):
        terrain[k + knob].setExpression("ValleyCamera." + knob)
    # Overcast: the terrain is lit by the sky; the sun through the gaps comes from EzDepthHaze.
    # The camera stands on the valley's edge; the kernel puts a granite outcrop in front of it.
    for knob, value in (("sun_intensity", 0.0), ("ambient_strength", 0.9)):
        terrain[k + knob].setValue(value)

    exr = OUT + "/valley_terrain.exr"
    write = nuke.nodes.Write(name="WriteTerrain", file=exr, file_type="exr", channels="rgba", xpos=300, ypos=0)
    write["datatype"].setValue("32 bit float")
    write.setInput(0, terrain)
    nuke.execute(write, 1, 1)

    plate = nuke.nodes.Read(name="TerrainRender", file=exr, xpos=300, ypos=100)
    with_depth = nuke.nodes.Copy(name="DistanceToDepth", from0="rgba.alpha", to0="depth.Z", xpos=300, ypos=180)
    with_depth.setInput(0, plate)
    with_depth.setInput(1, plate)
    solid = nuke.nodes.Expression(name="SolidAlpha", expr3="depth.Z > 0 ? 1 : 0", xpos=300, ypos=240)
    solid.setInput(0, with_depth)
    haze.setXYpos(300, 340)
    haze.setInput(0, solid)
    haze.setInput(1, cam)
    haze.setInput(2, atmos)
    # The HDRI's own clouds cast the beams: applying the look sets them up from it.
    haze.setInput(3, hdri)

    tools = {}
    exec(base64.b64decode(haze["tool_code"].value()).decode(), tools)
    nuke.message = lambda *a: None
    nuke.ask = lambda *a: False
    tools["analyze"](haze)
    if LOOK:
        haze["preset"].setValue(LOOK)
        tools["apply_look"](haze)
    else:
        # Overcast with shafts, set by hand: thick volumetric haze lit mostly by the sky, the
        # sun only through gaps in a cloud layer above the rim.
        for name, value in (("haze_mode", 1), ("steps", 2), ("haze_amount", 1.6), ("sun_scatter", 2.5),
                            ("sky_scatter", 1.0), ("shadow_strength", 1.0), ("shadow_quality", 2),
                            ("cloud_cover", 0.78), ("cloud_height", CAMERA[1] + 1500.0), ("cloud_size", 900.0),
                            ("cloud_softness", 0.12), ("noise_amount", 0.3), ("noise_size", 1500.0),
                            ("surface_add", True), ("surface_strength", 1.5), ("albedo_from", 0),
                            ("fog_density", 0.0)):
            haze[name].setValue(value)
        tools["rebase"](haze)

    viewer = nuke.nodes.Viewer(xpos=300, ypos=460)
    viewer.setInput(0, haze)
    viewer.setInput(1, solid)
    path = OUT + "/ezdepthhaze_valley_demo.nk"
    nuke.scriptSaveAs(path, overwrite=1)
    return path, haze


if __name__ == "__main__":
    path, haze = build()
    haze["viewer_resolution"].setValue("Full")
    grade = nuke.nodes.Grade(white=0.5)
    grade.setInput(0, haze)
    preview = nuke.nodes.Write(file=OUT + "/ezdepthhaze_valley_demo_preview.jpg", file_type="jpeg", channels="rgb")
    preview["colorspace"].setValue("sRGB")
    preview.setInput(0, grade)
    nuke.execute(preview, 1, 1)
    print("wrote", path)
