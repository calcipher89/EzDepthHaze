"""Build gizmos/EzDepthHaze.gizmo from the kernel in blink/.

Run from a terminal (NukeX licence, -i so BlinkScript can compile):

    Nuke15.1.exe --nukex -i -t python/build_gizmo.py

The group has three inputs: the plate (with depth in a channel), an optional Camera,
and an optional lat-long `atmos` input, normally an EzAtmosScatter node, whose
atmos_haze_color layer lights the haze and whose haze settings can be inherited.
"""

import os
import sys

import nuke

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import ezdepthhaze  # noqa: E402  (preset names)
BLINK = os.path.join(ROOT, "blink")
GIZMO_PATH = os.path.join(ROOT, "gizmos", "EzDepthHaze.gizmo")

LAYERS = ["haze_transmittance", "haze_inscatter", "haze_sun", "haze_sky", "haze_shadow", "haze_fog",
          "haze_wisps", "surface_sunlight", "surface_sun_visibility", "P", "N"]
# EzAtmosScatter layers the gizmo reads. They must exist when it is built and loaded, or the
# Shuffles picking them fall back to rgba.
ATMOS_LAYERS = ["atmos_haze_color", "atmos_haze_sun", "atmos_haze_sky", "atmos_inscatter", "atmos_transmittance"]
# (menu label, key of the node that feeds the main rgb)
VIEW_OUTPUTS = [("Hazed Plate", "hazed"), ("Haze Transmittance", "transmittance"),
                ("Haze In-scatter", "inscatter"), ("Haze Sun", "sun"), ("Haze Sky", "sky"),
                ("Haze Shadow", "shadow"), ("Haze Fog", "fog"), ("Haze Wisps", "wisps"),
                ("Surface Sunlight", "surface"), ("Surface Sun Visibility", "visibility"),
                ("World Position (P)", "P"), ("Normals (N)", "N")]

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


def _preset_script():
    """The apply button's script, with the preset values baked in, so the gizmo needs no
    Python module at run time. python/ezdepthhaze.py is where the values are edited."""
    presets = dict((name, {"knobs": p["knobs"], "fog_below_camera": p["fog_below_camera"]})
                   for name, p in ezdepthhaze.PRESETS)
    return "\n".join([
        "n = nuke.thisNode()",
        "presets = %r" % presets,
        "p = presets[n['preset'].value()]",
        "for k, v in p['knobs'].items():",
        "    n[k].setValue(v)",
        "if p['fog_below_camera'] is not None:",
        "    cam = n.input(1)",
        "    if n['plate_type'].getValue() == 0 and cam is not None and cam.knob('world_matrix'):",
        "        height = cam['world_matrix'].getValue(7) * n['depth_scale'].getValue()",
        "    else:",
        "        height = n['latlong_camera_height'].getValue()",
        "    n['fog_top'].setValue(height - p['fog_below_camera'])",
    ])


