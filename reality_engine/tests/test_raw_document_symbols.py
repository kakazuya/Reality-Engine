"""Contract for the raw_documents company-identity backfill (in-memory only)."""
import sqlite3
import unittest

from reality_engine.scripts import backfill_raw_document_symbols as bf


DDL = """
CREATE TABLE raw_documents (
    doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    published_date TEXT NOT NULL,
    source_url TEXT,
    local_file_path TEXT,
    file_size_bytes INTEGER
);
CREATE TABLE corporate_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    isin TEXT, symbol TEXT, doc_type TEXT, title TEXT,
    source_url TEXT, local_file_path TEXT
);
CREATE TABLE document_chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER,
    chunk_index INTEGER,
    symbol TEXT,
    isin TEXT
);
"""


class RawDocumentSymbolBackfillTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(DDL)

    def tearDown(self):
        self.conn.close()

    def add_doc(self, source_type, url=None, path=None):
        cur = self.conn.execute(
            "INSERT INTO raw_documents (title, source_type, published_date, source_url, local_file_path) "
            "VALUES ('ANNUAL_REPORT', ?, '2026-01-01', ?, ?)",
            (source_type, url, path))
        return int(cur.lastrowid)

    def add_chunk(self, doc_id, symbol, isin, n=1):
        self.conn.executemany(
            "INSERT INTO document_chunks (doc_id, chunk_index, symbol, isin) VALUES (?, ?, ?, ?)",
            [(doc_id, i, symbol, isin) for i in range(n)])

    def test_precedence_corporate_then_chunks_then_path(self):
        corp_path = r"C:\data\pdfs\CORP\ANNUAL_REPORT\a.pdf"
        corp_url = "https://example.test/corp.pdf"
        chunk_doc = self.add_doc("ANNUAL_REPORT")
        path_doc = self.add_doc("ANNUAL_REPORT",
                                path=r"C:\data\pdfs\PATHSYM\ANNUAL_REPORT\b.pdf")
        no_identity = self.add_doc("PIB_Press_Release", url="https://example.test/pib")
        self.add_doc("ANNUAL_REPORT")  # no path/url/chunks: stays without a symbol

        by_path = self.add_doc("ANNUAL_REPORT", path=corp_path)
        by_url = self.add_doc("CONCALL_TRANSCRIPT", url=corp_url)
        # Chunks also carry a different symbol for by_path: corporate_documents wins.
        self.add_chunk(by_path, "CHUNKLOSES", "INE000000001")
        self.add_chunk(chunk_doc, "CHUNKSYM", "INE000000002", n=3)
        self.add_chunk(chunk_doc, "NOISE", "INE000000099", n=1)

        self.conn.execute(
            "INSERT INTO corporate_documents (isin, symbol, doc_type, title, source_url, local_file_path) "
            "VALUES ('INE000000010', 'CORP', 'ANNUAL_REPORT', 'x', NULL, ?)",
            (corp_path,))
        self.conn.execute(
            "INSERT INTO corporate_documents (isin, symbol, doc_type, title, source_url, local_file_path) "
            "VALUES ('INE000000011', 'CORPURL', 'CONCALL_TRANSCRIPT', 'x', ?, NULL)",
            (corp_url,))

        result = bf.backfill(self.conn)
        rows = {row[0]: row for row in self.conn.execute(
            "SELECT doc_id, symbol, isin, symbol_source FROM raw_documents")}

        self.assertEqual(rows[by_path][1:], ("CORP", "INE000000010", bf.METHOD_CORP))
        self.assertEqual(rows[by_url][1:], ("CORPURL", "INE000000011", bf.METHOD_CORP))
        self.assertEqual(rows[chunk_doc][1:], ("CHUNKSYM", "INE000000002", bf.METHOD_CHUNKS))
        self.assertEqual(rows[path_doc][1], "PATHSYM")
        self.assertEqual(rows[path_doc][3], bf.METHOD_PATH)
        self.assertIsNone(rows[no_identity][1])
        self.assertIsNone(rows[no_identity][2])
        self.assertEqual(result["filled"], {"corporate_documents": 2,
                                            "document_chunks": 1,
                                            "local_file_path": 1})
        self.assertEqual(result["ar_without_symbol"], 1)  # only no_identity is not an AR
        after = {r["source_type"]: r for r in result["after"]}
        self.assertEqual(after["ANNUAL_REPORT"]["with_symbol"], 3)

    def test_existing_symbol_is_not_overwritten_and_rerun_is_idempotent(self):
        doc = self.add_doc("ANNUAL_REPORT", path=r"C:\data\pdfs\KEEPME\ANNUAL_REPORT\a.pdf")
        bf.ensure_columns(self.conn)
        self.conn.execute(
            "UPDATE raw_documents SET symbol='EXISTING', isin='INE000000099', symbol_source='seed' "
            "WHERE doc_id=?", (doc,))

        first = bf.backfill(self.conn)
        self.assertEqual(first["filled"], {"corporate_documents": 0,
                                           "document_chunks": 0,
                                           "local_file_path": 0})
        row = self.conn.execute(
            "SELECT symbol, isin, symbol_source FROM raw_documents WHERE doc_id=?", (doc,)
        ).fetchone()
        self.assertEqual(row, ("EXISTING", "INE000000099", "seed"))

        second = bf.backfill(self.conn)
        self.assertEqual(second["filled"], {"corporate_documents": 0,
                                            "document_chunks": 0,
                                            "local_file_path": 0})

    def test_dry_run_writes_nothing(self):
        self.add_doc("ANNUAL_REPORT", path=r"C:\data\pdfs\PATHSYM\ANNUAL_REPORT\a.pdf")
        result = bf.backfill(self.conn, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["filled"]["local_file_path"], 1)
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(raw_documents)")}
        self.assertNotIn("symbol", cols)  # dry run did not even ALTER

    def test_mode_and_most_common_chunk_identity(self):
        doc = self.add_doc("ANNUAL_REPORT")
        self.add_chunk(doc, "RARE", None, n=1)
        self.add_chunk(doc, "COMMON", "INE000000005", n=4)
        self.add_chunk(doc, None, "INE000000006", n=2)
        bf.backfill(self.conn)
        row = self.conn.execute(
            "SELECT symbol, isin, symbol_source FROM raw_documents WHERE doc_id=?", (doc,)
        ).fetchone()
        self.assertEqual(row, ("COMMON", "INE000000005", bf.METHOD_CHUNKS))


if __name__ == "__main__":
    unittest.main()
