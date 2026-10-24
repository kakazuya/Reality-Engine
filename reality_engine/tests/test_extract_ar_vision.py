"""Offline tests for the AR/deck chart-vision pass (no network, no live DB)."""
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

import pymupdf

os.environ.setdefault("KILO_API_KEY", "test")
os.environ.setdefault("OPENROUTER_API_KEY", "test")
from reality_engine.scripts import extract_ar_vision as v
from reality_engine.scripts import extract_deck_figures as deck

# The platform temp directory is not writable under the worktree sandbox; use files directly in the
# workspace (a freshly created sub-directory is not writable for a confined child either).
TMP = Path(".test_tmp_ar_vision")
TMP.mkdir(exist_ok=True)
_seq = [0]


def tmpfile(suffix):
    _seq[0] += 1
    return TMP / f"{os.getpid()}_{_seq[0]}_{time.time_ns() % 10**9}.{suffix}"


def cleanup(*paths):
    for p in paths:
        p = Path(p)
        p.unlink(missing_ok=True)
        Path(str(p) + "-wal").unlink(missing_ok=True)
        Path(str(p) + "-shm").unlink(missing_ok=True)


class PromptAndParseTests(unittest.TestCase):
    def test_chart_lines_are_not_facts(self):
        out = ("TITLE | Financial highlights\n"
               "Revenue | FY26 | 1,234.5 | Rs Cr\n"
               "CHART | Revenue | FY22-FY26 | rising from 800 to 1,200\n"
               "margin | FY26 | 18.2% | %\n"
               "236 | - | 236 | -\n")
        charts = v.parse_chart_lines(out)
        self.assertEqual(len(charts), 1)
        self.assertEqual(charts[0]["measure"], "Revenue")
        self.assertEqual(charts[0]["span"], "FY22-FY26")
        self.assertIn("rising", charts[0]["trend"])
        facts = v.facts_of(out)
        self.assertEqual([f["value"] for f in facts], [1234.5, 18.2])   # numeric-only metric dropped
        self.assertTrue(all(f["metric"].upper() != "CHART" for f in facts))

    def test_both_prompts_share_the_parse_contract(self):
        self.assertIn("metric | period | number | unit", v.PROMPT_A)
        self.assertIn("metric | period | number | unit", v.PROMPT_B)
        self.assertIn("TITLE |", v.PROMPT_A)
        self.assertIn("CHART |", v.PROMPT_B)
        p = v.build_prompt({"symbol": "X", "company": "X Ltd", "known_at": "2026-08-01", "fiscal_year": "2026-03-31",
                            "text": "Revenue 1,234"}, "b")
        self.assertIn("X Ltd", p); self.assertIn("1,234", p); self.assertIn("CHART", p)
        self.assertNotIn("<<<", v.build_prompt({"symbol": "X", "text": "  "}, "a"))

    def test_version_changes_with_prompt_and_is_stable(self):
        self.assertEqual(len(v.PROMPT_VERSION), 10)
        self.assertEqual(v.PROMPT_VERSION, v.PROMPT_VERSION)
        self.assertNotEqual(v.PROMPT_VERSION, deck.PROMPT_VERSION)


class GarbledTests(unittest.TestCase):
    def test_control_poison_is_garbled(self):
        self.assertTrue(v.garbled("\x01\x02\x03\x04" * 40))
        self.assertTrue(v.garbled("\ue001\ue002\ue003\ue004" * 40))

    def test_normal_and_hindi_text_are_not_garbled(self):
        self.assertFalse(v.garbled("Revenue from operations 1,234.5 18.2% for the year ended 31 March 2026. " * 2))
        self.assertFalse(v.garbled("राजस्व और लाभ के बारे में जानकारी दी गई है। यह वार्षिक रिपोर्ट है। " * 2))
        self.assertFalse(v.garbled("short"))


class FakePage:
    def __init__(self, text="", image_area=0.8, page_area=1.0):
        self._text = text
        self.rect = pymupdf.Rect(0, 0, 100, page_area * 100)
        self._img = image_area

    def get_text(self):
        return self._text

    def get_image_info(self):
        return [{"bbox": (0, 0, 100, self._img * 100)}]


