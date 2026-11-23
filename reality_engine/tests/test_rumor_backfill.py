"""Tests for reality_engine.processing.rumor_backfill (news-feed Tier-2)."""
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.processing.rumor_backfill import backfill_telegram_fts
from reality_engine.search.intel_search import tier_of


def _seed(mgr):
    rows = [
        ("ch_1", "c1", "Chan", 1, "RELIANCE breaks out on heavy volumes",
         "", '["RELIANCE"]', "2026-09-18 10:00:00"),
        ("ch_2", "c1", "Chan", 2, "",
         "", '["TCS"]', "2026-09-17 09:00:00"),
        ("ch_3", "c1", "Chan", 3, "another rumor without symbols",
         "", "{bad json", "2026-09-16 08:00:00"),
    ]
    with mgr.session() as conn:
        for pid, ch, title, mid, text, ocr, syms, ts in rows:
            conn.execute(
                "INSERT INTO telegram_posts (id, channel_id, channel_title, message_id,"
                " raw_message_text, ocr_extracted_text, detected_symbols_json,"
                " post_timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, ch, title, mid, text, ocr, syms, ts),
            )


class TestRumorBackfill(unittest.TestCase):
    def test_backfill_idempotent_and_mapping(self):
        self.assertEqual(tier_of("TELEGRAM_POST"), 2)
        with tempfile.TemporaryDirectory() as td:
            mgr = DatabaseManager(db_path=Path(td) / "test.db")
            _seed(mgr)
            first = backfill_telegram_fts(db=mgr)
            self.assertEqual(first,
                             {"posts_seen": 3, "chunks_written": 2,
                              "skipped_empty": 1, "skipped_dup": 0})
            with mgr.session() as conn:
                got = {r["chunk_id"]: dict(r) for r in conn.execute(
                    "SELECT chunk_id, symbol, isin, source_type, document_date,"
                    " document_text FROM intelligence_fts").fetchall()}
            self.assertEqual(set(got), {"tg:ch_1", "tg:ch_3"})
            self.assertEqual(got["tg:ch_1"]["symbol"], "RELIANCE")
            self.assertEqual(got["tg:ch_1"]["document_date"], "2026-09-18")
            self.assertEqual(got["tg:ch_1"]["source_type"], "TELEGRAM_POST")
            self.assertEqual(got["tg:ch_1"]["isin"], "")
            self.assertIn("breaks out", got["tg:ch_1"]["document_text"])
            self.assertEqual(got["tg:ch_3"]["symbol"], "")
            self.assertEqual(got["tg:ch_3"]["document_date"], "2026-09-16")
            second = backfill_telegram_fts(db=mgr)
            self.assertEqual(second["chunks_written"], 0)
            self.assertEqual(second["posts_seen"], 3)
            self.assertEqual(second["skipped_dup"], 2)
            self.assertEqual(second["skipped_empty"], 1)
            with mgr.session() as conn:
                n = conn.execute("SELECT COUNT(*) FROM intelligence_fts").fetchone()[0]
            self.assertEqual(n, 2)


if __name__ == "__main__":
    unittest.main()
