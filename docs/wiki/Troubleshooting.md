# Troubleshooting

## Plate solving

| Symptom | Likely cause and fix |
|---|---|
| `no solution` / `solve-field timed out` | Clouds, haze, moonlight, a low target or lights near the horizon. Try a higher target, a longer exposure, or check focus. The rescue retry runs automatically (see [[Annotated Pictures and Hard Solves]]) |
| Solves but the field size is wrong | Set `optics.focal_length_mm` to your lens. The reference "16 mm" lens measures 15.6 mm |
| Lens cap still on | It happens to everyone |

## Centring

| Symptom | Likely cause and fix |
|---|---|
| "error is growing after corrections" | An axis direction may be reversed: flip `mount.az_sign` or `mount.alt_sign`. Check first that Pi-lomar's position was read on every picture (all lines should say "mount error … (camera vs where Pi-lomar thinks it points)") |
| Corrections fall short, then overshoot on the way back | Gear slack. Run `pilomar-ps backlash` |
| Large azimuth corrections near the zenith | Normal: near the zenith a small sky offset needs a large azimuth turn |

## tmux mode

| Symptom | Likely cause and fix |
|---|---|
| `tmux session not found` | Start Pi-lomar with `tmux new -s pilomar '…'` |
| `Pi-lomar did not reach 'select'` | Pi-lomar asked a question the add-on didn't expect. Check with `tmux attach -t pilomar`. Since v0.3.6 it answers "Is this session complete?" with `y` when selecting a new target (this only allows the target change; no files are touched) |
| `did not return to the main menu` during a GOTO | Long slews take several minutes. Since v0.3.7 the add-on keeps waiting while Pi-lomar prints progress |
| Status reads fail after a long session | Fixed in v0.3.8 (tmux's scrollback filled up). Run `git pull` |
| A screen the add-on doesn't recognise | Return Pi-lomar to its main menu by hand and try again |
| Strange characters typed into Pi-lomar | Don't use the mouse wheel inside tmux. Scroll with `Ctrl+B` then `[` |

## Camera

| Symptom | Likely cause and fix |
|---|---|
| `capture` fails while Pi-lomar is running | Pi-lomar holds the camera: Camera tools 23 → 16 disables it |
| No stars in focus pictures | Use `--exposure 4 --gain 16` at night, and sweep focus slowly |

## Getting help

Run `pilomar-ps report` and include its output when you
[open an issue](https://github.com/jameskenney/pilomar-platesolve/issues). It
leaves out your location, hostname, username and file paths.
