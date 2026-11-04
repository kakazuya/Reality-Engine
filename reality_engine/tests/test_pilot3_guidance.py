"""Tests for the rule-based guidance extractor (``reality_engine/pilot3/guidance.py``, T-049).

Run from the repo root:
    python -m pytest reality_engine/tests/test_pilot3_guidance.py -q

The fixture tests build a tiny pilot3 database (doc / doc_page / transcript_statement) and check the rules: range
and pair parsing, metric and period attribution, the "did it change" chain, the cues that keep a target and the
filters that keep a past measurement out.  ``test_real_database_finds_the_ticket_targets`` copies the real
``pilot3.db`` to ``.tmp/`` (the live file is never written) and asserts the twelve targets the T-049 ticket lists;
it skips, with the path in the reason, when that database is absent.
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

import reality_engine.pilot3.guidance as guidance
from reality_engine.pilot3 import REAL_DB, schema
from reality_engine.pilot3.transcripts import SCHEMA as TRANSCRIPT_SCHEMA

ROOT = Path(__file__).resolve().parents[2]
TMP = ROOT / ".tmp"


def build_fixture(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    con = sqlite3.connect(path)
    con.execute(schema.TABLES["doc"])
    con.execute(schema.TABLES["doc_page"])
    con.executescript(TRANSCRIPT_SCHEMA)
    docs = [
        # KEC FY25 call: the FY26 margin target is first given here
        ("kec/call_q4fy25.pdf", "KEC", "transcript", "Conference Call Q4 FY25", "2025-05-27",
         "2025-05-29T16:00:00"),
        # KEC FY26 results deck (later than the Q3 call): the FY26 margin target is restated
        ("kec/deck_fy26.pdf", "KEC", "deck", "Q4 FY26 deck", "2026-04-29", "2026-04-29T17:00:00"),
        # KEC Q3 FY26 call: the FY26 margin target is cut to 7-7.5%
        ("kec/call_q3fy26.pdf", "KEC", "transcript", "Conference Call Q3 FY26", "2026-01-30",
         "2026-01-30T16:00:00"),
        # KEC Q4 FY26 call: says the next year's revenue and order-intake targets
        ("kec/call_q4fy26.pdf", "KEC", "transcript", "Conference Call Q4 FY26", "2026-05-21",
         "2026-05-21T16:00:00"),
        # KEC Q1 FY27 call: the capex and interest-cost answers
        ("kec/call_q1fy27.pdf", "KEC", "transcript", "Conference Call Q1 FY27", "2026-08-11",
         "2026-08-14T15:30:00"),
        # a page whose only sentence is a past measurement
        ("kec/old_results.pdf", "KEC", "results", "Results Q2 FY25", "2024-10-30", "2024-10-30T17:00:00"),
    ]
    con.executemany("INSERT INTO doc(doc_key,symbol,isin,doc_type,doc_family,title,filing_date,known_at,pages) "
                    "VALUES (?,?,NULL,?,?,?,?,?,1)", [(d[0], d[1], d[2], d[2], d[3], d[4], d[5]) for d in docs])
    pages = [
        ("kec/call_q4fy25.pdf", 1, "On the margin, we have been talking about 8% to 8.5% for the year."),
        ("kec/deck_fy26.pdf", 1, "We expect EBITDA margin of 8% to 8.5% for FY26."),
        ("kec/call_q3fy26.pdf", 1, "We have cut our margin guidance for the year to 7% to 7.5%."),
        ("kec/call_q4fy26.pdf", 1, "So we expect revenue growth of 12% to 15% for FY27."),
        ("kec/call_q4fy26.pdf", 2, "As far as order intake is concerned, we expect around INR30,000 crores for the year."),
        ("kec/call_q1fy27.pdf", 2, "What is your capex guidance? We expect about Rs 1,000 crores this year."),
        ("kec/call_q1fy27.pdf", 3, "What about interest cost? There should be a reduction of maybe "
                                   "INR20 crores, INR25 crores per quarter."),
        # the metric's word is in the question only, and the answer's own subject is net debt (4 Nov 2026 review)
        ("kec/call_q1fy27.pdf", 4, "What about the interest cost this year? Our net debt as on 31 March 2026 stands "
                                   "at Rs 1,000 crores, which is within our targeted average borrowing levels of "
                                   "Rs 1,200 crores for the year."),
        # a share of supply, with "margin" only in the question (4 Nov 2026 review)
        ("kec/call_q1fy27.pdf", 5, "What is the margin outlook? We expect 60% of our supply to come from "
                                   "captive mines next year."),
        ("kec/old_results.pdf", 1, "The order book was at INR 40,000 crores last year."),
        ("kec/old_results.pdf", 2, "Inflation is expected to rise from 2% to 5% in FY27."),
    ]
    con.executemany("INSERT INTO doc_page(doc_key,symbol,page,text,method,chars,known_at) VALUES (?,?,?,?,?,?,NULL)",
                    [(d, "KEC", p, t, "script_text", len(t)) for d, p, t in pages])
    statements = [
        ("kec/call_q4fy25.pdf", "Q4FY25", 1, 1, "Vimal Kejriwal", "ceo",
         "On the margin, we have been talking about 8% to 8.5% for the year."),
        ("kec/call_q3fy26.pdf", "Q3FY26", 1, 1, "Vimal Kejriwal", "ceo",
         "We have cut our margin guidance for the year to 7% to 7.5%."),
        ("kec/call_q4fy26.pdf", "Q4FY26", 1, 1, "Vimal Kejriwal", "ceo",
         "So we expect revenue growth of 12% to 15% for FY27."),
        ("kec/call_q4fy26.pdf", "Q4FY26", 2, 2, "Vimal Kejriwal", "ceo",
         "As far as order intake is concerned, we expect around INR30,000 crores for the year."),
        ("kec/call_q1fy27.pdf", "Q1FY27", 2, 2, "Anup Saha", "cfo",
         "We expect about Rs 1,000 crores this year."),
        ("kec/call_q1fy27.pdf", "Q1FY27", 3, 3, "Anup Saha", "cfo",
         "There should be a reduction of maybe INR20 crores, INR25 crores per quarter."),
    ]
    con.executemany(
        "INSERT INTO transcript_statement(symbol,doc_key,call_date,call_period,page,seq,speaker,role,section,topics,"
        "period_discussed,period_source,numbers_json,statement,quote,is_fragment,known_at,known_at_source,"
        "extractor_rule) VALUES ('KEC',?,?,?,?,?,?,?,'prepared','margin','','call','[]',?,?,0,'x','x','t')",
        [(dk, None, cp, pg, seq, spk, role, stmt, stmt) for dk, cp, pg, seq, spk, role, stmt in statements])
    con.commit()
    con.close()


@pytest.fixture(scope="module")
def fixture_db() -> Path:
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_fixture.db"
    build_fixture(path)
    assert guidance.run(str(path), ["KEC"])["rows"]["KEC"] > 0
    return path


def rows(db: Path, where: str = "1", args: tuple = ()) -> list[sqlite3.Row]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(f"SELECT *, rowid FROM guidance WHERE {where} ORDER BY said_on, id", args).fetchall()
    finally:
        con.close()


def test_ranges_and_pairs_are_read_with_their_units():
    assert [(n["low"], n["high"], n["unit"]) for n in guidance.numbers("12% to 15%")] == [(12.0, 15.0, "pct")]
    assert [(n["low"], n["high"], n["unit"]) for n in guidance.numbers("8-8.5%")] == [(8.0, 8.5, "pct")]
    assert [(n["low"], n["high"], n["unit"]) for n in guidance.numbers("145 to 160 bps")] == [(145.0, 160.0, "bps")]
    assert [(n["low"], n["high"], n["unit"]) for n in guidance.numbers("maybe INR20 crores, INR25 crores")] == \
        [(20.0, 25.0, "inr_cr")]
    assert [(n["low"], n["high"], n["unit"]) for n in guidance.numbers("$250 a ton")] == [(250.0, 250.0, "usd_per_t")]


def test_period_rules():
    # a Q4 call's unlabelled "for the year" is the year ahead, a Q3 call's is its own year
    assert guidance.target_period("we expect 12% to 15% for the year", "", "", "Q4FY26", (26, "Q4")) == "FY27"
    assert guidance.target_period("we expect 7% to 7.5% for the year", "", "", "Q3FY26", (26, "Q3")) == "FY26"
    # an explicit label always wins, and a bare quarter is the next one after the call ("Q1" in a Q4 call)
    assert guidance.target_period("we expect 8% for FY26", "", "", "Q1FY27", (27, "Q1")) == "FY26"
    assert guidance.target_period("we see about 5% in Q1", "", "", "Q4FY26", (26, "Q4"), 30) == "Q1FY27"
    # "Q2 to Q1" names Q2 as the target, "versus Q4" is a comparison base
    assert guidance.target_period("cost up 5%, 6% Q2 to Q1", "", "", "Q1FY27", (27, "Q1"), 12) == "Q2FY27"
    assert guidance.target_period("we see about 5% in Q1 versus Q4", "", "", "Q4FY26", (26, "Q4"), 20) == "Q1FY27"


def test_reported_actuals_and_rates_are_not_targets():
    """T-049, 4 Nov 2026: a reported quarter's cost and a tariff rate fail the guidance filters."""
    for sentence in ("Adjusted EBITDA down 9% YoY to $1,645 million",
                     "adjusted EBITDA was impacted by an estimated negative $54 million",
                     "adjusted EBITDA per ton came in at $506"):
        assert guidance.PAST_ONLY.search(sentence), sentence
    assert guidance.RATE_OF.search("especially with the 232 aluminium tariffs at 50%")
    assert not guidance.RATE_OF.search("we expect an EBITDA margin of 12%")


