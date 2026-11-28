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
from .model import PointingModel, PointingState, predicted_correction
from .mount import Correction, Mount
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
    reference: str = "target"      # "pilomar": compared with Pi-lomar's own position
    sky_target_alt: float = 0.0
    sky_target_az: float = 0.0

    def describe(self) -> str:
        if self.reference == "pilomar":
            return (f"mount error {self.separation_deg:.3f}° (camera vs where Pi-lomar thinks it points)"
                    f"  |  needs azimuth {self.d_az_deg:+.3f}°, altitude {self.d_alt_deg:+.3f}°")
        ew = "east" if self.east_deg > 0 else "west"
        ns = "north" if self.north_deg > 0 else "south"
        return (f"off by {self.separation_deg:.3f}°: {abs(self.east_deg):.3f}° too far {ew}, "
                f"{abs(self.north_deg):.3f}° too far {ns}  |  "
                f"needs azimuth {self.d_az_deg:+.3f}°, altitude {self.d_alt_deg:+.3f}°")


def pointing_error(target: Target, sol: PlateSolution, site: Site, when: datetime,
                   logical: tuple[float, float] | None = None) -> PointingError:
    """Error between where the camera should point and where it really points.

    ``logical`` is Pi-lomar's own position (az, alt) if known. Pi-lomar does
    not track while it sits at its menu, so the sky drifts away from the
    target after a GOTO; comparing with Pi-lomar's position measures only the
    mount's error, which is what a Tune should remove. Without it, the
    target's current position is used (correct while Pi-lomar is tracking).
    """
    t_alt, t_az = astro.j2000_to_altaz(target.ra_deg, target.dec_deg, site, when)
    a_alt, a_az = astro.j2000_to_altaz(sol.ra_deg, sol.dec_deg, site, when)
    east, north = astro.tangent_offsets(target.ra_deg, target.dec_deg, sol.ra_deg, sol.dec_deg)
    ref_az, ref_alt = (logical if logical is not None else (t_az, t_alt))
    if logical is not None:
        ref_ra, ref_dec = astro.altaz_to_j2000(ref_alt, ref_az, site, when)
        sep = astro.angular_separation(ref_ra, ref_dec, sol.ra_deg, sol.dec_deg)
    else:
        sep = astro.angular_separation(target.ra_deg, target.dec_deg, sol.ra_deg, sol.dec_deg)
    return PointingError(
        when=when.isoformat(),
        separation_deg=sep,
        east_deg=east, north_deg=north,
        target_alt=ref_alt, target_az=ref_az, actual_alt=a_alt, actual_az=a_az,
        d_az_deg=wrap180(ref_az - a_az), d_alt_deg=ref_alt - a_alt,
        rotation_deg=sol.rotation_deg,
        parallactic_deg=astro.parallactic_angle(sol.ra_deg, sol.dec_deg, site, when),
        reference="pilomar" if logical is not None else "target",
        sky_target_alt=t_alt, sky_target_az=t_az,
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

    HEADER = ["utc", "target", "target_ra", "target_dec", "solved_ra", "solved_dec",
              "target_alt", "target_az", "actual_alt", "actual_az", "d_alt", "d_az",
              "separation", "rotation", "scale_arcsec", "image", "mount_alt", "mount_az", "epoch"]

    def pointing(self, target: Target, sol: PlateSolution, err: PointingError,
                 state: PointingState | None = None):
        if self.csv.exists():
            with open(self.csv, encoding="utf-8") as f:
                if f.readline().strip().split(",") != self.HEADER:
                    self.csv.rename(self.csv.with_name("pointing_log_old.csv"))
        new = not self.csv.exists()
        m_az, m_alt = (state.mount_position(err.target_az, err.target_alt) if state
                       else (err.target_az, err.target_alt))
        with open(self.csv, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(self.HEADER)
            w.writerow([err.when, target.id, f"{target.ra_deg:.5f}", f"{target.dec_deg:.5f}",
                        f"{sol.ra_deg:.5f}", f"{sol.dec_deg:.5f}", f"{err.target_alt:.4f}",
                        f"{err.target_az:.4f}", f"{err.actual_alt:.4f}", f"{err.actual_az:.4f}",
                        f"{err.d_alt_deg:.4f}", f"{err.d_az_deg:.4f}", f"{err.separation_deg:.4f}",
                        f"{sol.rotation_deg:.2f}", f"{sol.scale_arcsec:.3f}", sol.image,
                        f"{m_alt:.4f}", f"{m_az:.4f}", state.epoch if state else ""])


def expected_fov_width(cfg: dict) -> float:
    import math
    o = cfg["optics"]
    return 2 * math.degrees(math.atan(o["sensor_width_mm"] / (2 * o["focal_length_mm"])))


def solve_with_fallback(solver: Solver, image, hint: SolveHint, blind_retry: bool) -> PlateSolution:
    """Solve; if that fails, retry with a cleaned picture and the lens preset
    (astrometry.net), then without the position hint."""
    try:
        return solver.solve(image, hint)
    except SolveError as first:
        err = first
    if getattr(solver, "cfg", {}).get("rescue", False) and hasattr(solver, "solve_rescue"):
        try:
            return solver.solve_rescue(image, hint)
        except SolveError as e:
            err = e
    if not blind_retry or hint.ra_deg is None:
        raise err
    blind = SolveHint(fov_width_deg=hint.fov_width_deg, fov_tolerance=hint.fov_tolerance)
    return solver.solve(image, blind)


def center_target(target: Target, *, cfg: dict, site: Site, source, solver: Solver,
                  mount: Mount, log: Logbook | None = None, verbose: bool = True,
                  sleep=time.sleep, model: PointingModel | None = None,
                  state: PointingState | None = None, when=None) -> CenterResult:
    """The centring loop: [model correction] -> picture -> solve -> compare -> Tune -> repeat."""
    c = cfg["centering"]
    state = state or PointingState(None)
    tol = float(c["tolerance_deg"])
    result = CenterResult(target=asdict(target), success=False, reason="")
    hint = SolveHint(target.ra_deg, target.dec_deg, float(cfg["solver"]["search_radius_deg"]),
                     expected_fov_width(cfg))
    say = print if verbose else (lambda *a, **k: None)
    prev_sep, strikes = None, 0

    if model is not None and model.params:
        if not apply_model_correction(target, model, state, site, mount, cfg,
                                      when or astro.utcnow(), say, log):
            result.reason = "stopped by user"
            return result
        sleep(float(c["settle_s"]))

    ref_kind = None
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
        logical = mount.position() if hasattr(mount, "position") else None
        if logical is None and ref_kind == "pilomar":
            logical = mount.position()          # one retry
            if logical is None:
                result.reason = ("could not read Pi-lomar's position (Status); stopped rather "
                                 "than mix two reference frames. Check: tmux attach -t pilomar")
                say(sol.summary())
                say(f"\n  ✘ {result.reason}")
                return result
        ref_kind = ref_kind or ("pilomar" if logical is not None else "target")
        err = pointing_error(target, sol, site, when, logical)
        say(sol.summary())
        say(f"    {err.describe()}")
        it = Iteration(n, str(image), sol.to_dict(), asdict(err))
        result.iterations.append(it)
        if log:
            log.pointing(target, sol, err, state)
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

        gain = float(c["gain"])
        d_az, d_alt = clamp_on_sky(err.d_az_deg * gain, err.d_alt_deg * gain,
                                   err.target_alt, float(c["max_correction_deg"]),
                                   float(c.get("max_azimuth_turn_deg", 30.0)))
        if abs(d_az) < float(c["min_correction_deg"]):
            d_az = 0.0
        if abs(d_alt) < float(c["min_correction_deg"]):
            d_alt = 0.0
        corr = mount.to_steps(d_az, d_alt)
        it.correction = asdict(corr)
        if log:
            log.event("correction", n=n, **asdict(corr))
        if not tune(mount, corr, state, cfg, say):
            result.reason = "stopped by user"
            return result
        sleep(float(c["settle_s"]))

    result.reason = f"not centred after {c['max_iterations']} pictures"
    say(f"\n  ✘ {result.reason}")
    return result


def clamp_on_sky(d_az: float, d_alt: float, alt: float, limit: float,
                 max_az_turn: float = 30.0) -> tuple[float, float]:
    """Limit a correction by how far it moves the view on the sky, not by raw azimuth.

    Near the zenith a small sky offset needs a large azimuth turn
    (azimuth degrees shrink by cos(altitude)), so a raw-azimuth limit would
    wrongly cut legitimate corrections short there.
    """
    import math
    sky = math.hypot(d_az * math.cos(math.radians(alt)), d_alt)
    if sky > limit:
        f = limit / sky
        d_az, d_alt = d_az * f, d_alt * f
    # Right at the zenith azimuth is barely defined, so also cap the turn itself;
    # the loop simply takes another picture and continues.
    return max(-max_az_turn, min(max_az_turn, d_az)), d_alt


def apply_model_correction(target: Target, model: PointingModel, state: PointingState,
                           site: Site, mount: Mount, cfg: dict, when: datetime,
                           say=print, log: Logbook | None = None) -> bool:
    """Predict the pointing error from the model and Tune it away, no picture needed."""
    t_alt, t_az = astro.j2000_to_altaz(target.ra_deg, target.dec_deg, site, when)
    logical = mount.position() if hasattr(mount, "position") else None
    if logical is not None:
        t_az, t_alt = logical
    d_az, d_alt = predicted_correction(model, state, t_az, t_alt)
    d_az, d_alt = clamp_on_sky(d_az, d_alt, t_alt, float(cfg["centering"]["max_correction_deg"]),
                               float(cfg["centering"].get("max_azimuth_turn_deg", 30.0)))
    small = float(cfg["centering"]["min_correction_deg"])
    if abs(d_az) < small and abs(d_alt) < small:
        say(f"  Pointing model: no correction needed for {target.id}")
        return True
    say(f"  Pointing model predicts: azimuth {d_az:+.3f}°, altitude {d_alt:+.3f}°")
    corr = mount.to_steps(d_az, d_alt)
    if log:
        log.event("model_correction", target=target.id, **asdict(corr))
    return tune(mount, corr, state, cfg, say)


def backlash_settings(cfg: dict) -> tuple[float, float]:
    """Gear slack in degrees (azimuth, altitude): measured file first, then config."""
    p = Path(cfg.get("data_dir", "data")) / "backlash.json"
    if p.exists():
        try:
            d = json.loads(p.read_text())
            return float(d.get("az_deg", 0.0)), float(d.get("alt_deg", 0.0))
        except (ValueError, OSError):
            pass
    m = cfg.get("mount", {})
    return float(m.get("backlash_az_deg", 0.0)), float(m.get("backlash_alt_deg", 0.0))


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def tune(mount: Mount, corr: Correction, state: PointingState | None, cfg: dict,
         say=print, compensate: bool = True) -> bool:
    """Apply a Tune correction, taking up gear slack when a motor reverses.

    The ledger records the camera's intended movement (corr.d_*), not the
    extra slack steps, because the slack moves the motor but not the camera.
    """
    b_az, b_alt = backlash_settings(cfg) if compensate else (0.0, 0.0)
    m = cfg.get("mount", {})
    d_az, d_alt = _sign(corr.az_steps), _sign(corr.alt_steps)
    extra_az = extra_alt = 0
    if state is not None and d_az and state.dir_az and d_az != state.dir_az and b_az > 0:
        extra_az = d_az * int(round(b_az * float(m.get("steps_per_degree_az", 1066.67))))
    if state is not None and d_alt and state.dir_alt and d_alt != state.dir_alt and b_alt > 0:
        extra_alt = d_alt * int(round(b_alt * float(m.get("steps_per_degree_alt", 1066.67))))
    send = corr
    if extra_az or extra_alt:
        parts = []
        if extra_az:
            parts.append(f"azimuth {extra_az:+d}")
        if extra_alt:
            parts.append(f"altitude {extra_alt:+d}")
        say(f"    + gear slack for the change of direction: {', '.join(parts)} steps")
        send = Correction(corr.d_az_deg, corr.d_alt_deg, corr.az_steps + extra_az,
                          corr.alt_steps + extra_alt)
    if not mount.apply(send):
        return False
    if state is not None:
        state.add(corr.d_az_deg, corr.d_alt_deg)
        state.set_dirs(d_az or None, d_alt or None)
    return True


def note_goto(mount: Mount, state: PointingState | None):
    """After a GOTO, remember which way each motor last turned (if known)."""
    if state is None:
        return
    d = getattr(mount, "last_goto_dir", None)
    state.set_dirs(*(d if d else (0, 0)))


class UnsafeTarget(RuntimeError):
    pass


def check_goto_safe(target: Target, site: Site, when: datetime, cfg: dict, min_alt: float = 5.0):
    """Refuse a GOTO that is below the horizon or too close to the Sun."""
    alt, _ = astro.j2000_to_altaz(target.ra_deg, target.dec_deg, site, when)
    if alt < min_alt:
        raise UnsafeTarget(f"{target.id} is at altitude {alt:.1f}°, below the {min_alt:.0f}° limit")
    jd = astro.julian_date(when)
    s_ra, s_dec = astro.date_to_j2000(*astro.sun_radec_of_date(jd), jd)
    sep = astro.angular_separation(target.ra_deg, target.dec_deg, s_ra, s_dec)
    limit = float(cfg.get("sun_avoid_deg", 30.0))
    if sep < limit:
        raise UnsafeTarget(f"{target.id} is only {sep:.0f}° from the Sun (limit {limit:.0f}°)")
    return alt, sep
