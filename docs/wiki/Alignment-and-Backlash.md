# Alignment and backlash

Plate solving every target works, but most of the pointing error is the same
every night. Measuring it once lets GOTOs land close to the target with no
picture at all.

## Startup alignment (pointing model)

```bash
pilomar-ps align --min-alt 40
pilomar-ps goto m31            # GOTO + predicted correction, no picture
pilomar-ps center m31          # optional: confirm with one picture
```

`align` visits about 6 targets spread around the sky, plate-solves each, and
fits the mount's fixed errors, the same terms professional telescopes use:

| Term | Meaning |
|---|---|
| IA | Azimuth home offset |
| IE | Altitude zero offset |
| AN, AW | Base tilt north–south and east–west |
| CA | Camera pointing slightly sideways on its arm |
| NPAE | Axes not quite square |

It uses as many terms as the number of solved points allows. Example from the
reference build: base tilt 0.87°, home offsets 0.8° and 0.4°, pointing error
1.19° → 0.27° rms.

Tips:

* Use `--min-alt 40` and `--az-range FROM TO` to keep away from trees, houses,
  lights and the Moon. Low targets often fail to solve.
* Re-run `align` after re-levelling, moving the observatory, a manual
  realignment, a forced stop, or measuring backlash.
* Don't make manual Tune moves between `align` and `goto`; the add-on keeps a
  ledger of its own Tune moves (`data/pointing_state.json`) but can't see yours.

**Why not measure latitude and longitude from the stars?** For an alt-az mount,
a base tilted by 1° looks exactly like a level base about 110 km away. Use an
accurate map location in Pi-lomar's settings, and let the model measure the
tilt.

## Backlash (gear slack)

When a motor reverses, it turns a little before the camera moves: the slack
between the gear teeth. On the reference build that's about 0.5–0.8° in
azimuth. It makes reversing corrections fall short, and makes a pointing model
wrong for GOTOs that arrive from the other direction.

```bash
pilomar-ps backlash            # about 2 minutes; point at 30–60° altitude first
pilomar-ps backlash --show
```

It moves each axis +2°, −2°, +2° with Tune, solving a picture after each move.
The camera's move after a reversal is 2° minus the slack. The result is saved
in `data/backlash.json`. From then on:

* every Tune correction that reverses a motor adds the slack, so the camera
  moves the full amount,
* the add-on reads Pi-lomar's position before and after each GOTO, so it knows
  which way the gears were last loaded.

Measure backlash first, then run `align`.
