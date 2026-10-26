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
EASY_KNOBS = [name for name, _, _ in SLIDERS] + ["look_strength"]


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


def surprise(n):
    """Random slider values within tasteful limits, scaled by 'surprise strength'."""
    b = _base(n)
    k = n["surprise_strength"].value()
    with _Busy():
        for name, _, (lo, hi) in SLIDERS:
            mid = _neutral(name, b)
            v = mid + (random.uniform(lo, hi) - dict((s, m) for s, m, _ in SLIDERS)[name]) * k
            knob = n[name]
            v = min(max(v, knob.min()), knob.max()) if hasattr(knob, "min") else v
            knob.setValue(round(v, 2))
    apply_easy(n)


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


def analyze(n):
    """Check the inputs and set up the plate, then say what was set and what to look at."""
    done, warn = [], []
    cam = _camera(n)
    if cam is None and n["plate_type"].getValue() == 0:
        warn.append("No camera in the 'camera' input (Dots and NoOps are fine).")
    atmos = _atmos(n)
    if atmos is None:
        warn.append("No EzAtmosScatter in 'atmos': the haze uses the flat haze colour and density.")
    elif atmos.knob("scene_scale"):
        scale = atmos["scene_scale"].value()
        if abs(scale - n["depth_scale"].value()) > 1e-9:
            n["depth_scale"].setValue(scale)
            done.append("Units to metres %g, from %s." % (scale, atmos.name()))
        else:
            done.append("Units to metres %g (matches %s)." % (scale, atmos.name()))
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
