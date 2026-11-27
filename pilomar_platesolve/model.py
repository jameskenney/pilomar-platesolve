"""Pointing model: the mount's fixed, repeatable errors, measured from the stars.

Why not just measure latitude/longitude from the stars? Because for an alt-az
mount a base tilted by 1° is geometrically identical to a level base ~110 km
away. Star pictures can only measure "where the mount's vertical axis points",
which mixes location and levelling. So we keep the map location (accurate to
~0.01°) and fit the mount's own errors instead, exactly as commercial GoTo
mounts do with a "3-star" or plate-solve alignment.

Terms (all in degrees, "actual minus mount", standard TPOINT-style names):

    IA    azimuth index error      home is not exactly where Pi-lomar thinks
    IE    altitude index error     "level" is not exactly level
    AN    base tilt, north-south   (together AN/AW = the base is not level)
    AW    base tilt, east-west
    CA    collimation              camera points slightly sideways of the arm
    NPAE  axes not perpendicular   altitude axis not square to azimuth axis

Error equations, derived from rotating the pointing vector by a small tilt
(the tilt couples into azimuth as tan(alt), which is why azimuth corrections
grow near the zenith):

    d_alt         = IE - AN*cos(A) - AW*sin(A)
    d_az * cos(E) = IA*cos(E) + CA + NPAE*sin(E) - sin(E)*(AN*sin(A) - AW*cos(A))

"Mount" coordinates are Pi-lomar's logical alt/az plus any Tune moves this
add-on has applied since the model was fitted (kept in PointingState).
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .astro import DEG, wrap180, wrap360

ALL_TERMS = ["IA", "IE", "AN", "AW", "CA", "NPAE"]


@dataclass
class Sample:
    """One plate solve: where the mount thought it pointed vs where it really did."""

    mount_az: float
    mount_alt: float
    actual_az: float
    actual_alt: float
    label: str = ""

    @property
    def d_az(self) -> float:
        return wrap180(self.actual_az - self.mount_az)

    @property
    def d_alt(self) -> float:
        return self.actual_alt - self.mount_alt


def _rows(az: float, alt: float, terms: list[str]):
    """Design-matrix rows (azimuth row is scaled by cos(alt): on-sky units)."""
    a, e = az * DEG, alt * DEG
    ce, se = math.cos(e), math.sin(e)
    az_row = {"IA": ce, "IE": 0.0, "AN": -se * math.sin(a), "AW": se * math.cos(a),
              "CA": 1.0, "NPAE": se}
    alt_row = {"IA": 0.0, "IE": 1.0, "AN": -math.cos(a), "AW": -math.sin(a),
               "CA": 0.0, "NPAE": 0.0}
    return [az_row[t] for t in terms], [alt_row[t] for t in terms]


def _solve_linear(m: list[list[float]], v: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting (no numpy on purpose)."""
    n = len(v)
    a = [row[:] + [v[i]] for i, row in enumerate(m)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(a[r][c]))
        if abs(a[p][c]) < 1e-12:
            raise ValueError("pointing model is under-determined: spread the "
                             "alignment points more widely across the sky")
        a[c], a[p] = a[p], a[c]
        for r in range(c + 1, n):
            f = a[r][c] / a[c][c]
            for k in range(c, n + 1):
                a[r][k] -= f * a[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (a[r][n] - sum(a[r][k] * x[k] for k in range(r + 1, n))) / a[r][r]
    return x


def choose_terms(samples: list[Sample]) -> list[str]:
    """Fit only what the data can support."""
    n = len(samples)
    if n < 2:
        raise ValueError("need at least 2 solved pictures (3 or more recommended)")
    if n < 3:
        return ["IA", "IE"]
    if n < 4:
        return ["IA", "IE", "AN", "AW"]
    alts = [s.mount_alt for s in samples]
    if n >= 6 and max(alts) - min(alts) >= 20:
        return list(ALL_TERMS)
    return ["IA", "IE", "AN", "AW", "CA"]


@dataclass
class PointingModel:
    params: dict = field(default_factory=dict)
    fitted_at: str = ""
    n_samples: int = 0
    rms_before_deg: float = 0.0
    rms_after_deg: float = 0.0
    residuals: list = field(default_factory=list)
    epoch: str = ""

    # --- prediction --------------------------------------------------------
    def delta(self, mount_az: float, mount_alt: float) -> tuple[float, float]:
        """Predicted (d_az, d_alt) = actual - mount, at a mount position."""
        terms = list(self.params)
        if not terms:
            return 0.0, 0.0
        az_row, alt_row = _rows(mount_az, mount_alt, terms)
        x = [self.params[t] for t in terms]
        ce = max(math.cos(mount_alt * DEG), 0.05)
        d_az = sum(r * p for r, p in zip(az_row, x)) / ce
        d_alt = sum(r * p for r, p in zip(alt_row, x))
        return d_az, d_alt

    def actual_for_mount(self, mount_az: float, mount_alt: float) -> tuple[float, float]:
        d_az, d_alt = self.delta(mount_az, mount_alt)
        return wrap360(mount_az + d_az), mount_alt + d_alt

    def mount_for_actual(self, az: float, alt: float) -> tuple[float, float]:
        """Where the mount must be so the camera really points at (az, alt)."""
        m_az, m_alt = az, alt
        for _ in range(8):
            d_az, d_alt = self.delta(m_az, m_alt)
            m_az, m_alt = wrap360(az - d_az), alt - d_alt
        return m_az, m_alt

    # --- persistence ---------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "PointingModel | None":
        p = Path(path)
        if not p.exists():
            return None
        return cls(**json.loads(p.read_text()))

    def describe(self) -> str:
        names = {"IA": "azimuth index (home offset)", "IE": "altitude index (level offset)",
                 "AN": "base tilt north-south", "AW": "base tilt east-west",
                 "CA": "camera sideways (collimation)", "NPAE": "axes not square"}
        lines = [f"  {t:5} {v:+8.3f}°  {names[t]}" for t, v in self.params.items()]
        if "AN" in self.params and "AW" in self.params:
            an, aw = self.params["AN"], self.params["AW"]
            tilt = math.hypot(an, aw)
            # The mount's vertical axis leans toward this azimuth.
            toward = wrap360(math.degrees(math.atan2(aw, an)))
            lines.append(f"        base tilt {tilt:.2f}°, vertical axis leaning toward azimuth {toward:.0f}°")
        lines.append(f"  fitted from {self.n_samples} pictures: pointing error "
                     f"{self.rms_before_deg:.2f}° rms before -> {self.rms_after_deg:.3f}° rms after")
        return "\n".join(lines)


def _on_sky(d_az: float, d_alt: float, alt: float) -> float:
    return math.hypot(d_az * math.cos(alt * DEG), d_alt)


def fit_model(samples: list[Sample], terms: list[str] | None = None) -> PointingModel:
    terms = terms or choose_terms(samples)
    rows, rhs = [], []
    for s in samples:
        az_row, alt_row = _rows(s.mount_az, s.mount_alt, terms)
        rows += [az_row, alt_row]
        rhs += [s.d_az * math.cos(s.mount_alt * DEG), s.d_alt]
    n = len(terms)
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(n)] for i in range(n)]
    atb = [sum(r[i] * b for r, b in zip(rows, rhs)) for i in range(n)]
    x = _solve_linear(ata, atb)
    model = PointingModel(params={t: v for t, v in zip(terms, x)},
                          fitted_at=datetime.now(timezone.utc).isoformat(),
                          n_samples=len(samples))
    before, after, res = [], [], []
    for s in samples:
        p_az, p_alt = model.delta(s.mount_az, s.mount_alt)
        r = _on_sky(s.d_az - p_az, s.d_alt - p_alt, s.mount_alt)
        before.append(_on_sky(s.d_az, s.d_alt, s.mount_alt))
        after.append(r)
        res.append({"label": s.label, "mount_az": round(s.mount_az, 3),
                    "mount_alt": round(s.mount_alt, 3), "residual_deg": round(r, 4)})
    model.rms_before_deg = math.sqrt(sum(v * v for v in before) / len(before))
    model.rms_after_deg = math.sqrt(sum(v * v for v in after) / len(after))
    model.residuals = res
    model.epoch = model.fitted_at
    return model


