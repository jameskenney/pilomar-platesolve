"""Pure-Python positional astronomy used by the plate-solve add-on.

No third-party packages: everything here runs on a stock Raspberry Pi OS
python3, so the add-on never has to share or modify Pi-lomar's virtualenv.

Conventions
-----------
* Angles are degrees unless a name ends in ``_rad``.
* RA/Dec are J2000 (ICRS) unless a function says "of date".
* Azimuth is measured from North through East (N=0, E=90, S=180, W=270),
  which is the convention Pi-lomar uses (home position is azimuth 180 = south).
* Longitude is positive East, negative West.

Accuracy
--------
Precession uses the IAU 1976 model; nutation and aberration (each < 20")
are ignored. For centring, only the *difference* between the target and
the solved position matters, and those small terms are almost identical for
two points a few degrees apart, so they cancel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

DEG = math.pi / 180.0
RAD = 180.0 / math.pi
J2000 = 2451545.0


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def wrap360(x: float) -> float:
    return x % 360.0


def wrap180(x: float) -> float:
    """Wrap an angle into [-180, 180)."""
    return (x + 180.0) % 360.0 - 180.0


def angular_separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Great-circle distance in degrees (haversine form, stable for small angles)."""
    ra1, dec1, ra2, dec2 = (v * DEG for v in (ra1, dec1, ra2, dec2))
    s = (math.sin((dec2 - dec1) / 2) ** 2
         + math.cos(dec1) * math.cos(dec2) * math.sin((ra2 - ra1) / 2) ** 2)
    return 2 * math.asin(min(1.0, math.sqrt(s))) * RAD


def hms_to_deg(h: float, m: float = 0.0, s: float = 0.0) -> float:
    return 15.0 * (abs(h) + m / 60.0 + s / 3600.0) * (-1 if h < 0 else 1)


def dms_to_deg(d: float, m: float = 0.0, s: float = 0.0, negative: bool | None = None) -> float:
    if negative is None:
        negative = d < 0 or m < 0 or s < 0
    v = abs(d) + abs(m) / 60.0 + abs(s) / 3600.0
    return -v if negative else v


def format_ra(ra_deg: float) -> str:
    h = wrap360(ra_deg) / 15.0
    hh = int(h)
    mm = int((h - hh) * 60)
    ss = ((h - hh) * 60 - mm) * 60
    if ss >= 59.995:
        ss, mm = 0.0, mm + 1
    if mm >= 60:
        mm, hh = mm - 60, (hh + 1) % 24
    return f"{hh:02d}h {mm:02d}m {ss:05.2f}s"


def format_dec(dec_deg: float) -> str:
    sign = "-" if dec_deg < 0 else "+"
    d = abs(dec_deg)
    dd = int(d)
    mm = int((d - dd) * 60)
    ss = ((d - dd) * 60 - mm) * 60
    if ss >= 59.95:
        ss, mm = 0.0, mm + 1
    if mm >= 60:
        mm, dd = mm - 60, dd + 1
    return f"{sign}{dd:02d}° {mm:02d}' {ss:04.1f}\""


# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------

def julian_date(t: datetime) -> float:
    """Julian Date (UTC treated as UT1; the < 1 s difference is irrelevant here)."""
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    t = t.astimezone(timezone.utc)
    y, m = t.year, t.month
    d = (t.day + (t.hour + (t.minute + (t.second + t.microsecond / 1e6) / 60.0) / 60.0) / 24.0)
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5


def gmst_deg(jd: float) -> float:
    """Greenwich Mean Sidereal Time in degrees (IAU 1982 expression)."""
    t = (jd - J2000) / 36525.0
    g = (280.46061837 + 360.98564736629 * (jd - J2000)
         + 0.000387933 * t * t - t * t * t / 38710000.0)
    return wrap360(g)


def lst_deg(jd: float, lon_east_deg: float) -> float:
    """Local mean sidereal time in degrees."""
    return wrap360(gmst_deg(jd) + lon_east_deg)


# --------------------------------------------------------------------------
# Precession (IAU 1976), J2000 <-> mean equator of date
# --------------------------------------------------------------------------

