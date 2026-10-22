"""Preset looks for the EzDepthHaze gizmo.

Used when building the gizmo: python/build_gizmo.py bakes these values into the gizmo's
"apply" button, so Nuke needs no Python module at run time. Edit them here and rebuild.

Each preset only sets EzDepthHaze knobs; artists keep tweaking afterwards. Altitudes are
given relative to the camera (negative = below it), so a preset works whatever the scale
of the scene. The sun itself lives on EzAtmosScatter; each preset suggests one.
"""

import nuke

PRESETS = [
    ("Clear Day", {
        "suggested_sun": "high, 30-45 degrees, from the side; white, full strength",
        # The sun the question after applying offers: degrees up, degrees right of the view, colour.
        "sun": {"elevation": 35.0, "azimuth": 60.0, "color": [1.0, 1.0, 1.0]},
        "knobs": {"haze_mode": 1, "haze_amount": 1.2, "match_horizon": True, "haze_tint": [1.0, 1.0, 1.0], "fog_density": 0.0,
                  "noise_amount": 0.2, "noise_size": 4000.0, "noise_stretch": 3.0, "sun_scatter": 1.0,
                  "sky_scatter": 1.0, "shadow_strength": 1.0, "shadow_fill": [0.0, 0.0, 0.0]},
        "fog_below_camera": None,
    }),
    ("Golden Hour", {
        "suggested_sun": "low, 2-6 degrees, in front of the camera; warm",
        "sun": {"elevation": 4.0, "azimuth": -15.0, "color": [1.0, 0.72, 0.5]},
        "knobs": {"haze_mode": 1, "haze_amount": 2.0, "match_horizon": True, "haze_tint": [1.0, 1.0, 1.0], "fog_density": 1.0,
                  "fog_softness": 600.0, "noise_amount": 0.8, "noise_size": 3000.0, "noise_stretch": 3.0,
                  "sun_scatter": 1.4, "sky_scatter": 1.0, "shadow_strength": 1.0, "shadow_fill": [0.0, 0.0, 0.0]},
        "fog_below_camera": 2500.0,
    }),
    ("Valley Fog", {
        "suggested_sun": "low morning sun, 8-15 degrees; slightly warm",
        "sun": {"elevation": 10.0, "azimuth": -30.0, "color": [1.0, 0.92, 0.85]},
        "knobs": {"haze_mode": 1, "haze_amount": 0.8, "match_horizon": True, "haze_tint": [0.95, 0.98, 1.0], "fog_density": 4.0,
                  "fog_softness": 300.0, "noise_amount": 0.5, "noise_size": 1500.0, "noise_stretch": 6.0,
                  "sun_scatter": 1.2, "sky_scatter": 1.1, "shadow_strength": 1.0, "shadow_fill": [0.0, 0.0, 0.0]},
        "fog_below_camera": 2300.0,
    }),
    ("Smoke Haze", {
        "suggested_sun": "any; a dimmed, reddened sun reads best",
        "sun": {"elevation": 8.0, "azimuth": -20.0, "color": [1.0, 0.72, 0.5]},
        "knobs": {"haze_mode": 1, "haze_amount": 2.5, "match_horizon": False, "haze_tint": [0.9, 0.68, 0.48], "fog_density": 0.1,
                  "fog_softness": 1500.0, "noise_amount": 0.6, "noise_size": 4000.0, "noise_stretch": 2.0,
                  "sun_scatter": 0.35, "sky_scatter": 1.0, "shadow_strength": 0.7, "shadow_fill": [0.0, 0.0, 0.0]},
        "fog_below_camera": 2000.0,
    }),
    ("Overcast Mist", {
        "suggested_sun": "any; it hardly shows",
        "sun": None,
        "knobs": {"haze_mode": 1, "haze_amount": 2.0, "match_horizon": False, "haze_tint": [0.85, 0.9, 1.0], "fog_density": 0.5,
                  "fog_softness": 800.0, "noise_amount": 0.9, "noise_size": 1200.0, "noise_stretch": 4.0,
                  "sun_scatter": 0.2, "sky_scatter": 1.6, "shadow_strength": 0.0, "shadow_fill": [0.0, 0.0, 0.0]},
        "fog_below_camera": 2600.0,
    }),
]

PRESET_NAMES = [name for name, _ in PRESETS]


def camera_height(node):
    """Height of the camera the node hazes from: the camera input, or the lat-long knob."""
    cam = node.input(1)
    if node["plate_type"].getValue() == 0 and cam is not None and cam.knob("world_matrix"):
        return cam["world_matrix"].getValue(7) * node["depth_scale"].getValue()
    return node["latlong_camera_height"].getValue()


def apply_preset(node, name=None):
    """Set the knobs of the preset picked in the node's 'preset' menu (or `name`)."""
    name = name or node["preset"].value()
    preset = dict(PRESETS)[name]
    for knob, value in preset["knobs"].items():
        node[knob].setValue(value)
    if preset["fog_below_camera"] is not None:
        node["fog_top"].setValue(camera_height(node) - preset["fog_below_camera"])
    return preset["suggested_sun"]


def preset_tooltip():
    return "\n".join("%s: sun %s." % (name, p["suggested_sun"]) for name, p in PRESETS)

# The demo scene's terrain as fit to shot measures it (python/fit_to_shot.py reference(),
# on the presets review's EzDepthHaze_GoldenHour): distance deciles 10/50/90 and altitude
# deciles in metres, median haze optical depth at haze amount 1, and camera height.
# Presets are fitted relative to these.
REFERENCE = {"dist": [6496.5, 10173.3, 38953.5],
             "alt": [1634.9, 1834.3, 1985.2, 2119.1, 2236.5, 2363.8, 2421.3, 2546.0, 2669.7, 2814.6, 3111.4],
             "tau": 0.173031, "camera": 4300.0, "sky_distance": 250.0}

# Where easy mode saves and finds looks. Change the paths here (and rebuild), or set the
# environment variables, which win.
LOOK_DIRS = {
    "User": {"env": "EZHAZE_USER_LOOKS", "path": "~/.nuke/ezdepthhaze_looks"},
    "Studio": {"env": "EZHAZE_STUDIO_LOOKS", "path": ""},
}
