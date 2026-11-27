"""A virtual sky, mount and solver so the whole loop can be tested indoors.

The simulated Pi-lomar tracks the target perfectly *except* for a fixed
alt/az pointing error (the kind left by imperfect homing or levelling), which
is exactly what the plate-solve loop is meant to remove.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

from . import astro
from .astro import Site
from .catalog import Target
from .mount import SimulatedMount
from .solvers import SolveError, SolveHint, Solver
from .wcs import PlateSolution, solution_from_header


class SimWorld:
    def __init__(self, target: Target, site: Site, start: datetime, mount: SimulatedMount,
                 seconds_per_picture: float = 30.0, noise_deg: float = 0.005, seed: int = 1,
                 fail_solves: int = 0):
        self.target, self.site, self.t = target, site, start
        self.mount = mount
        self.step = timedelta(seconds=seconds_per_picture)
        self.noise = noise_deg
        self.rng = random.Random(seed)
        self.fail_solves = fail_solves
        self.pointings: dict[str, tuple[float, float]] = {}
        self.count = 0

    def current_target(self) -> Target:
        """Whatever the mount last slewed to (alignment), else the fixed target."""
        return self.mount.gotos[-1] if getattr(self.mount, "gotos", None) else self.target

    def true_pointing(self, when: datetime) -> tuple[float, float]:
        t = self.current_target()
        alt, az = astro.j2000_to_altaz(t.ra_deg, t.dec_deg, self.site, when)
        alt, az = self.mount.actual_altaz(alt, az)
        alt += self.rng.gauss(0, self.noise)
        az += self.rng.gauss(0, self.noise)
        return astro.altaz_to_j2000(alt, az, self.site, when)


class SimSource:
    def __init__(self, world: SimWorld):
        self.w = world

    def capture(self):
        self.w.count += 1
        when = self.w.t
        self.w.t += self.w.step
        name = f"sim_{self.w.count:03d}.jpg"
        self.w.pointings[name] = self.w.true_pointing(when)
        return Path(name), when


class SimSolver(Solver):
    name = "simulated"

    def __init__(self, world: SimWorld, width=2028, height=1520, scale_arcsec=39.4, rotation_deg=20.0):
        self.w = world
        self.size = (width, height)
        self.scale = scale_arcsec / 3600.0
        self.rot = rotation_deg

    def available(self):
        return True

    def solve(self, image, hint: SolveHint | None = None) -> PlateSolution:
        if self.w.fail_solves > 0:
            self.w.fail_solves -= 1
            raise SolveError("simulated failure (clouds)")
        ra, dec = self.w.pointings[Path(image).name]
        import math
        r = math.radians(self.rot)
        s = self.scale
        # y-down image whose top edge points at position angle `rot`, not mirrored.
        cd = (-s * math.cos(r), -s * math.sin(r), s * math.sin(r), -s * math.cos(r))
        w, h = self.size
        hdr = {"CRVAL1": ra, "CRVAL2": dec, "CRPIX1": (w + 1) / 2, "CRPIX2": (h + 1) / 2,
               "CD1_1": cd[0], "CD1_2": cd[1], "CD2_1": cd[2], "CD2_2": cd[3],
               "IMAGEW": w, "IMAGEH": h}
        sol = solution_from_header(hdr, solver=self.name, image=str(image), y_down=True)
        sol.solve_seconds = 0.0
        return sol


def simulate_alignment(cfg: dict, site: Site, start: datetime, geometry, catalog_targets,
                       n_points: int = 6, n_tests: int = 8, noise_deg: float = 0.01,
                       verbose: bool = True, seed: int = 3):
    """Align a virtual mount with known faults, then GOTO test targets with the model.

    Returns (fitted model, list of (target id, error without model, error with model)).
    """
    from .align import choose_alignment_targets, run_alignment
    from .centering import apply_model_correction
    from .model import PointingState

    say = print if verbose else (lambda *a, **k: None)
    mount = SimulatedMount(cfg["mount"], geometry=geometry)
    pts = choose_alignment_targets(catalog_targets, site, start, n_points)
    if len(pts) < 3:
        raise RuntimeError("not enough catalogue targets above the horizon for alignment")
    world = SimWorld(pts[0], site, start, mount, seconds_per_picture=60, noise_deg=noise_deg, seed=seed)
    state = PointingState(None)
    say(f"Alignment targets: {', '.join(t.id for t in pts)}")
    model, _ = run_alignment(pts, cfg=cfg, site=site, source=SimSource(world), solver=SimSolver(world),
                             mount=mount, state=state, verbose=verbose)
    if model is None:
        raise RuntimeError("alignment failed")
    say("\nFitted model:\n" + model.describe())

    rng = random.Random(seed)
    when = world.t
    visible = [t for t in catalog_targets
               if astro.j2000_to_altaz(t.ra_deg, t.dec_deg, site, when)[0] > 20]
    tests = rng.sample(visible, min(n_tests, len(visible)))
    results = []
    say(f"\nGOTO test without pictures ({len(tests)} targets):")
    for t in tests:
        alt, az = astro.j2000_to_altaz(t.ra_deg, t.dec_deg, site, when)
        raw = SimulatedMount(cfg["mount"], geometry=geometry).actual_altaz(alt, az)
        before = _sep_altaz(az, alt, raw[1], raw[0])
        mount.goto(t)
        apply_model_correction(t, model, state, site, mount, cfg, when, say=lambda *a, **k: None)
        a_alt, a_az = mount.actual_altaz(alt, az)
        after = _sep_altaz(az, alt, a_az, a_alt)
        results.append((t.id, before, after))
        say(f"  {t.id:8} off by {before:5.2f}° without model  ->  {after:5.3f}° with model")
        when += timedelta(minutes=3)
    return model, results


def _sep_altaz(az1, alt1, az2, alt2) -> float:
    import math
    r = math.radians
    c = (math.sin(r(alt1)) * math.sin(r(alt2))
         + math.cos(r(alt1)) * math.cos(r(alt2)) * math.cos(r(az1 - az2)))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))
