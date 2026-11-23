"""Offline unit tests for the polars rolling-indicator batch path.

Contract: small synthetic frames only (never the live 3.1M-row table),
deterministic, fast. Covers:
  * polars rolling legs equal the pandas groupby-rolling values
  * helper returns None when polars is missing (pandas fallback engages)
  * pandas in / pandas out (no polars types leak past the edge)
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TEMP_DB_DIR = tempfile.mkdtemp(prefix="reality_polars_test_db_")
os.environ.setdefault(
    "REALITY_ENGINE_DB_PATH", str(Path(_TEMP_DB_DIR) / "singleton_isolated.db")
)

import pandas as pd  # noqa: E402

from reality_engine.pipeline.backfill import rolling_indicators_polars  # noqa: E402


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["A", "A", "A", "A", "B", "B"],
            "close": [10.0, 11.0, 12.0, 13.0, 20.0, 22.0],
            "high": [11.0, 12.0, 13.0, 14.0, 21.0, 23.0],
            "low": [9.0, 10.0, 11.0, 12.0, 19.0, 21.0],
            "deliverable_volume": [100, 200, 300, 400, 500, 600],
        }
    )


def _pandas_expected(pdf: pd.DataFrame) -> pd.DataFrame:
    g = pdf.groupby("symbol", sort=False)
    for col, win, fn in [
        ("deliv_sma_20", 20, "mean"),
        ("sma_20", 20, "mean"),
        ("sma_50", 50, "mean"),
        ("sma_200", 200, "mean"),
    ]:
        src = "deliverable_volume" if col == "deliv_sma_20" else "close"
        pdf[col] = getattr(g[src].rolling(win, min_periods=1), fn)().reset_index(level=0, drop=True)
    pdf["high_52w"] = g["high"].rolling(250, min_periods=1).max().reset_index(level=0, drop=True)
    pdf["low_52w"] = g["low"].rolling(250, min_periods=1).min().reset_index(level=0, drop=True)
    return pdf


class PolarsBatchTest(unittest.TestCase):
    def test_polars_matches_pandas(self):
        got = rolling_indicators_polars(_frame())
        want = _pandas_expected(_frame())
        self.assertIsNotNone(got)
        for col in ("deliv_sma_20", "sma_20", "sma_50", "sma_200", "high_52w", "low_52w"):
            for a, b in zip(got[col].tolist(), want[col].tolist()):
                self.assertAlmostEqual(float(a), float(b), places=4, msg=col)

    def test_missing_polars_falls_back(self):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "polars":
                raise ImportError("no polars")
            return real_import(name, *args, **kwargs)

        with mock.patch.object(builtins, "__import__", fake_import):
            self.assertIsNone(rolling_indicators_polars(_frame()))

    def test_pandas_in_pandas_out(self):
        got = rolling_indicators_polars(_frame())
        self.assertIsInstance(got, pd.DataFrame)
        for col in ("deliv_sma_20", "sma_20"):
            self.assertTrue(pd.api.types.is_numeric_dtype(got[col]))


if __name__ == "__main__":
    unittest.main()
