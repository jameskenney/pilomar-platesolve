import json
import random
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pilomar_platesolve import astro
from pilomar_platesolve.align import choose_alignment_targets, samples_from_log
from pilomar_platesolve.catalog import Catalog
from pilomar_platesolve.centering import Logbook, center_target
from pilomar_platesolve.config import DEFAULTS, _merge
from pilomar_platesolve.model import (PointingModel, PointingState, Sample, choose_terms,
                                      fit_model, predicted_correction)
from pilomar_platesolve.mount import SimulatedMount
from pilomar_platesolve.sim import SimSolver, SimSource, SimWorld, simulate_alignment

SITE = astro.Site(35.47, -97.52)
T0 = datetime(2026, 11, 27, 4, 0, tzinfo=timezone.utc)
TRUTH = {"IA": 1.2, "IE": -0.6, "AN": 0.5, "AW": -0.7, "CA": 0.3}


def synthetic_samples(truth, n=8, noise=0.0, seed=1):
    rng = random.Random(seed)
    model = PointingModel(params=dict(truth))
    out = []
    for i in range(n):
        az, alt = rng.uniform(0, 360), rng.uniform(20, 75)
        a_az, a_alt = model.actual_for_mount(az, alt)
        out.append(Sample(az, alt, a_az + rng.gauss(0, noise), a_alt + rng.gauss(0, noise), f"p{i}"))
    return out


class TestModelFit(unittest.TestCase):
    def test_recovers_true_parameters(self):
        m = fit_model(synthetic_samples(TRUTH, 10), ["IA", "IE", "AN", "AW", "CA"])
        for k, v in TRUTH.items():
            self.assertAlmostEqual(m.params[k], v, places=6)
        self.assertLess(m.rms_after_deg, 1e-6)
        self.assertGreater(m.rms_before_deg, 0.5)

    def test_noise_tolerated(self):
        m = fit_model(synthetic_samples(TRUTH, 12, noise=0.02))
        for k, v in TRUTH.items():
            self.assertAlmostEqual(m.params[k], v, delta=0.1)
        self.assertLess(m.rms_after_deg, 0.05)

    def test_terms_follow_sample_count(self):
        s = synthetic_samples(TRUTH, 6)
        self.assertEqual(choose_terms(s[:2]), ["IA", "IE"])
        self.assertEqual(choose_terms(s[:3]), ["IA", "IE", "AN", "AW"])
        self.assertIn("CA", choose_terms(s[:5]))
        with self.assertRaises(ValueError):
            choose_terms(s[:1])

    def test_degenerate_points_rejected(self):
        same = [Sample(100, 40, 101, 40), Sample(100, 40, 101, 40), Sample(100, 40, 101, 40)]
        with self.assertRaises(ValueError):
            fit_model(same, ["IA", "IE", "AN", "AW"])

    def test_inverse_and_wraparound(self):
        m = PointingModel(params=dict(TRUTH))
        for az, alt in [(0.2, 30), (359.8, 50), (180, 70), (90, 25)]:
            m_az, m_alt = m.mount_for_actual(az, alt)
            a_az, a_alt = m.actual_for_mount(m_az, m_alt)
            self.assertAlmostEqual(astro.wrap180(a_az - az), 0, places=6)
            self.assertAlmostEqual(a_alt, alt, places=6)

    def test_save_load(self):
        with tempfile.TemporaryDirectory() as d:
            m = fit_model(synthetic_samples(TRUTH, 8))
            m.save(Path(d) / "m.json")
            m2 = PointingModel.load(Path(d) / "m.json")
            self.assertEqual(m.params, m2.params)
            self.assertIsNone(PointingModel.load(Path(d) / "missing.json"))


class TestState(unittest.TestCase):
    def test_ledger_persists(self):
        with tempfile.TemporaryDirectory() as d:
            s = PointingState(Path(d) / "s.json")
            s.add(0.5, -0.25)
            s.add(0.1, 0.0)
            s2 = PointingState(Path(d) / "s.json")
            self.assertAlmostEqual(s2.tune_az, 0.6)
            self.assertEqual(s2.mount_position(359.8, 30), ((359.8 + 0.6) % 360, 29.75))
            s2.reset("e1")
            self.assertEqual(PointingState(Path(d) / "s.json").epoch, "e1")

    def test_correction_accounts_for_previous_tunes(self):
        m = PointingModel(params={"IA": 1.0, "IE": 0.0})
        s = PointingState(None)
        d_az, _ = predicted_correction(m, s, 100, 40)
        self.assertAlmostEqual(d_az, -1.0, places=6)
        s.add(d_az, 0)
        d_az, _ = predicted_correction(m, s, 200, 40)  # Tune already in place
        self.assertAlmostEqual(d_az, 0.0, places=6)


