"""Easy mode: a few big sliders over the advanced knobs, visibility in km, and saved looks.

build_gizmo.py embeds this file after fit_to_shot.py in the gizmo's knobChanged and buttons
(one shared namespace), with LOOK_DIRS, LOOK_KNOBS and DEFAULTS filled in, so Nuke needs no
Python module at run time.

The sliders are relative to a base look kept in the hidden easy_base knob: the preset as
fitted to the shot, a loaded look, or the advanced knobs after an artist edits one of them
(or a visibility distance). Every slider change rewrites the advanced knobs from the base,
so the Advanced tab always shows exactly what Easy did, ready to fine-tune.
"""
import json
import math
import os
import random
import re

import nuke

# Filled in by build_gizmo.py from python/ezdepthhaze.py and the gizmo's knobs.
LOOK_DIRS = {}
LOOK_KNOBS = []
DEFAULTS = {}

# Easy slider: (knob, neutral value, surprise range).
SLIDERS = [("easy_haze", 1.0, (0.6, 1.6)), ("easy_warmth", 0.0, (-0.6, 0.6)), ("easy_glow", 1.0, (0.6, 1.8)),
           ("easy_shafts", 1.0, (0.5, 1.4)), ("easy_light", 1.0, (0.6, 1.6)), ("easy_shadow", 1.0, (0.6, 1.4)),
           ("easy_fog", 1.0, (0.3, 2.0)), ("easy_fog_height", 0.0, (-0.5, 0.5)),
           ("easy_fog_softness", 1.0, (0.4, 1.6)), ("easy_texture", 1.0, (0.3, 2.0)),
           ("easy_texture_scale", 1.0, (0.4, 1.6)), ("easy_texture_detail", 1.0, (0.5, 1.8)),
           ("easy_texture_sharpness", 0.0, (0.0, 1.5))]
EASY_KNOBS = [name for name, _, _ in SLIDERS] + ["look_strength", "easy_exposure"]


class _Busy(object):
    """While easy mode sets knobs itself, knobChanged leaves them alone (the flag lives on the
    nuke module, the one thing that outlasts each knobChanged run)."""

    def __enter__(self):
        self.was = getattr(nuke, "_ezhaze_busy", False)
        nuke._ezhaze_busy = True

    def __exit__(self, *args):
        nuke._ezhaze_busy = self.was


def _value(n, name):
    v = n[name].value()
    return list(v) if isinstance(v, (list, tuple)) else v


def _sigma(n):
    """Haze extinction per metre at camera height for haze amount 1 (green)."""
    return max(_effective(n, "haze_density", "haze_density").getValue(1), 1e-12)


def show_visibility(n):
    """Write the visibility distances that match the advanced knobs."""
    with _Busy():
        amount = n["haze_amount"].value()
        n["vis_near"].setValue(round(n["haze_start"].value() / 1000.0, 2))
        n["vis_far"].setValue(round(3.0 / (_sigma(n) * max(amount, 1e-6)) / 1000.0, 2) if amount > 0 else 0.0)
        fog = n["fog_density"].value()
        n["vis_fog"].setValue(round(3.0 / fog, 2) if fog > 0 else 0.0)


def set_visibility(n, k):
    """An artist typed a visibility distance: set the knobs it stands for, then start Easy from there."""
    with _Busy():
        v = n[k].value()
        if k == "vis_near":
            n["haze_start"].setValue(max(v, 0.0) * 1000.0)
        elif k == "vis_far":
            n["haze_amount"].setValue(3.0 / (_sigma(n) * max(v, 0.01) * 1000.0))
        elif k == "vis_fog":
            n["fog_density"].setValue(3.0 / v if v > 0 else 0.0)
            if v > 0 and n["haze_mode"].getValue() == 0:
                n["haze_mode"].setValue("Volumetric")
    rebase(n)


