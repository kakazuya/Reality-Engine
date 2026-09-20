"""News explainer tests: temp-DB fixtures, zero network."""
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing.news_explainer import explain_move


def _mk_repo(td):
    mgr = DatabaseManager(db_path=Path(td) / "t.db")
    return Repository(manager=mgr), mgr


_ISIN = "INE002A01018"
_SYM = "RELIANCE"
_DATE = "2026-09-10"


def _seed_full(repo):
    repo.upsert_master_companies([{
        "isin": _ISIN, "nse_symbol": _SYM,
        "company_name": "Reliance Industries", "is_active": 1}])
    repo.upsert_daily_price_delivery([{
        "date": _DATE, "symbol": _SYM, "isin": _ISIN, "series": "EQ",
        "open": 100.0, "high": 105.0, "low": 99.0, "close": 96.0,
        "prev_close": 100.0, "change_pct": -4.0, "total_volume": 1000,
        "deliverable_volume": 500, "delivery_pct": 50.0,
        "delivery_spike_ratio": 2.5}])
    repo.upsert_corporate_documents([{
        "isin": _ISIN, "symbol": _SYM, "doc_type": "ANNOUNCEMENT",
        "title": "CFO resignation with immediate effect",
        "doc_date": _DATE, "source_url": "https://nse.example/ann/1",
        "source": "nse_official", "discovery_source": "nse_announcement_feed",
        "local_file_path": None, "file_size_bytes": None,
        "sha256_hash": "abc", "is_processed": 0}])
    repo.upsert_corporate_actions([{
        "isin": _ISIN, "symbol": _SYM, "subject": "Dividend declared",
        "action_type": "DIVIDEND", "ex_date": _DATE,
        "broadcast_date": _DATE, "source": "nse_official"}])
    repo.upsert_bulk_block_deals([{
        "id": "x" * 32, "deal_date": _DATE, "symbol": _SYM,
        "client_name": "BIG FUND", "deal_type": "BLOCK",
        "buy_sell": "SELL", "quantity": 1000, "trade_price": 96.5,
        "is_marquee_institution": 1}])


class TestNewsExplainer(unittest.TestCase):
    def test_verdict_high_on_resignation(self):
        with tempfile.TemporaryDirectory() as td:
            repo, mgr = _mk_repo(td)
            _seed_full(repo)
            out = explain_move(_SYM, _DATE, window_days=2, db=mgr)
            self.assertEqual(out["symbol"], _SYM)
            self.assertEqual(out["target_date"], _DATE)
            self.assertIsNotNone(out["price"])
            self.assertEqual(out["price"]["close"], 96.0)
            self.assertEqual(out["price"]["delivery_spike_ratio"], 2.5)
            self.assertEqual(len(out["announcements"]), 1)
            self.assertEqual(
                out["announcements"][0]["title"],
                "CFO resignation with immediate effect")
            self.assertEqual(len(out["corp_actions"]), 1)
            self.assertEqual(out["corp_actions"][0]["action_type"], "DIVIDEND")
            self.assertEqual(len(out["deals"]), 1)
            self.assertEqual(out["deals"][0]["client_name"], "BIG FUND")
            self.assertEqual(out["verdict"]["severity"], "HIGH")
            self.assertTrue(out["verdict"]["drivers"])

    def test_empty_db_symbol_low_no_crash(self):
        with tempfile.TemporaryDirectory() as td:
            _, mgr = _mk_repo(td)
            out = explain_move("NOBODY", "2026-09-10", db=mgr)
            self.assertEqual(out["verdict"]["severity"], "LOW")
            self.assertEqual(out["announcements"], [])
            self.assertEqual(out["corp_actions"], [])
            self.assertEqual(out["deals"], [])
            self.assertIsNone(out["price"])


if __name__ == "__main__":
    unittest.main()
