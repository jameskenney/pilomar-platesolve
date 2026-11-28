# FAQ

**Does it change Pi-lomar?**
No. It lives in its own folder and only reads Pi-lomar's files. Updating
Pi-lomar won't break it, and removing it leaves Pi-lomar exactly as it was.

**Does it need the internet?**
Only to install. Solving runs on the Pi with local index files.

**Do I have to use tmux?**
No. In `advisor` mode it prints the Tune steps and you type them into Pi-lomar's
Motor tools. `tmux` mode types them for you.

**Can it take pictures while Pi-lomar is running?**
Yes, if Pi-lomar's camera is disabled (Camera tools 23 → 16). Or set
`capture.source = "pilomar-folder"` and it uses the pictures Pi-lomar saves.

**How accurate is it?**
Centring stops within 0.1° by default (about 9 pixels with a 16 mm lens). Real
runs have finished at 0.03–0.08°.

**Why does Pi-lomar ask "Is this session complete?"**
Pi-lomar asks before changing target once a session has pictures. Answering
`y` only allows the change; the pictures stay where they are.

**Should I enter my latitude and longitude?**
Yes, accurately, in Pi-lomar's settings. The add-on reads them from there. Use
alignment to measure the mount's tilt and offsets, rather than trying to
measure location from the stars.

**Will it work with a 50 mm lens?**
It should: set `optics.focal_length_mm` to 50 and install the 2MASS index files
09 and 10 if they're missing. Not yet tested.