def rebase(n, relief=None, centre=True):
    """Make the advanced knobs' current values the base, and centre the sliders."""
    with _Busy():
        base = dict((k, _value(n, k)) for k in LOOK_KNOBS if n.knob(k))
        # Exposure stays as it is across looks: the base holds the haze brightness without it.
        if "haze_color_gain" in base and n.knob("easy_exposure"):
            base["haze_color_gain"] = base["haze_color_gain"] / 2.0 ** n["easy_exposure"].value()
        old = {}
        try:
            old = json.loads(n["easy_base"].value() or "{}")
        except ValueError:
            pass
        # What the last fit measured about the terrain, so sliders work in the shot's own units.
        for key, fallback in (("relief", max(n["fog_softness"].value() * 3.0, 50.0)),
                              ("low", n["fog_top"].value() - 300.0), ("valley", n["fog_top"].value()),
                              ("scale", 1.0)):
            base[key] = LAST_FIT.get(key, old.get(key, fallback))
        if relief:
            base["relief"] = relief
        n["easy_base"].setValue(json.dumps(base))
        if centre:
            for name, _, _ in SLIDERS:
                n[name].setValue(_neutral(name, base))
            n["look_strength"].setValue(1.0)
    show_visibility(n)


def _neutral(name, base):
    """A slider's middle: where it leaves the look as it is. 'light' sits at 0 when the look
    has no surface light, so moving it up adds some."""
    if name == "easy_light":
        return 1.0 if base.get("surface_add") else 0.0
    return dict((k, v) for k, v, _ in SLIDERS)[name]


def _base(n):
    try:
        return json.loads(n["easy_base"].value() or "{}")
    except ValueError:
        return {}


def apply_easy(n):
    """Rewrite the advanced knobs from the base and the sliders.

    Each slider moves several knobs, so it changes the look on any shot: where the look
    has none of something (no fog, no shadows), pushing the slider past the middle adds it.
    """
    try:
        b = json.loads(n["easy_base"].value() or "{}")
    except ValueError:
        b = {}
    if not b or "scale" not in b:
        # No look applied yet (a fresh node shows a look in its menu but still holds the
        # node's defaults): apply the shown look, fitted to the shot, then adjust it, keeping
        # the slider the artist just moved.
        LAST_FIT.clear()
        with _Busy():
            try:
                fit(n)
            except ValueError:
                _plain(n, PRESETS[n["preset"].value()])
        rebase(n, centre=False)
        b = json.loads(n["easy_base"].value())
    with _Busy():
        _apply_sliders(n, b)
    show_visibility(n)


