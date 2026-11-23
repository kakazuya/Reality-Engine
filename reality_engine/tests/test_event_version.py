"""Hermetic tests for the event-date/version migration (handover §4 item 1).

Temp DBs only — never touches the live DB or the queue lock. Mirrors the
fiscal pattern (backfill_fiscal_periods + test_fiscal_extraction):

  * columns + index + trigger land idempotently on all three tables
  * legacy tables (no event_* cols) gain them via migrate()
  * minimal DBs lacking raw_documents migrate cleanly (table skipped)
  * insert triggers stamp event_date/source/version without ingestion changes
  * explicit event values are never overwritten
  * backfill fills NULLs from published_date/doc_date; rerun is a no-op
  * --dry-run audit (describe) writes nothing
  * reader fallbacks work on legacy rows without event_* keys
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from reality_engine.scripts.migrate_event_version import (
    TABLES,
    describe,
    migrate,
    resolve_doc_version,
    resolve_event_date,
)

CHUNKS_LEGACY_DDL = (
    "CREATE TABLE document_chunks (chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " doc_id INTEGER, chunk_index INTEGER NOT NULL, content TEXT NOT NULL,"
    " embedding TEXT, published_date TEXT, timestamp_start_sec INTEGER,"
    " timestamp_end_sec INTEGER, sector_id INTEGER, industry_id INTEGER,"
    " symbol TEXT, isin TEXT, fiscal_period TEXT, fiscal_confidence REAL,"
    " fiscal_source TEXT, UNIQUE(doc_id, chunk_index))"
)

CORP_LEGACY_DDL = (
    "CREATE TABLE corporate_documents (id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " isin TEXT NOT NULL, symbol TEXT NOT NULL, doc_type TEXT NOT NULL,"
    " title TEXT NOT NULL, doc_date DATE NOT NULL, source_url TEXT,"
    " source TEXT, discovery_source TEXT, local_file_path TEXT,"
    " file_size_bytes INTEGER, sha256_hash TEXT, is_processed BOOLEAN DEFAULT 0,"
    " created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(source_url))"
)

RAW_LEGACY_DDL = (
    "CREATE TABLE raw_documents (doc_id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " title TEXT NOT NULL, source_type TEXT NOT NULL, published_date TEXT NOT NULL,"
    " fiscal_period TEXT, source_url TEXT, creator_or_ministry TEXT,"
    " created_at TEXT DEFAULT CURRENT_TIMESTAMP, sha256_hash TEXT UNIQUE,"
    " local_file_path TEXT, file_size_bytes INTEGER)"
)


def make_legacy_db(path: Path, with_raw: bool = True) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(CHUNKS_LEGACY_DDL)
    conn.execute(CORP_LEGACY_DDL)
    if with_raw:
        conn.execute(RAW_LEGACY_DDL)
    conn.commit()
    conn.close()


def cols_of(path: Path, table: str) -> set:
    conn = sqlite3.connect(str(path))
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        conn.close()


def index_names(path: Path) -> set:
    conn = sqlite3.connect(str(path))
    try:
        return {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
    finally:
        conn.close()


def trigger_names(path: Path) -> set:
    conn = sqlite3.connect(str(path))
    try:
        return {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
        }
    finally:
        conn.close()


class MigrationIdempotencyTest(unittest.TestCase):
    def test_columns_indexes_triggers_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "t.db"
            make_legacy_db(db)
            first = migrate(db, checkpoint=Path(td) / "ckpt.json")
            self.assertEqual(set(first["schema"]["tables"]), set(TABLES))
            for table, spec in TABLES.items():
                self.assertTrue(
                    {"event_date", "event_source", "doc_version"} <= cols_of(db, table),
                    table,
                )
                self.assertIn(spec["index"], index_names(db))
                self.assertIn(spec["trigger"], trigger_names(db))
            # Rerun is a clean no-op: nothing left to stamp.
            second = migrate(db, checkpoint=Path(td) / "ckpt.json")
            for table in TABLES:
                self.assertEqual(second["tables"][table]["scanned"], 0, table)

    def test_minimal_db_without_raw_documents(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "t.db"
            make_legacy_db(db, with_raw=False)
            summary = migrate(db, checkpoint=Path(td) / "ckpt.json")
            self.assertNotIn("raw_documents", summary["schema"]["tables"])
            self.assertNotIn("raw_documents", summary["tables"])
            self.assertTrue(
                {"event_date", "event_source", "doc_version"}
                <= cols_of(db, "document_chunks")
            )
            self.assertTrue(
                {"event_date", "event_source", "doc_version"}
                <= cols_of(db, "corporate_documents")
            )


class InsertTriggerStampTest(unittest.TestCase):
    def test_chunk_insert_stamps_from_published_date(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "t.db"
            make_legacy_db(db)
            migrate(db, checkpoint=Path(td) / "ckpt.json")
            conn = sqlite3.connect(str(db))
            conn.execute(
                "INSERT INTO document_chunks (doc_id, chunk_index, content, published_date)"
                " VALUES (1, 0, 'body text', '2024-05-17')"
            )
            conn.commit()
            row = conn.execute(
                "SELECT event_date, event_source, doc_version FROM document_chunks"
            ).fetchone()
            conn.close()
            self.assertEqual(row, ("2024-05-17", "published_date", 1))

    def test_corp_insert_stamps_from_doc_date(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "t.db"
            make_legacy_db(db)
            migrate(db, checkpoint=Path(td) / "ckpt.json")
            conn = sqlite3.connect(str(db))
            conn.execute(
                "INSERT INTO corporate_documents (isin, symbol, doc_type, title, doc_date)"
                " VALUES ('INE002A01018', 'RELIANCE', 'ANNUAL_REPORT', 'AR FY24', '2024-08-02')"
            )
            conn.commit()
            row = conn.execute(
                "SELECT event_date, event_source, doc_version FROM corporate_documents"
            ).fetchone()
            conn.close()
            self.assertEqual(row, ("2024-08-02", "doc_date", 1))

    def test_explicit_event_values_never_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "t.db"
            make_legacy_db(db)
            migrate(db, checkpoint=Path(td) / "ckpt.json")
            conn = sqlite3.connect(str(db))
            conn.execute(
                "INSERT INTO document_chunks (doc_id, chunk_index, content, published_date,"
                " event_date, event_source, doc_version)"
                " VALUES (1, 0, 'body', '2024-05-17', '2020-01-15', 'explicit', 7)"
            )
            conn.commit()
            row = conn.execute(
                "SELECT event_date, event_source, doc_version FROM document_chunks"
            ).fetchone()
            conn.close()
            self.assertEqual(row, ("2020-01-15", "explicit", 7))

    def test_null_fallback_stays_null_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "t.db"
            make_legacy_db(db)
            migrate(db, checkpoint=Path(td) / "ckpt.json")
            conn = sqlite3.connect(str(db))
            conn.execute(
                "INSERT INTO document_chunks (doc_id, chunk_index, content)"
                " VALUES (1, 0, 'undated body')"
            )
            conn.commit()
            row = conn.execute(
                "SELECT event_date, event_source, doc_version FROM document_chunks"
            ).fetchone()
            conn.close()
            self.assertEqual(row, (None, "unknown", 1))


class BackfillFillsNullsTest(unittest.TestCase):
    def test_legacy_rows_backfilled_rerun_noop(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "t.db"
            conn = sqlite3.connect(str(db))
            conn.execute(CHUNKS_LEGACY_DDL)
            conn.execute(CORP_LEGACY_DDL)
            conn.execute(RAW_LEGACY_DDL)
            # Legacy rows predate the triggers, so NULLs survive until migrate().
            conn.executemany(
                "INSERT INTO document_chunks (doc_id, chunk_index, content, published_date)"
                " VALUES (?,?,?,?)",
                [
                    (1, 0, "dated chunk", "2023-11-04"),
                    (1, 1, "undated chunk", None),
                ],
            )
            conn.execute(
                "INSERT INTO corporate_documents (isin, symbol, doc_type, title, doc_date)"
                " VALUES ('INE002A01018','RELIANCE','ANNUAL_REPORT','AR','2024-08-02')"
            )
            conn.execute(
                "INSERT INTO raw_documents (title, source_type, published_date)"
                " VALUES ('budget speech','Union_Budget','2025-02-01')"
            )
            conn.commit()
            conn.close()

            summary = migrate(db, batch_size=5, checkpoint=Path(td) / "ckpt.json")
            self.assertEqual(summary["tables"]["document_chunks"]["dated"], 1)
            self.assertEqual(summary["tables"]["document_chunks"]["still_null"], 1)
            self.assertEqual(summary["tables"]["corporate_documents"]["dated"], 1)
            self.assertEqual(summary["tables"]["raw_documents"]["dated"], 1)

            conn = sqlite3.connect(str(db))
            conn.row_factory = sqlite3.Row
            try:
                chunks = {
                    r["chunk_index"]: (r["event_date"], r["event_source"], r["doc_version"])
                    for r in conn.execute(
                        "SELECT chunk_index, event_date, event_source, doc_version"
                        " FROM document_chunks ORDER BY chunk_index"
                    ).fetchall()
                }
                self.assertEqual(chunks[0], ("2023-11-04", "published_date", 1))
                # Undateable row: honest NULL date, still versioned + labeled.
                self.assertEqual(chunks[1], (None, "unknown", 1))
                corp = conn.execute(
                    "SELECT event_date, event_source, doc_version FROM corporate_documents"
                ).fetchone()
                self.assertEqual(tuple(corp), ("2024-08-02", "doc_date", 1))
                raw = conn.execute(
                    "SELECT event_date, event_source, doc_version FROM raw_documents"
                ).fetchone()
                self.assertEqual(tuple(raw), ("2025-02-01", "published_date", 1))
                # content never rewritten by the migration.
                body = conn.execute(
                    "SELECT content FROM document_chunks WHERE chunk_index=0"
                ).fetchone()[0]
                self.assertEqual(body, "dated chunk")
            finally:
                conn.close()

            rerun = migrate(db, batch_size=5, checkpoint=Path(td) / "ckpt.json")
            for table in TABLES:
                self.assertEqual(rerun["tables"][table]["scanned"], 0, table)

    def test_checkpoint_resume(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "t.db"
            ckpt = Path(td) / "ckpt.json"
            conn = sqlite3.connect(str(db))
            conn.execute(CHUNKS_LEGACY_DDL)
            conn.execute(CORP_LEGACY_DDL)
            conn.executemany(
                "INSERT INTO document_chunks (doc_id, chunk_index, content, published_date)"
                " VALUES (?,?,?,?)",
                [(1, i, f"chunk {i}", f"2024-01-{i + 1:02d}") for i in range(5)],
            )
            conn.commit()
            conn.close()

            first = migrate(db, batch_size=2, limit=2, checkpoint=ckpt)
            self.assertEqual(first["tables"]["document_chunks"]["scanned"], 2)
            cursors = json.loads(ckpt.read_text(encoding="utf-8"))
            self.assertGreater(int(cursors["document_chunks"]), 0)

            second = migrate(db, batch_size=2, checkpoint=ckpt)
            total = (
                first["tables"]["document_chunks"]["scanned"]
                + second["tables"]["document_chunks"]["scanned"]
            )
            self.assertEqual(total, 5)
            self.assertEqual(second["tables"]["document_chunks"]["still_null"], 0)


class DryRunTest(unittest.TestCase):
    def test_describe_reports_pending_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "t.db"
            make_legacy_db(db)
            conn = sqlite3.connect(str(db))
            conn.execute(
                "INSERT INTO document_chunks (doc_id, chunk_index, content, published_date)"
                " VALUES (1, 0, 'x', '2024-01-01')"
            )
            conn.commit()
            conn.close()

            summary = describe(db)
            self.assertTrue(summary["dry_run"])
            chunks = summary["tables"]["document_chunks"]
            self.assertEqual(chunks["rows"], 1)
            self.assertEqual(chunks["pending_nulls"], 1)
            self.assertEqual(
                set(chunks["columns_missing"]), {"event_date", "event_source", "doc_version"}
            )
            self.assertFalse(chunks["index"])
            self.assertFalse(chunks["trigger"])
            self.assertFalse(summary["tables"]["raw_documents"]["index"])

            # Read-only: no DDL landed, no checkpoint file created.
            self.assertNotIn("event_date", cols_of(db, "document_chunks"))
            self.assertFalse((Path(td) / "migrate_event_version.checkpoint.json").exists())


class ReaderFallbackTest(unittest.TestCase):
    def test_legacy_row_without_event_keys(self):
        row = {"published_date": "2024-05-17", "doc_date": None}
        self.assertEqual(resolve_event_date(row), "2024-05-17")
        self.assertEqual(resolve_doc_version(row), 1)

    def test_explicit_event_wins(self):
        row = {"event_date": "2020-01-15", "published_date": "2024-05-17", "doc_version": 7}
        self.assertEqual(resolve_event_date(row), "2020-01-15")
        self.assertEqual(resolve_doc_version(row), 7)

    def test_nothing_dateable(self):
        self.assertIsNone(resolve_event_date({}))
        self.assertEqual(resolve_doc_version({}), 1)


if __name__ == "__main__":
    unittest.main()
