"""Fixture tests for plugins/reality-data/server/lookups_docs.py.

Run from the repo root:
    python -m unittest discover -s plugins/reality-data/tests -p "test_*.py"

No production database, Drive archive or model is touched: five tiny SQLite
stores are built in a temp dir and ``core.DB_FILES`` is pointed at them.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVER_DIR))

import core  # noqa: E402
import lookups_docs as lookup  # noqa: E402
from reality_engine.toolbelt import lookup_docs as cli  # noqa: E402

ISIN = "INE000000001"
IDENTITY = {
    "isin": ISIN,
    "name": "Test Company Limited",
    "nse_symbol": "TESTCO",
    "bse_symbol": "TESTCO",
    "bse_code": "500001",
    "segment": "",
    "status": "",
    "isin_history": [{"exchange": "NSE", "symbol": "TESTCO", "isin": ISIN}],
    "match_type": "symbol",
    "score": 95,
}

DECK_SHA = "a" * 64
EQUITY_SCHEMA = """
CREATE TABLE document_chunks (
    chunk_id INTEGER PRIMARY KEY, doc_id INTEGER, chunk_index INTEGER,
    content TEXT, published_date TEXT, symbol TEXT, isin TEXT
);
CREATE INDEX idx_docchunks_doc ON document_chunks(doc_id, chunk_index);
CREATE INDEX idx_docchunks_symbol ON document_chunks(symbol);
CREATE TABLE corporate_documents (
    id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT, doc_type TEXT, title TEXT,
    doc_date TEXT, source_url TEXT, local_file_path TEXT, sha256_hash TEXT,
    bse_newsid TEXT, bse_dissem_ts TEXT, publication_date TEXT, call_date TEXT
);
CREATE TABLE substrate_quarantine (
    rule_id TEXT, table_name TEXT, row_key TEXT, severity TEXT
);
"""
DECK_SCHEMA = """
CREATE TABLE deck_sources (
    source TEXT, source_id TEXT, symbol TEXT, isin TEXT, known_at TEXT,
    title TEXT, url TEXT, local_path TEXT, status TEXT, sha256 TEXT
);
CREATE TABLE doc_pages (sha256 TEXT, n_pages INTEGER);
CREATE TABLE pages (sha256 TEXT, page_no INTEGER, text_chars INTEGER, n_facts INTEGER);
CREATE TABLE facts (
    sha256 TEXT, page_no INTEGER, prompt_version TEXT, model TEXT, line_no INTEGER,
    metric TEXT, period TEXT, raw_number TEXT, value REAL, unit TEXT, is_final INTEGER
);
CREATE TABLE outputs (sha256 TEXT, page_no INTEGER, raw_output TEXT);
"""
CONCALL_SCHEMA = """
CREATE TABLE cc_docs (
    doc_id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT, filed_at TEXT,
    status TEXT, chars INTEGER, period_discussed TEXT
);
CREATE TABLE cc_items (
    doc_id INTEGER, isin TEXT, filed_at TEXT, list_name TEXT, metric TEXT, quote TEXT
);
"""
AR_SCHEMA = """
CREATE TABLE ar_docs (
    doc_id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT, company TEXT,
    fiscal_year TEXT, filed_at TEXT, sha256 TEXT, path TEXT, n_pages INTEGER,
    n_text_pages INTEGER, status TEXT
);
CREATE TABLE ar_facts (
    doc_id INTEGER, piece INTEGER, isin TEXT, symbol TEXT, filed_at TEXT, page INTEGER,
    category TEXT, item TEXT, value_raw TEXT, value REAL, unit TEXT, period TEXT,
    basis TEXT, quote TEXT
);
CREATE INDEX ar_facts_doc ON ar_facts(doc_id, piece);
"""
BSE_SCHEMA = """
CREATE TABLE ann (
    NEWSID TEXT, SCRIP_CD TEXT, ATTACHMENTNAME TEXT, NEWSSUB TEXT, HEADLINE TEXT,
    NEWS_DT TEXT, DissemDT TEXT, symbol TEXT
);
"""


def _insert(con, sql, rows=()):
    con.executemany(sql, rows)
    con.commit()


class LookupDocTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = None
        cls.dir = Path(".tmp") / f"lookups_docs_test_{os.getpid()}"
        cls.dir.mkdir(parents=True, exist_ok=True)
        cls._old_files = dict(core.DB_FILES)
        paths = {key: cls.dir / f"{key}.db" for key in cls._old_files}
        core.DB_FILES.clear()
        core.DB_FILES.update(paths)
        cls.snapshot = cls.dir / "truth_2026-01-01.duckdb"
        cls.snapshot.write_bytes(b"")
        cls._patches = [
            mock.patch.object(core, "resolve_one", return_value=dict(IDENTITY)),
            mock.patch.object(core, "snapshot_path", return_value=cls.snapshot),
            mock.patch.object(lookup, "_fetch_pdf", return_value=(None, "not configured")),
        ]
        for patcher in cls._patches:
            patcher.start()
        core._sqlite_conns.clear()
        core._quarantine = None

        con = sqlite3.connect(paths["equity_intelligence"])
        con.executescript(EQUITY_SCHEMA)
        _insert(con, "INSERT INTO substrate_quarantine VALUES (?,?,?,?)",
                [("q1", "ar_facts", "801", "high")])
        _insert(con, "INSERT INTO corporate_documents "
                     "(id, isin, symbol, doc_type, title, doc_date, source_url, "
                     "local_file_path, sha256_hash, bse_newsid, bse_dissem_ts) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(501, ISIN, "TESTCO", "CONCALL_TRANSCRIPT", "Q1 FY27 earnings call transcript",
                  "2026-08-06", "https://example/transcript.pdf", None, None, None,
                  "2026-08-06T20:44:09")])
        for index, text in enumerate([
            "management opened the call. page 1 of 19",
            "we expect fuel cell capacity to expand. page 10 of 19",
            "closing remarks. page 19 of 19",
        ]):
            _insert(con, "INSERT INTO document_chunks (chunk_id, doc_id, chunk_index, content, "
                         "published_date, symbol, isin) VALUES (?,?,?,?,?,?,?)",
                    [(index + 1, 900, index,
                      "[Metadata: Symbol: TESTCO | FY: | Doc: CONCALL_TRANSCRIPT | Date: 2026-08-06]\n"
                      + text, "2026-08-06", "TESTCO", ISIN)])
        con.close()

        con = sqlite3.connect(paths["deck_figures"])
        con.executescript(DECK_SCHEMA)
        _insert(con, "INSERT INTO deck_sources VALUES (?,?,?,?,?,?,?,?,?,?)",
                [("bse", "1", "TESTCO", ISIN, "2026-08-07T13:48:57.647",
                  "Investor Presentation - Q1 FY27", "https://example/deck.pdf",
                  r"C:\gone\deck.pdf", "ok", DECK_SHA)])
        _insert(con, "INSERT INTO doc_pages VALUES (?,?)", [(DECK_SHA, 31)])
        _insert(con, "INSERT INTO pages VALUES (?,?,?,?)", [(DECK_SHA, 10, 613, 2)])
        _insert(con, "INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(DECK_SHA, 10, "v1", "m", 1, "R&D facility", "-", "100,000", 100000.0,
                  "sq. ft.", 1)])
        _insert(con, "INSERT INTO outputs VALUES (?,?,?)",
                [(DECK_SHA, 10, "TITLE | Other Business Updates\n"
                                "R&D facility | - | 100,000 | sq. ft.")])
        con.close()

        con = sqlite3.connect(paths["concall_facts"])
        con.executescript(CONCALL_SCHEMA)
        _insert(con, "INSERT INTO cc_docs VALUES (?,?,?,?,?,?,?)",
                [(700, ISIN, "TESTCO", "2026-08-06T20:44:09.827", "ok", 55036, "Q1 FY27")])
        _insert(con, "INSERT INTO cc_items VALUES (?,?,?,?,?,?)",
                [(700, ISIN, "2026-08-06", "capacity_and_projects", "fuel cell capacity",
                  "we expect fuel cell capacity to expand")])
        con.close()

        con = sqlite3.connect(paths["ar_facts"])
        con.executescript(AR_SCHEMA)
        _insert(con, "INSERT INTO ar_docs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(800, ISIN, "TESTCO", "Test Company Limited", "FY26", "2026-09-01T10:00:00",
                  None, r"C:\gone\ar.pdf", 79, 78, "ok"),
                 (801, ISIN, "TESTCO", "Test Company Limited", "FY26", "2026-09-02T10:00:00",
                  None, None, 10, 10, "ok")])
        _insert(con, "INSERT INTO ar_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(800, 1, ISIN, "TESTCO", "2026-09-01T10:00:00", 21, "business",
                  "Manufacturing licence", "1", 1.0, "count", "FY26", "standalone",
                  "The company received a licence to manufacture defence equipment."),
                 (801, 1, ISIN, "TESTCO", None, 3, "business", "Fuel cell note", "1", 1.0,
                  "count", "FY26", "standalone", "fuel cell licence to manufacture")])
        con.close()

        con = sqlite3.connect(paths["bse_announcements"])
        con.executescript(BSE_SCHEMA)
        _insert(con, "INSERT INTO ann VALUES (?,?,?,?,?,?,?,?)",
                [("news-1", "500001", None, "Investor presentation", "Investor presentation",
                  "2026-08-20T18:00:00", "2026-08-20T18:00:00", "TESTCO")])
        con.close()

    @classmethod
    def tearDownClass(cls):
        for patcher in reversed(cls._patches):
            patcher.stop()
        core._sqlite_conns.clear()
        core.DB_FILES.clear()
        core.DB_FILES.update(cls._old_files)
        core._quarantine = None
        shutil.rmtree(cls.dir, ignore_errors=True)

    # -- docs ---------------------------------------------------------------
    def test_docs_lists_and_merges_stores(self):
        out = lookup.docs("TESTCO")
        self.assertTrue(out["found"])
        self.assertEqual([d["doc_type"] for d in out["documents"]],
                         ["ar", "announcement", "deck", "transcript"])
        deck = next(d for d in out["documents"] if d["doc_type"] == "deck")
        self.assertEqual(deck["date"], "2026-08-07")
        self.assertEqual(deck["pages"], 31)
        self.assertEqual(deck["keys"]["sha256"], DECK_SHA)
        self.assertTrue(deck["has_facts"])
        transcript = next(d for d in out["documents"] if d["doc_type"] == "transcript")
        stores = {s["store"] for s in transcript["stores"]}
        self.assertEqual(stores, {"concall_facts", "document_chunks", "corporate_documents"})
        self.assertTrue(transcript["has_facts"])
        self.assertIn("checked", out)
        self.assertTrue(out["provenance"])

    def test_docs_filters_type_and_range(self):
        out = lookup.docs("TESTCO", "deck", "2026-08-01", "2026-08-10")
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["documents"][0]["keys"]["sha256"], DECK_SHA)
        with self.assertRaises(core.DataError):
            lookup.docs("TESTCO", "nonsense")
        with self.assertRaises(core.DataError):
            lookup.docs("TESTCO", date_from="2026-09-01", date_to="2026-08-01")

    def test_docs_nothing_found_points_at_nearest(self):
        out = lookup.docs("TESTCO", "transcript", "2026-01-01", "2026-01-02")
        self.assertFalse(out["found"])
        self.assertTrue(out["checked"])
        self.assertTrue(out["nearest"])
        self.assertTrue(out["hint"])

    # -- doc_page -----------------------------------------------------------
    def test_doc_page_deck_falls_back_to_stored_extraction(self):
        out = lookup.doc_page("TESTCO", "2026-08-07", 10)
        self.assertTrue(out["found"])
        self.assertEqual(out["date_matched"], "2026-08-07")
        self.assertEqual(out["days_apart"], 0)
        self.assertEqual(out["page"], 10)
        self.assertEqual(out["page_count"], 31)
        self.assertEqual(out["page_label"], "page 10 of 31")
        self.assertEqual(out["text_source"], "stored_extraction")
        self.assertFalse(out["full_page_text"])
        self.assertIn("100,000 sq. ft.", out["text"])
        self.assertEqual(out["facts"][0]["metric"], "R&D facility")

    def test_doc_page_transcript_uses_page_chunk(self):
        out = lookup.doc_page("TESTCO", "2026-08-06", 10, doc_type="transcript")
        self.assertTrue(out["found"])
        self.assertEqual(out["page_count"], 19)
        self.assertEqual(out["text_source"], "stored_chunk")
        self.assertIn("fuel cell capacity", out["text"])
        self.assertNotIn("[Metadata:", out["text"])

    def test_doc_page_ar_page_and_label(self):
        out = lookup.doc_page("TESTCO", "2026-09-01", 21, doc_type="ar")
        self.assertTrue(out["found"])
        self.assertEqual(out["page_label"], "page 21 of 79")
        self.assertIn("licence to manufacture", out["text"])
        self.assertTrue(out["facts"])

    def test_doc_page_nothing_near_date(self):
        out = lookup.doc_page("TESTCO", "2027-01-01", 1)
        self.assertFalse(out["found"])
        self.assertTrue(out["nearest"])
        self.assertTrue(any(n["days_apart"] for n in out["nearest"]))

    # -- doc_find -----------------------------------------------------------
    def test_doc_find_transcript_quote_with_page(self):
        out = lookup.doc_find("TESTCO", "fuel cell", doc_type="transcript", date="2026-08-06")
        self.assertTrue(out["found"])
        passage = out["passages"][0]
        self.assertEqual(passage["doc_type"], "transcript")
        self.assertEqual(passage["page"], 10)
        self.assertIn("fuel cell capacity", passage["quote"])

    def test_doc_find_nothing_returns_nearest(self):
        out = lookup.doc_find("TESTCO", "zirconium", doc_type="transcript", date="2026-08-06")
        self.assertFalse(out["found"])
        self.assertTrue(out["nearest"])
        self.assertTrue(out["hint"])

    def test_quarantine_excludes_ar_doc(self):
        out = lookup.doc_find("TESTCO", "fuel cell", doc_type="ar")
        self.assertFalse([p for p in (out.get("passages") or []) if p.get("doc_id") == 801])
        listed = lookup.docs("TESTCO", "ar")
        self.assertEqual([d["keys"]["doc_id"] for d in listed["documents"]], [800])

    # -- CLI ----------------------------------------------------------------
    def test_cli_prints_json(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(["docs", "TESTCO", "--doc-type", "deck"])
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["found"])
        self.assertEqual(payload["documents"][0]["doc_type"], "deck")


if __name__ == "__main__":
    unittest.main()
