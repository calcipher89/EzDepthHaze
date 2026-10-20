# EzDepthHaze

Depth haze for The Foundry Nuke, built in BlinkScript. A companion to
[EZ-Atmos-Scatter](https://github.com/calcipher89/EZ-Atmos-Scatter): it hazes a plate or
CG render using its depth, lit by the same atmosphere.

Target: Nuke 15.1.

## Installing

Clone the repo into `~/.nuke/plugins/EzDepthHaze` and add this line to `~/.nuke/init.py`:

```python
nuke.pluginAddPath('./plugins/EzDepthHaze')
```

The node then shows up under **Nodes > EzDepthHaze**.

## Using it

1. Connect the render or plate to `plate`, with its depth in a channel (`depth.Z` by
   default; pick another with *depth channel*).
2. For a perspective render, connect its Camera to `camera`. For a 360 lat-long render, set
   *plate* to *Lat-long* and type the *camera height*.
3. Connect an EzAtmosScatter node to `atmos`. Its `atmos_haze_color` layer (the colour
   infinitely deep haze has in each direction) lights the haze, and with *inherit from
   atmos* on, its haze density, haze height and hdri rotation are used too. Without an atmos
   input, set *haze color* and *haze density* yourself.

For each pixel:

```
tau    = density * H / c * (exp(-c * start / H) - exp(-c * distance / H)),  c = view dir.y
T      = exp(-tau)
result = plate * T + hazeColor(view dir) * (1 - T)
```

The haze thins with altitude over the haze height H, so looking up clears faster than
looking sideways and looking down into a valley gets thicker. The output keeps every
channel of the plate and adds `haze_transmittance` and `haze_inscatter` layers.

### Knobs

| Knob | Default | What it does |
| --- | --- | --- |
| view output | Hazed Plate | Hazed Plate, Haze Transmittance or Haze In-scatter in rgb |
| plate | Camera | Camera (perspective, uses the `camera` input) or Lat-long |
| depth channel | depth.Z | Where the depth is |
| depth type | Distance | Distance from the camera, Planar Z (along the view axis) or 1/Z (ScanlineRender) |
| units to metres | 1 | Depth multiplier, e.g. 0.01 for centimetres |
| camera height (m) | 1 | Camera height for lat-long plates |
| sky | Leave Sky | Pixels with no depth: leave them, or haze them as if *sky distance* away |
| sky distance (km) | 50 | Distance used for sky pixels with Haze Sky |
| sky depth | 1e7 | Depth at or beyond which a pixel counts as sky |
| inherit from atmos | on | Take haze density, haze height and rotation from the EzAtmosScatter input |
| haze color from | Atmos Input | The atmos lat-long, looked up per view direction, or a flat colour |
| atmos layer | atmos_haze_color | Layer of the atmos input to use (rgba for a plain lat-long) |
| haze color | (0.6, 0.65, 0.75) | Flat haze colour |
| haze brightness | 1 | Multiplies the haze colour |
| haze density (1/m) | 0.0001 | Extinction per metre at camera height, when not inheriting |
| haze amount | 1 | Multiplies the density |
| haze height (km) | 1.2 | Height over which the haze thins by about two thirds, when not inheriting |
| haze start (m) | 0 | Distance where the haze begins |
| max distance (km) | 0 | Caps the hazed distance (0 = off) |
| atmos rotation | 0 | Rotation of the atmos lat-long, when not inheriting |

## Demo

`examples/DemoTerrain.blink` renders a procedural mountain range through a Nuke camera,
with distance in alpha, so the node can be tried without a CG render.

## Rebuilding the gizmo

```
Nuke15.1.exe --nukex -i -t python/build_gizmo.py
```
