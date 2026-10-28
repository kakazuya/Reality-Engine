"""Pure arithmetic tests for the query layer (no I/O)."""
from __future__ import annotations

import unittest

from reality_engine.query import compute


class TestGrowth(unittest.TestCase):
    def test_growth_and_cagr(self):
        self.assertAlmostEqual(compute.growth(100, 110), 10.0)
        self.assertAlmostEqual(compute.cagr(100, 121, 2), 10.0)
        self.assertIsNone(compute.cagr(100, 121, 0))
        self.assertIsNone(compute.growth(0, 10))

    def test_cagr_between_uses_real_dates(self):
        value, years = compute.cagr_between(100, 121, "2024-01-01", "2026-01-01")
        self.assertAlmostEqual(years, 731 / 365.25, places=3)
        self.assertAlmostEqual(value, 100 * ((121 / 100) ** (365.25 / 731) - 1), places=3)
        value, years = compute.cagr_between(100, 121, "2026-01-01", "2024-01-01")
        self.assertIsNone(value)
        self.assertIsNone(years)


class TestRatios(unittest.TestCase):
    def test_margin_ratio_delta(self):
        self.assertAlmostEqual(compute.margin(25, 200), 12.5)
        self.assertAlmostEqual(compute.ratio(25, 200), 0.125)
        self.assertAlmostEqual(compute.delta(25, 40), 15)
        self.assertIsNone(compute.margin(1, 0))
        self.assertIsNone(compute.ratio(None, 2))


class TestSeries(unittest.TestCase):
    def test_window_return_and_order(self):
        points = [("2026-06-03", 110), ("2026-06-01", 100), ("2026-06-02", 105)]
        ret, first, last = compute.window_return(points)
        self.assertAlmostEqual(ret, 10.0)
        self.assertEqual((first, last), (100, 110))
        self.assertEqual(compute.window_return([("2026-06-01", 100)]), (None, None, None))

    def test_extremes_and_drawdown(self):
        points = [("2026-06-01", 100), ("2026-06-02", 120), ("2026-06-03", 90),
                  ("2026-06-04", 110)]
        self.assertEqual(compute.extreme(points, "max"), (120, "2026-06-02"))
        self.assertEqual(compute.extreme(points, "min"), (90, "2026-06-03"))
        self.assertAlmostEqual(compute.max_drawdown(points), 25.0)

    def test_stats_single_point(self):
        stats = compute.series_stats([("2026-06-04", 42.0)])
        self.assertEqual(stats["rows"], 1)
        self.assertEqual(stats["first"], 42.0)
        self.assertIsNone(stats["return_pct"])

    def test_rsi_bounds(self):
        closes = [100 + (i % 5) for i in range(40)]
        value = compute.rsi(closes)
        self.assertTrue(0 <= value <= 100)
        self.assertIsNone(compute.rsi([100, 101]))


class TestRanking(unittest.TestCase):
    def test_rank_ties_share_rank(self):
        ranked = compute.rank({"a": 10, "b": 20, "c": 20})
        self.assertEqual([row[0] for row in ranked], ["b", "c", "a"])
        self.assertEqual(ranked[0][2], ranked[1][2])
        self.assertEqual(ranked[2][2], 3)

    def test_percentile_and_zscore(self):
        self.assertAlmostEqual(compute.percentile([1, 2, 3, 4], 3), 75.0)
        self.assertAlmostEqual(compute.zscore([1, 2, 3], 3), 1.0)
        self.assertIsNone(compute.zscore([1, 1], 1))

    def test_relative_return(self):
        subject = [("2026-06-01", 100), ("2026-06-30", 110)]
        bench = [("2026-06-01", 100), ("2026-06-30", 105)]
        self.assertAlmostEqual(compute.relative_return(subject, bench), 5.0)


class TestNoMagicNumbers(unittest.TestCase):
    def test_missing_inputs_never_become_zero(self):
        self.assertIsNone(compute.cagr(None, 10, 1))
        self.assertIsNone(compute.window_return([])[0])
        self.assertIsNone(compute.series_stats([]).get("return_pct"))


if __name__ == "__main__":
    unittest.main()
