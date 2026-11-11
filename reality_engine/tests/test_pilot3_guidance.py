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


# --- T-056 review, 4 Nov 2026: the spend beside the total, and the eight leftovers -------------------------
def write_db(path: Path, docs: list[tuple], pages: list[tuple]) -> None:
    """docs: (doc_key, symbol, doc_type, filing_date, known_at); pages: (doc_key, symbol, page, text)."""
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    con = sqlite3.connect(path)
    con.execute(schema.TABLES["doc"])
    con.execute(schema.TABLES["doc_page"])
    con.executescript(TRANSCRIPT_SCHEMA)
    con.executemany("INSERT INTO doc(doc_key,symbol,isin,doc_type,doc_family,title,filing_date,known_at,pages) "
                    "VALUES (?,?,NULL,?,?,'Deck',?,?,1)", [(d[0], d[1], d[2], d[2], d[3], d[4]) for d in docs])
    con.executemany("INSERT INTO doc_page(doc_key,symbol,page,text,method,chars,known_at) "
                    "VALUES (?,?,?,?,'script_text',?,NULL)",
                    [(d, s, p, t, len(t)) for d, s, p, t in pages])
    con.commit()
    con.close()


def test_a_project_spend_is_its_own_row_beside_the_total():
    """T-056 family D, restored 4 Nov 2026: the spend to date is a fact an investor asks for, with the period the
    sentence names, and it is never ``capex`` so no annual capex answer can pick it up."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_spend.db"
    write_db(path,
             [("hind/deck_may.pdf", "HINDALCO", "deck", "2026-05-19", "2026-05-19T17:00:00"),
              ("hind/deck_aug.pdf", "HINDALCO", "deck", "2026-08-05", "2026-08-05T17:00:00")],
             [("hind/deck_may.pdf", "HINDALCO", 26,
               "Estimated total capital cost remains in the order of $5 billion – $3.2 billion capital "
               "expenditures spent through end of FY26"),
              ("hind/deck_aug.pdf", "HINDALCO", 24,
               "Estimated total capital cost remains in the order of $5 billion – $3.8 billion capital "
               "expenditures spent through end of Q1FY27")])
    guidance.run(str(path), ["HINDALCO"])
    got = {(r["metric"], r["target_period"], r["low"], r["high"], r["unit"]) for r in rows(path)}
    assert ("project_capital_spent", "FY26", 3.2, 3.2, "usd_bn") in got
    assert ("project_capital_spent", "Q1FY27", 3.8, 3.8, "usd_bn") in got
    assert ("project_capital_cost", "FY26", 5.0, 5.0, "usd_bn") in got    # the total is still its own metric
    assert not [r for r in rows(path) if r["metric"] == "capex"], "a project spend is not one year's capex"
    for row in rows(path, "metric='project_capital_spent'"):
        assert row["quote"] and row["said_on"] and row["page"]


def test_the_review_leftovers_are_not_targets():
    """The eight quotes the controller's second hand read found wrong: each one's rule keeps it out."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_leftovers.db"
    docs = [("infy/call.pdf", "INFY", "deck", "2026-04-27", "2026-04-27T20:35:44"),
            ("kec/call.pdf", "KEC", "deck", "2026-08-11", "2026-08-14T15:30:00"),
            ("hind/call.pdf", "HINDALCO", "deck", "2026-02-12", "2026-02-12T17:00:00"),
            ("sun/call.pdf", "SUNPHARMA", "deck", "2026-10-28", "2026-10-28T17:41:16")]
    pages = [
        ("infy/call.pdf", "INFY", 1, "The impact of Optimum Healthcare, Stratus and Versent on operating margin "
                                    "will be approximately 0.7% on a full year annualized basis post closure."),
        ("kec/call.pdf", "KEC", 1, "So typically, we have been spending around INR250 crores, INR300 crores of "
                                  "capex."),
        ("kec/call.pdf", "KEC", 2, "What is the capex for FY26? But largely in Orissa, I think, INR1,000 crores in "
                                  "Orissa and INR600 crores would be in MP."),
        ("kec/call.pdf", "KEC", 3, "Now, whether the quantum will be 25 basis points or 50 basis points, difficult "
                                  "to quantify, which is why we are holding back."),
        ("hind/call.pdf", "HINDALCO", 1, "Underlying Adjusted EBITDA per tonne remains at ~$500/t excluding impacts "
                                        "of tariffs and Oswego fires incident Oswego Hotmill to restart in late Q1 "
                                        "FY27 By 2030 Guidance and Updates"),
        ("sun/call.pdf", "SUNPHARMA", 1, "China: Scaled platform, with multiple opportunities to accelerate presence "
                                        "China is a large, growing market with strong innovation pipeline Organon "
                                        "provides at scale platform for expansion $800 Mn+ revenue 8 large brands "
                                        "Potential to drive further growth $150 Bn+ market in 2025 5-7%+ expected "
                                        "growth over coming year 2000+ innovative products in development"),
        ("sun/call.pdf", "SUNPHARMA", 2, "As all of you know we are focusing on innovation today, Sun Pharma's 20% "
                                        "of the sales comes from innovation, but with the addition of both Organon "
                                        "and Sun, the total revenue would be 27% of a combined business."),
    ]
    write_db(path, docs, pages)
    guidance.run(str(path), ["INFY", "KEC", "HINDALCO", "SUNPHARMA"])
    quotes = " ".join(r["quote"] for r in rows(path))
    for needle in ("impact of Optimum", "have been spending", "in Orissa", "difficult to quantify",
                   "remains at ~$500", "China is a large", "of a combined business"):
        assert needle not in quotes, f"still a target: {needle}"
    assert not rows(path), [r["quote"] for r in rows(path)]
    # each rule on its own
    assert guidance.IMPACT_OF_ON.search("the impact of X and Y on operating margin will be 0.7%")
    assert guidance.HEDGE.search("whether it will be 25 or 50 basis points, difficult to quantify")
    assert guidance.PAST_ONLY.search("we have been spending around INR250 crores")
    assert not guidance.PAST_ONLY.search("we have been talking about 8% to 8.5% for the year")
    place = ("But largely in Orissa, I think, INR1,000 crores in Orissa and INR600 crores would be in MP.")
    picked = guidance.pick_number(place, guidance.numbers(place))
    assert picked is not None and picked["low"] == 600
    assert guidance.subject_ok("capex", place, picked, "What is the capex for FY26?") is False
    market = "China is a large, growing market and 5-7% growth is expected over the coming year"
    pct = [n for n in guidance.numbers(market) if n["unit"] == "pct"][0]
    assert guidance.subject_ok("revenue_growth", market, pct, "") is False
    share = "the total revenue would be 27% of a combined business"
    chosen = guidance.pick_number(share, guidance.numbers(share))
    assert chosen is not None and chosen["low"] == 27
    assert guidance.subject_ok("revenue_growth", share, chosen, "") is False
    ok = "We expect revenue growth of 12% to 15% for FY27."
    assert guidance.subject_ok("revenue_growth", ok, guidance.numbers(ok)[0], "") is True


