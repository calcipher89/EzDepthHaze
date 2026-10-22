"""Rebuild a shot's geometry, in low resolution, from an EzDepthHaze depth scan.

ezhaze_depth_scan.py prints a coarse grid of distances and the camera as plain text. This
turns that text back into a depth plate (distance in metres in depth.Z) and a matching
camera, so looks can be tuned on the shot's real layout without the shot leaving the studio.

Usage: Nuke15.1.exe --nukex -i --gpu -t examples/rebuild_depth_scan.py scan=<scan.txt> out=<folder>
Writes <folder>/scan_depth.hdr and <folder>/scan_rebuild.nk (plate, camera, EzDepthHaze).
"""
import math
import os
import struct
import sys

import nuke


def parse(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    start = next(i for i, l in enumerate(lines) if l.startswith("EZHAZE DEPTH SCAN"))
    info, grid = {}, []
    i = start + 1
    while i < len(lines) and not lines[i].startswith("grid"):
        key, _, rest = lines[i].partition(" ")
        info[key] = rest
        i += 1
    cols, rows = [int(v) for v in lines[i].split()[1:3]]
    for l in lines[i + 1:i + 1 + rows]:
        grid.append([float(v) for v in l.split()])
    lens = dict(zip(info["lens"].split()[0::2], [float(v) for v in info["lens"].split()[1::2]]))
    return {"cols": cols, "rows": rows, "grid": grid, "lens": lens,
            "matrix": [float(v) for v in info["matrix"].split()],
            "units": float(info.get("units_to_metres", "1")),
            "plate": [int(v) for v in info["plate"].split()]}


def write_hdr(path, grid):
    """A float image as Radiance RGBE (the distance in all three channels)."""
    rows, cols = len(grid), len(grid[0])
    with open(path, "wb") as f:
        f.write(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y %d +X %d\n" % (rows, cols))
        for row in grid:
            for v in row:
                if v <= 1e-32:
                    f.write(b"\0\0\0\0")
                    continue
                m, e = math.frexp(v)
                b = int(m * 256.0)
                f.write(struct.pack("BBBB", b, b, b, e + 128))


def build(scan, out):
    if not os.path.isdir(out):
        os.makedirs(out)
    hdr = os.path.join(out, "scan_depth.hdr").replace("\\", "/")
    write_hdr(hdr, scan["grid"])
    w = 1152
    h = int(round(w * scan["lens"]["vaperture"] / scan["lens"]["haperture"]))
    nuke.addFormat("%d %d 1 scan_format" % (w, h))
    read = nuke.nodes.Read(file=hdr, name="ScanDepth")
    up = nuke.nodes.Reformat(type="to format", format="scan_format", resize="distort", filter="Cubic")
    up.setInput(0, read)
    # A dull, even surface as the plate; EzDepthHaze lights it from the rebuilt normals.
    plate = nuke.nodes.Expression(name="ScanPlate", expr0="0.03", expr1="0.035", expr2="0.025", expr3="1",
                                  channel0="rgba")
    plate.setInput(0, up)
    depth = nuke.nodes.Copy(name="ScanToDepth", from0="rgba.red", to0="depth.Z")
    depth.setInput(0, plate)
    depth.setInput(1, up)
    m = scan["matrix"]
    cam = nuke.nodes.Camera3(name="ScanCamera")
    cam["useMatrix"].setValue(True)
    # The scan's matrix is in scene units; the rebuild works in metres.
    mm = list(m)
    for k in (3, 7, 11):
        mm[k] *= scan["units"]
    cam["matrix"].setValue(mm)
    for k in ("focal", "haperture", "vaperture"):
        cam[k].setValue(scan["lens"][k])
    haze = nuke.createNode("EzDepthHaze")
    haze.setName("ScanHaze")
    haze.setInput(0, depth)
    haze.setInput(1, cam)
    haze["depth_type"].setValue("Distance")
    haze["depth_scale"].setValue(1.0)
    haze["surface_add"].setValue(True)
    haze["albedo_from"].setValue("Constant")
    nuke.scriptSaveAs(os.path.join(out, "scan_rebuild.nk").replace("\\", "/"), overwrite=1)
    return haze


if __name__ == "__main__":
    args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
    with open(args["scan"]) as f:
        build(parse(f.read()), args.get("out", os.path.dirname(args["scan"])))
    print("REBUILT")
