# Night routine

This is the hands-free routine used on the reference build, with
`capture.source = "rpicam"` and `mount.backend = "tmux"`.

## 1. Start up

1. Turn on the 12 V motor supply, then boot the Pi.
2. Start Pi-lomar inside tmux, so the add-on can type into it:
   ```bash
   tmux new -s pilomar 'cd /home/pi/pilomar/src && ./pilomar'
   ```
3. In Pi-lomar, **leave the camera disabled** (Camera tools 23 → 16) so the
   add-on can use it.
4. Leave tmux with `Ctrl+B` then `D`. Pi-lomar keeps running at its main menu.

Tips for tmux: come back with `tmux attach -t pilomar`. Don't use the mouse
wheel inside tmux; it types arrow-key codes. To scroll, press `Ctrl+B` then
`[`, and `q` to stop.

## 2. Focus (once, or after the lens is bumped)

```bash
pilomar-ps focus --full --exposure 4 --gain 16
```

It prints the number of stars and their size every few seconds. Turn the focus
ring slowly: more stars and a smaller size are better. At f/1.4 the sharp zone
is very narrow.

## 3. Alignment (optional, once per setup)

```bash
pilomar-ps backlash            # measure gear slack, about 2 minutes
pilomar-ps align --min-alt 40  # about 25 minutes
```

See [[Alignment and Backlash]].

## 4. Centre a target

```bash
pilomar-ps suggest             # what's up and bright right now
pilomar-ps center m31 --goto   # GOTO, then picture → solve → correct, repeated
```

Let GOTOs finish. Pi-lomar's motors move about 2.6 s per degree, so a long
turn can take 8 minutes or more, with no output while the motors run.

## 5. Take your pictures in Pi-lomar

```bash
tmux attach -t pilomar
```

* `23` → `15` enables Pi-lomar's camera.
* `6` sets the exposure (for example 10 s), `7` the number of light frames.
* `2` begins the observation.
* Afterwards, lens cap on: `8` sets the number of darks, `9` takes them.
* `23` → `16` disables the camera again before using `pilomar-ps`.

## 6. Afterwards

* Copy the session folder to your computer (example from Windows PowerShell):
  ```
  scp -r pi@<pi-address>:/home/pi/pilomar/data/campaign_<target>_e<exp>s/session_<date> .
  ```
  Lights are in `light/`, darks in `dark/`. Each frame is saved as JPG and DNG.
* `pilomar-ps report` prints a summary of your results to share.
* Once a session is safely copied, you can delete its folder on the Pi to free space.

Next: [[Stacking with DeepSkyStacker]]