def test_a_restated_estimate_that_still_remains_is_a_target():
    """The counter-case to ``remains at``: a guidance word before the number keeps the row (a hand read found this
    one true on BAJFINANCE's Q1 FY27 call)."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_remains.db"
    write_db(path, [("baj/call.pdf", "BAJFINANCE", "deck", "2026-07-23", "2026-07-23T17:00:00")],
             [("baj/call.pdf", "BAJFINANCE", 6,
               "The AUM growth estimates of AUM remain at 24 to 25% aided by new lines")])
    guidance.run(str(path), ["BAJFINANCE"])
    got = [(r["metric"], r["low"], r["high"], r["unit"]) for r in rows(path)]
    assert ("aum_growth", 24.0, 25.0, "pct") in got, got


# --- T-058, 4 Nov 2026: targets said in words, and the metric the sentence does not name -------------------
def test_a_worded_target_is_a_row_without_an_invented_number():
    """SUNPHARMA: "we expect high single-digit … top line growth for FY27".  ``low``/``high`` stay NULL -- the
    direction and the exact quote carry the magnitude, so "high single-digit" is never turned into 7%."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_worded.db"
    write_db(path, [("sun/call.pdf", "SUNPHARMA", "deck", "2026-05-29", "2026-05-29T20:08:05")],
             [("sun/call.pdf", "SUNPHARMA", 6,
               "On the guidance, we expect high single-digit consolidated top line growth for FY27 based on our "
               "current understanding of the regulatory and macro environment.")])
    guidance.run(str(path), ["SUNPHARMA"])
    got = [(r["metric"], r["target_period"], r["low"], r["high"], r["unit"], r["direction"]) for r in rows(path)]
    assert got == [("revenue_growth", "FY27", None, None, "pct", "up")], got
    assert rows(path)[0]["quote"].startswith("On the guidance, we expect high single-digit")


def test_the_worded_families_and_the_three_sentences_that_must_stay_out():
    """The "70s" bucket, the flattish direction and "will get to" as a cue are targets; a result quoted against the
    guided range, a past exceptional item and a board appointment are not."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_worded2.db"
    docs = [("hdfc/call.pdf", "HDFCBANK", "deck", "2026-07-24", "2026-07-24T15:52:36"),
            ("eternal/call.pdf", "ETERNAL", "deck", "2026-10-27", "2026-10-27T13:57:28"),
            ("eternal/call2.pdf", "ETERNAL", "deck", "2026-05-06", "2026-05-06T13:57:28"),
            ("hul/call.pdf", "HINDUNILVR", "deck", "2026-05-07", "2026-05-07T17:00:00"),
            ("sun/call.pdf", "SUNPHARMA", "deck", "2026-08-06", "2026-08-06T17:00:00")]
    pages = [
        ("hdfc/call.pdf", "HDFCBANK", 14,
         "If you look at the unsecured mix, the provision coverage will be in the 70s, mid-70s or higher."),
        ("eternal/call.pdf", "ETERNAL", 3,
         "It's hard to project or comment on margin trajectory every quarter but broadly, over the next 1 or 2 "
         "years, we expect the margins to remain flattish."),
        ("eternal/call2.pdf", "ETERNAL", 6,
         "As we move to 5-6% margin that we are saying we will get to at some point, contribution margin will go "
         "up and on a year-on-year basis, we'll see that trend consistently."),
        ("hul/call.pdf", "HINDUNILVR", 4,
         "From a profitability perspective, EBITDA grew 6% year-on-year with EBITDA margin at 23.7%, coming in "
         "at the higher end of our guidance."),
        ("sun/call.pdf", "SUNPHARMA", 4,
         "Exceptional items for Q1 FY27 include a charge of INR1,617 million towards Organon's acquisition-"
         "related costs."),
        ("hdfc/call.pdf", "HDFCBANK", 10,
         "The Board will of course meet in due course, take the various regulators into confidence, and then take "
         "a call on the new chairman."),
    ]
    write_db(path, docs, pages)
    guidance.run(str(path), ["HDFCBANK", "ETERNAL", "HINDUNILVR", "SUNPHARMA"])
    got = {(r["symbol"], r["metric"], r["target_period"], r["low"], r["high"], r["direction"]) for r in rows(path)}
    assert ("HDFCBANK", "other", "FY27", None, None, "up") in got, got
    assert ("ETERNAL", "ebitda_margin", "FY27", None, None, "flat") in got, got
    assert ("ETERNAL", "ebitda_margin", "FY27", 5.0, 6.0, "up") in got, got
    quotes = " ".join(r["quote"] for r in rows(path))
    for needle in ("EBITDA margin at 23.7%", "Exceptional items", "new chairman"):
        assert needle not in quotes, f"still a target: {needle}"


def test_a_cagr_is_the_top_line_and_a_store_kpi_is_other():
    """The 60% CAGR guidance is revenue growth (and an EBITDA CAGR is not); "INR 11 lakh per day per store" is a
    store-level target stored as ``other``, the only metric the enum has for it."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_cagr.db"
    write_db(path,
             [("eternal/call.pdf", "ETERNAL", "deck", "2026-05-06", "2026-05-06T13:57:28"),
              ("eternal/call2.pdf", "ETERNAL", "deck", "2026-10-27", "2026-10-27T13:57:28")],
             [("eternal/call.pdf", "ETERNAL", 4,
               "We've given overall guidance of 60% CAGR and that would obviously mean some reasonable store "
               "expansion, but we're not planning to give out any specific number guidance on that."),
              ("eternal/call2.pdf", "ETERNAL", 12,
               "We gave guidance last time that in steady state it could get to about INR 11 lakh per day per "
               "store.")])
    guidance.run(str(path), ["ETERNAL"])
    got = {(r["metric"], r["target_period"], r["low"], r["high"], r["unit"]) for r in rows(path)}
    assert ("revenue_growth", "FY27", 60.0, 60.0, "pct") in got, got
    assert ("other", "FY27", 11.0, 11.0, "inr_lakh") in got, got
    ebitda = "Our revenue grew by 14.4% and the EBITDA/CAGR is 13%"
    assert guidance.NON_REVENUE_CAGR.search(ebitda)
    assert not guidance.subject_ok("revenue_growth", ebitda, guidance.numbers(ebitda)[-1], "")


def test_an_insurers_margin_stays_a_margin_not_a_nim():
    """T-058: SBILIFE carries ``lender: true`` (it is a life insurer), so its "margin" was mapped to NIM and then
    refused (``nim``/``credit_cost`` are read only for a bank or NBFC) and every margin row was lost.  A bank's
    "margin" is still its NIM."""
    import json

    from reality_engine.pilot3 import profile

    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_insurer_profile.json"
    path.write_text(json.dumps({
        "name": "insurer", "pages_db": "a.db", "raw_root": "raw", "manifest": "m.csv", "out": "o.db",
        "companies": [{"symbol": "SBILIFE", "sector": "insurance_life", "lender": True},
                      {"symbol": "HDFCBANK", "sector": "bank", "lender": True}]}), encoding="utf-8")
    profile.activate(profile.load(path))
    try:
        insurer = ("So we expect that our margin will continue to be a similar range that we maintain about "
                   "26% to 28% range that we are seeing.")
        assert guidance.metric_candidates("SBILIFE", insurer, "", "") == ["ebitda_margin"]
        bank = "we expect the margin to be around 3% to 3.5% for the year"
        assert guidance.metric_candidates("HDFCBANK", bank, "", "") == ["nim"]
    finally:
        profile.activate(None)


