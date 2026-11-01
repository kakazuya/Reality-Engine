"""Acceptance checks for the T-034 page-OCR overlay in the pilot-60 chunk loader.

    python -m pytest reality_engine/tests/test_ocr_overlay.py -q

Fixture only: a tiny ``chunks_v3`` store (doc/chunk/chunk_tag) and a gzipped
``ocr_pages.jsonl`` in the HP job's shape.  No live database is read and no
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

#: A thin text layer on an image-backed deck page.
THIN_BODY = "Installed capacity utilisation was 78% during the quarter."
#: What the OCR job reads on that page (> THIN_PAGE_CHARS).
OCR_TEXT = (
    "Installed capacity utilisation was 78% during the quarter. The company added 12 "
    "new stores, taking the total to 4,212 stores across India. Consolidated revenue "
    "for the quarter was Rs 3,50,000 crore, up 26% year on year. Management said demand "
    "stayed broad based across products and geographies, and that the new stores are "
    "ramping in line with the plan. The company reiterated its guidance for the year "
    "and said it sees no change in competitive intensity across its markets."
)
#: A page with a good text layer that agrees with the OCR on its numbers.
GOOD_BODY = (
    "Installed capacity utilisation was 82% in the quarter and demand stayed broad "
    "based across products. The company said consolidated revenue for the quarter was "
    "Rs 1,000 crore, up 26% year on year, with growth coming from both existing and new "
    "customers. Management added that the pipeline remains healthy and that it expects "
    "the second half to be similar to the first, with no major change in the operating "
    "environment or in the competitive intensity it faces across its markets."
)
GOOD_OCR_TEXT = (
    "Capacity utilisation of 82% was reported. Revenue came in at Rs 1,000 crore, a "
    "rise of 26% year on year. Demand was broad based across products and the company "
    "expects the second half to be similar to the first. The competitive environment "
    "did not change materially during the quarter."
)
#: A good page whose hidden text layer prints a number the OCR row does not.
DISAGREE_BODY = ("Revenue for the quarter was Rs 1,000 crore, up 26% year on year. " * 8)
DISAGREE_OCR_TEXT = ("Revenue for the quarter was Rs 1,200 crore, up 26% year on year. "
                     "Demand was broad based during the quarter.")

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


def ocr_row(page: int, text: str, low_conf: list[str] | None = None) -> dict:
    """One row in the HP job's shape (OCRPAGES_SCHEMA)."""
    return {"isin": DOC["isin"], "symbol": "BAJFINANCE", "doc_type": "deck",
            "doc_date": "2025-11-04", "file_name": "q2fy26_deck.pdf", "sha256": SHA,
            "page": page, "text": text, "mean_confidence": 0.93,
            "low_conf_numbers": low_conf or []}


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

    def store(self, pages: list[tuple[int, str]], **doc_over: object) -> Path:
        path = self.tmp / f"{self.token}_chunks_v3.db"
        doc = {**DOC, **doc_over}
        con = sqlite3.connect(path)
        con.executescript(STORE_DDL)
        con.execute("INSERT INTO doc VALUES (:doc_id,:sha256,:doc_type,:isin,:symbol_at_time,"
                    ":title,:event_date,:known_at,:fiscal_period,:page_count,:raw_path)", doc)
        for chunk_id, (page, body) in enumerate(pages, 1):
            con.execute("INSERT INTO chunk (chunk_id,doc_id,section,body,page_from,page_to,"
                        "unit_kind,fiscal_period,known_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (chunk_id, doc["doc_id"], "key slide", body, page, page, "page",
                         doc["fiscal_period"], doc["known_at"]))
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

    # acceptance 1: a thin page gets the OCR text
    def test_thin_page_gets_ocr_text(self):
        store = self.store([(12, THIN_BODY)])
        overlay = self.overlay([ocr_row(12, OCR_TEXT, low_conf=["3,50,000"])])
        docs, chunks = self.load(store, overlay)
        self.assertEqual(len(chunks), 1)
        chunk = chunks[0]
        self.assertEqual(chunk["body"], OCR_TEXT)
        self.assertEqual(chunk["text_source"], "ocr")
        self.assertEqual(chunk["page_from"], 12)
        self.assertEqual(chunk["doc_id"], DOC["doc_id"])
        self.assertEqual(chunk["low_conf_numbers"], ["3,50,000"])
        self.assertEqual(x.OCR_STATS["pages"]["filled"], 1)
        self.assertEqual(x.OCR_STATS["pages"]["still_thin"], 0)

    # acceptance 2: a page with good text keeps it
    def test_good_page_keeps_its_text(self):
        store = self.store([(7, GOOD_BODY)])
        overlay = self.overlay([ocr_row(7, GOOD_OCR_TEXT)])
        docs, chunks = self.load(store, overlay)
        self.assertEqual(chunks[0]["body"], GOOD_BODY)
        self.assertEqual(chunks[0]["text_source"], "chunk")
        self.assertEqual(x.OCR_STATS["pages"]["filled"], 0)
        self.assertEqual(x.OCR_STATS["pages"]["disagreements"], 0)

    # acceptance 3: a missing overlay file changes nothing
    def test_missing_overlay_file_changes_nothing(self):
        store = self.store([(3, THIN_BODY)])
        docs, chunks = self.load(store, self.tmp / f"{self.token}_absent.jsonl.gz")
        self.assertEqual(chunks[0]["body"], THIN_BODY)
        self.assertEqual(chunks[0]["text_source"], "chunk")
        self.assertFalse(x.OCR_STATS["present"])
        self.assertEqual(x.OCR_STATS["pages"], {})
        self.assertEqual(chunks[0]["page_from"], 3)

    # acceptance 4: a page with no OCR row stays as is and is counted
    def test_page_with_no_ocr_row_stays_and_is_counted(self):
        other = "Management commentary was not captured in the text layer."
        store = self.store([(1, THIN_BODY), (2, other)])
        overlay = self.overlay([ocr_row(1, OCR_TEXT)])
        docs, chunks = self.load(store, overlay)
        by_page = {chunk["page_from"]: chunk for chunk in chunks}
        self.assertEqual(by_page[2]["body"], other)
        self.assertEqual(by_page[2]["text_source"], "chunk")
        self.assertEqual(x.OCR_STATS["pages"]["thin_before"], 2)
        self.assertEqual(x.OCR_STATS["pages"]["filled"], 1)
        self.assertEqual(x.OCR_STATS["pages"]["unmatched"], 1)
        self.assertEqual(x.OCR_STATS["pages"]["still_thin"], 1)
        self.assertEqual(x.OCR_STATS["per_doc"][DOC["doc_id"]]["unmatched"], 1)

    # acceptance 5: a quote taken from OCR text passes the quote check
    def test_quote_from_ocr_text_passes_the_quote_check(self):
        store = self.store([(12, THIN_BODY)])
        overlay = self.overlay([ocr_row(12, OCR_TEXT)])
        docs, chunks = self.load(store, overlay)
        row = {"product": "stores", "period_end": "2025-09-30", "capacity": None,
               "capacity_unit": None, "utilisation_pct": 78, "production": None,
               "page": 12,
               "quote": "Installed capacity utilisation was 78% during the quarter"}
        clean, reason = x.validate("company_capacity_utilisation", row, docs[DOC["doc_id"]],
                                   chunks)
        self.assertIsNone(reason)
        assert clean is not None
        self.assertEqual(clean["page"], 12)
        self.assertEqual(clean["doc_id"], DOC["doc_id"])
        self.assertEqual(clean["source"], "ocr")

    # acceptance 6: the source of each passage is recorded
    def test_source_of_each_passage_is_recorded(self):
        store = self.store([(1, THIN_BODY), (2, GOOD_BODY)])
        overlay = self.overlay([ocr_row(1, OCR_TEXT), ocr_row(2, GOOD_OCR_TEXT)])
        docs, chunks = self.load(store, overlay)
        passages = x.select_passages(x.SPECS["company_capacity_utilisation"],
                                     docs[DOC["doc_id"]], chunks)
        sources = {passage["page_from"]: passage["text_source"] for passage in passages}
        self.assertEqual(sources, {1: "ocr", 2: "chunk"})

    # work item 2: the hidden text layer is wrong on its numbers, OCR wins
    def test_number_disagreement_gives_the_page_to_ocr(self):
        self.assertGreater(len(DISAGREE_BODY), x.THIN_PAGE_CHARS)
        store = self.store([(5, DISAGREE_BODY)])
        overlay = self.overlay([ocr_row(5, DISAGREE_OCR_TEXT)])
        docs, chunks = self.load(store, overlay)
        self.assertEqual(chunks[0]["body"], DISAGREE_OCR_TEXT)
        self.assertEqual(chunks[0]["text_source"], "ocr")
        self.assertEqual(x.OCR_STATS["pages"]["disagreements"], 1)
        logged = x.OCR_STATS["per_doc"][DOC["doc_id"]]
        self.assertEqual(logged["disagreement_pages"][0]["page"], 5)
        self.assertEqual(logged["disagreement_pages"][0]["text_layer_numbers"], ["1000"])

    # work item 1: the overlay joins the document by sha256, not by symbol
    def test_unmatched_sha_changes_nothing(self):
        store = self.store([(1, THIN_BODY)], sha256="b" * 64)
        overlay = self.overlay([ocr_row(1, OCR_TEXT)])   # row carries SHA = "a" * 64
        docs, chunks = self.load(store, overlay)
        self.assertEqual(chunks[0]["body"], THIN_BODY)
        self.assertEqual(chunks[0]["text_source"], "chunk")
        self.assertFalse(x.OCR_STATS["per_doc"])


if __name__ == "__main__":
    unittest.main()