class TestAlignment(unittest.TestCase):
    def test_targets_spread_out(self):
        pts = choose_alignment_targets(Catalog().all(), SITE, T0, 6)
        self.assertGreaterEqual(len(pts), 4)
        azs = sorted(astro.j2000_to_altaz(t.ra_deg, t.dec_deg, SITE, T0)[1] for t in pts)
        self.assertGreater(azs[-1] - azs[0], 150)

    def test_targets_respect_azimuth_and_altitude_limits(self):
        from pilomar_platesolve.align import az_in_range
        from pilomar_platesolve.catalog import Target
        grid = [Target(f"g{i}", "", ra, dec) for i, (ra, dec) in enumerate(
            (ra, dec) for ra in range(0, 360, 15) for dec in range(-30, 90, 10))]
        pts = choose_alignment_targets(grid, SITE, T0, 6, min_alt=35, az_range=(90, 270))
        self.assertGreaterEqual(len(pts), 3)
        azs = []
        for t in pts:
            alt, az = astro.j2000_to_altaz(t.ra_deg, t.dec_deg, SITE, T0)
            self.assertGreaterEqual(alt, 35)
            self.assertTrue(90 <= az <= 270)
            azs.append(az)
        self.assertEqual(azs, sorted(azs))          # one sweep
        self.assertTrue(az_in_range(10, (270, 90)) and not az_in_range(180, (270, 90)))

    def test_end_to_end_simulated_alignment(self):
        cfg = _merge(DEFAULTS, {})
        model, results = simulate_alignment(cfg, SITE, T0, PointingModel(params=dict(TRUTH)),
                                            Catalog().all(), verbose=False)
        self.assertLess(model.rms_after_deg, 0.05)
        for _, before, after in results:
            self.assertGreater(before, 0.3)
            self.assertLess(after, 0.1)

    def test_model_makes_centering_faster(self):
        cfg = _merge(DEFAULTS, {})
        truth = PointingModel(params=dict(TRUTH))
        fitted, _ = simulate_alignment(cfg, SITE, T0, truth, Catalog().all(), verbose=False)
        counts = {}
        for use in (False, True):
            tgt = Catalog().resolve("m33")
            mount = SimulatedMount(cfg["mount"], geometry=truth)
            world = SimWorld(tgt, SITE, T0, mount)
            res = center_target(tgt, cfg=cfg, site=SITE, source=SimSource(world),
                                solver=SimSolver(world), mount=mount, verbose=False,
                                sleep=lambda s: None, model=fitted if use else None,
                                state=PointingState(None), when=T0)
            self.assertTrue(res.success)
            counts[use] = len(res.iterations)
        self.assertEqual(counts[True], 1)       # already centred on the first picture
        self.assertGreater(counts[False], 1)

    def test_refit_from_log(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _merge(DEFAULTS, {})
            truth = PointingModel(params=dict(TRUTH))
            log = Logbook(d)
            state = PointingState(Path(d) / "state.json")
            state.reset("epoch-1")
            for name in ["m31", "m45", "m15", "ngc253", "m35", "ngc7000"]:
                tgt = Catalog().resolve(name)
                mount = SimulatedMount(cfg["mount"], geometry=truth)
                mount.tune_az, mount.tune_alt = state.tune_az, state.tune_alt
                world = SimWorld(tgt, SITE, T0, mount, noise_deg=0.0)
                center_target(tgt, cfg=cfg, site=SITE, source=SimSource(world),
                              solver=SimSolver(world), mount=mount, log=log, verbose=False,
                              sleep=lambda s: None, state=state)
            samples = samples_from_log(log.csv, "epoch-1")
            self.assertGreaterEqual(len(samples), 6)
            m = fit_model(samples)
            for k in ("IA", "IE", "AN", "AW"):
                self.assertAlmostEqual(m.params[k], TRUTH[k], delta=0.05)

    def test_old_log_header_is_moved_aside(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "pointing_log.csv").write_text("utc,target\n")
            cfg = _merge(DEFAULTS, {})
            tgt = Catalog().resolve("m31")
            mount = SimulatedMount(cfg["mount"], 0.5, 0.5)
            world = SimWorld(tgt, SITE, T0, mount)
            log = Logbook(d)
            center_target(tgt, cfg=cfg, site=SITE, source=SimSource(world), solver=SimSolver(world),
                          mount=mount, log=log, verbose=False, sleep=lambda s: None)
            self.assertTrue((Path(d) / "pointing_log_old.csv").exists())
            self.assertIn("mount_az", log.csv.read_text().splitlines()[0])


if __name__ == "__main__":
    unittest.main()