# --- T-062, 4 Nov 2026: a growth sentence, a customer mix, a slice of a total, the quarter and a delta ---------
def test_the_growth_sentence_the_mix_the_slice_the_quarter_and_the_delta():
    """The four rows the ticket names, each read from its own sentence: a growth sentence must not take a margin
    metric from the visible question, a customer profiling list is not a target, a number taken out of a stated
    total is a slice, "in the Q2 level" is that quarter of the filing's year, and a reduction or an accretion is
    the size of a change, not a level."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_t062.db"
    docs = [("sbi/call.pdf", "SBILIFE", "transcript", "2026-04-28", "2026-04-28T17:00:00"),
            ("maruti/call.pdf", "MARUTI", "transcript", "2026-08-06", "2026-08-06T17:00:00"),
            ("kec/call.pdf", "KEC", "transcript", "2026-05-21", "2026-05-21T16:00:00"),
            ("hind/call.pdf", "HINDALCO", "transcript", "2025-11-13", "2025-11-13T17:00:00"),
            ("infy/call.pdf", "INFY", "transcript", "2026-04-27", "2026-04-27T17:00:00"),
            ("eternal/call.pdf", "ETERNAL", "transcript", "2025-10-16", "2025-10-16T17:00:00")]
    pages = [
        # the visible question is about margins; the answer is the individual APE growth, and the second
        # "14% to 15%" sits 200 characters past "growing"
        ("sbi/call.pdf", "SBILIFE", 1,
         "What about the margin outlook for the year? So we expect that our margin will continue to be a similar "
         "range that we maintain about 26% to 28% range that we are seeing."),
        ("sbi/call.pdf", "SBILIFE", 2,
         "What about the margin outlook for the year? But at the start of the financial year, we had given a "
         "guidance that we'll be growing for the year at around 14% to 15% and we are sticking to our guidance "
         "for the entire financial year, notwithstanding the quarter-to- quarter or month-to-month variation, we "
         "are very sure that for the financial year, we will be closing with 14% to 15% as we had guided for."),
        # a customer profile, not a target
        ("maruti/call.pdf", "MARUTI", 1,
         "And the other customer profiling, so salaried is about 40%, business would be about 34%, self-employed "
         "about 20%, very broad profiling for customers."),
        # the whole and a slice of it
        ("kec/call.pdf", "KEC", 1,
         "So we expect that we should be touching around INR30,000 crores of order intake for the year."),
        ("kec/call.pdf", "KEC", 2,
         "So out of INR30,000 crores, if you take it, roughly it would be INR20,000 crores, maybe a little bit "
         "here and there."),
        # the quarter the call reports, not the filing's default year
        ("hind/call.pdf", "HINDALCO", 1,
         "So the cost of production in the Q2 level, I was expecting that question really is about 3% to 4% "
         "higher than Q1."),
        # a reduction inside the FY27 guidance list is not the growth guidance
        ("infy/call.pdf", "INFY", 1,
         "The FY27 guidance includes - Contribution from Stratus which we closed earlier this week, but excludes "
         "Versent JV and Optimum Healthcare acquisitions that are yet to be closed. - Reduction of 0.75% to 1% "
         "due to lower revenue from one of our large European manufacturing client."),
        # an accretion is not the margin level, and "in the next quarter" is the quarter after the call's own
        ("eternal/call.pdf", "ETERNAL", 1,
         "So far, we have banked more than half of the 1% point margin accretion that we expect as a result of "
         "this change."),
        ("eternal/call.pdf", "ETERNAL", 2,
         "As a result, in Q2FY26 about 80% of the NOV was on our own inventory which is expected to go to a "
         "steady state number of about 90% in the next quarter."),
    ]
    write_db(path, docs, pages)
    guidance.run(str(path), ["SBILIFE", "MARUTI", "KEC", "HINDALCO", "INFY", "ETERNAL"])
    got = {(r["symbol"], r["metric"], r["target_period"], r["low"], r["high"], r["unit"]) for r in rows(path)}
    # the margin guidance the sentence names stays a margin row (the sentence that must stay)
    assert ("SBILIFE", "ebitda_margin", "FY27", 26.0, 28.0, "pct") in got, got
    assert not rows(path, "symbol='SBILIFE' AND low=14 AND metric='ebitda_margin'")
    assert not rows(path, "symbol='MARUTI'")
    assert ("KEC", "order_intake", "FY27", 30000.0, 30000.0, "inr_cr") in got, got
    assert not rows(path, "symbol='KEC' AND low=20000")
    assert ("HINDALCO", "cost_of_production", "Q2FY26", 3.0, 4.0, "pct") in got, got
    assert not rows(path, "symbol='INFY'")
    assert not rows(path, "symbol='ETERNAL' AND metric='ebitda_margin'")
    assert ("ETERNAL", "other", "Q3FY26", 90.0, 90.0, "pct") in got, got


def test_the_growth_rule_and_the_insurers_top_line_on_their_own():
    # the second "14% to 15%" is 200 characters past "growing", so only the whole sentence sees the growth
    sb = ("But at the start of the financial year, we had given a guidance that we'll be growing for the year at "
          "around 14% to 15% and we are sticking to our guidance for the entire financial year, notwithstanding "
          "the quarter-to- quarter or month-to-month variation, we are very sure that for the financial year, we "
          "will be closing with 14% to 15% as we had guided for.")
    chosen = guidance.pick_number(sb, guidance.numbers(sb))
    assert chosen is not None and chosen["start"] > 300
    assert guidance.subject_ok("ebitda_margin", sb, chosen, "What about margins?") is False
    # an insurer's IRP/APE is its top line: "the guidance of 14% to 15% overall company" is growth, not a margin
    restatement = ("But what I will assure you is that the guidance of 14% to 15% overall company, that we are "
                   "going to stay with.")
    assert guidance.metric_candidates("SBILIFE", restatement,
                                      "So first question was regarding IRP breakdown for the different channels.",
                                      "")[0] == "revenue_growth"
    # a worded target takes its direction from its own size words, not from a growth elsewhere in the sentence
    flat = "So, that's why you see the growth in margin versus our earlier guidance of margin perhaps remaining flat."
    move = guidance.WORDED_MOVE.search(flat)
    assert move is not None
    assert guidance.worded_direction(flat, "ebitda_margin", move.start()) == "flat"
    up = "On the guidance, we expect high single-digit consolidated top line growth for FY27"
    assert guidance.worded_direction(up, "revenue_growth", up.index("single")) == "up"
    # the change rules on their own
    assert guidance.PCT_CHANGE.match(" point margin accretion that we expect")
    assert guidance.OTHER_TARGET.search("I am targeting that next year we should be delivering INR100,000 crores")
    assert not guidance.OTHER_TARGET.search("salaried is about 40%, business would be about 34%")
    slice_sentence = ("So out of INR30,000 crores, if you take it, roughly it would be INR20,000 crores, maybe a "
                      "little bit here and there.")
    sliced = guidance.pick_number(slice_sentence, guidance.numbers(slice_sentence))
    assert sliced is not None and sliced["low"] == 20000
    assert guidance.subject_ok("order_intake", slice_sentence, sliced, "") is False
    assert guidance.PAST_ONLY.search("yield on assets have come down from the beginning of the rate cycle")
    quarter = ("So the cost of production in the Q2 level, I was expecting that question really is about 3% to 4% "
               "higher than Q1.")
    assert guidance.target_period(quarter, "", "", "Q2FY26", (26, "Q2"),
                                  guidance.numbers(quarter)[0]["start"]) == "Q2FY26"
    reduction = ("The FY27 guidance includes - Reduction of 0.75% to 1% due to lower revenue from one of our large "
                 "European manufacturing client.")
    assert guidance.subject_ok("revenue_growth", reduction, guidance.numbers(reduction)[0], "") is False
    # "reach 9%, 10% margin" is a pair, not a 9% target (T-049 ticket list)
    pair = "The target again is that how soon we can reach 9%, 10% margin."
    assert [(n["low"], n["high"], n["unit"]) for n in guidance.numbers(pair)] == [(9.0, 10.0, "pct")]


# --- T-105, 8 Nov 2026: the Q2 FY27 call's missed targets, the horizon labels and the current-target view --------
def write_call_db(path: Path, docs: list[tuple], pages: list[tuple], statements: list[tuple]) -> None:
    """docs: (doc_key, symbol, doc_type, filing_date, known_at); pages: (doc_key, symbol, page, text);
    statements: full transcript_statement rows (symbol, doc_key, call_date, call_period, page, seq, speaker,
    role, statement, quote)."""
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    con = sqlite3.connect(path)
    con.execute(schema.TABLES["doc"])
    con.execute(schema.TABLES["doc_page"])
    con.executescript(TRANSCRIPT_SCHEMA)
    con.executemany("INSERT INTO doc(doc_key,symbol,isin,doc_type,doc_family,title,filing_date,known_at,pages) "
                    "VALUES (?,?,NULL,?,?,'Conference Call',?,?,1)",
                    [(d[0], d[1], d[2], d[2], d[3], d[4]) for d in docs])
    con.executemany("INSERT INTO doc_page(doc_key,symbol,page,text,method,chars,known_at) "
                    "VALUES (?,?,?,?,'script_text',?,NULL)", [(d, s, p, t, len(t)) for d, s, p, t in pages])
    con.executemany(
        "INSERT INTO transcript_statement(symbol,doc_key,call_date,call_period,page,seq,speaker,role,section,topics,"
        "period_discussed,period_source,numbers_json,statement,quote,is_fragment,known_at,known_at_source,"
        "extractor_rule) VALUES (?,?,?,?,?,?,?,?,'prepared','guidance','','call','[]',?,?,0,'x','x','t')",
        statements)
    con.commit()
    con.close()


def nbfc_profile():
    """A profile that calls BAJFINANCE a lender, so the unqualified "growth" is read as AUM growth (T-105)."""
    import json

    from reality_engine.pilot3 import profile

    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_t105_nbfc_profile.json"
    path.write_text(json.dumps({
        "name": "nbfc", "pages_db": "a.db", "raw_root": "raw", "manifest": "m.csv", "out": "o.db",
        "companies": [{"symbol": "BAJFINANCE", "sector": "nbfc", "lender": True}]}), encoding="utf-8")
    return profile.load(path)


def test_the_q2_fy27_call_count_and_opex_targets():
    """T-105: "60 million to 62 million new loans", "18 MM to 20 MM customers" and "a 25 to 40 basis point
    improvement … on opex-to-NTI" are targets the v1 cue list and number parser did not see."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_t105_counts.db"
    doc = ("baj/call_q2fy27.pdf", "BAJFINANCE", "transcript", "2026-10-23", "2026-10-23T14:45:33")
    sentences = [
        "New loans grew 11% to 13.5 million.",
        "We are well on track to deliver between 60 million to 62 million new loans in FY27.",
        "We added 4.42 million new customers during the quarter.",
        "We are clear about adding between 18 MM to 20 MM customers to the franchise in FY27.",
        "We remain pretty comfortable place to deliver a 25 to 40 basis point improvement in FY27 on opex-to-NTI.",
    ]
    statements = [("BAJFINANCE", "baj/call_q2fy27.pdf", None, "Q2FY27", 1, i + 1, "Rajeev Jain", "md", s, s)
                  for i, s in enumerate(sentences)]
    write_call_db(path, [doc], [("baj/call_q2fy27.pdf", "BAJFINANCE", 1, " ".join(sentences))], statements)
    guidance.run(str(path), ["BAJFINANCE"])
    got = {(r["metric"], r["target_period"], r["low"], r["high"], r["unit"], r["extractor_rule"])
           for r in rows(path)}
    assert ("new_loans", "FY27", 60.0, 62.0, "mn", "guidance_cue_v2") in got, got
    assert ("new_customers", "FY27", 18.0, 20.0, "mn", "guidance_cue_v2") in got, got
    assert ("opex_to_nti", "FY27", 25.0, 40.0, "bps", "guidance_cue_v2") in got, got
    assert not rows(path, "quote LIKE '%New loans grew 11%%'"), "a past measurement is not a count target"


