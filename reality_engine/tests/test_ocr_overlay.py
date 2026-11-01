"""Acceptance checks for the T-034 page-OCR overlay in the pilot-60 chunk loader.

    python -m pytest reality_engine/tests/test_ocr_overlay.py -q

Fixture only: a tiny ``chunks_v3`` store (doc/chunk/chunk_tag) and a gzipped
``ocr_pages.jsonl`` in the HP job's shape (``thin_pages.py`` writes ``why``,
``existing_chars`` and ``existing_text``).  No live database is read and no
model is called.
"""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
import unittest
import unittest.mock
import uuid
from pathlib import Path

from reality_engine.pilot import extract60 as x

SHA = "a" * 64
DOC = {"doc_id": f"sha256:{SHA}", "sha256": SHA, "doc_type": "deck",
       "isin": "INE296A01024", "symbol_at_time": "BAJFINANCE",
       "title": "Q2 FY26 investor presentation", "event_date": "2025-11-04",
       "known_at": "2025-11-04T18:00:00", "fiscal_period": "Q2FY26",
       "page_count": 2, "raw_path": None}

#: Page 12 of the deck: an image-backed slide with almost no text layer.
THIN_BODY = "This slide is a chart; its labels sit in the image."
#: Page 13 of the same deck: a full text page, not thin.
FULL_BODY = (
    "Consolidated revenue for the quarter was Rs 1,000 crore, up 26% year on "
    "year, with growth coming from both existing and new customers. Management "
    "added that the pipeline remains healthy and that it expects the second "
    "half to be similar to the first, with no major change in the operating "
    "environment or in the competitive intensity it faces across its markets."
)
#: One chunk covers both pages; only page 12 has a thin text layer.
MULTI_BODY = f"{THIN_BODY}\n\n{FULL_BODY}"
FULL_QUOTE = "Consolidated revenue for the quarter was Rs 1,000 crore"
#: What the OCR job reads on page 12 (no number from the full page's text).
OCR_TEXT = (
    "Installed capacity utilisation was 78% during the quarter. The company "
    "added 12 new stores, taking the total to 4,212 stores across India. "
    "Management said demand stayed broad based across products and "
    "geographies, and that the new stores are ramping in line with the plan. "
    "The company reiterated its guidance for the year and said it sees no "
    "change in competitive intensity across its markets."
)
#: OCR text for a layer-check page that misses the text layer's 1,000.
OCR_MISSING_PAGE_NUMBER = "Revenue rose 26% year on year; demand was broad based."
#: OCR text that prints a number the text layer does not have.
OCR_EXTRA_NUMBER = "Revenue was Rs 1,000 crore and 1,200 new stores were added."

STORE_DDL = """
CREATE TABLE doc (
    doc_id TEXT PRIMARY KEY, sha256 TEXT, doc_type TEXT, isin TEXT, symbol_at_time TEXT,
    title TEXT, event_date TEXT, known_at TEXT, fiscal_period TEXT, page_count INTEGER,
    raw_path TEXT);
CREATE TABLE chunk (
    chunk_id INTEGER PRIMARY KEY, doc_id TEXT, section TEXT, body TEXT, page_from INTEGER,
    page_to INTEGER, unit_kind TEXT, fiscal_period TEXT, known_at TEXT);
CREATE TABLE chunk_tag (chunk_id INTEGER, tag TEXT);
"""


def ocr_row(page: int, text: str, why: str | None = None, existing_chars: int = 0,
            existing_text: str = "", low_conf: list[str] | None = None) -> dict:
    """One row in the HP job's shape (``thin_pages.py`` output)."""
    row = {"isin": DOC["isin"], "symbol": "BAJFINANCE", "doc_type": "deck",
           "doc_date": "2025-11-04", "file_name": "q2fy26_deck.pdf", "sha256": SHA,
           "page": page, "text": text, "mean_confidence": 0.93,
           "existing_chars": existing_chars, "existing_text": existing_text,
           "low_conf_numbers": low_conf or []}
    if why is not None:
        row["why"] = why
    return row