class RoutingTests(unittest.TestCase):
    def test_text_page_is_skipped_without_ocr(self):
        calls = []
        old = v.ocr_text
        v.ocr_text = lambda page, side=v.OCR_SIDE: calls.append(1) or ""
        try:
            t = v.ar_page_task(FakePage("Revenue 1,234 2,345 3,456 4,567 5,678 for FY26 with a long discussion " * 10), 3)
        finally:
            v.ocr_text = old
        self.assertEqual(t["route"], "skip")
        self.assertFalse(calls)

    def test_image_page_with_numbers_goes_to_vision(self):
        old = v.ocr_text
        v.ocr_text = lambda page, side=v.OCR_SIDE: "Revenue 1,234 2,345 FY26"
        try:
            t = v.ar_page_task(FakePage(""), 7)
        finally:
            v.ocr_text = old
        self.assertEqual(t["route"], "vision")
        self.assertGreaterEqual(t["ocr"], 2)
        self.assertIn(1234.0, t["ocr_truth"])

    def test_image_page_without_numbers_is_skipped(self):
        old = v.ocr_text
        v.ocr_text = lambda page, side=v.OCR_SIDE: "Welcome to our annual report"
        try:
            t = v.ar_page_task(FakePage(""), 8)
        finally:
            v.ocr_text = old
        self.assertEqual(t["route"], "skip_ocr")

    def test_garbled_page_with_numbers_is_a_candidate(self):
        old = v.ocr_text
        v.ocr_text = lambda page, side=v.OCR_SIDE: "Revenue 1,234 2,345"
        try:
            t = v.ar_page_task(FakePage("\x01\x02\x03" * 100), 9)
        finally:
            v.ocr_text = old
        self.assertEqual(t["garbled"], 1)
        self.assertEqual(t["route"], "vision")

    def test_ocr_unavailable_reads_the_page(self):
        old = v.ocr_text
        v.ocr_text = lambda page, side=v.OCR_SIDE: None
        try:
            t = v.ar_page_task(FakePage(""), 10)
        finally:
            v.ocr_text = old
        self.assertEqual(t["route"], "vision")