def test_the_q2_fy27_growth_target_and_the_horizons():
    """T-105: "between 26%, 27% growth we should deliver now on a full year basis" is the FY27 AUM growth target;
    the metric comes from the growth word (a lender's unqualified growth is its AUM), and the sentence after it,
    "we maintain a guidance of 20% to 25%", carries only the medium-term corridor -- a horizon, not FY27."""
    from reality_engine.pilot3 import profile

    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_t105_growth.db"
    doc = ("baj/call_q2fy27.pdf", "BAJFINANCE", "transcript", "2026-10-23", "2026-10-23T14:45:33")
    page = ("Kunal Shah: Yes. Hi, so the first question is on growth guidance. Last time you said almost 26% growth "
            "plus the capital raise is also for the growth story. So, what would be the growth guidance here onwards "
            "for near and medium term? So that's the first question? And second, in terms of the overall margins, "
            "what is the outlook on margins, yes? Rajeev Jain: So, I would say FY27, two quarters gone. We're seeing "
            "the early onset of festival first 9, 10 days. I would say probably between 26%, 27% growth we should "
            "deliver now on a full year basis. I think that's just medium term, we maintain a guidance of 20% to 25% "
            "on a year lower here and a year higher there.")
    statements = [
        ("BAJFINANCE", "baj/call_q2fy27.pdf", None, "Q2FY27", 1, 1, "Rajeev Jain", "md",
         "So, I would say FY27, two quarters gone.", "So, I would say FY27, two quarters gone."),
        ("BAJFINANCE", "baj/call_q2fy27.pdf", None, "Q2FY27", 1, 2, "Rajeev Jain", "md",
         "I would say probably between 26%, 27% growth we should deliver now on a full year basis.",
         "I would say probably between 26%, 27% growth we should deliver now on a full year basis."),
        ("BAJFINANCE", "baj/call_q2fy27.pdf", None, "Q2FY27", 1, 3, "Rajeev Jain", "md",
         "I think that's just medium term, we maintain a guidance of 20% to 25% on a year lower here and a year "
         "higher there.",
         "I think that's just medium term, we maintain a guidance of 20% to 25% on a year lower here and a year "
         "higher there."),
    ]
    write_call_db(path, [doc], [("baj/call_q2fy27.pdf", "BAJFINANCE", 1, page)], statements)
    profile.activate(nbfc_profile())
    try:
        guidance.run(str(path), ["BAJFINANCE"])
    finally:
        profile.activate(None)
    got = {(r["metric"], r["target_period"], r["low"], r["high"], r["unit"], r["extractor_rule"])
           for r in rows(path)}
    assert ("aum_growth", "FY27", 26.0, 27.0, "pct", "guidance_cue_v2_context") in got, got
    assert ("aum_growth", "medium_term", 20.0, 25.0, "pct", "guidance_cue_v2_context") in got, got
    assert not rows(path, "target_period='FY27' AND low=20"), "the medium-term corridor must not become FY27"


