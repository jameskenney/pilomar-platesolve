# Stacking with DeepSkyStacker

Pi-lomar saves every frame as both JPG and DNG. DeepSkyStacker (tested with
6.2.2 on Windows) opens Pi HQ camera DNGs directly; they show as "RAW imx477",
4056 × 3040, 16-bit. Use the DNGs.

## How many frames, how long

* **Total exposure time** decides how smooth and deep the result is. Noise falls
  with the square root of total time, so 4× the time halves the noise.
* **Short frames** stay sharp. With a 16 mm lens, 10 s frames keep stars round
  if tracking is good. Check the first few frames before committing.
* Example: 180 × 10 s = 30 minutes of light, about 6 GB on the SD card.
* Take 20–25 darks afterwards with the lens cap on, at the same exposure and gain.

## Settings that worked

* **Raw/FITS DDP settings → Raw tab:** No White Balance Processing, AHD
  interpolation, brightness/red/blue all 1.
* **Register:** hot pixel detection on, stack after registering, best 80%,
  automatic star threshold.
* **Stacking:** Intersection mode, Kappa-Sigma (kappa 2, 5 iterations), Per
  Channel background calibration, Automatic alignment, darks combined with Median.

The colour preview looks green before stacking. That's normal for raw files.

## Processing the result

* On the **MTF Stretch** tab, **unlink the colour channels** (the chain button)
  before clicking Autostretch. A linked stretch leaves a strong green cast.
* In unlinked mode the Shadows and Midtones boxes only change the red channel,
  so leave them alone: Autostretch, then Apply.
* Saturation of about 10–17 brings out star colours before colour noise appears.
* Save as TIFF 16-bit with the adjustments applied.

Next steps for better images: flat frames for dark corners, more total time,
darker skies, and finishing in Siril or GIMP (gradient removal, cropping).
