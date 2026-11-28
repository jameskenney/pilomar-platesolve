"""Annotated copy of a solved picture: what is in the frame, and where.

Like the '.solution.jpg' Pi-lomar's own solver draws, this marks:

* the image centre (white crosshair) and, if given, the target (red),
* north and east arrows worked out from the plate solution,
* stars from Pi-lomar's Hipparcos catalogue (yellow circles, brighter = bigger),
* names of bright stars (green) and deep-sky objects in view (orange),
* a text block with RA/Dec, rotation, field of view, plate scale and time.

The picture is written to this add-on's own folder (data/annotated), never
next to Pi-lomar's pictures. Drawing uses OpenCV, which Pi-lomar installs.
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

from .astro import format_dec, format_ra
from .wcs import PlateSolution

# Proper names of bright stars, J2000 (RA, Dec in degrees). Placed by
# position, so no catalogue numbers are needed.
STAR_NAMES = [
    ("Alpheratz", 2.10, 29.09), ("Caph", 2.29, 59.15), ("Algenib", 3.31, 15.18),
    ("Schedar", 10.13, 56.54), ("Diphda", 10.90, -17.99), ("Navi", 14.18, 60.72),
    ("Mirach", 17.43, 35.62), ("Ruchbah", 21.45, 60.24), ("Achernar", 24.43, -57.24),
    ("Sheratan", 28.66, 20.81), ("Almach", 30.97, 42.33), ("Hamal", 31.79, 23.46),
    ("Mira", 34.84, -2.98), ("Polaris", 37.95, 89.26), ("Menkar", 45.57, 4.09),
    ("Algol", 47.04, 40.96), ("Mirfak", 51.08, 49.86), ("Alcyone", 56.87, 24.11),
    ("Aldebaran", 68.98, 16.51), ("Rigel", 78.63, -8.20), ("Capella", 79.17, 46.00),
    ("Bellatrix", 81.28, 6.35), ("Elnath", 81.57, 28.61), ("Mintaka", 83.00, -0.30),
    ("Alnilam", 84.05, -1.20), ("Alnitak", 85.19, -1.94), ("Saiph", 86.94, -9.67),
    ("Betelgeuse", 88.79, 7.41), ("Menkalinan", 89.88, 44.95), ("Canopus", 95.99, -52.70),
    ("Sirius", 101.29, -16.72), ("Castor", 113.65, 31.89), ("Procyon", 114.83, 5.22),
    ("Pollux", 116.33, 28.03), ("Alphard", 141.90, -8.66), ("Regulus", 152.09, 11.97),
    ("Algieba", 154.99, 19.84), ("Merak", 165.46, 56.38), ("Dubhe", 165.93, 61.75),
    ("Denebola", 177.26, 14.57), ("Phecda", 178.46, 53.69), ("Megrez", 183.86, 57.03),
    ("Alioth", 193.51, 55.96), ("Mizar", 200.98, 54.93), ("Spica", 201.30, -11.16),
    ("Alkaid", 206.89, 49.31), ("Arcturus", 213.92, 19.18), ("Kochab", 222.68, 74.16),
    ("Zubenelgenubi", 222.72, -16.04), ("Antares", 247.35, -26.43),
    ("Shaula", 263.40, -37.10), ("Rasalhague", 263.73, 12.56), ("Eltanin", 269.15, 51.49),
    ("Kaus Australis", 276.04, -34.38), ("Vega", 279.23, 38.78), ("Nunki", 283.82, -26.30),
    ("Albireo", 292.68, 27.96), ("Altair", 297.70, 8.87), ("Sadr", 305.56, 40.26),
    ("Deneb", 310.36, 45.28), ("Alderamin", 319.64, 62.59), ("Enif", 326.05, 9.88),
    ("Fomalhaut", 344.41, -29.62), ("Scheat", 345.94, 28.08), ("Markab", 346.19, 15.21),
]

# BGR colours for OpenCV
WHITE, RED, GREEN, YELLOW, ORANGE, CYAN = ((255, 255, 255), (60, 60, 255), (80, 255, 80),
                                           (0, 220, 255), (0, 160, 255), (255, 220, 0))


def available() -> bool:
    try:
        import cv2  # noqa: F401
        return True
    except ImportError:
        return False


def load_stars(path: str | Path, max_mag: float = 6.5) -> list[tuple[int, float, float, float]]:
    """(HIP number, RA, Dec, Vmag) from Pi-lomar's hip_main.dat."""
    out = []
    with open(path, encoding="latin-1") as f:
        for line in f:
            p = line.split("|")
            if len(p) < 10:
                continue
            try:
                mag = float(p[5])
                if mag > max_mag:
                    continue
                out.append((int(p[1]), float(p[8]), float(p[9]), mag))
            except ValueError:
                continue
    return out