def test_fixture_rows_carry_metric_period_unit_and_quote(fixture_db):
    got = {(r["metric"], r["target_period"], r["low"], r["high"], r["unit"]): r for r in rows(fixture_db)}
    assert ("revenue_growth", "FY27", 12.0, 15.0, "pct") in got
    assert ("ebitda_margin", "FY26", 8.0, 8.5, "pct") in got
    assert ("ebitda_margin", "FY26", 7.0, 7.5, "pct") in got
    assert ("order_intake", "FY27", 30000.0, 30000.0, "inr_cr") in got
    assert ("capex", "FY27", 1000.0, 1000.0, "inr_cr") in got
    assert ("interest_cost", "FY27", 20.0, 25.0, "inr_cr") in got
    margin = got[("ebitda_margin", "FY26", 7.0, 7.5, "pct")]
    assert margin["direction"] == "down" and margin["speaker"] == "Vimal Kejriwal"
    for row in rows(fixture_db):
        assert row["said_on"] and row["doc_key"] and row["page"] and row["quote"]
        assert row["known_at_source"] == "doc.known_at"


def test_past_measurements_and_macro_forecasts_are_not_targets(fixture_db):
    quotes = " ".join(r["quote"] for r in rows(fixture_db))
    assert "order book was at" not in quotes        # a past measurement
    assert "Inflation" not in quotes                # a macro forecast
    assert not rows(fixture_db, "metric='other'")   # nothing without a metric's own forward cue


