"""How node_layout.py arranges the inside of EzDepthHaze: its modules and their Backdrops,
the side chains that go left of the trunk, and labels on the Switches."""

MODULES = [
    # (Backdrop label, tile_color, node names it holds as a regex), top to bottom
    ("Inputs", 0x4a5a6aff, r"plate|camera|atmos"),
    ("Cloud gaps", 0x444444ff, r"clouds|NoClouds|CloudsOrNone|AtmosCloudsPick|CloudGaps.*"),
    ("Haze light from atmos", 0x7a6a3aff,
     r"AtmosPick|AtmosSunPick|AtmosSkyPick|Layer(Sun|Sky)Share|Haze(Sun|Sky|Total)Light|AtmosHazeColorSafe|"
     r"AtmosSky.*|Haze(Sun|Sky)Tint"),
    ("Work resolution", 0x4a5a6aff, r"DepthPick|WorkDepth|WorkPlate"),
    ("Haze passes", 0x3a5a4aff, r"Pass_.*|Smooth_.*|Full_.*"),
    ("Silhouettes + surface", 0x3a5a4aff, r"Silhouette_.*|Surface(Visibility|Sunlight)|Wisps|FogShare"),
    ("Haze comp", 0x5a4a6aff, r"InScatter|FogInScatter|ShadowLoss|SurfaceAdd|PlatePlusSurface|PlateTimesT|Hazed"),
    # Its own band, so the thirteen pipes into it come in along rails rather than across the comp.
    ("View output", 0x5a4a6aff, r"ViewOutput"),
    ("AOV layers", 0x6a4a4aff, r"MainRGB|Layer_.*|ClipTo|Output\d*"),
]

LEFT = []

LABELS = {
    "CloudsOrNone": "gaps from",
    "HazeSunLight": "atmos layer",
    "HazeSkyLight": "atmos layer",
    "ViewOutput": "view output",
}

# The clouds input comes and goes with 'gaps from' and is wired straight in by the panel code.
DIRECT = ["CloudsOrNone"]

HINTS = {"modules": MODULES, "left": LEFT, "labels": LABELS, "direct": DIRECT}
