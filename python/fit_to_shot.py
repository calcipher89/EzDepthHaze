"""Fit to shot: apply a preset scaled to the shot in the node's inputs.
    # Only when the frame has no sky of its own yet: a dome or card standing in for it.
    open_sky = m["pixels"] - len([x for x in m["raw"] if x < threshold])
    if m["depth_type"] != 2 and open_sky < 0.02 * m["pixels"]:
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
# What the last fit measured, for easy mode.
LAST_FIT = {}


def _pct(values, p):
    v = sorted(values)
    if not v:
        return 0.0
    x = p / 100.0 * (len(v) - 1)
    i = int(x)
    j = min(i + 1, len(v) - 1)
    return v[i] + (v[j] - v[i]) * (x - i)


def _camera(n):
    """The camera in the camera input, through any Dots or NoOps."""
    c = n.input(1)
    while c is not None and not c.knob("world_matrix"):
        c = c.input(0) if c.inputs() else None
    return c


def _effective(n, name, fallback):
    """A haze setting as the kernel sees it: from the atmos input when inheriting."""
    atmos = _atmos(n)
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
    cam = _camera(n)
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
    """A raw sky depth that splits off a far backdrop (a skydome or a card), or None.

    A backdrop is the farthest group of depths, tightly bunched (a dome around the camera,
    or a card), with a clear gap to the terrain in front of it. Edge pixels that blend the
    two sit inside that gap, so a few of them are allowed there."""
    v = sorted(x for x in raw if 0 < x < threshold)
    n = len(v)
    if n < 20:
        return None
    stray = max(2, n // 100)
    best, at = 1.0, None
    for i in range(n // 10, n - stray - 1):
        far = v[i + stray + 1:]
        # The group past the gap: at least 2% of the frame, and bunched (a dome, not terrain).
        if len(far) < 0.02 * n or far[-1] / far[0] > 1.6:
            continue
        gap = v[i + stray + 1] / v[i]
        if gap > best:
            best, at = gap, i
    if at is None or best < 1.5:
        return None
    return math.sqrt(v[at] * v[at + stray + 1])


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


def _clouds(n):
    """Where the cloud gaps' sky comes from: (node, layer, menu value), or (None, None, None).
    The clouds input (through any Dots or NoOps) when it's on the node and plugged in, else
    the atmos node's atmos_clouds layer when it outputs a lat-long."""
    c = n.input(3) if n.inputs() > 3 else None
    while c is not None and c.Class() in ("Dot", "NoOp"):
        c = c.input(0) if c.inputs() else None
    if c is not None and c.width():
        return c, "rgba", "Clouds Input"
    a = _atmos(n)
    if (a is not None and "atmos_clouds.red" in a.channels() and
            not (a.knob("output_mapping") and int(a["output_mapping"].getValue()) != 0)):
        return a, "atmos_clouds", "Sky (from atmos)"
    return None, None, None


def sync_clouds_input(n):
    """Show the clouds input only while 'gaps from' is Clouds Input (knobChanged does the same
    when the menu is changed by hand)."""
    want = n["cloud_from"].value() == "Clouds Input"
    if not want and n.input(3) is not None:
        n.setInput(3, None)
    with n:
        inp = nuke.toNode("clouds")
        if want and inp is None:
            inp = nuke.nodes.Input(name="clouds", xpos=1050, ypos=-300)
            pick = nuke.toNode("CloudsOrNone")
            if pick is not None:
                pick.setInput(1, inp)
        elif not want and inp is not None:
            nuke.delete(inp)


