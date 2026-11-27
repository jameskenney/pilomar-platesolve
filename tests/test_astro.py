import unittest
from datetime import datetime, timedelta, timezone

from pilomar_platesolve import astro


class TestTime(unittest.TestCase):
    def test_julian_date_j2000(self):
        self.assertAlmostEqual(astro.julian_date(datetime(2000, 1, 1, 12, tzinfo=timezone.utc)),
                               2451545.0, places=6)

    def test_julian_date_meeus_7a(self):
        # Meeus, Astronomical Algorithms, example 7.a: 1957 Oct 4.81 = JD 2436116.31
        t = datetime(1957, 10, 4, tzinfo=timezone.utc) + timedelta(days=0.81)
        self.assertAlmostEqual(astro.julian_date(t), 2436116.31, places=4)

    def test_gmst_meeus_12b(self):
        # Meeus example 12.b: 1987 Apr 10, 19:21:00 UT -> GMST 8h34m57.0896s
        jd = astro.julian_date(datetime(1987, 4, 10, 19, 21, 0, tzinfo=timezone.utc))
        self.assertAlmostEqual(astro.gmst_deg(jd), astro.hms_to_deg(8, 34, 57.0896), delta=1e-4)


class TestCoordinates(unittest.TestCase):
    def test_precession_meeus_21b(self):
        # Meeus example 21.b: theta Persei to 2028 Nov 13.19 TD (pm already applied)
        jd = 2462088.69
        ra, dec = astro.j2000_to_date(41.054063, 49.227750, jd)
        self.assertAlmostEqual(ra, 41.547214, delta=2e-5)
        self.assertAlmostEqual(dec, 49.348483, delta=2e-5)
        back = astro.date_to_j2000(ra, dec, jd)
        self.assertAlmostEqual(back[0], 41.054063, places=7)
        self.assertAlmostEqual(back[1], 49.227750, places=7)

    def test_altaz_meeus_13b(self):
        # Meeus example 13.b: Venus from Washington (US Naval Observatory)
        # 1987 Apr 10 19:21 UT; Meeus azimuth 68.0337 is measured from SOUTH.
        jd = astro.julian_date(datetime(1987, 4, 10, 19, 21, 0, tzinfo=timezone.utc))
        lon = -astro.dms_to_deg(77, 3, 56)
        lat = astro.dms_to_deg(38, 55, 17)
        ra = astro.hms_to_deg(23, 9, 16.641)
        dec = astro.dms_to_deg(-6, 43, 11.61)
        # Meeus uses apparent sidereal time; the 0.24 s difference is < 0.002 deg.
        alt, az = astro.radec_of_date_to_altaz(ra, dec, astro.lst_deg(jd, lon), lat)
        self.assertAlmostEqual(alt, 15.1249, delta=0.003)
        self.assertAlmostEqual(az, (68.0337 + 180) % 360, delta=0.003)

    def test_altaz_roundtrip(self):
        site = astro.Site(35.47, -97.52)
        t = datetime(2026, 11, 25, 4, 0, tzinfo=timezone.utc)
        for ra, dec in [(10.68, 41.27), (83.8, -5.4), (250.4, 36.46), (359.9, 89.0)]:
            alt, az = astro.j2000_to_altaz(ra, dec, site, t)
            ra2, dec2 = astro.altaz_to_j2000(alt, az, site, t)
            self.assertLess(astro.angular_separation(ra, dec, ra2, dec2), 1e-8)

    def test_polaris_altitude_is_latitude(self):
        site = astro.Site(35.47, -97.52)
        t = datetime(2026, 11, 25, 4, 0, tzinfo=timezone.utc)
        alt, az = astro.j2000_to_altaz(0.0, 90.0, site, t)  # J2000 pole
        self.assertAlmostEqual(alt, 35.47, delta=0.4)        # pole has precessed ~0.3 deg
        self.assertTrue(az < 2 or az > 358)

    def test_tangent_offsets_directions(self):
        e, n = astro.tangent_offsets(10.0, 40.0, 10.0, 41.0)
        self.assertAlmostEqual(n, 1.0, places=3)
        self.assertAlmostEqual(e, 0.0, places=6)
        e, n = astro.tangent_offsets(10.0, 40.0, 11.0, 40.0)   # larger RA = east
        self.assertGreater(e, 0.7)

    def test_wrap_and_format(self):
        self.assertEqual(astro.wrap180(190), -170)
        self.assertEqual(astro.format_ra(10.684583), "00h 42m 44.30s")
        self.assertEqual(astro.format_dec(-5.391111), "-05° 23' 28.0\"")

    def test_sun_and_moon_roughly(self):
        # 2026 June solstice: sun declination near +23.4
        jd = astro.julian_date(datetime(2026, 6, 21, 12, tzinfo=timezone.utc))
        self.assertAlmostEqual(astro.sun_radec_of_date(jd)[1], 23.44, delta=0.1)
        ra, dec = astro.moon_radec_of_date(jd)
        self.assertLess(abs(dec), 29.0)


if __name__ == "__main__":
    unittest.main()