def test_the_metric_must_be_the_targets_subject(fixture_db):
    """4 Nov 2026 review: a net-debt sentence was stored as an interest-cost target and a share of supply as a
    margin target, both because the metric came from the question and any plausible number from the answer."""
    quotes = [r["quote"] for r in rows(fixture_db)]
    assert not any("net debt" in q.lower() for q in quotes)          # the interest-cost question did not make it one
    assert not any("of our supply" in q.lower() for q in quotes)     # a share of supply is not a margin
    assert not [r for r in rows(fixture_db) if r["low"] == 60.0 and r["metric"] == "ebitda_margin"]
    # the real interest-cost answer to "what about interest cost?" is still read
    assert [r for r in rows(fixture_db) if r["metric"] == "interest_cost" and (r["low"], r["high"]) == (20.0, 25.0)]


def test_a_share_of_a_total_is_not_a_level():
    """The share rule on its own: a percentage of supply, turnover or cost is never a margin or a rate."""
    sentence = "We expect 60% of our supply to come from captive mines next year."
    nums = guidance.numbers(sentence)
    assert nums and nums[0]["low"] == 60.0
    assert guidance.subject_ok("ebitda_margin", sentence, nums[0], "What is the margin outlook?") is False
    share = "Our market share should be 25% of the market next year."
    assert guidance.subject_ok("other", share, guidance.numbers(share)[0], "") is True
    ok = "We expect EBITDA margin of 8% to 8.5% for FY26."
    chosen = guidance.numbers(ok)[0]
    assert guidance.subject_ok("ebitda_margin", ok, chosen, "") is True


