import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from pilomar_platesolve.cli import main
from pilomar_platesolve.focus import measure_stars, read_bmp_gray

HERE = Path(__file__).parent


class TestFocus(unittest.TestCase):
    def run_focus(self, d, sigma):
        Path(d, "sigma").write_text(str(sigma))
        os.environ["FAKE_FOCUS_SIGMA_FILE"] = str(Path(d, "sigma"))
        cfg = Path(d) / "config.json"
        cfg.write_text('{"data_dir": "%s", "pilomar_root": "%s", "capture": {"rpicam": {"exe": "%s"}}}'
                       % (Path(d) / "data", d, HERE / "fake_rpicam_still.py"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(main(["--config", str(cfg), "focus", "--count", "1"]), 0)
        return buf.getvalue(), read_bmp_gray(Path(d) / "data" / "focus" / "focus.bmp")

    def test_sharper_stars_measure_smaller(self):
        with tempfile.TemporaryDirectory() as d:
            sizes = []
            for sigma in (1.0, 2.0, 3.5):
                text, img = self.run_focus(d, sigma)
                self.assertIn("size", text)
                res = measure_stars(*img)
                self.assertGreater(res.stars, 20)
                sizes.append(res.hfr)
            self.assertLess(sizes[0], sizes[1])
            self.assertLess(sizes[1], sizes[2])

    def test_no_stars(self):
        w, h = 200, 150
        res = measure_stars(w, h, [30] * (w * h))
        self.assertIsNone(res.hfr)
        self.assertEqual(res.stars, 0)

    def tearDown(self):
        os.environ.pop("FAKE_FOCUS_SIGMA_FILE", None)


if __name__ == "__main__":
    unittest.main()