class PathTests(unittest.TestCase):
    def test_drive_rel_for_ar_and_decks(self):
        self.assertEqual(v.drive_rel(r"C:\x\data\pdfs\TCS\ANNUAL_REPORT\a.pdf", "ar"),
                         "pdfs/TCS/ANNUAL_REPORT/a.pdf")
        self.assertEqual(v.drive_rel(r"D:\RealityEngine\pdfs\TCS\ANNUAL_REPORT\a.pdf", "ar"),
                         "D_pdfs/TCS/ANNUAL_REPORT/a.pdf")
        self.assertEqual(v.drive_rel(r"C:\x\data\decks\nse\TCS\a.pdf", "decks"), "decks/nse/TCS/a.pdf")
        self.assertIsNone(v.drive_rel(r"C:\no\marker\a.pdf", "ar"))

    def test_existing_file_is_never_fetched(self):
        f = tmpfile("pdf"); f.write_bytes(b"x")
        try:
            self.assertEqual(v.fetch_pdf(str(f), "ar", TMP / "dl"), str(f))
        finally:
            cleanup(f)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.db = tmpfile("ar_facts.db")
        self.store = v.Store(self.db)
        self.task = {"doc_id": 7, "page_no": 3, "isin": "INE000000001", "symbol": "TEST", "fiscal_year": "2026-03-31",
                     "known_at": "2026-08-01T10:00", "sha256": "abc", "path": "x.pdf", "route": "vision",
                     "text_chars": 12, "truth": {1.0}, "img_cov": 0.9, "garbled": 0, "ocr": 3}

    def tearDown(self):
        self.store.con.close(); cleanup(self.db)

    def test_schema_is_additive_and_carries_metadata(self):
        for table in ("ar_vision_pages", "ar_vision_outputs", "ar_vision_facts", "ar_vision_chart_trends"):
            cols = {r[1] for r in self.store.query(f"PRAGMA table_info({table})")}
            for need in ("doc_id", "page_no", "isin", "symbol", "fiscal_year", "known_at"):
                self.assertIn(need, cols, table)
        # the text tables are not required to exist in this fresh DB; only our four are created
        self.assertEqual(self.store.query("SELECT COUNT(*) FROM ar_vision_pages")[0][0], 0)

    def test_save_page_roundtrip_and_resume(self):
        res = {"status": "ok", "model": "dots-3@openrouter",
               "reading": {"output": "Revenue | FY26 | 1,234 | Rs Cr\nCHART | Revenue | FY22-26 | rising",
                           "seconds": 1.5, "in_tok": 10, "out_tok": 20, "usd": 0.0},
               "facts": v.facts_of("Revenue | FY26 | 1,234 | Rs Cr"),
               "charts": v.parse_chart_lines("CHART | Revenue | FY22-26 | rising"), "recall": 1.0}
        self.store.save_page(self.task, res)
        self.assertIn((7, 3), self.store.done_keys())
        self.assertEqual(self.store.query("SELECT metric, value FROM ar_vision_facts")[0], ("Revenue", 1234.0))
        self.assertEqual(self.store.query("SELECT measure, span FROM ar_vision_chart_trends")[0], ("Revenue", "FY22-26"))
        self.assertEqual(self.store.query("SELECT status, n_facts, n_charts FROM ar_vision_pages")[0], ("ok", 1, 1))
        # idempotent: a second save replaces, does not duplicate facts
        self.store.save_page(self.task, res)
        self.assertEqual(self.store.query("SELECT COUNT(*) FROM ar_vision_facts")[0][0], 1)

    def test_three_attempts_cull_a_bad_page(self):
        bad = {"status": "error", "error": "HTTP 500", "facts": [], "charts": []}
        for _ in range(v.MAX_PAGE_ATTEMPTS - 1):
            self.store.save_page(self.task, bad)
        self.assertNotIn((7, 3), self.store.done_keys())       # still retried after one/two errors
        self.store.save_page(self.task, bad)
        self.assertIn((7, 3), self.store.done_keys())          # third strike: final
        self.assertEqual(self.store.query("SELECT attempts FROM ar_vision_pages")[0][0], 3)


class QueueTests(unittest.TestCase):
    def test_ar_scopes_and_order(self):
        db = tmpfile("ar.db")
        con = sqlite3.connect(db)
        try:
            con.execute("""CREATE TABLE ar_docs (doc_id INTEGER, isin TEXT, symbol TEXT, company TEXT, fiscal_year TEXT,
                filed_at TEXT, path TEXT, sha256 TEXT, n_pages INTEGER, n_text_pages INTEGER)""")
            con.executemany("INSERT INTO ar_docs VALUES (?,?,?,?,?,?,?,?,?,?)", [
                (1, "I1", "A", "A Ltd", "2026-03-31", "2026-08-01", "a.pdf", "s1", 10, 2),
                (2, "I2", "B", "B Ltd", "2025-03-31", "2025-08-01", "b.pdf", "s2", 10, 1),
                (3, "I3", "C", "C Ltd", "2026-03-31", "2026-09-01", "c.pdf", "s3", 10, 9),
                (4, "I4", "D", "D Ltd", "2026-03-31", "2026-07-01", "d.pdf", "s4", 10, 5),
            ])
            con.commit()
            self.assertEqual([x["doc_id"] for x in v.load_ar_docs(con, "fy26")], [1])
            self.assertEqual([x["doc_id"] for x in v.load_ar_docs(con, "older")], [2])
            self.assertEqual([x["doc_id"] for x in v.load_ar_docs(con, "fy26-all")], [3, 1, 4])
        finally:
            con.close(); cleanup(db)

    def test_deck_queue_needs_low_text_img_and_no_output(self):
        db = tmpfile("deck.db")
        con = sqlite3.connect(db)
        try:
            con.executescript(deck.SCHEMA)
            rows = [
                ("s1", 1, 10, "A", 50, 0.9, "skipped"),   # wanted
                ("s1", 2, 10, "A", 500, 0.9, "skipped"),  # text page
                ("s1", 3, 10, "A", 50, 0.1, "skipped"),   # little image
                ("s1", 4, 10, "A", 50, 0.9, "ok"),        # already read
                ("s2", 1, 10, "B", 50, 0.9, "skipped"),   # wanted
            ]
            for sha, pg, doc, sym, chars, cov, status in rows:
                con.execute("INSERT INTO pages (sha256,page_no,prompt_version,doc_id,isin,symbol,doc_type,known_at,route,"
                            "text_chars,text_numbers,img_cov,final_model,n_facts,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (sha, pg, "v", doc, "I", sym, "INVESTOR_PRESENTATION", "2026-09-01", "skip", chars, 0, cov,
                             None, 0, status))
            con.commit()
            q = v.load_deck_pages(con)
            self.assertEqual([(r["sha256"], r["page_no"]) for r in q], [("s1", 1), ("s2", 1)])
        finally:
            con.close(); cleanup(db)


