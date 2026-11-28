"""Measure gear slack (backlash) with the camera.

When a motor reverses, it turns a little before the camera starts to move:
the slack between the gear teeth. On the reference build this is about 0.5 to
0.8 degrees in azimuth, enough to spoil a correction that changes direction.

The measurement moves one axis +m, -m, +m (Tune steps, nothing else) and
plate-solves a picture after each move. The camera's alt/az is worked out for
the moment each picture was taken, so the sky drifting by does not matter
(Pi-lomar does not track while it sits at its main menu). After a reversal the
camera moves by m minus the slack, so slack = m - measured move. Two reversals
are averaged. Finally the axis is put back where it started.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import astro
from .astro import Site, wrap180
from .centering import expected_fov_width, solve_with_fallback
from .model import PointingState
from .mount import Correction, Mount
from .solvers import SolveError, SolveHint, Solver


class BacklashError(RuntimeError):
    pass


def _shoot(source, solver, site: Site, hint: SolveHint) -> tuple[float, float, object]:
    image, when = source.capture()
    try:
        sol = solve_with_fallback(solver, image, hint, True)
    except SolveError as e:
        raise BacklashError(f"picture {image} did not solve: {e}") from e
    alt, az = astro.j2000_to_altaz(sol.ra_deg, sol.dec_deg, site, when)
    return alt, az, sol


def measure_backlash(*, cfg: dict, site: Site, source, solver: Solver, mount: Mount,
                     state: PointingState, axes=("az", "alt"), move_deg: float = 2.0,
                     settle=lambda: None, say=print) -> dict:
    """Return {"az_deg": .., "alt_deg": .., "detail": {...}} for the axes measured."""
    fov = expected_fov_width(cfg)
    logical = mount.position() if hasattr(mount, "position") else None
    if logical is not None:
        ra, dec = astro.altaz_to_j2000(logical[1], logical[0], site, astro.utcnow())
        hint = SolveHint(ra, dec, float(cfg["solver"]["search_radius_deg"]), fov)
    else:
        hint = SolveHint(fov_width_deg=fov)

    def move(axis: str, deg: float):
        corr = mount.to_steps(deg, 0.0) if axis == "az" else mount.to_steps(0.0, deg)
        if not mount.apply(corr):
            raise BacklashError("stopped by user")
        settle()

    def where(axis: str) -> tuple[float, float, float]:
        nonlocal hint
        alt, az, sol = _shoot(source, solver, site, hint)
        hint = SolveHint(sol.ra_deg, sol.dec_deg, 5.0, sol.fov_width_deg, 0.1)
        return (az if axis == "az" else alt), alt, az

    result: dict = {"detail": {}}
    for axis in axes:
        name = "azimuth" if axis == "az" else "altitude"
        say(f"\nMeasuring {name} slack with {move_deg:g}° moves (+, -, +):")
        p0, alt0, _ = where(axis)
        if axis == "az" and alt0 > 70:
            say(f"  note: camera is at altitude {alt0:.0f}°; azimuth is less precise near the "
                "zenith. 30-60° is best.")
        positions = [p0]
        for i, sign in enumerate((+1, -1, +1), 1):
            move(axis, sign * move_deg)
            p, _, _ = where(axis)
            d = wrap180(p - positions[-1]) if axis == "az" else p - positions[-1]
            positions.append(p)
            say(f"  move {i}: asked {sign * move_deg:+.3f}°, camera moved {d:+.3f}°")
        m2 = abs(wrap180(positions[2] - positions[1]) if axis == "az" else positions[2] - positions[1])
        m3 = abs(wrap180(positions[3] - positions[2]) if axis == "az" else positions[3] - positions[2])
        slack = max(0.0, move_deg - (m2 + m3) / 2)
        spread = abs(m2 - m3)
        say(f"  {name} slack: {slack:.3f}° (two reversals differ by {spread:.3f}°)")
        if spread > 0.2:
            say("  warning: the two reversals disagree; wind, a loose belt or a bad solve? "
                "Consider measuring again.")
        result[f"{axis}_deg"] = round(slack, 4)
        result["detail"][axis] = {"positions": positions, "moves": [m2, m3],
                                  "camera_alt": alt0}

        # Put the axis back where it started. The last move was positive, so
        # this reversal needs the slack added; then check with one more picture.
        back = wrap180(p0 - positions[3]) if axis == "az" else p0 - positions[3]
        extra = slack if back < 0 else 0.0
        corr = mount.to_steps(back - extra, 0.0) if axis == "az" else mount.to_steps(0.0, back - extra)
        if not mount.apply(corr):
            raise BacklashError("stopped by user")
        settle()
        p_end, _, _ = where(axis)
        residual = wrap180(p_end - p0) if axis == "az" else p_end - p0
        say(f"  returned to within {residual:+.3f}° of the start")
        # The ledger tracks where the camera really is relative to Pi-lomar's
        # own position: only the leftover offset counts.
        if axis == "az":
            state.add(residual, 0.0)
            state.set_dirs(-1 if back < 0 else 1, None)
        else:
            state.add(0.0, residual)
            state.set_dirs(None, -1 if back < 0 else 1)
    return result


def save_backlash(data_dir: str | Path, result: dict, move_deg: float) -> Path:
    """Write data/backlash.json, keeping an earlier value for an axis not measured now."""
    p = Path(data_dir) / "backlash.json"
    old = {}
    if p.exists():
        try:
            old = json.loads(p.read_text())
        except ValueError:
            old = {}
    out = {
        "az_deg": result.get("az_deg", old.get("az_deg", 0.0)),
        "alt_deg": result.get("alt_deg", old.get("alt_deg", 0.0)),
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "move_deg": move_deg,
        "detail": result.get("detail", {}),
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2))
    return p
