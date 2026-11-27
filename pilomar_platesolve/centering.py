"""Compare "where we wanted to point" with "where the solver says we point",
and run the capture -> solve -> correct loop until the target is centred."""

from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from . import astro
from .astro import Site, wrap180
from .catalog import Target
from .mount import Mount
from .solvers import SolveError, SolveHint, Solver
from .wcs import PlateSolution


@dataclass
class PointingError:
    """Target minus actual, in the two frames that matter."""

    when: str
    separation_deg: float          # total miss on the sky
    east_deg: float                # + = camera points EAST of the target
    north_deg: float               # + = camera points NORTH of the target
    target_alt: float
    target_az: float
    actual_alt: float
    actual_az: float
    d_az_deg: float                # motor correction needed (target - actual)
    d_alt_deg: float
    rotation_deg: float
    parallactic_deg: float

    def describe(self) -> str:
        ew = "east" if self.east_deg > 0 else "west"
        ns = "north" if self.north_deg > 0 else "south"
        return (f"off by {self.separation_deg:.3f}°: {abs(self.east_deg):.3f}° too far {ew}, "
                f"{abs(self.north_deg):.3f}° too far {ns}  |  "
                f"needs azimuth {self.d_az_deg:+.3f}°, altitude {self.d_alt_deg:+.3f}°")


def pointing_error(target: Target, sol: PlateSolution, site: Site, when: datetime) -> PointingError:
    t_alt, t_az = astro.j2000_to_altaz(target.ra_deg, target.dec_deg, site, when)
    a_alt, a_az = astro.j2000_to_altaz(sol.ra_deg, sol.dec_deg, site, when)
    east, north = astro.tangent_offsets(target.ra_deg, target.dec_deg, sol.ra_deg, sol.dec_deg)
    return PointingError(
        when=when.isoformat(),
        separation_deg=astro.angular_separation(target.ra_deg, target.dec_deg, sol.ra_deg, sol.dec_deg),
        east_deg=east, north_deg=north,
        target_alt=t_alt, target_az=t_az, actual_alt=a_alt, actual_az=a_az,
        d_az_deg=wrap180(t_az - a_az), d_alt_deg=t_alt - a_alt,
        rotation_deg=sol.rotation_deg,
        parallactic_deg=astro.parallactic_angle(sol.ra_deg, sol.dec_deg, site, when),
    )


@dataclass
class Iteration:
    n: int
    image: str
    solution: dict | None
    error: dict | None
    correction: dict | None = None
    note: str = ""


@dataclass
class CenterResult:
    target: dict
    success: bool
    reason: str
    iterations: list[Iteration] = field(default_factory=list)

    @property
    def final_error(self) -> float | None:
        for it in reversed(self.iterations):
            if it.error:
                return it.error["separation_deg"]
        return None


