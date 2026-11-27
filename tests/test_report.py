import tempfile
import time
import unittest
from datetime import datetime, timezone

from pilomar_platesolve import astro
from pilomar_platesolve.align import choose_alignment_targets, run_alignment
from pilomar_platesolve.catalog import Catalog
from pilomar_platesolve.centering import Logbook, center_target
from pilomar_platesolve.config import DEFAULTS, _merge
from pilomar_platesolve.model import PointingModel, PointingState
from pilomar_platesolve.mount import SimulatedMount
from pilomar_platesolve.report import render
from pilomar_platesolve.sim import SimSolver, SimSource, SimWorld

SITE = astro.Site(35.47, -97.52)
T0 = datetime(2026, 11, 27, 4, 0, tzinfo=timezone.utc)


class TestReport(unittest.TestCase):
    def test_report_from_logged_runs(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _merge(DEFAULTS, {"data_dir": d, "pilomar_root": d})
            truth = PointingModel(params={"IA": 1.0, "IE": -0.5, "AN": 0.4, "AW": -0.3})

            # An alignment run, logged the way `pilomar-ps align` logs it.
            log = Logbook(d)
            mount = SimulatedMount(cfg["mount"], geometry=truth)
            pts = choose_alignment_targets(Catalog().all(), SITE, T0, 6)
            world = SimWorld(pts[0], SITE, T0, mount)
            log.event("align_start", targets=[t.id for t in pts], mount="simulated")
            model, _ = run_alignment(pts, cfg=cfg, site=SITE, source=SimSource(world),
                                     solver=SimSolver(world), mount=mount,
                                     state=PointingState(None), log=log, verbose=False)
            log.event("model_fitted", model=model.to_dict())

            # Two centring runs, logged the way `pilomar-ps center` logs them.
            time.sleep(1.1)  # separate session files
            for name in ("m31", "m45"):
                log = Logbook(d)
                tgt = Catalog().resolve(name)
                m = SimulatedMount(cfg["mount"], 1.5, -0.8)
                w = SimWorld(tgt, SITE, T0, m)
                log.event("start", command="center", target=name, mount="simulated")
                res = center_target(tgt, cfg=cfg, site=SITE, source=SimSource(w), solver=SimSolver(w),
                                    mount=m, log=log, verbose=False, sleep=lambda s: None)
                log.event("end", success=res.success, reason=res.reason, final_error=res.final_error)
                time.sleep(1.1)

            text = render(cfg)
            self.assertIn("Plate solving:", text)
            self.assertIn("runs: 2, centred: 2", text)
            self.assertIn("6 pictures", text)
            self.assertRegex(text, r"base tilt 0\.(4[6-9]|5[0-4])°")
            self.assertIn("solver: simulated", text)
            # Nothing personal: no coordinates, no paths.
            self.assertNotIn("35.47", text)
            self.assertNotIn("97.52", text)
            self.assertNotIn(d, text)

    def test_empty_report(self):
        with tempfile.TemporaryDirectory() as d:
            text = render(_merge(DEFAULTS, {"data_dir": d, "pilomar_root": d}))
            self.assertIn("no runs yet", text)
            self.assertIn("no alignments yet", text)


if __name__ == "__main__":
    unittest.main()
