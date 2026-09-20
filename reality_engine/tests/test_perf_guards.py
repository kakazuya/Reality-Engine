"""Performance guards — embedding memoization, chunk indexes, planner-stat refresh.

Each of these guards fails if the corresponding optimisation is removed *or* if it is
re-introduced incorrectly (the two bugs actually hit while building them: a cache that
could be mutated through its returned list, and a stats refresh that never converged).
"""

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.vector_store import VectorStoreManager


class TestEmbeddingMemoization(unittest.TestCase):
    """O4: identical (text, is_query) must not re-run the embedder."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vecstore_"))
        self.store = VectorStoreManager(db_path=self.tmp)
        self.calls = []
        original = self.store._embed_uncached

        def counting(text, is_query=False):
            self.calls.append((text, is_query))
            return original(text, is_query)

        self.store._embed_uncached = counting  # type: ignore[assignment]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_repeated_query_embeds_once(self):
        first = self.store.embed("order book capex", is_query=True)
        second = self.store.embed("order book capex", is_query=True)
        third = self.store.embed("order book capex", is_query=True)
        self.assertEqual(len(self.calls), 1, f"expected one embed call, got {self.calls}")
        self.assertEqual(first, second)
        self.assertEqual(second, third)

    def test_distinct_texts_and_flags_are_separate_entries(self):
        self.store.embed("alpha", is_query=True)
        self.store.embed("beta", is_query=True)
        self.store.embed("alpha", is_query=False)  # same text, different role
        self.assertEqual(len(self.calls), 3)

    def test_cached_vector_cannot_be_corrupted_through_the_returned_list(self):
        """A cache that hands out its stored list lets callers mutate other callers' data."""
        stored = self.store.embed("gamma", is_query=True)
        baseline = list(stored)
        stored[0] = 999.0  # caller scribbles on the result
        self.assertEqual(self.store.embed("gamma", is_query=True), baseline)


class TestChunkLookupIndexes(unittest.TestCase):
    """O5: symbol/isin-scoped chunk reads must use an index, not a full scan.

    ``document_chunks`` is created at runtime by the ingest path (pdf_ingestor /
    youtube_transcriber), not by schema.sql, so on a *fresh* database it does not exist
    when init_db's migrations first run. The indexes are therefore created on the next
    DatabaseManager construction -- which is what this test exercises, because that is the
    real path a fresh checkout takes.
    """

    _CHUNKS_DDL = (
        "CREATE TABLE IF NOT EXISTS document_chunks ("
        " chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " doc_id INTEGER REFERENCES raw_documents(doc_id) ON DELETE CASCADE,"
        " chunk_index INTEGER NOT NULL, content TEXT NOT NULL, embedding TEXT,"
        " published_date TEXT, timestamp_start_sec INTEGER, timestamp_end_sec INTEGER,"
        " sector_id INTEGER, industry_id INTEGER, symbol TEXT, isin TEXT,"
        " UNIQUE(doc_id, chunk_index))"
    )

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chunkidx_"))
        self.db_path = self.tmp / "chunks.db"
        self.mgr = DatabaseManager(db_path=self.db_path)
        with self.mgr.session() as conn:
            conn.execute(self._CHUNKS_DDL)  # ingest-time creation, as in production
            conn.execute(
                "INSERT INTO raw_documents (doc_id, title, source_type, published_date) "
                "VALUES (1, 't', 'CONCALL_TRANSCRIPT', '2026-01-01')"
            )
            conn.executemany(
                "INSERT INTO document_chunks (doc_id, chunk_index, content, symbol, isin) "
                "VALUES (1, ?, ?, ?, ?)",
                [(i, f"chunk {i}", "HAL" if i % 2 else "TCS", "INE066F01020") for i in range(200)],
            )
        # Next process start: init_db reruns the idempotent migrations.
        self.mgr = DatabaseManager(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_indexes_created_by_migration(self):
        with self.mgr.session() as conn:
            names = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='document_chunks'"
                ).fetchall()
            }
        self.assertIn("idx_docchunks_symbol", names)
        self.assertIn("idx_docchunks_isin", names)

    def test_symbol_lookup_uses_the_index(self):
        with self.mgr.session() as conn:
            plan = " ".join(
                r[3] for r in conn.execute(
                    "EXPLAIN QUERY PLAN SELECT chunk_id, content FROM document_chunks "
                    "WHERE symbol = ? LIMIT 5", ("HAL",)
                ).fetchall()
            )
        self.assertIn("USING INDEX idx_docchunks_symbol", plan, plan)
        self.assertNotIn("SCAN document_chunks", plan, plan)


class TestPlannerStatRefresh(unittest.TestCase):
    """O6: stats refresh must detect real drift and then converge to a no-op."""

    _ROWS = 1200

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="plannerstats_"))
        self.mgr = DatabaseManager(db_path=self.tmp / "stats.db")
        with self.mgr.session() as conn:
            conn.executemany(
                "INSERT INTO nse_index_breadth (date, index_name, change_pct, close) VALUES (?,?,?,?)",
                [(f"2026-01-{i % 28 + 1:02d}", f"IDX{i}", 0.0, float(i)) for i in range(self._ROWS)],
            )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_large_table_ends_up_with_fresh_stats_then_converges(self):
        """Outcome contract: a large table has statistics afterwards, and re-running is a no-op.

        Which mechanism does it is deliberately not asserted: ``PRAGMA optimize`` covers
        tables that have never been analysed, and the drift check below covers statistics
        that exist but are stale on disk.
        """
        self.mgr.optimize()
        with self.mgr.session() as conn:
            stat = conn.execute(
                "SELECT stat FROM sqlite_stat1 WHERE tbl = 'nse_index_breadth' LIMIT 1"
            ).fetchone()
        self.assertIsNotNone(stat, "no statistics recorded for a 1200-row table")
        self.assertEqual(self.mgr.optimize(), {})

    def test_detects_injected_drift_and_repairs_it(self):
        self.mgr.optimize()  # establish fresh stats
        with self.mgr.session() as conn:
            conn.execute(
                "UPDATE sqlite_stat1 SET stat = '1 1' WHERE tbl = 'nse_index_breadth'"
            )
        repaired = self.mgr.optimize()
        self.assertIn("nse_index_breadth", repaired, repaired)
        self.assertIn("drift", repaired["nse_index_breadth"])
        with self.mgr.session() as conn:
            stat = conn.execute(
                "SELECT stat FROM sqlite_stat1 WHERE tbl = 'nse_index_breadth' LIMIT 1"
            ).fetchone()[0]
        self.assertNotEqual(stat.split()[0], "1")
        self.assertEqual(self.mgr.optimize(), {})


if __name__ == "__main__":
    unittest.main()