class DeckStoreTests(unittest.TestCase):
    def test_three_failures_cull_a_leftover_page(self):
        db = tmpfile("deck.db")
        store = v.DeckStore(db)
        task = {"sha256": "s1", "page_no": 4, "doc_id": 1, "isin": "I", "symbol": "X",
                "doc_type": "INVESTOR_PRESENTATION", "known_at": "2026-09-01", "text_chars": 0, "img_cov": 1.0}
        bad = {"status": "error", "error": "HTTP 500", "facts": [], "charts": []}
        try:
            for _ in range(v.MAX_PAGE_ATTEMPTS):
                store.save(task, bad)
            self.assertIn(("s1", 4), store.failed())
            self.assertNotIn(("s1", 4), store.done())
        finally:
            store.con.close(); cleanup(db)


class CullTests(unittest.TestCase):
    def test_three_consecutive_failures_bench_a_reader(self):
        class Ledger:
            def __init__(self): self.blocked = []
            def block(self, model, seconds, reason=""): self.blocked.append((model, seconds))
        class Inner:
            limiters, ledger, pacer = {}, None, None
            def read(self, model, *a, **k): raise RuntimeError("boom")
        inner = Inner(); ledger = Ledger(); inner.ledger = ledger
        c = v.CullClient(inner, ["m"])
        for _ in range(v.READER_STRIKES):
            with self.assertRaises(RuntimeError):
                c.read("m", "b64", "p")
        self.assertTrue(c.culled("m"))
        self.assertEqual(len(ledger.blocked), 1)


class GateHelperTests(unittest.TestCase):
    def test_reference_number_match_ignores_grouping(self):
        self.assertTrue(v._ref_has_number("Revenue 28,00,000 and 18.2%", {"raw": "2800000", "value": 2800000.0}))
        self.assertTrue(v._ref_has_number("margin 18.20", {"raw": "18.2%", "value": 18.2}))
        self.assertFalse(v._ref_has_number("Revenue 1,234", {"raw": "9,999", "value": 9999.0}))
        self.assertIsNone(v._ref_has_number("x", {"raw": "-", "value": None}))

    def test_label_support(self):
        self.assertTrue(v._label_supported("Domestic Formulations Revenue", "domestic formulations grew"))
        self.assertFalse(v._label_supported("Domestic Formulations Revenue", "margin expanded"))
        self.assertIsNone(v._label_supported("12", "nothing"))


class LockTests(unittest.TestCase):
    def test_second_writer_refused_and_stale_taken_over(self):
        lock = tmpfile("run.lock")
        try:
            self.assertTrue(v.acquire_lock(lock))
            self.assertFalse(v.acquire_lock(lock))
            v.release_lock(lock)
            self.assertFalse(lock.exists())
            lock.write_text("99999999 2026-01-01\n")   # dead pid
            self.assertTrue(v.acquire_lock(lock))
            v.release_lock(lock)
        finally:
            cleanup(lock)


if __name__ == "__main__":
    unittest.main()

