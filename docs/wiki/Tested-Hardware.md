# Tested hardware

The reference build used to develop and test the add-on. Other Pi-lomar builds
should work: set `optics` and `mount.steps_per_degree_*` in `config.json` to match.

| Part | Reference build |
|---|---|
| Computer | Raspberry Pi 5, 8 GB RAM, 64 GB microSD |
| Operating system | Raspberry Pi OS (Legacy, 64-bit), Debian Bookworm, Python 3.11 |
| Pi-lomar software | 1.3.0 ([Short-bus/pilomar](https://github.com/Short-bus/pilomar)) |
| Motor controller | Raspberry Pi Pico 2 running CircuitPython 10.3.2, following the [Pi-lomar TMC2209 + Pico 2 controller upgrade](https://www.instructables.com/Pi-lomar-TMC2209-Pico2-Motor-Controller-Upgrade/) |
| Controller board | Pi-lomar PCB 3.1.1, motor "Orientation" 1 on both axes |
| Motor drivers | 2 × BigTreeTech TMC2209 V1.3, 1/4 microstepping |
| Motors | 2 × StepperOnline 17HM19-2004S (0.9° per step) |
| Gearing | 60:1 worm, then 4:1 final drive (384,000 steps per turn) |
| Camera | Raspberry Pi HQ camera (IMX477), 16 mm C-mount lens at f/1.4 (measured 22.7° × 17.0°, 40.3″/px at 2028 px) |
| Plate solver | astrometry.net 0.93 from apt, 2MASS index files 11–19 |

## Results so far

| Test | Result |
|---|---|
| Solver on synthetic sky (`selftest`) | Solves in 1.5–2.1 s; centre within 2–14″, rotation within 0.02° |
| Real night pictures | Solves in 2.2–5.6 s (4 s exposures, gain 16, town sky) |
| Centring | M15 0.33° → 0.078° in 2 pictures; M31 0.56° → 0.030° in 4; M45 0.71° → 0.043° in 3 |
| GOTO through Pi-lomar | Landed at 120.007° / 15.006° for a 120° / 15° target |
| Startup alignment | 3 of 6 points solved (low ones failed); 1.19° → 0.27° rms |
| Annotated pictures | Labelled Mirach, M31, M32, M110, NGC 147/185/272 on a real Andromeda picture |
| Stacking | 60 × 4 s DNGs plus 20 darks in DeepSkyStacker 6.2.2 |
| Backlash measurement and compensation | Tested in simulation; night test pending |

If you test on a different build, please share `pilomar-ps report` in an
[issue](https://github.com/jameskenney/pilomar-platesolve/issues).
