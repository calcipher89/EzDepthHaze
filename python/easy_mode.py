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
            for name, neutral, _ in SLIDERS:
                n[name].setValue(neutral)
            n["look_strength"].setValue(1.0)
    show_visibility(n)


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
    if b.get("surface_add"):
        n["surface_add"].setValue(li > 0)
        n["surface_strength"].setValue(b.get("surface_strength", 1.0) * li)
    else:
        n["surface_add"].setValue(li > 1.0)
        n["surface_strength"].setValue(max(li - 1.0, 0.0))

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
    """Random slider values within tasteful limits."""
    with _Busy():
        for name, _, (lo, hi) in SLIDERS:
            n[name].setValue(round(random.uniform(lo, hi), 2))
    apply_easy(n)


def reset_sliders(n):
    """Centre the sliders: back to the base look."""
    with _Busy():
        for name, neutral, _ in SLIDERS:
            n[name].setValue(neutral)
        n["look_strength"].setValue(1.0)
    apply_easy(n)


def reset_look(n):
    """Every look knob back to the node's defaults, the sliders centred and the base cleared.
    The plate settings (depth channel, type, units, sky depth) stay as they are."""
    with _Busy():
        for name, script in DEFAULTS.items():
            if n.knob(name):
                n[name].fromScript(script)
        for name, neutral, _ in SLIDERS:
            n[name].setValue(neutral)
        n["look_strength"].setValue(1.0)
        n["easy_base"].setValue("")
    show_visibility(n)
    easy_message("Look reset to the node's defaults. Pick a look, or press apply, to start again.")


def on_knob(n, k):
    """knobChanged, for a knob easy mode looks after (only from the open panel)."""
    if k == "preset":
        apply_look(n)
    elif k == "my_looks":
        load_look(n)
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

def look_dir(where):
    d = os.environ.get(LOOK_DIRS[where]["env"]) or LOOK_DIRS[where]["path"]
    return os.path.expanduser(d) if d else ""


def list_looks():
    """'User: name' / 'Studio: name' for every saved look."""
    names = []
    for where in ("User", "Studio"):
        d = look_dir(where)
        if d and os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(".json"):
                    names.append("%s: %s" % (where, f[:-5]))
    return names


def refresh_look_menu(n):
    looks = list_looks()
    n["my_looks"].setValues(looks or ["(no saved looks)"])
    return looks


def save_look(n):
    name = n["look_name"].value().strip()
    where = n["save_to"].value()
    d = look_dir(where)
    if not name:
        raise ValueError("type a look name first")
    if not d:
        raise ValueError("no %s looks folder: set $%s" % (where.lower(), LOOK_DIRS[where]["env"]))
    if not os.path.isdir(d):
        os.makedirs(d)
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
    path = os.path.join(d, safe + ".json")
    look = {"name": name, "preset": n["preset"].value(),
            "knobs": dict((k, _value(n, k)) for k in LOOK_KNOBS if n.knob(k))}
    with open(path, "w") as f:
        json.dump(look, f, indent=1)
    refresh_look_menu(n)
    return path


def load_look(n, label=None):
    label = label or n["my_looks"].value()
    if ": " not in label:
        return None
    where, name = label.split(": ", 1)
    path = os.path.join(look_dir(where), name + ".json")
    with open(path) as f:
        look = json.load(f)
    with _Busy():
        for k, v in look["knobs"].items():
            if n.knob(k):
                n[k].setValue(v)
    rebase(n)
    return path




def easy_message(text):
    if nuke.GUI:
        nuke.message(text)
    else:
        print(text)
