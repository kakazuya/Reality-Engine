"""Hermetic tests for the call-row backfill (temp DBs only, never the live DB).

Contract: the screener is always stubbed — it writes through the real
``repo.upsert_eod_scrip_calls`` path (idempotency included) but never runs
real screens or touches the network. Covers the task acceptance:

  * a stubbed screen fills call rows for 2 uncovered attribution dates
  * resume skips dates already covered (the stub is never called for them)
  * a failure on one date lands honestly in ``failed_dates`` without
    aborting the remaining dates
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing.move_attributor import ensure_move_attribution_schema
from reality_engine.scripts import backfill_call_rows as bcr


def _seed_company(conn: Any, symbol: str, isin: str) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO master_companies
            (isin, nse_symbol, company_name, industry, sector, is_nifty200, is_active)
        VALUES (?, ?, ?, 'Industrials', 'Capital Goods', 1, 1)
        """,
        (isin, symbol, f"{symbol} Ltd"),
    )


def _seed_attribution(conn: Any, symbol: str, date_iso: str) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO move_attribution
            (symbol, attribution_date, realized_move_pct, noise_floor,
             is_material, explained_total, residual)
        VALUES (?, ?, 3.0, 2.0, 1, 1.5, 1.5)
        """,
        (symbol, date_iso),
    )


def _call_row(symbol: str, date_iso: str, rank: int) -> Dict[str, Any]:
    return {
        "date": date_iso,
        "symbol": symbol,
        "isin": f"INE-{symbol}",
        "composite_rank": rank,
        "technical_score": 60.0,
        "fundamental_score": 55.0,
        "alt_sentiment_score": 50.0,
        "composite_score": 58.0,
        "current_market_price": 100.0,
        "recommended_entry_range": "INR 98.5 - INR 101.5",
        "target_price": 118.0,
        "stop_loss": 94.0,
        "risk_reward_ratio": 3.0,
        "conviction_level": "MODERATE",
        "is_solvency_approved": 1,
        "delivery_spike_ratio": 1.0,
        "delivery_conviction_score": 10.0,
        "yoy_revenue_growth_pct": 5.0,
        "yoy_pat_growth_pct": 6.0,
    }


class StubScreen:
    """Fake ``screen_fn``: writes rows via the real upsert path (or raises)."""

    def __init__(self, repo: Repository, fail_dates: Optional[List[str]] = None,
                 symbols: Optional[List[str]] = None):
        self.repo = repo
        self.fail_dates = set(fail_dates or [])
        self.symbols = symbols or ["AAA", "BBB"]
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, target_date: str, top_n: int, universe: str) -> List[Dict[str, Any]]:
        self.calls.append({"target_date": target_date, "top_n": top_n, "universe": universe})
        if target_date in self.fail_dates:
            raise RuntimeError(f"boom on {target_date}")
        records = [_call_row(s, target_date, i + 1) for i, s in enumerate(self.symbols)]
        self.repo.upsert_eod_scrip_calls(records)  # real upsert path, incl. idempotency
        return records


class BackfillCallRowsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="backfill_call_rows_"))
        self.mgr = DatabaseManager(db_path=self.tmp / "test.db")
        self.repo = Repository(self.mgr)
        ensure_move_attribution_schema(self.mgr)
        for symbol in ("AAA", "BBB"):
            with self.mgr.session() as conn:
                _seed_company(conn, symbol, f"INE-{symbol}")
        self.dates = ["2026-07-01", "2026-07-02", "2026-07-03"]
        with self.mgr.session() as conn:
            for d in self.dates:
                for symbol in ("AAA", "BBB"):
                    _seed_attribution(conn, symbol, d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _count(self, date_iso: str) -> int:
        with self.mgr.session() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM eod_scrip_calls WHERE date = ?", (date_iso,)
            ).fetchone()[0]

    def test_fills_two_uncovered_dates_through_real_upsert(self):
        stub = StubScreen(self.repo)
        summary = bcr.backfill_call_rows(
            repo=self.repo, screen_fn=stub, limit_dates=2,
        )
        self.assertEqual(summary["dates_requested"], 2)
        self.assertEqual(summary["dates_filled"], 2)
        self.assertEqual(summary["call_rows_written"], 4)
        self.assertEqual(summary["failed_dates"], [])
        targets = [c["target_date"] for c in stub.calls]
        self.assertEqual(targets, ["2026-07-01", "2026-07-02"])  # ascending
        # Screens run the attribution-matching contract (nifty200, >=200 breadth).
        for call in stub.calls:
            self.assertEqual(call["universe"], "nifty200")
            self.assertGreaterEqual(call["top_n"], 200)
        self.assertEqual(self._count("2026-07-01"), 2)
        self.assertEqual(self._count("2026-07-02"), 2)
        self.assertEqual(self._count("2026-07-03"), 0)

    def test_resume_skips_covered_dates(self):
        self.repo.upsert_eod_scrip_calls([_call_row("AAA", "2026-07-01", 1)])
        stub = StubScreen(self.repo)
        summary = bcr.backfill_call_rows(repo=self.repo, screen_fn=stub)
        self.assertEqual(summary["dates_requested"], 2)
        self.assertEqual([c["target_date"] for c in stub.calls],
                         ["2026-07-02", "2026-07-03"])
        self.assertEqual(summary["dates_filled"], 2)
        self.assertEqual(summary["failed_dates"], [])
        # Idempotent re-run: everything covered, the stub never fires.
        stub2 = StubScreen(self.repo)
        summary2 = bcr.backfill_call_rows(repo=self.repo, screen_fn=stub2)
        self.assertEqual(stub2.calls, [])
        self.assertEqual(summary2["dates_requested"], 0)
        self.assertEqual(summary2["dates_filled"], 0)
        self.assertEqual(summary2["call_rows_written"], 0)

    def test_failure_on_one_date_does_not_abort_others(self):
        stub = StubScreen(self.repo, fail_dates=["2026-07-02"])
        summary = bcr.backfill_call_rows(repo=self.repo, screen_fn=stub)
        self.assertEqual(summary["dates_requested"], 3)
        self.assertEqual(summary["dates_filled"], 2)
        self.assertEqual(summary["call_rows_written"], 4)
        self.assertEqual(summary["failed_dates"], ["2026-07-02"])
        self.assertEqual([c["target_date"] for c in stub.calls], self.dates)
        self.assertEqual(self._count("2026-07-01"), 2)
        self.assertEqual(self._count("2026-07-02"), 0)
        self.assertEqual(self._count("2026-07-03"), 2)


if __name__ == "__main__":
    unittest.main()