def _in_view(sol: PlateSolution, ra: float, dec: float, margin: float = 0.0):
    """Array (x, y) if (ra, dec) is on the picture (and in front of the camera)."""
    c = (math.sin(math.radians(dec)) * math.sin(math.radians(sol.crval[1])) +
         math.cos(math.radians(dec)) * math.cos(math.radians(sol.crval[1])) *
         math.cos(math.radians(ra - sol.crval[0])))
    if c < math.cos(math.radians(min(80.0, sol.fov_diag_deg))):
        return None
    x, y = sol.radec_to_pixel(ra, dec)
    x, y = x - 1, y - 1      # FITS pixels are 1-based
    if -margin <= x < sol.width_px + margin and -margin <= y < sol.height_px + margin:
        return x, y
    return None


def _direction(sol: PlateSolution, d_ra: float, d_dec: float) -> tuple[float, float]:
    """Unit vector on the picture for a small step on the sky from the centre."""
    cx, cy = sol.radec_to_pixel(sol.ra_deg, sol.dec_deg)
    x, y = sol.radec_to_pixel(sol.ra_deg + d_ra / max(0.05, math.cos(math.radians(sol.dec_deg))),
                              sol.dec_deg + d_dec)
    dx, dy = x - cx, y - cy
    n = math.hypot(dx, dy) or 1.0
    return dx / n, dy / n


