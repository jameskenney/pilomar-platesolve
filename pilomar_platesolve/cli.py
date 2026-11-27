"""pilomar-ps: plate solving and automatic centring for Pi-lomar.

    pilomar-ps check                     is everything installed?
    pilomar-ps solve IMAGE [--target M31] where was this picture pointing?
    pilomar-ps target M31                where is it now, is it up?
    pilomar-ps suggest                   good deep-sky targets right now
    pilomar-ps center M31                capture -> solve -> correct until centred
    pilomar-ps watch [--target M31]      solve every new Pi-lomar picture
    pilomar-ps simulate M31 --az 1.5 --alt -0.8   test the loop without hardware
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, astro
from .camera import CaptureError, FileSource, PilomarFolderSource, RpicamSource
from .catalog import Catalog
from .centering import (Logbook, center_target, expected_fov_width, pointing_error,
                        solve_with_fallback)
from .config import DEFAULTS, config_path, load_config
from .mount import AdvisorMount, SimulatedMount, TmuxMount
from .pilomar_bridge import newest_image, pilomar_running, site_from_config
from .solvers import SolveError, SolveHint, make_solver


def _site(cfg):
    try:
        return site_from_config(cfg)
    except RuntimeError as e:
        sys.exit(f"error: {e}")


def _target(cfg, name):
    try:
        return Catalog(cfg["pilomar_root"]).resolve(name)
    except KeyError as e:
        sys.exit(f"error: {e.args[0]}")


def _workdir(cfg) -> Path:
    p = Path(cfg["data_dir"]) / "work"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- commands

def cmd_check(cfg, args):
    ok = True

    def line(good, label, detail=""):
        nonlocal ok
        ok &= bool(good) or label.startswith("(optional)")
        print(f"  [{'ok' if good else '--'}] {label}" + (f": {detail}" if detail else ""))

    print(f"pilomar-platesolve {__version__}")
    print(f"  config file : {cfg['_config_file'] or '(none, using defaults) ' + str(config_path())}")
    print(f"  data folder : {cfg['data_dir']}")
    root = Path(cfg["pilomar_root"])
    line(root.exists(), "Pi-lomar folder", str(root))
    line((root / "data" / "pilomar_params.json").exists(), "Pi-lomar parameter file (read-only)")
    try:
        s = site_from_config(cfg)
        line(True, "observing site", f"lat {s.lat_deg:+.3f}, lon {s.lon_east_deg:+.3f}")
    except RuntimeError as e:
        line(False, "observing site", str(e))
    cat = Catalog(cfg["pilomar_root"])
    line(len(cat.sources) > 1, "target catalogue", ", ".join(cat.sources))
    sf = cfg["solver"]["astrometry"].get("solve_field", "solve-field")
    line(shutil.which(sf), "astrometry.net solve-field", shutil.which(sf) or "sudo apt install astrometry.net")
    idx = list(Path("/usr/share/astrometry").glob("index-*")) if Path("/usr/share/astrometry").exists() else []
    line(idx, "astrometry.net index files", f"{len(idx)} in /usr/share/astrometry"
         if idx else "sudo apt install astrometry-data-2mass-08-19")
    ast = cfg["solver"]["astap"].get("astap", "astap_cli")
    line(shutil.which(ast), "(optional) ASTAP astap_cli", shutil.which(ast) or "not installed")
    rc = cfg["capture"]["rpicam"].get("exe", "rpicam-still")
    line(shutil.which(rc), "(optional) rpicam-still", shutil.which(rc) or "not found")
    line(shutil.which("tmux"), "(optional) tmux for automatic Tune", shutil.which("tmux") or "sudo apt install tmux")
    print(f"  Pi-lomar running now: {'yes' if pilomar_running() else 'no'}")
    print(f"  backend: solver={cfg['solver']['backend']}  capture={cfg['capture']['source']}"
          f"  mount={cfg['mount']['backend']}")
    print(f"  expected field width: {expected_fov_width(cfg):.1f}° "
          f"({cfg['optics']['focal_length_mm']} mm lens)")
    return 0 if ok else 1


def cmd_solve(cfg, args):
    solver = make_solver(cfg, _workdir(cfg))
    target = _target(cfg, args.target) if args.target else None
    hint = SolveHint(fov_width_deg=expected_fov_width(cfg))
    if args.hint:
        h = Catalog().resolve(args.hint) if not target else target
        hint.ra_deg, hint.dec_deg = h.ra_deg, h.dec_deg
        hint.radius_deg = float(cfg["solver"]["search_radius_deg"])
    elif target:
        hint.ra_deg, hint.dec_deg = target.ra_deg, target.dec_deg
        hint.radius_deg = float(cfg["solver"]["search_radius_deg"])
    try:
        sol = solve_with_fallback(solver, args.image, hint, bool(cfg["solver"].get("blind_retry", True)))
    except SolveError as e:
        print(f"No solution: {e}")
        return 2
    out = {"solution": sol.to_dict()}
    print(f"\n{Path(args.image).name}")
    print(sol.summary())
    if target:
        when = _parse_time(args.time) or FileSource(args.image).capture()[1]
        err = pointing_error(target, sol, _site(cfg), when)
        out["target"] = asdict(target)
        out["error"] = asdict(err)
        print(f"\n  Target {target.id} {target.name}: {err.describe()}")
    dest = Path(cfg["data_dir"]) / "solutions" / (Path(args.image).stem + ".solution.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2, default=str))
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    print(f"\n  saved {dest}")
    return 0


def cmd_target(cfg, args):
    t = _target(cfg, args.name)
    site = _site(cfg)
    now = _parse_time(args.time) or astro.utcnow()
    alt, az = astro.j2000_to_altaz(t.ra_deg, t.dec_deg, site, now)
    print(f"{t.id}  {t.name}  ({t.kind}, mag {t.magnitude if t.magnitude is not None else '?'})")
    print(f"  J2000   RA {astro.format_ra(t.ra_deg)}  Dec {astro.format_dec(t.dec_deg)}")
    print(f"  now     altitude {alt:+.2f}°  azimuth {az:.2f}°   ({now:%Y-%m-%d %H:%M} UTC)")
    print("  " + ("above the horizon" if alt > 0 else "BELOW the horizon"))
    return 0


def cmd_suggest(cfg, args):
    site = _site(cfg)
    now = _parse_time(args.time) or astro.utcnow()
    s = cfg["suggest"]
    min_alt = args.min_alt if args.min_alt is not None else float(s["min_alt_deg"])
    max_mag = args.max_mag if args.max_mag is not None else float(s["max_mag"])
    sun_alt, _ = astro.body_altaz("sun", site, now)
    jd = astro.julian_date(now)
    mra, mdec = astro.date_to_j2000(*astro.moon_radec_of_date(jd), jd)
    moon_alt, _ = astro.body_altaz("moon", site, now)
    rows = []
    for t in Catalog(cfg["pilomar_root"]).all():
        if t.magnitude is None or t.magnitude > max_mag:
            continue
        alt, az = astro.j2000_to_altaz(t.ra_deg, t.dec_deg, site, now)
        if alt < min_alt:
            continue
        msep = astro.angular_separation(t.ra_deg, t.dec_deg, mra, mdec)
        if moon_alt > 0 and msep < float(s["moon_min_sep_deg"]):
            continue
        rows.append((t.magnitude, alt, az, msep, t))
    rows.sort(key=lambda r: (r[0], -r[1]))
    print(f"{now:%Y-%m-%d %H:%M} UTC   sun altitude {sun_alt:+.1f}°   moon altitude {moon_alt:+.1f}°")
    if sun_alt > -12:
        print("  note: the sky is not fully dark yet (sun above -12°)")
    print(f"\n  {'target':10} {'mag':>4} {'alt':>6} {'az':>6} {'moon':>5}  name")
    for mag, alt, az, msep, t in rows[: args.limit or int(s["limit"])]:
        print(f"  {t.id:10} {mag:4.1f} {alt:6.1f} {az:6.1f} {msep:5.0f}  {t.name} ({t.kind})")
    if not rows:
        print("  nothing suitable above the horizon right now")
    return 0


def _make_mount(cfg, args):
    backend = args.mount or cfg["mount"]["backend"]
    if backend == "advisor":
        return AdvisorMount(cfg["mount"])
    if backend == "tmux":
        return TmuxMount(cfg["mount"], dry_run=args.dry_run)
    sys.exit(f"error: mount backend {backend!r} not usable here (advisor, tmux)")


def _make_source(cfg, args, mount):
    src = args.source or cfg["capture"]["source"]
    if args.image:
        return FileSource(args.image)
    if src == "rpicam":
        return RpicamSource(cfg["capture"]["rpicam"], Path(cfg["data_dir"]) / "captures")
    if src == "pilomar-folder":
        trigger = mount.trigger_capture if isinstance(mount, TmuxMount) and \
            cfg["mount"]["tmux"].get("capture_keys") else None
        return PilomarFolderSource(cfg["capture"]["folder"], cfg["pilomar_root"], trigger)
    sys.exit(f"error: unknown capture source {src!r}")


def cmd_center(cfg, args):
    target = _target(cfg, args.name)
    site = _site(cfg)
    now = astro.utcnow()
    alt, az = astro.j2000_to_altaz(target.ra_deg, target.dec_deg, site, now)
    print(f"Centring {target.id} {target.name}: now at altitude {alt:.1f}°, azimuth {az:.1f}°")
    if alt < 5:
        sys.exit("error: target is below (or too close to) the horizon")
    if args.tolerance:
        cfg["centering"]["tolerance_deg"] = args.tolerance
    if args.max_iter:
        cfg["centering"]["max_iterations"] = args.max_iter
    print("First make sure Pi-lomar has done GOTO on this target and is tracking it.")
    mount = _make_mount(cfg, args)
    source = _make_source(cfg, args, mount)
    log = Logbook(cfg["data_dir"])
    log.event("start", target=asdict(target), site=asdict(site), mount=mount.name)
    try:
        res = center_target(target, cfg=cfg, site=site, source=source,
                            solver=make_solver(cfg, _workdir(cfg)), mount=mount, log=log)
    except (CaptureError, RuntimeError) as e:
        print(f"error: {e}")
        return 3
    except KeyboardInterrupt:
        print("\nstopped")
        return 130
    log.event("end", success=res.success, reason=res.reason)
    print(f"\n  log: {log.session}")
    return 0 if res.success else 1


def cmd_watch(cfg, args):
    solver = make_solver(cfg, _workdir(cfg))
    target = _target(cfg, args.target) if args.target else None
    site = _site(cfg) if target else None
    pattern = cfg["capture"]["folder"]["glob"]
    since = time.time()
    hint = SolveHint(target.ra_deg if target else None, target.dec_deg if target else None,
                     float(cfg["solver"]["search_radius_deg"]), expected_fov_width(cfg))
    first = None
    log = Logbook(cfg["data_dir"])
    print(f"Watching {cfg['pilomar_root']}/{pattern} for new pictures. Ctrl+C to stop.")
    try:
        while True:
            p = newest_image(cfg["pilomar_root"], pattern, since)
            if p is None:
                time.sleep(2)
                continue
            since = p.stat().st_mtime
            time.sleep(cfg["capture"]["folder"].get("settle_s", 1.0))
            try:
                sol = solve_with_fallback(solver, p, hint, True)
            except SolveError as e:
                print(f"{p.name}: no solution ({e})")
                continue
            hint = SolveHint(sol.ra_deg, sol.dec_deg, 5.0, sol.fov_width_deg, 0.1)
            first = first or sol
            drift = astro.angular_separation(first.ra_deg, first.dec_deg, sol.ra_deg, sol.dec_deg)
            msg = (f"{p.name}: RA {astro.format_ra(sol.ra_deg)} Dec {astro.format_dec(sol.dec_deg)} "
                   f"rot {sol.rotation_deg:.1f}°  drift since first {drift * 60:.1f}'")
            if target:
                err = pointing_error(target, sol, site,
                                     datetime.fromtimestamp(p.stat().st_mtime, timezone.utc))
                msg += f"  | {err.describe()}"
                log.pointing(target, sol, err)
            print(msg)
            log.event("watch_solved", image=str(p), solution=sol.to_dict())
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


def cmd_simulate(cfg, args):
    from .sim import SimSolver, SimSource, SimWorld
    target = _target(cfg, args.name)
    try:
        site = site_from_config(cfg)
    except RuntimeError:
        site = astro.Site(35.47, -97.52)  # Oklahoma City, the reference build
    start = _parse_time(args.time) or astro.utcnow()
    alt, _ = astro.j2000_to_altaz(target.ra_deg, target.dec_deg, site, start)
    if alt < 5:
        print(f"note: {target.id} is below the horizon at that time (alt {alt:.1f}°); simulating anyway")
    true_az_sign = -cfg["mount"]["az_sign"] if args.wrong_sign else None
    mount = SimulatedMount(cfg["mount"], args.az, args.alt, args.backlash, true_az_sign=true_az_sign)
    world = SimWorld(target, site, start, mount, fail_solves=args.fail)
    print(f"Simulating {target.id} with a pointing error of az {args.az:+.2f}°, alt {args.alt:+.2f}°")
    res = center_target(target, cfg=cfg, site=site, source=SimSource(world),
                        solver=SimSolver(world), mount=mount, log=None, sleep=lambda s: None)
    print(f"\nresult: {'SUCCESS' if res.success else 'FAILED'} - {res.reason}")
    return 0 if res.success else 1


def cmd_config(cfg, args):
    if args.write_example:
        dest = config_path()
        if dest.exists() and not args.force:
            sys.exit(f"{dest} already exists (use --force to overwrite)")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(DEFAULTS, indent=2))
        print(f"wrote {dest}")
        return 0
    shown = {k: v for k, v in cfg.items() if not k.startswith("_")}
    print(json.dumps(shown, indent=2))
    return 0


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pilomar-ps", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="config file (default ~/pilomar-platesolve/config.json)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="check installation")

    s = sub.add_parser("solve", help="plate-solve one image")
    s.add_argument("image")
    s.add_argument("--target", help="compare with this target (e.g. M31)")
    s.add_argument("--hint", help="approximate position to speed up solving (name or 'ra dec')")
    s.add_argument("--time", help="UTC time of the picture (ISO), default file time")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("target", help="show a target's position now")
    s.add_argument("name")
    s.add_argument("--time")

    s = sub.add_parser("suggest", help="list good deep-sky targets now")
    s.add_argument("--min-alt", type=float)
    s.add_argument("--max-mag", type=float)
    s.add_argument("--limit", type=int)
    s.add_argument("--time")

    s = sub.add_parser("center", help="centre a target: capture, solve, correct, repeat")
    s.add_argument("name")
    s.add_argument("--mount", choices=["advisor", "tmux"])
    s.add_argument("--source", choices=["rpicam", "pilomar-folder"])
    s.add_argument("--image", help="use this image (single test pass)")
    s.add_argument("--dry-run", action="store_true", help="tmux: print keystrokes, don't send")
    s.add_argument("--tolerance", type=float, help="degrees")
    s.add_argument("--max-iter", type=int)

    s = sub.add_parser("watch", help="solve each new Pi-lomar image as it is saved")
    s.add_argument("--target")

    s = sub.add_parser("simulate", help="run the centring loop against a virtual mount")
    s.add_argument("name")
    s.add_argument("--az", type=float, default=1.5, help="starting azimuth error, degrees")
    s.add_argument("--alt", type=float, default=-0.8, help="starting altitude error, degrees")
    s.add_argument("--backlash", type=float, default=0.1, help="fraction of each move lost")
    s.add_argument("--wrong-sign", action="store_true", help="simulate a reversed azimuth sign")
    s.add_argument("--fail", type=int, default=0, help="number of solves that fail first")
    s.add_argument("--time")

    s = sub.add_parser("config", help="show the active configuration")
    s.add_argument("--write-example", action="store_true", help="write a full config.json")
    s.add_argument("--force", action="store_true")
    return p


COMMANDS = {"check": cmd_check, "solve": cmd_solve, "target": cmd_target, "suggest": cmd_suggest,
            "center": cmd_center, "watch": cmd_watch, "simulate": cmd_simulate, "config": cmd_config}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    return COMMANDS[args.cmd](cfg, args) or 0


if __name__ == "__main__":
    sys.exit(main())
