"""Build a demo scene for EzDepthHaze lit by a real HDRI: the procedural mountains of
DemoTerrain.blink under the HDRI's own sky and sun.

Run from a terminal (needs EzAtmosScatter and EzDepthHaze on the plugin path):

    Nuke15.1.exe --nukex -i --gpu -t examples/build_hdri_demo.py <hdri.exr> <output folder> [look]

It finds the sun in the HDRI with EzAtmosScatter, turns the camera towards it (the sun a
little left of centre, so glow and shafts show), renders the terrain once to
<output folder>/hdri_demo_terrain.exr and saves <output folder>/ezdepthhaze_hdri_demo.nk with
the look (Golden Hour by default) applied and fitted. Tested with Poly Haven's Ticknock 02
(CC0, https://polyhaven.com/a/ticknock_02), a clear sunset.
"""

import base64
import math
import os
import sys

import nuke

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HDRI = sys.argv[1].replace("\\", "/")
OUT = (sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "examples", "hdri_demo")).replace("\\", "/")
LOOK = sys.argv[3] if len(sys.argv) > 3 else "Golden Hour"
CAMERA_HEIGHT = 4300.0
SUN_LEFT = 15.0


def note(text, x, y):
    n = nuke.nodes.StickyNote(label=text, note_font_size=18)
    n.setXYpos(x, y)
    return n


def build():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    root = nuke.root()
    root.begin()
    nuke.addFormat("1920 1080 1 HD_1080")
    root["format"].setValue("HD_1080")
    for knob in ("int8Lut", "int16Lut", "monitorLut"):
        root[knob].setValue("sRGB")

    # Make the gizmos before their inputs: a node that gets an input it didn't have when it
    # was made can keep its no-input fallback in a terminal session.
    atmos = nuke.nodes.EzAtmosScatter(name="Atmos")
    atmos.setXYpos(0, 0)
    hdri = nuke.nodes.Read(name="HDRI", file=HDRI, xpos=0, ypos=-150)
    atmos.setInput(0, hdri)
    atmos["passes"].setValue("Depth Haze")
    atmos["camera_height"].setValue(CAMERA_HEIGHT)
    atmos["view_output"].setValue("Scatter")
    sun = list(atmos["sun_in_use"].value())
    ln = math.sqrt(sum(x * x for x in sun)) or 1.0
    sun = [x / ln for x in sun]
    sun_az = math.degrees(math.atan2(sun[0], -sun[2]))
    sun_el = math.degrees(math.asin(max(-1.0, min(1.0, sun[1]))))

    cam = nuke.nodes.Camera3(name="DemoCamera", xpos=600, ypos=0)
    cam["translate"].setValue([0, CAMERA_HEIGHT, 0])
    # Nuke's Y rotation turns the view from -Z towards -X, the sun's azimuth is from -Z towards
    # +X: turn the camera onto the sun, then a little past it so it sits left of centre.
    cam["rotate"].setValue([-9, -(sun_az + SUN_LEFT), 0])
    cam["focal"].setValue(35)
    cam["haperture"].setValue(36)
    cam["vaperture"].setValue(20.25)
    atmos.setInput(3, cam)

    ref = nuke.nodes.Constant(name="Frame", format="HD_1080", xpos=300, ypos=-200)
    terrain = nuke.nodes.BlinkScript(name="DemoTerrain", xpos=300, ypos=-100)
    terrain.setInput(0, ref)
    terrain.setInput(1, hdri)
    terrain["kernelSourceFile"].setValue(os.path.join(ROOT, "examples", "DemoTerrain.blink").replace("\\", "/"))
    terrain["reloadKernelSourceFile"].execute()
    terrain["recompile"].execute()
    k = "DemoTerrain_"
    for row in range(3):
        for col in range(3):
            terrain[k + "cam_row%d" % row].setExpression("DemoCamera.world_matrix.%d" % (row * 4 + col), col)
    for i in range(3):
        terrain[k + "cam_position"].setExpression("DemoCamera.world_matrix.%d" % (3 + 4 * i), i)
    for knob in ("focal", "haperture", "vaperture"):
        terrain[k + knob].setExpression("DemoCamera." + knob)
    for i in range(3):
        terrain[k + "sun_direction"].setExpression("Atmos.sun_in_use.%s" % "xyz"[i], i)
    terrain[k + "sun_color"].setValue([1.0, 0.72, 0.5])
    terrain[k + "terrain_height"].setValue(2800)
    terrain[k + "terrain_scale"].setValue(4500)

    exr = OUT + "/hdri_demo_terrain.exr"
    write = nuke.nodes.Write(name="WriteTerrain", file=exr, file_type="exr", channels="rgba", xpos=300, ypos=0)
    write["datatype"].setValue("32 bit float")
    write.setInput(0, terrain)
    nuke.execute(write, 1, 1)

    haze = nuke.nodes.EzDepthHaze(name="EzDepthHaze1")
    haze.setXYpos(300, 340)
    plate = nuke.nodes.Read(name="TerrainRender", file=exr, xpos=300, ypos=100)
    with_depth = nuke.nodes.Copy(name="DistanceToDepth", from0="rgba.alpha", to0="depth.Z", xpos=300, ypos=180)
    with_depth.setInput(0, plate)
    with_depth.setInput(1, plate)
    solid = nuke.nodes.Expression(name="SolidAlpha", expr3="depth.Z > 0 ? 1 : 0", xpos=300, ypos=240)
    solid.setInput(0, with_depth)
    haze.setInput(0, solid)
    haze.setInput(1, cam)
    haze.setInput(2, atmos)

    # Analyze, then the look fitted to the shot, as an artist would from the panel.
    tools = {}
    exec(base64.b64decode(haze["tool_code"].value()).decode(), tools)
    nuke.message = lambda *a: None
    nuke.ask = lambda *a: False
    tools["analyze"](haze)
    haze["preset"].setValue(LOOK)
    tools["apply_look"](haze)

    viewer = nuke.nodes.Viewer(xpos=300, ypos=460)
    viewer.setInput(0, haze)
    viewer.setInput(1, solid)
    note("HDRI: %s\nAtmos finds its sun (%.1f deg up) and lights the haze." % (os.path.basename(HDRI), sun_el), -260, -120)
    note("DemoCamera looks towards the HDRI's sun.\nDemoTerrain renders mountains under the HDRI sky;\nWriteTerrain re-renders them.", 520, -120)
    note("EzDepthHaze: %s, fitted to the shot.\nViewer: 1 = hazed, 2 = raw render." % LOOK, 520, 330)

    path = OUT + "/ezdepthhaze_hdri_demo.nk"
    nuke.scriptSaveAs(path, overwrite=1)
    print("sun %.1f deg up, %.1f deg round; camera turned %.1f" % (sun_el, sun_az, -(sun_az + SUN_LEFT)))
    return path, haze


if __name__ == "__main__":
    path, haze = build()
    haze["viewer_resolution"].setValue("Full")
    preview = nuke.nodes.Write(file=OUT + "/ezdepthhaze_hdri_demo_preview.jpg", file_type="jpeg", channels="rgb")
    preview["colorspace"].setValue("sRGB")
    preview.setInput(0, haze)
    nuke.execute(preview, 1, 1)
    print("wrote", path)
