"""T-161/T-159: a document's own first pages correct the record's type and date (pure text, no store, no PDF).

Each date case is one of the six misdated q12 transcripts (Opus held audit, 10 Nov 2026): a company-website
crawl stored a 2016-2018 call under its August 2026 crawl date.  ``reconcile_doc`` takes the printed call date.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pytest

from reality_engine import raw_store
from reality_engine.pilot3 import profile
from reality_engine.pilot3.call_dates import call_date
from reality_engine.pilot3.docs_collect import collect_manifest, reconcile_doc

CALL_BODY = "Moderator: Welcome to the call. Management participants: the CFO. Question and answer session follows."


def _call(date: str) -> list[str]:
    """The first three pages of a call transcript: the header date, the participants and the Q&A."""
    return [f"TATAELXSI Limited Earnings Call\n{date}\n{CALL_BODY}",
            "Management Participants: Mr. X, Chief Financial Officer.\n" + CALL_BODY,
            "Question and Answer session.\n" + CALL_BODY]


@pytest.mark.parametrize("printed, filed", [
    ("July 27, 2018", "2026-08-28"),        # TATAELXSI
    ("January 22, 2018", "2026-08-28"),     # TATAELXSI
    ("December 13, 2017", "2026-08-28"),    # APLAPOLLO
    ("October 29, 2018", "2026-08-29"),     # EDELWEISS
    ("November 11, 2016", "2026-08-29"),    # EDELWEISS
    ("August 10, 2016", "2026-08-28"),      # EDELWEISS
])
def test_a_printed_call_date_years_before_the_record_wins(printed, filed):
    pages = _call(printed)
    expected = call_date(pages)                      # the reader the rule and the build share
    doc_type, filing_date, known_at, notes = reconcile_doc(
        "transcript", filed, f"{filed}T09:00:00", 12, pages)
    assert doc_type == "transcript"
    assert (filing_date, known_at) == (expected, f"{expected}T23:59:59")
    assert notes["date_source"] == "printed" and notes["record_filing_date"] == filed
    assert notes["record_known_at"] == f"{filed}T09:00:00"


def test_a_covering_letter_dated_at_the_filing_keeps_the_record():
    """Page 1 is the covering letter dated at filing, page 2 the call three days earlier: both are near it."""
    pages = ["Covering letter dated August 31, 2026. Please find enclosed the transcript.",
             "TATAELXSI Limited Earnings Call August 28, 2026\n" + CALL_BODY,
             CALL_BODY]
    assert reconcile_doc("transcript", "2026-08-31", "2026-08-31T18:00:00", 9, pages) == (
        "transcript", "2026-08-31", "2026-08-31T18:00:00", {})


def test_a_date_after_the_record_never_moves_it_later():
    """A 2027 date on a document filed 2026-01-01 is not a reason to move a date forward (ticket step 1)."""
    pages = _call("January 5, 2027")
    assert reconcile_doc("transcript", "2026-01-01", "2026-01-01T10:00:00", 5, pages)[1:3] == (
        "2026-01-01", "2026-01-01T10:00:00")


def test_the_first_pages_not_a_late_mention_date_the_document():
    """A 2026 transcript that mentions 2018 on page 5 keeps its 2026 filing date (only pages 1-3 are read)."""
    pages = _call("August 28, 2026")               # the caller passes pages 1-3; page 5 is never in this list
    assert reconcile_doc("transcript", "2026-08-28", "2026-08-28T18:00:00", 40, pages)[1] == "2026-08-28"
    # and the same text with the 2018 date on page 1 is re-dated: it is the position, not the year, that decides
    assert reconcile_doc("transcript", "2026-08-28", "2026-08-28T18:00:00", 40, _call("July 27, 2018"))[1] == "2018-07-27"


def test_a_meet_outcome_whose_first_pages_are_a_call_is_a_transcript():
    """HAVELLS files its call as 'Analyst / Investor Meet - Outcome'; the pages say it is a transcript."""
    pages = [f"Analyst / Investor Meet - Outcome\nHAVELLS India Limited Earnings Call July 24, 2024\n{CALL_BODY}",
             "Management Participants: Mr. Y.\n" + CALL_BODY, CALL_BODY]
    doc_type, filing_date, known_at, notes = reconcile_doc(
        "announcement", "2024-07-24", "2024-07-24T18:00:00", 16, pages)
    assert doc_type == "transcript"
    assert (filing_date, known_at) == ("2024-07-24", "2024-07-24T18:00:00")
    assert notes == {"type_source": "printed", "record_type": "announcement"}


def test_a_press_release_that_names_the_conference_call_is_not_a_transcript():
    """HINDALCO/ASIANPAINT file a results news release and a deck that say "a conference call will be held"."""
    pages = ["News Release: Q2 FY26 Results. The Company will host a conference call at 5:00 pm IST today.",
             "Performance highlights and the earnings call dial-in are enclosed. Segmental results overleaf.",
             "The results and the call details continue on the following pages."]
    assert reconcile_doc("press_release", "2025-11-04", "2025-11-04T18:00:00", 30, pages) == (
        "press_release", "2025-11-04", "2025-11-04T18:00:00", {})


def test_a_call_intimation_is_not_a_transcript():
    """TITAN/APLAPOLLO/BHARTIARTL intimations say "followed by a Q&A session"; only the transcript has a moderator."""
    pages = ["Intimation of earnings call: a brief management discussion on the Q1FY2020 results followed by an "
             "interactive Question & Answer session. Details of the conference call are as follows:",
             "The audio recording and call transcript will be made available on the Company's website.",
             "Management team will be represented by the CFO."]
    assert reconcile_doc("announcement", "2026-07-22", "2026-07-22T18:00:00", 3, pages) == (
        "announcement", "2026-07-22", "2026-07-22T18:00:00", {})


def test_a_results_pdf_printing_only_its_comparatives_keeps_its_date():
    """SAIL's 2020 results PDFs print a 2015 comparative only: a results document's date is its period end."""
    pages = ["Statement of unaudited financial results for the quarter ended 30 June 2015.",
             "Figures in Rs crore; comparative for the quarter ended 30 June 2015 shown alongside.",
             "Notes to the results follow."]
    assert reconcile_doc("results", "2020-09-14", "2020-09-14T18:00:00", 20, pages) == (
        "results", "2020-09-14", "2020-09-14T18:00:00", {})


def test_a_deck_printing_its_period_start_keeps_its_date():
    """A HINDALCO Q4 FY25 deck filed 2025-11-21 prints "April 1, 2025" as its period start, not its own date."""
    pages = ["Investor presentation: the period from April 1, 2025 onward. Management commentary follows.",
             "Segment highlights for the year ended March 31, 2025.",
             "Safe harbour statement."]
    assert reconcile_doc("deck", "2025-11-21", "2025-11-21T18:00:00", 40, pages) == (
        "deck", "2025-11-21", "2025-11-21T18:00:00", {})


def test_a_one_page_audio_link_stays_an_announcement():
    """The one-page meet outcome on results day is the audio link, not the transcript."""
    pages = ["Analyst / Investor Meet - Outcome. The audio recording of the call moderated by the company is at "
             "https://example.invalid/audio"]
    assert reconcile_doc("announcement", "2024-07-24", "2024-07-24T18:00:00", 1, pages) == (
        "announcement", "2024-07-24", "2024-07-24T18:00:00", {})


def _write_pdf(path: Path, pages: list[str]) -> Path:
    import pymupdf

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((40, 60), text, fontsize=11)
    doc.save(path)
    doc.close()
    return path


def _write_manifest(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["isin", "symbol_at_time", "newsid", "bucket", "category", "subcat", "headline", "dissem_ts",
                  "url", "local_path", "sha256", "status"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return path


def test_collect_manifest_audio_link_keeps_transcript_and_drops_link_letter(tmp_path: Path):
    """T-223: a 4-page concall_audio_link transcript is kept as transcript; a 1-page link letter is dropped."""
    pytest.importorskip("pymupdf")
    raw = tmp_path / "raw"
    tx_pdf = _write_pdf(raw / "FAIRCHEMOR" / "concall_audio_link" / "tx1.pdf", [
        "Moderator: Ladies and gentlemen, good day and welcome to the conference call.",
        "Management Participants: Managing Director and CFO. Revenue grew 12% YoY.",
        "Question and Answer session continues with analyst commentary.",
        "Thank you for joining the earnings conference call today.",
    ])
    link_pdf = _write_pdf(raw / "FAIRCHEMOR" / "concall_audio_link" / "lnk1.pdf", [
        "Please find attached the link of audio recording of the Earnings Con-call at https://example.invalid/audio",
    ])
    manifest = _write_manifest(raw / "manifest.csv", [
        {"isin": "INE0DNW01011", "symbol_at_time": "FAIRCHEMOR", "newsid": "tx1", "bucket": "concall_audio_link",
         "category": "Company Update", "subcat": "Earnings Call Transcript",
         "headline": "Please find attached herewith Transcript of audio recording of Earnings Con-call",
         "dissem_ts": "2025-11-14T18:00:00", "local_path": str(tx_pdf), "status": "ok"},
        {"isin": "INE0DNW01011", "symbol_at_time": "FAIRCHEMOR", "newsid": "lnk1", "bucket": "concall_audio_link",
         "category": "Company Update", "subcat": "Audio Recording of Earnings Call",
         "headline": "Audio recording link of Earnings Con-call",
         "dissem_ts": "2025-11-13T18:00:00", "local_path": str(link_pdf), "status": "ok"},
    ])
    out = tmp_path / "pages.db"
    prof = profile.Profile(
        name="t223_test", pages_db=out, raw_root=raw, manifest=manifest, out=tmp_path / "pilot.db",
        companies=(profile.ProfileCompany(symbol="FAIRCHEMOR", name="Fairchem Organics Limited",
                                          isins=("INE0DNW01011",)),),
    )
    store = raw_store.RawStore(roots={"raw": raw}, manifest=tmp_path / "no_drive.db")
    counts = collect_manifest(prof, ("FAIRCHEMOR",), out, log=lambda *_: None, store=store)
    stat = counts["FAIRCHEMOR"]
    assert stat == {
        "rows": 2, "docs": 1, "pages": 4, "needs_ocr": 0, "undated": 0, "missing": 0,
        "errors": 0, "not_documents": 1, "dupes": 0, "redated": 0, "retyped": 0,
        "audio_link_transcripts": 1,
    }
    con = sqlite3.connect(out)
    try:
        docs = con.execute("SELECT doc_key, doc_type, pages, source_record FROM doc").fetchall()
        assert len(docs) == 1
        doc_key, doc_type, pages, source_record = docs[0]
        assert doc_key == "FAIRCHEMOR/concall_audio_link/tx1.pdf"
        assert doc_type == "transcript"
        assert pages == 4
        meta = json.loads(source_record)
        assert meta["type_source"] == "printed"
        assert meta["bucket"] == "concall_audio_link"
        assert con.execute("SELECT COUNT(*) FROM doc_page WHERE doc_key=?", (doc_key,)).fetchone()[0] == 4
        assert con.execute("SELECT COUNT(*) FROM doc_page").fetchone()[0] == 4
    finally:
        con.close()


def test_collect_manifest_audio_link_rejects_long_non_call_and_missing_file(tmp_path: Path):
    """T-223: a long non-call audio-link PDF and a missing-file row stay not_documents and write nothing."""
    pytest.importorskip("pymupdf")
    raw = tmp_path / "raw"
    non_call = _write_pdf(raw / "VIDHIING" / "concall_audio_link" / "long_other.pdf", [
        "Board Meeting Outcome: appointment of internal auditor and statutory compliance schedule.",
        "Annexure I: Brief profile of the auditor and terms of appointment.",
        "Annexure II: Declaration under SEBI listing regulations.",
        "Annexure III: Closing notes and signature of the Company Secretary.",
    ])
    tx_phrase = _write_pdf(raw / "VIDHIING" / "concall_audio_link" / "tx_phrase.pdf", [
        "VIDHIING Limited Earnings Conference Call Q2 FY26 held on November 13, 2025.",
        "Opening remarks by Managing Director on revenue and margin trajectory.",
        "Participant questions on capacity expansion and exports.",
    ])
    manifest = _write_manifest(raw / "manifest.csv", [
        {"isin": "INE632C01026", "symbol_at_time": "VIDHIING", "newsid": "long1", "bucket": "concall_audio_link",
         "dissem_ts": "2025-11-14T18:00:00", "local_path": str(non_call), "status": "ok"},
        {"isin": "INE632C01026", "symbol_at_time": "VIDHIING", "newsid": "missing1", "bucket": "concall_audio_link",
         "dissem_ts": "2025-11-14T18:00:00", "status": "ok"},
        {"isin": "INE632C01026", "symbol_at_time": "VIDHIING", "newsid": "tx2", "bucket": "concall_audio_link",
         "dissem_ts": "2025-11-15T18:00:00", "local_path": str(tx_phrase), "status": "ok"},
    ])
    out = tmp_path / "pages.db"
    prof = profile.Profile(
        name="t223_edge", pages_db=out, raw_root=raw, manifest=manifest, out=tmp_path / "pilot.db",
        companies=(profile.ProfileCompany(symbol="VIDHIING", isins=("INE632C01026",)),),
    )
    store = raw_store.RawStore(roots={"raw": raw}, manifest=tmp_path / "no_drive.db")
    stat = collect_manifest(prof, ("VIDHIING",), out, log=lambda *_: None, store=store)["VIDHIING"]
    assert stat == {
        "rows": 3, "docs": 1, "pages": 3, "needs_ocr": 0, "undated": 0, "missing": 0,
        "errors": 0, "not_documents": 2, "dupes": 0, "redated": 0, "retyped": 0,
        "audio_link_transcripts": 1,
    }
    con = sqlite3.connect(out)
    try:
        rows = con.execute("SELECT doc_key, doc_type FROM doc").fetchall()
        assert rows == [("VIDHIING/concall_audio_link/tx_phrase.pdf", "transcript")]
    finally:
        con.close()