def cloud_setup(n, st=None):
    """With a sky in the clouds input: use it for the gaps, put the cloud layer where the sky
    round the sun is used, and set cloud cover so about a quarter of that sky lets the sun
    through. Returns a line saying what was set, or None without a clouds input."""
    sky, layer, source = _clouds(n)
    if sky is None:
        return None
    atmos = _atmos(n)
    src = atmos if atmos is not None else n
    sun = [src["sun_direction"].value(i) for i in range(3)]
    length = math.sqrt(sum(x * x for x in sun)) or 1.0
    sun = [x / length for x in sun]
    if sun[1] < 0.05:
        return "Clouds input: the sun is at the horizon, so cloud gaps can't cast beams."
    if atmos is not None and atmos.knob("hdri_rotation"):
        rot = math.radians(atmos["hdri_rotation"].value())
    else:
        rot = math.radians(n["env_rotation"].value())
    # The sky the beams come through: rings 5 to 25 degrees round the sun.
    up = [0.0, 1.0, 0.0] if abs(sun[1]) < 0.99 else [1.0, 0.0, 0.0]
    a = [sun[1] * up[2] - sun[2] * up[1], sun[2] * up[0] - sun[0] * up[2], sun[0] * up[1] - sun[1] * up[0]]
    la = math.sqrt(sum(x * x for x in a)) or 1.0
    a = [x / la for x in a]
    b = [sun[1] * a[2] - sun[2] * a[1], sun[2] * a[0] - sun[0] * a[2], sun[0] * a[1] - sun[1] * a[0]]
    w, h = sky.format().width(), sky.format().height()
    # A keyed alpha in the clouds input (1 cloud, 0 gap) is used as it is.
    # (A constant alpha, as many HDRI reads have, is no key.)
    alpha = layer + ".alpha" in sky.channels()
    if alpha:
        probe = [sky.sample(layer + ".alpha", (i + 0.5) / 16.0 * w, (0.55 + 0.4 * (j + 0.5) / 4.0) * h)
                 for i in range(16) for j in range(4)]
        alpha = max(probe) - min(probe) > 0.05
    n["cloud_key"].setValue("Alpha" if alpha else "Blue Sky")
    keys = []
    for ring in range(1, 6):
        ang = math.radians(5.0 * ring)
        for k in range(12):
            phi = 2.0 * math.pi * k / 12.0
            d = [math.cos(ang) * sun[i] + math.sin(ang) * (math.cos(phi) * a[i] + math.sin(phi) * b[i])
                 for i in range(3)]
            lon = math.atan2(d[0], -d[2]) - rot
            lat = math.asin(max(-1.0, min(1.0, d[1])))
            u = lon / (2.0 * math.pi) + 0.5
            x, y = (u - math.floor(u)) * w, (lat / math.pi + 0.5) * h
            if alpha:
                keys.append(1.0 - max(0.0, min(1.0, sky.sample(layer + ".alpha", x, y))))
                continue
            r, g, bl = [sky.sample("%s.%s" % (layer, c), x, y) for c in ("red", "green", "blue")]
            # The same key as the kernel: blue sky (away from the horizon) or the sun itself.
            key = max(0.0, min(1.0, (bl - r) / max(bl, 1e-4) * 3.0)) * max(0.0, min(1.0, (d[1] - 0.05) / 0.15))
            disc = max(0.0, min(1.0, (0.2126 * r + 0.7152 * g + 0.0722 * bl) / 50.0 - 1.0))
            keys.append(max(key, disc))
    keys.sort()
    if keys[-max(len(keys) // 10, 1)] < 0.2:
        n["cloud_from"].setValue("Noise")
        sync_clouds_input(n)
        return ("Clouds input: the sky round the sun has hardly any %s, so the gaps stay on "
                "Noise (check with view output > Cloud Gaps)." % ("gaps in the alpha" if alpha else "blue gaps"))
    n["cloud_from"].setValue(source)
    sync_clouds_input(n)
    cover = max(0.3, min(0.97, keys[int(len(keys) * 0.75)]))
    n["cloud_cover"].setValue(round(cover, 3))
    if st is None:
        try:
            st = _stats(measure(n), n["sky_threshold"].value())
        except ValueError:
            st = None
    if st is not None:
        # Low enough that the beams in frame draw on the sky round the sun, not just the sun.
        n["cloud_height"].setValue(round(st["camera"] + max(1000.0, 0.35 * st["dist"][1]), 1))
    return ("Clouds input: gaps from the %s, cloud cover %.2f (about a quarter of the sky round "
            "the sun lets light through), cloud height %.0f m."
            % ("keyed alpha" if alpha else "sky's blue", cover, n["cloud_height"].value()))


def sun_suggestion(n, preset):
    """The preset's sun placed relative to this camera, when the current sun is far from it.

    Returns (question, direction, colour) or None."""
    want = preset.get("sun")
    atmos = _atmos(n)
    cam = _camera(n)
    if not want or atmos is None or cam is None or not cam.knob("world_matrix") or n["plate_type"].getValue() == 1:
        return None
    wm = cam["world_matrix"]
    yaw = math.atan2(-wm.getValue(2), wm.getValue(10))
    sun = list(atmos["sun_direction"].value())
    if atmos.knob("sun_in_use"):
        # Newer EzAtmosScatter: the sun it uses, whether found in the HDRI, from an Axis or manual.
        sun = list(atmos["sun_in_use"].value())
    elif atmos.knob("sun_from") and atmos["sun_from"].value() == "Auto (HDRI)":
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


def _phase(mu, g=0.76):
    """Cornette-Shanks haze phase function, as in EzAtmosScatter's kernel."""
    g2 = g * g
    return 1.5 * (1.0 - g2) / (2.0 + g2) * (1.0 + mu * mu) / max(1.0 + g2 - 2.0 * g * mu, 1e-6) ** 1.5


def _frame_phase(n, cam, sun):
    """How strongly the haze in frame scatters this sun towards the camera: the haze phase
    function averaged over a grid of view directions across the camera's frame."""
    wm = cam["world_matrix"]
    ax = [wm.getValue(0), wm.getValue(4), wm.getValue(8)]
    ay = [wm.getValue(1), wm.getValue(5), wm.getValue(9)]
    az = [wm.getValue(2), wm.getValue(6), wm.getValue(10)]
    focal = cam["focal"].value() if cam.knob("focal") else 35.0
    hap = cam["haperture"].value() if cam.knob("haperture") else 36.0
    plate = n.input(0)
    aspect = float(plate.height()) / plate.width() if plate is not None and plate.width() else 9.0 / 16.0
    sx, sy = hap / 2.0 / focal, hap * aspect / 2.0 / focal
    total = 0.0
    for j in range(5):
        for i in range(9):
            u, v = (i / 4.0 - 1.0) * sx, (j / 2.0 - 1.0) * sy
            d = [-az[c] + u * ax[c] + v * ay[c] for c in range(3)]
            ln = math.sqrt(sum(x * x for x in d)) or 1.0
            total += _phase(sum(d[c] / ln * sun[c] for c in range(3)))
    return total / 45.0


def follow_sun(n, preset):
    """Keep the sun EzAtmosScatter finds in its HDRI (or takes from its Axis) and fit the look to
    it: the sunlit haze is scaled so the glow and shafts in frame are about as strong as with the
    sun the look was tuned with. Returns a summary line, or None when the sun is manual (then the
    look offers to move it instead) or there is nothing to fit to."""
    want = preset.get("sun")
    atmos = _atmos(n)
    cam = _camera(n)
    if not want or atmos is None or not atmos.knob("sun_in_use") or not atmos.knob("sun_from"):
        return None
    if atmos["sun_from"].value() == "Manual" or cam is None or not cam.knob("world_matrix") \
            or n["plate_type"].getValue() == 1:
        return None
    sun = list(atmos["sun_in_use"].value())
    ln = math.sqrt(sum(x * x for x in sun)) or 1.0
    sun = [x / ln for x in sun]
    wm = cam["world_matrix"]
    yaw = math.atan2(-wm.getValue(2), wm.getValue(10))
    a = yaw + math.radians(want["azimuth"])
    e = math.radians(want["elevation"])
    tuned = [math.sin(a) * math.cos(e), math.sin(e), -math.cos(a) * math.cos(e)]
    ratio = _frame_phase(n, cam, tuned) / max(_frame_phase(n, cam, sun), 1e-6)
    scale = min(max(ratio, 0.5), 2.0)
    n["sun_scatter"].setValue(round(n["sun_scatter"].value() * scale, 3))
    az = math.degrees(math.atan2(sun[0], -sun[2]) - yaw)
    az = (az + 180.0) % 360.0 - 180.0
    elev = math.degrees(math.asin(max(-1.0, min(1.0, sun[1]))))
    line = ("Kept %s's sun from its %s (%.0f deg up, %.0f deg %s of the view); sun scatter x%.2f to match "
            "the look's glow." % (atmos.name(), "HDRI" if atmos["sun_from"].value().startswith("Auto") else "Axis",
                                  elev, abs(az), "right" if az > 0 else "left", scale))
    if ratio > 2.0:
        line += " The sun is too far from where the look wants it for a full match, so shafts and glow stay weaker."
    return line


def _plain(n, preset):
    """The preset as tuned, for when there is no depth or camera to fit it to."""
    for k, v in preset["knobs"].items():
        n[k].setValue(v)
    cam = _camera(n)
    if n["plate_type"].getValue() == 0 and cam is not None and cam.knob("world_matrix"):
        height = cam["world_matrix"].getValue(7) * n["depth_scale"].getValue()
    else:
        height = n["latlong_camera_height"].getValue()
    if preset["fog_below_camera"] is not None:
        n["fog_top"].setValue(height - preset["fog_below_camera"])
    if preset.get("cloud_above_camera"):
        n["cloud_height"].setValue(height + preset["cloud_above_camera"])


def fit(n, name=None):
    """Apply the preset picked on `n` (or `name`), fitted to the shot. Returns a short summary."""
    name = name or n["preset"].value()
    preset = PRESETS[name]
    ref = REFERENCE
    m = measure(n)

    threshold = n["sky_threshold"].value()
    backdrop = None
    # Only when the frame has no open sky of its own: then a dome or card stands in for it.
    open_sky = m["pixels"] - len([x for x in m["raw"] if x < threshold])
    if m["depth_type"] != 2 and open_sky < 0.02 * m["pixels"]:
        backdrop = find_backdrop(m["raw"], threshold)
        if backdrop is not None:
            threshold = backdrop
            n["sky_threshold"].setValue(round(backdrop, 3))
    st = _stats(m, threshold)

    scale = st["dist"][1] / ref["dist"][1]
    # Easy mode moves the fog height in steps of the terrain's altitude range.
    LAST_FIT["relief"] = max(st["alt"][9] - st["alt"][1], 1.0)
    LAST_FIT["low"] = st["alt"][0]
    LAST_FIT["valley"] = st["alt"][2]
    LAST_FIT["scale"] = st["dist"][1] / ref["dist"][1]
    relief = max(st["alt"][9] - st["alt"][1], 1.0) / max(ref["alt"][9] - ref["alt"][1], 1.0)
    knobs = dict(preset["knobs"])
    knobs["haze_amount"] = preset["knobs"]["haze_amount"] * ref["tau"] / max(st["tau"], 1e-12)
    if knobs.get("fog_density"):
        knobs["fog_density"] = preset["knobs"]["fog_density"] / scale
    if "fog_softness" in knobs:
        knobs["fog_softness"] = preset["knobs"]["fog_softness"] * relief
    for k in ("noise_size", "cloud_size", "cloud_breakup_size"):
        if k in knobs:
            knobs[k] = preset["knobs"][k] * scale
    for k in knobs:
        n[k].setValue(knobs[k])
    if preset["fog_below_camera"] is not None:
        fog_top = _place(ref["camera"] - preset["fog_below_camera"], ref["alt"], st["alt"])
        n["fog_top"].setValue(round(fog_top, 1))
    if preset.get("cloud_above_camera"):
        n["cloud_height"].setValue(round(st["camera"] + preset["cloud_above_camera"] * scale, 1))
    clouds_line = cloud_setup(n, st) if knobs.get("cloud_cover") else None
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
    if clouds_line:
        lines.append(clouds_line)
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
    # A sun from the HDRI or an Axis stays where it is (moving it would part it from the sky);
    # the look is fitted to it instead. Only a manual sun is offered the look's own sun.
    followed = follow_sun(n, preset)
    if followed is not None:
        summary += "\n" + followed
        offer = None
    else:
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
