import math
import os
import random
import tempfile
import unittest
from pathlib import Path

from pilomar_platesolve.cli import main
from pilomar_platesolve.synthetic import load_hipparcos, render_starfield
from pilomar_platesolve.wcs import image_size

HERE = Path(__file__).parent


def fake_catalogue(path, n=20000, seed=1):
    r = random.Random(seed)
    with open(path, "w") as f:
        f.write("H|           0| |00 00 00.00|+00 00 00.0|     | |H|            |            | |\n")
        for i in range(1, n + 1):
            ra, dec = r.uniform(0, 360), math.degrees(math.asin(r.uniform(-1, 1)))
            f.write(f"H|{i:>12}| |00 00 00.00|+00 00 00.0|{r.uniform(2, 9):5.2f}| |H|"
                    f"{ra:012.8f}|{dec:+012.8f}| |   1.00|\n")


class TestSynthetic(unittest.TestCase):
    def test_catalogue_parsing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "hip_main.dat"
            fake_catalogue(p, 1000)
            stars = load_hipparcos(p, 8.0)
            self.assertTrue(500 < len(stars) < 1000)   # blank-magnitude line skipped
            self.assertTrue(all(m <= 8.0 for _, _, m in stars))

    def test_star_lands_on_its_pixel(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "one.png"
            # One bright star exactly at the centre, picture rotated 40 degrees.
            truth = render_starfield([(10.0, 41.0, 3.0)], 10.0, 41.0, 40.0, 201, 151, 60.0, out, seed=2)
            self.assertEqual(image_size(out), (201, 151))
            self.assertEqual(truth["stars"], 1)
            self.assertTrue(Path(str(out) + ".truth.json").exists())

    def test_selftest_commands_with_stand_in_solver(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "pilomar" / "data").mkdir(parents=True)
            fake_catalogue(Path(d) / "pilomar" / "data" / "hip_main.dat")
            (Path(d) / "pilomar" / "data" / "pilomar_params.json").write_text(
                '{"HomeLat": "35.47 N", "HomeLon": "97.52 W"}')
            cfg = Path(d) / "config.json"
            cfg.write_text('{"pilomar_root": "%s", "data_dir": "%s", "solver": {"astrometry": '
                           '{"solve_field": "%s"}}}' % (Path(d) / "pilomar", Path(d) / "data",
                                                         HERE / "fake_solve_field.py"))
            with open(os.devnull, "w") as null:
                import contextlib
                with contextlib.redirect_stdout(null):
                    self.assertEqual(main(["--config", str(cfg), "selftest", "--targets", "m31,m42"]), 0)
                    self.assertEqual(main(["--config", str(cfg), "selftest", "--center"]), 0)
                    self.assertEqual(main(["--config", str(cfg), "tune", "--az", "1", "--mount", "tmux",
                                           "--dry-run"]), 0)
            from pilomar_platesolve.config import _merge, DEFAULTS
            from pilomar_platesolve.report import render
            text = render(_merge(DEFAULTS, {"data_dir": str(Path(d) / "data"), "pilomar_root": d}))
            self.assertIn("runs: 1, centred: 1", text)


if __name__ == "__main__":
    unittest.main()
