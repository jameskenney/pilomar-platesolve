import tempfile
import unittest
from pathlib import Path

from pilomar_platesolve import annotate as ann
from pilomar_platesolve.catalog import Catalog
from pilomar_platesolve.synthetic import render_starfield
from pilomar_platesolve.wcs import solution_from_header

STARS = [(279.23, 38.78, 0.0),     # Vega
         (284.74, 32.69, 3.5), (283.63, 36.90, 4.3), (275.0, 40.0, 5.5)]


@unittest.skipUnless(ann.available(), "OpenCV not installed")
class TestAnnotate(unittest.TestCase):
    def test_labels_and_marks(self):
        import cv2
        with tempfile.TemporaryDirectory() as d:
            png = Path(d) / "lyra.png"
            t = render_starfield(STARS, 281.0, 36.0, 30.0, 1014, 760, 80.6, png)
            h = {"CRVAL1": t["ra"], "CRVAL2": t["dec"], "CRPIX1": t["crpix"][0], "CRPIX2": t["crpix"][1],
                 "CD1_1": t["cd"][0], "CD1_2": t["cd"][1], "CD2_1": t["cd"][2], "CD2_2": t["cd"][3],
                 "IMAGEW": 1014, "IMAGEH": 760}
            sol = solution_from_header(h, 1014, 760, y_down=True)
            # The rendered Vega sits where the overlay will circle it.
            x, y = ann._in_view(sol, 279.23, 38.78)
            img = cv2.imread(str(png), 0)
            self.assertGreater(int(img[int(round(y)), int(round(x))]), 150)
            stars = [(i, ra, dec, m) for i, (ra, dec, m) in enumerate(STARS)]
            m57 = Catalog().resolve("m57")
            out = Path(d) / "out" / "lyra.annotated.jpg"
            res = ann.annotate(png, sol, out, stars=stars, dsos=[m57], target=m57, title="test")
            self.assertTrue(out.exists())
            self.assertIn("Vega", res["named"])
            self.assertIn("m57", res["dsos"])
            self.assertEqual(res["stars"], 4)
            self.assertEqual(cv2.imread(str(out)).shape[:2], (760, 1014))

    def test_same_object_labelled_once(self):
        from pilomar_platesolve.catalog import Target
        h = {"CRVAL1": 10.68, "CRVAL2": 41.27, "CRPIX1": 500.5, "CRPIX2": 400.5,
             "CD1_1": -0.0112, "CD1_2": 0.0, "CD2_1": 0.0, "CD2_2": -0.0112, "IMAGEW": 1000, "IMAGEH": 800}
        sol = solution_from_header(h, 1000, 800, y_down=True)
        with tempfile.TemporaryDirectory() as d:
            import cv2, numpy as np
            png = Path(d) / "blank.png"
            cv2.imwrite(str(png), np.zeros((800, 1000), np.uint8))
            dsos = [Target("pgc0002557", "", 10.6847, 41.2690), Target("ngc205", "", 10.0921, 41.6853),
                    Target("m31", "Andromeda", 10.6846, 41.2688), Target("m110", "", 10.0920, 41.6853)]
            res = ann.annotate(png, sol, Path(d) / "o.jpg", dsos=dsos)
            self.assertEqual(sorted(res["dsos"]), ["m110", "m31"])

    def test_north_arrow_matches_rotation(self):
        # rotation 0: north is straight up (negative y on a top-down picture)
        h = {"CRVAL1": 10.0, "CRVAL2": 40.0, "CRPIX1": 500.5, "CRPIX2": 400.5,
             "CD1_1": -0.01, "CD1_2": 0.0, "CD2_1": 0.0, "CD2_2": -0.01, "IMAGEW": 1000, "IMAGEH": 800}
        sol = solution_from_header(h, 1000, 800, y_down=True)
        dx, dy = ann._direction(sol, 0.0, 0.2)
        self.assertLess(dy, -0.99)

    def test_star_name_positions_are_sane(self):
        for name, ra, dec in ann.STAR_NAMES:
            self.assertTrue(0 <= ra < 360 and -90 <= dec <= 90, name)


if __name__ == "__main__":
    unittest.main()
