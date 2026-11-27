# How it works (for contributors)

## 1. From solver output to numbers

`solve-field` is run with `--crpix-center`, so the WCS reference pixel is the
image centre and `CRVAL1/2` is the centre's RA/Dec. `wcs.py` still computes the
centre from CRPIX + CD + TAN projection, so output from other solvers (ASTAP,
or `solve-field` without that flag) works too.

With the CD matrix `[[CD1_1, CD1_2], [CD2_1, CD2_2]]` (degrees per pixel, in
east/north standard coordinates):

* **plate scale** = sqrt(|det CD|) × 3600 ″/px (correct for any rotation;
  `|CD1_1|` alone is only right when the rotation is 0°)
* **FOV** = width × scale, height × scale
* **rotation** = position angle of the image's top edge:
  `atan2(-CD1_2, -CD2_2)` for JPEG/PNG (rows numbered from the top),
  `atan2(CD1_2, CD2_2)` for FITS
* **mirrored**: for top-down rows a normal sky image has det CD > 0; FITS
  (bottom-up) the reverse

## 2. From RA/Dec to motor corrections

Pi-lomar's motors are azimuth and altitude, so the target and the solved centre
are both converted to alt/az **at the picture's mid-exposure time**:

J2000 → precess to date (IAU 1976) → hour angle from local mean sidereal time
→ alt/az (azimuth from north through east, as in Pi-lomar).

```
d_az  = wrap180(target_az  - actual_az)
d_alt =         target_alt - actual_alt
steps = d × steps_per_degree × sign
```

Nutation, aberration and refraction are ignored. Each is under about 0.5′ of
*difference* between two points a few degrees apart, so they cancel in the
correction. Absolute positions are good to around 20″, which is far below one
pixel at 16 mm.

The error is also reported on the sky as east/north tangent-plane offsets
(`astro.tangent_offsets`), which is the "1.5° too far east, 0.8° too far north"
view.

## 3. Why Tune

`TunePosition(delta)` in Pi-lomar moves a motor by `delta` steps without
changing its logical angle. After a Tune the motor's real angle is
`logical + offset`. Pi-lomar keeps tracking by updating the logical angle, so
the offset, which is the correction, persists. Pi-lomar's optical drift tracker
uses the same function. Pi-lomar resets its drift tracker after a manual Tune,
which is what we want after a plate-solve correction.

## 4. Loop control

* gain 0.9 (under-correct slightly: backlash and settling)
* clamp to `max_correction_deg`, ignore axes below `min_correction_deg`
* divergence check: two consecutive iterations with error > 1.2 × previous → stop
  and point at `az_sign` / `alt_sign`
* the next solve's hint is the last solution (small search radius, tight scale
  range), so later solves are faster than the first

## 5. Adding a back end

* **solver**: subclass `solvers.Solver`, implement `available`, `command`, `solve`
  returning a `PlateSolution`; register it in `SOLVERS`
* **mount**: subclass `mount.Mount`, implement `apply(Correction) -> bool`
* **picture source**: any object with `capture() -> (Path, datetime_utc)`

`sim.py` shows all three in their simplest form.
