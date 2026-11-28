# pilomar-platesolve wiki

**pilomar-platesolve** adds plate solving and automatic target centring to
[Pi-lomar](https://github.com/Short-bus/pilomar), the 3D-printed miniature
observatory by Short-bus.

You type `pilomar-ps center m31`. The Pi takes a picture, works out from the
stars exactly where the camera points, compares that with where Andromeda
really is, nudges the motors by the difference through Pi-lomar's own Tune
tool, and repeats until the galaxy is centred. It runs entirely on the
Raspberry Pi, with no internet connection.

It's an **add-on, not a fork**: it lives in its own folder, never edits a
Pi-lomar file, and keeps working when you update Pi-lomar.

## Start here

| If you want to… | Read |
|---|---|
| Install it on your Pi | [[Installation]] |
| Use it on a clear night | [[Night Routine]] |
| See every command | [[Commands]] |
| Understand how it talks to Pi-lomar | [[How It Works]] |
| Make GOTOs land on target without pictures | [[Alignment and Backlash]] |
| Rescue hard pictures, or label what's in a picture | [[Annotated Pictures and Hard Solves]] |
| Stack your pictures | [[Stacking with DeepSkyStacker]] |
| Fix a problem | [[Troubleshooting]] |
| See what it's been tested on | [[Tested Hardware]] |
| Common questions | [[FAQ]] |

## What a centring run looks like

From a real night (M45, 16 mm lens, town sky):

```
[1] Capturing...
  Solved by     : astrometry in 2.6 s
    mount error 0.709° ...  |  needs azimuth -1.318°, altitude -0.004°
[2] Capturing...
    mount error 0.289° ...  |  needs azimuth -0.535°, altitude +0.033°
[3] Capturing...
    mount error 0.043° ...
  ✔ centred to 0.043° (tolerance 0.1°) in 3 picture(s)
  total time: 82 s, 3 picture(s)
```

## Status

Plate solving, centring, focusing help, startup alignment and stacking have all
worked under the sky. Backlash compensation, rescue solves and annotated
pictures (v0.4) are tested in simulation and on real saved pictures; full
night testing is in progress. See [[Tested Hardware]] for details.

The code and README are in the
[repository](https://github.com/jameskenney/pilomar-platesolve). MIT licence.
