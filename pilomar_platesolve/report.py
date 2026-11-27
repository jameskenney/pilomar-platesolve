"""`pilomar-ps report`: summarise the logs into one block that is easy to share.

It never includes your location, hostname, username or file paths: only the
hardware/software versions and the measured results (times, accuracy).
"""

from __future__ import annotations

import json
import platform
import re
import shutil
import statistics
import subprocess
from datetime import datetime
from pathlib import Path

from . import __version__


def _read(path: str) -> str:
    try:
        return Path(path).read_text(errors="ignore")
    except OSError:
        return ""


def _run(cmd: list[str]) -> str:
    if not shutil.which(cmd[0]):
        return ""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def system_info(cfg: dict) -> dict:
    info = {"add-on": __version__}
    model = _read("/proc/device-tree/model").strip("\x00 \n")
    if model:
        info["computer"] = model
    m = re.search(r"MemTotal:\s+(\d+)", _read("/proc/meminfo"))
    if m:
        info["RAM"] = f"{int(m.group(1)) / 1024 / 1024:.1f} GB"
    m = re.search(r'PRETTY_NAME="([^"]+)"', _read("/etc/os-release"))
    if m:
        info["OS"] = m.group(1)
    info["architecture"] = platform.machine()
    info["Python"] = platform.python_version()
    m = re.search(r"^VERSION\s*=\s*['\"]([^'\"]+)", _read(str(Path(cfg["pilomar_root"]) / "src" / "pilomar.py")), re.M)
    if m:
        info["Pi-lomar"] = m.group(1)
    for pkg in ("astrometry.net", "astrometry-data-2mass-08-19"):
        v = _run(["dpkg-query", "-W", "-f=${Version}", pkg])
        if v:
            info[pkg] = v
    astap = cfg["solver"]["astap"].get("astap", "astap_cli")
    if shutil.which(astap):
        info["ASTAP"] = "installed"
    o = cfg["optics"]
    info["lens"] = f"{o['focal_length_mm']} mm"
    info["solver / capture / mount"] = (f"{cfg['solver']['backend']} / {cfg['capture']['source']}"
                                        f" / {cfg['mount']['backend']}")
    return info


def _events(data_dir: Path, since: datetime | None):
    for f in sorted((data_dir / "sessions").glob("session_*.jsonl")):
        evs = []
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if since and datetime.fromisoformat(e["t"]) < since:
                continue
            evs.append(e)
        if evs:
            yield evs


def _secs(a: str, b: str) -> float:
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()


def _stats(vals: list[float], unit: str, digits: int = 1) -> str:
    if not vals:
        return "none"
    f = f"{{:.{digits}f}}"
    if len(vals) == 1:
        return f.format(vals[0]) + unit
    return (f"median {f.format(statistics.median(vals))}{unit}, "
            f"lowest {f.format(min(vals))}{unit}, highest {f.format(max(vals))}{unit} ({len(vals)} total)")


def collect(cfg: dict, since: datetime | None = None) -> dict:
    data = Path(cfg["data_dir"])
    solve_times, scales, fovs, solvers = [], [], [], set()
    failed = 0
    centers, aligns, gotos = [], [], 0
    for evs in _events(data, since):
        start = next((e for e in evs if e["event"] in ("start", "align_start")), None)
        n_pics = 0
        first_err = None
        used_model = False
        for e in evs:
            sol = e.get("solution")
            if e["event"] in ("solved", "watch_solved", "solve_cmd", "align_sample") and sol:
                solve_times.append(float(sol.get("solve_seconds", 0)))
                if sol.get("scale_arcsec"):
                    scales.append(float(sol["scale_arcsec"]))
                    fovs.append((float(sol["fov_width_deg"]), float(sol["fov_height_deg"])))
                if sol.get("solver"):
                    solvers.add(sol["solver"])
            if e["event"] in ("solve_failed", "solve_cmd_failed"):
                failed += 1
            if e["event"] in ("solved", "solve_failed"):
                n_pics += 1
            if e["event"] == "solved" and first_err is None:
                first_err = e["error"]["separation_deg"]
            if e["event"] == "model_correction":
                used_model = True
            if e["event"] == "goto":
                gotos += 1
            if e["event"] == "end" and start:
                centers.append({"ok": e.get("success"), "seconds": _secs(start["t"], e["t"]),
                                "pictures": n_pics, "first_error": first_err,
                                "final_error": e.get("final_error"), "model": used_model,
                                "mount": start.get("mount", "")})
            if e["event"] == "model_fitted" and start:
                m = e["model"]
                aligns.append({"seconds": _secs(start["t"], e["t"]), "n": m["n_samples"],
                               "before": m["rms_before_deg"], "after": m["rms_after_deg"],
                               "params": m["params"]})
    return {"solve_times": solve_times, "scales": scales, "fovs": fovs, "solvers": sorted(solvers),
            "failed": failed, "centers": centers, "aligns": aligns, "gotos": gotos}


