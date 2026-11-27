"""Star-based focus helper that works over SSH (no picture needed).

Takes a picture every few seconds with rpicam-still (BMP, so no extra
libraries are needed to read it), finds the stars, and prints their median
size as a half-flux radius (HFR) in pixels. Turn the focus ring slowly and
watch the number: smaller = sharper. The best focus is the lowest value.
"""

from __future__ import annotations

import math
import shutil
import statistics
import subprocess
from dataclasses import dataclass
from pathlib import Path


class FocusError(RuntimeError):
    pass


def read_bmp_gray(path: str | Path) -> tuple[int, int, list[int]]:
    """Read a 24/32-bit uncompressed BMP into a grey list (row 0 = top)."""
    data = Path(path).read_bytes()
    if data[:2] != b"BM":
        raise FocusError("not a BMP file")
    off = int.from_bytes(data[10:14], "little")
    w = int.from_bytes(data[18:22], "little", signed=True)
    h = int.from_bytes(data[22:26], "little", signed=True)
    bpp = int.from_bytes(data[28:30], "little")
    if bpp not in (24, 32):
        raise FocusError(f"unsupported BMP depth {bpp}")
    step = bpp // 8
    row_len = (w * step + 3) & ~3
    bottom_up = h > 0
    h = abs(h)
    gray = [0] * (w * h)
    for y in range(h):
        src = off + (h - 1 - y if bottom_up else y) * row_len
        row = data[src:src + w * step]
        # Sum of B, G, R scaled back to 0-255 (stars are white-ish; this keeps noise low).
        b, g, r = row[0::step], row[1::step], row[2::step]
        base = y * w
        for x in range(w):
            gray[base + x] = (b[x] + g[x] + r[x]) // 3
    return w, h, gray


@dataclass
class FocusResult:
    stars: int
    hfr: float | None          # median half-flux radius, pixels (smaller = sharper)
    background: float
    saturated: int


def measure_stars(w: int, h: int, px: list[int], max_stars: int = 40, radius: int = 7) -> FocusResult:
    sample = px[::97] or [0]
    bg = statistics.median(sample)
    mad = statistics.median(abs(v - bg) for v in sample) or 1.0
    thresh = bg + max(6.0 * 1.4826 * mad, 12.0)

    peaks = []
    for y in range(radius, h - radius):
        row = y * w
        for x in range(radius, w - radius):
            v = px[row + x]
            if v < thresh:
                continue
            # Local maximum in a 5x5 box (ties broken by position).
            is_max = True
            for dy in (-2, -1, 0, 1, 2):
                r2 = (y + dy) * w
                for dx in (-2, -1, 0, 1, 2):
                    if dx == 0 and dy == 0:
                        continue
                    n = px[r2 + x + dx]
                    if n > v or (n == v and (dy < 0 or (dy == 0 and dx < 0))):
                        is_max = False
                        break
                if not is_max:
                    break
            if is_max:
                peaks.append((v, x, y))
    peaks.sort(reverse=True)

    saturated = sum(1 for v, _, _ in peaks if v >= 250)
    usable = [p for p in peaks if p[0] < 250]
    if len(usable) < 3:
        usable = peaks
    hfrs = []
    for v, cx, cy in usable[:max_stars]:
        tot = wsum = 0.0
        for yy in range(cy - radius, cy + radius + 1):
            r2 = yy * w
            for xx in range(cx - radius, cx + radius + 1):
                d = math.hypot(xx - cx, yy - cy)
                if d > radius:
                    continue
                f = px[r2 + xx] - bg
                if f > 0:
                    tot += f
                    wsum += f * d
        if tot > 0:
            hfrs.append(wsum / tot)
    return FocusResult(len(peaks), statistics.median(hfrs) if hfrs else None, bg, saturated)


def capture_bmp(cfg: dict, out: Path, exposure_s: float, gain: float, roi: str | None,
                width: int, height: int) -> Path:
    exe = cfg.get("exe", "rpicam-still")
    if not shutil.which(exe):
        raise FocusError(f"{exe} not found")
    cmd = [exe, "-n", "--immediate", "-e", "bmp", "--shutter", str(int(exposure_s * 1e6)),
           "--gain", str(gain), "--awbgains", "1,1", "--denoise", "off",
           "--width", str(width), "--height", str(height), "-o", str(out)]
    if roi:
        cmd += ["--roi", roi]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=exposure_s + 60)
    if p.returncode != 0 or not out.exists():
        msg = (p.stderr or "").strip().splitlines()[-1:] or ["unknown error"]
        raise FocusError(f"rpicam-still failed: {msg[0]} (is Pi-lomar's camera enabled, "
                         "or an rpicam-hello preview running?)")
    return out


def bar(value: float, best: float, width: int = 20) -> str:
    """A bar that is full at the best value seen and shrinks as focus gets worse."""
    frac = max(0.0, min(1.0, best / value)) if value else 0.0
    n = int(round(frac * width))
    return "#" * n + "." * (width - n)
