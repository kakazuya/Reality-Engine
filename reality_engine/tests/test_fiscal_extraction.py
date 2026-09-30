"""Hermetic tests for fiscal-period extraction (findings §11, temp DBs only).

Covers the ticket acceptance:
  * every pattern family P1-P6 (+P7) with priority/tie-breaks/confidence
  * header-noise rejection: a chunk whose ONLY FY signal is the machine
    header (``FY:`` literal / empty ``FY:  ``) labels NONE
  * multi-conflict → NULL + MULTI + 0.2
  * migration idempotency (columns + idx_chunks_fiscal, twice)
  * insert stamps FY at chunk-row write (pdf_ingestor path)
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.processing.document_parser import (
    chunk_body,
    extract_fiscal_period,
)

HDR = "[Metadata: Symbol: HAL | FY:   | Doc: CONCALL | Date: 2026-08-14]"


def body(text: str) -> str:
    return extract_fiscal_period(text)


class ExtractorPatternsTest(unittest.TestCase):
    def test_p1_quarter_grain(self):
        self.assertEqual(body("results for Q2FY24 were strong"), ("Q2FY24", 1.0, "QFY"))
        self.assertEqual(body("Q3 FY 2025 guidance raised"), ("Q3FY25", 1.0, "QFY"))
        self.assertEqual(body("Q1FY2024-25 revenue grew"), ("Q1FY25", 1.0, "QFY"))

    def test_p2_fy_range(self):
        self.assertEqual(body("Union Budget FY2023-24 outlay"), ("FY24", 0.9, "FY_RANGE"))
        self.assertEqual(body("Economic Survey FY 2024-25 notes"), ("FY25", 0.9, "FY_RANGE"))
        self.assertEqual(body("plan FY2023-2024 period"), ("FY24", 0.9, "FY_RANGE"))

    def test_p3_fy_short(self):
        period, conf, src = body("capex guidance for FY24")
        self.assertEqual((period, src), ("FY24", "FY_SHORT"))
        self.assertGreaterEqual(conf, 0.5)

    def test_p4_fy_year(self):
        self.assertEqual(body("outlook for FY2025 remains"), ("FY25", 0.9, "FY_YEAR"))

    def test_p5_anchored_yy_range(self):
        period, conf, src = body("fiscal year 2024-25 was strong")
        self.assertEqual((period, conf, src), ("FY25", 0.5, "YY_RANGE"))
        # Unanchored bare range: no signal.
        self.assertEqual(body("page 2024-25 of 300"), (None, 0.0, "NONE"))

    def test_p6_quarter_end_date(self):
        # June 2024 → Q1 of FY ending Mar 2025.
        self.assertEqual(
            body("results for the quarter ended 30 June 2024"),
            ("Q1FY25", 0.3, "QTR_DATE"),
        )
        # March 2024 → Q4 of FY ending Mar 2024.
        self.assertEqual(
            body("quarter ended March 31, 2024 review"),
            ("Q4FY24", 0.3, "QTR_DATE"),
        )

    def test_p7_half_year(self):
        self.assertEqual(body("H1FY25 review meeting"), ("H1FY25", 1.0, "H_FY"))

    def test_priority_p1_over_p2_over_p4(self):
        period, conf, src = body("FY2023-24 results; Q2FY24 concall; FY2025 outlook")
        self.assertEqual((period, conf, src), ("Q2FY24", 1.0, "QFY"))
        period, conf, src = body("FY2023-24 budget vs FY2025 outlook")
        self.assertEqual((period, conf, src), ("FY24", 0.9, "FY_RANGE"))

    def test_p6_never_overrides(self):
        period, _, src = body("FY2025 outlook; quarter ended December 2024 review")
        self.assertEqual(period, "FY25")
        self.assertEqual(src, "FY_YEAR")

    def test_same_tier_rightmost_wins(self):
        period, _, src = body("Q1FY24 review; Q3FY24 results section")
        self.assertEqual(period, "Q3FY24")
        self.assertEqual(src, "QFY")

    def test_same_tier_conflict_null_multi(self):
        self.assertEqual(
            body("FY2023-24 budget versus FY2024-25 survey"),
            (None, 0.2, "MULTI"),
        )
        self.assertEqual(
            body("Q1FY24 review then Q3FY25 outlook"),
            (None, 0.2, "MULTI"),
        )

    def test_url_guard(self):
        text = "see https://cdn.example.com/FY24/icon.png for details"
        self.assertEqual(body(text), (None, 0.0, "NONE"))

    def test_normalization(self):
        self.assertEqual(body("FY 25 push")[0], "FY25")
        self.assertEqual(body("FY2024 note")[0], "FY24")


class HeaderNoiseTest(unittest.TestCase):
    def test_header_only_fy_is_none(self):
        # Raw stored content: literal FY: in header, empty body signal.
        content = HDR + "\nrevenue grew across segments this quarter"
        self.assertEqual(extract_fiscal_period(chunk_body(content)), (None, 0.0, "NONE"))

    def test_header_fy_value_ignored_body_wins(self):
        hdr = "[Metadata: Symbol: HAL | FY: 2021 | Doc: CONCALL | Date: 2026-08-14]"
        content = hdr + "\nQ2FY24 results were strong"
        self.assertEqual(
            extract_fiscal_period(chunk_body(content)), ("Q2FY24", 1.0, "QFY")
        )

    def test_naive_raw_match_would_fire_but_body_does_not(self):
        content = HDR + "\nplain operating review, no period mentioned"
        # The literal "FY:" exists in raw content (naive-regex noise) …
        self.assertIn("FY:", content)
        # … but the body extractor stays silent.
        self.assertEqual(extract_fiscal_period(chunk_body(content)), (None, 0.0, "NONE"))

    def test_chunk_body_splits_first_newline(self):
        self.assertEqual(chunk_body(HDR + "\nQ2FY24 strong"), "Q2FY24 strong")
        self.assertEqual(chunk_body("no header here FY24"), "no header here FY24")


class MigrationIdempotencyTest(unittest.TestCase):
    def test_columns_and_index_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = DatabaseManager(db_path=Path(td) / "t.db")
            with mgr.session() as conn:
                cols = {r[1] for r in conn.execute("PRAGMA table_info(document_chunks)").fetchall()}
                self.assertTrue({"fiscal_period", "fiscal_confidence", "fiscal_source"} <= cols)
                idx = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_chunks_fiscal'").fetchall()}
                self.assertEqual(idx, {"idx_chunks_fiscal"})
            # Second init (migration re-run) must be a clean no-op.
            mgr2 = DatabaseManager(db_path=Path(td) / "t.db")
            with mgr2.session() as conn:
                n = conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
                self.assertEqual(n, 0)

    def test_legacy_table_gains_columns(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "legacy.db"
            conn = sqlite3.connect(str(db))
            conn.execute(
                "CREATE TABLE document_chunks (chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " doc_id INTEGER, chunk_index INTEGER NOT NULL, content TEXT NOT NULL,"
                " embedding TEXT, published_date TEXT, symbol TEXT, isin TEXT,"
                " UNIQUE(doc_id, chunk_index))"
            )
            conn.commit()
            conn.close()
            DatabaseManager(db_path=db)
            conn = sqlite3.connect(str(db))
            cols = {r[1] for r in conn.execute("PRAGMA table_info(document_chunks)").fetchall()}
            conn.close()
            self.assertTrue({"fiscal_period", "fiscal_confidence", "fiscal_source"} <= cols)


class InsertStampTest(unittest.TestCase):
    def test_persist_stamps_fy_per_chunk(self):
        from reality_engine.ingestion.pdf_ingestor import PDFIngestor
        from reality_engine.tests.conftest import get_shared_ocr_engine

        class StubVS:
            def embed_many(self, texts):
                return [[0.1] * 4 for _ in texts]

            def embed(self, text):
                return [0.1] * 4

            def add_chunks(self, recs):
                return len(recs)

        with tempfile.TemporaryDirectory() as td:
            mgr = DatabaseManager(db_path=Path(td) / "t.db")
            ing = PDFIngestor(db=mgr, vector_store=StubVS(), ocr_engine=get_shared_ocr_engine())
            res = ing.ingest_text(
                "Q2FY24 results call. " * 30 + "Revenue grew strongly across defence segments. " * 30,
                title="HAL concall", source_type="CONCALL", published_date="2026-08-14",
                symbol="HAL", isin="INE066F01020",
            )
            self.assertEqual(res["status"], "ingested")
            with mgr.session() as conn:
                rows = conn.execute(
                    "SELECT fiscal_period, fiscal_confidence, fiscal_source, content"
                    " FROM document_chunks WHERE symbol='HAL'").fetchall()
                self.assertGreater(len(rows), 0)
                for r in rows:
                    fp = r["fiscal_period"] if hasattr(r, "keys") else r[0]
                    fc = r["fiscal_confidence"] if hasattr(r, "keys") else r[1]
                    fs = r["fiscal_source"] if hasattr(r, "keys") else r[2]
                    self.assertEqual(fp, "Q2FY24")
                    self.assertEqual(fc, 1.0)
                    self.assertEqual(fs, "QFY")

    def test_backfill_labels_null_rows(self):
        from reality_engine.scripts.backfill_fiscal_periods import backfill_fiscal_periods

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "t.db"
            mgr = DatabaseManager(db_path=db)
            with mgr.session() as conn:
                conn.execute(
                    "INSERT INTO raw_documents (title, source_type, published_date) VALUES (?,?,?)",
                    ("d", "CONCALL", "2026-08-14"),
                )
                doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.executemany(
                    "INSERT INTO document_chunks (doc_id, chunk_index, content) VALUES (?,?,?)",
                    [
                        (doc_id, 0, HDR + "\nFY2023-24 budget review of segments"),
                        (doc_id, 1, HDR + "\nplain operating review, nothing dated"),
                    ],
                )
            summary = backfill_fiscal_periods(db, batch_size=5)
            self.assertEqual(summary["rows_scanned"], 2)
            self.assertEqual(summary["rows_labeled"], 1)
            with mgr.session() as conn:
                got = {r["chunk_index"]: (r["fiscal_period"], r["fiscal_source"]) for r in conn.execute(
                    "SELECT chunk_index, fiscal_period, fiscal_source FROM document_chunks ORDER BY chunk_index").fetchall()}
                self.assertEqual(got[0], ("FY24", "FY_RANGE"))
                self.assertEqual(got[1], (None, "NONE"))
            # Re-run is idempotent: nothing left NULL.
            summary2 = backfill_fiscal_periods(db, batch_size=5)
            self.assertEqual(summary2["rows_scanned"], 0)


if __name__ == "__main__":
    unittest.main()
