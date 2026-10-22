"""Fit to shot: apply a preset scaled to the shot in the node's inputs.

The presets were tuned on the demo (terrain 6-130 km away, camera 4.3 km up). This measures
the shot's depth and camera at the current frame, the same way the kernel reads them, and
sets the preset's knobs relative to it:

- haze amount, so the median terrain pixel gets the demo's amount of haze;
- fog top and softness, at the same place in the shot's terrain altitudes;
- noise size, wind, shadow and match distances, scaled with the scene's distances;
- sky depth, when a far backdrop (a dome or card) stands apart from the terrain.

This is how presets are applied: picking one in the menu, or pressing apply, fits it to the
shot (or applies it as tuned when there is no depth or camera yet), shows a short summary,
and offers to move the EzAtmosScatter sun to where the look wants it. build_gizmo.py embeds
this file in the gizmo, with PRESETS and REFERENCE filled in, so Nuke needs no Python module
at run time. It only sets knobs when run, so renders on the farm see plain values.
"""
import math
import nuke

PRESETS = {}  # filled in by build_gizmo.py
# The demo's measurements (measure() on the demo scene); see python/build_gizmo.py.
REFERENCE = {}


def _pct(values, p):
    v = sorted(values)
    if not v:
        return 0.0
    x = p / 100.0 * (len(v) - 1)
    i = int(x)
    j = min(i + 1, len(v) - 1)
    return v[i] + (v[j] - v[i]) * (x - i)


def _effective(n, name, fallback):
    """A haze setting as the kernel sees it: from the atmos input when inheriting."""
    atmos = n.input(2)
    if n["inherit_atmos"].value() and atmos is not None and atmos.knob(name):
        return atmos[name]
    return n[fallback]


def _height_path(c, d, h):
    """Kernel heightPath(c, 0, d): haze along a ray climbing c per metre, relative to camera height."""
    if abs(c) * d / h < 1e-4:
        return d
    return h / c * (1.0 - math.exp(-c * d / h))


def measure(n, grid=(48, 27)):
    """Distances, altitudes and haze of the shot's terrain, sampled on a grid."""
    plate = n.input(0)
    cam = n.input(1)
    if plate is None:
        raise ValueError("connect a plate with depth first")
    latlong = n["plate_type"].getValue() == 1
    if not latlong and (cam is None or not cam.knob("world_matrix")):
        raise ValueError("connect the camera first")
    scale = n["depth_scale"].value()
    dtype = int(n["depth_type"].getValue())
    chan = n["depth_channel"].value()
    if latlong:
        origin = [0.0, n["latlong_camera_height"].value(), 0.0]
    else:
        m = cam["world_matrix"]
        rows = [[m.getValue(r * 4 + c) for c in range(3)] for r in range(3)]
        origin = [m.getValue(3 + 4 * i) * scale for i in range(3)]
        hap, vap, focal = cam["haperture"].value(), cam["vaperture"].value(), cam["focal"].value()
    sigma = _effective(n, "haze_density", "haze_density").getValue(1)
    h = _effective(n, "haze_height", "haze_height").value() * 1000.0

    w, hgt = plate.width(), plate.height()
    raw_all, samples = [], []
    for j in range(grid[1]):
        for i in range(grid[0]):
            u, v = (i + 0.5) / grid[0], (j + 0.5) / grid[1]
            raw = plate.sample(chan, plate.bbox().x() + u * w, plate.bbox().y() + v * hgt)
            if latlong:
                lon, lat = (u - 0.5) * 2 * math.pi, (v - 0.5) * math.pi
                d = [math.sin(lon) * math.cos(lat), math.sin(lat), -math.cos(lon) * math.cos(lat)]
                planar = 1.0
            else:
                cd = [(u - 0.5) * hap / focal, (v - 0.5) * vap / focal, -1.0]
                planar = math.sqrt(sum(x * x for x in cd))
                d = [sum(rows[r][k] * cd[k] for k in range(3)) for r in range(3)]
                ln = math.sqrt(sum(x * x for x in d))
                d = [x / ln for x in d]
            if raw <= 0:
                continue
            dist = raw if dtype == 0 else raw * planar if dtype == 1 else planar / raw
            raw_all.append(raw)
            samples.append((raw, dist * scale, d))
    return {"origin": origin, "sigma": sigma, "height": h, "raw": raw_all, "samples": samples,
            "pixels": grid[0] * grid[1], "depth_type": dtype}


