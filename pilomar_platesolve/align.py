"""Startup alignment: visit a few spread-out targets, plate-solve each, fit the
mount's pointing model. No Tune moves are made during alignment, so each
picture compares Pi-lomar's own idea of where it points with reality."""

from __future__ import annotations

import csv
import math
from datetime import datetime
from pathlib import Path

from . import astro
from .astro import Site, wrap180
from .catalog import Target
from .centering import (Logbook, UnsafeTarget, check_goto_safe, expected_fov_width,
                        solve_with_fallback)
from .model import PointingModel, PointingState, Sample, fit_model
from .solvers import SolveError, SolveHint, Solver


def _altaz_distance(a1, e1, a2, e2) -> float:
    a1, e1, a2, e2 = (v * math.pi / 180 for v in (a1, e1, a2, e2))
    c = math.sin(e1) * math.sin(e2) + math.cos(e1) * math.cos(e2) * math.cos(a1 - a2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def az_in_range(az: float, az_range) -> bool:
    """az_range = (start, end) going clockwise; (270, 90) passes through north."""
    if not az_range:
        return True
    a, b = az_range[0] % 360, az_range[1] % 360
    az %= 360
    return a <= az <= b if a <= b else (az >= a or az <= b)


def choose_alignment_targets(targets: list[Target], site: Site, when: datetime, n: int = 6,
                             min_alt: float = 25.0, max_alt: float = 75.0,
                             az_range=None) -> list[Target]:
    """Pick n catalogue targets spread as widely as possible across the visible sky,
    optionally only between min_alt and max_alt and inside an azimuth range."""
    cands = []
    for t in targets:
        alt, az = astro.j2000_to_altaz(t.ra_deg, t.dec_deg, site, when)
        if min_alt <= alt <= max_alt and az_in_range(az, az_range):
            cands.append((t, az, alt))
    if not cands:
        return []
    # Start low in the south-ish part of the sky, then repeatedly add the
    # candidate farthest from everything chosen so far.
    chosen = [min(cands, key=lambda c: abs(wrap180(c[1] - 180)) + abs(c[2] - 40))]
    while len(chosen) < n and len(chosen) < len(cands):
        best = max((c for c in cands if c not in chosen),
                   key=lambda c: min(_altaz_distance(c[1], c[2], k[1], k[2]) for k in chosen))
        if min(_altaz_distance(best[1], best[2], k[1], k[2]) for k in chosen) < 5:
            break  # nothing usefully different left
        chosen.append(best)
    # Visit in azimuth order, starting from the range's start: one sweep, no wrap.
    start = az_range[0] % 360 if az_range else 0.0
    chosen.sort(key=lambda c: (c[1] - start) % 360)
    return [c[0] for c in chosen]


def run_alignment(targets: list[Target], *, cfg: dict, site: Site, source, solver: Solver,
                  mount, state: PointingState, log: Logbook | None = None,
                  verbose: bool = True) -> tuple[PointingModel | None, list[Sample]]:
    say = print if verbose else (lambda *a, **k: None)
    samples: list[Sample] = []
    fov = expected_fov_width(cfg)
    for i, t in enumerate(targets, 1):
        say(f"\n[{i}/{len(targets)}] {t.id} {t.name}")
        if getattr(mount, "name", "") != "simulated":
            try:
                check_goto_safe(t, site, astro.utcnow(), cfg)
            except UnsafeTarget as e:
                say(f"  skipping: {e}")
                continue
        if not mount.goto(t):
            say("  stopped by user")
            break
        image, when = source.capture()
        hint = SolveHint(t.ra_deg, t.dec_deg, float(cfg["solver"]["search_radius_deg"]), fov)
        try:
            sol = solve_with_fallback(solver, image, hint, True)
        except SolveError as e:
            say(f"  no solution ({e}); skipping this point")
            if log:
                log.event("solve_failed", target=t.id, error=str(e))
            continue
        l_alt, l_az = astro.j2000_to_altaz(t.ra_deg, t.dec_deg, site, when)
        # Mount frame = Pi-lomar's logical position. Any Tune moves made before
        # alignment are physically baked in, so the ledger restarts at zero.
        # Read it from Pi-lomar when possible (it doesn't track at its menu).
        pos = mount.position() if hasattr(mount, "position") else None
        m_az, m_alt = pos if pos is not None else (l_az, l_alt)
        a_alt, a_az = astro.j2000_to_altaz(sol.ra_deg, sol.dec_deg, site, when)
        s = Sample(m_az, m_alt, a_az, a_alt, t.id)
        samples.append(s)
        say(f"  mount az {m_az:7.2f} alt {m_alt:6.2f}  |  actual az {a_az:7.2f} alt {a_alt:6.2f}"
            f"  |  error az {s.d_az:+.2f}° alt {s.d_alt:+.2f}°")
        if log:
            log.event("align_sample", target=t.id, image=str(image), sample=s.__dict__,
                      solution=sol.to_dict())
    if len(samples) < 2:
        say("\nToo few solved pictures to fit a model.")
        return None, samples
    model = fit_model(samples)
    state.reset(epoch=model.epoch)
    return model, samples


def samples_from_log(csv_path: str | Path, epoch: str) -> list[Sample]:
    """Reuse every solve logged in the current epoch (e.g. from `center`) to refit."""
    out = []
    p = Path(csv_path)
    if not p.exists():
        return out
    with open(p, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("epoch", "") != epoch or not r.get("mount_az"):
                continue
            out.append(Sample(float(r["mount_az"]), float(r["mount_alt"]),
                              float(r["actual_az"]), float(r["actual_alt"]), r.get("target", "")))
    return out