def _add_knobs(group, depth_pick, env_pick):
    k = []
    defaults = {}

    def add(knob, value=None):
        k.append(knob)
        if value is not None:
            defaults[knob.name()] = value

    add(nuke.Tab_Knob("ezdepthhaze", "EzDepthHaze"))
    preset = nuke.Enumeration_Knob("preset", "preset", ezdepthhaze.PRESET_NAMES)
    preset.setTooltip("A starting look. Pick one and press apply; every knob stays editable afterwards. "
                      "Fog heights are set relative to the camera. Suggested suns (set on EzAtmosScatter):\n"
                      + ezdepthhaze.preset_tooltip())
    add(preset, 1)
    apply = nuke.PyScript_Knob("apply_preset", "apply", _preset_script())
    apply.setTooltip("Sets the knobs of the chosen preset.")
    add(apply)
    view = nuke.Enumeration_Knob("view_output", "view output", [label for label, _ in VIEW_OUTPUTS])
    view.setTooltip("What the main rgb shows. Every pass is also written to its own layer: plate * "
                    "haze_transmittance + haze_sun + haze_sky (+ surface_sunlight * T when added) = result.")
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
                 "Scene units to metres, e.g. 0.01 for centimetres. Scales the depth and the camera position.", 1.0))
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
    color_from = nuke.Enumeration_Knob("haze_color_from", "haze color from", ["Atmos Sun + Sky", "Atmos Layer", "Color"])
    color_from.setTooltip("Atmos Sun + Sky: EzAtmosScatter's atmos_haze_sun and atmos_haze_sky layers, looked up "
                          "in each pixel's view direction; shadows remove only the sun part. Atmos Layer: one "
                          "layer of the atmos input ('atmos layer'), split by 'sun share'. Color: one flat "
                          "colour, split by 'sun share'.")
    add(color_from)
    add(*_double("sun_share", "sun share", 0, 1, "With Atmos Layer or Color: how much of the haze light comes "
                 "from the sun (and so can be shadowed) rather than the sky.", 0.6))
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
    tint = nuke.Color_Knob("haze_tint", "haze tint")
    tint.setTooltip("Tints all the haze light, e.g. warm brown for smoke. White leaves it as the atmosphere made it.")
    add(tint, [1.0, 1.0, 1.0])
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

    add(nuke.Text_Knob("shadow_divider", "Sun and Shadows"))
    sun = nuke.XYZ_Knob("sun_direction", "sun direction")
    sun.setTooltip("Direction towards the sun, +Y up. Taken from the atmos input's sun direction when "
                   "inheriting (set its 'sun from' to Manual so the two agree).")
    add(sun, [0.0, 0.1, -1.0])
    add(*_double("sun_scatter", "sun scatter", 0, 4, "Multiplies the sunlit haze: how bright the light shafts are.", 1.0))
    add(*_double("sky_scatter", "sky scatter", 0, 4, "Multiplies the sky-lit haze: how bright the haze in shadow is.", 1.0))
    add(*_double("shadow_strength", "shadow strength", 0, 1, "How much sunlight the haze loses where the terrain "
                 "blocks the sun. 1 is physical; 0 turns volumetric shadows off.", 1.0))
    fill = nuke.Color_Knob("shadow_fill", "shadow fill")
    fill.setTooltip("Puts back a tinted share of the sunlight the shadowed haze lost. 0 is physical.")
    add(fill, [0.0, 0.0, 0.0])
    add(*_double("shadow_distance", "shadow distance (km)", 0.1, 100, "How far towards the sun each point looks "
                 "for terrain that blocks it.", 20.0))
    add(*_double("penumbra", "penumbra (deg)", 0, 5, "Softness of the shadow edges: the sun's apparent size is "
                 "about 0.5. Larger is softer but grainier.", 0.5))
    add(*_double("occluder_thickness", "occluder thickness (m)", 1, 1e9, "How deep each surface in the depth is "
                 "taken to be. Mountains are solid (the default); lower it for thin objects like trees.", 1e9))
    shadow_quality = nuke.Enumeration_Knob("shadow_quality", "shadow quality", ["Draft", "Normal", "High"])
    shadow_quality.setTooltip("Samples towards the sun (8, 16, 32) and how often along the view ray they are taken.")
    add(shadow_quality, 1)
    note = nuke.Text_Knob("shadow_note", "", "Screen space: only terrain in frame casts shadows. Shadows need "
                          "Volumetric mode or match horizon sky to step the ray; Fast mode steps 16 slabs.")
    add(note)

    add(nuke.Text_Knob("surface_divider", "Surface Light"))
    surface_add = nuke.Boolean_Knob("surface_add", "add surface light")
    surface_add.setTooltip("Adds the sunlight falling on the terrain to the plate. Off: it is only written to the "
                           "surface_sunlight layer. Leave off for CG already lit by the same sun.")
    surface_add.setFlag(nuke.STARTLINE)
    add(surface_add, False)
    add(*_double("surface_strength", "surface light strength", 0, 10, "Multiplies the surface light.", 1.0))
    surface_color = nuke.Color_Knob("surface_color", "sun light color")
    surface_color.setTooltip("Colour and brightness of the sunlight on the terrain.")
    add(surface_color, [1.0, 0.8, 0.6])
    albedo_from = nuke.Enumeration_Knob("albedo_from", "albedo from", ["Plate", "Constant"])
    albedo_from.setTooltip("Plate: use the plate's own colour as the surface colour. Constant: use 'albedo'.")
    add(albedo_from)
    albedo = nuke.Color_Knob("albedo", "albedo")
    add(albedo, [0.15, 0.15, 0.15])

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
    _link(node, "use_env", "[exists parent.input2] && parent.haze_color_from!=2")
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
    _link(node, "sun_share", "parent.sun_share")
    _link(node, "sun_scatter", "parent.sun_scatter")
    _link(node, "sky_scatter", "parent.sky_scatter")
    _link(node, "shadow_strength", "parent.shadow_strength")
    for i, c in enumerate("rgb"):
        _link(node, "shadow_fill", "parent.shadow_fill.%s" % c, i)
        _link(node, "surface_color", "parent.surface_color.%s" % c, i)
        _link(node, "albedo", "parent.albedo.%s" % c, i)
    _link(node, "shadow_distance", "parent.shadow_distance * 1000")
    _link(node, "penumbra", "parent.penumbra")
    _link(node, "occluder_thickness", "parent.occluder_thickness")
    _link(node, "shadow_samples", "parent.shadow_quality==0 ? 8 : parent.shadow_quality==1 ? 16 : 32")
    _link(node, "shadow_every", "parent.shadow_quality==0 ? 6 : parent.shadow_quality==1 ? 3 : 1")
    _link(node, "surface_strength", "parent.surface_strength")
    _link(node, "albedo_from_plate", "parent.albedo_from==0")
    for i, c in enumerate("xyz"):
        _link(node, "sun_direction", ATMOS % ("sun_direction", "sun_direction.%s" % c, "parent.sun_direction.%s" % c), i)


