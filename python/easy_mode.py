"""Easy mode: a few big sliders over the advanced knobs, look thumbnails, and saved looks.

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
import tempfile

import nuke

# Filled in by build_gizmo.py from python/ezdepthhaze.py.
LOOK_DIRS = {}
LOOK_KNOBS = []

# Easy slider: (knob, neutral value, surprise range).
SLIDERS = [("easy_haze", 1.0, (0.6, 1.6)), ("easy_warmth", 0.0, (-0.6, 0.6)), ("easy_glow", 1.0, (0.6, 1.8)),
           ("easy_shafts", 1.0, (0.5, 1.4)), ("easy_fog", 1.0, (0.3, 2.0)), ("easy_fog_height", 0.0, (-0.5, 0.5)),
           ("easy_texture", 1.0, (0.3, 2.0))]
EASY_KNOBS = [name for name, _, _ in SLIDERS] + ["look_strength"]


def _value(n, name):
    v = n[name].value()
    return list(v) if isinstance(v, (list, tuple)) else v


def rebase(n, relief=None):
    """Make the advanced knobs' current values the base, and centre the sliders."""
    base = dict((k, _value(n, k)) for k in LOOK_KNOBS if n.knob(k))
    old = {}
    try:
        old = json.loads(n["easy_base"].value() or "{}")
    except ValueError:
        pass
    base["relief"] = relief or LAST_FIT.get("relief") or old.get("relief") or max(n["fog_softness"].value() * 3.0, 50.0)
    n["easy_base"].setValue(json.dumps(base))
    for name, neutral, _ in SLIDERS:
        n[name].setValue(neutral)
    n["look_strength"].setValue(1.0)


def apply_easy(n):
    """Rewrite the advanced knobs from the base and the sliders."""
    try:
        b = json.loads(n["easy_base"].value() or "{}")
    except ValueError:
        b = {}
    if not b:
        rebase(n)
        b = json.loads(n["easy_base"].value())
    s = n["look_strength"].value()
    e = dict((name, n[name].value()) for name, _, _ in SLIDERS)
    n["haze_amount"].setValue(b["haze_amount"] * e["easy_haze"] * s)
    n["fog_density"].setValue(b["fog_density"] * e["easy_fog"] * s)
    n["fog_top"].setValue(b["fog_top"] + e["easy_fog_height"] * b["relief"])
    n["noise_amount"].setValue(min(b["noise_amount"] * e["easy_texture"], 1.5) * s)
    n["sun_scatter"].setValue(b["sun_scatter"] * e["easy_glow"])
    n["shadow_strength"].setValue(min(max(b["shadow_strength"] * e["easy_shafts"], 0.0), 1.0))
    w = e["easy_warmth"]
    tint = b["haze_tint"] if isinstance(b["haze_tint"], list) else [b["haze_tint"]] * 3
    n["haze_tint"].setValue([tint[0] * (1.0 + 0.3 * w), tint[1] * (1.0 + 0.05 * w), tint[2] * (1.0 - 0.3 * w)])


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

def render_thumbnails(n, width=160):
    """A small render of every preset on this frame, shown on the look buttons.

    Renders a temporary copy of the node on a downsized plate, writes a JPEG per look to the
    temp folder and deletes the copy, so nothing stays in memory."""
    plate = n.input(0)
    if plate is None:
        raise ValueError("connect a plate first")
    folder = os.path.join(tempfile.gettempdir(), "ezdepthhaze_thumbs")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    keep = [x for x in nuke.selectedNodes()]
    for x in nuke.allNodes():
        x.setSelected(False)
    n.setSelected(True)
    clip = os.path.join(folder, "_copy.nk")
    nuke.nodeCopy(clip)
    n.setSelected(False)
    copy = nuke.nodePaste(clip)
    os.remove(clip)
    small = nuke.nodes.Reformat(type="scale", filter="Impulse")
    small["scale"].setValue(float(width) / max(plate.width(), 1))
    small.setInput(0, plate)
    copy.setInput(0, small)
    for i in (1, 2):
        copy.setInput(i, n.input(i))
    copy["show_before"].setValue(False)
    out = nuke.nodes.Write(file_type="jpeg", channels="rgb")
    out["colorspace"].setValue("sRGB")
    out.setInput(0, copy)
    paths = []
    try:
        for i, name in enumerate(n["preset"].values()):
            copy["preset"].setValue(name)
            try:
                fit(copy, name)
            except ValueError:
                _plain(copy, PRESETS[name])
            path = os.path.join(folder, "%s_%d.jpg" % (n.name(), i)).replace("\\", "/")
            out["file"].setValue(path)
            nuke.execute(out, nuke.frame(), nuke.frame())
            paths.append(path)
            knob = n.knob("look_%d" % i)
            if knob is not None:
                knob.setLabel("<img src=\"%s\"><br>%s" % (path, name))
    finally:
        for x in (out, copy, small):
            nuke.delete(x)
        for x in keep:
            x.setSelected(True)
    return paths


def easy_message(text):
    if nuke.GUI:
        nuke.message(text)
    else:
        print(text)
