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
        cmd += [str(a) for a in self.cfg.get("extra_args", [])]
        return cmd

    def solve(self, image, hint=None) -> PlateSolution:
        image = Path(image)
        hint = hint or SolveHint()
        if not image.exists():
            raise SolveError(f"image not found: {image}")
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
        cmd += [str(a) for a in self.cfg.get("extra_args", [])]
        return cmd

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
