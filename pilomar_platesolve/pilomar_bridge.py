"""Read-only view of a Pi-lomar installation.

This module is the *only* place that knows about Pi-lomar's files. It never
writes to them, and every lookup degrades gracefully if Pi-lomar changes a
name in a future release (you just get ``None`` and a clear message).
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from .astro import Site


def read_params(pilomar_root: str | Path) -> dict:
    p = Path(pilomar_root) / "data" / "pilomar_params.json"
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def parse_lat_lon(value, positive: str, negative: str) -> float | None:
    """Turn 35.47, "35.47", "35.47 N", "97.52 W" or "-97.52" into signed degrees."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().upper()
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*([NSEW])?$", s)
    if not m:
        return None
    v = float(m.group(1))
    if m.group(2) == negative:
        v = -abs(v)
    elif m.group(2) == positive:
        v = abs(v)
    return v


def site_from_config(cfg: dict) -> Site:
    s = cfg.get("site", {})
    lat, lon = s.get("lat_deg"), s.get("lon_east_deg")
    if lat is None or lon is None:
        params = read_params(cfg["pilomar_root"])
        lat = lat if lat is not None else parse_lat_lon(params.get("HomeLat"), "N", "S")
        lon = lon if lon is not None else parse_lat_lon(params.get("HomeLon"), "E", "W")
    if lat is None or lon is None:
        raise RuntimeError(
            "observing site unknown: set site.lat_deg / site.lon_east_deg in config.json, "
            "or set your home location in Pi-lomar")
    return Site(float(lat), float(lon), float(s.get("elevation_m") or 0.0))


def pilomar_running() -> bool:
    """True if a pilomar.py process is running (Linux /proc scan, no psutil)."""
    proc = Path("/proc")
    if not proc.exists():
        return False
    me = os.getpid()
    for d in proc.iterdir():
        if not d.name.isdigit() or int(d.name) == me:
            continue
        try:
            cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
        except OSError:
            continue
        if "pilomar.py" in cmd:
            return True
    return False


def newest_image(pilomar_root: str | Path, pattern: str, newer_than: float = 0.0) -> Path | None:
    root = Path(pilomar_root)
    best, best_t = None, newer_than
    for p in root.glob(pattern):
        try:
            t = p.stat().st_mtime
        except OSError:
            continue
        if t > best_t and ".solution." not in p.name:
            best, best_t = p, t
    return best


def wait_for_new_image(pilomar_root, pattern: str, since: float, timeout_s: float,
                       settle_s: float = 1.0, poll_s: float = 1.0) -> Path | None:
    """Wait for Pi-lomar to save a new image, then wait until it stops growing."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        p = newest_image(pilomar_root, pattern, since)
        if p is not None:
            size = -1
            while size != p.stat().st_size:
                size = p.stat().st_size
                time.sleep(settle_s)
            return p
        time.sleep(poll_s)
    return None
