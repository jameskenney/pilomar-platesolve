"""Read a plate solution (FITS WCS) and turn it into the numbers you care about.

Both astrometry.net (``solve-field``) and ASTAP write the answer as a FITS
World Coordinate System header: a reference pixel (CRPIX), the sky position of
that pixel (CRVAL) and a 2x2 "CD" matrix saying how many degrees of sky each
pixel step covers in x and y. Everything else -- centre RA/Dec, rotation,
plate scale, field of view, mirror flip -- is derived from those few numbers.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .astro import DEG, RAD, format_dec, format_ra, wrap360


# --------------------------------------------------------------------------
# Header parsing
# --------------------------------------------------------------------------

def _parse_value(raw: str):
    raw = raw.strip()
    if raw.startswith("'"):
        end = raw.find("'", 1)
        while end != -1 and end + 1 < len(raw) and raw[end + 1] == "'":
            end = raw.find("'", end + 2)
        return raw[1:end if end != -1 else None].replace("''", "'").rstrip()
    if "/" in raw:
        raw = raw.split("/", 1)[0].strip()
    if raw in ("T", "F"):
        return raw == "T"
    try:
        if any(c in raw for c in ".eEdD"):
            return float(raw.replace("D", "E").replace("d", "e"))
        return int(raw)
    except ValueError:
        return raw


def parse_fits_header_text(text: str) -> dict:
    """Parse FITS header cards. Accepts 80-column card images *or* newline text."""
    cards: list[str]
    if "\n" in text.strip():
        cards = text.splitlines()
    else:
        cards = [text[i:i + 80] for i in range(0, len(text), 80)]
    hdr: dict = {}
    for card in cards:
        key = card[:8].strip()
        if key == "END":
            break
        if not key or key in ("COMMENT", "HISTORY"):
            continue
        if card[8:10] == "= ":
            hdr[key] = _parse_value(card[10:])
        elif "=" in card:  # ASTAP .ini style  KEY=VALUE
            k, v = card.split("=", 1)
            hdr[k.strip()] = _parse_value(v)
    return hdr


def read_wcs_file(path: str | Path) -> dict:
    data = Path(path).read_bytes()
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return parse_fits_header_text(text)


# --------------------------------------------------------------------------
# Solution
# --------------------------------------------------------------------------

@dataclass
class PlateSolution:
    """Everything a plate solve tells you about where the camera points."""

    ra_deg: float            # image centre, J2000
    dec_deg: float
    rotation_deg: float      # position angle of the image's top edge, east of north
    scale_arcsec: float      # plate scale, arcseconds per pixel
    fov_width_deg: float
    fov_height_deg: float
    width_px: int
    height_px: int
    flipped: bool            # True if the image is mirrored relative to the sky
    crpix: tuple[float, float]
    crval: tuple[float, float]
    cd: tuple[float, float, float, float]
    solver: str = ""
    solve_seconds: float = 0.0
    image: str = ""
    extra: dict = field(default_factory=dict)

    # --- derived helpers ---------------------------------------------------
    @property
    def fov_diag_deg(self) -> float:
        return math.hypot(self.fov_width_deg, self.fov_height_deg)

    def pixel_to_radec(self, x: float, y: float) -> tuple[float, float]:
        """FITS 1-based pixel -> RA/Dec (TAN projection, linear terms)."""
        return pixel_to_radec(x, y, self.crpix, self.crval, self.cd)

    def radec_to_pixel(self, ra: float, dec: float) -> tuple[float, float]:
        return radec_to_pixel(ra, dec, self.crpix, self.crval, self.cd)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ra_hms"] = format_ra(self.ra_deg)
        d["dec_dms"] = format_dec(self.dec_deg)
        d["fov_diag_deg"] = self.fov_diag_deg
        return d

    def summary(self) -> str:
        return "\n".join([
            f"  RA   (centre) : {format_ra(self.ra_deg)}   ({self.ra_deg:.4f}°)",
            f"  Dec  (centre) : {format_dec(self.dec_deg)}   ({self.dec_deg:+.4f}°)",
            f"  Rotation      : {self.rotation_deg:.2f}° (image top, east of north)"
            + ("  [mirrored]" if self.flipped else ""),
            f"  Field of view : {self.fov_width_deg:.2f}° x {self.fov_height_deg:.2f}°"
            f"  (diagonal {self.fov_diag_deg:.2f}°)",
            f"  Plate scale   : {self.scale_arcsec:.2f}\"/pixel"
            f"  ({self.width_px} x {self.height_px} px)",
            f"  Solved by     : {self.solver} in {self.solve_seconds:.1f} s"
            + (f"  (retry: {self.extra['rescue']})" if self.extra.get("rescue") else ""),
        ])


def pixel_to_radec(x, y, crpix, crval, cd):
    cd11, cd12, cd21, cd22 = cd
    dx, dy = x - crpix[0], y - crpix[1]
    xi = (cd11 * dx + cd12 * dy) * DEG
    eta = (cd21 * dx + cd22 * dy) * DEG
    a0, d0 = crval[0] * DEG, crval[1] * DEG
    den = math.cos(d0) - eta * math.sin(d0)
    ra = a0 + math.atan2(xi, den)
    dec = math.atan2(math.sin(d0) + eta * math.cos(d0), math.hypot(xi, den))
    return wrap360(ra * RAD), dec * RAD


def radec_to_pixel(ra, dec, crpix, crval, cd):
    cd11, cd12, cd21, cd22 = cd
    a, d = ra * DEG, dec * DEG
    a0, d0 = crval[0] * DEG, crval[1] * DEG
    den = math.sin(d) * math.sin(d0) + math.cos(d) * math.cos(d0) * math.cos(a - a0)
    xi = math.cos(d) * math.sin(a - a0) / den * RAD
    eta = (math.sin(d) * math.cos(d0) - math.cos(d) * math.sin(d0) * math.cos(a - a0)) / den * RAD
    det = cd11 * cd22 - cd12 * cd21
    dx = (cd22 * xi - cd12 * eta) / det
    dy = (-cd21 * xi + cd11 * eta) / det
    return dx + crpix[0], dy + crpix[1]


def _cd_from_header(h: dict) -> tuple[float, float, float, float]:
    if "CD1_1" in h:
        return (float(h.get("CD1_1", 0.0)), float(h.get("CD1_2", 0.0)),
                float(h.get("CD2_1", 0.0)), float(h.get("CD2_2", 0.0)))
    cdelt1, cdelt2 = float(h.get("CDELT1", 0.0)), float(h.get("CDELT2", 0.0))
    if "PC1_1" in h:
        return (cdelt1 * float(h["PC1_1"]), cdelt1 * float(h.get("PC1_2", 0.0)),
                cdelt2 * float(h.get("PC2_1", 0.0)), cdelt2 * float(h["PC2_2"]))
    rot = float(h.get("CROTA2", 0.0)) * DEG
    return (cdelt1 * math.cos(rot), -cdelt2 * math.sin(rot),
            cdelt1 * math.sin(rot), cdelt2 * math.cos(rot))


def solution_from_header(h: dict, width_px: int | None = None, height_px: int | None = None,
                         solver: str = "", image: str = "",
                         y_down: bool | None = None) -> PlateSolution:
    """Build a PlateSolution from a parsed WCS header.

    ``y_down`` says whether pixel row 1 is the top of the picture (True for
    JPEG/PNG, the Pi camera's normal output). If None it is guessed from the
    image file extension (FITS -> False, anything else -> True).
    """
    if y_down is None:
        y_down = not str(image).lower().endswith((".fits", ".fit", ".fts"))
    if h.get("PLTSOLVD") is False:
        raise ValueError("solver reported no solution (PLTSOLVD=F)")
    for k in ("CRVAL1", "CRVAL2", "CRPIX1", "CRPIX2"):
        if k not in h:
            raise ValueError(f"WCS header is missing {k}")
    cd = _cd_from_header(h)
    det = cd[0] * cd[3] - cd[1] * cd[2]
    if det == 0:
        raise ValueError("WCS CD matrix is singular")

    w = int(width_px or h.get("IMAGEW") or h.get("NAXIS1") or 0)
    hh = int(height_px or h.get("IMAGEH") or h.get("NAXIS2") or 0)
    if not w or not hh:
        raise ValueError("image size unknown (no IMAGEW/IMAGEH or NAXIS in header)")

    crpix = (float(h["CRPIX1"]), float(h["CRPIX2"]))
    crval = (float(h["CRVAL1"]), float(h["CRVAL2"]))

    # Centre of the image in FITS 1-based pixel coordinates.
    ra_c, dec_c = pixel_to_radec((w + 1) / 2.0, (hh + 1) / 2.0, crpix, crval, cd)

    scale_deg = math.sqrt(abs(det))
    # For JPEG/PNG input the solvers number pixel rows from the top of the
    # picture (y_down=True), so "up" on screen is the -y direction. FITS
    # viewers draw row 1 at the bottom, so for FITS input "up" is +y.
    # The sky direction of a pixel step is the matching CD column, in
    # (east, north) standard coordinates; position angle is north->east.
    sgn = -1.0 if y_down else 1.0
    up_east, up_north = sgn * cd[1], sgn * cd[3]
    rotation = wrap360(math.atan2(up_east, up_north) * RAD)
    # Looking at the sky (from inside the sphere) with north up, east is on
    # the left. With y up that gives det(CD) < 0; with y down, det > 0.
    flipped = (det < 0) if y_down else (det > 0)

    return PlateSolution(
        ra_deg=ra_c, dec_deg=dec_c, rotation_deg=rotation,
        scale_arcsec=scale_deg * 3600.0,
        fov_width_deg=w * scale_deg, fov_height_deg=hh * scale_deg,
        width_px=w, height_px=hh, flipped=flipped,
        crpix=crpix, crval=crval, cd=cd, solver=solver, image=str(image),
    )


# --------------------------------------------------------------------------
# Image size without PIL (JPEG, PNG, FITS)
# --------------------------------------------------------------------------

def image_size(path: str | Path) -> tuple[int, int]:
    p = Path(path)
    with p.open("rb") as f:
        head = f.read(26)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
        if head[:6] == b"SIMPLE":
            f.seek(0)
            hdr = parse_fits_header_text(f.read(2880 * 4).decode("ascii", "replace"))
            return int(hdr["NAXIS1"]), int(hdr["NAXIS2"])
        if head[:2] == b"\xff\xd8":
            f.seek(2)
            while True:
                b = f.read(1)
                while b and b != b"\xff":
                    b = f.read(1)
                while b == b"\xff":
                    b = f.read(1)
                if not b:
                    break
                marker = b[0]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    continue
                seglen = int.from_bytes(f.read(2), "big")
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                              0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    data = f.read(5)
                    return int.from_bytes(data[3:5], "big"), int.from_bytes(data[1:3], "big")
                f.seek(seglen - 2, 1)
    raise ValueError(f"cannot read image size of {p}")