def _mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _mat_vec(m, v):
    return [sum(m[i][k] * v[k] for k in range(3)) for i in range(3)]


def _transpose(m):
    return [[m[j][i] for j in range(3)] for i in range(3)]


def _r2(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, 0, -s], [0, 1, 0], [s, 0, c]]


def _r3(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, s, 0], [-s, c, 0], [0, 0, 1]]


def precession_matrix(jd: float):
    """Rotation matrix taking J2000 mean coordinates to mean coordinates of date."""
    t = (jd - J2000) / 36525.0
    asec = DEG / 3600.0
    zeta = (2306.2181 * t + 0.30188 * t ** 2 + 0.017998 * t ** 3) * asec
    z = (2306.2181 * t + 1.09468 * t ** 2 + 0.018203 * t ** 3) * asec
    theta = (2004.3109 * t - 0.42665 * t ** 2 - 0.041833 * t ** 3) * asec
    return _mat_mul(_r3(-z), _mat_mul(_r2(theta), _r3(-zeta)))


def _radec_to_vec(ra, dec):
    ra, dec = ra * DEG, dec * DEG
    return [math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]


def _vec_to_radec(v):
    x, y, z = v
    ra = math.atan2(y, x) * RAD
    dec = math.atan2(z, math.hypot(x, y)) * RAD
    return wrap360(ra), dec


def j2000_to_date(ra: float, dec: float, jd: float) -> tuple[float, float]:
    return _vec_to_radec(_mat_vec(precession_matrix(jd), _radec_to_vec(ra, dec)))


def date_to_j2000(ra: float, dec: float, jd: float) -> tuple[float, float]:
    return _vec_to_radec(_mat_vec(_transpose(precession_matrix(jd)), _radec_to_vec(ra, dec)))


# --------------------------------------------------------------------------
# Horizontal coordinates
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Site:
    lat_deg: float
    lon_east_deg: float
    elevation_m: float = 0.0


def radec_of_date_to_altaz(ra: float, dec: float, lst: float, lat: float) -> tuple[float, float]:
    """(alt, az) for RA/Dec of date, local sidereal time and latitude (all degrees)."""
    h = (lst - ra) * DEG
    d, p = dec * DEG, lat * DEG
    sin_alt = math.sin(p) * math.sin(d) + math.cos(p) * math.cos(d) * math.cos(h)
    alt = math.asin(max(-1.0, min(1.0, sin_alt)))
    az = math.atan2(-math.cos(d) * math.sin(h),
                    math.sin(d) * math.cos(p) - math.cos(d) * math.sin(p) * math.cos(h))
    return alt * RAD, wrap360(az * RAD)


def altaz_to_radec_of_date(alt: float, az: float, lst: float, lat: float) -> tuple[float, float]:
    a, z, p = alt * DEG, az * DEG, lat * DEG
    sin_dec = math.sin(p) * math.sin(a) + math.cos(p) * math.cos(a) * math.cos(z)
    dec = math.asin(max(-1.0, min(1.0, sin_dec)))
    h = math.atan2(-math.cos(a) * math.sin(z),
                   math.sin(a) * math.cos(p) - math.cos(a) * math.sin(p) * math.cos(z))
    return wrap360(lst - h * RAD), dec * RAD


def j2000_to_altaz(ra: float, dec: float, site: Site, t: datetime) -> tuple[float, float]:
    """Geometric (unrefracted) altitude and azimuth of a J2000 position."""
    jd = julian_date(t)
    ra_d, dec_d = j2000_to_date(ra, dec, jd)
    return radec_of_date_to_altaz(ra_d, dec_d, lst_deg(jd, site.lon_east_deg), site.lat_deg)


def altaz_to_j2000(alt: float, az: float, site: Site, t: datetime) -> tuple[float, float]:
    jd = julian_date(t)
    ra_d, dec_d = altaz_to_radec_of_date(alt, az, lst_deg(jd, site.lon_east_deg), site.lat_deg)
    return date_to_j2000(ra_d, dec_d, jd)


