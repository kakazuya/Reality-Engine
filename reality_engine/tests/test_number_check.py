"""Acceptance checks for the T-040 number check and the dispute re-read.

    python -m pytest reality_engine/tests/test_number_check.py -q

Fixtures only: an extract DB built from ``extract60.DDL`` in the repo's ``.tmp`` and
overlay rows in the HP job's shape.  The crop re-read is stubbed, so no page is rendered
and no model, GPU or network call is made.
"""
from __future__ import annotations

import sqlite3
import unittest
import unittest.mock
import uuid
from collections import Counter

from reality_engine.pilot import extract60 as x
from reality_engine.pilot import proto3 as p

SHA = "a" * 64
DOC_ID = f"sha256:{SHA}"
#: The Tata Elxsi fault the ticket names: the text layer prints 0055.19, the PDF 10,056.19.
TEXT_LAYER = "Revenue for the year was 0055.19 crore in FY26."
OCR_READING = "Revenue for the year was 10,056.19 crore in FY26."


def ocr_row(page: int = 21, text: str = OCR_READING, existing_text: str = TEXT_LAYER,
            error: str | None = None, low_conf: list[str] | None = None) -> dict:
    """One page row in the HP job's shape (``thin_pages.py`` output)."""
    row = {"sha256": SHA, "page": page, "why": "layer_check", "text": text,
           "existing_text": existing_text, "mean_confidence": 0.92,
           "low_conf_numbers": low_conf or []}
    if error is not None:
        row["error"] = error
    return row


def measure_row(**over: object) -> dict:
    """A segment-P&L row as ``validate`` returns it (value printed in Rs crore)."""
    row = {"isin": "INE296A01032", "known_at": "2026-05-01T10:00:00", "doc_id": DOC_ID,
           "quote": "Revenue for the year was 10,056.19 crore",
           "page": 21, "source": "chunks_v3", "segment": "Consumer",
           "period_end": "2026-03-31", "metric": "revenue", "basis": "consolidated",
           "value_cr": 10056.19, "share_of_total_pct": None}
    row.update(over)
    return row


def check_of(row: dict, pages: dict, table: str = "company_segment_pnl") -> dict:
    return x.number_check_row(table, row, SHA, pages)


class NumberCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = x.REPO / ".tmp"
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.token = f"number_check_{uuid.uuid4().hex[:10]}"

    def tearDown(self) -> None:
        for path in self.tmp.glob(f"{self.token}*"):
            try:
                path.unlink()
            except OSError:
                pass

    # acceptance: a number in both readings is confirmed.
    def test_number_in_both_readings_is_confirmed(self):
        page = ocr_row(text="Revenue was 10,056.19 crore.",
                       existing_text="Revenue was 10,056.19 crore.")
        check = check_of(measure_row(), {SHA: {21: page}})
        self.assertEqual(check["status"], "confirmed")
        self.assertEqual((check["in_text_layer"], check["in_ocr"]), (1, 1))
        self.assertEqual(check["printed_token"], "10,056.19")
        self.assertEqual(check["quote_source"], "chunks_v3")
        self.assertIsNone(check["reason"])

    # acceptance: "1,000" and "1000" compare equal.
    def test_comma_grouping_compares_equal(self):
        page = ocr_row(text="Revenue was 1000 crore.",
                       existing_text="Revenue was Rs. 1,000 crore.")
        check = check_of(measure_row(quote="Revenue was Rs 1,000 crore", value_cr=1000.0),
                         {SHA: {21: page}})
        self.assertEqual(check["status"], "confirmed")
        self.assertEqual(check["printed_token"], "1,000")

    # acceptance: the Tata Elxsi fault is disputed whichever source the quote used.
    def test_text_layer_misread_is_disputed_from_the_text_layer(self):
        check = check_of(measure_row(quote="Revenue for the year was 0055.19 crore",
                                     value_cr=55.19),
                         {SHA: {21: ocr_row()}})
        self.assertEqual(check["status"], "disputed")
        self.assertEqual((check["in_text_layer"], check["in_ocr"]), (1, 0))
        self.assertEqual(check["printed_token"], "0055.19")
        self.assertEqual(check["other_token"], "10,056.19")

    def test_text_layer_misread_is_disputed_from_the_ocr(self):
        check = check_of(measure_row(), {SHA: {21: ocr_row()}})
        self.assertEqual(check["status"], "disputed")
        self.assertEqual((check["in_text_layer"], check["in_ocr"]), (0, 1))
        self.assertEqual(check["printed_token"], "10,056.19")
        self.assertEqual(check["other_token"], "0055.19")

    # acceptance: blank OCR text with no error is a reading that lacks the number.
    def test_blank_ocr_text_without_error_is_disputed(self):
        check = check_of(measure_row(quote="Revenue was 10,056.19 crore"),
                         {SHA: {21: ocr_row(text="", existing_text=OCR_READING)}})
        self.assertEqual(check["status"], "disputed")
        self.assertEqual(check["in_ocr"], 0)

    # acceptance: no OCR row and an OCR error are unchecked, with the reason kept.
    def test_no_ocr_row_is_unchecked(self):
        check = check_of(measure_row(), {SHA: {}})
        self.assertEqual((check["status"], check["reason"]), ("unchecked", "no_ocr_row"))
        self.assertIsNone(check["in_text_layer"])

    def test_ocr_error_is_unchecked(self):
        check = check_of(measure_row(), {SHA: {21: ocr_row(error="page raster failed")}})
        self.assertEqual((check["status"], check["reason"]), ("unchecked", "ocr_error"))

    def test_row_without_a_page_or_a_number_is_unchecked(self):
        self.assertEqual(check_of(measure_row(page=None), {SHA: {21: ocr_row()}})["reason"],
                         "no_page")
        empty = check_of({"quote": "Rating action followed the review",
                          "doc_id": DOC_ID, "page": 21}, {SHA: {21: ocr_row()}},
                         table="rating_action")
        self.assertEqual((empty["status"], empty["reason"]), ("unchecked", "no_value"))

    def test_low_confidence_token_is_flagged(self):
        check = check_of(measure_row(), {SHA: {21: ocr_row(low_conf=["10,056.19"])}})
        self.assertEqual(check["in_low_conf"], 1)
        self.assertEqual(check["ocr_mean_confidence"], 0.92)

    # acceptance: load_ocr_pages keeps the rows that used to vanish.
    def test_loader_keeps_blank_text_and_error_rows(self):
        path = self.tmp / f"{self.token}_ocr_pages.jsonl.gz"
        with x.gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write(x.json.dumps(ocr_row(page=1, text="")) + "\n")
            handle.write(x.json.dumps(ocr_row(page=2, error="boom")) + "\n")
        pages = x.load_ocr_pages(path)
        self.assertEqual(sorted(pages[SHA]), [1, 2])

    def test_write_stores_the_check_and_keeps_the_measure_row(self):
        db = self.tmp / f"{self.token}_extract.db"
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        con.executescript(x.DDL)
        pages = {SHA: {21: ocr_row(text="Revenue was 10,056.19 crore.",
                                   existing_text="Revenue was 10,056.19 crore.")}}
        row = measure_row()
        with unittest.mock.patch.object(x, "OCR_PAGES", pages):
            x._write(con, "company_segment_pnl", [row], Counter(), Counter(),
                     {DOC_ID: {"sha256": SHA}})
            check = dict(con.execute("SELECT * FROM number_check").fetchone())
            self.assertEqual(check["status"], "confirmed")
            self.assertEqual(check["row_pk"], x.row_pk("company_segment_pnl", row))
            # a second write of the same row (INSERT OR IGNORE) keeps a resolution.
            con.execute("UPDATE number_check SET resolved_value = '10,056.19', "
                        "resolved_by = 'rapidocr_crop'")
            x._write(con, "company_segment_pnl", [row], Counter(), Counter(),
                     {DOC_ID: {"sha256": SHA}})
        stored = tuple(con.execute(
            "SELECT quote, value_cr FROM company_segment_pnl").fetchone())
        self.assertEqual(stored, ("Revenue for the year was 10,056.19 crore", 10056.19))
        self.assertEqual(con.execute("SELECT resolved_by FROM number_check").fetchone()[0],
                         "rapidocr_crop")
        con.close()


    def test_dryrun_report_counts_by_company_and_unchecked_reason(self):
        rows = [check_of(measure_row(), {SHA: {21: ocr_row()}}),
                check_of(measure_row(), {SHA: {}})]
        docs = {DOC_ID: {"isin": "INE296A01032", "doc_type": "annual_report"}}
        report = p._number_check_report(rows, docs)
        self.assertEqual(report["by_company_doc_type"]["BAJFINANCE|annual_report"],
                         {"confirmed": 0, "disputed": 1, "unchecked": 1})
        self.assertEqual(report["unchecked_reasons"], {"no_ocr_row": 1})
        self.assertEqual(p._number_check_report(None, docs), {"present": False})


