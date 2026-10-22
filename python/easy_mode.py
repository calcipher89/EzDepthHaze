"""Easy mode: a few big sliders over the advanced knobs, and saved looks.

build_gizmo.py embeds this file after fit_to_shot.py in the gizmo's knobChanged and buttons
(one shared namespace), with LOOK_DIRS and LOOK_KNOBS filled in, so Nuke needs no Python
module at run time.

The sliders are relative to a base look kept in the hidden easy_base knob: the preset as
fitted to the shot, a loaded look, or whatever the advanced knobs held when 'advanced' was
turned off. Every slider change rewrites the advanced knobs from the base, so turning
'advanced' on shows exactly what Easy did, ready to fine-tune.
"""
import json
import os
import random

import nuke

# Filled in by build_gizmo.py from python/ezdepthhaze.py.
LOOK_DIRS = {}
LOOK_KNOBS = []

# Easy slider: (knob, neutral value, surprise range).
SLIDERS = [("easy_haze", 1.0, (0.6, 1.6)), ("easy_warmth", 0.0, (-0.6, 0.6)), ("easy_glow", 1.0, (0.6, 1.8)),
           ("easy_shafts", 1.0, (0.5, 1.4)), ("easy_fog", 1.0, (0.3, 2.0)), ("easy_fog_height", 0.0, (-0.5, 0.5)),
           ("easy_fog_softness", 1.0, (0.4, 1.6)), ("easy_texture", 1.0, (0.3, 2.0)),
           ("easy_texture_scale", 1.0, (0.4, 1.6)), ("easy_texture_detail", 1.0, (0.5, 1.8)),
           ("easy_texture_sharpness", 0.0, (0.0, 1.5))]
EASY_KNOBS = [name for name, _, _ in SLIDERS] + ["look_strength"]


def _value(n, name):
    v = n[name].value()
    return list(v) if isinstance(v, (list, tuple)) else v


def rebase(n, relief=None, centre=True):
    """Make the advanced knobs' current values the base, and centre the sliders."""
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
        try:
            fit(n)
        except ValueError:
            _plain(n, PRESETS[n["preset"].value()])
        rebase(n, centre=False)
        b = json.loads(n["easy_base"].value())
    s = n["look_strength"].value()
    e = dict((name, n[name].value()) for name, _, _ in SLIDERS)

    # Haze: thickness.
    n["haze_amount"].setValue(b["haze_amount"] * e["easy_haze"] * s)

    # Warmth: orange or blue haze light, and less or more blue sky light in it.
    w = e["easy_warmth"]
    tint = b["haze_tint"] if isinstance(b["haze_tint"], list) else [b["haze_tint"]] * 3
    n["haze_tint"].setValue([tint[0] * (1.0 + 0.6 * w), tint[1] * (1.0 + 0.1 * w), tint[2] * (1.0 - 0.6 * w)])
    n["sky_scatter"].setValue(b["sky_scatter"] * (1.0 - 0.4 * w))

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
    if textured and n["haze_mode"].getValue() == 0:
        n["haze_mode"].setValue("Volumetric")


def apply_look(n):
    """Apply the picked preset fitted to the shot, then start Easy from it."""
    LAST_FIT.clear()
    summary = apply_preset(n)
    rebase(n)
    return summary


def surprise(n):
    """Random slider values within tasteful limits."""
    for name, _, (lo, hi) in SLIDERS:
        n[name].setValue(round(random.uniform(lo, hi), 2))
    apply_easy(n)


def reset_sliders(n):
    """Centre the sliders: back to the base look."""
    for name, neutral, _ in SLIDERS:
        n[name].setValue(neutral)
    n["look_strength"].setValue(1.0)
    apply_easy(n)


def set_advanced(n, rebase_on_hide=True):
    """Show or hide the advanced knobs. Leaving advanced makes its values Easy's new base."""
    show = bool(n["advanced"].value())
    inside = False
    for k in n.allKnobs():
        if k.name() == "ezdepthhaze":
            inside = True
        elif k.Class() == "Tab_Knob" and k.name() != "ezdepthhaze":
            inside = False
        if inside:
            k.setVisible(show)
    if not show and rebase_on_hide and n["easy_base"].value():
        rebase(n)


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
    for k, v in look["knobs"].items():
        if n.knob(k):
            n[k].setValue(v)
    rebase(n)
    return path


# ---- Thumbnails --------------------------------------------------------------------------

def easy_message(text):
    if nuke.GUI:
        nuke.message(text)
    else:
        print(text)