def render(cfg: dict, since: datetime | None = None) -> str:
    info = system_info(cfg)
    r = collect(cfg, since)
    out = ["=== pilomar-platesolve test report ===",
           f"generated {datetime.now():%Y-%m-%d %H:%M}" + (f", since {since:%Y-%m-%d}" if since else ""),
           "", "System:"]
    out += [f"  {k}: {v}" for k, v in info.items()]

    out += ["", "Plate solving:"]
    total = len(r["solve_times"]) + r["failed"]
    out.append(f"  solved {len(r['solve_times'])} of {total} pictures"
               + (f" ({100 * len(r['solve_times']) / total:.0f}%)" if total else ""))
    out.append(f"  solve time: {_stats(r['solve_times'], ' s')}")
    if r["scales"]:
        w = statistics.median(f[0] for f in r["fovs"])
        h = statistics.median(f[1] for f in r["fovs"])
        out.append(f"  plate scale: {statistics.median(r['scales']):.2f}\"/px, field {w:.2f}° x {h:.2f}°")
    if r["solvers"]:
        out.append(f"  solver: {', '.join(r['solvers'])}")

    out += ["", "Centring (pilomar-ps center):"]
    cs = r["centers"]
    if not cs:
        out.append("  no runs yet")
    else:
        ok = [c for c in cs if c["ok"]]
        out.append(f"  runs: {len(cs)}, centred: {len(ok)}")
        out.append(f"  time per run: {_stats([c['seconds'] for c in ok], ' s', 0)}")
        out.append(f"  pictures per run: {_stats([float(c['pictures']) for c in ok], '', 1)}")
        firsts = [c["first_error"] for c in cs if c["first_error"] is not None]
        out.append(f"  error on first picture: {_stats(firsts, '°', 2)}")
        finals = [c["final_error"] for c in ok if c["final_error"] is not None]
        out.append(f"  final error: {_stats(finals, '°', 3)}")
        with_model = [c["first_error"] for c in cs if c["model"] and c["first_error"] is not None]
        if with_model:
            out.append(f"  first-picture error with pointing model: {_stats(with_model, '°', 2)}")
        out.append(f"  mount mode: {', '.join(sorted({c['mount'] for c in cs}))}")
        fails = [c for c in cs if not c["ok"]]
        if fails:
            out.append(f"  not centred: {len(fails)}")

    out += ["", "Alignment (pilomar-ps align):"]
    if not r["aligns"]:
        out.append("  no alignments yet")
    for a in r["aligns"][-3:]:
        p = a["params"]
        tilt = (p.get("AN", 0) ** 2 + p.get("AW", 0) ** 2) ** 0.5
        out.append(f"  {a['n']} pictures in {a['seconds'] / 60:.1f} min: error {a['before']:.2f}° rms"
                   f" -> {a['after']:.3f}° after model; base tilt {tilt:.2f}°, "
                   f"home offset az {p.get('IA', 0):+.2f}° alt {p.get('IE', 0):+.2f}°")
    if r["gotos"]:
        out.append(f"  model GOTOs: {r['gotos']}")
    out.append("=== end of report ===")
    return "\n".join(out)
