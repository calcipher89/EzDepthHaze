"""Build gizmos/EzDepthHaze.gizmo from the kernel in blink/.

Run from a terminal (NukeX licence, -i so BlinkScript can compile):

    Nuke15.1.exe --nukex -i -t python/build_gizmo.py

The group has three inputs: the plate (with depth in a channel), an optional Camera,
and an optional lat-long `atmos` input, normally an EzAtmosScatter node, whose
atmos_haze_color layer lights the haze and whose haze settings can be inherited.
"""

import os

import nuke

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLINK = os.path.join(ROOT, "blink")
GIZMO_PATH = os.path.join(ROOT, "gizmos", "EzDepthHaze.gizmo")

LAYERS = ["haze_transmittance", "haze_inscatter"]
VIEW_OUTPUTS = ["Hazed Plate", "Haze Transmittance", "Haze In-scatter"]

# Expressions that read the camera input, or fall back to an identity camera.
CAM = "[exists parent.input1] ? parent.input1.%s : %s"
# Expressions that read a setting from the atmos input when 'inherit from atmos' is on.
ATMOS = "parent.inherit_atmos && [exists parent.input2.%s] ? parent.input2.%s : %s"


def _load_kernel(node, filename):
    # Setting kernelSource from Python does not rebuild the parameter knobs; loading the
    # file does. Clear the path afterwards so the gizmo carries its own copy of the source.
    node["kernelSourceFile"].setValue(os.path.join(BLINK, filename).replace("\\", "/"))
    node["reloadKernelSourceFile"].execute()
    node["recompile"].execute()
    node["kernelSourceFile"].setValue("")


def _link(node, param, expression, channel=None):
    knob = node["%s_%s" % (node["kernelName"].value(), param)]
    if channel is None:
        knob.setExpression(expression)
    else:
        knob.setExpression(expression, channel)


def _double(name, label, lo, hi, tip, value):
    knob = nuke.Double_Knob(name, label)
    knob.setRange(lo, hi)
    knob.setTooltip(tip)
    return knob, value


