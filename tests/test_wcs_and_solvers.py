import math
import tempfile
import unittest
from pathlib import Path

from pilomar_platesolve.solvers import AstapSolver, AstrometryNetSolver, SolveHint
from pilomar_platesolve.wcs import (image_size, parse_fits_header_text, read_wcs_file,
                                    solution_from_header)


def card(key, value, comment=""):
    if isinstance(value, str):
        v = f"'{value:<8}'"
        s = f"{key:<8}= {v:<20}"
    elif isinstance(value, bool):
        s = f"{key:<8}= {'T' if value else 'F':>20}"
    elif isinstance(value, float):
        s = f"{key:<8}= {value:>20.12E}"
    else:
        s = f"{key:<8}= {value:>20}"
    if comment:
        s += f" / {comment}"
    return s[:80].ljust(80)


def header_block(cards):
    text = "".join(cards) + "END".ljust(80)
    return text + " " * (-len(text) % 2880)


def wcs_header(ra=10.6847, dec=41.2690, scale_arcsec=39.4, rot_deg=30.0, w=2028, h=1520):
    s = scale_arcsec / 3600
    r = math.radians(rot_deg)
    cd = (-s * math.cos(r), -s * math.sin(r), s * math.sin(r), -s * math.cos(r))
    return header_block([
        card("SIMPLE", True), card("BITPIX", 8), card("NAXIS", 0),
        card("WCSAXES", 2), card("CTYPE1", "RA---TAN-SIP"), card("CTYPE2", "DEC--TAN-SIP"),
        card("CRVAL1", float(ra)), card("CRVAL2", float(dec)),
        card("CRPIX1", (w + 1) / 2), card("CRPIX2", (h + 1) / 2),
        card("CD1_1", cd[0]), card("CD1_2", cd[1]),
        card("CD2_1", cd[2]), card("CD2_2", cd[3]),
        card("IMAGEW", w), card("IMAGEH", h),
        card("COMMENT", "x"),
    ])


class TestWcs(unittest.TestCase):
    def test_parse_cards(self):
        h = parse_fits_header_text(wcs_header())
        self.assertEqual(h["CTYPE1"], "RA---TAN-SIP")
        self.assertTrue(h["SIMPLE"])
        self.assertAlmostEqual(h["CRVAL1"], 10.6847)
        self.assertEqual(h["IMAGEW"], 2028)

    def test_solution_numbers(self):
        sol = solution_from_header(parse_fits_header_text(wcs_header(rot_deg=30.0)), image="x.jpg")
        self.assertAlmostEqual(sol.ra_deg, 10.6847, places=6)
        self.assertAlmostEqual(sol.dec_deg, 41.2690, places=6)
        self.assertAlmostEqual(sol.scale_arcsec, 39.4, places=6)
        self.assertAlmostEqual(sol.rotation_deg, 30.0, places=6)
        self.assertAlmostEqual(sol.fov_width_deg, 2028 * 39.4 / 3600, places=6)
        self.assertFalse(sol.flipped)

    def test_mirrored_image_detected(self):
        h = parse_fits_header_text(wcs_header())
        h["CD1_1"], h["CD2_1"] = -h["CD1_1"], -h["CD2_1"]
        self.assertTrue(solution_from_header(h, image="x.jpg").flipped)

    def test_center_when_crpix_not_centre(self):
        # solve-field without --crpix-center puts CRPIX elsewhere; the reported
        # centre must still be the sky position of the middle pixel.
        h = dict(parse_fits_header_text(wcs_header()), CRPIX1=300.0, CRPIX2=1200.0)
        sol = solution_from_header(h, image="x.jpg")
        x, y = sol.radec_to_pixel(sol.ra_deg, sol.dec_deg)
        self.assertAlmostEqual(x, (2028 + 1) / 2, places=6)
        self.assertAlmostEqual(y, (1520 + 1) / 2, places=6)
        self.assertGreater(abs(sol.ra_deg - 10.6847), 1.0)

    def test_pixel_roundtrip(self):
        sol = solution_from_header(parse_fits_header_text(wcs_header()), image="x.jpg")
        for x, y in [(1, 1), (2028, 1), (500, 1400), (1014.5, 760.5)]:
            ra, dec = sol.pixel_to_radec(x, y)
            x2, y2 = sol.radec_to_pixel(ra, dec)
            self.assertAlmostEqual(x, x2, places=6)
            self.assertAlmostEqual(y, y2, places=6)

    def test_astap_ini_style(self):
        text = ("PLTSOLVD=T\nCRPIX1= 1.0145E+03\nCRPIX2= 7.605E+02\nCRVAL1= 1.068E+01\n"
                "CRVAL2= 4.127E+01\nCD1_1=-1.0E-02\nCD1_2= 0\nCD2_1= 0\nCD2_2=-1.0E-02\n")
        sol = solution_from_header(parse_fits_header_text(text), 2028, 1520, image="x.jpg")
        self.assertAlmostEqual(sol.scale_arcsec, 36.0, places=6)
        self.assertAlmostEqual(sol.rotation_deg, 0.0, places=6)
        with self.assertRaises(ValueError):
            solution_from_header(parse_fits_header_text("PLTSOLVD=F\n"), 10, 10)

    def test_read_file_and_image_size(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.wcs"
            p.write_text(wcs_header())
            self.assertIn("CD1_1", read_wcs_file(p))
            png = Path(d) / "a.png"
            png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
                            + (640).to_bytes(4, "big") + (480).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00")
            self.assertEqual(image_size(png), (640, 480))
            jpg = Path(d) / "a.jpg"
            sof = b"\xff\xc0\x00\x11\x08" + (1520).to_bytes(2, "big") + (2028).to_bytes(2, "big") + b"\x03" + b"\x00" * 9
            jpg.write_bytes(b"\xff\xd8" + b"\xff\xe0\x00\x10" + b"JFIF\x00" + b"\x00" * 9 + sof + b"\xff\xd9")
            self.assertEqual(image_size(jpg), (2028, 1520))


class TestSolverCommands(unittest.TestCase):
    def test_astrometry_command(self):
        with tempfile.TemporaryDirectory() as d:
            s = AstrometryNetSolver({"downsample": 2, "cpulimit_s": 30}, Path(d))
            cmd = s.command(Path("/x/img.jpg"), SolveHint(10.68, 41.27, 15, 22.2))
            self.assertEqual(cmd[0], "solve-field")
            self.assertIn("--crpix-center", cmd)
            self.assertEqual(cmd[cmd.index("--ra") + 1], "10.68000")
            self.assertEqual(cmd[cmd.index("--scale-units") + 1], "degwidth")
            self.assertAlmostEqual(float(cmd[cmd.index("--scale-low") + 1]), 22.2 * 0.75, places=2)
            blind = s.command(Path("/x/img.jpg"), SolveHint())
            self.assertNotIn("--ra", blind)

    def test_astap_command(self):
        with tempfile.TemporaryDirectory() as d:
            s = AstapSolver({}, Path(d))
            cmd = s.command(Path("/x/img.jpg"), SolveHint(15.0, -10.0, 10, 22.2))
            self.assertEqual(cmd[cmd.index("-ra") + 1], "1.00000")    # hours
            self.assertEqual(cmd[cmd.index("-spd") + 1], "80.00000")  # dec + 90


if __name__ == "__main__":
    unittest.main()