def annotate(image: str | Path, sol: PlateSolution, out: str | Path, *, stars=None,
             dsos=None, target=None, when: datetime | None = None, star_limit: int = 150,
             title: str = "") -> dict:
    """Draw the overlay and save it. Returns a summary of what was labelled."""
    import cv2
    img = cv2.imread(str(image), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"can't read {image}")
    h, w = img.shape[:2]
    if (w, h) != (sol.width_px, sol.height_px):
        # Solved at another size (e.g. a reduced copy): scale the solution.
        img = cv2.resize(img, (sol.width_px, sol.height_px))
        h, w = img.shape[:2]
    u = max(1.0, w / 1000.0)                 # size unit: 1 at 1000 px wide
    th = max(1, int(round(u)))
    fs = 0.45 * u
    font = cv2.FONT_HERSHEY_SIMPLEX

    def text(s, x, y, colour, scale=fs, thick=th):
        cv2.putText(img, s, (int(x), int(y)), font, scale, (0, 0, 0), thick + 2, cv2.LINE_AA)
        cv2.putText(img, s, (int(x), int(y)), font, scale, colour, thick, cv2.LINE_AA)

    summary = {"stars": 0, "named": [], "dsos": []}

    # Catalogue stars, brightest first
    if stars:
        shown = []
        for hip, ra, dec, mag in stars:
            p = _in_view(sol, ra, dec)
            if p:
                shown.append((mag, p))
        shown.sort()
        for mag, (x, y) in shown[:star_limit]:
            r = int(round(u * max(3.0, 9.0 - mag)))
            cv2.circle(img, (int(x), int(y)), r, YELLOW, th, cv2.LINE_AA)
        summary["stars"] = min(len(shown), star_limit)

    # Bright-star names
    for name, ra, dec in STAR_NAMES:
        p = _in_view(sol, ra, dec)
        if p:
            text(name, p[0] + 10 * u, p[1] - 8 * u, GREEN, fs * 1.2)
            summary["named"].append(name)

    # Deep-sky objects. Catalogues list some objects twice (NGC 205 is M110,
    # PGC 2557 is M31): label each place once, preferring the Messier name.
    def rank(t):
        i = t.id.lower()
        return (0 if i[:1] == "m" and i[1:].isdigit() else 1 if i.startswith(("ngc", "ic")) else 2, i)
    placed: list[tuple[float, float]] = []
    for t in sorted(dsos or [], key=rank):
        p = _in_view(sol, t.ra_deg, t.dec_deg)
        if not p:
            continue
        near = max(6.0, 0.05 * 3600 / sol.scale_arcsec)      # 0.05° or 6 px
        if any(math.hypot(p[0] - q[0], p[1] - q[1]) < near for q in placed):
            continue
        placed.append(p)
        r_px = 12 * u
        if t.size_deg:
            r_px = max(r_px, t.size_deg * 3600 / sol.scale_arcsec / 2)
        cv2.circle(img, (int(p[0]), int(p[1])), int(r_px), ORANGE, th, cv2.LINE_AA)
        label = t.id.upper() + (f" {t.name}" if t.name else "")
        text(label, p[0] + r_px * 0.75, p[1] + r_px * 0.75 + 14 * u, ORANGE, fs * 1.1)
        summary["dsos"].append(t.id)

    # Centre crosshair
    cx, cy = w / 2, h / 2
    g, L = 12 * u, 45 * u
    for (x1, y1, x2, y2) in ((cx - L, cy, cx - g, cy), (cx + g, cy, cx + L, cy),
                             (cx, cy - L, cx, cy - g), (cx, cy + g, cx, cy + L)):
        cv2.line(img, (int(x1), int(y1)), (int(x2), int(y2)), WHITE, th, cv2.LINE_AA)

    # Target marker and offset line
    if target is not None:
        p = _in_view(sol, target.ra_deg, target.dec_deg, margin=max(w, h))
        if p:
            tx, ty = p
            on = 0 <= tx < w and 0 <= ty < h
            if on:
                cv2.drawMarker(img, (int(tx), int(ty)), RED, cv2.MARKER_CROSS, int(30 * u), th + 1)
            cv2.line(img, (int(cx), int(cy)), (int(min(max(tx, 0), w - 1)), int(min(max(ty, 0), h - 1))),
                     RED, th, cv2.LINE_AA)

    # North / east arrows, bottom-left
    ox, oy, a = 90 * u, h - 90 * u, 60 * u
    for label, (dra, ddec), colour in (("N", (0.0, 0.2), CYAN), ("E", (0.2, 0.0), CYAN)):
        dx, dy = _direction(sol, dra, ddec)
        end = (int(ox + dx * a), int(oy + dy * a))
        cv2.arrowedLine(img, (int(ox), int(oy)), end, colour, th + 1, cv2.LINE_AA, tipLength=0.25)
        text(label, end[0] + dx * 12 * u - 6 * u, end[1] + dy * 12 * u + 6 * u, colour, fs * 1.2)

    # Information block, top-left
    lines = [title] if title else []
    lines += [
        f"RA {format_ra(sol.ra_deg)}   Dec {format_dec(sol.dec_deg)}",
        f"Rotation {sol.rotation_deg:.1f} deg   Field {sol.fov_width_deg:.2f} x {sol.fov_height_deg:.2f} deg",
        f"Scale {sol.scale_arcsec:.2f}\"/px   Solved in {sol.solve_seconds:.1f} s",
    ]
    if when:
        lines.append(when.strftime("%Y-%m-%d %H:%M:%S UTC"))
    for i, s in enumerate(lines):
        text(s, 20 * u, (30 + 24 * i) * u, WHITE)

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    summary["path"] = str(out)
    return summary
