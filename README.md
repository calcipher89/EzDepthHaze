# EzDepthHaze

Depth haze for The Foundry Nuke, built in BlinkScript. A companion to
[EZ-Atmos-Scatter](https://github.com/calcipher89/EZ-Atmos-Scatter): it hazes a plate or
CG render using its depth, lit by the same atmosphere.

Target: Nuke 15.1.

## Installing

No install: `groups/EzDepthHaze_group.nk` is the same node as a plain Group. Import it with
**File > Import Script** (or paste its text into the node graph) and it works on its own,
without the gizmo on the plugin path, so it can live in a shot script or a toolset.

As a gizmo:

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
channel of the plate and adds the layers listed under Layers below.

### Knobs

| Knob | Default | What it does |
| --- | --- | --- |
| view output | Hazed Plate | Hazed Plate, Haze Transmittance or Haze In-scatter in rgb |
| plate | Camera | Camera (perspective, uses the `camera` input) or Lat-long |
| depth channel | depth.Z | Where the depth is |
| depth type | Distance | Distance from the camera, Planar Z (along the view axis) or 1/Z (ScanlineRender) |
| units to metres | 1 | Scene units to metres, e.g. 0.01 for centimetres. Scales the depth and the camera position |
| camera height (m) | 1 | Camera height for lat-long plates |
| sky | Leave Sky | Pixels with no depth: leave them, or haze them as if *sky distance* away |
| sky distance (km) | 50 | Distance used for sky pixels with Haze Sky |
| sky depth | 1e7 | Depth at or beyond which a pixel counts as sky |
| inherit from atmos | on | Take haze density, haze height and rotation from the EzAtmosScatter input |
| match horizon sky | on | Far haze takes the light of the atmos input's own sky, so distant terrain fades into the sky behind it |
| match distance (km) | 20 | Distance over which the haze light changes from the camera's to the horizon sky's |
| atmos layer | atmos_haze_color | Layer of the atmos input to use (rgba for a plain lat-long) |
| haze color | (0.6, 0.65, 0.75) | Flat haze colour |
| haze brightness | 1 | Multiplies the haze colour |
| haze density (1/m) | 0.0001 | Extinction per metre at camera height, when not inheriting |
| haze amount | 1 | Multiplies the density |
| haze height (km) | 1.2 | Height over which the haze thins by about two thirds, when not inheriting |
| haze start (m) | 0 | Distance where the haze begins |
| max distance (km) | 0 | Caps the hazed distance (0 = off) |
| atmos rotation | 0 | Rotation of the atmos lat-long, when not inheriting |

## Easy mode

The node opens on its **Easy** tab:

- **Looks**: a button per preset. *refresh looks* renders a small picture (160 pixels
  wide) of every look on the current frame onto the buttons; it uses a temporary copy of
  the node on a downsized plate and deletes it afterwards. Clicking a look applies it,
  fitted to the shot (see Presets).
- **look strength**: from clear air (0) to the full look (1).
- **haze**, **warmth**, **glow**, **shafts**, **fog**, **fog height** and **texture**:
  big sliders, each driving the knobs underneath (haze amount; haze tint; sun scatter;
  shadow strength; fog density; fog top, in steps of the terrain's height range; noise
  amount). They are relative to the look as applied, so the middle is always the look.
- **surprise me** picks random adjustments within tasteful limits; **reset** centres
  the sliders; **before** shows the plate without haze.
- **My Looks**: type a *name*, pick *save to* User or Studio and press *save look*.
  *saved looks* lists both folders; picking one loads it.
- **advanced** shows every knob, set to what Easy did, to fine-tune. Turning it off
  again starts Easy from your tuned values, with the sliders centred.

Looks are JSON files in the User folder (`~/.nuke/ezdepthhaze_looks`, or
`$EZHAZE_USER_LOOKS`) or the Studio folder (`$EZHAZE_STUDIO_LOOKS`). The default paths are
at the bottom of `python/ezdepthhaze.py`; change them there and rebuild. Easy mode only
reacts to changes made in the open panel, so loading or rendering a script never changes
a knob.

## Presets

Pick a look (the *look* menu or a look button) and it is applied straight away, fitted to the shot (see below);
every knob stays editable. *apply* applies it again, for example after connecting the plate
and camera, or to undo your tweaks. A short summary pops up, and when the EzAtmosScatter
sun is far from where the look wants it, it asks whether to move it there (sun direction
and colour, with *sun from* set to Manual). *haze tint* colours all the haze light.

| Preset | Look | Sun it offers |
| --- | --- | --- |
| Clear Day | Light blue aerial perspective, crisp shadows, no fog | 35 degrees up, 60 degrees right, white |
| Golden Hour | Warm haze, strong shafts, light valley fog | 4 degrees up, 15 degrees left, warm |
| Valley Fog | A dense fog lake in the valleys, clear air above | 10 degrees up, 30 degrees left, slightly warm |
| Smoke Haze | Thick brown-orange haze, low contrast | 8 degrees up, 20 degrees left, reddened |
| Overcast Mist | Grey-blue mist with drifting wisps, no sun shadows | None |

### Fitted to the shot

The presets were tuned on the demo: terrain 6-130 km away, seen from 4.3 km up. Applying
one measures the depth and camera at the current frame and sets:

- *haze amount*, so the median terrain pixel gets the demo's amount of haze;
- *fog top* and *fog softness*, at the same place in the shot's range of terrain altitudes;
- *noise size*, *wind*, *shadow distance*, *match distance* and *sky distance*, scaled with
  the scene's distances;
- *sky depth*, when a far backdrop (a skydome or card) stands well apart from the terrain.

Without a plate or camera yet, the preset is applied as tuned. Picking a preset only applies
it from the open panel, never while a script loads or renders, so tuned knobs stay put.
This matches the look, not the physics: a 2 km shot gets far denser haze than real air
would give it.

The preset values are built into the gizmo; edit them in `python/ezdepthhaze.py` and
rebuild the gizmo.

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

## Sun, shadows and surface light

The haze light is split in two: the part lit by the sun (`atmos_haze_sun`) and the part lit
by the sky (`atmos_haze_sky`), both from EzAtmosScatter. Along each view ray the node checks
whether the air can see the sun: from each point it walks towards the sun and compares
against the depth in screen space. Shadowed air keeps its sky light and loses only the
sunlight, so the shadows behind ridges come out in the colour of the sky, and the gaps
between ridges read as shafts of sunlight. Shadows need the ray to be stepped (Volumetric
mode, or Fast mode with *match horizon sky*). Only terrain in frame casts shadows.

From the depth the node also rebuilds world positions (`P`) and normals (`N`) and tests
each surface point against the sun the same way, giving the sunlight falling on the
terrain (`surface_sunlight`). It can be added to the plate for photos and matte paintings;
leave it off for CG already lit by the same sun.

| Knob | Default | What it does |
| --- | --- | --- |
| haze color from | Atmos Sun + Sky | EzAtmosScatter's split layers, one atmos layer split by *sun share*, or a flat colour split by *sun share* |
| sun direction | (0, 0.1, -1) | Direction towards the sun, when not inheriting |
| sun scatter | 1 | Brightness of the sunlit haze (the shafts) |
| sky scatter | 1 | Brightness of the sky-lit haze (the haze in shadow) |
| shadow strength | 1 | Sunlight lost where terrain blocks the sun; 1 is physical, 0 is off |
| shadow fill | 0 | Puts back a tinted share of the lost sunlight (artistic) |
| shadow distance (km) | 20 | How far towards the sun each point looks for blockers |
| penumbra (deg) | 0.5 | Shadow softness; the sun is about 0.5 across |
| occluder thickness (m) | 1e9 | How deep each surface is taken to be; lower it for thin objects |
| shadow quality | Normal | Samples towards the sun, and how often along the view ray |
| add surface light | off | Adds `surface_sunlight` to the plate before hazing |
| surface light strength | 1 | Multiplies the surface light |
| sun light color | (1, 0.8, 0.6) | Colour and brightness of the sunlight on the terrain |
| albedo from | Plate | The plate's colour, or a constant *albedo* |

## Layers

Every pass is written to its own layer, so the look can be rebuilt and graded:

```
result = (plate + surface_sunlight, if added) * haze_transmittance + haze_sun + haze_sky
```

| Layer | Contents |
| --- | --- |
| `haze_transmittance` | How much of the plate survives the haze |
| `haze_inscatter` | All the haze light (`haze_sun + haze_sky`) |
| `haze_sun` | Sunlit haze, with shadows |
| `haze_sky` | Sky-lit haze |
| `haze_shadow` | Sunlight the haze lost to shadows |
| `haze_fog` | The fog layer's share of the in-scatter |
| `haze_wisps` | How much the noise changed the density, signed, weighted like the in-scatter |
| `surface_sunlight` | Sunlight falling on the terrain |
| `surface_sun_visibility` | 1 where a surface sees the sun, 0 in shadow |
| `P`, `N` | World position (metres) and normal, rebuilt from depth |

## Demo

`examples/DemoTerrain.blink` renders a procedural mountain range through a Nuke camera,
with distance in alpha, so the node can be tried without a CG render.
`examples/build_demo.py` builds a full sunset scene with it (needs EzAtmosScatter too):

```
Nuke15.1.exe --nukex -i --gpu -t examples/build_demo.py <output folder>
```

It renders the terrain once to `demo_terrain.exr` and saves `ezdepthhaze_demo.nk`.

`examples/build_layer_breakdown.py <demo folder>` then adds a labelled rebuild of the result
from its layers next to the node (plate + surface light, times transmittance, plus sun and
sky haze, with a difference check) and saves `ezdepthhaze_layer_breakdown.nk`.

## Rebuilding the gizmo

The build writes both `gizmos/EzDepthHaze.gizmo` and its Group version `groups/EzDepthHaze_group.nk`.

```
Nuke15.1.exe --nukex -i -t python/build_gizmo.py
```
