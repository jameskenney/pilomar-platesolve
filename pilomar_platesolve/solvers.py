"""Local plate-solver back ends.

* ``astrometry`` -- astrometry.net's ``solve-field``. This is the same solver
  Pi-lomar's own ``scripts/astrometry.net`` installer sets up
  (``astrometry.net`` + ``astrometry-data-2mass-08-19`` from apt), so nothing
  extra needs installing and nothing is installed twice.
* ``astap`` -- ASTAP's command-line solver (``astap_cli``), optional. Often
  faster on a Pi when given a good position hint.

Both run fully offline on the Pi. Each writes its working files into this
add-on's own work folder, never into Pi-lomar's folders.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .wcs import PlateSolution, image_size, read_wcs_file, solution_from_header


class SolveError(RuntimeError):
    pass


@dataclass
class SolveHint:
    """What we already roughly know. Each item makes the solve much faster."""

    ra_deg: float | None = None
    dec_deg: float | None = None
    radius_deg: float | None = None
    fov_width_deg: float | None = None   # expected horizontal field of view
    fov_tolerance: float = 0.25          # +/- fraction for the scale search


# Source-extraction settings per lens, from the (unused) comments in Pi-lomar's
# own pilomarplatesolve.py. --objs: how many of the brightest stars to try;
# --uniformize: spread them over the whole picture; --sigma: detection threshold.
LENS_PRESETS = {
    "16mm": ["--objs", "120", "--uniformize", "120", "--sigma", "6"],
    "50mm": ["--objs", "80", "--uniformize", "80", "--sigma", "8"],
}


def preset_for(name: str, fov_width_deg: float | None) -> tuple[str, list[str]]:
    """'auto' picks by field width: the 16 mm lens sees ~23°, the 50 mm ~7°."""
    if name in LENS_PRESETS:
        return name, LENS_PRESETS[name]
    if name == "auto" and fov_width_deg:
        key = "16mm" if fov_width_deg > 12 else "50mm"
        return key, LENS_PRESETS[key]
    return "none", []


class Solver:
    name = "base"

    def __init__(self, cfg: dict, workdir: Path):
        self.cfg = cfg
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)

    def available(self) -> bool:
        raise NotImplementedError

    def command(self, image: Path, hint: SolveHint) -> list[str]:
        raise NotImplementedError

    def solve(self, image: str | Path, hint: SolveHint | None = None) -> PlateSolution:
        raise NotImplementedError


class AstrometryNetSolver(Solver):
    name = "astrometry"

    def exe(self) -> str:
        return self.cfg.get("solve_field", "solve-field")

    def available(self) -> bool:
        return shutil.which(self.exe()) is not None

    def command(self, image: Path, hint: SolveHint) -> list[str]:
        base = image.stem
        cmd = [
            self.exe(), str(image),
            "--dir", str(self.workdir), "--out", base,
            "--overwrite", "--no-plots",
            "--crpix-center",                       # CRVAL is then the image centre
            "--downsample", str(self.cfg.get("downsample", 2)),
            "--cpulimit", str(self.cfg.get("cpulimit_s", 60)),
            "--new-fits", "none", "--index-xyls", "none", "--rdls", "none",
            "--match", "none", "--corr", "none",
        ]
        if hint.fov_width_deg:
            lo = hint.fov_width_deg * (1 - hint.fov_tolerance)
            hi = hint.fov_width_deg * (1 + hint.fov_tolerance)
            cmd += ["--scale-units", "degwidth", "--scale-low", f"{lo:.3f}", "--scale-high", f"{hi:.3f}"]
        if hint.ra_deg is not None and hint.dec_deg is not None:
            cmd += ["--ra", f"{hint.ra_deg:.5f}", "--dec", f"{hint.dec_deg:.5f}",
                    "--radius", f"{hint.radius_deg or 15:.2f}"]
        if self._preset_args:
            cmd += self._preset_args
        cmd += [str(a) for a in self.cfg.get("extra_args", [])]
        return cmd

    _preset_args: list[str] = []

    def solve_rescue(self, image, hint=None) -> PlateSolution:
        """Second try for a picture that didn't solve: clean it up first and
        use the lens preset. The solution is for the original picture (same size)."""
        from . import imageprep
        image = Path(image)
        hint = hint or SolveHint()
        name, args = preset_for(str(self.cfg.get("preset", "auto")), hint.fov_width_deg)
        cleaned = imageprep.clean_for_solving(image, self.workdir) if self.cfg.get("clean", True) else None
        old_args, old_cpu = self._preset_args, self.cfg.get("cpulimit_s", 60)
        self._preset_args = args
        self.cfg["cpulimit_s"] = self.cfg.get("rescue_cpulimit_s", 30)
        try:
            sol = self.solve(cleaned or image, hint)
        finally:
            self._preset_args = old_args
            self.cfg["cpulimit_s"] = old_cpu
        sol.image = str(image)
        sol.extra["rescue"] = ", ".join(x for x in (
            "cleaned" if cleaned else "", f"{name} preset" if args else "") if x) or "retry"
        return sol

    def solve(self, image, hint=None) -> PlateSolution:
        image = Path(image)
        hint = hint or SolveHint()
        if not image.exists():
            raise SolveError(f"image not found: {image}")
        if self.cfg.get("preset_when") == "always" and not self._preset_args:
            self._preset_args = preset_for(str(self.cfg.get("preset", "auto")), hint.fov_width_deg)[1]
            try:
                return self.solve(image, hint)
            finally:
                self._preset_args = []
        wcs = self.workdir / (image.stem + ".wcs")
        wcs.unlink(missing_ok=True)
        cmd = self.command(image, hint)
        t0 = time.monotonic()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=float(self.cfg.get("cpulimit_s", 60)) + 30)
        except FileNotFoundError as e:
            raise SolveError(f"{self.exe()} not installed (sudo apt install astrometry.net)") from e
        except subprocess.TimeoutExpired as e:
            raise SolveError("solve-field timed out") from e
        dt = time.monotonic() - t0
        (self.workdir / (image.stem + ".solve.log")).write_text(
            " ".join(cmd) + "\n\n" + proc.stdout + "\n" + proc.stderr)
        if not wcs.exists():
            raise SolveError("no solution (too few stars, clouds, wrong scale hint, "
                             "or missing index files). See " + str(self.workdir / (image.stem + ".solve.log")))
        w, h = image_size(image)
        sol = solution_from_header(read_wcs_file(wcs), w, h, solver=self.name, image=str(image))
        sol.solve_seconds = dt
        return sol


class AstapSolver(Solver):
    """ASTAP command-line solver. Needs astap_cli plus a star database (e.g. D50)."""

    name = "astap"

    def exe(self) -> str:
        return self.cfg.get("astap", "astap_cli")

    def available(self) -> bool:
        return shutil.which(self.exe()) is not None

    def command(self, image: Path, hint: SolveHint) -> list[str]:
        out = self.workdir / image.stem
        cmd = [self.exe(), "-f", str(image), "-o", str(out), "-wcs",
               "-z", str(self.cfg.get("downsample", 2))]
        if hint.fov_width_deg:
            # ASTAP wants the *height* of the field.
            aspect = float(self.cfg.get("aspect_h_over_w", 0.75))
            cmd += ["-fov", f"{hint.fov_width_deg * aspect:.3f}"]
        if hint.ra_deg is not None and hint.dec_deg is not None:
            cmd += ["-ra", f"{hint.ra_deg / 15.0:.5f}", "-spd", f"{hint.dec_deg + 90.0:.5f}",
                    "-r", f"{hint.radius_deg or 15:.2f}"]
        else:
            cmd += ["-r", "180"]
        if self._preset_args:
            cmd += self._preset_args
        cmd += [str(a) for a in self.cfg.get("extra_args", [])]
        return cmd

    _preset_args: list[str] = []

    def solve_rescue(self, image, hint=None) -> PlateSolution:
        """Second try for a picture that didn't solve: clean it up first and
        use the lens preset. The solution is for the original picture (same size)."""
        from . import imageprep
        image = Path(image)
        hint = hint or SolveHint()
        name, args = preset_for(str(self.cfg.get("preset", "auto")), hint.fov_width_deg)
        cleaned = imageprep.clean_for_solving(image, self.workdir) if self.cfg.get("clean", True) else None
        old_args, old_cpu = self._preset_args, self.cfg.get("cpulimit_s", 60)
        self._preset_args = args
        self.cfg["cpulimit_s"] = self.cfg.get("rescue_cpulimit_s", 30)
        try:
            sol = self.solve(cleaned or image, hint)
        finally:
            self._preset_args = old_args
            self.cfg["cpulimit_s"] = old_cpu
        sol.image = str(image)
        sol.extra["rescue"] = ", ".join(x for x in (
            "cleaned" if cleaned else "", f"{name} preset" if args else "") if x) or "retry"
        return sol

    def solve(self, image, hint=None) -> PlateSolution:
        image = Path(image)
        hint = hint or SolveHint()
        out = self.workdir / image.stem
        ini, wcs = Path(str(out) + ".ini"), Path(str(out) + ".wcs")
        for f in (ini, wcs):
            f.unlink(missing_ok=True)
        cmd = self.command(image, hint)
        t0 = time.monotonic()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=float(self.cfg.get("timeout_s", 90)))
        except FileNotFoundError as e:
            raise SolveError(f"{self.exe()} not installed") from e
        except subprocess.TimeoutExpired as e:
            raise SolveError("astap timed out") from e
        dt = time.monotonic() - t0
        (self.workdir / (image.stem + ".solve.log")).write_text(
            " ".join(cmd) + "\n\n" + proc.stdout + "\n" + proc.stderr)
        if not ini.exists():
            raise SolveError("astap produced no result file")
        hdr = read_wcs_file(ini)
        if hdr.get("PLTSOLVD") is False:
            raise SolveError("astap found no solution")
        if wcs.exists():
            hdr = {**read_wcs_file(wcs), **hdr}
        w, h = image_size(image)
        sol = solution_from_header(hdr, w, h, solver=self.name, image=str(image))
        sol.solve_seconds = dt
        return sol


SOLVERS = {"astrometry": AstrometryNetSolver, "astap": AstapSolver}


def make_solver(cfg: dict, workdir: Path) -> Solver:
    name = cfg.get("solver", {}).get("backend", "astrometry")
    if name not in SOLVERS:
        raise ValueError(f"unknown solver backend {name!r}; choose from {list(SOLVERS)}")
    return SOLVERS[name](cfg.get("solver", {}).get(name, {}), workdir)
