import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from pilomar_platesolve.config import DEFAULTS, _merge
from pilomar_platesolve.mount import Correction, TmuxMount

HERE = Path(__file__).parent
SESSION = "pps_test_pilomar"


@unittest.skipUnless(shutil.which("tmux"), "tmux not installed")
class TestTmuxMount(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "fake.log"
        subprocess.run(["tmux", "kill-session", "-t", SESSION], capture_output=True)
        subprocess.run(["tmux", "new", "-d", "-s", SESSION, "-x", "160", "-y", "50",
                        f"python3 {HERE / 'fake_pilomar.py'} {self.log} 1.0"], check=True)
        time.sleep(0.8)

    def tearDown(self):
        subprocess.run(["tmux", "kill-session", "-t", SESSION], capture_output=True)
        self.tmp.cleanup()

    def mount(self, **tmux):
        cfg = _merge(DEFAULTS, {"mount": {"tmux": {"session": SESSION, "poll_s": 0.1,
                                                   "settle_s": 0.1, **tmux}}})
        return TmuxMount(cfg["mount"])

    def moves(self):
        return [ln for ln in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_verified_mode_survives_slow_moves(self):
        m = self.mount()
        m.apply(Correction(1, -1, 1500, -1500))   # each move takes 1.5 s in the fake
        m.apply(Correction(0, 0.5, 0, 533))
        self.assertEqual(self.moves(), ["TUNE Azimuth 1500", "TUNE Altitude -1500", "TUNE Altitude 533"])
        self.assertEqual(m._state()[0], "main")

    def test_recovers_when_left_in_motor_tools_or_tune(self):
        m = self.mount()
        subprocess.run(["tmux", "send-keys", "-t", SESSION, "21", "Enter"], check=True)
        time.sleep(0.5)
        subprocess.run(["tmux", "send-keys", "-t", SESSION, "4", "Enter"], check=True)
        time.sleep(0.5)
        self.assertEqual(m._state()[0], "tune_prompt")
        m.apply(Correction(0, 1, 0, 200))
        self.assertEqual(self.moves(), ["TUNE Altitude 200"])   # no stray azimuth move
        self.assertEqual(m._state()[0], "main")
        self.assertNotIn("EXIT", self.moves())

    def test_blind_mode_loses_keys_like_real_hardware(self):
        m = self.mount(mode="blind", key_delay_s=0.2)
        m.apply(Correction(0, 1, 0, 1500))
        time.sleep(2.5)
        self.assertEqual(self.moves(), ["TUNE Azimuth 0", "TUNE Altitude 1500"])
        self.assertNotEqual(m._state()[0], "main")   # the bug the verified mode fixes

    def test_never_exits_pilomar_from_main_menu(self):
        m = self.mount()
        self.assertEqual(m._state()[0], "main")   # "1 Select target" is not the Select menu
        m.ensure_main_menu()
        time.sleep(0.5)
        self.assertNotIn("EXIT", self.moves())


if __name__ == "__main__":
    unittest.main()