# --------------------------------------------------------------------------
# Tune ledger
# --------------------------------------------------------------------------

class PointingState:
    """Tune moves this add-on has applied since the model was fitted.

    A Tune moves a motor without changing Pi-lomar's logical angle, and that
    offset stays for good (even across restarts and homing). So "where the
    mount really is" = Pi-lomar's logical position + this ledger.
    Pass path=None for an in-memory ledger (simulations, tests).
    """

    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self.tune_az = 0.0
        self.tune_alt = 0.0
        self.epoch = ""
        if self.path and self.path.exists():
            d = json.loads(self.path.read_text())
            self.tune_az, self.tune_alt = d.get("tune_az", 0.0), d.get("tune_alt", 0.0)
            self.epoch = d.get("epoch", "")

    def add(self, d_az: float, d_alt: float):
        self.tune_az += d_az
        self.tune_alt += d_alt
        self.save()

    def reset(self, epoch: str = ""):
        self.tune_az = self.tune_alt = 0.0
        self.epoch = epoch
        self.save()

    def save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"tune_az": self.tune_az, "tune_alt": self.tune_alt,
                                             "epoch": self.epoch}, indent=2))

    def mount_position(self, logical_az: float, logical_alt: float) -> tuple[float, float]:
        return wrap360(logical_az + self.tune_az), logical_alt + self.tune_alt


def predicted_correction(model: PointingModel, state: PointingState,
                         target_az: float, target_alt: float) -> tuple[float, float]:
    """Tune (d_az, d_alt) to apply after Pi-lomar's GOTO so the camera lands on target."""
    need_az, need_alt = model.mount_for_actual(target_az, target_alt)
    now_az, now_alt = state.mount_position(target_az, target_alt)
    return wrap180(need_az - now_az), need_alt - now_alt
