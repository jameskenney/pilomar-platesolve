# Annotated pictures and hard solves

## Annotated pictures

```bash
pilomar-ps annotate picture.jpg --target m31
pilomar-ps capture --solve --annotate
```

The labelled copy goes in `~/pilomar-platesolve/data/annotated/` (never in
Pi-lomar's folders). It shows:

* the picture's centre (white crosshair) and the target (red), with a line between them,
* north and east arrows,
* the 150 brightest stars from Pi-lomar's `hip_main.dat` (yellow circles),
* names of bright stars (green),
* Messier and bright NGC objects in view (orange), each labelled once,
* RA/Dec, rotation, field of view, scale and time in the corner.

On a real picture of Andromeda with the 16 mm lens it labelled Mirach, M31, M32,
M110, NGC 147, NGC 185 and NGC 272. The idea comes from the `.solution.jpg`
picture Pi-lomar's own solver draws.

## Pictures that don't solve

Haze, moonlight and the glow near the horizon can hide too many stars. When a
solve fails, the add-on tries once more before giving up:

1. **A cleaned copy.** The smooth sky glow is fitted and subtracted, hot pixels
   are filtered, and the result is stretched so faint stars stand out. The
   picture keeps its size, so the solution applies to the original.
2. **The lens preset.** Star-detection settings for the lens, taken from the
   comments in Pi-lomar's own solver:
   * 16 mm: `--objs 120 --uniformize 120 --sigma 6`
   * 50 mm: `--objs 80 --uniformize 80 --sigma 8`

   chosen by field width.
3. Only then, a solve without the position hint.

When the retry was needed, the output says `(retry: cleaned, 16mm preset)`.

Settings, under `solver.astrometry` in `config.json`:

| Setting | Default | Meaning |
|---|---|---|
| `rescue` | `true` | Retry a failed solve |
| `clean` | `true` | Use the cleaned copy on the retry (needs OpenCV) |
| `preset` | `"auto"` | `"auto"`, `"16mm"`, `"50mm"` or `"none"` |
| `preset_when` | `"rescue"` | `"always"` uses the preset on every solve |
| `rescue_cpulimit_s` | `30` | Time limit for the retry |