def _apply_sliders(n, b):
    s = n["look_strength"].value()
    e = dict((name, n[name].value()) for name, _, _ in SLIDERS)

    # Exposure: the haze light's brightness in stops, on top of the look's.
    if n.knob("easy_exposure"):
        n["haze_color_gain"].setValue(b.get("haze_color_gain", 1.0) * 2.0 ** n["easy_exposure"].value())

    # Haze: thickness.
    n["haze_amount"].setValue(b["haze_amount"] * e["easy_haze"] * s)

    # Warmth: orange or blue haze light, and less or more blue sky light in it. Shadow past
    # the middle also takes sky light out of the shadowed air.
    w = e["easy_warmth"]
    sd = e["easy_shadow"]
    tint = b["haze_tint"] if isinstance(b["haze_tint"], list) else [b["haze_tint"]] * 3
    n["haze_tint"].setValue([tint[0] * (1.0 + 0.6 * w), tint[1] * (1.0 + 0.1 * w), tint[2] * (1.0 - 0.6 * w)])
    n["sky_scatter"].setValue(b["sky_scatter"] * (1.0 - 0.4 * w) * (1.0 - 0.4 * max(sd - 1.0, 0.0)))

    # Shadow: below the middle the lost sunlight is put back (lighter shadows).
    fill = b["shadow_fill"] if isinstance(b["shadow_fill"], list) else [b["shadow_fill"]] * 3
    if sd < 1.0:
        n["shadow_fill"].setValue([c + (1.0 - c) * (1.0 - sd) for c in fill])
    else:
        n["shadow_fill"].setValue([c * max(2.0 - sd, 0.0) for c in fill])

    # Glow and shafts: the sunlit haze, and how hard the terrain cuts it.
    g = e["easy_glow"]
    sh = e["easy_shafts"]
    sun = b["sun_scatter"] * g ** 1.5
    if sh <= 1.0:
        n["shadow_strength"].setValue(b["shadow_strength"] * sh)
        n["penumbra"].setValue(b["penumbra"])
    else:
        # Past the middle: full shadows, crisper edges, brighter sunlit air between them.
        n["shadow_strength"].setValue(1.0)
        n["penumbra"].setValue(b["penumbra"] / (1.0 + 2.0 * (sh - 1.0)))
        sun *= 1.0 + (sh - 1.0)
    n["sun_scatter"].setValue(sun)

    # Light: the sunlight falling on the terrain itself, added to the plate.
    li = e["easy_light"]
    n["surface_add"].setValue(li > 0)
    if b.get("surface_add"):
        n["surface_strength"].setValue(b.get("surface_strength", 1.0) * li)
    else:
        # The look had none: the slider starts at 0 and adds it.
        n["surface_strength"].setValue(li)

    # Fog: denser and deeper (it rises up the valleys), or some where the look has none.
    f = e["easy_fog"]
    if b["fog_density"] > 0:
        n["fog_density"].setValue(b["fog_density"] * f * f * s)
    else:
        n["fog_density"].setValue(2.0 / max(b["scale"], 1e-3) * max(f - 1.0, 0.0) * s)
    top = b["fog_top"] if b["fog_top"] > b["low"] else b["valley"]
    rise = 0.35 * (f - 1.0) * b["relief"]
    n["fog_top"].setValue(top + rise + e["easy_fog_height"] * b["relief"])
    soft = b["fog_softness"]
    if b["fog_density"] <= 0 and f > 1.0:
        soft = max(soft, 0.25 * b["relief"])
    n["fog_softness"].setValue(soft * e["easy_fog_softness"])

    # Texture: how much the noise breaks up the fog and the haze, the size of its patches,
    # how much fine detail they carry and how crisp their edges are.
    t = e["easy_texture"]
    amount = b["noise_amount"] if b["noise_amount"] > 0 else 0.5
    n["noise_amount"].setValue(min(amount * t, 3.0) * s)
    n["noise_on_haze"].setValue(min(max(b["noise_on_haze"], 0.1) * t ** 1.5, 1.0))
    n["noise_size"].setValue(b["noise_size"] * e["easy_texture_scale"])
    detail = e["easy_texture_detail"]
    n["noise_detail"].setValue(int(round(min(max(b.get("noise_detail", 4) + 2.0 * (detail - 1.0), 1), 8))))
    n["noise_roughness"].setValue(min(max(b.get("noise_roughness", 0.5) + 0.15 * (detail - 1.0), 0.3), 0.8))
    n["noise_sharpness"].setValue(b.get("noise_sharpness", 1.0) + 2.5 * e["easy_texture_sharpness"])
    textured = t != 1.0 or e["easy_texture_scale"] != 1.0 or detail != 1.0 or e["easy_texture_sharpness"] != 0.0
    if (textured or n["fog_density"].value() > 0) and n["haze_mode"].getValue() == 0:
        n["haze_mode"].setValue("Volumetric")


def apply_look(n):
    """Apply the picked preset fitted to the shot, then start Easy from it."""
    LAST_FIT.clear()
    with _Busy():
        summary = apply_preset(n)
    rebase(n)
    return summary


def _backlight(n):
    """How much the sun can give glow and shafts in this shot, 0 to 1: 1 with the sun low
    (under 12 deg) and in front of the camera, falling to 0 beside, behind or high. 0.5 when it
    can't be told (no atmos, camera or sun)."""
    atmos, cam = _atmos(n), _camera(n)
    if atmos is None or cam is None or not cam.knob("world_matrix"):
        return 0.5
    knob = atmos.knob("sun_in_use") or atmos.knob("sun_direction")
    if knob is None:
        return 0.5
    sun = list(knob.value())
    ln = math.sqrt(sum(x * x for x in sun)) or 1.0
    sun = [x / ln for x in sun]
    wm = cam["world_matrix"]
    yaw = math.atan2(-wm.getValue(2), wm.getValue(10))
    az = math.degrees(math.atan2(sun[0], -sun[2]) - yaw)
    az = abs((az + 180.0) % 360.0 - 180.0)
    elev = math.degrees(math.asin(max(-1.0, min(1.0, sun[1]))))
    front = max(0.0, min(1.0, (90.0 - az) / 60.0))
    low = max(0.0, min(1.0, (25.0 - elev) / 13.0)) if elev > -3.0 else 0.3
    return front * low


