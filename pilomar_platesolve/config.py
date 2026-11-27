"""Configuration: built-in defaults, overridden by ~/pilomar-platesolve/config.json."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

HOME_DIR = Path(os.environ.get("PILOMAR_PS_HOME", Path.home() / "pilomar-platesolve"))

DEFAULTS: dict = {
    # Where Pi-lomar lives. Only ever READ, never written.
    "pilomar_root": "/home/pi/pilomar",
    # Where this add-on keeps its logs, work files and solutions.
    "data_dir": str(HOME_DIR / "data"),

    # Observing site. null = read HomeLat/HomeLon from Pi-lomar's parameter file.
    "site": {"lat_deg": None, "lon_east_deg": None, "elevation_m": 0},

    # Raspberry Pi HQ camera (IMX477, 4056 x 3040 px of 1.55 um) + 16 mm lens.
    "optics": {"focal_length_mm": 16.0, "sensor_width_mm": 6.287, "sensor_height_mm": 4.712},

    "solver": {
        "backend": "astrometry",            # "astrometry" or "astap"
        "search_radius_deg": 15.0,          # how far from the hint to look
        "blind_retry": True,                # retry with no position hint if a hinted solve fails
        "astrometry": {"solve_field": "solve-field", "downsample": 2, "cpulimit_s": 60,
                       "extra_args": []},
        "astap": {"astap": "astap_cli", "downsample": 2, "timeout_s": 90,
                  "aspect_h_over_w": 0.75, "extra_args": []},
    },

    "capture": {
        # "rpicam"          : this tool takes the picture with rpicam-still
        # "pilomar-folder"  : wait for the next picture Pi-lomar saves
        "source": "pilomar-folder",
        "rpicam": {"exe": "rpicam-still", "exposure_s": 2.0, "gain": 8.0,
                   "width": 2028, "height": 1520, "extra_args": []},
        "folder": {"glob": "data/campaign_*/**/*.jpg", "timeout_s": 180, "settle_s": 1.0},
    },

    "mount": {
        # "advisor"   : prints the Tune steps for you to type into Pi-lomar (safe default)
        # "tmux"      : types them into Pi-lomar for you (experimental, see docs)
        # "simulated" : no hardware, for testing
        "backend": "advisor",
        # With 1/4 microstepping one turn is 384000 steps (see build log),
        # i.e. 1066.67 steps per degree. Pi-lomar prints the exact figure on
        # the Tune screen; copy it here if yours differs.
        "steps_per_degree_az": 384000 / 360.0,
        "steps_per_degree_alt": 384000 / 360.0,
        # +1 means positive Tune steps increase azimuth (clockwise seen from
        # above) / raise the camera, which is how Pi-lomar is set up when its
        # direction check passes. Flip to -1 if centring runs away.
        "az_sign": 1,
        "alt_sign": 1,
        "tmux": {
            "session": "pilomar",
            "key_delay_s": 0.8,
            # UNVERIFIED menu paths: check them by hand once and adjust.
            # {az_steps} / {alt_steps} are replaced with integers.
            "tune_keys": ["21", "Enter", "4", "Enter", "{az_steps}", "Enter", "x", "Enter",
                          "5", "Enter", "{alt_steps}", "Enter", "x", "Enter", "x", "Enter"],
            "capture_keys": [],
            # Optional, UNVERIFIED: keys to select a target and GOTO it, e.g.
            # ["1", "Enter", "3", "Enter", "{target}", "Enter", "4", "Enter"].
            # Empty = you do the GOTO in Pi-lomar when asked.
            "goto_keys": [],
            "goto_wait_s": 60,       # time allowed for a slew before the next step
        },
    },

    "centering": {
        "tolerance_deg": 0.10,       # stop when the target is this close to centre
        "max_iterations": 6,
        "gain": 0.9,                 # apply 90% of the error: avoids overshoot from backlash
        "max_correction_deg": 10.0,  # never move the view more than this on the sky in one step
        "max_azimuth_turn_deg": 30.0,  # and never turn azimuth more than this (zenith safety)
        "min_correction_deg": 0.02,  # ignore smaller corrections on an axis
        "settle_s": 3.0,             # wait after a move before the next picture
        "zenith_warn_alt_deg": 80.0,
    },

    "suggest": {"min_alt_deg": 25.0, "max_mag": 9.0, "moon_min_sep_deg": 25.0, "limit": 12},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def config_path() -> Path:
    return Path(os.environ.get("PILOMAR_PS_CONFIG", HOME_DIR / "config.json"))


def load_config(path: str | Path | None = None) -> dict:
    p = Path(path) if path else config_path()
    user = {}
    if p.exists():
        with open(p, encoding="utf-8") as f:
            user = json.load(f)
        user.pop("_comment", None)
    cfg = _merge(DEFAULTS, user)
    cfg["_config_file"] = str(p) if p.exists() else None
    cfg["data_dir"] = str(Path(os.path.expanduser(cfg["data_dir"])))
    return cfg
