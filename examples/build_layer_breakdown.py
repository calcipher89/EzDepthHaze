"""Build a layer breakdown next to the EzDepthHaze demo, rebuilding its result from its
layers so artists can see how the output is assembled.

Build the demo first (examples/build_demo.py), then run:

    Nuke15.1.exe --nukex -i --gpu -t examples/build_layer_breakdown.py <demo folder>

It opens <demo folder>/ezdepthhaze_demo.nk, adds the breakdown and saves
<demo folder>/ezdepthhaze_layer_breakdown.nk, then checks the rebuild against the node.
"""

import os
import sys

import nuke

D = (sys.argv[1] if len(sys.argv) > 1 else "examples/demo").replace("\\", "/")
nuke.scriptOpen(D + "/ezdepthhaze_demo.nk")
haze = nuke.toNode("EzDepthHaze1")
plate = nuke.toNode("SolidAlpha")
X, Y = haze.xpos() + 700, haze.ypos()


def at(node, x, y):
    node.setXYpos(X + x, Y + y)
    return node


def pull(layer, x, y):
    s = nuke.nodes.Shuffle2(name="Get_" + layer, label=layer)
    s["in1"].setValue(layer)
    s.setInput(0, haze)
    return at(s, x, y)


def merge(name, op, b, a, x, y):
    m = nuke.nodes.Merge2(name=name, operation=op, output="rgb")
    m.setInput(0, b)
    m.setInput(1, a)
    return at(m, x, y)


def note(text, x, y, size=18):
    n = nuke.nodes.StickyNote(label=text, note_font_size=size)
    return at(n, x, y)


def backdrop(label, x, y, w, h, color):
    b = nuke.nodes.BackdropNode(label="<center>" + label, note_font_size=28, tile_color=color, bdwidth=w, bdheight=h)
    return at(b, x, y)


T = pull("haze_transmittance", 0, 120)
sun = pull("haze_sun", 150, 120)
sky = pull("haze_sky", 300, 120)
surface = pull("surface_sunlight", 450, 120)
shadow = pull("haze_shadow", 600, 120)
fog = pull("haze_fog", 750, 120)
wisps = pull("haze_wisps", 900, 120)

# 1. Surface light on the plate (only when 'add surface light' is on).
add = at(nuke.nodes.Multiply(name="SurfaceAddSwitch", channels="rgb"), 450, 200)
add["value"].setExpression("EzDepthHaze1.surface_add")
add.setInput(0, surface)
lit = merge("Plate_plus_Surface", "plus", plate, add, -150, 260)
# 2. Dim it by what survives the haze.
dimmed = merge("Times_Transmittance", "multiply", lit, T, -150, 340)
# 3. Add the sunlit and the sky-lit haze.
plus_sun = merge("Plus_HazeSun", "plus", dimmed, sun, -150, 420)
result = merge("Plus_HazeSky", "plus", plus_sun, sky, -150, 500)
dot = at(nuke.nodes.Dot(name="Rebuilt_EzDepthHaze", label="rebuilt EzDepthHaze result"), -116, 600)
dot.setInput(0, result)
check = merge("Check_Difference", "difference", haze, dot, 150, 640)

# Extra layers for look development.
unshadowed = merge("Sun_without_Shadows", "plus", sun, shadow, 600, 260)
look_fog = at(nuke.nodes.Grade(name="Example_FogGrade", channels="rgb", white=1.0, label="grade the fog alone"), 750, 260)
look_fog.setInput(0, fog)
look_wisps = at(nuke.nodes.Expression(name="Example_WispsMask", expr0="clamp(r * 4 + 0.5)", expr1="clamp(g * 4 + 0.5)",
                                      expr2="clamp(b * 4 + 0.5)", label="wisps as a 0-1 mask"), 900, 260)
look_wisps.setInput(0, wisps)

viewer = at(nuke.nodes.Viewer(name="BreakdownViewer"), -150, 760)
viewer.setInput(0, dot)
viewer.setInput(1, haze)
viewer.setInput(2, check)
viewer.setInput(3, unshadowed)

backdrop("Pull each pass out of its layer", -40, 60, 1100, 120, 0x3a4a5aff)
backdrop("1  plate + surface light (if added)", -200, 190, 760, 120, 0x4a5a3aff)
backdrop("2  x haze_transmittance", -200, 320, 360, 70, 0x5a4a3aff)
backdrop("3  + haze_sun + haze_sky", -200, 400, 360, 150, 0x5a3a4aff)
backdrop("4  check against EzDepthHaze", -200, 580, 520, 120, 0x3a3a3aff)
backdrop("Look development layers", 560, 190, 520, 140, 0x2a4a4aff)

note("EzDepthHaze result =\n  (plate + surface_sunlight * add) * haze_transmittance\n+ haze_sun   (sunlit haze, with shadows)\n+ haze_sky   (sky-lit haze)\n\n"
     "haze_inscatter = haze_sun + haze_sky\nhaze_sun + haze_shadow = the sunlit haze with no shadows", 1150, 120)
note("haze_shadow: sunlight the shadowed air lost. Add some back\nfor softer shadows, or grade haze_sun and haze_sky apart\nto push warm shafts against cool shadows.", 1150, 330, 16)
note("haze_fog: the fog layer's share of the in-scatter.\nhaze_wisps: how much the noise changed the density (signed).\nP / N: world position and normals rebuilt from depth.", 1150, 430, 16)
note("Viewer: 1 = rebuilt, 2 = EzDepthHaze, 3 = difference (black),\n4 = sunlit haze without shadows.", -200, 830, 16)

path = D + "/ezdepthhaze_layer_breakdown.nk"
nuke.scriptSaveAs(path, overwrite=1)

# Verify the rebuild against the node.
for name, node in (("rebuilt", dot), ("node", haze)):
    w = nuke.nodes.Write(file="%s/_check_%s.exr" % (D, name), file_type="exr")
    w.setInput(0, node)
    nuke.execute(w, 1, 1)
    nuke.delete(w)
a = nuke.nodes.Read(file=D + "/_check_rebuilt.exr")
b = nuke.nodes.Read(file=D + "/_check_node.exr")
worst = 0.0
for x in range(10, 1920, 61):
    for y in range(5, 1080, 37):
        for c in ("red", "green", "blue"):
            worst = max(worst, abs(a.sample(c, x, y) - b.sample(c, x, y)))
nuke.delete(a)
nuke.delete(b)
for name in ("rebuilt", "node"):
    try:
        os.remove("%s/_check_%s.exr" % (D, name))
    except OSError:
        pass  # still held open by Nuke; harmless
print("max difference from EzDepthHaze:", worst)
print("wrote", path)
