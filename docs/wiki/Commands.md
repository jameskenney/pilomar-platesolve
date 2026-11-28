# Commands

Run `pilomar-ps <command> --help` for every option.

## Everyday

| Command | What it does |
|---|---|
| `pilomar-ps check` | Checks that everything is installed and Pi-lomar's files are found |
| `pilomar-ps suggest` | Bright deep-sky targets that are up now (avoids the Moon) |
| `pilomar-ps target andromeda` | Where a target is right now (altitude, azimuth) |
| `pilomar-ps center m31 --goto` | GOTO, then picture → solve → Tune until centred (within 0.1°) |
| `pilomar-ps center m31` | Same, without the GOTO (Pi-lomar is already on target) |
| `pilomar-ps goto m31` | GOTO plus the pointing-model correction, no picture |
| `pilomar-ps focus --full` | Star count and size every few seconds, for focusing |
| `pilomar-ps report` | Summary of your results to share (no personal details) |

## Alignment and mount

| Command | What it does |
|---|---|
| `pilomar-ps backlash` | Measures the gear slack on each axis (about 2 minutes) |
| `pilomar-ps backlash --show` | Shows the slack values in use |
| `pilomar-ps align` | Startup alignment: visits about 6 targets and fits a pointing model. `--min-alt 40`, `--az-range 90 270` avoid low or blocked sky |
| `pilomar-ps model show` / `fit` / `reset` | Inspect, refine from logged solves, or clear the model |
| `pilomar-ps tune --az 1 --alt -0.5` | One Tune move (degrees). `--raw` sends exact steps, `--dry-run` only prints |
| `pilomar-ps slew m31` / `--altaz 30 180` | Have Pi-lomar GOTO, no correction. Refuses below 5° or near the Sun |

## Pictures and solving

| Command | What it does |
|---|---|
| `pilomar-ps capture` | Take one picture (`--exposure`, `--gain`) |
| `pilomar-ps capture --solve --annotate` | …and solve it and save a labelled copy |
| `pilomar-ps solve picture.jpg` | Where was this picture pointing? (`--target m31` compares with a target) |
| `pilomar-ps annotate picture.jpg --target m31` | Solve and save a labelled copy in `data/annotated/` |
| `pilomar-ps watch --target m31` | Solve every picture Pi-lomar saves; shows drift |

## Testing without the sky

| Command | What it does |
|---|---|
| `python3 -m unittest discover -s tests` | The unit tests |
| `pilomar-ps simulate m31 --az 1.5 --alt -0.8` | The centring loop with a virtual mount (`--backlash`, `--wrong-sign`, `--fail 1`) |
| `pilomar-ps simulate-align` | Alignment on a virtual tilted mount |
| `pilomar-ps selftest` | The real solver on synthetic star pictures drawn from Hipparcos |
| `pilomar-ps selftest --center` | The centring loop with the real solver and a virtual mount |

## Targets

Targets can be Messier or NGC numbers (`m31`, `M 31`, `NGC 7000`), names
(`andromeda`, `orion nebula`) or coordinates (`10.68 41.27` or
`00:42:44 +41:16:09`). Names come from Pi-lomar's own catalogue files.
