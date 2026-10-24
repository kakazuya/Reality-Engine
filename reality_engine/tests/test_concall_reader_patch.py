"""Contract for the 2026-10-24 concall-reader patch: chunk text assembly, date resolver, retryable skips, strict order.

In-memory/temp SQLite only; every test stops before any network call.
"""
import datetime as dt
import shutil
import sqlite3
import unittest
import uuid
from pathlib import Path

from reality_engine.scripts import concall_deepseek as cd
from reality_engine.scripts.concall_pilot import KILO_URL

MAIN_DDL = """
CREATE TABLE corporate_documents (id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT, doc_type TEXT,
    bse_dissem_ts TEXT, publication_date TEXT, call_date TEXT, doc_date TEXT, local_file_path TEXT,
    sha256_hash TEXT, source_url TEXT);
CREATE TABLE raw_documents (doc_id INTEGER PRIMARY KEY, sha256_hash TEXT, source_url TEXT);
CREATE TABLE document_chunks (chunk_id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER, chunk_index INTEGER,
    content TEXT, UNIQUE(doc_id, chunk_index));
"""


class ConcallReaderPatchTests(unittest.TestCase):
    def setUp(self):
        # the DSH sandbox does not allow the OS temp dir (or mkdtemp-created dirs); keep test scratch in the workspace
        self.dir = Path(__file__).resolve().parent / "test_scratch" / uuid.uuid4().hex
        self.dir.mkdir(parents=True)
        self.main_path = self.dir / "equity_intelligence.db"
        main = sqlite3.connect(self.main_path)
        main.executescript(MAIN_DDL)
        main.commit()
        main.close()
        self.out_path = self.dir / "concall_facts.db"
        out = sqlite3.connect(self.out_path)
        out.executescript(cd.DDL)
        out.close()
        self._saved = (cd.PRIORITY, cd.TG_ISINS, cd.SINCE, cd.OUT_DB)
        cd.PRIORITY = self.dir / "no_priority.json"
        cd.TG_ISINS = self.dir / "no_tg_isins.json"
        cd.SINCE = "2015-01-01"
        cd.OUT_DB = self.out_path

    def tearDown(self):
        cd.PRIORITY, cd.TG_ISINS, cd.SINCE, cd.OUT_DB = self._saved
        shutil.rmtree(self.dir, ignore_errors=True)

    # ---------------------------------------------------------------- helpers
    def add_doc(self, doc_id, symbol="TEST", filed="2026-01-01", path=None, sha=None, url=None):
        main = sqlite3.connect(self.main_path)
        with main:
            main.execute("INSERT INTO corporate_documents (id, isin, symbol, doc_type, bse_dissem_ts, doc_date, "
                         "local_file_path, sha256_hash, source_url) VALUES (?,?,?,'CONCALL_TRANSCRIPT',?,?,?,?,?)",
                         (doc_id, f"INE{doc_id:09d}", symbol, filed, filed[:10] if filed else None, path, sha, url))
        main.close()

    def add_raw(self, raw_id, sha=None, url=None, chunks=()):
        main = sqlite3.connect(self.main_path)
        with main:
            main.execute("INSERT INTO raw_documents (doc_id, sha256_hash, source_url) VALUES (?,?,?)",
                         (raw_id, sha, url))
            main.executemany("INSERT INTO document_chunks (doc_id, chunk_index, content) VALUES (?,?,?)",
                             [(raw_id, i, c) for i, c in enumerate(chunks)])
        main.close()

    def set_status(self, doc_id, status):
        out = sqlite3.connect(self.out_path)
        with out:
            out.execute("INSERT OR REPLACE INTO cc_docs (doc_id, status) VALUES (?,?)", (doc_id, status))
        out.close()

    def queue(self, **kw):
        out = sqlite3.connect(self.out_path)
        try:
            return cd.queue(out, only_tg=False, since="2015-01-01", main_db=self.main_path, **kw)
        finally:
            out.close()

    # ---------------------------------------------------------------- chunk assembly
    def test_join_chunks_strips_headers_and_word_overlap(self):
        header = "[Metadata: Symbol: X | FY:  | Doc: CONCALL_TRANSCRIPT | Date: 2026-08-28]\n"
        joined = cd.join_chunks([header + "a b c d e f g h i j", header + "f g h i j k l m", header + "m n o"])
        self.assertEqual(joined, "a b c d e f g h i j k l m n o")

    def test_join_chunks_no_overlap_keeps_a_newline(self):
        self.assertEqual(cd.join_chunks(["a b c", "d e f"]), "a b c\nd e f")

    def test_join_chunks_only_strips_the_leading_header(self):
        self.assertEqual(cd.join_chunks(["x [Metadata: keep me] y"]), "x [Metadata: keep me] y")

    def test_item_text_falls_back_to_chunks_when_pdf_is_missing(self):
        self.add_doc(1, path=str(self.dir / "absent.pdf"), sha="sha-1")
        self.add_raw(11, sha="sha-1", chunks=["[Metadata: x]\nheld on 11 August 2026", "[Metadata: x]\n11 August 2026 then rest"])
        item = self.queue(from_chunks=True)[0]
        text, source = cd._item_text(item)
        self.assertEqual(source, "chunks")
        self.assertIn("then rest", text)
        self.assertEqual(text.count("11 August 2026"), 1)   # overlap was dropped

    def test_item_text_raises_when_neither_source_exists(self):
        self.add_doc(1, path=None, sha=None)
        with self.assertRaises(cd.UnreadableText):
            cd._item_text({"id": 1, "path": None, "chunk_doc": None})

    # ---------------------------------------------------------------- date resolver
    def test_date_resolver_patterns(self):
        cases = [
            ("Q1 FY27 Earnings Conference Call August 11, 2026", "2026-08-11", "text_call_date"),
            ("The earnings conference call was held on 11th August 2026.", "2026-08-11", "text_call_date"),
            ("Concall held on 11-08-2026 at 4 pm.", "2026-08-11", "text_call_date"),
            ("Concall held on 31-12-2025.", "2025-12-31", "text_call_date"),
            ("the call took place on 04-Jun—19", "2019-06-04", "text_call_date"),
            ("August 11, 2026", "2026-08-11", "text_dateline"),
        ]
        for text, want, want_source in cases:
            with self.subTest(text=text):
                iso, source, confidence, _ = cd.resolve_call_date(text, today=dt.date(2026, 10, 24))
                self.assertEqual(iso, want)
                self.assertEqual(source, want_source)
                self.assertIn(confidence, ("high", "medium"))

    def test_date_resolver_prefers_the_call_date_over_the_letter_date(self):
        text = ("In continuation of our letter dated 30.05.2019, please find enclosed the transcript of the Q4 FY19 "
                "earnings conference call held on 04-Jun-19 at 12:30 hrs IST.")
        iso, source, confidence, _ = cd.resolve_call_date(text, crawl_date="2026-08-28")
        self.assertEqual((iso, source, confidence), ("2019-06-04", "text_call_date", "high"))

    def test_date_resolver_sanity_rules(self):
        text = "Q1 FY27 Earnings Conference Call August 11, 2026"
        self.assertEqual(cd.resolve_call_date(text, filed="2026-08-13")[0], "2026-08-11")
        after, source, _, _ = cd.resolve_call_date(text, filed="2026-07-01")
        self.assertIsNone(after)
        self.assertTrue(source.endswith("_after_filing"))
        stale, source, _, _ = cd.resolve_call_date(text, filed="2026-12-01")
        self.assertIsNone(stale)
        self.assertTrue(source.endswith("_outside_60d"))
        future, source, _, _ = cd.resolve_call_date("conference call on August 11, 2027", today=dt.date(2026, 10, 24))
        self.assertIsNone(future)
        self.assertTrue(source.endswith("_future"))

    def test_date_resolver_rejects_impossible_dates_and_no_date(self):
        self.assertEqual(cd.resolve_call_date("concall on 31-02-2026", today=dt.date(2026, 10, 24))[0], None)
        self.assertEqual(cd.resolve_call_date("the first question is from the line of A", today=dt.date(2026, 10, 24))[0],
                         None)

    # ---------------------------------------------------------------- retryable skips
    def test_missing_text_writes_retryable_status_and_stays_in_queue(self):
        self.add_doc(1, path=str(self.dir / "gone.pdf"), sha="sha-gone")
        self.set_status(1, "skip_unreadable")          # old terminal-looking row from the pre-patch runner
        todo = self.queue(from_chunks=False)
        self.assertEqual([t["id"] for t in todo], [1])
        lane = cd.make_lane("NO_SUCH_KEY", "beam-free", 0, env={"NO_SUCH_KEY": "x"})
        res = cd.work(todo[0], lane, str(self.out_path))
        self.assertEqual(res["status"], "skip_unreadable_text")
        out = sqlite3.connect(self.out_path)
        self.assertEqual(out.execute("SELECT status FROM cc_docs WHERE doc_id=1").fetchone()[0], "skip_unreadable_text")
        out.close()
        self.assertEqual([t["id"] for t in self.queue(from_chunks=False)], [1])   # retryable, not done

    def test_done_set_excludes_only_terminal_skips(self):
        for doc_id, status in enumerate(("ok", "skip_cover_letter", "skip_duplicate", "skip_unreadable",
                                         "skip_unreadable_text", "queued_429", "error"), 1):
            self.add_doc(doc_id, symbol=f"S{doc_id}", filed=f"2026-01-{doc_id:02d}",
                         path=str(self.dir / f"d{doc_id}.pdf"))
            self.set_status(doc_id, status)
        ids = {t["id"] for t in self.queue(from_chunks=False)}
        self.assertEqual(ids, {4, 5, 6, 7})

    # ---------------------------------------------------------------- ordering + text dates
    def test_strict_date_orders_newest_first_and_includes_the_text_dated_doc(self):
        for doc_id, filed in ((1, "2026-01-01"), (2, "2026-03-01"), (3, "2026-02-01"), (5, "2025-01-01")):
            p = self.dir / f"d{doc_id}.pdf"
            p.write_bytes(b"")
            self.add_doc(doc_id, symbol=f"S{doc_id}", filed=filed, path=str(p))
        # undated: the crawl stamp overwrote the filing date; the call date is in the chunk text
        self.add_doc(4, symbol="UNDATED", filed=None, sha="sha-undated")
        self.add_raw(44, sha="sha-undated", chunks=[
            "[Metadata: Symbol: UNDATED | Date: 2026-08-28]\nQ1 FY27 Earnings Conference Call held on 11 August 2026"])
        self.set_status(5, "queued_429")
        todo = self.queue(from_chunks=True, strict_date=True)
        self.assertEqual([t["id"] for t in todo], [4, 2, 3, 1, 5])
        self.assertEqual(todo[0]["date_source"], "text_call_date")
        self.assertEqual(todo[0]["filed"], "2026-08-11")

    def test_default_order_still_puts_queued_429_first(self):
        for doc_id, symbol, filed in ((1, "NEW", "2026-03-01"), (2, "OLD429", "2025-01-01")):
            p = self.dir / f"d{doc_id}.pdf"
            p.write_bytes(b"")
            self.add_doc(doc_id, symbol=symbol, filed=filed, path=str(p))
        self.set_status(2, "queued_429")
        self.assertEqual([t["id"] for t in self.queue(from_chunks=False, strict_date=False)], [2, 1])

    # ---------------------------------------------------------------- lanes
    def test_lanes_get_stable_sessions_and_their_own_gateway(self):
        env = {"KILO_API_KEY": "k1", "OPENCODE_GO_API_KEY_2": "g2"}
        kilo = cd.make_lane("KILO_API_KEY", "reflection/beam-free", 1, env=env)
        kilo_again = cd.make_lane("KILO_API_KEY", "reflection/beam-free", 1, env=env)
        go = cd.make_lane("OPENCODE_GO_API_KEY_2", "beam-free", 0, env=env)
        self.assertEqual(kilo["url"], KILO_URL)
        self.assertEqual(go["url"], cd.GO_URL)
        self.assertEqual(kilo["session"], kilo_again["session"])
        self.assertNotEqual(kilo["session"], go["session"])


if __name__ == "__main__":
    unittest.main()
