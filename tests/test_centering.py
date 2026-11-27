import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pilomar_platesolve import astro
from pilomar_platesolve.catalog import Catalog, load_pilomar_catalog, parse_coordinates
from pilomar_platesolve.centering import Logbook, center_target, pointing_error
from pilomar_platesolve.config import DEFAULTS, _merge
from pilomar_platesolve.mount import AdvisorMount, Correction, SimulatedMount, TmuxMount
from pilomar_platesolve.pilomar_bridge import parse_lat_lon, site_from_config
from pilomar_platesolve.sim import SimSolver, SimSource, SimWorld

SITE = astro.Site(35.47, -97.52)          # Oklahoma City
T0 = datetime(2026, 11, 25, 3, 0, tzinfo=timezone.utc)


def cfg(**over):
    return _merge(DEFAULTS, over)


def run(err_az, err_alt, target="m31", **kw):
    c = cfg()
    tgt = Catalog().resolve(target)
    mount = SimulatedMount(c["mount"], err_az, err_alt, kw.pop("lost", 0.1),
                           true_az_sign=kw.pop("true_az_sign", None))
    world = SimWorld(tgt, SITE, kw.pop("start", T0), mount, fail_solves=kw.pop("fail", 0))
    res = center_target(tgt, cfg=c, site=SITE, source=SimSource(world), solver=SimSolver(world),
                        mount=mount, verbose=False, sleep=lambda s: None, **kw)
    return res, mount


class TestCentering(unittest.TestCase):
    def test_example_from_the_brief(self):
        res, mount = run(1.5, -0.8)
        self.assertTrue(res.success, res.reason)
        self.assertLessEqual(len(res.iterations), 4)
        self.assertLess(res.final_error, 0.1)
        self.assertLess(abs(mount.err_az) + abs(mount.err_alt), 0.2)

    def test_large_error_is_clamped_but_converges(self):
        res, mount = run(-14.0, 6.0)
        self.assertTrue(res.success, res.reason)
        first = mount.history[0]
        self.assertLessEqual(abs(first.d_az_deg), DEFAULTS["centering"]["max_correction_deg"] + 1e-9)

    def test_reversed_sign_is_detected(self):
        res, _ = run(1.5, -0.8, true_az_sign=-1)
        self.assertFalse(res.success)
        self.assertIn("sign", res.reason)

    def test_blind_retry_after_failed_hinted_solve(self):
        res, _ = run(1.0, 1.0, fail=1)
        self.assertTrue(res.success, res.reason)

    def test_two_failed_solves_stop_cleanly(self):
        res, _ = run(1.0, 1.0, fail=2)
        self.assertFalse(res.success)
        self.assertIn("solve failed", res.reason)

    def test_other_targets_and_times(self):
        for name, start in [("m42", datetime(2026, 12, 20, 6, 0, tzinfo=timezone.utc)),
                            ("m13", datetime(2026, 6, 20, 5, 0, tzinfo=timezone.utc)),
                            ("m81", datetime(2026, 3, 1, 4, 0, tzinfo=timezone.utc))]:
            res, _ = run(0.7, 1.2, target=name, start=start)
            self.assertTrue(res.success, f"{name}: {res.reason}")

    def test_pointing_error_signs(self):
        c = cfg()
        tgt = Catalog().resolve("m31")
        mount = SimulatedMount(c["mount"], 0.0, 0.0)
        world = SimWorld(tgt, SITE, T0, mount, noise_deg=0.0)
        src, solver = SimSource(world), SimSolver(world)
        # Camera aimed 1 degree higher than the target: needs altitude -1.
        mount.err_alt = 1.0
        img, when = src.capture()
        err = pointing_error(tgt, solver.solve(img), SITE, when)
        self.assertAlmostEqual(err.d_alt_deg, -1.0, places=4)
        self.assertAlmostEqual(err.d_az_deg, 0.0, places=4)
        self.assertAlmostEqual(err.separation_deg, 1.0, places=3)

    def test_logbook(self):
        with tempfile.TemporaryDirectory() as d:
            c = cfg()
            tgt = Catalog().resolve("m31")
            mount = SimulatedMount(c["mount"], 1.0, 0.5)
            world = SimWorld(tgt, SITE, T0, mount)
            log = Logbook(d)
            center_target(tgt, cfg=c, site=SITE, source=SimSource(world), solver=SimSolver(world),
                          mount=mount, log=log, verbose=False, sleep=lambda s: None)
            self.assertTrue(log.session.exists())
            self.assertGreater(len(log.csv.read_text().splitlines()), 1)


