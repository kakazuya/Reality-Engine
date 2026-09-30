"""Hermetic tests for the universe-index OHLC backfill.

Contract: no live network (fetcher always stubbed), no writes outside a
temp DB, deterministic, fast. Covers what index-backfill needs:
  * a missing date is parsed (4 legs only) and upserted
  * resume skips dates already holding all 4 names (no fetch call)
  * a None/empty fetch lands honestly in missing_dates (never fabricated)
  * dry-run reports gaps without fetching or writing
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.scripts import backfill_index_ohlc as bib

COLS = [
    "Index Name", "Open Index Value", "High Index Value", "Low Index Value",
    "Closing Index Value", "Points Change", "Change(%)", "Volume",
    "Turnover (Rs. Cr.)", "P/E", "P/B", "Div Yield",
]


def _seed_row(date_iso: str, name: str, close: float) -> Dict:
    return {
        "date": date_iso, "index_name": name,
        "open": close - 1.0, "high": close + 1.0, "low": close - 2.0,
        "close": close, "change_pct": 0.1, "points_change": 1.0,
        "volume": 1000, "turnover_cr": 10.0,
        "advances_count": 0, "declines_count": 0,
        "advance_decline_ratio": 1.0,
        "pe_ratio": 20.0, "pb_ratio": 3.0, "dividend_yield": 1.2,
    }


def _stub_frame(rows: List[tuple]) -> pd.DataFrame:
    """Build a minimal index-bhavcopy frame: [(name, close), ...]."""
    data = [
        [name, c - 1.0, c + 1.0, c - 2.0, c, 1.0, 0.1, 1000, 10.0, 20.0, 3.0, 1.2]
        for name, c in rows
    ]
    return pd.DataFrame(data, columns=COLS)


def _four_legs(base: float = 100.0) -> pd.DataFrame:
    return _stub_frame([(n, base + i) for i, n in enumerate(bib.UNIVERSE_INDEX)])


class StubFetcher:
    """Callable stub: maps date_iso -> frame (or None for a 404/holiday)."""

    def __init__(self, frames: Dict[str, Optional[pd.DataFrame]]):
        self.frames = frames
        self.calls: List[str] = []

    def __call__(self, target: datetime) -> Optional[pd.DataFrame]:
        iso = target.strftime("%Y-%m-%d")
        self.calls.append(iso)
        return self.frames.get(iso)


class IndexBackfillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="index_backfill_"))
        self.mgr = DatabaseManager(db_path=self.tmp / "test.db")
        self.repo = Repository(self.mgr)
        # Two fully-covered seed dates.
        for d in ("2025-09-01", "2025-09-02"):
            self.repo.upsert_index_breadth(
                [_seed_row(d, n, 100.0 + i) for i, n in enumerate(bib.UNIVERSE_INDEX)]
            )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _count(self, date_iso: str) -> int:
        with self.mgr.session() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM nse_index_breadth WHERE date = ?", (date_iso,)
            ).fetchone()[0]

    def test_backfills_missing_date_and_resumes_seeded(self):
        stub = StubFetcher({"2025-09-03": _four_legs(200.0)})
        summary = bib.backfill_index_ohlc(
            since="2025-09-01", until="2025-09-03",
            repo=self.repo, fetcher=stub, rate_limit_sec=0,
        )
        self.assertEqual(summary["dates_requested"], 3)
        self.assertEqual(summary["dates_filled"], 1)
        self.assertEqual(summary["rows_upserted"], 4)
        self.assertEqual(summary["missing_dates"], [])
        # Resume: seeded dates never hit the network.
        self.assertEqual(stub.calls, ["2025-09-03"])
        self.assertEqual(self._count("2025-09-03"), 4)
        with self.mgr.session() as conn:
            closes = {
                r[0]: r[1] for r in conn.execute(
                    "SELECT index_name, close FROM nse_index_breadth WHERE date = '2025-09-03'"
                )
            }
        for i, name in enumerate(bib.UNIVERSE_INDEX):
            self.assertAlmostEqual(closes[name], 200.0 + i)

        # Second run: everything covered, zero fetches, zero writes.
        stub2 = StubFetcher({})
        summary2 = bib.backfill_index_ohlc(
            since="2025-09-01", until="2025-09-03",
            repo=self.repo, fetcher=stub2, rate_limit_sec=0,
        )
        self.assertEqual(stub2.calls, [])
        self.assertEqual(summary2["dates_filled"], 0)
        self.assertEqual(summary2["rows_upserted"], 0)
        self.assertEqual(summary2["missing_dates"], [])

    def test_none_fetch_lands_in_missing_dates(self):
        stub = StubFetcher({})  # every date behaves like a 404/holiday
        summary = bib.backfill_index_ohlc(
            since="2025-09-04", until="2025-09-04",
            repo=self.repo, fetcher=stub, rate_limit_sec=0,
        )
        self.assertEqual(summary["dates_filled"], 0)
        self.assertEqual(summary["rows_upserted"], 0)
        self.assertEqual(summary["missing_dates"], ["2025-09-04"])
        self.assertEqual(self._count("2025-09-04"), 0)

    def test_dry_run_reports_gaps_without_fetch_or_write(self):
        stub = StubFetcher({"2025-09-03": _four_legs()})
        summary = bib.backfill_index_ohlc(
            since="2025-09-01", until="2025-09-03", dry_run=True,
            repo=self.repo, fetcher=stub, rate_limit_sec=0,
        )
        self.assertEqual(stub.calls, [])
        self.assertEqual(summary["missing_dates"], ["2025-09-03"])
        self.assertEqual(summary["dates_filled"], 0)
        self.assertEqual(summary["rows_upserted"], 0)
        self.assertEqual(self._count("2025-09-03"), 0)


if __name__ == "__main__":
    unittest.main()