def _add_knobs(group, depth_pick, env_pick):
    k = []
    defaults = {}

    def add(knob, value=None):
        k.append(knob)
        if value is not None:
            defaults[knob.name()] = value

    add(nuke.Tab_Knob("ezdepthhaze", "EzDepthHaze"))
    view = nuke.Enumeration_Knob("view_output", "view output", VIEW_OUTPUTS)
    view.setTooltip("What the main rgb shows. The transmittance and in-scatter are also written to the "
                    "haze_transmittance and haze_inscatter layers.")
    add(view)

    add(nuke.Text_Knob("plate_divider", "Plate"))
    plate_type = nuke.Enumeration_Knob("plate_type", "plate", ["Camera", "Lat-long"])
    plate_type.setTooltip("Camera: a perspective render or plate, with its Camera plugged into the 'camera' "
                          "input. Lat-long: a 360 lat-long render, such as an environment of the mountains.")
    add(plate_type)
    depth_channel = nuke.Link_Knob("depth_channel", "depth channel")
    depth_channel.makeLink(depth_pick.name(), "from0")
    depth_channel.setTooltip("Channel holding the depth.")
    add(depth_channel)
    depth_type = nuke.Enumeration_Knob("depth_type", "depth type", ["Distance", "Planar Z", "1/Z"])
    depth_type.setTooltip("Distance: distance from the camera (most path tracers' 'distance' AOV). Planar Z: "
                          "depth along the camera's view axis (Arnold/V-Ray Z). 1/Z: Nuke's ScanlineRender.")
    add(depth_type)
    add(*_double("depth_scale", "units to metres", 0.001, 100,
                 "Multiplies depth to get metres, e.g. 0.01 for centimetres.", 1.0))
    add(*_double("latlong_camera_height", "camera height (m)", 0, 5000,
                 "Camera height above sea level for lat-long plates. Camera plates use the camera's height.", 1.0))
    sky = nuke.Enumeration_Knob("sky_handling", "sky", ["Leave Sky", "Haze Sky"])
    sky.setTooltip("Pixels with no depth (or beyond 'sky depth') are sky. Leave Sky keeps them as they are; "
                   "Haze Sky hazes them as if they were 'sky distance' away.")
    add(sky)
    add(*_double("sky_distance", "sky distance (km)", 0, 200, "Distance used for sky pixels with Haze Sky.", 50.0))
    add(*_double("sky_threshold", "sky depth", 0, 1e7,
                 "Depth (in the plate's units) at or beyond which a pixel counts as sky.", 1e7))

    add(nuke.Text_Knob("haze_divider", "Haze"))
    inherit = nuke.Boolean_Knob("inherit_atmos", "inherit from atmos")
    inherit.setTooltip("With an EzAtmosScatter node in the 'atmos' input, take its haze density, haze height "
                       "and hdri rotation, so the haze matches its sky.")
    inherit.setFlag(nuke.STARTLINE)
    add(inherit, True)
    color_from = nuke.Enumeration_Knob("haze_color_from", "haze color from", ["Atmos Input", "Color"])
    color_from.setTooltip("Atmos Input: the colour comes from the lat-long in the 'atmos' input, looked up in "
                          "each pixel's view direction, so the sun side glows. Color: one flat colour.")
    add(color_from)
    match = nuke.Boolean_Knob("match_horizon", "match horizon sky")
    match.setTooltip("With an EzAtmosScatter atmos input, haze far away takes the light of that atmosphere's "
                     "own sky (its atmos_inscatter over 1 - atmos_transmittance) instead of the light at "
                     "camera height. At sunset the air far away gets dimmer, redder sunlight, so without "
                     "this distant terrain fades to a haze brighter than the sky behind it.")
    match.setFlag(nuke.STARTLINE)
    add(match, True)
    add(*_double("match_distance", "match distance (km)", 1, 200, "Distance over which the haze light "
                 "changes from the camera's to the horizon sky's.", 20.0))
    env_layer = nuke.Link_Knob("atmos_layer", "atmos layer")
    env_layer.makeLink(env_pick.name(), "in1")
    env_layer.setTooltip("Layer of the atmos input to use: atmos_haze_color for EzAtmosScatter, rgba for a "
                         "plain lat-long.")
    add(env_layer)
    color = nuke.Color_Knob("haze_color", "haze color")
    color.setTooltip("Haze colour when 'haze color from' is Color, or no atmos input is connected.")
    add(color, [0.6, 0.65, 0.75])
    add(*_double("haze_color_gain", "haze brightness", 0, 4, "Multiplies the haze colour.", 1.0))
    density = nuke.Color_Knob("haze_density", "haze density (1/m)")
    density.setTooltip("How much the haze dims light per metre at camera height. Ignored when inheriting.")
    add(density, [0.0001, 0.0001, 0.0001])
    add(*_double("haze_amount", "haze amount", 0, 10, "Multiplies the haze density.", 1.0))
    add(*_double("haze_height", "haze height (km)", 0.05, 10,
                 "Height over which the haze thins by about two thirds. Ignored when inheriting.", 1.2))
    add(*_double("haze_start", "haze start (m)", 0, 10000, "Distance from the camera where the haze begins.", 0.0))
    add(*_double("max_distance", "max distance (km)", 0, 200, "Caps the hazed distance. 0 = no cap.", 0.0))
    add(*_double("env_rotation", "atmos rotation", -180, 180,
                 "Rotation of the atmos lat-long in degrees. Ignored when inheriting.", 0.0))

    add(nuke.Text_Knob("volume_divider", "Fog and Noise"))
    mode = nuke.Enumeration_Knob("haze_mode", "mode", ["Fast", "Volumetric"])
    mode.setTooltip("Fast: the haze alone, worked out exactly in one step. Volumetric: marches each ray so "
                    "the fog layer and noise below can change the density along it.")
    add(mode)
    quality = nuke.Enumeration_Knob("steps", "quality", ["Draft (16)", "Normal (48)", "High (96)"])
    quality.setTooltip("Samples along each ray in Volumetric mode.")
    add(quality, 1)
    add(*_double("fog_density", "fog density (1/km)", 0, 5,
                 "How thick the fog layer is. 1 dims light by about two thirds every kilometre.", 0.0))
    add(*_double("fog_top", "fog top (m)", -500, 5000, "Altitude the fog fills up to, e.g. the valley floor "
                 "plus a few hundred metres.", 1000.0))
    add(*_double("fog_softness", "fog softness (m)", 0, 2000, "How gradually the fog fades out around its top.", 300.0))
    add(*_double("noise_amount", "noise amount", 0, 1, "How much world-space noise breaks up the fog.", 0.0))
    add(*_double("noise_on_haze", "noise on haze", 0, 1, "How much of the noise also applies to the "
                 "thin haze, not only the fog.", 0.3))
    add(*_double("noise_size", "noise size (m)", 10, 20000, "Size of the largest wisps and banks.", 2000.0))
    add(*_double("noise_stretch", "noise flatten", 1, 10, "Squashes the noise vertically so it forms banks "
                 "and layers rather than blobs.", 3.0))
    detail = nuke.Int_Knob("noise_detail", "noise detail")
    detail.setTooltip("Octaves of noise: more adds finer wisps.")
    add(detail, 4)
    wind = nuke.XYZ_Knob("noise_wind", "wind (m/s)")
    wind.setTooltip("Drifts the noise over time.")
    add(wind, [5.0, 0.0, 0.0])
    add(*_double("noise_seed", "noise seed", 0, 100, "Changes the noise pattern.", 1.0))

    add(nuke.Text_Knob("shaft_divider", "Light Shafts"))
    add(*_double("shaft_amount", "shaft amount", 0, 1, "How much the haze darkens where mountains block "
                 "the sun, leaving shafts of light through the gaps. Camera plates with the sun in front.", 0.0))
    sun = nuke.XYZ_Knob("sun_direction", "sun direction")
    sun.setTooltip("Direction towards the sun, +Y up. Taken from the atmos input's sun direction when "
                   "inheriting (set its 'sun from' to Manual so the two agree).")
    add(sun, [0.0, 0.1, -1.0])
    add(*_double("shaft_length", "shaft length", 0, 1, "How far towards the sun each pixel looks, as a "
                 "fraction of the way there.", 0.6))
    add(*_double("shaft_decay", "shaft fade", 0.8, 1, "How quickly blockers further along count less. "
                 "Closer to 1 gives longer shafts.", 0.97))
    add(*_double("shaft_falloff", "shaft focus", 0.5, 16, "How tightly the shafts gather around the sun.", 2.0))
    add(*_double("clear_distance", "shaft clear distance (km)", 1, 300, "Terrain beyond this is so hazed it "
                 "casts no visible shadow.", 60.0))
    shaft_quality = nuke.Enumeration_Knob("shaft_quality", "shaft quality", ["Draft (32)", "Normal (64)", "High (128)"])
    add(shaft_quality, 1)

    for knob in k:
        group.addKnob(knob)
    for name, value in defaults.items():
        group[name].setValue(value)


