#!/usr/bin/env python3
import json, sys, time
a = sys.argv[1:]
img = a[0]; d = a[a.index("--dir")+1]; o = a[a.index("--out")+1]
assert "--crpix-center" in a and "--scale-units" in a
t = json.load(open(img + ".truth.json"))
def card(k, v):
    v = f"{v:>20.12E}" if isinstance(v, float) else f"{v:>20}"
    return f"{k:<8}= {v}".ljust(80)
cards = [card("SIMPLE", "T"), card("CRVAL1", float(t["ra"])), card("CRVAL2", float(t["dec"])),
         card("CRPIX1", float(t["crpix"][0])), card("CRPIX2", float(t["crpix"][1])),
         card("CD1_1", float(t["cd"][0])), card("CD1_2", float(t["cd"][1])),
         card("CD2_1", float(t["cd"][2])), card("CD2_2", float(t["cd"][3])),
         card("IMAGEW", t["width"]), card("IMAGEH", t["height"]), "END".ljust(80)]
time.sleep(0.2)
open(f"{d}/{o}.wcs", "w").write("".join(cards))
print("Field center: fake")