def build():
    for layer in LAYERS + ATMOS_LAYERS:
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

    # Sun and sky haze light. Atmos Sun + Sky uses EzAtmosScatter's split layers; Atmos Layer
    # splits one layer of the atmos input by 'sun share'.
    sun_layer = nuke.nodes.Shuffle2(name="AtmosSunPick", xpos=450, ypos=-200)
    sun_layer.setInput(0, atmos)
    sun_layer["in1"].setValue("atmos_haze_sun")
    sky_layer = nuke.nodes.Shuffle2(name="AtmosSkyPick", xpos=500, ypos=-200)
    sky_layer.setInput(0, atmos)
    sky_layer["in1"].setValue("atmos_haze_sky")
    share_sun = nuke.nodes.Multiply(name="LayerSunShare", channels="rgb", xpos=600, ypos=-170)
    share_sun["value"].setExpression("parent.sun_share")
    share_sun.setInput(0, env_pick)
    share_sky = nuke.nodes.Multiply(name="LayerSkyShare", channels="rgb", xpos=650, ypos=-170)
    share_sky["value"].setExpression("1 - parent.sun_share")
    share_sky.setInput(0, env_pick)
    env_sun = nuke.nodes.Switch(name="HazeSunLight", xpos=450, ypos=-140)
    env_sun.setInput(0, sun_layer)
    env_sun.setInput(1, share_sun)
    env_sun["which"].setExpression("parent.haze_color_from==1")
    env_sky = nuke.nodes.Switch(name="HazeSkyLight", xpos=500, ypos=-140)
    env_sky.setInput(0, sky_layer)
    env_sky.setInput(1, share_sky)
    env_sky["which"].setExpression("parent.haze_color_from==1")
    env_total = nuke.nodes.Merge2(name="HazeTotalLight", operation="plus", output="rgb", xpos=550, ypos=-110)
    env_total.setInput(0, env_sun)
    env_total.setInput(1, env_sky)

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
    safe_color.setInput(0, env_total)
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

    # Haze tint, applied after the horizon ratio's reference so it reaches far haze too.
    tinted = []
    for name, src, x in (("HazeSunTint", env_sun, 450), ("HazeSkyTint", env_sky, 500)):
        m = nuke.nodes.Multiply(name=name, channels="rgb", xpos=x, ypos=-80)
        for i, c in enumerate("rgb"):
            m["value"].setExpression("parent.haze_tint.%s" % c, i)
        m.setInput(0, src)
        tinted.append(m)
    sun_tinted, sky_tinted = tinted

    # One kernel per pass (BlinkScript writes a single image). Only the shadowed sun pass
    # tests for shadows, so the others cost a plain march.
    passes = {}
    for i, (key, output) in enumerate((("transmittance", 1), ("sun", 3), ("sky", 4), ("sun_free", 5),
                                       ("masks", 6), ("surface_raw", 7), ("P", 8), ("N", 9))):
        node = nuke.nodes.BlinkScript(name="Pass_" + key, xpos=120 * i - 300, ypos=-80)
        node.setInput(0, plate)
        node.setInput(1, depth_pick)
        node.setInput(2, sun_tinted)
        node.setInput(3, sky_tinted)
        node.setInput(4, sky_light)
        _load_kernel(node, "EzDepthHaze.blink")
        _link_haze(node, output)
        passes[key] = node

    def merge(name, op, a, b, x, y):
        m = nuke.nodes.Merge2(name=name, operation=op, output="rgb", xpos=x, ypos=y)
        m.setInput(0, b)
        m.setInput(1, a)
        return m

    def mono(name, source, channel, x, y):
        s = nuke.nodes.Shuffle2(name=name, xpos=x, ypos=y)
        s.setInput(0, source)
        s["mappings"].setValue([("rgba.%s" % channel, "rgba.red"), ("rgba.%s" % channel, "rgba.green"),
                                ("rgba.%s" % channel, "rgba.blue")])
        return s

    inscatter = merge("InScatter", "plus", passes["sky"], passes["sun"], 0, 0)
    shadow = merge("ShadowLoss", "from", passes["sun"], passes["sun_free"], 120, 0)
    fog_share = mono("FogShare", passes["masks"], "red", 240, 0)
    fog = merge("FogInScatter", "multiply", fog_share, inscatter, 240, 40)
    wisps = mono("Wisps", passes["masks"], "green", 360, 0)
    visibility = mono("SurfaceVisibility", passes["surface_raw"], "alpha", 480, 0)
    surface = nuke.nodes.Remove(name="SurfaceSunlight", operation="keep", channels="rgb", xpos=600, ypos=0)
    surface.setInput(0, passes["surface_raw"])

    # result = (plate + surface light, if added) * T + sun + sky
    surface_add = nuke.nodes.Multiply(name="SurfaceAdd", channels="rgb", xpos=600, ypos=40)
    surface_add["value"].setExpression("parent.surface_add")
    surface_add.setInput(0, surface)
    lit_plate = merge("PlatePlusSurface", "plus", surface_add, plate, 0, 60)
    dimmed = merge("PlateTimesT", "multiply", passes["transmittance"], lit_plate, 0, 100)
    hazed = merge("Hazed", "plus", inscatter, dimmed, 0, 140)

    sources = {"hazed": hazed, "transmittance": passes["transmittance"], "inscatter": inscatter,
               "sun": passes["sun"], "sky": passes["sky"], "shadow": shadow, "fog": fog, "wisps": wisps,
               "surface": surface, "visibility": visibility, "P": passes["P"], "N": passes["N"]}
    view = nuke.nodes.Switch(name="ViewOutput", xpos=0, ypos=200)
    for i, (_, key) in enumerate(VIEW_OUTPUTS):
        view.setInput(i, sources[key])
    view["which"].setExpression("parent.view_output")

    # Main rgb from the view switch; every other channel of the plate passes through.
    stream = nuke.nodes.Copy(name="MainRGB", channels="rgb", xpos=0, ypos=260)
    stream.setInput(0, plate)
    stream.setInput(1, view)
    layer_sources = [("haze_transmittance", passes["transmittance"]), ("haze_inscatter", inscatter),
                     ("haze_sun", passes["sun"]), ("haze_sky", passes["sky"]), ("haze_shadow", shadow),
                     ("haze_fog", fog), ("haze_wisps", wisps), ("surface_sunlight", surface),
                     ("surface_sun_visibility", visibility), ("P", passes["P"]), ("N", passes["N"])]
    for i, (layer, source) in enumerate(layer_sources):
        copy = nuke.nodes.Copy(name="Layer_" + layer, xpos=0, ypos=320 + 40 * i)
        copy.setInput(0, stream)
        copy.setInput(1, source)
        for c, channel in enumerate(("red", "green", "blue")):
            copy["from%d" % c].setValue("rgba." + channel)
            copy["to%d" % c].setValue("%s.%s" % (layer, channel))
        stream = copy
    out = nuke.nodes.Output(xpos=0, ypos=320 + 40 * len(layer_sources) + 40)
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
    group_body = body[body.index("Group {"):]
    body = body.replace("Group {", "Gizmo {", 1)
    header = "version %d.%d v%d\n" % (nuke.NUKE_VERSION_MAJOR, nuke.NUKE_VERSION_MINOR, nuke.NUKE_VERSION_RELEASE)
    for layer in LAYERS + ATMOS_LAYERS:
        header += "add_layer {%s %s.red %s.green %s.blue}\n" % (layer, layer, layer, layer)
    with open(path, "w") as f:
        f.write(header + body[body.index("Gizmo {"):])
    # The same node as a plain Group, for studios that keep tools in scripts rather than
    # on the plugin path: File > Import Script (or paste) it, no gizmo install needed.
    group_path = os.path.join(ROOT, "groups", os.path.splitext(os.path.basename(path))[0] + "_group.nk")
    if not os.path.isdir(os.path.dirname(group_path)):
        os.makedirs(os.path.dirname(group_path))
    with open(group_path, "w") as f:
        f.write(header + group_body)
    return path, group_path


if __name__ == "__main__":
    print("wrote", save_gizmo(build()))