def refraction_deg(true_alt_deg: float, pressure_hpa: float = 1010.0, temp_c: float = 10.0) -> float:
    """Saemundsson's atmospheric refraction for a true altitude (degrees)."""
    h = max(true_alt_deg, -1.0)
    r_arcmin = 1.02 / math.tan((h + 10.3 / (h + 5.11)) * DEG)
    return r_arcmin / 60.0 * (pressure_hpa / 1010.0) * (283.0 / (273.0 + temp_c))


def parallactic_angle(ra: float, dec: float, site: Site, t: datetime) -> float:
    """Angle between the north celestial pole and the zenith directions at a target.

    For an alt-az mount like Pi-lomar this is how far the field rotates
    relative to north; it changes as the target crosses the sky.
    """
    jd = julian_date(t)
    ra_d, dec_d = j2000_to_date(ra, dec, jd)
    h = (lst_deg(jd, site.lon_east_deg) - ra_d) * DEG
    p, d = site.lat_deg * DEG, dec_d * DEG
    return math.atan2(math.sin(h), math.tan(p) * math.cos(d) - math.sin(d) * math.cos(h)) * RAD


# --------------------------------------------------------------------------
# Tangent-plane offsets
# --------------------------------------------------------------------------

def tangent_offsets(ra0: float, dec0: float, ra: float, dec: float) -> tuple[float, float]:
    """Gnomonic standard coordinates (east, north) in degrees of (ra,dec) around (ra0,dec0)."""
    a0, d0, a, d = ra0 * DEG, dec0 * DEG, ra * DEG, dec * DEG
    den = math.sin(d) * math.sin(d0) + math.cos(d) * math.cos(d0) * math.cos(a - a0)
    xi = math.cos(d) * math.sin(a - a0) / den
    eta = (math.sin(d) * math.cos(d0) - math.cos(d) * math.sin(d0) * math.cos(a - a0)) / den
    return math.atan(xi) * RAD, math.atan(eta) * RAD


# --------------------------------------------------------------------------
# Sun and Moon (low precision, for "is it dark?" and moon avoidance only)
# --------------------------------------------------------------------------

def _ecl_to_eq(lam: float, beta: float, jd: float) -> tuple[float, float]:
    eps = (23.439291 - 0.0130042 * (jd - J2000) / 36525.0) * DEG
    l, b = lam * DEG, beta * DEG
    ra = math.atan2(math.sin(l) * math.cos(eps) - math.tan(b) * math.sin(eps), math.cos(l))
    dec = math.asin(math.sin(b) * math.cos(eps) + math.cos(b) * math.sin(eps) * math.sin(l))
    return wrap360(ra * RAD), dec * RAD


def sun_radec_of_date(jd: float) -> tuple[float, float]:
    n = jd - J2000
    L = wrap360(280.460 + 0.9856474 * n)
    g = wrap360(357.528 + 0.9856003 * n) * DEG
    lam = L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)
    return _ecl_to_eq(lam, 0.0, jd)


def moon_radec_of_date(jd: float) -> tuple[float, float]:
    """Astronomical Almanac low-precision Moon (about 0.3 deg, geocentric)."""
    t = (jd - J2000) / 36525.0
    s = lambda x: math.sin(x * DEG)  # noqa: E731
    lam = (218.32 + 481267.881 * t + 6.29 * s(135.0 + 477198.87 * t)
           - 1.27 * s(259.3 - 413335.36 * t) + 0.66 * s(235.7 + 890534.22 * t)
           + 0.21 * s(269.9 + 954397.74 * t) - 0.19 * s(357.5 + 35999.05 * t)
           - 0.11 * s(186.5 + 966404.03 * t))
    beta = (5.13 * s(93.3 + 483202.02 * t) + 0.28 * s(228.2 + 960400.89 * t)
            - 0.28 * s(318.3 + 6003.15 * t) - 0.17 * s(217.6 - 407332.21 * t))
    return _ecl_to_eq(wrap360(lam), beta, jd)


def body_altaz(body: str, site: Site, t: datetime) -> tuple[float, float]:
    jd = julian_date(t)
    ra, dec = (sun_radec_of_date if body == "sun" else moon_radec_of_date)(jd)
    return radec_of_date_to_altaz(ra, dec, lst_deg(jd, site.lon_east_deg), site.lat_deg)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
