"""PIT contract for corporate_documents: v_document_pit never falls back to crawl dates."""
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository

_spec = importlib.util.spec_from_file_location(
    "apply_annual_report_pit", Path(__file__).resolve().parents[2] / "analysis" / "apply_annual_report_pit.py")
_ar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ar)


class DocumentPitTests(unittest.TestCase):
    def test_annual_report_filename_shapes(self):
        base = "https://www.bseindia.com/bseplus/AnnualReport/532343/"
        self.assertEqual(_ar.parse(base + "5323430320.pdf"), ("fpe", "2020-03-31"))
        self.assertEqual(_ar.parse(base + "66461532343_08_09_20.pdf"), ("pub", "2020-09-08"))
        self.assertIsNone(_ar.parse(base + "76549532343.pdf"))

    def test_view_prefers_feed_timestamp_and_never_uses_crawl_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = DatabaseManager(Path(tmp) / "t.db")
            db.init_db()
            repo = Repository(db)
            with db.session() as conn:
                conn.execute("INSERT OR IGNORE INTO master_companies(isin, nse_symbol, company_name) VALUES ('INE000A01010','AAA','Aaa Ltd')")
            base = {"isin": "INE000A01010", "symbol": "AAA", "doc_type": "CONCALL_TRANSCRIPT",
                    "title": "t", "doc_date": "2026-08-29"}
            repo.upsert_corporate_documents([
                {**base, "source_url": "u1", "bse_dissem_ts": "2024-05-02T18:40:11"},
                {**base, "source_url": "u2"},
            ])
            with db.session() as conn:
                rows = {r[0]: r for r in conn.execute(
                    "SELECT source_url, pit_ts, pit_basis, crawl_doc_date FROM v_document_pit")}
            self.assertEqual(rows["u1"][1:3], ("2024-05-02T18:40:11", "bse_feed"))
            self.assertIsNone(rows["u2"][1])
            self.assertEqual(rows["u2"][2], "unknown")


if __name__ == "__main__":
    unittest.main()
