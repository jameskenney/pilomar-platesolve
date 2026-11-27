"""Ways to apply a pointing correction to Pi-lomar.

Pi-lomar already has exactly the right tool for this: **Motor tools -> Tune
azimuth / altitude position**. A Tune move turns the motor by a number of
steps *without* changing Pi-lomar's idea of where it is pointing, and Pi-lomar's
own optical drift tracker uses the same function to keep targets centred.
So a Tune correction is remembered while Pi-lomar keeps tracking the target,
and no Pi-lomar code needs changing.

Back ends:
* ``AdvisorMount``   -- tells you the steps to type (default, zero risk).
* ``TmuxMount``      -- types them into a Pi-lomar running inside tmux.
* ``SimulatedMount`` -- no hardware, for tests and demos.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass


@dataclass
class Correction:
    d_az_deg: float
    d_alt_deg: float
    az_steps: int
    alt_steps: int


class Mount:
    name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def to_steps(self, d_az: float, d_alt: float) -> Correction:
        c = self.cfg
        az = int(round(d_az * float(c["steps_per_degree_az"]) * int(c.get("az_sign", 1))))
        alt = int(round(d_alt * float(c["steps_per_degree_alt"]) * int(c.get("alt_sign", 1))))
        return Correction(d_az, d_alt, az, alt)

    def apply(self, corr: Correction) -> bool:
        """Apply a correction. Return False if the user aborted."""
        raise NotImplementedError

    def goto(self, target) -> bool:
        """Have Pi-lomar slew to a target. Return False if the user aborted."""
        print(f"\n  >>> In Pi-lomar: select target '{target.id}' and GOTO it (main menu 4).")
        if not sys.stdin.isatty():
            return True
        return input("  Press Enter once it has arrived (or 'q' to stop): ").strip().lower() != "q"


class AdvisorMount(Mount):
    name = "advisor"

    def __init__(self, cfg: dict, interactive: bool = True):
        super().__init__(cfg)
        self.interactive = interactive and sys.stdin.isatty()

    def apply(self, corr: Correction) -> bool:
        print("\n  >>> In Pi-lomar: Motor tools (21)")
        if corr.az_steps:
            print(f"      Tune azimuth position  (4): enter {corr.az_steps:+d}  then 'x'"
                  f"   [{corr.d_az_deg:+.3f}°]")
        if corr.alt_steps:
            print(f"      Tune altitude position (5): enter {corr.alt_steps:+d}  then 'x'"
                  f"   [{corr.d_alt_deg:+.3f}°]")
        if not self.interactive:
            return True
        ans = input("  Press Enter when done (or 'q' to stop): ").strip().lower()
        return ans != "q"


class TmuxMount(Mount):
    """Drive Pi-lomar's menus by sending keystrokes to its tmux pane.

    Pi-lomar has no remote-control interface, but it is an ordinary terminal
    program, so typing into it from outside is the least invasive option.
    Start Pi-lomar with:  tmux new -s pilomar 'cd /home/pi/pilomar/src && ./pilomar'
    """

    name = "tmux"

    def __init__(self, cfg: dict, dry_run: bool = False):
        super().__init__(cfg)
        self.t = cfg.get("tmux", {})
        self.dry_run = dry_run

    def available(self) -> bool:
        if not shutil.which("tmux"):
            return False
        r = subprocess.run(["tmux", "has-session", "-t", self.t.get("session", "pilomar")],
                           capture_output=True)
        return r.returncode == 0

    def keys_for(self, corr: Correction) -> list[str]:
        out = []
        for k in self.t.get("tune_keys", []):
            out.append(str(k).replace("{az_steps}", str(corr.az_steps))
                       .replace("{alt_steps}", str(corr.alt_steps)))
        return out

    def send(self, keys: list[str]):
        session = self.t.get("session", "pilomar")
        delay = float(self.t.get("key_delay_s", 0.8))
        for k in keys:
            if self.dry_run:
                print(f"    [dry-run] tmux send-keys -t {session} {k}")
                continue
            if k in ("Enter", "Escape", "Tab", "BSpace"):
                subprocess.run(["tmux", "send-keys", "-t", session, k], check=True)
            else:
                subprocess.run(["tmux", "send-keys", "-t", session, "-l", "--", k], check=True)
            time.sleep(delay)

    def goto(self, target) -> bool:
        keys = self.t.get("goto_keys") or []
        if not keys:
            return super().goto(target)
        print(f"  Sending GOTO {target.id}")
        self.send([str(k).replace("{target}", target.id) for k in keys])
        wait = float(self.t.get("goto_wait_s", 60))
        if not self.dry_run:
            time.sleep(wait)
        return True

    def trigger_capture(self):
        keys = self.t.get("capture_keys") or []
        if keys:
            self.send([str(k) for k in keys])

    # ------------------------------------------------------------------
    # Screen-aware ("verified") mode: read Pi-lomar's screen through tmux and
    # wait for each prompt before typing the next key. Typing ahead on a timer
    # loses keys when Pi-lomar is busy moving a motor (seen on real hardware).
    # ------------------------------------------------------------------
    HEADERS = {"main": "Pilomar main menu", "motor": "Motor tools menu", "select": "Select target"}

    def _screen(self) -> list[str]:
        out = subprocess.run(["tmux", "capture-pane", "-p", "-J", "-t", self.t.get("session", "pilomar"),
                              "-S", "-2000"], capture_output=True, text=True, check=True).stdout
        lines = [ln.rstrip() for ln in out.splitlines()]
        while lines and not lines[-1]:
            lines.pop()
        return lines

    def _state(self) -> tuple[str, list[str]]:
        lines = self._screen()
        last = lines[-1] if lines else ""
        if "steps to move" in last:
            return "tune_prompt", lines
        if re.search(r"option\s*:\s*$", last, re.I):
            best, where = "unknown_menu", -1
            # A menu heading is a line on its own ("Select target" also appears
            # inside the main menu as "1 Select target", which must not count).
            for name, header in self.HEADERS.items():
                for i in range(len(lines) - 1, -1, -1):
                    if lines[i].strip() == header:
                        if i > where:
                            best, where = name, i
                        break
            return best, lines
        return "busy", lines

    def _type(self, text: str):
        session = self.t.get("session", "pilomar")
        if text:
            subprocess.run(["tmux", "send-keys", "-t", session, "-l", "--", text], check=True)
        subprocess.run(["tmux", "send-keys", "-t", session, "Enter"], check=True)

    def _wait(self, want: str, timeout: float, min_prompts: int | None = None) -> list[str]:
        """Wait until Pi-lomar shows the wanted prompt (and, for Tune, a new one)."""
        deadline = time.monotonic() + timeout
        poll = float(self.t.get("poll_s", 0.3))
        state, lines = "busy", []
        while time.monotonic() < deadline:
            time.sleep(poll)
            state, lines = self._state()
            if state == want and (min_prompts is None or
                                  sum("steps to move" in ln for ln in lines) >= min_prompts):
                time.sleep(float(self.t.get("settle_s", 0.3)))
                return lines
        last = lines[-1] if lines else ""
        raise RuntimeError(f"Pi-lomar did not reach '{want}' in {timeout:.0f} s "
                           f"(now '{state}', last line: {last!r}). Check it with: "
                           f"tmux attach -t {self.t.get('session', 'pilomar')}")

    def ensure_main_menu(self):
        """Back out of Tune / Motor tools / Select target to the main menu.

        Never types 'x' at the main menu itself (that would exit Pi-lomar).
        """
        for _ in range(5):
            state, lines = self._state()
            if state == "main":
                return
            if state == "busy":
                self._wait_not_busy(30)
                continue
            if state in ("tune_prompt", "motor", "select"):
                self._type("x")
                time.sleep(float(self.t.get("settle_s", 0.3)) + 0.5)
                continue
            last = lines[-1] if lines else ""
            raise RuntimeError("Pi-lomar is at a screen this add-on doesn't recognise "
                               f"(last line: {last!r}); return it to the main menu by hand.")
        raise RuntimeError("could not get Pi-lomar back to its main menu")

    def _wait_not_busy(self, timeout: float):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._state()[0] != "busy":
                return
            time.sleep(0.5)

    def _tune_axis(self, option: str, steps: int):
        before = sum("steps to move" in ln for ln in self._screen())
        self._type(option)
        self._wait("tune_prompt", 20, before + 1)
        self._type(str(steps))
        move_s = abs(steps) / float(self.t.get("steps_per_second_estimate", 300)) + 30
        self._wait("tune_prompt", move_s, before + 2)
        self._type("x")
        self._wait("motor", 20)

    def apply_verified(self, corr: Correction):
        self.ensure_main_menu()
        self._type(str(self.t.get("motor_tools_option", "21")))
        self._wait("motor", 20)
        if corr.az_steps:
            self._tune_axis(str(self.t.get("tune_az_option", "4")), corr.az_steps)
        if corr.alt_steps:
            self._tune_axis(str(self.t.get("tune_alt_option", "5")), corr.alt_steps)
        self._type("x")
        self._wait("main", 20)

    def apply(self, corr: Correction) -> bool:
        if not corr.az_steps and not corr.alt_steps:
            return True
        print(f"  Sending Tune: azimuth {corr.az_steps:+d} steps, altitude {corr.alt_steps:+d} steps")
        mode = self.t.get("mode", "verified")
        if self.dry_run:
            if mode == "verified":
                print("    [dry-run] back to main menu, 21 (Motor tools)"
                      + (f", 4 then {corr.az_steps}, x" if corr.az_steps else "")
                      + (f", 5 then {corr.alt_steps}, x" if corr.alt_steps else "")
                      + ", x (main menu) - waiting for each prompt")
            else:
                self.send(self.keys_for(corr))
            return True
        if not self.available():
            raise RuntimeError("tmux session not found; start Pi-lomar inside tmux "
                               f"(session name '{self.t.get('session', 'pilomar')}')")
        if mode == "verified":
            self.apply_verified(corr)
        else:
            self.send(self.keys_for(corr))
        return True


class SimulatedMount(Mount):
    """Pretend mount. Its errors can be a fixed alt/az offset (err_*) and/or a
    full mount geometry (a PointingModel of the *true* tilt, offsets etc.)."""

    name = "simulated"

    def __init__(self, cfg: dict, err_az_deg: float = 0.0, err_alt_deg: float = 0.0,
                 lost_motion_fraction: float = 0.0,
                 true_az_sign: int | None = None, true_alt_sign: int | None = None,
                 geometry=None):
        """``true_*_sign`` is how the hardware really responds to +steps; by
        default it matches the config (i.e. the config is right).
        ``lost_motion_fraction`` imitates backlash eating part of each move.
        """
        super().__init__(cfg)
        self.base_az = err_az_deg
        self.base_alt = err_alt_deg
        self.geometry = geometry
        self.lost = lost_motion_fraction
        self.true_az_sign = true_az_sign if true_az_sign is not None else int(cfg.get("az_sign", 1))
        self.true_alt_sign = true_alt_sign if true_alt_sign is not None else int(cfg.get("alt_sign", 1))
        self.tune_az = 0.0   # physical Tune motion so far, degrees
        self.tune_alt = 0.0
        self.history: list[Correction] = []
        self.gotos: list = []

    # Remaining fixed error (for the simple constant-offset case).
    @property
    def err_az(self) -> float:
        return self.base_az + self.tune_az

    @property
    def err_alt(self) -> float:
        return self.base_alt + self.tune_alt

    def actual_altaz(self, logical_alt: float, logical_az: float) -> tuple[float, float]:
        """Where the camera really points when Pi-lomar believes (alt, az)."""
        m_az = logical_az + self.tune_az
        m_alt = logical_alt + self.tune_alt
        d_az, d_alt = self.geometry.delta(m_az, m_alt) if self.geometry else (0.0, 0.0)
        return m_alt + d_alt + self.base_alt, (m_az + d_az + self.base_az) % 360.0

    def goto(self, target) -> bool:
        self.gotos.append(target)
        return True

    def apply(self, corr: Correction) -> bool:
        self.history.append(corr)
        moved_az = corr.az_steps / float(self.cfg["steps_per_degree_az"]) * self.true_az_sign
        moved_alt = corr.alt_steps / float(self.cfg["steps_per_degree_alt"]) * self.true_alt_sign
        self.tune_az += moved_az * (1 - self.lost)
        self.tune_alt += moved_alt * (1 - self.lost)
        return True
