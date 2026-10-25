"""Fast fixture tests for plugins/reality-data/server/search_docs.py.

Run:  python plugins/reality-data/tests/test_search_docs.py
No production database, model download or GPU is touched.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

import search_docs  # noqa: E402


EQUITY_SCHEMA = """
CREATE TABLE raw_documents (
    doc_id INTEGER PRIMARY KEY, title TEXT, source_type TEXT,
    published_date TEXT, source_url TEXT
);
CREATE TABLE document_chunks (
    chunk_id INTEGER PRIMARY KEY, doc_id INTEGER, chunk_index INTEGER,
    content TEXT, published_date TEXT, symbol TEXT, isin TEXT
);
CREATE VIRTUAL TABLE intelligence_fts USING fts5(
    chunk_id UNINDEXED, symbol, isin, source_type UNINDEXED,
    document_date UNINDEXED, document_text, tokenize='porter unicode61'
);
CREATE TABLE master_companies (
    isin TEXT PRIMARY KEY, nse_symbol TEXT, bse_code TEXT, company_name TEXT
);
CREATE TABLE substrate_quarantine (
    rule_id TEXT, table_name TEXT, row_key TEXT, severity TEXT
);
CREATE TABLE corporate_documents (
    id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT, doc_type TEXT,
    title TEXT, doc_date TEXT, source_url TEXT
);
"""

AR_SCHEMA = """
CREATE TABLE ar_docs (
    doc_id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT, company TEXT,
    fiscal_year TEXT, filed_at TEXT
);
CREATE TABLE ar_facts (
    doc_id INTEGER, piece INTEGER, isin TEXT, symbol TEXT, fiscal_year TEXT,
    filed_at TEXT, page INTEGER, category TEXT, item TEXT, value_raw TEXT,
    value REAL, unit TEXT, period TEXT, basis TEXT, quote TEXT, model TEXT,
    value_check TEXT, prompt_version TEXT
);
CREATE INDEX ar_facts_doc ON ar_facts(doc_id, piece);
CREATE VIRTUAL TABLE ar_facts_fts USING fts5(
    item, category, content='ar_facts', content_rowid='rowid',
    tokenize='unicode61'
);
"""


def _connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode = WAL")
    return con


def _chunk(con, chunk_id, doc_id, text, symbol="", isin="", date=""):
    con.execute(
        "INSERT INTO document_chunks(chunk_id, doc_id, chunk_index, content, published_date, symbol, isin) "
        "VALUES (?,?,?,?,?,?,?)",
        (chunk_id, doc_id, 0, text, date, symbol, isin),
    )
    con.execute(
        "INSERT INTO intelligence_fts(chunk_id, symbol, isin, source_type, document_date, document_text) "
        "SELECT ?, ?, ?, source_type, ?, ? FROM raw_documents WHERE doc_id = ?",
        (str(chunk_id), symbol, isin, date, text, doc_id),
    )


FIXTURE = Path(__file__).resolve().parent / "fixtures"
KEEP = {".gitkeep", ".gitignore"}


class SearchDocsTest(unittest.TestCase):
    def setUp(self):
        # Fixture databases live in the checked-in fixtures/ directory (ignored
        # by git).  Creating the parent (instead of tempfile's per-test
        # subdirectory) also works under the agent's Windows file sandbox.
        FIXTURE.mkdir(exist_ok=True)
        for path in FIXTURE.iterdir():
            if path.is_dir():
                shutil.rmtree(path)
            elif path.name not in KEEP:
                path.unlink()
        self.root = FIXTURE
        self._old_env = {
            key: os.environ.get(key)
            for key in ("REALITY_DATA_ROOT", "REALITY_ENGINE_DATA_DIR")
        }
        os.environ["REALITY_DATA_ROOT"] = str(self.root)
        os.environ["REALITY_ENGINE_DATA_DIR"] = str(self.root / "engine-data")
        search_docs.close()
        self._build_fixture()

    def tearDown(self):
        search_docs.close()
        for path in self.root.iterdir():
            if path.is_dir():
                shutil.rmtree(path)
            elif path.name not in KEEP:
                path.unlink()
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _build_fixture(self):
        eq = _connect(self.root / "equity_intelligence.db")
        eq.executescript(EQUITY_SCHEMA)
        docs = [
            (1, "CONCOR Annual Report 2025-26", "ANNUAL_REPORT", "2026-09-23", "https://example.com/concor-ar.pdf"),
            (2, "RBI Monetary Policy Statement", "RBI_Monetary_Policy", "2026-10-07", "https://example.com/rbi.pdf"),
            (3, "ACME Q4 FY25 Earnings Call", "CONCALL_TRANSCRIPT", "2025-05-05", "https://example.com/acme-call.pdf"),
            (4, "ACME Annual Report 2023-24", "ANNUAL_REPORT", "2024-01-01", "https://example.com/acme-ar.pdf"),
        ]
        eq.executemany(
            "INSERT INTO raw_documents(doc_id, title, source_type, published_date, source_url) VALUES (?,?,?,?,?)",
            docs,
        )
        eq.executemany(
            "INSERT INTO master_companies VALUES (?,?,?,?)",
            [
                ("INE111A01025", "CONCOR", "531344", "Container Corporation of India Ltd"),
                ("INE050001010", "PPL", "542684", "Prakash Pipes Ltd"),
                ("INE999A01010", "ACME", "500001", "Acme Industries Ltd"),
            ],
        )
        eq.execute(
            "INSERT INTO corporate_documents VALUES (900,?,?,?,?,?,?)",
            (
                "INE050001010",
                "PPL",
                "ANNUAL_REPORT",
                "Prakash Pipes Annual Report 2019-20",
                "2020-09-08",
                "https://example.com/ppl-ar-2020.pdf",
            ),
        )
        eq.executemany(
            "INSERT INTO substrate_quarantine VALUES (?,?,?,?)",
            [
                ("synthetic_isin_companies", "master_companies", "INE_AUTO_99999", "quarantine"),
                ("noise_fixture", "document_chunks", "400", "quarantine"),
                ("ar_wrong_company_pdf", "ar_facts", "901", "quarantine"),
            ],
        )
        _chunk(eq, 100, 1, "Container volumes grew 12% as the segment revenue improved.", "CONCOR", "INE111A01025", "2026-09-23")
        _chunk(eq, 200, 2, "The Monetary Policy Committee took the decision to keep the repo rate unchanged at 5.50%.", "", "", "2026-10-07")
        _chunk(eq, 300, 3, "ACME segment revenue and order book guidance for the year.", "ACME", "INE999A01010", "2025-05-05")
        _chunk(eq, 301, 4, "ACME annual report segment revenue split by division.", "ACME", "INE999A01010", "2024-01-01")
        _chunk(eq, 302, 3, "Synthetic backfill chunk mentioning segment revenue.", "542684", "INE_AUTO_99999", "2025-05-05")
        _chunk(eq, 400, 4, "Quarantined fixture chunk mentioning segment revenue.", "ACME", "INE999A01010", "2024-01-01")
        eq.commit()
        eq.close()

        ar = _connect(self.root / "ar_facts.db")
        ar.executescript(AR_SCHEMA)
        ar.executemany(
            "INSERT INTO ar_docs(doc_id, isin, symbol, company, fiscal_year, filed_at) VALUES (?,?,?,?,?,?)",
            [
                (900, "INE050001010", "PPL", "Prakash Pipes Ltd", "FY2020", "2020-09-08T12:00:00"),
                (901, "INE050001010", "PPL", "Prakash Pipes Ltd", "FY2020", "2020-09-08T12:00:00"),
            ],
        )
        facts = [
            (900, "INE050001010", "PPL", "2020-09-08T12:00:00", 68, "segment_info",
             "Segment Revenue: PVC Pipe and Fitting", "33296", "a)PVC Pipe and Fitting 33296"),
            (900, "INE050001010", "PPL", "2020-09-08T12:00:00", 68, "segment_info",
             "Total Segment Revenue", "34096", "Total 34096"),
            (901, "INE050001010", "PPL", "2020-09-08T12:00:00", 12, "segment_info",
             "Segment Revenue: quarantined fixture", "1", "quarantined segment revenue"),
        ]
        for doc_id, isin, symbol, filed_at, page, category, item, value, quote in facts:
            ar.execute(
                "INSERT INTO ar_facts(doc_id, isin, symbol, fiscal_year, filed_at, page, category, "
                "item, value_raw, quote, value_check) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (doc_id, isin, symbol, "FY2020", filed_at, page, category, item, value, quote, "found"),
            )
        ar.execute(
            "INSERT INTO ar_facts_fts(rowid, item, category) "
            "SELECT rowid, item, category FROM ar_facts"
        )
        ar.commit()
        ar.close()

    # ------------------------------------------------------------------
    def test_lexical_symbol_metadata(self):
        rows = search_docs.search_docs("container volumes", symbol="CONCOR")
        self.assertTrue(rows)
        top = rows[0]
        self.assertEqual(top["doc_type"], "annual_report")
        self.assertEqual(top["symbol"], "CONCOR")
        self.assertEqual(top["isin"], "INE111A01025")
        self.assertEqual(top["date"], "2026-09-23")
        self.assertEqual(top["url"], "https://example.com/concor-ar.pdf")
        self.assertEqual(top["source"], "fts")
        self.assertIsNone(top["page"])
        self.assertIn("Container volumes", top["text"])
        self.assertEqual(
            set(top),
            {"text", "doc_id", "doc_type", "symbol", "isin", "date",
             "page", "url", "score", "source"},
        )

    def test_doc_type_filter(self):
        rows = search_docs.search_docs("segment revenue", symbol="ACME", doc_types=["concall"])
        self.assertTrue(rows)
        self.assertTrue(all(r["doc_type"] == "concall" for r in rows))

        rows = search_docs.search_docs("segment revenue", symbol="ACME", doc_types=["annual_report"])
        self.assertTrue(rows)
        self.assertTrue(all(r["doc_type"] == "annual_report" for r in rows))

    def test_date_filter(self):
        rows = search_docs.search_docs("container volumes", symbol="CONCOR", date_from="2026")
        self.assertTrue(rows)
        rows = search_docs.search_docs("container volumes", symbol="CONCOR", date_to="2025")
        self.assertFalse(rows)

    def test_quarantine_filters(self):
        rows = search_docs.search_docs("segment revenue", symbol="ACME", top_k=20)
        self.assertTrue(rows)
        joined = " ".join(r["text"] for r in rows)
        self.assertNotIn("Synthetic backfill", joined)
        self.assertNotIn("Quarantined fixture", joined)
        self.assertNotIn("INE_AUTO", " ".join(r["isin"] for r in rows))

    def test_ppl_annual_report_facts(self):
        rows = search_docs.search_docs("segment revenue", symbol="PPL")
        self.assertTrue(rows)
        top = rows[0]
        self.assertEqual(top["doc_type"], "annual_report")
        self.assertEqual(top["symbol"], "PPL")
        self.assertEqual(top["date"], "2020-09-08")
        self.assertEqual(top["page"], 68)
        self.assertEqual(top["url"], "https://example.com/ppl-ar-2020.pdf")
        self.assertEqual(top["source"], "fts")
        self.assertTrue(any("33296" in row["text"] for row in rows))

    def test_rbi_policy_query(self):
        rows = search_docs.search_docs("repo rate decision", doc_types=["rbi"])
        self.assertTrue(rows)
        self.assertTrue(all(r["doc_type"] == "rbi" for r in rows))
        self.assertIn("repo rate", rows[0]["text"].lower())

    def test_fts_only_fallback_status(self):
        status = search_docs.warm()
        self.assertFalse(status["vector"])
        self.assertEqual(status["fallback"], "fts-only")
        rows = search_docs.search_docs("container volumes", symbol="CONCOR")
        self.assertTrue(rows)
        self.assertTrue(all(r["source"] == "fts" for r in rows))

    def test_vector_fusion_marks_both(self):
        index_dir = self.root / "vector_index"
        index_dir.mkdir(exist_ok=True)
        import numpy as np

        vectors = np.zeros((2, 384), dtype=np.float32)
        vectors[0, 0] = 1.0     # chunk 100
        vectors[1, 1] = 1.0     # chunk 200
        np.save(index_dir / "chunk_vectors.npy", vectors)
        np.save(index_dir / "chunk_ids.npy", np.array([100, 200], dtype=np.int64))
        (index_dir / "chunk_index_meta.json").write_text(
            json.dumps({"rows": 2, "dim": 384}), encoding="utf-8"
        )

        class FakeEmbedder:
            def embed(self, text, is_query=False):
                return [1.0] + [0.0] * 383

        with mock.patch.object(search_docs, "_embedder_hint", return_value=True), \
                mock.patch.object(search_docs, "_load_embedder", return_value=FakeEmbedder()):
            status = search_docs.warm(force=True)
            self.assertTrue(status["vector"])
            rows = search_docs.search_docs("container volumes", symbol="CONCOR")
        self.assertTrue(rows)
        self.assertEqual(rows[0]["source"], "fts+local_dense")

    def test_seed_dense_returns_fts_miss_without_paid_call(self):
        index_dir = self.root / "vector_index_nemotron8b"
        index_dir.mkdir(exist_ok=True)
        import numpy as np
        import query_embed

        vectors = np.zeros((2, 4096), dtype=np.float16)
        vectors[0, 0] = 1.0     # chunk 100, the only FTS hit
        vectors[1, 0] = 1.0     # chunk 200, a paraphrase FTS misses
        np.save(index_dir / "chunk_vectors.npy", vectors)
        np.save(index_dir / "chunk_ids.npy", np.array([100, 200], dtype=np.int64))
        (index_dir / "chunk_index_meta.json").write_text(
            json.dumps({"rows": 2, "dim": 4096}), encoding="utf-8"
        )
        old = os.environ.pop("REALITY_DATA_ALLOW_PAID_EMBED", None)
        try:
            with mock.patch.object(query_embed, "CACHE_DIR", self.root / ".qcache_compact"), \
                    mock.patch.object(search_docs.dense_free, "QCACHE_DIR",
                                      self.root / ".qcache_vectors"), \
                    mock.patch.object(query_embed, "_call",
                                      side_effect=AssertionError("paid embed called")), \
                    mock.patch.object(query_embed, "embed_query",
                                      side_effect=AssertionError("paid embed called")):
                query_embed.close()
                search_docs.warm(force=True)
                rows = search_docs.search_docs("container volumes", top_k=5)
        finally:
            search_docs.dense_free.clear()
            query_embed.close()
            if old is not None:
                os.environ["REALITY_DATA_ALLOW_PAID_EMBED"] = old
        self.assertTrue(rows)
        seed_hit = next(r for r in rows if "repo rate" in r["text"])
        self.assertIn("seed_dense", seed_hit["source"])
        self.assertEqual(rows[0]["source"], "fts+seed_dense")

    def test_as_of_drops_future_rows_and_counts_them(self):
        result = search_docs.search_docs(
            "segment revenue", symbol="ACME", top_k=20, as_of="2024-12-31"
        )
        self.assertIsInstance(result, dict)
        self.assertEqual(result["as_of"], "2024-12-31")
        self.assertGreaterEqual(result["hidden_after_as_of"], 1)
        self.assertTrue(result["results"])
        self.assertTrue(all(r["date"] <= "2024-12-31" for r in result["results"]))
        self.assertFalse(
            any("order book guidance" in r["text"] for r in result["results"])
        )
        # Without as_of the list contract is unchanged.
        self.assertIsInstance(
            search_docs.search_docs("segment revenue", symbol="ACME"), list
        )

    def test_invalid_date_rejected(self):
        with self.assertRaises(ValueError):
            search_docs.search_docs("revenue", date_from="2026-13-01")


if __name__ == "__main__":
    unittest.main(verbosity=2)
