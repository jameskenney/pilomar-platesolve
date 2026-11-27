"""Where pictures come from.

* ``RpicamSource``  -- takes its own short exposure with ``rpicam-still``.
  Only works while Pi-lomar is not holding the camera (e.g. Pi-lomar's camera
  disabled in Camera tools, or Pi-lomar not running).
* ``PilomarFolderSource`` -- waits for the next image Pi-lomar saves (preview
  frames or observation lights). Fully hands-off from Pi-lomar's point of view.
* ``FileSource`` -- a fixed image, for testing and re-solving old pictures.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .pilomar_bridge import wait_for_new_image


class CaptureError(RuntimeError):
    pass


class Source:
    def capture(self) -> tuple[Path, datetime]:
        """Return (image path, UTC time at mid-exposure)."""
        raise NotImplementedError


class FileSource(Source):
    def __init__(self, path: str | Path, when: datetime | None = None):
        self.path = Path(path)
        self.when = when

    def capture(self):
        if not self.path.exists():
            raise CaptureError(f"image not found: {self.path}")
        when = self.when or datetime.fromtimestamp(self.path.stat().st_mtime, timezone.utc)
        return self.path, when


class RpicamSource(Source):
    def __init__(self, cfg: dict, outdir: Path):
        self.cfg = cfg
        self.outdir = Path(outdir)
        self.outdir.mkdir(parents=True, exist_ok=True)

    def available(self) -> bool:
        return shutil.which(self.cfg.get("exe", "rpicam-still")) is not None

    def command(self, out: Path) -> list[str]:
        c = self.cfg
        cmd = [c.get("exe", "rpicam-still"), "-n", "--immediate",
               "--shutter", str(int(float(c.get("exposure_s", 2.0)) * 1e6)),
               "--gain", str(c.get("gain", 8.0)),
               "--awbgains", "1,1", "--denoise", "off",
               "--width", str(c.get("width", 2028)), "--height", str(c.get("height", 1520)),
               "-o", str(out)]
        return cmd + [str(a) for a in c.get("extra_args", [])]

    def capture(self):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = self.outdir / f"ps_{stamp}.jpg"
        exp = float(self.cfg.get("exposure_s", 2.0))
        start = datetime.now(timezone.utc)
        try:
            p = subprocess.run(self.command(out), capture_output=True, text=True, timeout=exp + 60)
        except FileNotFoundError as e:
            raise CaptureError("rpicam-still not found") from e
        except subprocess.TimeoutExpired as e:
            raise CaptureError("rpicam-still timed out") from e
        if p.returncode != 0 or not out.exists():
            msg = (p.stderr or "").strip().splitlines()[-1:] or ["unknown error"]
            hint = (" -- is Pi-lomar (or rpicam-hello) holding the camera? Use "
                    "capture.source = 'pilomar-folder' while Pi-lomar is running.")
            raise CaptureError(f"rpicam-still failed: {msg[0]}{hint}")
        return out, start + timedelta(seconds=exp / 2)


class PilomarFolderSource(Source):
    def __init__(self, cfg: dict, pilomar_root: str | Path, trigger=None):
        self.cfg = cfg
        self.root = Path(pilomar_root)
        self.trigger = trigger  # optional callable that asks Pi-lomar to take a picture

    def capture(self):
        since = time.time()
        if self.trigger:
            self.trigger()
        else:
            print("  Waiting for Pi-lomar to save a new picture "
                  "(take preview frames or run an observation in Pi-lomar)...")
        p = wait_for_new_image(self.root, self.cfg.get("glob", "data/campaign_*/**/*.jpg"),
                               since, float(self.cfg.get("timeout_s", 180)),
                               float(self.cfg.get("settle_s", 1.0)))
        if p is None:
            raise CaptureError("no new Pi-lomar image appeared before the timeout")
        return p, datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