class TestMounts(unittest.TestCase):
    def test_steps(self):
        m = AdvisorMount(DEFAULTS["mount"], interactive=False)
        c = m.to_steps(1.5, -0.8)
        self.assertEqual(c.az_steps, 1600)
        self.assertEqual(c.alt_steps, -853)

    def test_tmux_keys(self):
        m = TmuxMount(DEFAULTS["mount"], dry_run=True)
        keys = m.keys_for(Correction(1, -1, 1067, -1067))
        self.assertIn("1067", keys)
        self.assertIn("-1067", keys)


class TestCatalogAndBridge(unittest.TestCase):
    def test_resolve_names(self):
        cat = Catalog()
        self.assertEqual(cat.resolve("M31").id, "m31")
        self.assertEqual(cat.resolve("m 31").id, "m31")
        self.assertEqual(cat.resolve("Messier 31").id, "m31")
        self.assertEqual(cat.resolve("andromeda").id, "m31")
        self.assertEqual(cat.resolve("NGC 7000").id, "ngc7000")
        with self.assertRaises(KeyError):
            cat.resolve("double cluster")   # ambiguous
        with self.assertRaises(KeyError):
            cat.resolve("not a thing")

    def test_coordinates(self):
        self.assertEqual(parse_coordinates("10.5 41.2"), (10.5, 41.2))
        ra, dec = parse_coordinates("00:42:44 +41:16:09")
        self.assertAlmostEqual(ra, 10.68333, places=4)
        self.assertAlmostEqual(dec, 41.26917, places=4)
        _, dec = parse_coordinates("05h35m17s -05d23m28s")
        self.assertLess(dec, 0)

    def test_pilomar_catalog_format(self):
        sample = {"m31": {"name": "the andromeda galaxy", "magnitude": 3.4, "ra": [0, 42, 42],
                          "dec": [41, 16, 0], "radeg": 10.675, "decdeg": 41.2667, "type": "galaxy",
                          "ngc": "ngc224", "label": "m31", "widthdeg": 2.97},
                  "m4": {"name": "", "magnitude": 5.6, "ra": [16, 23, 36], "dec": [-26, -32, 0],
                         "label": "m4"}}
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "data").mkdir()
            (Path(d) / "data" / "messierobjects.json").write_text(json.dumps(sample))
            cat = Catalog(d)
            self.assertEqual(cat.resolve("ngc 224").ra_deg, 10.675)
            self.assertEqual(cat.resolve("m31").source, "messierobjects.json")
            self.assertAlmostEqual(cat.resolve("m4").dec_deg, -26.5333, places=3)
            self.assertEqual(len(load_pilomar_catalog(Path(d) / "data" / "messierobjects.json")), 3)

    def test_lat_lon_parsing(self):
        self.assertEqual(parse_lat_lon("35.47 N", "N", "S"), 35.47)
        self.assertEqual(parse_lat_lon("97.52 W", "E", "W"), -97.52)
        self.assertEqual(parse_lat_lon("-97.52", "E", "W"), -97.52)
        self.assertEqual(parse_lat_lon(12.5, "E", "W"), 12.5)
        self.assertIsNone(parse_lat_lon("nonsense", "E", "W"))

    def test_site_from_pilomar_params(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "data").mkdir()
            (Path(d) / "data" / "pilomar_params.json").write_text(
                json.dumps({"HomeLat": "35.47 N", "HomeLon": "97.52 W"}))
            s = site_from_config(cfg(pilomar_root=d))
            self.assertEqual((s.lat_deg, s.lon_east_deg), (35.47, -97.52))
            before = (Path(d) / "data" / "pilomar_params.json").read_text()
            site_from_config(cfg(pilomar_root=d))
            self.assertEqual(before, (Path(d) / "data" / "pilomar_params.json").read_text())


if __name__ == "__main__":
    unittest.main()