def test_the_past_measurements_of_the_q2_fy27_call_stay_out():
    """T-105: the five sentences a hand read marked as must-stay-out are past facts or hypotheticals, not targets."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_t105_past.db"
    doc = ("baj/call_q2fy27.pdf", "BAJFINANCE", "transcript", "2026-10-23", "2026-10-23T14:45:33")
    sentences = [
        "AUM, as you can see, grew by 26.5% to INR 5,84,624 crores, delivering net AUM addition of close to INR "
        "38,000 crores in the quarter.",
        "New loans grew 11% to 13.5 million.",
        "Cost of funds came down sequentially by 9 basis points and came in at 7.31%.",
        "In a year, we may grow 27%, in a year, we may grow 23%.",
        "Q2 was 10- 12 basis points lower than Q1.",
    ]
    statements = [("BAJFINANCE", "baj/call_q2fy27.pdf", None, "Q2FY27", i + 1, 1, "Rajeev Jain", "md", s, s)
                  for i, s in enumerate(sentences)]
    pages = [("baj/call_q2fy27.pdf", "BAJFINANCE", i + 1, s) for i, s in enumerate(sentences)]
    write_call_db(path, [doc], pages, statements)
    guidance.run(str(path), ["BAJFINANCE"])
    assert not rows(path), [r["quote"] for r in rows(path)]


def test_the_current_target_is_the_latest_document_and_history_keeps_the_chain():
    """T-105 step 2: April 22-24%, August 24-25%, October 26-27% -- the default view serves only October, an as_of
    before October serves only August, and history keeps all three."""
    from reality_engine.pilot3 import queries

    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_t105_current.db"
    docs = [("baj/deck_apr.pdf", "BAJFINANCE", "deck", "2026-04-29", "2026-04-29T17:00:00"),
            ("baj/call_aug.pdf", "BAJFINANCE", "deck", "2026-08-04", "2026-08-04T17:00:00"),
            ("baj/call_oct.pdf", "BAJFINANCE", "deck", "2026-10-23", "2026-10-23T14:45:33")]
    pages = [("baj/deck_apr.pdf", "BAJFINANCE", 1, "The Company estimates AUM growth of 22-24% for FY27."),
             ("baj/call_aug.pdf", "BAJFINANCE", 1, "We expect AUM growth of 24% to 25% for FY27."),
             ("baj/call_oct.pdf", "BAJFINANCE", 1, "We now expect AUM growth of 26% to 27% for FY27.")]
    write_db(path, docs, pages)
    guidance.run(str(path), ["BAJFINANCE"])
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        current = queries.guidance_rows(con, "BAJFINANCE", metric="aum", period="FY27")
        before_oct = queries.guidance_rows(con, "BAJFINANCE", metric="aum", period="FY27", as_of="2026-10-01")
        history = queries.guidance_rows(con, "BAJFINANCE", metric="aum", period="FY27", history=True)
    finally:
        con.close()
    assert [(r["low"], r["high"]) for r in current] == [(26.0, 27.0)], current
    assert current[0]["superseded_rows"] == 2, "the April and August rows are both behind the October one"
    assert [(r["low"], r["high"]) for r in before_oct] == [(24.0, 25.0)], before_oct
    assert before_oct[0]["superseded_rows"] == 1
    assert [(r["low"], r["high"]) for r in history] == [(26.0, 27.0), (24.0, 25.0), (22.0, 24.0)], history


# --- T-166, 10 Nov 2026: the outside forecast, the speaker and the two noise shapes -----------------------
def test_an_outside_forecast_is_not_company_guidance():
    """The real Chola slide sentences (u8): ICRA's and CRISIL's industry outlook and an unlabelled industry
    forecast are not Cholamandalam's targets, while a management sentence in the same store stays."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_t166_forecast.db"
    docs = [("chola/deck_2026.pdf", "CHOLAFIN", "deck", "2026-07-28", "2026-07-28T17:00:00")]
    pages = [("chola/deck_2026.pdf", "CHOLAFIN", 1,
              "Sector Outlook | Chola’s Position | Home Loans - Industry outlook "
              "• ICRA expects AUM of AHFCs to rise by 19% -21% in FY26 and FY27. "
              "• The overall growth in HFCs is expected to remain at 12-14% in FY24. "
              "• Credit costs in the sector are expected to moderate slightly to 2.0-2.2% in FY2027. "
              "• CRISIL estimates the LAP segment to experience growth at a rate of 10-12% for FY24."),
             ("chola/deck_2026.pdf", "CHOLAFIN", 2,
              "ICRA Rating highlighted that NBFC are experiencing a moderation in credit expansion at present. "
              "Growth is expected to ease to 13% -15% in FY25 and FY26 from the 17% expansion witnessed in the "
              "previously two fiscal."),
             ("chola/deck_2026.pdf", "CHOLAFIN", 3,
              "We still believe we have always guided in the 20% to 25% range for AUM growth, and we still believe "
              "that will hold.")]
    write_db(path, docs, pages)
    guidance.run(str(path), ["CHOLAFIN"])
    got = rows(path)
    quotes = [r["quote"] or "" for r in got]
    assert not [q for q in quotes if "ICRA" in q or "CRISIL" in q or "HFCs" in q or "the sector" in q
                or "Growth is expected to ease" in q], quotes
    assert [r for r in got if r["metric"] == "aum_growth" and r["low"] == 20 and r["high"] == 25], got


def test_the_previous_sentence_attributes_only_when_the_company_does_not_speak():
    assert guidance.external_forecast("ICRA expects AUM of AHFCs to rise by 19% -21% in FY26 and FY27.")
    assert guidance.external_forecast("The overall growth in HFCs is expected to remain at 12-14% in FY24")
    assert guidance.external_forecast(
        "Growth is expected to ease to 13% -15% in FY25 and FY26",
        "ICRA Rating highlighted that NBFC are experiencing a moderation in credit expansion at present.")
    # a rating boilerplate before the company's own sentence does not make it an outside forecast
    assert not guidance.external_forecast("We expect revenue growth of 15% for FY27.",
                                          "ICRA has reaffirmed our rating at AA+.")
    # an "industry tailwind" is not an industry forecast of the company's number
    assert not guidance.external_forecast("Structural Tailwinds for Travel & Tourism Industry expected to continue")


