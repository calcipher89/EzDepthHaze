"""Fit to shot: apply a preset scaled to the shot in the node's inputs.

The presets were tuned on the demo (terrain 6-130 km away, camera 4.3 km up). This measures
the shot's depth and camera at the current frame, the same way the kernel reads them, and
sets the preset's knobs relative to it:

- haze amount, so the median terrain pixel gets the demo's amount of haze;
- fog top and softness, at the same place in the shot's terrain altitudes;
- noise size, wind, shadow and match distances, scaled with the scene's distances;
- sky depth, when a far backdrop (a dome or card) stands apart from the terrain.

build_gizmo.py embeds this file in the gizmo's "fit to shot" button, with PRESETS and
REFERENCE filled in, so Nuke needs no Python module at run time. It only sets knobs once,
when pressed, so renders on the farm see plain values.
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


def _sun_note(n, m):
    """Where the sun is relative to the view, when it's far from what the presets assume."""
    if n["plate_type"].getValue() == 1 or n.input(1) is None:
        return []
    sun = [x for x in _effective(n, "sun_direction", "sun_direction").value()]
    ln = math.sqrt(sum(x * x for x in sun)) or 1.0
    sun = [x / ln for x in sun]
    wm = n.input(1)["world_matrix"]
    fwd = [-wm.getValue(2), -wm.getValue(6), -wm.getValue(10)]
    az = math.degrees(math.atan2(sun[0], -sun[2]) - math.atan2(fwd[0], -fwd[2]))
    az = (az + 180.0) % 360.0 - 180.0
    elev = math.degrees(math.asin(max(-1.0, min(1.0, sun[1]))))
    notes = []
    if abs(az) > 60.0:
        notes.append("The sun is %.0f deg %s of where the camera looks; the presets' backlit glow and "
                     "shafts need it in front." % (abs(az), "right" if az > 0 else "left"))
    if elev > 20.0:
        notes.append("The sun is %.0f deg up; the warm looks expect it low (under 10 deg)." % elev)
    return notes


def fit(n, name=None):
    """Apply the preset picked on `n` (or `name`), fitted to the shot. Returns a summary."""
    name = name or n["preset"].value()
    preset = PRESETS[name]
    ref = REFERENCE
    m = measure(n)

    lines = []
    threshold = n["sky_threshold"].value()
    if m["depth_type"] != 2:
        backdrop = find_backdrop(m["raw"], threshold)
        if backdrop is not None:
            threshold = backdrop
            n["sky_threshold"].setValue(round(backdrop, 3))
            lines.append("Found a far backdrop: sky depth set to %.6g (raw units)." % backdrop)
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

    lines.insert(0, "%s fitted: terrain %.0f-%.0f m away (median %.0f m, %.2fx the demo), "
                    "altitudes %.0f to %.0f m, camera at %.0f m."
                 % (name, st["dist"][0], st["dist"][2], st["dist"][1], scale, st["alt"][0], st["alt"][10],
                    st["camera"]))
    lines.append("haze amount %.3g, fog top %.0f m, fog softness %.0f m, noise size %.0f m."
                 % (n["haze_amount"].value(), n["fog_top"].value(), n["fog_softness"].value(),
                    n["noise_size"].value()))
    lines += _sun_note(n, m)
    lines.append("Suggested sun: %s." % preset["suggested_sun"])
    return "\n".join(lines)


def reference(n):
    """The measurements stored as REFERENCE, taken on the demo scene's node."""
    m = measure(n)
    st = _stats(m, n["sky_threshold"].value())
    return {"dist": st["dist"], "alt": st["alt"], "tau": st["tau"], "camera": st["camera"]}
