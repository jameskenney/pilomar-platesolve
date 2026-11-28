# Installation

## What you need

* A working Pi-lomar (tested with 1.3.0) on a Raspberry Pi 5.
* The Raspberry Pi HQ camera. Tested with a 16 mm lens; a 50 mm lens should work
  with the extra index files noted below.
* About 1 GB free for the star index files.

## Install

```bash
cd ~
git clone https://github.com/jameskenney/pilomar-platesolve.git
cd pilomar-platesolve
./install.sh
source ~/.profile
pilomar-ps check
```

`install.sh`:

* installs `astrometry.net`, the `astrometry-data-2mass-08-19` index files and
  `tmux` from apt, if they're missing,
* creates the `pilomar-ps` command and a `config.json`,
* runs `pilomar-ps check`.

The 2MASS index package is the one Pi-lomar's own documentation recommends for
16–50 mm lenses. Files 11 to 19 are enough for a 16 mm lens. A 50 mm lens may
need 09 and 10 as well; if those failed to download, install them again later.

The add-on uses only Python's standard library. The optional image clean-up and
annotated pictures use OpenCV, which Pi-lomar already installs.

## Settings to check

`pilomar-ps config` shows every setting. Edit `config.json` in the
`pilomar-platesolve` folder to change one. The ones that matter most:

| Setting | What it is | Typical value |
|---|---|---|
| `capture.source` | Where pictures come from | `rpicam` (the add-on takes them) or `pilomar-folder` (it waits for Pi-lomar's) |
| `mount.backend` | How corrections are applied | `advisor` (prints Tune steps for you) or `tmux` (types them into Pi-lomar) |
| `optics.focal_length_mm` | Lens focal length | `16` |
| `mount.steps_per_degree_az` / `_alt` | Motor steps per degree | `1066.67` (Pi-lomar's Tune screen shows the figure) |
| `mount.az_sign` / `alt_sign` | Which way + steps turn | `1`; flip to `-1` if centring runs away |

Your latitude and longitude are read from Pi-lomar's own settings
(`pilomar_params.json`). Make sure they're right there: an error of 0.1° in
longitude shifts pointing by up to about 0.1°.

## Updating

```bash
cd ~/pilomar-platesolve && git pull
```

Your `config.json`, pointing model and logs aren't part of the repository, so
updates never overwrite them.

Next: [[Night Routine]]
