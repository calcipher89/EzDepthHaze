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

## Fog and noise

Set *mode* to *Volumetric* to march each ray, so the density can change along it:

- **Fog layer**: fills everything below *fog top* (an altitude in metres) with *fog density*,
  fading out over *fog softness*. Set the top a few hundred metres above the valley floors
  and the fog pools in the valleys, with each ridge standing out in front of the next.
- **Noise**: 3D fBm fixed in world space modulates the fog (and, by *noise on haze*, the thin
  haze too), so it breaks into banks and wisps. *noise flatten* squashes it vertically into
  layers; *wind* drifts it over time, so it stays put when the camera moves and moves when
  the air does.

Steps are packed towards the camera and jittered per pixel, so *quality* trades grain for
speed.

| Knob | Default | What it does |
| --- | --- | --- |
| mode | Fast | Fast (exact, one step) or Volumetric (marched, for fog and noise) |
| quality | Normal (48) | Samples per ray in Volumetric mode |
| fog density (1/km) | 0 | Thickness of the fog layer |
| fog top (m) | 1000 | Altitude the fog fills up to |
| fog softness (m) | 300 | How gradually the fog fades out around its top |
| noise amount | 0 | How much the noise breaks up the fog |
| noise on haze | 0.3 | How much of the noise applies to the thin haze as well |
| noise size (m) | 2000 | Size of the largest wisps and banks |
| noise flatten | 3 | Squashes the noise vertically into layers |
| noise detail | 4 | Octaves of noise |
| wind (m/s) | (5, 0, 0) | Drifts the noise over time |
| noise seed | 1 | Changes the pattern |

## Light shafts

With *shaft amount* above 0 and the sun in front of a camera plate, each pixel looks across
the image towards the sun and checks how much of the way is open sky. Where mountains
block the sun, the haze near the sun gets less light; the gaps between ridges stay bright,
so shafts of sunlight stream through them. The sun direction comes from the atmos input
(set its *sun from* to Manual) or from *sun direction*.

| Knob | Default | What it does |
| --- | --- | --- |
| shaft amount | 0 | How much the blocked haze darkens (0 = off) |
| sun direction | (0, 0.1, -1) | Direction towards the sun, when not inheriting |
| shaft length | 0.6 | How far towards the sun each pixel looks, as a fraction of the way |
| shaft fade | 0.97 | How quickly blockers further along count less; closer to 1 gives longer shafts |
| shaft focus | 2 | How tightly the shafts gather around the sun |
| shaft clear distance (km) | 60 | Terrain beyond this is too hazed to cast a visible shadow |
| shaft quality | Normal (64) | Samples along the way to the sun |

This is a screen-space effect: it only knows what is in frame, and lat-long plates get no
shafts.

## Demo

`examples/DemoTerrain.blink` renders a procedural mountain range through a Nuke camera,
with distance in alpha, so the node can be tried without a CG render.

## Rebuilding the gizmo

```
Nuke15.1.exe --nukex -i -t python/build_gizmo.py
```