def find_backdrop(raw, threshold):
    """A raw sky depth that splits off a far backdrop, or None.

    Looks for the widest gap (as a ratio) in the sorted depths beyond the median; a backdrop
    is far further than the terrain in front of it, with nothing in between."""
    v = sorted(x for x in raw if x < threshold)
    if len(v) < 20:
        return None
    best, at = 1.0, None
    for i in range(len(v) // 2, len(v) - 1):
        if v[i] > 0 and v[i + 1] / v[i] > best:
            best, at = v[i + 1] / v[i], i
    if at is None or best < 3.0 or len(v) - 1 - at < 0.02 * len(v):
        return None
    return math.sqrt(v[at] * v[at + 1])


def _stats(m, threshold):
    near = [s for s in m["samples"] if s[0] < threshold] if m["depth_type"] != 2 else m["samples"]
    if len(near) < 10:
        raise ValueError("too few terrain pixels to measure (is the depth channel right?)")
    o = m["origin"]
    dist = [s[1] for s in near]
    alt = [o[1] + s[2][1] * s[1] for s in near]
    tau = [m["sigma"] * _height_path(s[2][1], s[1], m["height"]) for s in near]
    return {"dist": [_pct(dist, p) for p in (10, 50, 90)],
            "alt": [_pct(alt, p) for p in range(0, 101, 10)],
            "tau": _pct(tau, 50), "camera": o[1]}


def _place(value, ref_alts, alts):
    """The altitude at the same place in `alts` as `value` is in `ref_alts` (deciles)."""
    span_ref = max(ref_alts[-1] - ref_alts[0], 1.0)
    span = max(alts[-1] - alts[0], 1.0)
    if value <= ref_alts[0]:
        return alts[0] - (ref_alts[0] - value) / span_ref * span
    if value >= ref_alts[-1]:
        return alts[-1] + (value - ref_alts[-1]) / span_ref * span
    for i in range(len(ref_alts) - 1):
        a, b = ref_alts[i], ref_alts[i + 1]
        if a <= value <= b:
            f = (value - a) / (b - a) if b > a else 0.0
            return alts[i] + f * (alts[i + 1] - alts[i])
    return value


def _atmos(n):
    """The EzAtmosScatter in the atmos input, through any Dots or NoOps."""
    a = n.input(2)
    while a is not None and not a.knob("sun_direction"):
        a = a.input(0) if a.inputs() else None
    return a


def sun_suggestion(n, preset):
    """The preset's sun placed relative to this camera, when the current sun is far from it.

    Returns (question, direction, colour) or None."""
    want = preset.get("sun")
    atmos = _atmos(n)
    cam = n.input(1)
    if not want or atmos is None or cam is None or not cam.knob("world_matrix") or n["plate_type"].getValue() == 1:
        return None
    wm = cam["world_matrix"]
    yaw = math.atan2(-wm.getValue(2), wm.getValue(10))
    sun = list(atmos["sun_direction"].value())
    if atmos.knob("sun_from") and atmos["sun_from"].value() == "Auto (HDRI)":
        with atmos:
            light = nuke.toNode("Light")
            if light is not None:
                sun = [light.sample(c, 0.5, 0.5) for c in ("red", "green", "blue")]
    ln = math.sqrt(sum(x * x for x in sun)) or 1.0
    sun = [x / ln for x in sun]
    az = math.degrees(math.atan2(sun[0], -sun[2]) - yaw)
    az = (az + 180.0) % 360.0 - 180.0
    elev = math.degrees(math.asin(max(-1.0, min(1.0, sun[1]))))
    if abs(az - want["azimuth"]) < 25.0 and abs(elev - want["elevation"]) < 5.0:
        return None
    a = yaw + math.radians(want["azimuth"])
    e = math.radians(want["elevation"])
    direction = [round(math.sin(a) * math.cos(e), 4), round(math.sin(e), 4), round(-math.cos(a) * math.cos(e), 4)]
    side = "left" if want["azimuth"] < 0 else "right"
    question = ("The sun is %.0f deg up and %.0f deg %s of the view. This look wants it %.0f deg up, %.0f deg %s.\n\n"
                "Set %s's sun to that%s?"
                % (elev, abs(az), "right" if az > 0 else "left", want["elevation"], abs(want["azimuth"]), side,
                   atmos.name(), " (this switches 'sun from' to Manual)" if atmos["sun_from"].value() != "Manual" else ""))
    return question, direction, want["color"]


def _plain(n, preset):
    """The preset as tuned, for when there is no depth or camera to fit it to."""
    for k, v in preset["knobs"].items():
        n[k].setValue(v)
    if preset["fog_below_camera"] is not None:
        cam = n.input(1)
        if n["plate_type"].getValue() == 0 and cam is not None and cam.knob("world_matrix"):
            height = cam["world_matrix"].getValue(7) * n["depth_scale"].getValue()
        else:
            height = n["latlong_camera_height"].getValue()
        n["fog_top"].setValue(height - preset["fog_below_camera"])


def fit(n, name=None):
    """Apply the preset picked on `n` (or `name`), fitted to the shot. Returns a short summary."""
    name = name or n["preset"].value()
    preset = PRESETS[name]
    ref = REFERENCE
    m = measure(n)

    threshold = n["sky_threshold"].value()
    backdrop = None
    if m["depth_type"] != 2:
        backdrop = find_backdrop(m["raw"], threshold)
        if backdrop is not None:
            threshold = backdrop
            n["sky_threshold"].setValue(round(backdrop, 3))
    st = _stats(m, threshold)

    scale = st["dist"][1] / ref["dist"][1]
    relief = max(st["alt"][9] - st["alt"][1], 1.0) / max(ref["alt"][9] - ref["alt"][1], 1.0)
    knobs = dict(preset["knobs"])
    knobs["haze_amount"] = preset["knobs"]["haze_amount"] * ref["tau"] / max(st["tau"], 1e-12)
    if knobs.get("fog_density"):
        knobs["fog_density"] = preset["knobs"]["fog_density"] / scale
    if "fog_softness" in knobs:
        knobs["fog_softness"] = preset["knobs"]["fog_softness"] * relief
    for k in ("noise_size",):
        if k in knobs:
            knobs[k] = preset["knobs"][k] * scale
    for k in knobs:
        n[k].setValue(knobs[k])
    if preset["fog_below_camera"] is not None:
        fog_top = _place(ref["camera"] - preset["fog_below_camera"], ref["alt"], st["alt"])
        n["fog_top"].setValue(round(fog_top, 1))
    wind = n["noise_wind"].value()
    speed = math.sqrt(sum(x * x for x in wind)) or 1.0
    n["noise_wind"].setValue([x / speed * 5.0 * scale for x in wind] if any(wind) else [5.0 * scale, 0.0, 0.0])
    n["shadow_distance"].setValue(round(20.0 * scale, 3))
    n["match_distance"].setValue(round(20.0 * scale, 3))
    # Sky pixels hazed as if this far away (Haze Sky) take the same scale, or they get the
    # fitted haze amount over the demo's full distance.
    n["sky_distance"].setValue(round(REFERENCE.get("sky_distance", 250.0) * scale, 3))

    lines = ["%s, fitted to this shot." % name,
             "Terrain %.1f-%.1f km away, %.2gx the demo's distances." % (st["dist"][0] / 1000.0, st["dist"][2] / 1000.0, scale),
             "Haze amount %.3g, fog top %.0f m." % (n["haze_amount"].value(), n["fog_top"].value())]
    if backdrop is not None:
        lines.append("A far backdrop now counts as sky.")
    return "\n".join(lines)


def apply_preset(n):
    """Apply the picked preset, fitted to the shot when it can be measured, then report it
    and offer the preset's sun. Used by the apply button and when a preset is picked."""
    preset = PRESETS[n["preset"].value()]
    try:
        summary = fit(n)
    except ValueError as e:
        _plain(n, preset)
        summary = "%s, as tuned on the demo (%s to fit it to this shot)." % (n["preset"].value(), e)
    offer = sun_suggestion(n, preset)
    if not nuke.GUI:
        print(summary)
        return summary
    if offer is None:
        nuke.message(summary)
        return summary
    question, direction, colour = offer
    if nuke.ask(summary + "\n\n" + question):
        atmos = _atmos(n)
        atmos["sun_from"].setValue("Manual")
        atmos["sun_direction"].setValue(direction)
        if atmos.knob("sun_color"):
            atmos["sun_color"].setValue(colour)
    return summary


def reference(n):
    """The measurements stored as REFERENCE, taken on the demo scene's node."""
    m = measure(n)
    st = _stats(m, n["sky_threshold"].value())
    return {"dist": st["dist"], "alt": st["alt"], "tau": st["tau"], "camera": st["camera"]}
