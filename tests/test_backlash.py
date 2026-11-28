import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pilomar_platesolve.astro import Site
from pilomar_platesolve.backlash import measure_backlash, save_backlash
from pilomar_platesolve.catalog import Catalog
from pilomar_platesolve.centering import backlash_settings, center_target, tune
from pilomar_platesolve.config import DEFAULTS, _merge
from pilomar_platesolve.model import PointingState
from pilomar_platesolve.mount import Correction, SimulatedMount
from pilomar_platesolve.sim import SimSolver, SimSource, SimWorld

SITE = Site(35.47, -97.52)
WHEN = datetime(2026, 11, 28, 2, 0, tzinfo=timezone.utc)


class Recorder(SimulatedMount):
    pass


class TestGearSlackSimulation(unittest.TestCase):
    def test_dead_band(self):
        m = SimulatedMount(DEFAULTS["mount"], backlash_az_deg=0.6)
        spd = DEFAULTS["mount"]["steps_per_degree_az"]
        m.apply(Correction(1, 0, round(spd), 0))      # same direction: full move
        self.assertAlmostEqual(m.tune_az, 1.0, places=2)
        m.apply(Correction(-1, 0, -round(spd), 0))    # reversal: loses 0.6
        self.assertAlmostEqual(m.tune_az, 0.6, places=2)


class TestTuneHelper(unittest.TestCase):
    def cfg(self, d, b=0.6):
        return _merge(DEFAULTS, {"data_dir": d, "mount": {"backlash_az_deg": b}})

    def test_adds_slack_only_on_reversal(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = self.cfg(d)
            m = SimulatedMount(cfg["mount"], backlash_az_deg=0.6)
            st = PointingState(None)
            st.dir_az = 1
            tune(m, m.to_steps(0.5, 0), st, cfg, say=lambda *a: None)
            self.assertEqual(m.history[-1].az_steps, m.to_steps(0.5, 0).az_steps)
            tune(m, m.to_steps(-0.5, 0), st, cfg, say=lambda *a: None)
            self.assertEqual(m.history[-1].az_steps, m.to_steps(-1.1, 0).az_steps)
            # camera came back exactly; ledger counts only the intended moves
            self.assertAlmostEqual(m.tune_az, 0.0, places=2)
            self.assertAlmostEqual(st.tune_az, 0.0, places=6)
            self.assertEqual(st.dir_az, -1)

    def test_measured_file_wins(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = self.cfg(d, 0.1)
            self.assertEqual(backlash_settings(cfg), (0.1, 0.0))
            save_backlash(d, {"az_deg": 0.7}, 2.0)
            self.assertEqual(backlash_settings(cfg), (0.7, 0.0))
            save_backlash(d, {"alt_deg": 0.2}, 2.0)          # keeps az
            self.assertEqual(backlash_settings(cfg), (0.7, 0.2))


class TestMeasure(unittest.TestCase):
    def test_measures_simulated_slack(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _merge(DEFAULTS, {"data_dir": d})
            target = Catalog().resolve("m15")
            m = SimulatedMount(cfg["mount"], backlash_az_deg=0.7, backlash_alt_deg=0.25)
            world = SimWorld(target, SITE, WHEN, m, seconds_per_picture=0, noise_deg=0.003)
            st = PointingState(None)
            res = measure_backlash(cfg=cfg, site=SITE, source=SimSource(world), solver=SimSolver(world),
                                   mount=m, state=st, say=lambda *a: None)
            self.assertAlmostEqual(res["az_deg"], 0.7, delta=0.03)
            self.assertAlmostEqual(res["alt_deg"], 0.25, delta=0.03)
            # camera returned to where it started, ledger matches reality
            self.assertAlmostEqual(m.tune_az, st.tune_az, delta=0.02)
            self.assertAlmostEqual(m.tune_alt, st.tune_alt, delta=0.02)


class TestCentringWithSlack(unittest.TestCase):
    def run_center(self, comp):
        with tempfile.TemporaryDirectory() as d:
            cfg = _merge(DEFAULTS, {"data_dir": d, "mount": {"backlash_az_deg": comp},
                                    "centering": {"tolerance_deg": 0.05}})
            target = Catalog().resolve("m15")
            m = SimulatedMount(cfg["mount"], err_az_deg=1.2, err_alt_deg=0.4, backlash_az_deg=0.7)
            st = PointingState(None)
            st.dir_az = 1
            world = SimWorld(target, SITE, WHEN, m, noise_deg=0.003)
            r = center_target(target, cfg=cfg, site=SITE, source=SimSource(world),
                              solver=SimSolver(world), mount=m, verbose=False,
                              sleep=lambda s: None, state=st)
            return r

    def test_compensation_saves_pictures(self):
        without, with_ = self.run_center(0.0), self.run_center(0.7)
        self.assertTrue(with_.success)
        self.assertLess(len(with_.iterations), len(without.iterations))


if __name__ == "__main__":
    unittest.main()
