"""T-213 round 15: the five checks of ``answer/answer_checker.py`` on a tmp fixture store.

The fixture store carries a few real rows (Blue Star, BLUESTARCO) so every check is
exercised on the run-B cases that failed the blind grade: BS-031 look-ahead, BS-034
one call cited, BS-018 the analyst's figure, BS-008 the company-wide order book used
as the segment's, BS-026 "data not found" after three routes.

No model call, no network, no live store: the fixture is built in ``work``.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reality_engine.answer import answer_checker as ac  # noqa: E402

import pytest  # noqa: E402

TS = "D:/RealityEngine/raw/pilot60_history/BLUESTARCO/concall_transcript/"
AR = "D:/RealityEngine/raw/pilot60_history/BLUESTARCO/annual_report/"
DECK = "D:/RealityEngine/raw/pilot60_history/BLUESTARCO/investor_presentation/"
NEWS = "D:/RealityEngine/raw/pilot60_history/BLUESTARCO/material_filing/"
RESULTS = "D:/RealityEngine/raw/pilot60_history/BLUESTARCO/quarterly_results/"

Q2FY27 = TS + "89668a89-aed7-4023-9d85-36816f084e77.pdf"
Q1FY27 = TS + "3fadd68c-bf46-4a08-b275-5d948f15ae60.pdf"
Q4FY26 = TS + "4f991634-ac17-424b-ae16-ec67875b4485.pdf"
Q3FY26 = TS + "40f59c51-0bd8-4959-81fd-db799a7972bb.pdf"
Q2FY26 = TS + "6f6fd4a4-7156-451c-9032-c155c481eaf5.pdf"
FY26_AR = AR + "342c2bfa-31bc-4e47-ac71-c64a4eb588e7.pdf"
FY24_AR = AR + "53c9e103-10e0-49f2-b7ee-0487b1cfb188.pdf"
DECK_Q2 = DECK + "fa301402-5a44-4e1a-8a46-2ad0de9276a6.pdf"
INVESTOR_UPDATE = NEWS + "cfe71ba5-d702-4b62-8b89-96a01426f275.pdf"
RESULTS_Q2 = RESULTS + "a9fe8184-35e4-409d-b816-3c5d8cf5b0d5.pdf"
WJT = NEWS + "3ce837d9-aaba-45c3-a1d6-d36ba51fbd88.pdf"

DOCS = [
    # doc_key, doc_type, filing_date, known_at
    (Q2FY26, "transcript", "2025-11-12", "2025-11-12T16:00:00"),
    (Q3FY26, "transcript", "2026-02-04", "2026-02-04T17:00:00"),
    (Q4FY26, "transcript", "2026-05-12", "2026-05-12T18:00:00"),
    (FY26_AR, "annual_report", "2026-07-13", "2026-07-13T23:18:46"),
    (Q1FY27, "transcript", "2026-08-13", "2026-08-13T18:44:34"),
    (RESULTS_Q2, "results", "2026-10-29", "2026-10-29T16:13:56"),
    (DECK_Q2, "deck", "2026-10-30", "2026-10-30T16:52:07"),
    (INVESTOR_UPDATE, "announcement", "2026-10-30", "2026-10-30T18:03:42"),
    (Q2FY27, "transcript", "2026-11-05", "2026-11-05T16:40:50"),
    (FY24_AR, "annual_report", "2024-07-13", "2024-07-13T20:37:30"),
    (WJT, "announcement", "2024-10-02", "2024-10-02T11:18:26"),
]

CALLS = [
    (Q2FY26, "Q2FY26", "2025-11-12", "2025-11-12T16:00:00"),
    (Q3FY26, "Q3FY26", "2026-02-04", "2026-02-04T17:00:00"),
    (Q4FY26, "Q4FY26", "2026-05-12", "2026-05-12T18:00:00"),
    (Q1FY27, "Q1FY27", "2026-08-13", "2026-08-13T18:44:34"),
    (Q2FY27, "Q2FY27", "2026-11-05", "2026-11-05T16:40:50"),
]

PAGES = [
    # the Q2FY27 call, page 14: the write-back answer, management speaking
    (Q2FY27, 14, "Page 13 of 17\n Blue Star Limited \nOctober 30, 2026 \n\nNikhil Sohoni: \n"
     "During this quarter the company sold its MedTech business for total consideration of "
     "Rs. 35.6 cr. The provisions pertaining to the same have been written back.\n"),
    # page 15: the analyst's Rs 12-13 cr, the figure run B gave to management
    (Q2FY27, 15, "Page 14 of 17 \n Blue Star Limited \nOctober 30, 2026 \n\nUmang Mehta: \n"
     "In the cash flow statement there is a Rs. 77 cr provision write-back and I understand "
     "Rs. 12 cr - Rs. 13 cr pertains to the third segment.\n\nNikhil Sohoni: \n"
     "Certain warranties and incentives get written back in the normal course of business.\n"),
    # page 16: management on US heat pumps, a figure behind a management label
    (Q2FY27, 16, "Page 15 of 17 \n Blue Star Limited \nOctober 30, 2026 \n\nB. Thiagarajan: \n"
     "To the U.S. market we supply the heat pumps now in a limited way and it has the "
     "potential to bring in USD 100 million of additional revenue.\n"),
    (DECK_Q2, 10, "Financial highlights - Q2FY27\nRevenue from operations\n2,930.95 cr\n"
     "Carried-forward order book\n7,229.22 cr\n30 Sep 2026: 7,120.44 cr\n"),
    (INVESTOR_UPDATE, 4, "3 | P a g e\n\nCarried-forward order book of the Electro-Mechanical "
     "Projects business was at 5141.78 cr as on September 30, 2026, as compared to 4,840.46 cr "
     "as on September 30, 2025, a growth of 6.2%.\n"),
    (RESULTS_Q2, 9, "Provisions and liabilities written back (76.99) (18.48)\n"),
]

STATEMENTS = [
    # doc_key, call_date, call_period, page, speaker, role, quote, known_at
    (Q2FY27, "2026-11-05", "Q2FY27", 14, "Nikhil Sohoni", "mgmt",
     "During this quarter the company sold its MedTech business for total consideration of "
     "Rs. 35.6 cr.", "2026-11-05T16:40:50"),
    (Q2FY27, "2026-11-05", "Q2FY27", 15, "Nikhil Sohoni", "mgmt",
     "Certain warranties and incentives get written back in the normal course of business.",
     "2026-11-05T16:40:50"),
    (Q2FY27, "2026-11-05", "Q2FY27", 16, "B. Thiagarajan", "md",
     "To the U.S. market we supply the heat pumps now in a limited way and it has the potential "
     "to bring in USD 100 million of additional revenue.", "2026-11-05T16:40:50"),
    (Q1FY27, "2026-08-13", "Q1FY27", 5, "B. Thiagarajan", "md",
     "MEP order booking guidance for the year is 8% to 10%, possibly 12%.", "2026-08-13T18:44:34"),
    (Q4FY26, "2026-05-12", "Q4FY26", 5, "B. Thiagarajan", "md",
     "Electro-mechanical projects and commercial air conditioning should maintain growth "
     "momentum.", "2026-05-12T18:00:00"),
    (Q2FY26, "2025-11-12", "Q2FY26", 4, "B. Thiagarajan", "md",
     "We have been disciplined about the margins.", "2025-11-12T16:00:00"),
    (Q3FY26, "2026-02-04", "Q3FY26", 8, "B. Thiagarajan", "md",
     "The next year will be better.", "2026-02-04T17:00:00"),
]


@pytest.fixture()
def work():
    """A case directory under the repo's ``.tmp`` (pytest's ``tmp_path`` is sandbox-denied)."""
    path = REPO_ROOT / ".tmp" / "answer_checker_tests" / uuid.uuid4().hex[:10]
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def build_store(path: Path) -> Path:
    known = {row[0]: row[3] for row in DOCS}
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE doc (doc_key TEXT, doc_type TEXT, filing_date TEXT, known_at TEXT)")
    con.execute("CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT, known_at TEXT)")
    con.execute(
        "CREATE TABLE transcript_statement (id INTEGER PRIMARY KEY, doc_key TEXT, call_date TEXT, "
        "call_period TEXT, page INTEGER, seq INTEGER, speaker TEXT, role TEXT, quote TEXT, "
        "known_at TEXT)"
    )
    con.executemany("INSERT INTO doc VALUES (?,?,?,?)", DOCS)
    con.executemany("INSERT INTO doc_page VALUES (?,?,?,?)",
                    [(doc_key, page, text, known[doc_key]) for doc_key, page, text in PAGES])
    con.executemany(
        "INSERT INTO transcript_statement "
        "(doc_key, call_date, call_period, page, seq, speaker, role, quote, known_at) "
        "VALUES (?,?,?,?,0,?,?,?,?)",
        STATEMENTS,
    )
    con.commit()
    con.close()
    return path


def _answer(**kw: object) -> ac.Answer:
    base: dict[str, object] = dict(qid="BS-000", question="What was revenue in Q2FY27?", as_of="2026-11-11",
                text="Revenue was Rs 2,930.95 crore in Q2FY27.",
                sources=(ac.Source(RESULTS_Q2, "results", 7, "2026-10-29T16:13:56"),))
    base.update(kw)
    return ac.Answer(**cast("dict[str, Any]", base))


def _calls(qid: str, tools: list[str]) -> list[ac.Call]:
    return [ac.Call(qid, tool, {}) for tool in tools]


# ---------------------------------------------------------------- C1


def test_c1_look_ahead_names_the_late_annual_report(work):
    store = ac.Store(build_store(work / "s.db"))
    late = _answer(
        question="What did Blue Star disclose about the WJT dispute and how has it changed?",
        as_of="2024-11-30",
        text="The WJT claim was about Rs 223.60 crore; the FY26 AR says the arbitration is "
             "complete.",
        sources=(ac.Source(WJT, "announcement", 1, "2024-10-02T11:18:26"),),
    )
    check = ac.check_c1(late, store)
    assert not check.ok and "FY26 annual report" in check.fact and "2026-07-13" in check.fact

    fixed = _answer(
        question=late.question, as_of="2024-11-30",
        text="The WJT claim was about Rs 223.60 crore, treated as a contingent claim in the FY24 AR.",
        sources=late.sources,
    )
    assert ac.check_c1(fixed, store).ok


# ---------------------------------------------------------------- C2


def test_c2_change_across_calls_needs_every_named_call(work):
    store = ac.Store(build_store(work / "s.db"))
    question = ("How did the revenue growth guidance for the MEP business change across the "
                "Q4FY26, Q1FY27 and Q2FY27 calls?")
    one_call = _answer(
        question=question,
        text="At the Q1FY27 call management guided MEP growth of 8-10%.",
        sources=(ac.Source(Q1FY27, "transcript", 5, "2026-08-13T18:44:34"),),
    )
    check = ac.check_c2(one_call, store)
    assert not check.ok and "Q4FY26" in check.fact and "Q2FY27" in check.fact
    assert Q4FY26 in check.look and Q2FY27 in check.look

    all_calls = _answer(
        question=question,
        text=("At the Q4FY26 call management kept the qualitative line; at Q1FY27 it guided "
              "8-10% MEP growth; at Q2FY27 it repeated the absolute targets."),
        sources=(ac.Source(Q4FY26, "transcript", 5, "2026-05-12T18:00:00"),
                 ac.Source(Q1FY27, "transcript", 5, "2026-08-13T18:44:34"),
                 ac.Source(Q2FY27, "transcript", 11, "2026-11-05T16:40:50")),
    )
    assert ac.check_c2(all_calls, store).ok


def test_c2_ignores_a_figure_change_between_two_quarters(work):
    """A change between two printed quarters is not a calls-covered question."""
    store = ac.Store(build_store(work / "s.db"))
    answer = _answer(
        question="By how many basis points did the Unitary Products segment margin change in "
                 "Q2FY27 versus Q2FY26?",
        text="The margin fell 385 bps to 2.31%.",
        sources=(ac.Source(RESULTS_Q2, "results", 7, "2026-10-29T16:13:56"),),
    )
    assert ac.check_c2(answer, store).ok


# ---------------------------------------------------------------- C3


def test_c3_analysts_figure_is_not_managements(work):
    store = ac.Store(build_store(work / "s.db"))
    answer = _answer(
        question="What did management say the provision write-back relates to?",
        text="Management said Rs 12-13 crore of it pertains to Segment 3.",
        sources=(ac.Source(Q2FY27, "transcript", 14, "2026-11-05T16:40:50"),),
    )
    check = ac.check_c3(answer, store)
    assert not check.ok and "12-13 crore" in check.fact and "Umang Mehta" in check.fact

    fixed = _answer(
        question=answer.question,
        text="Management said the MedTech business was sold for Rs 35.6 crore and its "
             "provisions were written back.",
        sources=answer.sources,
    )
    assert ac.check_c3(fixed, store).ok


def test_c3_named_call_must_be_cited(work):
    store = ac.Store(build_store(work / "s.db"))
    answer = _answer(
        question="What did management say about pricing?",
        text="Management said only 13% of the 18% cost increase had been passed on by the "
             "Q2FY27 call.",
        sources=(ac.Source(Q2FY26, "transcript", 4, "2025-11-12T16:00:00"),),
    )
    check = ac.check_c3(answer, store)
    assert not check.ok and "Q2FY27" in check.fact


# ---------------------------------------------------------------- C4


SEGMENT_QUESTION = (
    "What was the carried-forward order book of the Electro-Mechanical Projects and Commercial "
    "Air Conditioning Systems business as at 30 Sep 2026, and what was it a year earlier?"
)


def test_c4_company_wide_order_book_is_not_the_segments(work):
    store = ac.Store(build_store(work / "s.db"))
    wrong = _answer(
        question=SEGMENT_QUESTION,
        text="The company's carried-forward order book was Rs 7,229.22 crore at 30 Sep 2026 "
             "versus Rs 7,120.44 crore a year earlier.",
        sources=(ac.Source(DECK_Q2, "deck", 10, "2026-10-30T16:52:07"),),
    )
    check = ac.check_c4(wrong, store)
    assert not check.ok
    assert "7229.22" in check.fact and "5,141.78" in check.fact
    assert INVESTOR_UPDATE in check.look

    fixed = _answer(
        question=SEGMENT_QUESTION,
        text="The Electro-Mechanical Projects and Commercial Air Conditioning Systems "
             "carried-forward order book was Rs 5,141.78 crore at 30 Sep 2026 versus "
             "Rs 4,840.46 crore a year earlier.",
        sources=(ac.Source(INVESTOR_UPDATE, "announcement", 4, "2026-10-30T18:03:42"),),
    )
    assert ac.check_c4(fixed, store).ok


def test_c4_segment_figure_without_a_scope_word(work):
    store = ac.Store(build_store(work / "s.db"))
    answer = _answer(
        question="What is the ratio of the Electro-Mechanical Projects order book at 30 Sep 2026 "
                 "to that segment's trailing twelve-month revenue?",
        text="Against the carried-forward order book of Rs 7,229.22 crore at 30 Sep 2026 the "
             "ratio is 1.0x.",
        sources=(ac.Source(DECK_Q2, "deck", 10, "2026-10-30T16:52:07"),),
    )
    check = ac.check_c4(answer, store)
    assert not check.ok and "7229.22" in check.fact


# ---------------------------------------------------------------- C5


def test_c5_not_found_needs_four_routes_and_a_page(work):
    store = ac.Store(build_store(work / "s.db"))
    answer = _answer(
        question="What has Blue Star stated about its PLI participation: approved investment, "
                 "investment made, and incentive accrued?",
        text="The store holds the incentive side but no approved-investment figure is disclosed "
             "— data not found for that part.",
        sources=(ac.Source(FY26_AR, "annual_report", 299, "2026-07-13T23:18:46"),),
    )
    thin = _calls(answer.qid, ["search", "statements", "topic", "page"])
    check = ac.check_c5(answer, thin, store)
    assert not check.ok and "four routes" in check.fact

    thick = _calls(answer.qid, ["search", "statements", "topic", "cells", "page"])
    assert ac.check_c5(answer, thick, store).ok


# ---------------------------------------------------------------- assembly + CLI


def test_followup_quotes_only_the_failed_facts():
    checks = [ac.Check("C1", True), ac.Check("C2", True),
              ac.Check("C3", False, "the figure is the analyst's", ("doc.pdf",)),
              ac.Check("C4", True), ac.Check("C5", True)]
    assert ac.followup_text(checks) == (
        "Check failed: C3 - the figure is the analyst's. Look again in doc.pdf."
    )
    assert ac.followup_text([ac.Check("C1", True)]) == ""


def test_cli_writes_one_line_per_answer(work):
    db = build_store(work / "s.db")
    answers_dir = work / "answers"
    answers_dir.mkdir()
    row = {
        "qid": "BS-018",
        "question": "What did management say the provision write-back relates to?",
        "as_of": "2026-11-11",
        "answer": "Management said Rs 12-13 crore of it pertains to Segment 3.",
        "sources": [{"doc_key": Q2FY27, "doc_type": "transcript", "page": 14,
                     "known_at": "2026-11-05T16:40:50"}],
    }
    (answers_dir / "answers.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    (answers_dir / "calls.jsonl").write_text(
        "\n".join(json.dumps({"qid": "BS-018", "tool": t, "args": "{}"})
                  for t in ("statements", "page")) + "\n",
        encoding="utf-8",
    )
    out = work / "check.jsonl"
    assert ac.main(["--db", str(db), "--answers", str(answers_dir), "--out", str(out)]) == 0
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1 and lines[0]["qid"] == "BS-018"
    assert [c["id"] for c in lines[0]["checks"]] == ["C1", "C2", "C3", "C4", "C5"]
    assert lines[0]["followup"].startswith("Check failed: C3 - ")