class Logbook:
    """Session JSON-lines log + a CSV of every solve (raw data for a future pointing model)."""

    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir)
        (self.dir / "sessions").mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session = self.dir / "sessions" / f"session_{stamp}.jsonl"
        self.csv = self.dir / "pointing_log.csv"

    def event(self, kind: str, **data):
        with open(self.session, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": datetime.now().isoformat(), "event": kind, **data}, default=str) + "\n")

    def pointing(self, target: Target, sol: PlateSolution, err: PointingError):
        new = not self.csv.exists()
        with open(self.csv, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["utc", "target", "target_ra", "target_dec", "solved_ra", "solved_dec",
                            "target_alt", "target_az", "actual_alt", "actual_az", "d_alt", "d_az",
                            "separation", "rotation", "scale_arcsec", "image"])
            w.writerow([err.when, target.id, f"{target.ra_deg:.5f}", f"{target.dec_deg:.5f}",
                        f"{sol.ra_deg:.5f}", f"{sol.dec_deg:.5f}", f"{err.target_alt:.4f}",
                        f"{err.target_az:.4f}", f"{err.actual_alt:.4f}", f"{err.actual_az:.4f}",
                        f"{err.d_alt_deg:.4f}", f"{err.d_az_deg:.4f}", f"{err.separation_deg:.4f}",
                        f"{sol.rotation_deg:.2f}", f"{sol.scale_arcsec:.3f}", sol.image])


def expected_fov_width(cfg: dict) -> float:
    import math
    o = cfg["optics"]
    return 2 * math.degrees(math.atan(o["sensor_width_mm"] / (2 * o["focal_length_mm"])))


def solve_with_fallback(solver: Solver, image, hint: SolveHint, blind_retry: bool) -> PlateSolution:
    try:
        return solver.solve(image, hint)
    except SolveError:
        if not blind_retry or hint.ra_deg is None:
            raise
        blind = SolveHint(fov_width_deg=hint.fov_width_deg, fov_tolerance=hint.fov_tolerance)
        return solver.solve(image, blind)


def center_target(target: Target, *, cfg: dict, site: Site, source, solver: Solver,
                  mount: Mount, log: Logbook | None = None, verbose: bool = True,
                  sleep=time.sleep) -> CenterResult:
    """The centring loop: picture -> solve -> compare -> Tune -> repeat."""
    c = cfg["centering"]
    tol = float(c["tolerance_deg"])
    result = CenterResult(target=asdict(target), success=False, reason="")
    hint = SolveHint(target.ra_deg, target.dec_deg, float(cfg["solver"]["search_radius_deg"]),
                     expected_fov_width(cfg))
    say = print if verbose else (lambda *a, **k: None)
    prev_sep, strikes = None, 0

    for n in range(1, int(c["max_iterations"]) + 1):
        say(f"\n[{n}] Capturing...")
        image, when = source.capture()
        say(f"    image: {image}")
        try:
            sol = solve_with_fallback(solver, image, hint, bool(cfg["solver"].get("blind_retry", True)))
        except SolveError as e:
            it = Iteration(n, str(image), None, None, note=f"solve failed: {e}")
            result.iterations.append(it)
            if log:
                log.event("solve_failed", n=n, image=str(image), error=str(e))
            result.reason = f"plate solve failed: {e}"
            return result
        err = pointing_error(target, sol, site, when)
        say(sol.summary())
        say(f"    {err.describe()}")
        it = Iteration(n, str(image), sol.to_dict(), asdict(err))
        result.iterations.append(it)
        if log:
            log.pointing(target, sol, err)
            log.event("solved", n=n, solution=sol.to_dict(), error=asdict(err))

        # Use the latest solution as the next hint: faster solves.
        hint = SolveHint(sol.ra_deg, sol.dec_deg, max(5.0, err.separation_deg * 2 + 2),
                         sol.fov_width_deg, 0.1)

        if err.separation_deg <= tol:
            result.success = True
            result.reason = f"centred to {err.separation_deg:.3f}° (tolerance {tol}°) in {n} picture(s)"
            say(f"\n  ✔ {result.reason}")
            return result

        if prev_sep is not None and err.separation_deg > prev_sep * 1.2:
            strikes += 1
            if strikes >= 2:
                result.reason = ("error is growing after corrections: the azimuth or altitude "
                                 "sign (mount.az_sign / mount.alt_sign) is probably reversed, "
                                 "or steps_per_degree is wrong")
                say(f"\n  ✘ {result.reason}")
                return result
        else:
            strikes = 0
        prev_sep = err.separation_deg

        if err.target_alt > float(c["zenith_warn_alt_deg"]):
            say("    note: target is near the zenith, azimuth corrections become large there")

        lim = float(c["max_correction_deg"])
        gain = float(c["gain"])
        d_az = max(-lim, min(lim, err.d_az_deg * gain))
        d_alt = max(-lim, min(lim, err.d_alt_deg * gain))
        if abs(d_az) < float(c["min_correction_deg"]):
            d_az = 0.0
        if abs(d_alt) < float(c["min_correction_deg"]):
            d_alt = 0.0
        corr = mount.to_steps(d_az, d_alt)
        it.correction = asdict(corr)
        if log:
            log.event("correction", n=n, **asdict(corr))
        if not mount.apply(corr):
            result.reason = "stopped by user"
            return result
        sleep(float(c["settle_s"]))

    result.reason = f"not centred after {c['max_iterations']} pictures"
    say(f"\n  ✘ {result.reason}")
    return result
