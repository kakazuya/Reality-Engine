"""Offline tests for the Vahan raw fetcher (no network, no live data)."""

import unittest

from reality_engine.scripts import fetch_vahan_raw as v


class MonthTests(unittest.TestCase):
    def test_months_parse_newest_first_and_skip_quarters(self):
        rows = v.months_of([{"yearAsString": "2026-October", "registeredVehicleCount": 11610},
                            {"yearAsString": "2021-December", "registeredVehicleCount": 240},
                            {"yearAsString": "2026-Q4", "registeredVehicleCount": 9}])
        self.assertEqual([r["month"] for r in rows], ["2026-10", "2021-12"])
        self.assertEqual(rows[0]["registrations"], 11610)

    def test_slug_is_file_safe(self):
        self.assertEqual(v.slug("OLA ELECTRIC TECHNOLOGIES PVT LTD"),
                         "ola_electric_technologies_pvt_ltd")
        self.assertEqual(v.slug("HERO MOTOCORP LTD"), "hero_motocorp_ltd")


if __name__ == "__main__":
    unittest.main()
