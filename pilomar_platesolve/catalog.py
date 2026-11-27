"""Find targets by name ("M31", "andromeda", "NGC 7000") or by coordinates.

The primary source is Pi-lomar's own catalogue files (``data/messierobjects.json``
and ``data/ngc.json``), opened read-only, so names match what Pi-lomar shows.
A small built-in list keeps the tool usable off the Pi and in tests.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .astro import dms_to_deg, hms_to_deg


@dataclass
class Target:
    id: str
    name: str
    ra_deg: float      # J2000
    dec_deg: float
    magnitude: float | None = None
    kind: str = ""
    size_deg: float | None = None
    source: str = ""


# A few dozen bright deep-sky objects (J2000). Used only when Pi-lomar's
# catalogue is not available.
_BUILTIN = [
    # id, name, RA h m s, Dec d m s, mag, type, size (arcmin)
    ("m1", "Crab Nebula", (5, 34, 31.9), (22, 0, 52), 8.4, "supernova remnant", 6),
    ("m3", "", (13, 42, 11.6), (28, 22, 38), 6.2, "globular cluster", 18),
    ("m5", "", (15, 18, 33.2), (2, 4, 52), 5.6, "globular cluster", 23),
    ("m8", "Lagoon Nebula", (18, 3, 37), (-24, -23, -12), 6.0, "nebula", 90),
    ("m11", "Wild Duck Cluster", (18, 51, 6), (-6, -16, 0), 5.8, "open cluster", 14),
    ("m13", "Hercules Globular Cluster", (16, 41, 41.2), (36, 27, 37), 5.8, "globular cluster", 20),
    ("m15", "", (21, 29, 58.3), (12, 10, 1), 6.2, "globular cluster", 18),
    ("m16", "Eagle Nebula", (18, 18, 48), (-13, -49, 0), 6.0, "nebula", 35),
    ("m17", "Omega Nebula", (18, 20, 26), (-16, -10, -36), 6.0, "nebula", 11),
    ("m20", "Trifid Nebula", (18, 2, 23), (-23, -1, -48), 6.3, "nebula", 28),
    ("m22", "", (18, 36, 24.2), (-23, -54, -12), 5.1, "globular cluster", 32),
    ("m27", "Dumbbell Nebula", (19, 59, 36.3), (22, 43, 16), 7.5, "planetary nebula", 8),
    ("m31", "Andromeda Galaxy", (0, 42, 44.3), (41, 16, 9), 3.4, "galaxy", 178),
    ("m32", "", (0, 42, 41.8), (40, 51, 55), 8.1, "galaxy", 8),
    ("m33", "Triangulum Galaxy", (1, 33, 50.9), (30, 39, 37), 5.7, "galaxy", 70),
    ("m35", "", (6, 8, 54), (24, 20, 0), 5.3, "open cluster", 28),
    ("m42", "Orion Nebula", (5, 35, 17.3), (-5, -23, -28), 4.0, "nebula", 85),
    ("m44", "Beehive Cluster", (8, 40, 24), (19, 40, 0), 3.7, "open cluster", 95),
    ("m45", "Pleiades", (3, 47, 24), (24, 7, 0), 1.6, "open cluster", 110),
    ("m51", "Whirlpool Galaxy", (13, 29, 52.7), (47, 11, 43), 8.4, "galaxy", 11),
    ("m57", "Ring Nebula", (18, 53, 35.1), (33, 1, 45), 8.8, "planetary nebula", 1.4),
    ("m64", "Black Eye Galaxy", (12, 56, 43.7), (21, 40, 58), 8.5, "galaxy", 10),
    ("m81", "Bode's Galaxy", (9, 55, 33.2), (69, 3, 55), 6.9, "galaxy", 27),
    ("m82", "Cigar Galaxy", (9, 55, 52.2), (69, 40, 47), 8.4, "galaxy", 11),
    ("m92", "", (17, 17, 7.4), (43, 8, 9), 6.4, "globular cluster", 14),
    ("m97", "Owl Nebula", (11, 14, 47.7), (55, 1, 9), 9.9, "planetary nebula", 3.4),
    ("m101", "Pinwheel Galaxy", (14, 3, 12.6), (54, 20, 57), 7.9, "galaxy", 29),
    ("m104", "Sombrero Galaxy", (12, 39, 59.4), (-11, -37, -23), 8.0, "galaxy", 9),
    ("m110", "", (0, 40, 22.1), (41, 41, 7), 8.5, "galaxy", 22),
    ("ngc869", "Double Cluster (h Persei)", (2, 19, 0), (57, 8, 0), 3.7, "open cluster", 30),
    ("ngc884", "Double Cluster (chi Persei)", (2, 22, 18), (57, 8, 0), 3.8, "open cluster", 30),
    ("ngc7000", "North America Nebula", (20, 59, 17), (44, 31, 44), 4.0, "nebula", 120),
    ("ngc253", "Sculptor Galaxy", (0, 47, 33.1), (-25, -17, -18), 7.1, "galaxy", 27),
]


def _norm(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"^(messier)\s*", "m", s)
    s = re.sub(r"^(m|ngc|ic)\s+(\d)", r"\1\2", s)
    return s.replace("the ", "").strip()


def builtin_targets() -> dict[str, Target]:
    out = {}
    for tid, name, ra, dec, mag, kind, size in _BUILTIN:
        out[tid] = Target(tid, name, hms_to_deg(*ra), dms_to_deg(*dec), mag, kind,
                          size / 60.0, "builtin")
    return out


def _entry_coords(v: dict) -> tuple[float, float] | None:
    for rk, dk in (("radeg", "decdeg"), ("ra_degrees", "dec_degrees"), ("ra_deg", "dec_deg")):
        if rk in v and dk in v and v[rk] is not None and v[dk] is not None:
            return float(v[rk]), float(v[dk])
    ra, dec = v.get("ra"), v.get("dec")
    if isinstance(ra, list) and isinstance(dec, list) and len(ra) == 3 and len(dec) == 3:
        return hms_to_deg(*ra), dms_to_deg(*dec)
    return None


def load_pilomar_catalog(path: Path) -> dict[str, Target]:
    """Read one of Pi-lomar's catalogue JSON files (read-only)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    items = data.items() if isinstance(data, dict) else enumerate(data)
    out: dict[str, Target] = {}
    for key, v in items:
        if not isinstance(v, dict):
            continue
        c = _entry_coords(v)
        if c is None:
            continue
        tid = _norm(str(v.get("label") or v.get("messier") or v.get("ngc") or key))
        name = str(v.get("name") or "").strip()
        size = v.get("widthdeg")
        mag = v.get("magnitude")
        out[tid] = Target(tid, name.title(), c[0], c[1],
                          float(mag) if isinstance(mag, (int, float)) else None,
                          str(v.get("typelabel") or v.get("type") or ""),
                          float(size) if isinstance(size, (int, float)) else None,
                          path.name)
        ngc = v.get("ngc")
        if ngc and _norm(str(ngc)) not in out:
            out[_norm(str(ngc))] = out[tid]
    return out


