"""Master upsert collision handling (placeholder promotion + ISIN change)."""
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository


def _mk_repo(td):
    mgr = DatabaseManager(db_path=Path(td) / "t.db")
    return Repository(manager=mgr), mgr


class TestMasterUpsert(unittest.TestCase):
    def test_placeholder_promotion(self):
        with tempfile.TemporaryDirectory() as td:
            repo, mgr = _mk_repo(td)
            repo.upsert_master_companies([{
                "isin": "INE_AUTO_AAREYDRUGS", "nse_symbol": "AAREYDRUGS",
                "company_name": "AAREYDRUGS", "is_active": 1}])
            with mgr.session() as conn:
                conn.execute(
                    "INSERT INTO daily_price_delivery (date, symbol, isin, series, open, high, low, close, prev_close,"
                    " change_pct, total_volume, deliverable_volume, delivery_pct)"
                    " VALUES ('2026-08-28','AAREYDRUGS','INE_AUTO_AAREYDRUGS','EQ',1,1,1,1,1,0,10,5,50.0)")
            n = repo.upsert_master_companies([{
                "isin": "INE198H01019", "nse_symbol": "AAREYDRUGS",
                "company_name": "Aarey Drugs", "is_active": 1}])
            self.assertGreater(n, 0)
            with mgr.session() as conn:
                rows = conn.execute("SELECT isin, nse_symbol, is_active FROM master_companies WHERE nse_symbol='AAREYDRUGS'").fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["isin"], "INE198H01019")
                stub = conn.execute("SELECT nse_symbol, is_active FROM master_companies WHERE isin='INE_AUTO_AAREYDRUGS'").fetchone()
                self.assertIsNone(stub["nse_symbol"])
                self.assertEqual(stub["is_active"], 0)
                px = conn.execute("SELECT DISTINCT isin FROM daily_price_delivery WHERE symbol='AAREYDRUGS'").fetchall()
                self.assertEqual([r[0] for r in px], ["INE198H01019"])
                cnt = conn.execute("SELECT COUNT(*) FROM daily_price_delivery").fetchone()[0]
                self.assertEqual(cnt, 1)

    def test_real_isin_change_frees_symbol(self):
        with tempfile.TemporaryDirectory() as td:
            repo, mgr = _mk_repo(td)
            repo.upsert_master_companies([{
                "isin": "INE0LZF01013", "nse_symbol": "CORDELIA",
                "company_name": "Old", "is_active": 1}])
            repo.upsert_master_companies([{
                "isin": "INE0LZF01039", "nse_symbol": "CORDELIA",
                "company_name": "New", "is_active": 1}])
            with mgr.session() as conn:
                rows = conn.execute("SELECT isin FROM master_companies WHERE nse_symbol='CORDELIA'").fetchall()
                self.assertEqual([r[0] for r in rows], ["INE0LZF01039"])
                old = conn.execute("SELECT nse_symbol, is_active FROM master_companies WHERE isin='INE0LZF01013'").fetchone()
                self.assertIsNone(old["nse_symbol"])
                self.assertEqual(old["is_active"], 0)

    def test_intra_batch_dedupe(self):
        with tempfile.TemporaryDirectory() as td:
            repo, mgr = _mk_repo(td)
            repo.upsert_master_companies([
                {"isin": "INE_AUTO_DUP", "nse_symbol": "DUPX", "company_name": "stub", "is_active": 1},
                {"isin": "INE111A01011", "nse_symbol": "DUPX", "company_name": "real", "is_active": 1},
            ])
            with mgr.session() as conn:
                rows = conn.execute("SELECT isin FROM master_companies WHERE nse_symbol='DUPX'").fetchall()
                self.assertEqual([r[0] for r in rows], ["INE111A01011"])

    def test_placeholder_incoming_skipped_when_real_holds_symbol(self):
        with tempfile.TemporaryDirectory() as td:
            repo, mgr = _mk_repo(td)
            repo.upsert_master_companies([{
                "isin": "INEREAL00001", "nse_symbol": "KEEP", "company_name": "Real", "is_active": 1}])
            repo.upsert_master_companies([{
                "isin": "INE_AUTO_KEEP", "nse_symbol": "KEEP", "company_name": "KEEP", "is_active": 1}])
            with mgr.session() as conn:
                rows = conn.execute("SELECT isin FROM master_companies WHERE nse_symbol='KEEP'").fetchall()
                self.assertEqual([r[0] for r in rows], ["INEREAL00001"])


if __name__ == "__main__":
    unittest.main()