def _link_haze(node, output):
    _link(node, "output", str(output))
    _link(node, "latlong_plate", "parent.plate_type")
    identity = ["1", "0", "0", "0", "1", "0", "0", "0", "1"]
    for row in range(3):
        for col in range(3):
            _link(node, "cam_row%d" % row, CAM % ("world_matrix.%d" % (row * 4 + col), identity[row * 3 + col]), col)
    for i in range(3):
        _link(node, "cam_position", CAM % ("world_matrix.%d" % (3 + 4 * i), "0"), i)
    _link(node, "focal", CAM % ("focal", "35"))
    _link(node, "haperture", CAM % ("haperture", "36"))
    _link(node, "vaperture", CAM % ("vaperture", "20.25"))
    _link(node, "latlong_camera_height", "parent.latlong_camera_height")
    _link(node, "depth_type", "parent.depth_type")
    _link(node, "depth_scale", "parent.depth_scale")
    _link(node, "sky_threshold", "parent.sky_threshold")
    _link(node, "haze_sky", "parent.sky_handling")
    _link(node, "sky_distance", "parent.sky_distance * 1000")
    _link(node, "use_env", "[exists parent.input2] && parent.haze_color_from==0")
    _link(node, "use_far", "[exists parent.input2] && parent.match_horizon")
    _link(node, "match_distance", "parent.match_distance * 1000")
    _link(node, "env_rotation", ATMOS % ("hdri_rotation", "hdri_rotation", "parent.env_rotation"))
    for i, c in enumerate("rgb"):
        _link(node, "haze_color", "parent.haze_color.%s" % c, i)
        _link(node, "haze_density", ATMOS % ("haze_density", "haze_density.%s" % c, "parent.haze_density.%s" % c), i)
    _link(node, "haze_color_gain", "parent.haze_color_gain")
    _link(node, "haze_amount", "parent.haze_amount")
    _link(node, "haze_height", "(%s) * 1000" % (ATMOS % ("haze_height", "haze_height", "parent.haze_height")))
    _link(node, "haze_start", "parent.haze_start")
    _link(node, "max_distance", "parent.max_distance * 1000")
    _link(node, "volumetric", "parent.haze_mode")
    _link(node, "march_steps", "parent.steps==0 ? 16 : parent.steps==1 ? 48 : 96")
    _link(node, "fog_density", "parent.fog_density / 1000")
    _link(node, "fog_top", "parent.fog_top")
    _link(node, "fog_softness", "parent.fog_softness")
    _link(node, "noise_amount", "parent.noise_amount")
    _link(node, "noise_on_haze", "parent.noise_on_haze")
    _link(node, "noise_size", "parent.noise_size")
    _link(node, "noise_stretch", "parent.noise_stretch")
    _link(node, "noise_detail", "parent.noise_detail")
    for i, c in enumerate("xyz"):
        _link(node, "noise_wind", "parent.noise_wind.%s" % c, i)
    _link(node, "noise_time", "frame / root.fps")
    _link(node, "noise_seed", "parent.noise_seed")
    _link(node, "shaft_amount", "parent.shaft_amount")
    _link(node, "shaft_falloff", "parent.shaft_falloff")
    for i, c in enumerate("xyz"):
        _link(node, "sun_direction", ATMOS % ("sun_direction", "sun_direction.%s" % c, "parent.sun_direction.%s" % c), i)


