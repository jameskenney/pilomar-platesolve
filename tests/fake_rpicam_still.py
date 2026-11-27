#!/usr/bin/env python3
"""Stand-in for rpicam-still: writes a BMP star field. Blur (sigma, px) comes from
the file named in $FAKE_FOCUS_SIGMA_FILE (default 1.5)."""
import math, os, random, sys
a = sys.argv[1:]
out = a[a.index("-o") + 1]
w, h = int(a[a.index("--width") + 1]), int(a[a.index("--height") + 1])
sf = os.environ.get("FAKE_FOCUS_SIGMA_FILE")
sigma = float(open(sf).read()) if sf and os.path.exists(sf) else 1.5
r = random.Random(4)
img = bytearray(r.randrange(18, 26) for _ in range(w * h))
for _ in range(60):
    cx, cy, peak = r.uniform(20, w - 20), r.uniform(20, h - 20), r.uniform(40, 200) / max(1, sigma / 1.5) ** 2
    for y in range(int(cy) - 12, int(cy) + 13):
        for x in range(int(cx) - 12, int(cx) + 13):
            v = peak * math.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * sigma ** 2))
            i = y * w + x
            img[i] = min(255, img[i] + int(v))
row_len = (w * 3 + 3) & ~3
pix = bytearray()
for y in range(h - 1, -1, -1):
    row = bytearray()
    for x in range(w):
        v = img[y * w + x]
        row += bytes((v, v, v))
    pix += row + b"\0" * (row_len - w * 3)
hdr = b"BM" + (54 + len(pix)).to_bytes(4, "little") + b"\0\0\0\0" + (54).to_bytes(4, "little")
dib = (40).to_bytes(4, "little") + w.to_bytes(4, "little") + h.to_bytes(4, "little", signed=True) \
    + (1).to_bytes(2, "little") + (24).to_bytes(2, "little") + b"\0" * 24
open(out, "wb").write(hdr + dib + pix)
