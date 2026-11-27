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

    def true_pointing(self, when: datetime) -> tuple[float, float]:
        alt, az = astro.j2000_to_altaz(self.target.ra_deg, self.target.dec_deg, self.site, when)
        alt += self.mount.err_alt + self.rng.gauss(0, self.noise)
        az += self.mount.err_az + self.rng.gauss(0, self.noise)
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
