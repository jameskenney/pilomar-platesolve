import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from pilomar_platesolve import imageprep
from pilomar_platesolve.centering import solve_with_fallback
from pilomar_platesolve.solvers import AstrometryNetSolver, SolveHint, preset_for

FAKE = r'''#!/usr/bin/env python3
import sys
a = sys.argv[1:]
d = a[a.index("--dir") + 1]; o = a[a.index("--out") + 1]
open(d + "/calls.log", "a").write(" ".join(a) + "\n")
if "--objs" not in a:          # a hard picture: only the rescue settings solve it
    sys.exit(0)
def card(k, v):
    v = f"{v:>20.12E}" if isinstance(v, float) else f"{v:>20}"
    return f"{k:<8}= {v}".ljust(80)
s = 40.3 / 3600
cards = [card("SIMPLE", "T"), card("CRVAL1", 10.68), card("CRVAL2", 41.27),
         card("CRPIX1", 100.5), card("CRPIX2", 75.5), card("CD1_1", -s), card("CD1_2", 0.0),
         card("CD2_1", 0.0), card("CD2_2", -s), card("IMAGEW", 200), card("IMAGEH", 150), "END".ljust(80)]
open(f"{d}/{o}.wcs", "w").write("".join(cards))
'''


def hazy_star_picture(path: Path):
    import cv2
    import numpy as np
    h, w = 150, 200
    yy, xx = np.mgrid[0:h, 0:w]
    img = 60 + 0.5 * xx + 0.3 * yy                    # bright gradient (moonlit haze)
    rng = np.random.default_rng(1)
    for _ in range(40):
        x, y = rng.integers(5, w - 5), rng.integers(5, h - 5)
        img += 60 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / 3.0)
    img += rng.normal(0, 3, img.shape)
    cv2.imwrite(str(path), np.clip(img, 0, 255).astype(np.uint8))


class TestPresets(unittest.TestCase):
    def test_auto_by_field_width(self):
        self.assertEqual(preset_for("auto", 22.7)[0], "16mm")
        self.assertEqual(preset_for("auto", 7.0)[0], "50mm")
        self.assertEqual(preset_for("none", 22.7), ("none", []))
        self.assertIn("--uniformize", preset_for("16mm", None)[1])

    def test_always_mode_adds_preset(self):
        with tempfile.TemporaryDirectory() as d:
            s = AstrometryNetSolver({"preset_when": "always"}, Path(d))
            self.assertNotIn("--objs", s.command(Path("x.jpg"), SolveHint(fov_width_deg=22.7)))


@unittest.skipUnless(imageprep.available(), "OpenCV/NumPy not installed")
class TestCleanAndRescue(unittest.TestCase):
    def test_clean_removes_gradient_keeps_size(self):
        import cv2
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "hazy.jpg"
            hazy_star_picture(src)
            out = imageprep.clean_for_solving(src, Path(d) / "work")
            self.assertTrue(out and out.exists())
            a, b = cv2.imread(str(src), 0), cv2.imread(str(out), 0)
            self.assertEqual(a.shape, b.shape)
            # background no longer rises across the frame
            self.assertLess(abs(float(b[:, -20:].mean()) - float(b[:, :20].mean())), 10)
            self.assertGreater(float(a[:, -20:].mean()) - float(a[:, :20].mean()), 50)

    def test_rescue_solves_hard_picture(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "fake_solve_field"
            fake.write_text(FAKE)
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            src = Path(d) / "hazy.jpg"
            hazy_star_picture(src)
            work = Path(d) / "work"
            work.mkdir()
            solver = AstrometryNetSolver({"solve_field": str(fake), "rescue": True,
                                          "preset": "auto", "clean": True}, work)
            sol = solve_with_fallback(solver, src, SolveHint(10.7, 41.3, 15, 22.7), True)
            calls = (work / "calls.log").read_text().splitlines()
            self.assertEqual(len(calls), 2)                 # normal, then rescue
            self.assertIn(".clean.png", calls[1])
            self.assertIn("--objs 120", calls[1])
            self.assertEqual(sol.image, str(src))
            self.assertIn("cleaned", sol.extra["rescue"])
            self.assertIn("retry:", sol.summary())


if __name__ == "__main__":
    unittest.main()