def _link_shafts(node):
    _link(node, "latlong_plate", "parent.plate_type")
    identity = ["1", "0", "0", "0", "1", "0", "0", "0", "1"]
    for row in range(3):
        for col in range(3):
            _link(node, "cam_row%d" % row, CAM % ("world_matrix.%d" % (row * 4 + col), identity[row * 3 + col]), col)
    _link(node, "focal", CAM % ("focal", "35"))
    _link(node, "haperture", CAM % ("haperture", "36"))
    _link(node, "vaperture", CAM % ("vaperture", "20.25"))
    for i, c in enumerate("xyz"):
        _link(node, "sun_direction", ATMOS % ("sun_direction", "sun_direction.%s" % c, "parent.sun_direction.%s" % c), i)
    _link(node, "env_rotation", ATMOS % ("hdri_rotation", "hdri_rotation", "parent.env_rotation"))
    _link(node, "sky_threshold", "parent.sky_threshold")
    _link(node, "shaft_length", "parent.shaft_length")
    _link(node, "shaft_samples", "parent.shaft_amount > 0 ? (parent.shaft_quality==0 ? 32 : parent.shaft_quality==1 ? 64 : 128) : 0")
    _link(node, "shaft_decay", "parent.shaft_decay")
    _link(node, "depth_scale", "parent.depth_scale")
    _link(node, "clear_distance", "parent.clear_distance * 1000")


