"""Tests for the real-deck chunk loader (``scripts/load_deck_chunks.py``).

No live database and no network: a 3-page PDF is generated in a temp dir, and
the output store is a temp file.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reality_engine.scripts import load_deck_chunks as loader

HEADER = "ACME LIMITED · Investor presentation · Q1 FY27 · 2026-07-30"
PAGES = [
    "ACME Limited Q1 FY27 results presentation revenue 1,000 crore EBITDA 200 crore "
    "margin 20% order book 5,000 crore capex plan 750 crore capacity addition",
    "Business overview three segments domestic 60% exports 40% distributor network "
    "12,000 dealers 450 towns new products launched 18 brands market share 14%",
    "Thank you",
]


class ChunkDeckTest(unittest.TestCase):
    def test_empty_pages_are_left_out(self):
        text, numbers, ends = loader.normalise_pages(PAGES)
        self.assertNotIn("Thank you", text)          # 9 chars < 40
        self.assertEqual(numbers, [1, 2])
        self.assertEqual(ends, [len(PAGES[0]), len(text)])
        self.assertEqual(text.count("  "), 0)

    def test_page_mapping_and_header(self):
        chunks = loader.chunk_deck(PAGES, HEADER)
        self.assertEqual(len(chunks), 1)              # < 512 words: one chunk
        chunk = chunks[0]
        self.assertEqual((chunk["page_from"], chunk["page_to"]), (1, 2))
        self.assertEqual(chunk["header"], HEADER)
        self.assertTrue(chunk["body"].startswith("ACME Limited Q1 FY27"))
        self.assertEqual(chunk["char_len"], len(HEADER) + len(chunk["body"]))

    def test_long_deck_splits_with_overlap(self):
        pages = [("word " * 1200).strip()]
        chunks = loader.chunk_deck(pages, HEADER)
        self.assertEqual(len(chunks), 3)              # 512 / (512-64) windows
        self.assertTrue(all(c["page_from"] == 1 and c["page_to"] == 1 for c in chunks))
        self.assertEqual([c["chunk_index"] for c in chunks], [0, 1, 2])
        # 64-word overlap between consecutive windows.
        first, second = chunks[0]["body"].split(), chunks[1]["body"].split()
        self.assertEqual(len(first), 512)
        self.assertEqual(first[-64:], second[:64])

    def test_deck_is_not_pruned_like_a_concall(self):
        deck = ["Business overview and guidance for the year ahead with numbers 1 2 3",
                "Question and Answer session we expect 20% growth in the next year and "
                "margin expansion of 200 basis points on the back of the new plant"]
        chunks = loader.chunk_deck(deck, HEADER)
        body = " ".join(c["body"] for c in chunks)
        self.assertIn("Business overview", body)      # production pruner would drop it

    def test_nul_bytes_are_stripped(self):
        # A NUL in the text layer makes SQLite's length() (and FTS) stop early.
        chunks = loader.chunk_deck(["Revenue \x00 1,000 crore EBITDA \x00 200 crore "
                                    "and a long tail of guidance for the year ahead"], HEADER)
        self.assertEqual(len(chunks), 1)
        self.assertNotIn("\x00", chunks[0]["body"])
        self.assertEqual(chunks[0]["char_len"], len(HEADER) + len(chunks[0]["body"]))

    def test_image_only_deck_has_no_chunks(self):
        self.assertEqual(loader.chunk_deck(["", "   ", "1234567890"], HEADER), [])


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "chunks_v2.db"
        self.con = loader.open_out(self.db)
        self.doc = {"sha256": "a" * 64, "symbol": "ACME", "isin": "INE000000001",
                    "known_at": "2026-07-30T18:00:00", "title": "Q1 FY27",
                    "pages": 3, "empty_pages": 1, "status": "ok",
                    "chunks": loader.chunk_deck(PAGES, HEADER)}

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_write_doc_is_idempotent_and_searchable(self):
        self.assertEqual(loader.write_doc(self.con, self.doc), 1)
        self.con.commit()
        self.assertEqual(loader.write_doc(self.con, self.doc), 1)   # replaces, no dupes
        self.con.commit()
        self.assertEqual(self.con.execute("SELECT count(*) FROM deck_chunks").fetchone()[0], 1)
        self.assertEqual(loader.rebuild_fts(self.con), 1)
        hit = self.con.execute(
            "SELECT c.symbol, c.page_from FROM deck_chunks_fts f "
            "JOIN deck_chunks c ON c.chunk_id = f.rowid WHERE deck_chunks_fts MATCH 'EBITDA'"
        ).fetchall()
        self.assertEqual(hit, [("ACME", 1)])

    def test_stats(self):
        loader.write_doc(self.con, self.doc)
        self.con.commit()
        report = loader.stats(self.db)
        self.assertEqual((report["decks"], report["chunks"], report["chunks_per_deck"]),
                         (1, 1, 1.0))
        self.assertEqual(report["p50"], self.doc["chunks"][0]["char_len"])
        self.assertEqual(report["tokens_est"], report["chars"] // 4)
        self.assertEqual(report["status"], {"ok": 1})

    def test_done_shas_skips_only_ok(self):
        loader.write_doc(self.con, dict(self.doc, status="no_text", chunks=[]))
        self.con.commit()
        self.assertEqual(loader.done_shas(self.con), set())


class ParsePdfTest(unittest.TestCase):
    def test_parse_real_pdf_pages(self):
        import fitz

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deck.pdf"
            with fitz.open() as pdf:
                for text in PAGES:
                    page = pdf.new_page()
                    page.insert_text((40, 60), text, fontsize=8)
                pdf.save(path)
            doc = loader.parse_deck(str(path), {"sha256": "b" * 64, "symbol": "ACME",
                                                "isin": "INE000000001",
                                                "known_at": "2026-07-30T18:00:00",
                                                "title": "Q1 FY27", "company": "ACME LIMITED"})
        self.assertEqual(doc["status"], "ok")
        self.assertEqual(doc["pages"], 3)
        self.assertGreaterEqual(doc["chunks"][0]["page_from"], 1)
        self.assertIn("Investor presentation", doc["chunks"][0]["header"])
        self.assertIn("ACME LIMITED", doc["chunks"][0]["header"])

    def test_bad_pdf_is_an_error_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.pdf"
            path.write_bytes(b"not a pdf")
            doc = loader.parse_deck(str(path), {"sha256": "c" * 64, "symbol": "X"})
        self.assertTrue(doc["status"].startswith("error:"))
        self.assertEqual(doc["chunks"], [])


class MigrateTreeTest(unittest.TestCase):
    """The bulk ``rclone copy`` tree -> ``<sha[:2]>/<sha>.pdf`` mover."""

    SHA_GOOD = "ab" * 32
    SHA_WRONG = "cd" * 32

    def setUp(self):
        import hashlib

        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        # The job logs to .tmp/p2 in the checkout; tests must not write there.
        self._log = loader.FETCH_LOG
        loader.FETCH_LOG = root / "fetch_log.jsonl"
        self.tree = root / "tree"
        (self.tree / "bse" / "500520").mkdir(parents=True)
        (self.tree / "bse" / "500520" / "good.pdf").write_bytes(b"%PDF-good")
        (self.tree / "bse" / "500520" / "wrong.pdf").write_bytes(b"%PDF-wrong")
        (self.tree / "bse" / "500520" / "later.pdf.partial").write_bytes(b"%PDF-half")
        (self.tree / "bse" / "other.pdf").write_bytes(b"%PDF-unknown")
        good = hashlib.sha256(b"%PDF-good").hexdigest()
        wrong = hashlib.sha256(b"%PDF-wrong").hexdigest()
        self.dest = root / "dest"
        self.index = root / "index.json"
        from reality_engine.toolbelt import drive_fetch

        drive_fetch.save_index(self.index, {
            "schema": 1, "remote": drive_fetch.DEFAULT_REMOTE, "folders": {"decks": {"at": "",
                "files": {
                    "decks/bse/500520/good.pdf": {"sha256": good, "size": len(b"%PDF-good"),
                                                  "md5": None},
                    "decks/bse/500520/wrong.pdf": {"sha256": self.SHA_WRONG, "size": 999,
                                                   "md5": None},
                    "decks/bse/500520/later.pdf.partial": {"sha256": "ee" * 32, "size": 9,
                                                           "md5": None},
                }}}})
        self.good = good
        self._wrong_hash = wrong

    def tearDown(self):
        loader.FETCH_LOG = self._log
        self.tmp.cleanup()

    def test_moves_only_verified_complete_files(self):
        stats = loader.migrate_tree(self.tree, self.index, self.dest)
        self.assertEqual(stats, {"files": 3, "moved": 1, "known": 2, "unmatched": 1,
                                "mismatch": 1})
        self.assertTrue((self.dest / self.good[:2] / f"{self.good}.pdf").exists())
        self.assertFalse((self.dest / self.SHA_WRONG[:2] / f"{self.SHA_WRONG}.pdf").exists())
        self.assertFalse((self.tree / "bse" / "500520" / "good.pdf").exists())
        # The in-flight partial is untouched so the copy can still finish it.
        self.assertTrue((self.tree / "bse" / "500520" / "later.pdf.partial").exists())

    def test_rerun_is_a_no_op(self):
        loader.migrate_tree(self.tree, self.index, self.dest)
        stats = loader.migrate_tree(self.tree, self.index, self.dest)
        self.assertEqual((stats["moved"], stats["files"]), (0, 0))
        self.assertTrue((self.tree / "bse" / "500520" / "later.pdf.partial").exists())


if __name__ == "__main__":
    unittest.main()
