"""T-161/T-159: a document's own first pages correct the record's type and date (pure text, no store, no PDF).

Each date case is one of the six misdated q12 transcripts (Opus held audit, 10 Nov 2026): a company-website
crawl stored a 2016-2018 call under its August 2026 crawl date.  ``reconcile_doc`` takes the printed call date.
"""
from __future__ import annotations

import pytest

from reality_engine.pilot3.call_dates import call_date
from reality_engine.pilot3.docs_collect import reconcile_doc

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