def _frame_stats(n, grid=(10, 6)):
    """Mean and spread of the luminance of the terrain in frame (pixels with depth, short of
    the sky), from a coarse grid of samples of the node's output."""
    plate = n.input(0)
    if plate is None:
        return None
    channel = n["depth_channel"].value()
    threshold = n["sky_threshold"].value()
    lums = []
    for j in range(grid[1]):
        for i in range(grid[0]):
            x = plate.format().width() * (i + 0.5) / grid[0]
            y = plate.format().height() * (j + 0.5) / grid[1]
            dv = plate.sample(channel, x, y)
            if dv <= 0 or dv >= threshold:
                continue
            lums.append(0.2126 * n.sample("red", x, y) + 0.7152 * n.sample("green", x, y) +
                        0.0722 * n.sample("blue", x, y))
    if len(lums) < 4:
        return None
    mean = sum(lums) / len(lums)
    spread = math.sqrt(sum((v - mean) ** 2 for v in lums) / len(lums))
    return mean, spread


def surprise(n):
    """Random slider values within tasteful limits, scaled by 'surprise strength', weighed by
    the shot: glow and shafts only reach far when the sun is low and in front, and each pick
    is checked on the image. A pick that makes the terrain more than about a third brighter or
    darker than the look, or washes out its contrast, is tried again (up to 6 times, then the
    best one is kept)."""
    b = _base(n)
    k = n["surprise_strength"].value()
    middles = dict((s, m) for s, m, _ in SLIDERS)
    sunny = _backlight(n)
    # Sun-driven sliders: their reach shrinks when the sun can't show them.
    reach = {"easy_glow": 0.3 + 0.7 * sunny, "easy_shafts": 0.3 + 0.7 * sunny}
    with _Busy():
        for name, _, _ in SLIDERS:
            n[name].setValue(_neutral(name, b))
    apply_easy(n)
    base_stats = _frame_stats(n) if nuke.GUI else None
    best = None
    for attempt in range(6 if base_stats else 1):
        # Later tries stay closer to the look.
        k_try = k * (1.0 - 0.12 * attempt)
        picks = {}
        with _Busy():
            for name, _, (lo, hi) in SLIDERS:
                mid = _neutral(name, b)
                v = mid + (random.uniform(lo, hi) - middles[name]) * k_try * reach.get(name, 1.0)
                knob = n[name]
                v = min(max(v, knob.min()), knob.max()) if hasattr(knob, "min") else v
                picks[name] = round(v, 2)
                knob.setValue(picks[name])
        apply_easy(n)
        if base_stats is None:
            return picks
        stats = _frame_stats(n)
        if stats is None:
            return picks
        brightness = abs(math.log(max(stats[0], 1e-6) / max(base_stats[0], 1e-6)))
        contrast = stats[1] / max(base_stats[1], 1e-6)
        score = brightness + max(0.0, 0.7 - contrast)
        if best is None or score < best[0]:
            best = (score, picks)
        if brightness < 0.3 and contrast > 0.7:
            return picks
    with _Busy():
        for name, v in best[1].items():
            n[name].setValue(v)
    apply_easy(n)
    return best[1]