def build():
    for layer in LAYERS:
        nuke.Layer(layer, ["%s.red" % layer, "%s.green" % layer, "%s.blue" % layer])

    group = nuke.nodes.Group(name="EzDepthHaze1")
    group["tile_color"].setValue(0x6a8fa5ff)

    group.begin()
    plate = nuke.nodes.Input(name="plate", xpos=0, ypos=-300)
    nuke.nodes.Input(name="camera", xpos=300, ypos=-300)
    atmos = nuke.nodes.Input(name="atmos", xpos=600, ypos=-300)

    # The depth goes to red of its own stream; the haze colour lat-long to rgb of another.
    depth_pick = nuke.nodes.Copy(name="DepthPick", from0="depth.Z", to0="rgba.red", xpos=150, ypos=-200)
    depth_pick.setInput(0, plate)
    depth_pick.setInput(1, plate)
    env_pick = nuke.nodes.Shuffle2(name="AtmosPick", xpos=600, ypos=-200)
    env_pick.setInput(0, atmos)
    env_pick["in1"].setValue("atmos_haze_color")

    # Horizon light: inscatter / (1 - transmittance) of the atmos sky, the average light along
    # each sky ray per unit of haze. Haze far away takes this light, so distant terrain fades
    # into the sky behind it instead of glowing brighter than it. Below the horizon the atmos
    # rays hit the ground, so the row just above it is held downwards; a blur keeps the
    # azimuth profile smooth.
    sky_in = nuke.nodes.Shuffle2(name="AtmosSkyScatter", xpos=750, ypos=-200)
    sky_in.setInput(0, atmos)
    sky_in["in1"].setValue("atmos_inscatter")
    sky_t = nuke.nodes.Shuffle2(name="AtmosSkyTransmittance", xpos=900, ypos=-200)
    sky_t.setInput(0, atmos)
    sky_t["in1"].setValue("atmos_transmittance")
    veil = nuke.nodes.Expression(name="AtmosSkyVeil", expr0="max(1 - r, 0.02)", expr1="max(1 - g, 0.02)",
                                 expr2="max(1 - b, 0.02)", xpos=900, ypos=-160)
    veil.setInput(0, sky_t)
    per_haze = nuke.nodes.Merge2(name="AtmosSkyPerHaze", operation="divide", output="rgb", xpos=750, ypos=-120)
    per_haze.setInput(0, veil)
    per_haze.setInput(1, sky_in)
    # Stored as a ratio to the haze colour, so below the horizon the haze keeps following the
    # sun's phase function and only takes on the horizon sky's dimming and reddening.
    safe_color = nuke.nodes.Expression(name="AtmosHazeColorSafe", expr0="max(r, 1e-5)", expr1="max(g, 1e-5)",
                                       expr2="max(b, 1e-5)", xpos=600, ypos=-160)
    safe_color.setInput(0, env_pick)
    ratio = nuke.nodes.Merge2(name="AtmosSkyRatio", operation="divide", output="rgb", xpos=750, ypos=-110)
    ratio.setInput(0, safe_color)
    ratio.setInput(1, per_haze)
    soften = nuke.nodes.Blur(name="AtmosSkySoften", xpos=750, ypos=-100)
    soften["size"].setValue([96, 24])
    soften.setInput(0, ratio)
    upper = nuke.nodes.Crop(name="AtmosSkyUpper", crop=False, xpos=750, ypos=-90)
    upper.setInput(0, soften)
    for i, e in enumerate(("0", "input.height / 2 + 2", "input.width", "input.height")):
        upper["box"].setExpression(e, i)
    grow = nuke.nodes.AdjBBox(name="AtmosSkyExtend", xpos=750, ypos=-60)
    grow["numpixels"].setExpression("input.height")
    grow.setInput(0, upper)
    sky_light = nuke.nodes.Crop(name="AtmosSkyFull", crop=False, xpos=750, ypos=-30)
    sky_light.setInput(0, grow)
    for i, e in enumerate(("0", "0", "AtmosSkyPerHaze.width", "AtmosSkyPerHaze.height")):
        sky_light["box"].setExpression(e, i)

    # Screen-space shafts: how much of each pixel's line towards the sun is open sky.
    shafts = nuke.nodes.BlinkScript(name="Shafts", xpos=300, ypos=-140)
    shafts.setInput(0, depth_pick)
    _load_kernel(shafts, "EzShafts.blink")
    _link_shafts(shafts)

    kernels = []
    for i, (name, output) in enumerate((("Haze", 0), ("Transmittance", 1))):
        node = nuke.nodes.BlinkScript(name=name, xpos=150 * i, ypos=-80)
        node.setInput(0, plate)
        node.setInput(1, depth_pick)
        node.setInput(2, env_pick)
        node.setInput(4, sky_light)
        node.setInput(3, shafts)
        _load_kernel(node, "EzDepthHaze.blink")
        _link_haze(node, output)
        kernels.append(node)
    hazed, trans = kernels

    # In-scatter = hazed - plate * T, so only two kernels are needed.
    dimmed = nuke.nodes.Merge2(name="PlateTimesT", operation="multiply", output="rgb", xpos=300, ypos=0)
    dimmed.setInput(0, plate)
    dimmed.setInput(1, trans)
    inscatter = nuke.nodes.Merge2(name="InScatter", operation="from", output="rgb", xpos=300, ypos=60)
    inscatter.setInput(0, hazed)
    inscatter.setInput(1, dimmed)

    view = nuke.nodes.Switch(name="ViewOutput", xpos=0, ypos=120)
    for i, node in enumerate((hazed, trans, inscatter)):
        view.setInput(i, node)
    view["which"].setExpression("parent.view_output")

    # Main rgb from the view switch; every other channel of the plate passes through.
    stream = nuke.nodes.Copy(name="MainRGB", channels="rgb", xpos=0, ypos=200)
    stream.setInput(0, plate)
    stream.setInput(1, view)
    for i, (layer, source) in enumerate((("haze_transmittance", trans), ("haze_inscatter", inscatter))):
        copy = nuke.nodes.Copy(name="Layer_" + layer, xpos=0, ypos=260 + 60 * i)
        copy.setInput(0, stream)
        copy.setInput(1, source)
        for c, channel in enumerate(("red", "green", "blue")):
            copy["from%d" % c].setValue("rgba." + channel)
            copy["to%d" % c].setValue("%s.%s" % (layer, channel))
        stream = copy
    out = nuke.nodes.Output(xpos=0, ypos=420)
    out.setInput(0, stream)
    group.end()

    _add_knobs(group, depth_pick, env_pick)
    return group


def save_gizmo(group, path=GIZMO_PATH):
    """Write the group out as a .gizmo, layers first so the Copy nodes resolve."""
    for node in nuke.allNodes():
        node.setSelected(False)
    group.setSelected(True)
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    tmp = path + ".tmp"
    nuke.nodeCopy(tmp)
    with open(tmp) as f:
        body = f.read()
    os.remove(tmp)
    body = body.replace("Group {", "Gizmo {", 1)
    header = "version %d.%d v%d\n" % (nuke.NUKE_VERSION_MAJOR, nuke.NUKE_VERSION_MINOR, nuke.NUKE_VERSION_RELEASE)
    for layer in LAYERS:
        header += "add_layer {%s %s.red %s.green %s.blue}\n" % (layer, layer, layer, layer)
    with open(path, "w") as f:
        f.write(header + body[body.index("Gizmo {"):])
    return path


if __name__ == "__main__":
    print("wrote", save_gizmo(build()))
