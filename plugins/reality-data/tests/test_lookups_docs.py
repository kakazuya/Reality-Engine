"""Fixture tests for plugins/reality-data/server/lookups_docs.py.

Run from the repo root:
    python -m unittest discover -s plugins/reality-data/tests -p "test_*.py"

No production database, Drive archive or model is touched: five tiny SQLite
stores plus a DuckDB document-list snapshot are built under the worktree's
``.tmp/`` and ``core.DB_FILES`` / ``core.snapshot_path`` are pointed at them.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import sys
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import duckdb

ROOT = Path(__file__).resolve().parents[3]
SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
TMP = ROOT / ".tmp"
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
DECK2_SHA = "b" * 64
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
CREATE INDEX idx_docs_sym_date ON corporate_documents(symbol, doc_date DESC);
CREATE TABLE substrate_quarantine (
    rule_id TEXT, table_name TEXT, row_key TEXT, severity TEXT
);
"""
DECK_SCHEMA = """
CREATE TABLE deck_sources (
    source TEXT, source_id TEXT, symbol TEXT, isin TEXT, known_at TEXT,
    title TEXT, url TEXT, local_path TEXT, status TEXT, sha256 TEXT
);
CREATE INDEX ix_deck_sources_isin ON deck_sources(isin, known_at);
CREATE TABLE doc_pages (sha256 TEXT, n_pages INTEGER);
CREATE TABLE pages (sha256 TEXT, page_no INTEGER, text_chars INTEGER, n_facts INTEGER);
CREATE TABLE facts (
    sha256 TEXT, page_no INTEGER, prompt_version TEXT, model TEXT, line_no INTEGER,
    metric TEXT, period TEXT, raw_number TEXT, value REAL, unit TEXT, is_final INTEGER
);
CREATE TABLE outputs (sha256 TEXT, page_no INTEGER, raw_output TEXT);
CREATE INDEX ix_facts_page ON facts(sha256, page_no);
"""
CONCALL_SCHEMA = """
CREATE TABLE cc_docs (
    doc_id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT, filed_at TEXT,
    status TEXT, chars INTEGER, period_discussed TEXT
);
CREATE TABLE cc_items (
    doc_id INTEGER, isin TEXT, filed_at TEXT, list_name TEXT, metric TEXT, quote TEXT
);
CREATE INDEX idx_cc_items_isin ON cc_items(isin, filed_at);
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
CREATE INDEX ar_facts_isin ON ar_facts(isin);
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


def _scratch_dir() -> Path:
    """A unique writable dir under the worktree's ``.tmp/``.

    ``tempfile.mkdtemp`` creates the directory with mode 0o700, which this
    Windows sandbox turns into an ACL the test process cannot write to; a
    plain 0o755 mkdir inherits the writable workspace ACL.
    """
    TMP.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        path = TMP / f"lookups_docs_test_{os.getpid()}_{time.time_ns()}"
        try:
            path.mkdir(mode=0o755, parents=False, exist_ok=False)
            return path
        except FileExistsError:
            continue
    raise RuntimeError("could not create a scratch directory under .tmp/")


class _FakePage:
    def __init__(self, text: str):
        self._text = text

    def get_text(self, _mode: str) -> str:
        return self._text


class _FakePdf:
    page_count = 1

    def __init__(self, text: str):
        self._text = text

    def __getitem__(self, _index: int) -> _FakePage:
        return _FakePage(self._text)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class LookupDocTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = _scratch_dir()
        cls.deck2_pdf = cls.dir / "deck_b.pdf"
        cls.deck2_pdf.write_bytes(b"not a real pdf; the fitz module is patched")
        cls._old_files = dict(core.DB_FILES)
        paths = {key: cls.dir / f"{key}.db" for key in cls._old_files}
        core.DB_FILES.clear()
        core.DB_FILES.update(paths)
        cls.snapshot = cls.dir / "truth_test.duckdb"
        cls._build_snapshot(cls.snapshot)
        cls._patches = [
            mock.patch.object(core, "resolve_one", return_value=dict(IDENTITY)),
            mock.patch.object(core, "snapshot_path", return_value=cls.snapshot),
            mock.patch.object(lookup, "_fetch_pdf", return_value=(None, "not configured")),
        ]
        for patcher in cls._patches:
            patcher.start()
        core.close_all()

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
                  "2026-08-06T20:44:09"),
                 (801, ISIN, "TESTCO", "CONCALL_TRANSCRIPT", "Q1 FY27 transcript (2nd id)",
                  "2026-08-06", "https://example/transcript2.pdf", None, None, None,
                  "2026-08-06T18:00:00"),
                 (502, ISIN, "TESTCO", "INVESTOR_PRESENTATION", "Investor Presentation Q1 FY27",
                  "2026-08-07", "https://example/deck.pdf", None, DECK_SHA, None,
                  "2026-08-07T13:48:57.647")])
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
                  r"C:\gone\deck.pdf", "ok", DECK_SHA),
                 ("bse", "2", "TESTCO", ISIN, "2026-08-07T15:00:00.000",
                  "Investor Presentation - Q1 FY27 (revised)", "https://example/deck2.pdf",
                  str(cls.deck2_pdf), "ok", DECK2_SHA)])
        _insert(con, "INSERT INTO doc_pages VALUES (?,?)",
                [(DECK_SHA, 31), (DECK2_SHA, 2)])
        _insert(con, "INSERT INTO pages VALUES (?,?,?,?)",
                [(DECK_SHA, 10, 613, 2), (DECK2_SHA, 1, 80, 0)])
        _insert(con, "INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(DECK_SHA, 10, "v1", "m", 1, "R&D facility", "-", "100,000", 100000.0,
                  "sq. ft.", 1)])
        _insert(con, "INSERT INTO outputs VALUES (?,?,?)",
                [(DECK_SHA, 10, "TITLE | Other Business Updates\n"
                                "R&D facility | - | 100,000 | sq. ft."),
                 (DECK2_SHA, 1, "facility capacity expanded in Q2")])
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
                  "count", "FY26", "standalone", "fuel cell licence to manufacture"),
                 (802, 1, "INE999999999", "TESTCO", "2026-09-03T10:00:00", 5, "business",
                  "Wrong-company licence", "1", 1.0, "count", "FY26", "standalone",
                  "wrong company licence to manufacture")])
        con.close()

        con = sqlite3.connect(paths["bse_announcements"])
        con.executescript(BSE_SCHEMA)
        con.close()

    @staticmethod
    def _build_snapshot(path: Path) -> None:
        con = duckdb.connect(str(path))
        con.execute("CREATE TABLE ar_docs (doc_id BIGINT, isin VARCHAR, symbol VARCHAR, "
                    "company VARCHAR, fiscal_year VARCHAR, filed_at VARCHAR, sha256 VARCHAR, "
                    "n_pages BIGINT, n_text_pages BIGINT, status VARCHAR)")
        con.execute("CREATE TABLE cc_docs (doc_id BIGINT, isin VARCHAR, symbol VARCHAR, "
                    "filed_at VARCHAR, chars BIGINT, period_discussed VARCHAR, status VARCHAR)")
        con.execute("CREATE TABLE bse_ann (NEWSID VARCHAR, SCRIP_CD VARCHAR, symbol VARCHAR, "
                    "NEWS_DT VARCHAR, DissemDT VARCHAR, NEWSSUB VARCHAR, HEADLINE VARCHAR, "
                    "ATTACHMENTNAME VARCHAR)")
        con.executemany("INSERT INTO ar_docs VALUES (?,?,?,?,?,?,?,?,?,?)", [
            (800, ISIN, "TESTCO", "Test Company Limited", "FY26", "2026-09-01T10:00:00",
             None, 79, 78, "ok"),
            (801, ISIN, "TESTCO", "Test Company Limited", "FY26", "2026-09-02T10:00:00",
             None, 10, 10, "ok"),
        ])
        con.executemany("INSERT INTO cc_docs VALUES (?,?,?,?,?,?,?)", [
            (700, ISIN, "TESTCO", "2026-08-06T20:44:09.827", 55036, "Q1 FY27", "ok"),
        ])
        con.executemany("INSERT INTO bse_ann VALUES (?,?,?,?,?,?,?,?)", [
            ("news-1", "500001", "TESTCO", "2026-08-20T18:00:00", "2026-08-20T18:00:00",
             "Investor presentation", "Investor presentation", None),
        ])
        con.close()

    @classmethod
    def tearDownClass(cls):
        for patcher in reversed(cls._patches):
            patcher.stop()
        core.close_all()
        core.DB_FILES.clear()
        core.DB_FILES.update(cls._old_files)
        shutil.rmtree(cls.dir, ignore_errors=True)

    # -- docs ---------------------------------------------------------------
    def test_docs_lists_distinct_same_day_documents(self):
        out = lookup.docs("TESTCO")
        self.assertTrue(out["found"])
        self.assertEqual(out["count"], 8)
        self.assertEqual(len(out["documents"]), 8)
        self.assertEqual(out["warnings"], [])
        self.assertFalse(out["partial"])
        self.assertEqual([d["doc_type"] for d in out["documents"][:2]],
                         ["ar", "announcement"])

        decks = [d for d in out["documents"] if d["doc_type"] == "deck"]
        self.assertEqual({d["keys"]["sha256"] for d in decks}, {DECK_SHA, DECK2_SHA})
        self.assertEqual({d["date"] for d in decks}, {"2026-08-07"})
        first = next(d for d in decks if d["keys"]["sha256"] == DECK_SHA)
        self.assertEqual(first["pages"], 31)
        self.assertTrue(first["has_facts"])
        # Same filing seen from corporate_documents merges by sha256.
        self.assertIn("corporate_documents", {s["store"] for s in first["stores"]})

        transcripts = [d for d in out["documents"] if d["doc_type"] == "transcript"]
        stores = {s["store"] for d in transcripts for s in d["stores"]}
        self.assertEqual(stores, {"concall_facts", "document_chunks", "corporate_documents"})
        self.assertTrue(any(d["keys"].get("doc_id") == 801 for d in transcripts))

    def test_docs_filters_type_and_range(self):
        out = lookup.docs("TESTCO", "deck", "2026-08-01", "2026-08-10")
        self.assertEqual(out["count"], 2)
        self.assertEqual({d["keys"]["sha256"] for d in out["documents"]},
                         {DECK_SHA, DECK2_SHA})
        with self.assertRaises(core.DataError):
            lookup.docs("TESTCO", "nonsense")
        with self.assertRaises(core.DataError):
            lookup.docs("TESTCO", date_from="2026-09-01", date_to="2026-08-01")

    def test_docs_limit_caps_output(self):
        one = lookup.docs("TESTCO", limit=1)
        self.assertEqual(one["count"], 1)
        self.assertEqual(len(one["documents"]), 1)
        self.assertEqual(one["filters"]["limit"], 1)
        five = lookup.docs("TESTCO", limit=5)
        self.assertEqual(five["count"], 5)
        self.assertEqual(len(five["documents"]), 5)

    def test_docs_nothing_found_points_at_nearest(self):
        out = lookup.docs("TESTCO", "transcript", "2026-01-01", "2026-01-02")
        self.assertFalse(out["found"])
        self.assertTrue(out["checked"])
        self.assertTrue(out["nearest"])
        self.assertTrue(out["hint"])
        self.assertEqual(out["warnings"], [])
        self.assertFalse(out["partial"])

    # -- doc_page -----------------------------------------------------------
    def test_doc_page_deck_falls_back_to_stored_extraction(self):
        out = lookup.doc_page("TESTCO", "2026-08-07", 10, doc_type="deck")
        self.assertTrue(out["found"])
        self.assertEqual(out["date_matched"], "2026-08-07")
        self.assertEqual(out["days_apart"], 0)
        self.assertEqual(out["page"], 10)
        self.assertEqual(out["page_count"], 31)
        self.assertEqual(out["page_label"], "page 10 of 31")
        self.assertEqual(out["text_source"], "stored_extraction")
        self.assertFalse(out["full_page_text"])
        self.assertFalse(out["fetched"])
        # D10: the failed Drive fetch must be surfaced even when stored text exists.
        self.assertEqual(out["fetch_note"], "not configured")
        self.assertIn("100,000 sq. ft.", out["text"])
        self.assertEqual(out["facts"][0]["metric"], "R&D facility")
        self.assertEqual(out["warnings"], [])

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
    def test_doc_find_default_doc_type_does_not_crash(self):
        # D1: the documented default (no doc_type) hit deck.get() on a Row.
        out = lookup.doc_find("TESTCO", "facility")
        self.assertTrue(out["found"])
        self.assertTrue(any(p["store"] == "deck_figures" for p in out["passages"]))
        self.assertEqual(out["warnings"], [])

    def test_doc_find_transcript_quote_with_page_and_chunk_index(self):
        out = lookup.doc_find("TESTCO", "fuel cell", doc_type="transcript", date="2026-08-06")
        self.assertTrue(out["found"])
        chunk = next(p for p in out["passages"] if p["store"] == "document_chunks")
        self.assertEqual(chunk["doc_type"], "transcript")
        self.assertEqual(chunk["page"], 10)
        self.assertEqual(chunk["chunk_index"], 1)
        self.assertIn("fuel cell capacity", chunk["quote"])

    def test_doc_find_ar_uses_isin_owner_only(self):
        # D4: the symbol branch scanned ar_facts; only the company ISIN may match.
        out = lookup.doc_find("TESTCO", "licence", doc_type="ar")
        self.assertTrue(out["found"])
        self.assertEqual({p["doc_id"] for p in out["passages"]}, {800})
        self.assertNotIn(802, {p["doc_id"] for p in out["passages"]})

    def test_quarantine_applies_to_ar_docs_not_corporate_ids(self):
        # D9: ar_facts doc id 801 is quarantined; corporate_documents.id 801 is
        # a different filing (same value) and must stay visible.
        out = lookup.doc_find("TESTCO", "fuel cell", doc_type="ar")
        self.assertFalse([p for p in (out.get("passages") or []) if p.get("doc_id") == 801])
        listed = lookup.docs("TESTCO", "ar")
        self.assertEqual([d["keys"]["doc_id"] for d in listed["documents"]], [800])
        transcripts = lookup.docs("TESTCO", "transcript")
        corporate_ids = {s["keys"]["doc_id"] for d in transcripts["documents"]
                         for s in d["stores"] if s["store"] == "corporate_documents"}
        self.assertIn(801, corporate_ids)

    def test_doc_find_deck_falls_back_for_older_deck(self):
        # D7: after the newest deck's local PDF matched, older decks must still
        # try their stored extraction.
        fake_fitz = types.SimpleNamespace(
            open=lambda _path: _FakePdf("facility capacity expanded in Q2"))
        with mock.patch.dict(sys.modules, {"fitz": fake_fitz}):
            out = lookup.doc_find("TESTCO", "facility", doc_type="deck")
        self.assertTrue(out["found"])
        self.assertEqual({p["doc_id"] for p in out["passages"]}, {DECK_SHA, DECK2_SHA})

    def test_doc_find_nothing_returns_nearest(self):
        out = lookup.doc_find("TESTCO", "zirconium", doc_type="transcript", date="2026-08-06")
        self.assertFalse(out["found"])
        self.assertTrue(out["nearest"])
        self.assertTrue(out["hint"])

    # -- warnings / partial / budgets --------------------------------------
    def test_store_error_sets_partial_and_names_store(self):
        # D5: an unindexed/slow store used to return [] and look complete.
        real = lookup._run_sqlite

        def flaky(store, sql, params=(), timeout=15.0):
            if store == "deck_figures":
                raise core.DataError("query_timeout", "simulated")
            return real(store, sql, params, timeout=timeout)

        with mock.patch.object(lookup, "_run_sqlite", side_effect=flaky):
            out = lookup.docs("TESTCO")
        self.assertTrue(out["found"])
        self.assertTrue(out["partial"])
        self.assertTrue(any(w.startswith("deck_figures") and "query_timeout" in w
                            for w in out["warnings"]))

    def test_store_listed_from_duckdb_with_indexed_sqlite_filter(self):
        # D6: announcements come from DuckDB; corporate_documents filters the
        # real indexed symbol column instead of upper()/COALESCE scans.
        queries, ducks = [], []
        real_query, real_duck = lookup._query, lookup._duck

        def query_spy(*args, **kwargs):
            queries.append((args[0], args[1], args[4]))
            return real_query(*args, **kwargs)

        def duck_spy(*args, **kwargs):
            ducks.append((args[0], args[1]))
            return real_duck(*args, **kwargs)

        with mock.patch.object(lookup, "_query", side_effect=query_spy), \
                mock.patch.object(lookup, "_duck", side_effect=duck_spy):
            out = lookup.docs("TESTCO")
        self.assertTrue(out["found"])
        self.assertFalse(any(store == "bse_announcements" for store, _sql, _l in queries))
        corp = next(sql for store, sql, label in queries
                    if label == "equity_intelligence.corporate_documents")
        self.assertIn("symbol IN", corp)
        self.assertNotIn("upper(symbol)", corp)
        self.assertTrue(any(label == "truth_duckdb.bse_ann" for label, _sql in ducks))

    def test_over_budget_store_is_skipped_with_warning(self):
        with mock.patch.object(lookup, "STORE_BUDGET_S", -1.0):
            out = lookup.docs("TESTCO")
        self.assertFalse(out["found"])
        self.assertTrue(out["partial"])
        self.assertIn("deck_figures skipped: no index on isin", out["warnings"])

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
