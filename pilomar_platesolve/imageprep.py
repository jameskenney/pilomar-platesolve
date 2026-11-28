"""Optional picture clean-up before plate solving.

Pi-lomar's own solver runs a 'PrepForPlateSolving' filter first. This does a
similar job for hard pictures (haze, moonlight, a glow near the horizon):

1. Estimate the smooth sky background (stars removed with a morphological
   opening on a reduced copy, then blurred) and subtract it, so a bright
   gradient doesn't swamp the faint stars.
2. A light median filter takes out hot pixels and grain.
3. Stretch so the faint stars stand out, and save a grey PNG.

The cleaned picture has the same size as the original, so the solution
applies to the original unchanged. It is written to this add-on's own work
folder, never next to Pi-lomar's pictures.

It needs OpenCV and NumPy, which Pi-lomar already installs. Without them the
clean-up is skipped and the original picture is used.
"""

from __future__ import annotations

from pathlib import Path


def available() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


def clean_for_solving(image: str | Path, outdir: str | Path) -> Path | None:
    """Write a cleaned grey PNG and return its path, or None if not possible."""
    image = Path(image)
    if image.suffix.lower() in (".fits", ".fit", ".fts"):
        return None
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    img = cv2.imread(str(image), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    f = img.astype(np.float32)
    h, w = f.shape
    k = 8
    small = cv2.resize(f, (max(1, w // k), max(1, h // k)), interpolation=cv2.INTER_AREA)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    opened = cv2.morphologyEx(small, cv2.MORPH_OPEN, kernel)   # stars removed
    bg = _smooth_background(opened, w, h, np)
    d = cv2.medianBlur(f - bg, 3)
    d[d < 0] = 0
    hi = float(np.percentile(d, 99.95))
    if hi <= 0:
        return None
    out = np.clip(d * (255.0 / hi), 0, 255).astype(np.uint8)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    dest = outdir / (image.stem + ".clean.png")
    cv2.imwrite(str(dest), out)
    return dest


def _smooth_background(small, w: int, h: int, np):
    """Fit a smooth surface (2nd-order polynomial) to the reduced, star-free
    picture, ignoring outliers, and evaluate it at full size. Sky glow from
    the Moon, haze or town lights is smooth, and unlike a blur this doesn't
    bend at the picture's edges."""
    sh, sw = small.shape
    yy, xx = np.mgrid[0:sh, 0:sw]
    x = (xx.ravel() + 0.5) / sw * 2 - 1
    y = (yy.ravel() + 0.5) / sh * 2 - 1
    v = small.ravel().astype(np.float64)
    a = np.stack([np.ones_like(x), x, y, x * x, x * y, y * y], axis=1)
    keep = np.ones(v.shape, bool)
    for _ in range(3):
        coef, *_ = np.linalg.lstsq(a[keep], v[keep], rcond=None)
        r = v - a @ coef
        s = float(np.std(r[keep])) or 1.0
        keep = np.abs(r) < 2.5 * s
    fy, fx = np.mgrid[0:h, 0:w]
    X = (fx + 0.5) / w * 2 - 1
    Y = (fy + 0.5) / h * 2 - 1
    bg = coef[0] + coef[1] * X + coef[2] * Y + coef[3] * X * X + coef[4] * X * Y + coef[5] * Y * Y
    return bg.astype(np.float32)