class OverlayTest(unittest.TestCase):
    def setUp(self) -> None:
        # The DSH sandbox's own temp dir refuses SQLite's files, and a directory
        # created here is not writable either; the repo's .tmp is the pilot's
        # scratch area, so the fixture files sit in it directly.
        self.tmp = x.REPO / ".tmp"
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.token = f"ocr_overlay_{uuid.uuid4().hex[:10]}"

    def tearDown(self) -> None:
        for path in self.tmp.glob(f"{self.token}_*"):
            try:
                path.unlink()
            except OSError:
                pass

    def store(self, pages: list[tuple[int, int, str]], **doc_over: object) -> Path:
        path = self.tmp / f"{self.token}_chunks_v3.db"
        doc = {**DOC, **doc_over}
        con = sqlite3.connect(path)
        con.executescript(STORE_DDL)
        con.execute("INSERT INTO doc VALUES (:doc_id,:sha256,:doc_type,:isin,:symbol_at_time,"
                    ":title,:event_date,:known_at,:fiscal_period,:page_count,:raw_path)", doc)
        for chunk_id, (page_from, page_to, body) in enumerate(pages, 1):
            con.execute("INSERT INTO chunk (chunk_id,doc_id,section,body,page_from,page_to,"
                        "unit_kind,fiscal_period,known_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (chunk_id, doc["doc_id"], "key slide", body, page_from, page_to,
                         "page", doc["fiscal_period"], doc["known_at"]))
        con.commit()
        con.close()
        return path

    def overlay(self, rows: list[dict]) -> Path:
        path = self.tmp / f"{self.token}_ocr_pages.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        return path

    def load(self, store: Path, overlay: Path) -> tuple[dict, list[dict]]:
        with unittest.mock.patch.dict(os.environ, {"REALITY_OCR_OVERLAY": str(overlay)}):
            return x.load_store(store)

    # acceptance 1+2: a thin page inside a two-page chunk is added as its own
    # chunk; the original body is never edited.
    def test_thin_page_in_multi_page_chunk_is_added_not_replaced(self):
        store = self.store([(12, 13, MULTI_BODY)])
        overlay = self.overlay([ocr_row(12, OCR_TEXT, why="thin",
                                        existing_chars=len(THIN_BODY),
                                        low_conf=["3,50,000"])])
        docs, chunks = self.load(store, overlay)
        self.assertEqual(len(chunks), 2)
        original = next(chunk for chunk in chunks if chunk["chunk_id"] == 1)
        self.assertEqual(original["body"], MULTI_BODY)
        self.assertEqual(original["text_source"], "chunk")
        ocr = next(chunk for chunk in chunks if chunk["text_source"] == "ocr")
        self.assertEqual(ocr["chunk_id"], f"ocr:{DOC['doc_id']}:12")
        self.assertEqual(ocr["body"], OCR_TEXT)
        self.assertEqual((ocr["page_from"], ocr["page_to"]), (12, 12))
        self.assertEqual(ocr["doc_id"], DOC["doc_id"])
        self.assertEqual(ocr["low_conf_numbers"], ["3,50,000"])
        self.assertEqual(x.OCR_STATS["pages"]["thin_applied"], 1)

    # acceptance 5: the OCR passage reaches the reader, in page order, and a
    # quote found only there validates as source ocr.
    def test_ocr_page_reaches_reader_in_page_order_and_quote_is_ocr(self):
        store = self.store([(12, 13, MULTI_BODY), (20, 20, FULL_BODY)])
        overlay = self.overlay([ocr_row(12, OCR_TEXT, why="thin",
                                        existing_chars=len(THIN_BODY))])
        docs, chunks = self.load(store, overlay)
        passages = x.select_passages(x.SPECS["company_capacity_utilisation"],
                                     docs[DOC["doc_id"]], chunks)
        ocr = [passage for passage in passages if passage["text_source"] == "ocr"]
        self.assertEqual(len(ocr), 1)
        self.assertEqual(ocr[0]["section"], "ocr")
        self.assertEqual(ocr[0]["tags"], set())
        pages = [passage["page_from"] for passage in passages if passage.get("dense")]
        self.assertEqual(pages, sorted(pages))
        self.assertIn(12, pages)
        row = {"product": "stores", "period_end": "2025-09-30", "capacity": None,
               "capacity_unit": None, "utilisation_pct": 78, "production": None,
               "page": 12,
               "quote": "Installed capacity utilisation was 78% during the quarter"}
        clean, reason = x.validate("company_capacity_utilisation", row,
                                   docs[DOC["doc_id"]], passages)
        self.assertIsNone(reason)
        assert clean is not None
        self.assertEqual(clean["page"], 12)
        self.assertEqual(clean["source"], "ocr")

    # acceptance 5: a quote found only in the original multi-page chunk stays
    # chunks_v3, even though an OCR chunk covers the same page.
    def test_quote_from_full_page_keeps_chunks_v3(self):
        store = self.store([(12, 13, MULTI_BODY)])
        overlay = self.overlay([ocr_row(12, OCR_TEXT, why="thin",
                                        existing_chars=len(THIN_BODY))])
        docs, chunks = self.load(store, overlay)
        # validate's own passages argument is where it looks: the original
        # multi-page chunk carries the quote, the OCR chunk on page 12 does not.
        passages = chunks
        row = {"metric": "revenue", "period_end": "2025-09-30",
               "value": 1000, "unit": "inr_cr", "page": 13, "quote": FULL_QUOTE}
        clean, reason = x.validate("company_operating_metrics", row,
                                   docs[DOC["doc_id"]], passages)
        self.assertIsNone(reason)
        assert clean is not None
        self.assertIn(clean["page"], (12, 13))   # the chunk's own page_from
        self.assertEqual(clean["source"], "chunks_v3")

    # acceptance 3+4: a layer-check row never changes the reader's text; a
    # number the OCR missed is logged from the row's own existing_text.
    def test_layer_check_missed_number_leaves_text_unchanged(self):
        store = self.store([(12, 13, MULTI_BODY)])
        overlay = self.overlay([ocr_row(13, OCR_MISSING_PAGE_NUMBER, why="layer_check",
                                        existing_chars=len(FULL_BODY),
                                        existing_text=FULL_BODY)])
        docs, chunks = self.load(store, overlay)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["body"], MULTI_BODY)
        self.assertEqual(chunks[0]["text_source"], "chunk")
        self.assertEqual(x.OCR_STATS["pages"]["layer_check_pages"], 1)
        logged = x.OCR_STATS["per_doc"][DOC["doc_id"]]["numbers_only_in_text"]
        self.assertEqual(logged, [{"page": 13, "numbers": ["1000"]}])
        self.assertEqual(x.OCR_STATS["per_doc"][DOC["doc_id"]]["numbers_only_in_ocr"], [])
        passages = x.select_passages(x.SPECS["company_capacity_utilisation"],
                                     docs[DOC["doc_id"]], chunks)
        self.assertFalse(any(p["text_source"] == "ocr" for p in passages))

    # acceptance 4: a number only OCR has is logged too.
    def test_layer_check_extra_ocr_number_is_logged(self):
        store = self.store([(7, 7, "Revenue was Rs 1,000 crore for the quarter.")])
        overlay = self.overlay([ocr_row(7, OCR_EXTRA_NUMBER, why="layer_check",
                                        existing_text="Revenue was Rs 1,000 crore for "
                                                      "the quarter.")])
        docs, chunks = self.load(store, overlay)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(x.OCR_STATS["pages"]["layer_check_pages"], 1)
        self.assertEqual(x.OCR_STATS["pages"]["numbers_only_in_text"], 0)
        logged = x.OCR_STATS["per_doc"][DOC["doc_id"]]["numbers_only_in_ocr"]
        self.assertEqual(logged, [{"page": 7, "numbers": ["1200"]}])

    # acceptance 4: a row with no why is counted and not applied.
    def test_row_without_why_is_counted_and_not_applied(self):
        store = self.store([(7, 7, THIN_BODY)])
        overlay = self.overlay([ocr_row(7, OCR_TEXT, why=None,
                                        existing_chars=len(THIN_BODY))])
        docs, chunks = self.load(store, overlay)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["body"], THIN_BODY)
        self.assertEqual(x.OCR_STATS["pages"]["bad_rows"], 1)
        self.assertEqual(x.OCR_STATS["per_doc"][DOC["doc_id"]]["bad_rows"], 1)

    # acceptance 6: a missing overlay file changes nothing.
    def test_missing_overlay_file_changes_nothing(self):
        store = self.store([(3, 3, THIN_BODY)])
        docs, chunks = self.load(store, self.tmp / f"{self.token}_absent.jsonl.gz")
        self.assertEqual(chunks[0]["body"], THIN_BODY)
        self.assertEqual(chunks[0]["text_source"], "chunk")
        self.assertFalse(x.OCR_STATS["present"])
        self.assertEqual(x.OCR_STATS["pages"], {})

    def test_thin_row_unmatched_to_a_document_is_counted(self):
        store = self.store([(1, 1, THIN_BODY)], sha256="b" * 64)
        overlay = self.overlay([ocr_row(1, OCR_TEXT, why="thin",
                                        existing_chars=len(THIN_BODY))])
        docs, chunks = self.load(store, overlay)
        self.assertEqual(chunks[0]["body"], THIN_BODY)
        self.assertEqual(x.OCR_STATS["pages"]["thin_unmatched"], 1)
        self.assertFalse(x.OCR_STATS["per_doc"])


    # T-040 whole-page rule: an OCR chunk needs 2+ distinct numbers to go whole.
    def test_ocr_chunk_with_one_number_is_not_whole_page(self):
        one = {"text_source": "ocr", "body": "Management commentary with 7 new hires."}
        two = {"text_source": "ocr", "body": "Revenue 1,240 crore and EBIT 210 crore."}
        self.assertFalse(x.is_whole_page(one))
        self.assertTrue(x.is_whole_page(two))

    # T-040: the one-number page takes the ordinary keyword path and is not sent.
    def test_one_number_ocr_page_is_not_sent_whole(self):
        store = self.store([(12, 12, THIN_BODY)])
        overlay = self.overlay([ocr_row(12, "Management commentary with 7 new hires.",
                                        why="thin", existing_chars=len(THIN_BODY))])
        docs, chunks = self.load(store, overlay)
        self.assertEqual(len(chunks), 2)
        spec = {"docs": ("deck",), "sections": (), "tags": (), "max_passages": 4,
                "terms": "revenue|margin|EBIT", "needs_number": True}
        passages = x.select_passages(spec, docs[DOC["doc_id"]], chunks)
        self.assertNotIn("ocr", {chunk.get("section") for chunk in passages})


if __name__ == "__main__":
    unittest.main()