def match_plate(n, grid=(24, 14)):
    """Set 'exposure' so the haze over the farthest terrain in this frame is as bright as the
    plate's sky just above it (the sky the terrain should fade into), or, with no sky in frame,
    as the plate's highlights (its 90th percentile). Returns what it did."""
    plate = n.input(0)
    if plate is None:
        raise ValueError("connect a plate with depth first")
    channel = n["depth_channel"].value()
    threshold = n["sky_threshold"].value()
    inverse = n["depth_type"].getValue() == 2
    fmt = plate.format()
    terrain, sky_low = [], []
    for i in range(grid[0]):
        x = fmt.width() * (i + 0.5) / grid[0]
        column_sky = []
        for j in range(grid[1]):
            y = fmt.height() * (j + 0.5) / grid[1]
            dv = plate.sample(channel, x, y)
            lum = 0.2126 * plate.sample("red", x, y) + 0.7152 * plate.sample("green", x, y) + \
                0.0722 * plate.sample("blue", x, y)
            if dv <= 0 or dv >= threshold:
                column_sky.append((y, lum))
            else:
                dist = 1.0 / dv if inverse else dv
                haze = 0.2126 * n.sample("haze_inscatter.red", x, y) + \
                    0.7152 * n.sample("haze_inscatter.green", x, y) + 0.0722 * n.sample("haze_inscatter.blue", x, y)
                terrain.append((dist, lum, haze))
        if column_sky:
            # The lowest sky in the column: what the farthest terrain meets.
            sky_low.append(min(column_sky)[1])
    if len(terrain) < 6:
        raise ValueError("not enough terrain in frame to match")
    terrain.sort()
    far = terrain[int(len(terrain) * 0.8):]
    have = sorted(t[2] for t in far)[len(far) // 2]
    if len(sky_low) >= 3:
        target = sorted(sky_low)[len(sky_low) // 2]
        what = "the plate's sky just above the terrain"
    else:
        lums = sorted(t[1] for t in terrain)
        target = lums[int(len(lums) * 0.9)]
        what = "the plate's highlights (no sky in frame)"
    if have <= 1e-6 or target <= 1e-6:
        raise ValueError("the haze or the plate is black here: nothing to match")
    current = n["easy_exposure"].value()
    stops = min(max(current + math.log(target / have, 2.0), -4.0), 4.0)
    n["easy_exposure"].setValue(round(stops, 2))
    apply_easy(n)
    return "Exposure %+.2f stops: the haze over the farthest terrain now matches %s." % (stops, what)


def reset_sliders(n):
    """Centre the sliders: back to the base look."""
    b = _base(n)
    with _Busy():
        for name, _, _ in SLIDERS:
            n[name].setValue(_neutral(name, b))
        n["look_strength"].setValue(1.0)
    apply_easy(n)


def reset_look(n):
    """Every look knob back to the node's defaults, the sliders centred and the base cleared.
    The plate settings (depth channel, type, units, sky depth) stay as they are."""
    with _Busy():
        for name, script in DEFAULTS.items():
            if n.knob(name):
                n[name].fromScript(script)
        for name, _, _ in SLIDERS:
            n[name].setValue(_neutral(name, {"surface_add": n["surface_add"].value()}))
        n["look_strength"].setValue(1.0)
        if n.knob("easy_exposure"):
            n["easy_exposure"].setValue(0.0)
        n["easy_base"].setValue("")
    show_visibility(n)
    easy_message("Look reset to the node's defaults. Pick a look, or press apply, to start again.")


def on_knob(n, k):
    """knobChanged, for a knob easy mode looks after (only from the open panel)."""
    if k == "preset":
        apply_look(n)
    elif k in ("vis_near", "vis_far", "vis_fog"):
        set_visibility(n, k)
    elif k in EASY_KNOBS:
        apply_easy(n)
    elif k in LOOK_KNOBS:
        # An artist tuned an advanced knob by hand: that becomes Easy's starting point.
        rebase(n)


# Scene units analyze offers when it can't tell them from the atmos node: (label, metres).
SCENE_UNITS = [("Metres", 1.0), ("Decimetres", 0.1), ("Centimetres", 0.01), ("Millimetres", 0.001),
               ("Feet", 0.3048), ("Inches", 0.0254)]


def _scene_units(n, atmos, atmos_scale, raw):
    """Set 'units to metres' and say how. The depth values alone can't tell decimetres from
    metres, so: the atmos node's units when they are set there (not 1); else, once per node,
    ask (with the median depth shown in each unit); else keep the node's own."""
    if atmos_scale is not None and abs(atmos_scale - 1.0) > 1e-9:
        n["depth_scale"].setValue(atmos_scale)
        return "Units to metres %g, from %s." % (atmos_scale, atmos.name())
    current = n["depth_scale"].value()
    if n["units_confirmed"].value() or not nuke.GUI:
        return "Units to metres %g (kept; change 'units to metres' if the scene isn't in that)." % current
    median = raw[len(raw) // 2]
    if n["depth_type"].getValue() == 2:
        median = 1.0 / median
    options = ["%s: median depth %.3g km" % (label, median * m / 1000.0) for label, m in SCENE_UNITS]
    default = 0
    for i, (_, m) in enumerate(SCENE_UNITS):
        if abs(m - current) < 1e-9:
            default = i
    pick = None
    try:
        pick = nuke.choice("EzDepthHaze analyze", "What units is the scene's depth in?", options, default)
    except Exception:
        pick = None
    if pick is None or pick < 0:
        return "Units to metres %g (kept)." % current
    label, scale = SCENE_UNITS[pick]
    n["depth_scale"].setValue(scale)
    n["units_confirmed"].setValue(True)
    line = "Units to metres %g: the scene is in %s (you picked it)." % (scale, label.lower())
    if atmos is not None and atmos.knob("scene_scale"):
        atmos["scene_scale"].setValue(scale)
        line += " %s's units to metres set to match." % atmos.name()
    return line


def analyze(n):
    """Check the inputs and set up the plate, then say what was set and what to look at."""
    done, warn = [], []
    cam = _camera(n)
    if cam is None and n["plate_type"].getValue() == 0:
        warn.append("No camera in the 'camera' input (Dots and NoOps are fine).")
    atmos = _atmos(n)
    atmos_scale = None
    if atmos is None:
        warn.append("No EzAtmosScatter in 'atmos': the haze uses the flat haze colour and density.")
    elif atmos.knob("scene_scale"):
        atmos_scale = atmos["scene_scale"].value()
    plate = n.input(0)
    if plate is None:
        raise ValueError("connect a plate with depth first")
    raw = []
    for j in range(12):
        for i in range(20):
            v = plate.sample(n["depth_channel"].value(), plate.bbox().x() + (i + 0.5) / 20.0 * plate.width(),
                             plate.bbox().y() + (j + 0.5) / 12.0 * plate.height())
            if v > 0:
                raw.append(v)
    if not raw:
        raise ValueError("no depth in %s: pick the right depth channel" % n["depth_channel"].value())
    raw.sort()
    if raw[len(raw) // 2] < 0.01 and n["depth_type"].getValue() != 2:
        n["depth_type"].setValue("1/Z")
        done.append("The depth looks like 1/Z (Nuke's ScanlineRender): depth type set to 1/Z.")
    done.append(_scene_units(n, atmos, atmos_scale, raw))
    if n["sky_handling"].value() != "Haze Sky":
        n["sky_handling"].setValue("Haze Sky")
        done.append("Sky: Haze Sky, so the sky fades into the haze like the terrain.")
    if cam is not None or n["plate_type"].getValue() == 1:
        m = measure(n)
        threshold = n["sky_threshold"].value()
        open_sky = m["pixels"] - len([x for x in m["raw"] if x < threshold])
        if m["depth_type"] != 2 and open_sky < 0.02 * m["pixels"]:
            backdrop = find_backdrop(m["raw"], threshold)
            if backdrop is not None:
                n["sky_threshold"].setValue(round(backdrop, 3))
                done.append("Found a sky dome or card behind the terrain: sky depth %.6g." % backdrop)
        st = _stats(m, n["sky_threshold"].value())
        done.append("Terrain %.1f-%.1f km away; camera %.0f m above the lowest of it."
                    % (st["dist"][0] / 1000.0, st["dist"][2] / 1000.0, st["camera"] - st["alt"][0]))
        offer = sun_suggestion(n, PRESETS[n["preset"].value()])
        if offer is not None:
            warn.append(offer[0].split("\n\n")[0])
    text = "\n".join(done + ([""] + ["Note: " + w for w in warn] if warn else []))
    easy_message("EzDepthHaze analyze\n\n" + text)
    return text


# ---- Looks on disk -----------------------------------------------------------------------

def look_dir(n, where):
    """The User or Studio looks folder: its environment variable when set, else the node's
    hidden folder knob, else the default from python/ezdepthhaze.py."""
    d = os.environ.get(LOOK_DIRS[where]["env"])
    knob = n.knob(where.lower() + "_looks_dir")
    if not d and knob is not None:
        d = knob.value()
    d = (d or LOOK_DIRS[where]["path"]).strip()
    # $VAR and ${VAR} are environment variables (Tcl would read them as its own variables);
    # an unset one stays as $VAR, which look_dir_problem reports.
    d = re.sub(r"\$\{?(\w+)\}?", lambda m: os.environ.get(m.group(1), "$" + m.group(1)), d)
    if "[" in d:
        # Tcl, such as [getenv SHOW]; its error names an unset variable as $SHOW.
        try:
            d = nuke.tcl("subst", d)
        except RuntimeError as e:
            d = str(e)
    return os.path.expanduser(d) if d else ""


def look_dir_problem(d):
    """Why a looks folder can't be used, or None. An unset variable leaves '$NAME' in the path
    (or, through [getenv], Tcl's error text), and a relative path would land wherever Nuke was
    started from."""
    m = re.search(r"\$\{?(\w+)", d)
    if m:
        return "$%s isn't set in Nuke" % m.group(1)
    if not os.path.isabs(d):
        return "it isn't a full path"
    return None


def list_looks(n):
    """'User: name' / 'Studio: name' for every saved look."""
    names = []
    for where in ("User", "Studio"):
        d = look_dir(n, where)
        if d and not look_dir_problem(d) and os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(".json"):
                    names.append("%s: %s" % (where, f[:-5]))
    return names


def refresh_look_menu(n):
    looks = list_looks(n)
    n["my_looks"].setValues(looks or ["(no saved looks)"])
    return looks


def _backup(path):
    """Keep a dated copy of a look in the folder's .backup subfolder before it changes."""
    if not os.path.isfile(path):
        return None
    import shutil
    import time
    folder = os.path.join(os.path.dirname(path), ".backup")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    name = os.path.splitext(os.path.basename(path))[0]
    stamp = time.strftime("%Y%m%d_%H%M%S")
    copy = os.path.join(folder, "%s_%s.json" % (name, stamp))
    i = 1
    while os.path.exists(copy):
        i += 1
        copy = os.path.join(folder, "%s_%s_%d.json" % (name, stamp, i))
    shutil.copy2(path, copy)
    return copy


def _picked(n):
    label = n["my_looks"].value()
    if ": " not in label:
        raise ValueError("pick a saved look first")
    where, name = label.split(": ", 1)
    return os.path.join(look_dir(n, where), name + ".json")


def save_look(n):
    name = n["look_name"].value().strip()
    where = n["save_to"].value()
    d = look_dir(n, where)
    if not name:
        raise ValueError("type a look name first")
    if not d:
        raise ValueError("no %s looks folder: set the %s looks folder knob or $%s"
                         % (where.lower(), where.lower(), LOOK_DIRS[where]["env"]))
    problem = look_dir_problem(d)
    if problem:
        raise ValueError("can't save to the %s looks folder '%s': %s" % (where.lower(), d, problem))
    if not os.path.isdir(d):
        try:
            os.makedirs(d)
        except OSError as e:
            raise ValueError("can't create the %s looks folder '%s' (%s): ask for it to be made "
                             "writable, or pick another folder" % (where.lower(), d, e.strerror or e))
    if not os.access(d, os.W_OK):
        raise ValueError("can't write to the %s looks folder '%s'" % (where.lower(), d))
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
    path = os.path.join(d, safe + ".json")
    _backup(path)
    look = {"name": name, "preset": n["preset"].value(),
            "knobs": dict((k, _value(n, k)) for k in LOOK_KNOBS if n.knob(k))}
    with open(path, "w") as f:
        json.dump(look, f, indent=1)
    refresh_look_menu(n)
    return path


def load_look(n):
    """Apply the saved look picked in the menu."""
    path = _picked(n)
    with open(path) as f:
        look = json.load(f)
    with _Busy():
        for k, v in look["knobs"].items():
            if n.knob(k):
                n[k].setValue(v)
    rebase(n)
    return path


def delete_look(n):
    """Delete the saved look picked in the menu (after asking), keeping a backup."""
    path = _picked(n)
    if nuke.GUI and not nuke.ask("Delete the look '%s'?\n\nA copy is kept in %s."
                                 % (n["my_looks"].value(), os.path.join(os.path.dirname(path), ".backup"))):
        return None
    copy = _backup(path)
    os.remove(path)
    refresh_look_menu(n)
    return copy


def easy_message(text):
    if nuke.GUI:
        nuke.message(text)
    else:
        print(text)


# ---- Layer breakout ----------------------------------------------------------------------

def build_breakout(n):
    """Rebuild the node's result from its layers next to it, laid out as a merge trunk:

        plate (+ surface_sunlight) x haze_transmittance + haze_sun + haze_sky

    A row of Dots runs right from the node's output with a Shuffle under each; every layer
    drops down to a Dot level with its Merge on the trunk below the plate, and comes in from
    the right as the A input. A Difference against the node at the bottom shows it matches."""
    plate = n.input(0)
    if plate is None:
        raise ValueError("connect a plate first")
    col, step, gap = 180, 90, 34
    x0, y0 = n.xpos() + 250, n.ypos() + 60
    with nuke.root():
        for x in nuke.allNodes():
            x.setSelected(False)
        made = []

        def dot(src, x, y):
            d = nuke.nodes.Dot(xpos=x + gap, ypos=y + 4)
            d.setInput(0, src)
            made.append(d)
            return d

        layers = []
        if n["surface_add"].value():
            layers.append(("surface_sunlight", "plus"))
        layers += [("haze_transmittance", "multiply"), ("haze_sun", "plus"), ("haze_sky", "plus")]

        # The trunk: the plate, down the left column.
        trunk = dot(plate, x0, y0)
        # The row of Dots from the node's output, one column per layer.
        row = dot(n, x0 + col, y0)
        heads = [row]
        for i in range(1, len(layers)):
            row = dot(row, x0 + col * (i + 1), y0)
            heads.append(row)
        stream = trunk
        y = y0 + 160
        for i, ((layer, op), head) in enumerate(zip(layers, heads)):
            x = x0 + col * (i + 1)
            sh = nuke.nodes.Shuffle2(name="%s_%s" % (n.name(), layer), xpos=x, ypos=y0 + 70)
            sh.setInput(0, head)
            sh["in1"].setValue(layer)
            sh["label"].setValue("%s to rgba" % layer)
            made.append(sh)
            low = dot(sh, x, y)
            m = nuke.nodes.Merge2(operation=op, output="rgb", xpos=x0, ypos=y)
            m.setInput(0, stream)
            m.setInput(1, low)
            made.append(m)
            stream = m
            y += step
        # Check: the rebuild against the node, should be black.
        last = dot(heads[-1], x0 + col * (len(layers) + 1), y0)
        check_dot = dot(last, x0 + col * (len(layers) + 1), y)
        check = nuke.nodes.Merge2(name="%s_breakout_check" % n.name(), operation="difference", output="rgb",
                                  xpos=x0, ypos=y, label="should be black")
        check.setInput(0, stream)
        check.setInput(1, check_dot)
        made.append(check)
        bd = nuke.nodes.BackdropNode(label="%s breakout" % n.name(), note_font_size=24,
                                     xpos=x0 - 60, ypos=y0 - 70,
                                     bdwidth=col * (len(layers) + 1) + 160, bdheight=y - y0 + 160)
        for m in made:
            m.setSelected(True)
    return stream