class Catalog:
    def __init__(self, pilomar_root: str | Path | None = None):
        self.targets: dict[str, Target] = builtin_targets()
        self.sources = ["builtin"]
        if pilomar_root:
            for fname in ("ngc.json", "messierobjects.json"):  # Messier wins on clashes
                p = Path(pilomar_root) / "data" / fname
                if p.exists():
                    try:
                        self.targets.update(load_pilomar_catalog(p))
                        self.sources.append(str(p))
                    except (OSError, ValueError, json.JSONDecodeError):
                        pass

    def resolve(self, text: str) -> Target:
        """Look up a target by id, name, or 'RA Dec' coordinates."""
        coords = parse_coordinates(text)
        if coords:
            return Target("coords", text.strip(), coords[0], coords[1], source="coordinates")
        key = _norm(text)
        if key in self.targets:
            return self.targets[key]
        hits = [t for t in self.targets.values() if key and key in _norm(t.name)]
        uniq = {id(t): t for t in hits}
        if len(uniq) == 1:
            return next(iter(uniq.values()))
        if uniq:
            names = ", ".join(sorted(f"{t.id} ({t.name})" for t in uniq.values()))
            raise KeyError(f"'{text}' matches several targets: {names}")
        raise KeyError(f"unknown target '{text}'")

    def all(self) -> list[Target]:
        return list({id(t): t for t in self.targets.values()}.values())


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """Accept '10.684 41.269' (degrees) or '00:42:44 +41:16:09' / '0h42m44s 41d16m09s'."""
    t = text.strip().replace(",", " ")
    parts = t.split()
    if len(parts) != 2:
        return None
    a, b = parts
    num = re.compile(r"^[+-]?\d+(\.\d+)?$")
    if num.match(a) and num.match(b):
        ra, dec = float(a), float(b)
        return (ra, dec) if 0 <= ra < 360 and -90 <= dec <= 90 else None
    sexa = re.compile(r"^([+-]?)(\d+)[:hd° ](\d+)[:m' ](\d+(\.\d+)?)s?\"?$")
    ma, mb = sexa.match(a), sexa.match(b)
    if ma and mb:
        ra = hms_to_deg(float(ma.group(2)), float(ma.group(3)), float(ma.group(4)))
        dec = dms_to_deg(float(mb.group(2)), float(mb.group(3)), float(mb.group(4)),
                         negative=mb.group(1) == "-")
        return ra, dec
    return None
