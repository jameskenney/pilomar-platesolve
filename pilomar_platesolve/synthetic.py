"""Synthetic star pictures for indoor testing.

Draws the real sky (from the Hipparcos catalogue Pi-lomar already downloads to
``data/hip_main.dat``) as the HQ camera + lens would see it at a chosen
pointing and rotation, and writes a PNG. Feeding that to the *real* plate
solver tests the solver installation, its speed, and this add-on's maths
(centre, rotation, scale, mirroring) against a known right answer, in daylight.
"""

from __future__ import annotations

import json
import math
import random
import struct
import zlib
from pathlib import Path

from .wcs import radec_to_pixel


def load_hipparcos(path: str | Path, max_mag: float = 8.0) -> list[tuple[float, float, float]]:
    """(ra_deg, dec_deg, vmag) for Hipparcos stars brighter than max_mag.

    hip_main.dat (VizieR I/239) is '|'-separated: field 5 Vmag, 8 RAdeg, 9 DEdeg.
    """
    out = []
    with open(path, encoding="latin-1") as f:
        for line in f:
            p = line.split("|")
            if len(p) < 10:
                continue
            try:
                mag = float(p[5])
                ra, dec = float(p[8]), float(p[9])
            except ValueError:
                continue
            if mag <= max_mag:
                out.append((ra, dec, mag))
    return out


def _cd(scale_arcsec: float, rotation_deg: float) -> tuple[float, float, float, float]:
    """CD matrix of a y-down, non-mirrored image whose top edge is at position angle `rotation`."""
    s, r = scale_arcsec / 3600.0, math.radians(rotation_deg)
    return (-s * math.cos(r), -s * math.sin(r), s * math.sin(r), -s * math.cos(r))


def write_png_gray(path: str | Path, width: int, height: int, pixels: bytearray):
    raw = b"".join(b"\x00" + bytes(pixels[y * width:(y + 1) * width]) for y in range(height))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    Path(path).write_bytes(png)


def render_starfield(stars, ra0: float, dec0: float, rotation_deg: float, width: int, height: int,
                     scale_arcsec: float, out: str | Path, seed: int = 1, sigma_px: float = 1.3,
                     limit_mag: float = 8.0) -> dict:
    """Draw the stars around (ra0, dec0) into a grey-scale PNG. Returns the true WCS."""
    rng = random.Random(seed)
    crpix = ((width + 1) / 2.0, (height + 1) / 2.0)
    cd = _cd(scale_arcsec, rotation_deg)
    # Background: dark grey with a little noise (fast: random bytes through a lookup table).
    table = bytes(14 + (b % 7) for b in range(256))
    pix = bytearray(rng.randbytes(width * height).translate(table))
    radius = math.hypot(width, height) * scale_arcsec / 3600.0 / 2 + 0.5
    cos_r = math.cos(math.radians(radius))
    d0 = math.radians(dec0)
    drawn = 0
    box = int(math.ceil(4 * sigma_px))
    for ra, dec, mag in stars:
        # Quick angular-distance cut before projecting.
        d = math.radians(dec)
        c = (math.sin(d) * math.sin(d0) + math.cos(d) * math.cos(d0) * math.cos(math.radians(ra - ra0)))
        if c < cos_r:
            continue
        x, y = radec_to_pixel(ra, dec, crpix, (ra0, dec0), cd)
        if not (-box <= x <= width + box and -box <= y <= height + box):
            continue
        peak = min(240.0, 40.0 * 10 ** (-0.4 * (mag - limit_mag)))
        cx, cy = x - 1, y - 1  # FITS 1-based -> array 0-based
        for yy in range(max(0, int(cy) - box), min(height, int(cy) + box + 2)):
            dy2 = (yy - cy) ** 2
            row = yy * width
            for xx in range(max(0, int(cx) - box), min(width, int(cx) + box + 2)):
                v = peak * math.exp(-((xx - cx) ** 2 + dy2) / (2 * sigma_px ** 2))
                if v >= 1:
                    i = row + xx
                    pix[i] = min(255, pix[i] + int(v))
        drawn += 1
    write_png_gray(out, width, height, pix)
    truth = {"ra": ra0, "dec": dec0, "rotation": rotation_deg, "scale_arcsec": scale_arcsec,
             "width": width, "height": height, "stars": drawn, "cd": cd, "crpix": crpix}
    # The right answer, kept next to the picture so results can be checked later.
    Path(str(out) + ".truth.json").write_text(json.dumps(truth, indent=2))
    return truth


class SyntheticSource:
    """A picture source that renders what a simulated mount is really looking at."""

    def __init__(self, world, stars, outdir: Path, width: int, height: int, scale_arcsec: float,
                 rotation_deg: float = 25.0):
        self.w, self.stars = world, stars
        self.outdir = Path(outdir)
        self.outdir.mkdir(parents=True, exist_ok=True)
        self.size, self.scale, self.rot = (width, height), scale_arcsec, rotation_deg
        self.truths: dict[str, tuple[float, float]] = {}

    def capture(self):
        self.w.count += 1
        when = self.w.t
        self.w.t += self.w.step
        ra, dec = self.w.true_pointing(when)
        out = self.outdir / f"selftest_center_{self.w.count:02d}.png"
        render_starfield(self.stars, ra, dec, self.rot, *self.size, self.scale, out, seed=self.w.count)
        self.truths[out.name] = (ra, dec)
        return out, when
