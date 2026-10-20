"""Build a demo scene for EzDepthHaze: a backlit range of mountains at sunset.

Run from a terminal (needs EzAtmosScatter and EzDepthHaze on the plugin path):

    Nuke15.1.exe --nukex -i --gpu -t examples/build_demo.py <output folder>

It renders the procedural terrain (examples/DemoTerrain.blink) once to
<output folder>/demo_terrain.exr, so the saved script opens quickly, and saves
<output folder>/ezdepthhaze_demo.nk with:

    Sky       EzAtmosScatter with a low manual sun, its Scatter used as the sky
    Atmos     EzAtmosScatter lit by that sky; its atmos_haze_color lights the haze
    Terrain   the DemoTerrain kernel (for re-rendering), and a Read of its EXR
    EzDepthHaze  Volumetric haze, valley fog, noise and light shafts

Viewer input 1 is the hazed result, 2 the raw terrain render.
"""

import os
import sys

import nuke

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = (sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "examples", "demo")).replace("\\", "/")

SUN = [-0.35, 0.045, -1.0]
SUN_COLOR = [1.0, 0.72, 0.5]
CAMERA_HEIGHT = 4300.0


def atmos(name, source, x, y, haze_amount):
    g = nuke.createNode("EzAtmosScatter", inpanel=False)
    g.setName(name)
    g.setInput(0, source)
    g.setXYpos(x, y)
    g["sun_from"].setValue("Manual")
    g["sun_direction"].setValue(SUN)
    g["light_from_hdri"].setValue(False)
    g["sun_color"].setValue(SUN_COLOR)
    g["sun_strength"].setValue(0.35)
    g["camera_height"].setValue(CAMERA_HEIGHT)
    g["haze_amount"].setValue(haze_amount)
    g["haze_height"].setValue(2.0)
    g["view_output"].setValue("Scatter")
    return g


def note(text, x, y):
    n = nuke.nodes.StickyNote(label=text, note_font_size=18)
    n.setXYpos(x, y)
    return n


def build():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    root = nuke.root()
    nuke.addFormat("1920 1080 1 HD_1080")
    nuke.addFormat("2048 1024 1 latlong_2k")
    root["format"].setValue("HD_1080")
    for knob in ("int8Lut", "int16Lut", "monitorLut"):
        root[knob].setValue("sRGB")

    cam = nuke.nodes.Camera3(name="DemoCamera", xpos=600, ypos=0)
    cam["translate"].setValue([0, CAMERA_HEIGHT, 0])
    cam["rotate"].setValue([-9, 0, 0])
    cam["focal"].setValue(35)
    cam["haperture"].setValue(36)
    cam["vaperture"].setValue(20.25)

    black = nuke.nodes.Constant(name="NoHDRI", format="latlong_2k", color=0, xpos=0, ypos=-200)
    sky = atmos("Sky", black, 0, -100, 3.0)
    lit = atmos("Atmos", sky, 0, 0, 1.0)

    ref = nuke.nodes.Constant(name="Frame", format="HD_1080", xpos=300, ypos=-200)
    terrain = nuke.nodes.BlinkScript(name="DemoTerrain", xpos=300, ypos=-100)
    terrain.setInput(0, ref)
    terrain.setInput(1, sky)
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
        terrain[k + "sun_direction"].setExpression("Sky.sun_direction.%s" % "xyz"[i], i)
    terrain[k + "sun_color"].setValue(SUN_COLOR)
    terrain[k + "terrain_height"].setValue(2800)
    terrain[k + "terrain_scale"].setValue(4500)

    exr = OUT + "/demo_terrain.exr"
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

    haze = nuke.createNode("EzDepthHaze", inpanel=False)
    haze.setXYpos(300, 340)
    haze.setInput(0, solid)
    haze.setInput(1, cam)
    haze.setInput(2, lit)
    for name, value in [("haze_amount", 3.0), ("sky_handling", 1), ("sky_distance", 250.0), ("haze_mode", 1),
                        ("steps", 2), ("fog_density", 1.0), ("fog_top", 1800.0), ("fog_softness", 600.0),
                        ("noise_amount", 0.8), ("noise_size", 3000.0), ("shaft_amount", 1.0),
                        ("shaft_length", 0.8), ("shaft_falloff", 1.0)]:
        haze[name].setValue(value)

    viewer = nuke.nodes.Viewer(xpos=300, ypos=460)
    viewer.setInput(0, haze)
    viewer.setInput(1, solid)

    note("Sky: EzAtmosScatter with a low manual sun.\nIts Scatter view is the sky the terrain is\nrendered against.", -260, -120)
    note("Atmos: EzAtmosScatter lit by that sky.\nEzDepthHaze reads its atmos_haze_color layer\nand inherits its haze density, height and sun.", -260, 0)
    note("DemoTerrain renders procedural mountains through\nDemoCamera, distance in alpha. WriteTerrain\nre-renders demo_terrain.exr if you change them.", 520, -120)
    note("EzDepthHaze: Volumetric haze, valley fog below\n1800 m broken up by noise, and light shafts.\nViewer: 1 = hazed, 2 = raw render.", 520, 330)

    path = OUT + "/ezdepthhaze_demo.nk"
    nuke.scriptSaveAs(path, overwrite=1)
    return path, haze


if __name__ == "__main__":
    path, haze = build()
    preview = nuke.nodes.Write(file=OUT + "/ezdepthhaze_demo_preview.png", file_type="png", channels="rgb")
    preview["colorspace"].setValue("sRGB")
    preview.setInput(0, haze)
    nuke.execute(preview, 1, 1)
    print("wrote", path)