def test_the_analysts_question_and_the_non_management_role_are_not_guidance():
    """The real BEL call page: Umesh Raut's question ("order inflow guidance of INR27,000 crores") was stored
    as an order-intake row because the wrapped sentence never matched its "Name:" label; the label fix and the
    role check keep it out, and a management statement in the same document still produces its row."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_t166_speaker.db"
    doc = ("bel/call_2025-11-04.pdf", "BEL", "transcript", "2025-11-04", "2025-11-04T17:57:09")
    pages = [("bel/call_2025-11-04.pdf", "BEL", 1,
              "Moderator: The next question is from the line of Umesh Raut from Nomura.\n"
              "Umesh Raut:\nCongrats for a very good set of numbers. Sir, my first question is pertaining to "
              "order inflow guidance of INR27,000 crores, excluding QRSAM for FY '26. So in that order inflow "
              "guidance, are we assuming any orders from next-generation corvette?\n"
              "Manoj Jain:\nCertainly, yes. As I told, in this NGC partial orders because overall NGC has so "
              "many BEL components."),
             ("bel/call_2025-11-04.pdf", "BEL", 2,
              "We expect revenue growth of 15% for FY27."),
             ("bel/call_2025-11-04.pdf", "BEL", 3,
              "Manoj Jain: We expect order intake of INR30,000 crores for FY27.")]
    statements = [
        # the statement store knows this call only as the generic "Management": the raw page's named MD is
        # still management, so the analyst-intro set (not the statement speaker list) decides the speaker check
        ("BEL", "bel/call_2025-11-04.pdf", None, "Q2FY26", 2, 1, "Management", "md",
         "We expect revenue growth of 15% for FY27.", "We expect revenue growth of 15% for FY27."),
        ("BEL", "bel/call_2025-11-04.pdf", None, "Q2FY26", 2, 2, "Some Analyst", "analyst",
         "We expect order intake of INR30,000 crores for FY27.",
         "We expect order intake of INR30,000 crores for FY27."),
    ]
    write_call_db(path, [doc], pages, statements)
    guidance.run(str(path), ["BEL"])
    got = rows(path)
    assert not [r for r in got if "order inflow guidance of INR27,000" in (r["quote"] or "")], got
    assert not [r for r in got if r["speaker"] == "Some Analyst"], got
    assert [r for r in got if (r["quote"] or "").startswith("We expect revenue growth of 15%")], got
    # a named speaker on a page of a call the statement store stored as "Management" is not an analyst
    assert [r for r in got if r["speaker"] == "Manoj Jain" and r["metric"] == "order_intake"], got


def test_a_variability_band_is_a_target_and_a_plain_wide_range_is_not():
    """The real BEL rows (u8): "we have variability of 25% to 31% EBITDA margins" is management's own band and is
    a target (T-187), while a plain 7-point range is not; "INR120-plus million" (read as 120 crore) is far below
    BEL's own five-figure-crore order intake."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_t166_noise.db"
    write_db(path,
             [("bel/call_2026-07-28.pdf", "BEL", "deck", "2026-07-28", "2026-07-28T14:01:42")],
             [("bel/call_2026-07-28.pdf", "BEL", 1,
               # the question that makes the band answer a guidance statement (the real call's Q&A)
               "Is that really achievable, going forward for the coming quarters, on EBITDA margins? "
               "We have variability of 25% to 31% EBITDA margins based on the product mix in quarter-to-quarter "
               "etcetera, but at the year end, let me again assure you, we will cross 28%."),
              ("bel/call_2026-07-28.pdf", "BEL", 2,
               "We are confident of what our target we have given around INR120-plus million."),
              ("bel/call_2026-07-28.pdf", "BEL", 3,
               "As far as order intake is concerned, we expect around INR30,000 crores for the year."),
              # the width rule on its own: a 7-point range is not a corridor, a 2-point one is
              ("bel/call_2026-07-28.pdf", "BEL", 4,
               "We expect an EBITDA margin of 18% to 25% for FY27."),
              ("bel/call_2026-07-28.pdf", "BEL", 5,
               "We expect an EBITDA margin of 23% to 25% for FY27.")])
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE kpi_series (symbol TEXT, metric TEXT, value REAL, unit TEXT)")
    con.executemany("INSERT INTO kpi_series VALUES (?,?,?,?)",
                    [("BEL", "order_intake", 20000.0, "inr_cr"), ("BEL", "order_intake", 24000.0, "inr_cr"),
                     ("BEL", "order_intake", 27000.0, "inr_cr")])
    con.commit()
    con.close()
    guidance.run(str(path), ["BEL"])
    got = rows(path)
    assert [r for r in got if r["metric"] == "ebitda_margin" and r["low"] == 25 and r["high"] == 31], got
    assert not [r for r in got if r["metric"] == "ebitda_margin" and r["low"] == 18 and r["high"] == 25], got
    assert not [r for r in got if r["metric"] == "order_intake" and r["high"] == 120], got
    assert [r for r in got if r["metric"] == "order_intake" and r["high"] == 30000], got
    assert [r for r in got if r["metric"] == "ebitda_margin" and r["low"] == 23 and r["high"] == 25], got


# --- T-166 round 4, 10 Nov 2026: the clause, the table, the past figure and the speaker ---------------------
ADANI_FY26_BLOB = (
    "• India Ratings & Research reaffirmed the credit rating of non-convertible debentures and bank loans "
    "(long-term) of APSEZ as IND AAA / Stable and commercial paper and bank loans (short term) as IND A1+  "
    "FY26 guidance  Parameter  FY26 guidance  Revenue ₹36,000-38,000 Cr  EBITDA ₹21,000-22,000 Cr  "
    "Capex ₹11,000-12,000 Cr  Net debt / EBITDA  Policy up to 2.5x")


