"""pilomar-ps: plate solving and automatic centring for Pi-lomar.

    pilomar-ps check                     is everything installed?
    pilomar-ps solve IMAGE [--target M31] where was this picture pointing?
    pilomar-ps target M31                where is it now, is it up?
    pilomar-ps suggest                   good deep-sky targets right now
    pilomar-ps center M31                capture -> solve -> correct until centred
    pilomar-ps watch [--target M31]      solve every new Pi-lomar picture
    pilomar-ps align                     startup alignment: measure the mount's errors
    pilomar-ps goto M31                  GOTO + model correction, no picture needed
    pilomar-ps model show|fit|reset      inspect or rebuild the pointing model
    pilomar-ps simulate M31 --az 1.5 --alt -0.8   test the loop without hardware
    pilomar-ps simulate-align            test alignment against a virtual tilted mount
    pilomar-ps report                    test results summary to copy and share
    pilomar-ps selftest [--center]       indoor test: real solver on synthetic star pictures
    pilomar-ps capture                   take one picture (camera check)
    pilomar-ps tune --az 1               send one Tune move (mount check)
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
from .align import choose_alignment_targets, run_alignment, samples_from_log
from .centering import apply_model_correction
from .model import PointingModel, PointingState, fit_model
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


def _model_paths(cfg) -> tuple[Path, Path]:
    d = Path(cfg["data_dir"])
    return d / "pointing_model.json", d / "pointing_state.json"


def _load_model(cfg, args=None) -> tuple[PointingModel | None, PointingState]:
    mp, sp = _model_paths(cfg)
    state = PointingState(sp)
    if args is not None and getattr(args, "dry_run", False):
        state.path = None  # dry run: never write the ledger
    return PointingModel.load(mp), state


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
    log = Logbook(cfg["data_dir"])
    try:
        sol = solve_with_fallback(solver, args.image, hint, bool(cfg["solver"].get("blind_retry", True)))
    except SolveError as e:
        print(f"No solution: {e}")
        log.event("solve_cmd_failed", error=str(e))
        return 2
    log.event("solve_cmd", solution=sol.to_dict())
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
    log.event("start", command="center", target=target.id, mount=mount.name)
    t_start = time.monotonic()
    model, state = _load_model(cfg, args)
    if args.no_model or args.image:
        model = None
    elif model:
        print(f"Using pointing model fitted {model.fitted_at[:16]} "
              f"({model.rms_after_deg:.2f}° rms).")
    try:
        res = center_target(target, cfg=cfg, site=site, source=source,
                            solver=make_solver(cfg, _workdir(cfg)), mount=mount, log=log,
                            model=model, state=state)
    except (CaptureError, RuntimeError) as e:
        print(f"error: {e}")
        return 3
    except KeyboardInterrupt:
        print("\nstopped")
        return 130
    log.event("end", success=res.success, reason=res.reason, final_error=res.final_error)
    print(f"\n  total time: {time.monotonic() - t_start:.0f} s, {len(res.iterations)} picture(s)")
    print(f"  log: {log.session}")
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


def cmd_align(cfg, args):
    site = _site(cfg)
    now = _parse_time(args.time) or astro.utcnow()
    cat = Catalog(cfg["pilomar_root"])
    if args.targets:
        targets = [_target(cfg, n) for n in args.targets.split(",")]
    else:
        targets = choose_alignment_targets(cat.all(), site, now, args.points)
    if len(targets) < 3:
        sys.exit("error: fewer than 3 usable targets above the horizon; try --targets")
    print("Alignment: Pi-lomar will visit these targets. Make NO manual Tune moves meanwhile.")
    for t in targets:
        alt, az = astro.j2000_to_altaz(t.ra_deg, t.dec_deg, site, now)
        print(f"  {t.id:8} az {az:6.1f}°  alt {alt:5.1f}°  {t.name}")
    mount = _make_mount(cfg, args)
    source = _make_source(cfg, args, mount)
    _, state = _load_model(cfg, args)
    log = Logbook(cfg["data_dir"])
    log.event("align_start", targets=[t.id for t in targets], mount=mount.name)
    t_start = time.monotonic()
    try:
        model, samples = run_alignment(targets, cfg=cfg, site=site, source=source,
                                       solver=make_solver(cfg, _workdir(cfg)), mount=mount,
                                       state=state, log=log)
    except (CaptureError, RuntimeError) as e:
        print(f"error: {e}")
        return 3
    except KeyboardInterrupt:
        print("\nstopped")
        return 130
    print(f"\n  alignment took {(time.monotonic() - t_start) / 60:.1f} min")
    if model is None:
        return 1
    mp, _ = _model_paths(cfg)
    if args.dry_run:
        print("\n(dry run: model not saved)\n" + model.describe())
        return 0
    model.save(mp)
    log.event("model_fitted", model=model.to_dict())
    print("\nPointing model saved to " + str(mp) + "\n" + model.describe())
    if model.rms_after_deg > 0.5:
        print("  note: large leftover error; check for backlash, a loose mount, or a bad solve")
    return 0


def cmd_goto(cfg, args):
    target = _target(cfg, args.name)
    site = _site(cfg)
    model, state = _load_model(cfg, args)
    if model is None:
        sys.exit("error: no pointing model yet; run 'pilomar-ps align' first")
    alt, _ = astro.j2000_to_altaz(target.ra_deg, target.dec_deg, site, astro.utcnow())
    if alt < 5:
        sys.exit(f"error: {target.id} is below the horizon")
    mount = _make_mount(cfg, args)
    if not args.no_slew and not mount.goto(target):
        return 1
    log = Logbook(cfg["data_dir"])
    ok = apply_model_correction(target, model, state, site, mount, cfg, astro.utcnow(), log=log)
    log.event("goto", target=target.id, ok=ok, slewed=not args.no_slew)
    if ok:
        print(f"  {target.id} should now be centred to within about {max(model.rms_after_deg, 0.05) * 2:.1f}°."
              " Use 'pilomar-ps center' to confirm with a picture.")
    return 0 if ok else 1


def cmd_model(cfg, args):
    mp, sp = _model_paths(cfg)
    model, state = _load_model(cfg)
    if args.action == "show":
        if not model:
            print("No pointing model yet. Run 'pilomar-ps align'.")
        else:
            print(f"Pointing model ({mp}), fitted {model.fitted_at}:\n{model.describe()}")
            print(f"  Tune applied since then: azimuth {state.tune_az:+.3f}°, altitude {state.tune_alt:+.3f}°")
        return 0
    if args.action == "fit":
        samples = samples_from_log(Path(cfg["data_dir"]) / "pointing_log.csv", state.epoch)
        if len(samples) < 3:
            sys.exit(f"error: only {len(samples)} usable logged solves since the last alignment")
        new = fit_model(samples)
        new.epoch = state.epoch  # same frame as the logged mount positions
        new.save(mp)
        print(f"Refitted from {len(samples)} logged solves:\n{new.describe()}")
        return 0
    if args.action == "reset":
        mp.unlink(missing_ok=True)
        state.reset()
        print("Pointing model and Tune ledger cleared.")
        return 0
    return 1


def cmd_simulate_align(cfg, args):
    from .sim import simulate_alignment
    try:
        site = site_from_config(cfg)
    except RuntimeError:
        site = astro.Site(35.47, -97.52)
    start = _parse_time(args.time) or astro.utcnow()
    truth = PointingModel(params={"IA": args.ia, "IE": args.ie, "AN": args.an,
                                  "AW": args.aw, "CA": args.ca})
    print("Virtual mount faults:\n" + truth.describe().split("\n  fitted")[0])
    model, results = simulate_alignment(cfg, site, start, truth, Catalog(cfg["pilomar_root"]).all(),
                                        n_points=args.points)
    worst = max(r[2] for r in results) if results else 99
    print(f"\nworst error after model correction: {worst:.3f}°")
    return 0 if worst < 0.25 else 1


def cmd_report(cfg, args):
    from .report import render
    since = _parse_time(args.since) if args.since else None
    text = render(cfg, since)
    print(text)
    dest = Path(cfg["data_dir"]) / "report.txt"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text + "\n")
    print(f"\n(also saved to {dest})")
    return 0


def _best_time(target, site, start=None):
    """The time in the next 24 h when the target is highest (for simulated tests)."""
    from datetime import timedelta
    start = start or astro.utcnow()
    times = [start + timedelta(minutes=30 * i) for i in range(48)]
    return max(times, key=lambda t: astro.j2000_to_altaz(target.ra_deg, target.dec_deg, site, t)[0])


def cmd_selftest(cfg, args):
    import math
    import random
    from datetime import datetime as _dt

    from .synthetic import SyntheticSource, load_hipparcos, render_starfield
    cat_path = Path(args.catalog or Path(cfg["pilomar_root"]) / "data" / "hip_main.dat")
    if not cat_path.exists():
        sys.exit(f"error: star catalogue not found at {cat_path} (Pi-lomar downloads it as hip_main.dat)")
    solver = make_solver(cfg, _workdir(cfg))
    if not solver.available():
        sys.exit("error: plate solver not installed; run ./install.sh")
    t0 = time.monotonic()
    stars = load_hipparcos(cat_path, args.max_mag)
    print(f"Loaded {len(stars)} stars brighter than magnitude {args.max_mag} "
          f"in {time.monotonic() - t0:.1f} s")
    o = cfg["optics"]
    width = args.width
    height = round(width * o["sensor_height_mm"] / o["sensor_width_mm"])
    fov = expected_fov_width(cfg)
    scale = fov * 3600.0 / width
    outdir = Path(cfg["data_dir"]) / "selftest"
    outdir.mkdir(parents=True, exist_ok=True)
    log = Logbook(cfg["data_dir"])
    rng = random.Random(args.seed)
    print(f"Synthetic pictures: {width} x {height} px, {scale:.1f}\"/px, {fov:.1f}° wide "
          f"({o['focal_length_mm']} mm lens)\n")

    ok_all = True
    if not args.center:
        print(f"  {'target':8} {'solve':>7} {'centre err':>11} {'rotation err':>13} {'scale err':>10}  result")
        for name in args.targets.split(","):
            tgt = _target(cfg, name.strip())
            # Pretend Pi-lomar missed by up to ~1.5 degrees, camera at a random angle.
            ra = tgt.ra_deg + rng.uniform(-1.5, 1.5) / max(0.2, math.cos(math.radians(tgt.dec_deg)))
            dec = max(-89.0, min(89.0, tgt.dec_deg + rng.uniform(-1.5, 1.5)))
            rot = rng.uniform(0, 360)
            img = outdir / f"selftest_{tgt.id}.png"
            truth = render_starfield(stars, ra, dec, rot, width, height, scale, img,
                                     seed=rng.randrange(1 << 30), limit_mag=args.max_mag)
            hint = SolveHint(tgt.ra_deg, tgt.dec_deg, float(cfg["solver"]["search_radius_deg"]), fov)
            try:
                sol = solve_with_fallback(solver, img, hint, True)
            except SolveError as e:
                ok_all = False
                print(f"  {tgt.id:8} {'-':>7} {'-':>11} {'-':>13} {'-':>10}  NOT SOLVED "
                      f"({truth['stars']} stars drawn): {e}")
                log.event("solve_cmd_failed", selftest=True, target=tgt.id, error=str(e))
                continue
            c_err = astro.angular_separation(ra, dec, sol.ra_deg, sol.dec_deg) * 3600
            r_err = abs(astro.wrap180(sol.rotation_deg - rot))
            s_err = abs(sol.scale_arcsec - scale) / scale * 100
            good = c_err < 3 * scale and r_err < 0.5 and s_err < 1 and not sol.flipped
            ok_all &= good
            print(f"  {tgt.id:8} {sol.solve_seconds:6.1f}s {c_err:9.1f}\" {r_err:11.2f}° {s_err:9.2f}%  "
                  + ("OK" if good else "CHECK") + ("  [solver says mirrored]" if sol.flipped else ""))
            log.event("solve_cmd", selftest=True, target=tgt.id, solution=sol.to_dict(),
                      truth={"ra": ra, "dec": dec, "rotation": rot},
                      error_arcsec=c_err, rotation_error_deg=r_err)
        print(f"\n  Pictures and solver logs: {outdir}  and  {_workdir(cfg)}")
        print("  " + ("PASS: the plate solver works on this Pi." if ok_all else
                      "Some checks failed; paste this output to get help."))
        return 0 if ok_all else 1

    # --center: whole centring loop with a virtual mount but the REAL solver.
    from .sim import SimWorld
    tgt = _target(cfg, args.targets.split(",")[0].strip())
    site = _site(cfg)
    when = _best_time(tgt, site)
    alt, az = astro.j2000_to_altaz(tgt.ra_deg, tgt.dec_deg, site, when)
    print(f"Centring test on {tgt.id} as it will be at {when:%Y-%m-%d %H:%M} UTC "
          f"(altitude {alt:.0f}°), virtual mount off by az {args.az:+.1f}°, alt {args.alt:+.1f}°")
    mount = SimulatedMount(cfg["mount"], args.az, args.alt, 0.05)
    world = SimWorld(tgt, site, when, mount, seconds_per_picture=60, noise_deg=0.0)
    source = SyntheticSource(world, stars, outdir, width, height, scale, rotation_deg=rng.uniform(0, 360))
    log.event("start", command="center", target=tgt.id, mount="simulated (selftest)")
    t_start = time.monotonic()
    res = center_target(tgt, cfg=cfg, site=site, source=source, solver=solver, mount=mount, log=log,
                        sleep=lambda s: None)
    log.event("end", success=res.success, reason=res.reason, final_error=res.final_error)
    print(f"\n  total time: {time.monotonic() - t_start:.0f} s, {len(res.iterations)} picture(s)")
    print("  " + ("PASS: capture -> solve -> correct loop works with the real solver." if res.success
                  else "FAILED: paste this output to get help."))
    return 0 if res.success else 1


def cmd_capture(cfg, args):
    if pilomar_running():
        print("note: Pi-lomar is running; if it holds the camera this will fail. "
              "Disable Pi-lomar's camera (Camera tools) or close Pi-lomar first.")
    rc = dict(cfg["capture"]["rpicam"])
    if args.exposure:
        rc["exposure_s"] = args.exposure
    if args.gain:
        rc["gain"] = args.gain
    src = RpicamSource(rc, Path(cfg["data_dir"]) / "captures")
    if not src.available():
        sys.exit("error: rpicam-still not found")
    t0 = time.monotonic()
    try:
        path, when = src.capture()
    except CaptureError as e:
        sys.exit(f"error: {e}")
    from .wcs import image_size
    w, h = image_size(path)
    print(f"Captured {path} ({w} x {h} px, {path.stat().st_size // 1024} KB) in {time.monotonic() - t0:.1f} s")
    return 0


def cmd_tune(cfg, args):
    mount = _make_mount(cfg, args)
    corr = mount.to_steps(args.az, args.alt)
    print(f"Tune: azimuth {args.az:+.3f}° = {corr.az_steps:+d} steps, "
          f"altitude {args.alt:+.3f}° = {corr.alt_steps:+d} steps")
    if not mount.apply(corr):
        return 1
    if not args.dry_run:
        _, state = _load_model(cfg)
        state.add(args.az, args.alt)
    return 0


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
    s.add_argument("--no-model", action="store_true", help="ignore the pointing model")

    s = sub.add_parser("align", help="startup alignment: fit the mount's pointing model")
    s.add_argument("--points", type=int, default=6)
    s.add_argument("--targets", help="comma-separated targets instead of automatic choice")
    s.add_argument("--mount", choices=["advisor", "tmux"])
    s.add_argument("--source", choices=["rpicam", "pilomar-folder"])
    s.add_argument("--image", help=argparse.SUPPRESS)
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--time")

    s = sub.add_parser("goto", help="GOTO a target and correct it with the pointing model")
    s.add_argument("name")
    s.add_argument("--no-slew", action="store_true",
                   help="Pi-lomar is already on the target; just re-apply the correction")
    s.add_argument("--mount", choices=["advisor", "tmux"])
    s.add_argument("--dry-run", action="store_true")

    s = sub.add_parser("model", help="show, refit or clear the pointing model")
    s.add_argument("action", choices=["show", "fit", "reset"])

    s = sub.add_parser("selftest", help="indoor test: real solver on synthetic star pictures")
    s.add_argument("--targets", default="m31,m42,m13,m81", help="comma-separated targets")
    s.add_argument("--center", action="store_true", help="run the centring loop (virtual mount, real solver)")
    s.add_argument("--az", type=float, default=1.5, help="--center: starting azimuth error")
    s.add_argument("--alt", type=float, default=-0.8, help="--center: starting altitude error")
    s.add_argument("--width", type=int, default=1014, help="synthetic picture width in pixels")
    s.add_argument("--max-mag", type=float, default=8.0, help="faintest star to draw")
    s.add_argument("--catalog", help="path to hip_main.dat (default: Pi-lomar's data folder)")
    s.add_argument("--seed", type=int, default=7)

    s = sub.add_parser("capture", help="take one picture with rpicam-still (camera check)")
    s.add_argument("--exposure", type=float, help="seconds (e.g. 0.01 indoors in daylight)")
    s.add_argument("--gain", type=float)

    s = sub.add_parser("tune", help="send one Tune move through the configured mount mode")
    s.add_argument("--az", type=float, default=0.0, help="degrees")
    s.add_argument("--alt", type=float, default=0.0, help="degrees")
    s.add_argument("--mount", choices=["advisor", "tmux"])
    s.add_argument("--dry-run", action="store_true")

    s = sub.add_parser("report", help="summary of test results to copy and share (no personal details)")
    s.add_argument("--since", help="only include runs from this date, e.g. 2026-12-01")

    s = sub.add_parser("simulate-align", help="test alignment on a virtual mount with known faults")
    s.add_argument("--ia", type=float, default=1.2, help="azimuth home offset, degrees")
    s.add_argument("--ie", type=float, default=-0.6, help="altitude zero offset")
    s.add_argument("--an", type=float, default=0.5, help="base tilt north-south")
    s.add_argument("--aw", type=float, default=-0.7, help="base tilt east-west")
    s.add_argument("--ca", type=float, default=0.3, help="camera sideways offset")
    s.add_argument("--points", type=int, default=6)
    s.add_argument("--time")

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
            "center": cmd_center, "watch": cmd_watch, "simulate": cmd_simulate, "config": cmd_config,
            "align": cmd_align, "goto": cmd_goto, "model": cmd_model,
            "simulate-align": cmd_simulate_align, "report": cmd_report,
            "selftest": cmd_selftest, "capture": cmd_capture, "tune": cmd_tune}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    return COMMANDS[args.cmd](cfg, args) or 0


if __name__ == "__main__":
    sys.exit(main())
