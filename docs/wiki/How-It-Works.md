# How it works

## Plate solving in one paragraph

A plate solver looks at the pattern of stars in a picture and matches it
against a star catalogue, the way you'd recognise a constellation. The answer
is exact: the RA and Dec of the picture's centre, its rotation, its field of
view and its scale in arcseconds per pixel. This add-on uses
[astrometry.net](https://astrometry.net)'s `solve-field`, the same solver
Pi-lomar's own installer sets up. With a hint ("near M31, about 23° wide") a
solve takes 2–5 seconds on a Pi 5.

## How it fits with Pi-lomar

| Pi-lomar already has | The add-on adds |
|---|---|
| `solve-field` and the 2MASS index files (Pi-lomar's `scripts/astrometry.net`) | Uses the same installation |
| A plate solver that reports where a picture was pointing | Turns the answer into a correction and applies it, in a loop |
| GOTO and tracking | Nothing changed: Pi-lomar still does all slewing and tracking |
| Motor tools → **Tune**, which moves a motor without changing Pi-lomar's idea of where it points | Applies every correction through Tune, so it stays in effect while Pi-lomar tracks |

Pi-lomar has no remote-control interface, so in `tmux` mode the add-on reads
Pi-lomar's screen through tmux and types menu choices, waiting for each prompt
before typing the next. In `advisor` mode it prints the Tune steps for you to
type yourself.

## The centring loop

1. Take a short exposure.
2. Plate-solve it.
3. Convert the solved centre and the target to altitude/azimuth at the moment
   the picture was taken.
4. If they're within 0.1°, stop.
5. Otherwise convert the difference to motor steps and send it through Tune.
   Go back to 1.

Pi-lomar doesn't track while it sits at its main menu, so the add-on reads
Pi-lomar's own position (Status) and compares the picture with that, rather
than with the target's current position, which keeps moving.

## Safety

* Applies 90% of each correction, limits single moves (10° on the sky, 30° of
  azimuth turn), and stops if the error grows.
* Refuses a GOTO below 5° altitude or within 30° of the Sun.
* Never types `x` at Pi-lomar's main menu (that would quit) and answers "no" if
  Pi-lomar ever asks whether to shut down.

## Why it won't conflict with Pi-lomar updates

* It lives in its own folder (`~/pilomar-platesolve`).
* It only **reads** Pi-lomar's files: your location, the target catalogues, the
  star catalogue and saved pictures. It writes only into its own `data` folder.
* It doesn't import or patch Pi-lomar's code, and uses only Python's standard
  library (plus OpenCV, which Pi-lomar installs, for optional extras).
* Everything that knows about Pi-lomar's files is in one small file
  (`pilomar_bridge.py`); everything that knows its menus is in `mount.py`, with
  the menu numbers in `config.json`.

The maths (WCS, rotation, precession, the pointing model) is in
[docs/HOW_IT_WORKS.md](https://github.com/jameskenney/pilomar-platesolve/blob/main/docs/HOW_IT_WORKS.md).