def test_step1_an_agency_name_removes_only_its_own_clause():
    """The real ADANIPORTS page blob prints India Ratings and then the FY26 guidance table: the revenue
    36,000-38,000 target survives (the agency does not govern that clause), while ICRA's 19-21% does not."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_t166_r4_clause.db"
    docs = [("ports/deck_2026.pdf", "ADANIPORTS", "deck", "2026-05-01", "2026-05-01T17:00:00"),
            ("chola/deck_2026.pdf", "CHOLAFIN", "deck", "2026-07-28", "2026-07-28T17:00:00")]
    pages = [("ports/deck_2026.pdf", "ADANIPORTS", 1, ADANI_FY26_BLOB),
             ("chola/deck_2026.pdf", "CHOLAFIN", 1,
              "• ICRA expects AUM of AHFCs to rise by 19% -21% in FY26 and FY27. "
              "• CRISIL estimates the LAP segment to experience growth at a rate of 10-12% for FY24.")]
    write_db(path, docs, pages)
    guidance.run(str(path), ["ADANIPORTS", "CHOLAFIN"])
    got = rows(path)
    assert [r for r in got if r["symbol"] == "ADANIPORTS" and r["metric"] == "revenue"
            and (r["low"], r["high"]) == (36000, 38000)], got
    assert [r for r in got if r["symbol"] == "ADANIPORTS" and r["metric"] == "ebitda"
            and (r["low"], r["high"]) == (21000, 22000)], got
    assert not [r for r in got if r["symbol"] == "CHOLAFIN"], got


def test_step2_a_guidance_table_keys_each_number_by_its_label():
    """A real table (label beside its own amount, named guidance, named FY) yields one row per line; prose that
    merely mentions Revenue and EBITDA is not a table, and the OCR "18.800-18,900" is not a corridor."""
    table = guidance.table_targets(
        "FY26 guidance  Parameter  FY26 guidance  Revenue ₹36,000-38,000 Cr  EBITDA ₹21,000-22,000 Cr  "
        "Capex ₹11,000-12,000 Cr  Net debt / EBITDA  Policy up to 2.5x")
    assert [(r["metric"], r["num"]["low"], r["num"]["high"], r["period"]) for r in table] == [
        ("revenue", 36000, 38000, "FY26"), ("ebitda", 21000, 22000, "FY26"), ("capex", 11000, 12000, "FY26")]
    prose = "Revenue and EBITDA guidance at ₹36,000-38,000 Cr and ₹21,000-22,000 Cr respectively"
    assert guidance.table_targets(prose) == []
    parsed = guidance.table_targets(
        "FY25 Guidance 47 EBITDA Rs 18.800-18,900 Cr (previous guidance: Rs 17,000 – 18,000 Cr) FY25 Guidance "
        "Revenue Rs 29,000-31,000 Cr Capex Rs 10,500-11,500 Cr Net Debt to EBITDA 2.2–2.5x")
    assert [(r["metric"], r["num"]["low"], r["num"]["high"]) for r in parsed] == [
        ("revenue", 29000, 31000), ("capex", 10500, 11500)]


def test_step3_past_figures_are_not_guidance():
    """The APLAPOLLO movement, the H1 spend, "had targeted", "used to be", "achieved … of guidance" and the
    measured value before "against target" are measurements; a target in another clause survives."""
    def kept(text: str) -> list[tuple]:
        return [(n["low"], n["high"]) for n in guidance.numbers(text) if not guidance.past_figure(text, n)]

    apollo = ("Our EBITDA per ton improved to Rs. 5,400 from Rs. 4,200 per ton this was drive by value addition, "
              "brand premium and market fold which we saw in the first half of FY22 and now we are confident that "
              "our margins going forward should be in range of Rs. 4,500 to Rs. 5,500 per ton.")
    assert not [v for v in kept(apollo) if v[1] <= 4200], kept(apollo)
    idea = ("On the capex for the H2, we have spent Rs. 4,200 crores towards capex in the H1, and our guidance "
            "is that we would be in the range of Rs. 7,500 to 8,000 crores.")
    assert (7500.0, 8000.0) in kept(idea) and not [v for v in kept(idea) if v[1] == 4200], kept(idea)
    coal = "FY 22-23 capex is ~INR 18,619 crore against target of INR 16,500 crore"
    assert (16500.0, 16500.0) in kept(coal) and not [v for v in kept(coal) if v[0] == 18619], kept(coal)
    used = ("2022, we used to be around Rs.20,000, Rs.22,000 crores of capex, which we stepped up for the rollout "
            "of 5G and then that number went up all the way to Rs.28,000 to Rs.34,000 crores")
    assert (28000.0, 34000.0) in kept(used) and not [v for v in kept(used) if v[0] == 20000], kept(used)
    achieved = "We have achieved 75% of our revised revenue guidance as well of INR 980 crores"
    assert not [v for v in kept(achieved) if v[0] == 75], kept(achieved)
    # a target stated in another clause is not removed by the past figure beside it
    forward = "We expect EBITDA margin of 24.5% to 25.5% for FY25."
    assert (24.5, 25.5) in kept(forward), kept(forward)


def test_step4_a_slide_title_is_not_a_speaker_and_management_stays():
    """Decks: "International Ports:" / "Solid future outlook:" are slide titles, never speakers. A transcript
    keeps its management speakers ("Manoj Jain", "Management")."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_t166_r4_speaker.db"
    docs = [("ports/deck.pdf", "ADANIPORTS", "deck", "2026-10-28", "2026-10-28T17:00:00"),
            ("bel/call.pdf", "BEL", "transcript", "2025-11-04", "2025-11-04T17:57:09")]
    pages = [("ports/deck.pdf", "ADANIPORTS", 1,
              "International Ports:\nDriven by strong H1 performance, APSEZ has upgraded its capex guidance to "
              "₹15,000 Cr - ₹17,000 Cr (₹12,000 Cr - ₹14,000 previously)"),
             ("ports/deck.pdf", "ADANIPORTS", 2,
              "Solid future outlook:\nSufficient capacity for 20% annual sales volume growth Three focus areas: "
              "Cash flows and profitability"),
             ("bel/call.pdf", "BEL", 2,
              "Manoj Jain: We expect revenue growth of 15% for FY27.")]
    statements = [
        ("BEL", "bel/call.pdf", None, "Q2FY26", 2, 1, "Manoj Jain", "md",
         "We expect order intake of INR30,000 crores for FY27.",
         "We expect order intake of INR30,000 crores for FY27."),
        ("BEL", "bel/call.pdf", None, "Q2FY26", 2, 2, "Management", "md",
         "We expect revenue growth of 15% for FY27.", "We expect revenue growth of 15% for FY27."),
    ]
    write_call_db(path, docs, pages, statements)
    guidance.run(str(path), ["ADANIPORTS", "BEL"])
    got = rows(path)
    assert [r for r in got if r["symbol"] == "ADANIPORTS"], got
    assert not [r for r in got if r["symbol"] == "ADANIPORTS" and r["speaker"]], got
    assert not [r for r in got if (r["speaker"] or "") == "Solid future outlook"], got
    assert [r for r in got if r["symbol"] == "BEL" and r["speaker"] == "Manoj Jain"
            and r["metric"] == "order_intake"], got
    assert [r for r in got if r["symbol"] == "BEL" and r["speaker"] == "Management"], got