class RecheckTest(unittest.TestCase):
    """``proto3 recheck`` resolves only on an exact match with one candidate."""

    def setUp(self) -> None:
        self.tmp = x.REPO / ".tmp"
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.token = f"recheck_{uuid.uuid4().hex[:10]}"
        self.pdf = self.tmp / f"{self.token}.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 fixture\n")
        self.db = self.tmp / f"{self.token}_extract.db"
        self.docs = {DOC_ID: {"doc_id": DOC_ID, "sha256": SHA, "doc_type": "annual_report",
                              "isin": "INE296A01032", "raw_path": str(self.pdf)}}

    def tearDown(self) -> None:
        for path in self.tmp.glob(f"{self.token}*"):
            try:
                path.unlink()
            except OSError:
                pass

    def seed(self, **over: object) -> None:
        check = check_of(measure_row(**over), {SHA: {21: ocr_row()}})
        self.assertEqual(check["status"], "disputed")
        check["row_pk"] = "row-1"
        con = sqlite3.connect(self.db)
        con.executescript(x.DDL)
        columns = ", ".join(check)
        con.execute(f"INSERT INTO number_check ({columns}) VALUES "
                    f"({', '.join('?' * len(check))})", list(check.values()))
        con.commit()
        con.close()

    def test_recheck_resolves_when_the_reread_equals_one_candidate(self):
        self.seed(source="ocr")     # the quote was read from the OCR chunk
        out = p.cmd_recheck(db=self.db, docs=self.docs,
                            read_page=lambda _pdf, _page, _token: "10,056.19 crore")
        self.assertEqual(out["resolved"], 1)
        self.assertEqual(out["won"], {"ocr": 1})
        self.assertEqual(out["by_status"]["disputed"], 1)
        con = sqlite3.connect(self.db)
        row = con.execute("SELECT resolved_value, resolved_by, status FROM number_check"
                          ).fetchone()
        con.close()
        self.assertEqual(row, ("10,056.19", "rapidocr_crop", "disputed"))

    def test_recheck_leaves_it_disputed_when_the_reread_equals_neither(self):
        self.seed()
        out = p.cmd_recheck(db=self.db, docs=self.docs,
                            read_page=lambda _pdf, _page, _token: "revenue grew 9.9%")
        self.assertEqual(out["resolved"], 0)
        self.assertEqual(out["left_disputed"], {"no_exact_match": 1})
        con = sqlite3.connect(self.db)
        row = con.execute("SELECT resolved_value, resolved_by FROM number_check").fetchone()
        con.close()
        self.assertEqual(row, (None, None))

    def test_recheck_without_a_pdf_leaves_it_disputed(self):
        self.seed()
        docs = {DOC_ID: {"doc_id": DOC_ID, "raw_path": str(self.tmp / f"{self.token}_gone.pdf")}}
        out = p.cmd_recheck(db=self.db, docs=docs, read_page=lambda *a: "10,056.19")
        self.assertEqual(out["left_disputed"], {"no_pdf": 1})


if __name__ == "__main__":
    unittest.main()
