"""Depth scan: a coarse grid of distances and the camera, as plain text.

Prints only numbers: the camera's matrix and lens, and the distance in metres of a grid of
points across the frame (rounded, about 96 x 33). No colour, no pixels of the plate, no
names or paths. Paste the output to Claude to rebuild the shot's geometry in low resolution.

In Nuke: select the EzDepthHaze node, then in the Script Editor run
    exec(open(r"<folder>/ezhaze_depth_scan.py").read())
"""
import math
import nuke


def depth_scan(haze=None, columns=96):
    haze = haze or nuke.selectedNode()
    plate = haze.input(0)
    cam = haze.input(1)
    while cam is not None and not cam.knob("world_matrix"):
        cam = cam.input(0) if cam.inputs() else None
    if plate is None or cam is None:
        raise ValueError("connect the plate and camera to EzDepthHaze first")
    w, h = plate.width(), plate.height()
    hap, vap, focal = cam["haperture"].value(), cam["vaperture"].value(), cam["focal"].value()
    rows = max(int(round(columns * vap / hap)), 4)
    chan = haze["depth_channel"].value()
    scale = haze["depth_scale"].value()
    dtype = int(haze["depth_type"].getValue())
    m = cam["world_matrix"]
    lines = ["EZHAZE DEPTH SCAN v1",
             "frame %d" % nuke.frame(),
             "plate %d %d" % (w, h),
             "lens focal %.4f haperture %.4f vaperture %.4f" % (focal, hap, vap),
             "matrix " + " ".join("%.6g" % m.getValue(i) for i in range(16)),
             "units_to_metres %g" % scale,
             "grid %d %d (distance along the ray in metres, top row first; 0 = no depth)" % (columns, rows)]
    for j in range(rows - 1, -1, -1):
        row = []
        for i in range(columns):
            u, v = (i + 0.5) / columns, (j + 0.5) / rows
            raw = plate.sample(chan, plate.bbox().x() + u * w, plate.bbox().y() + v * h)
            if raw <= 0:
                row.append("0")
                continue
            planar = math.sqrt(((u - 0.5) * hap / focal) ** 2 + ((v - 0.5) * vap / focal) ** 2 + 1.0)
            dist = raw if dtype == 0 else raw * planar if dtype == 1 else planar / raw
            row.append("%d" % round(dist * scale))
        lines.append(" ".join(row))
    lines.append("END")
    text = "\n".join(lines)
    print(text)
    return text


if __name__ in ("__main__", "builtins"):
    depth_scan()