# --- T-187, 11 Nov 2026: the four targets the 11 Nov rebuild lost, and gross margin is not a margin -------------
def test_t187_the_four_management_targets_are_restored():
    """The four real management sentences the 11 Nov rebuild dropped: a stated band of variability ("we have
    variability of 25% to 31% EBITDA margins"), a restated guided band ("which was a range of 23% to 24%"), a
    present-perfect capex restatement ("we have guided ... we have spent ... INR 1,100 crores") and an annual
    capex run-rate ("our annual CapEx has used to be ... INR 1200-1300 crores")."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_t187_targets.db"
    bel = ("We have variability of 25% to 31% EBITDA margins based on the product mix in quarter-to-quarter "
           "etcetera, but at the year end, let me again assure you, we will cross 28%.")
    cipla = ("EBITDA margin for the full year is trending at a higher end of what we had guided earlier, which was "
             "a range of 23% to 24%.")
    indhotel = ("So we have guided in the press release that firstly, in the context of the CAPEX, this year, we "
                "have spent close to about INR 1,100 crores.")
    apollo = ("So which is higher than what it has been in the recent past, where our annual CapEx has used to be "
              "for India, INR 1200 - 1300 crores.")
    docs = [("t187/bel.pdf", "BEL", "transcript", "2026-07-28", "2026-07-28T17:00:00"),
            ("t187/cipla.pdf", "CIPLA", "transcript", "2024-01-29", "2024-01-29T17:00:00"),
            ("t187/indhotel.pdf", "INDHOTEL", "transcript", "2025-05-12", "2025-05-12T17:00:00"),
            ("t187/apollo.pdf", "APOLLOTYRE", "transcript", "2026-08-11", "2026-08-11T17:00:00")]
    pages = [
        ("t187/bel.pdf", "BEL", 16,
         "Bhavya Gandhi: Is that really achievable, sir, going forward for the coming quarters, on EBITDA "
         "margins? Manoj Jain: Definitely yes. " + bel),
        ("t187/cipla.pdf", "CIPLA", 6, cipla),
        ("t187/indhotel.pdf", "INDHOTEL", 9, indhotel),
        ("t187/apollo.pdf", "APOLLOTYRE", 8,
         "Is it fair to say that the main CapEx because you had guided for more than INR 3,000 crores of CapEx "
         "this year? So the CapEx definitely has started. India quarter CapEx was INR 500 crores. " + apollo),
    ]
    statements = [
        ("BEL", "t187/bel.pdf", None, "Q1FY27", 16, 1, "Manoj Jain", "md", bel, bel),
        ("CIPLA", "t187/cipla.pdf", None, "Q3FY24", 6, 1, "Ashish Adukia", "cfo", cipla, cipla),
        ("INDHOTEL", "t187/indhotel.pdf", None, "Q4FY25", 9, 1, "Ankur Dalwani", "mgmt", indhotel, indhotel),
        ("APOLLOTYRE", "t187/apollo.pdf", None, "Q1FY27", 8, 1, "Gaurav Kumar", "cfo", apollo, apollo),
    ]
    write_call_db(path, docs, pages, statements)
    guidance.run(str(path), ["BEL", "CIPLA", "INDHOTEL", "APOLLOTYRE"])
    got = {(r["symbol"], r["metric"], r["target_period"], r["low"], r["high"], r["unit"], r["speaker"])
           for r in rows(path)}
    assert ("BEL", "ebitda_margin", "FY27", 25.0, 31.0, "pct", "Manoj Jain") in got, got
    assert ("CIPLA", "ebitda_margin", "FY24", 23.0, 24.0, "pct", "Ashish Adukia") in got, got
    assert ("INDHOTEL", "capex", "FY26", 1100.0, 1100.0, "inr_cr", "Ankur Dalwani") in got, got
    assert ("APOLLOTYRE", "capex", "FY27", 1200.0, 1300.0, "inr_cr", "Gaurav Kumar") in got, got


def test_t187_gross_margin_is_not_an_ebitda_margin():
    """T-187: a number governed by "gross margin" is never stored as ``ebitda_margin`` (no ``gross_margin``
    metric is added), while the EBITDA-margin number of the same sentence stays a row."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_t187_gross.db"
    mixed = "Gross margin for the full year should be around 42% and EBITDA margins would be around 23%."
    follow = ("So that mix determines the gross margin. So, going forward at the full year, we should have around "
              "42%. So that way it will average out to 58% and we end up with a gross margin of 42%.")
    write_db(path,
             [("t187/bel_gross.pdf", "BEL", "deck", "2024-02-02", "2024-02-02T17:00:00"),
              ("t187/cipla_gross.pdf", "CIPLA", "deck", "2026-05-15", "2026-05-15T17:00:00")],
             [("t187/bel_gross.pdf", "BEL", 1, mixed + " " + follow),
              ("t187/bel_gross.pdf", "BEL", 2, "The gross margin of 40% to 42% will be the range, so 45-"),
              ("t187/bel_gross.pdf", "BEL", 3,
               "See currently, the gross margin is not 49% as you said, it is around the range of 44.5% only, for "
               "up to December, the gross margin is 44.5% only, and we have guided for 42% to 44%."),
              ("t187/cipla_gross.pdf", "CIPLA", 1,
               "So chronic will definitely come with 5% to 10% better gross margin.")])
    guidance.run(str(path), ["BEL", "CIPLA"])
    got = [(r["metric"], r["target_period"], r["low"], r["high"], r["quote"]) for r in rows(path)]
    assert ("ebitda_margin", "FY24", 23.0, 23.0, mixed) in got, got
    assert not [r for r in got if r[0] == "ebitda_margin" and r[2] in (5.0, 40.0, 42.0, 44.5, 49.0)], got
    # the rule on its own: the last margin phrase before the number decides, and a bare number is the gross margin
    # the text restates ("we end up with a gross margin of 42%")
    for text, value, after in (
            ("The gross margin of 40% to 42% will be the range, so 45-", 40.0, ""),
            ("So chronic will definitely come with 5% to 10% better gross margin.", 5.0, ""),
            ("So, going forward at the full year, we should have around 42%.", 42.0,
             " So that way it will average out to 58% and we end up with a gross margin of 42%.")):
        number = next(n for n in guidance.numbers(text) if n["low"] == value)
        assert guidance.gross_margin_owns(text, number, after), text
    ok = "We expect an EBITDA margin of 23% to 25% for FY27."
    assert not guidance.gross_margin_owns(ok, guidance.numbers(ok)[0], "")


def test_t187_the_three_rightly_removed_classes_stay_out():
    """The rows the new rules rightly removed stay out after T-187: CHOLAFIN's CRISIL/ICRA industry forecasts, BEL's
    analyst-question order intake, and ADANIPORTS' "capex" rows whose number is the revenue/EBITDA guidance."""
    TMP.mkdir(exist_ok=True)
    path = TMP / "guidance_t187_removed.db"
    chola = [
        ("chola/deck.pdf", "CHOLAFIN", 1,
         "• ICRA expects AUM of AHFCs to rise by 19% -21% in FY26 and FY27. "
         "• The overall growth in HFCs is expected to remain at 12-14% in FY24. "
         "• CRISIL estimates the LAP segment to experience growth at a rate of 10-12% for FY24."),
        ("chola/deck.pdf", "CHOLAFIN", 2,
         "Growth is expected to ease to 13% -15% in FY25 and FY26 from the 17% expansion witnessed in the "
         "previously two fiscal."),
    ]
    bel = [("bel/call.pdf", "BEL", 1,
            "Moderator: The next question is from the line of Umesh Raut from Nomura.\n"
            "Umesh Raut:\nSir, my first question is pertaining to order inflow guidance of INR27,000 crores, "
            "excluding QRSAM for FY '26.\n"
            "Manoj Jain:\nCertainly, yes.")]
    ports = [("ports/deck.pdf", "ADANIPORTS", 1, ADANI_FY26_BLOB)]
    write_call_db(path,
                  [("chola/deck.pdf", "CHOLAFIN", "deck", "2026-07-28", "2026-07-28T17:00:00"),
                   ("bel/call.pdf", "BEL", "transcript", "2025-11-04", "2025-11-04T17:57:09"),
                   ("ports/deck.pdf", "ADANIPORTS", "deck", "2026-05-01", "2026-05-01T17:00:00")],
                  chola + bel + ports, [])
    guidance.run(str(path), ["CHOLAFIN", "BEL", "ADANIPORTS"])
    got = rows(path)
    assert not [r for r in got if r["symbol"] == "CHOLAFIN"], got
    assert not [r for r in got if r["metric"] == "order_intake" and r["low"] == 27000], got
    ports_rows = [r for r in got if r["symbol"] == "ADANIPORTS"]
    assert [r for r in ports_rows if r["metric"] == "revenue" and (r["low"], r["high"]) == (36000, 38000)], got
    assert [r for r in ports_rows if r["metric"] == "ebitda" and (r["low"], r["high"]) == (21000, 22000)], got
    assert not [r for r in ports_rows if r["metric"] == "capex"
                and (r["low"], r["high"]) in ((36000, 38000), (21000, 22000))], got