def test_revision_chain_links_the_cut(fixture_db):
    con = sqlite3.connect(f"file:{fixture_db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        latest = con.execute("SELECT * FROM guidance WHERE metric='ebitda_margin' AND low=7 AND high=7.5").fetchone()
        previous = con.execute("SELECT * FROM guidance WHERE id=?", (latest["revision_of"],)).fetchone()
    finally:
        con.close()
    assert previous is not None
    assert (previous["low"], previous["high"], previous["said_on"]) == (8.0, 8.5, "2025-05-27")
    assert latest["said_on"] == "2026-01-30"


def test_quote_is_on_the_page(fixture_db):
    con = sqlite3.connect(f"file:{fixture_db}?mode=ro", uri=True)
    try:
        for r in rows(fixture_db):
            text = con.execute("SELECT text FROM doc_page WHERE doc_key=? AND page=?", (r["doc_key"], r["page"])).fetchone()
            assert text, r["doc_key"]
            assert " ".join(r["quote"].split()) in " ".join(text[0].split())
    finally:
        con.close()


def test_queries_shapes_and_point_in_time(fixture_db):
    from reality_engine.pilot3 import queries

    con = sqlite3.connect(f"file:{fixture_db}?mode=ro", uri=True)
    try:
        all_rows = queries.guidance_rows(con, "KEC")
        early = queries.guidance_rows(con, "KEC", as_of="2026-03-01")
        margins = queries.guidance_rows(con, "KEC", metric="margin", period="FY26")
        assert len(early) < len(all_rows)
        assert all(r["said_on"] <= "2026-03-01" for r in early)
        assert {r["metric"] for r in margins} == {"ebitda_margin"}
        assert {r["target_period"] for r in margins} == {"FY26"}
    finally:
        con.close()


# --- the twelve targets the ticket lists, on a copy of the real database -----------------------------
TICKET_TARGETS = [
    ("KEC FY27 revenue growth 12-15%",
     "symbol='KEC' AND metric='revenue_growth' AND target_period='FY27' AND low=12 AND high=15"),
    ("KEC FY26 EBITDA margin 8-8.5%",
     "symbol='KEC' AND metric='ebitda_margin' AND target_period='FY26' AND low=8 AND high=8.5"),
    ("KEC FY26 EBITDA margin cut to 7-7.5%",
     "symbol='KEC' AND metric='ebitda_margin' AND target_period='FY26' AND low=7 AND high=7.5"),
    ("KEC ~50% of orders price-variable",
     "symbol='KEC' AND metric='other' AND low=50 AND quote LIKE '%fixed%'"),
    ("KEC INR20-25 crore interest cut per quarter",
     "symbol='KEC' AND metric='interest_cost' AND low=20 AND high=25 AND unit='inr_cr'"),
    ("KEC order-intake target INR30,000 crore",
     "symbol='KEC' AND metric='order_intake' AND low=30000 AND high=30000"),
    ("BAJFINANCE NIM moderation 10-15 bps FY27",
     "symbol='BAJFINANCE' AND metric='nim' AND target_period='FY27' AND low=10 AND high=15 AND unit='bps'"),
    ("BAJFINANCE credit cost 1.45-1.60% FY27",
     "symbol='BAJFINANCE' AND metric='credit_cost' AND target_period='FY27' AND low=1.45 AND high=1.6"),
    ("BAJFINANCE AUM growth 22-24% FY27",
     "symbol='BAJFINANCE' AND metric='aum_growth' AND target_period='FY27' AND low=22 AND high=24"),
    ("HINDALCO India aluminium cost +5% Q1FY27",
     "symbol='HINDALCO' AND metric='cost_of_production' AND target_period='Q1FY27' AND low=5 AND high=5"),
    ("HINDALCO cash cost +5-6% Q2FY27",
     "symbol='HINDALCO' AND metric='cost_of_production' AND target_period='Q2FY27' AND low=5 AND high=6"),
    ("HINDALCO India downstream EBITDA $250/t FY27",
     "symbol='HINDALCO' AND metric='ebitda_per_tonne' AND target_period='FY27' AND low=250 AND high=250"),
]


@pytest.mark.skipif(not REAL_DB.is_file(), reason=f"pilot3 database not built at {REAL_DB}")
def test_real_database_finds_the_ticket_targets():
    TMP.mkdir(exist_ok=True)
    copy = TMP / "guidance_acceptance.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(copy) + suffix).unlink(missing_ok=True)
    for suffix in ("", "-wal", "-shm"):
        src = Path(str(REAL_DB) + suffix)
        if src.is_file():
            shutil.copyfile(src, str(copy) + suffix)
    stats = guidance.run(str(copy), ["KEC", "BAJFINANCE", "HINDALCO"])
    assert set(stats["rows"]) == {"KEC", "BAJFINANCE", "HINDALCO"}
    con = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    try:
        missing = [name for name, where in TICKET_TARGETS
                   if not con.execute(f"SELECT 1 FROM guidance WHERE {where}").fetchone()]
        # T-049, 4 Nov 2026: a reported quarter's cost ("down 9% YoY", "impacted by ... $54 million") and a
        # tariff RATE ("232 aluminium tariffs at 50%") were stored as forward targets
        wrong = con.execute(
            "SELECT COUNT(*) FROM guidance WHERE symbol='HINDALCO' AND ("
            "(metric='ebitda_margin' AND low=50 AND high=50 AND quote LIKE '%tariff%') OR "
            "(metric='revenue_growth' AND quote LIKE '%Adjusted EBITDA down%'))").fetchone()[0]
    finally:
        con.close()
    assert not missing, f"not extracted: {missing}"
    assert wrong == 0, f"{wrong} reported actual(s) still stored as guidance"


# --- T-056: period and target-precision rules -------------------------------------------------------------
def test_next_and_coming_year_move_one_year_forward():
    assert guidance.target_period("we expect about INR11,000 crores next year", "", "", "Q2FY26", (26, "Q2")) == "FY27"
    assert guidance.target_period("in the coming financial year we expect 8% growth", "", "", "Q2FY27",
                                  (27, "Q2")) == "FY28"
    assert guidance.target_period("this year we expect 12% growth", "", "", "Q2FY26", (26, "Q2")) == "FY26"
    # a Q4 call's "this year" is already the year ahead, so "next year" is the one after it
    assert guidance.target_period("next year will be INR15,000 crores", "", "", "Q4FY26", (26, "Q4")) == "FY28"


def test_a_backward_looking_quarter_is_not_the_target_period():
    sentence = ("With our Q1 results and a view for the rest of the financial year, we are changing our revenue "
                "growth guidance to 1.5% to 3%")
    assert guidance.target_period(sentence, "", "", "Q1FY27", (27, "Q1"),
                                  guidance.numbers(sentence)[0]["start"]) == "FY27"
    sentence = "Based on our Q2 performance and revised outlook, our guidance is 1% to 2%"
    assert guidance.target_period(sentence, "", "", "Q2FY27", (27, "Q2"),
                                  guidance.numbers(sentence)[0]["start"]) == "FY27"
    # the sentence's own FY26 is nearer the number than the quarter heading printed far away
    sentence = ("FY26 capital expenditures expected to be in a range of $1.9 billion to $2.2 billion Adjusted free "
                "cash flow Novelis Q3FY26 Earnings")
    assert guidance.target_period(sentence, "", "", None, (26, "Q3"),
                                  guidance.numbers(sentence)[0]["start"]) == "FY26"


def test_a_reported_actual_against_the_guided_range_is_not_a_target():
    for sentence in ("EBITDA Margin at 22.6% was within the guided range.",
                     "EBITDA margin of 23.3% remains within our guided range, excluding Ice Cream.",
                     "We are now on a nine-month basis at 21% margin, which is midpoint of the guidance we have given."):
        assert guidance.GUIDED_ACTUAL.search(sentence), sentence
    assert guidance.REPORT_BASIS.search("reducing from 1.75% to 1.65%, this is really how we will report")
    assert not guidance.GUIDED_ACTUAL.search(
        "we expect the mid-term margin guidance to remain around our current guided range of 22.5% to 23.5%")


def test_the_other_metric_needs_its_guidance_word_in_the_same_clause():
    l1 = ("With a large order book and L1 position of over INR10,000 crores, gradual improvement in labour and "
          "expected collections, we expect the business to deliver growth")
    assert not guidance.other_cued(l1, guidance.numbers(l1)[0])
    debt = "Gross debtors would be around INR800 crores, INR900 crores."
    assert not guidance.other_cued(debt, guidance.numbers(debt)[0])
    target = "I am targeting that next year we should be delivering INR100,000 crores volume"
    assert guidance.other_cued(target, guidance.numbers(target)[0])
    fixed = "Fixed versus variable would be roughly 50%, okay?"
    assert guidance.other_cued(fixed, guidance.numbers(fixed)[0])


def test_a_segment_number_is_not_the_company_metric():
    cables = "Cables, I don't have the exact number, it could be higher single digit, maybe 6% or something."
    assert guidance.segment_subject(cables, guidance.numbers(cables)[0], "KEC")
    india = ("In FY27, the India capex will be about INR12,000 crores, and the Novelis capex will be between "
             "2.3 billion to 2.4 billion")
    assert not guidance.segment_subject(india, guidance.numbers(india)[0], "HINDALCO")


def test_the_number_after_the_cue_is_not_a_comparison_base():
    sentence = ("around INR8,000 crores or so is the order intake target for Civil, against INR5,000 crores, "
                "which we got this year and INR2,500 crores last year.")
    picked = guidance.pick_number(sentence, guidance.numbers(sentence))
    assert picked is not None and picked["low"] == 8000


def test_the_running_header_is_not_part_of_the_sentence():
    assert guidance.HEADER_TAIL.sub("", "KEC International Limited August 11, 2026 Page 14 of 23 As far as order") \
        == "As far as order"


def test_one_row_per_metric_period_value_and_date():
    """T-056 family I: the BSE/NSE copies and the several pages of a document collapse; a later restatement stays."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_duplicate.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    con = sqlite3.connect(path)
    con.execute(schema.TABLES["doc"])
    con.execute(schema.TABLES["doc_page"])
    con.executescript(TRANSCRIPT_SCHEMA)
    docs = [("kec/bse.pdf", "2026-05-21", "2026-05-21T16:00:00"), ("kec/nse.pdf", "2026-05-21", "2026-05-21T16:00:00"),
            ("kec/call.pdf", "2026-08-14", "2026-08-14T15:30:00")]
    con.executemany("INSERT INTO doc(doc_key,symbol,isin,doc_type,doc_family,title,filing_date,known_at,pages) "
                    "VALUES (?,'KEC',NULL,'deck','deck','Q4 FY26 deck',?,?,1)", docs)
    for doc_key, _d, _k in docs:
        con.execute("INSERT INTO doc_page(doc_key,symbol,page,text,method,chars,known_at) "
                    "VALUES (?,'KEC',1,'We expect revenue growth of 12% to 15% for FY27.','script_text',48,NULL)",
                    (doc_key,))
    con.commit()
    con.close()
    stats = guidance.run(str(path), ["KEC"])
    assert stats["rows"]["KEC"] == 2, "the same target on the same date must be one row, a restatement another"
    got = rows(path)
    assert [r["said_on"] for r in got] == ["2026-05-21", "2026-08-14"]
    assert got[0]["revision_of"] is None and got[1]["revision_of"] == got[0]["id"]
