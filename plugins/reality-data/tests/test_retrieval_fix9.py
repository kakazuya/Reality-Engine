"""T-242 retrieval fix 9: the row the page itself supports is elected (a superseded target loses to the upgraded
sibling, a value its own quote cannot reproduce is never first, another entity's target is never the company's, a
looser growth sibling loses to the measured one); a named call serves up to three sentences of one turn; the
spelled-out metric names resolve.

    python -m pytest -q plugins/reality-data/tests/test_retrieval_fix9.py

Written as pytest functions on purpose: ``python -m unittest`` does not collect them.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]
SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SERVER_DIR))

import lookups_pilot3 as p3  # noqa: E402
from reality_engine.pilot3 import kpi as kpi_mod, schema, transcripts  # noqa: E402

SYM = "TST"
ISIN = "INE000000001"
CALL, FILED = "2026-11-04", "2026-11-12"          # printed call date vs filing date
CALL_DOC, DECK_DOC = "calls/nov.pdf", "decks\\nov.pdf"
OBS_COLUMNS = (
    "observation_id INTEGER, symbol TEXT, measure TEXT, record_type TEXT, status TEXT, period TEXT, period_kind TEXT, "
    "period_source TEXT, basis TEXT, basis_source TEXT, printed_label TEXT, statement TEXT, speaker TEXT, "
    "direction TEXT, question_context TEXT, segment TEXT, product TEXT, plant TEXT, geography TEXT, customer TEXT, "
    "group_path TEXT, entity_scope TEXT, series_title TEXT, value REAL, value_high REAL, unit TEXT, scale REAL, "
    "doc_key TEXT, page INTEGER, source TEXT, doc_type TEXT, known_at TEXT, check_status TEXT, checker TEXT, "
    "check_evidence TEXT, check_fields TEXT")


@pytest.fixture(scope="module")
def store() -> Iterator[Path]:
    tmp_root = ROOT / ".tmp"
    tmp_root.mkdir(exist_ok=True)
    db = tmp_root / f"t242_fix9_{uuid4().hex}.db"
    c = sqlite3.connect(db)
    schema.create(c, list(schema.TABLES))
    c.executescript(kpi_mod.SCHEMA + transcripts.SCHEMA)
    c.execute(schema.FTS)
    c.execute(f"CREATE TABLE obs_fact ({OBS_COLUMNS})")
    c.execute("INSERT INTO company VALUES (?,?,NULL,NULL,'t','532714','Test Company Limited')", (SYM, ISIN))
    c.executemany(f"INSERT INTO doc VALUES ({','.join('?' * 12)})", [
        (CALL_DOC, SYM, ISIN, "transcript", "transcript", "Transcript of call held on 4 November 2026",
         FILED, f"{FILED}T12:00:00", 20, None, "sandbox", "nov"),
        (DECK_DOC, SYM, ISIN, "deck", "deck", "Investor Presentation", "2026-10-29",
         "2026-10-29T12:00:00", 8, None, "sandbox", "deck")])
    c.execute(f"INSERT INTO doc_page VALUES ({','.join('?' * 8)})",
              (CALL_DOC, SYM, 5, "Other expenses were discussed on the call.", "script_text", 54,
               f"{FILED}T12:00:00", None))
    c.commit()
    c.execute("INSERT INTO doc_page_fts(rowid, text) SELECT rowid, text FROM doc_page")

    def add(table: str, **kw) -> int:
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        kept = {k: v for k, v in kw.items() if k in cols}
        cur = c.execute(f"INSERT INTO {table} ({','.join(kept)}) VALUES ({','.join(['?'] * len(kept))})",
                        list(kept.values()))
        return int(cur.lastrowid or 0)

    # 1. two FY27 revenue targets in ONE call: the page says the 12-14% is the previously communicated guidance it
    #    is exceeding, and the 15-17% is the upgraded one ("Hotel segment" later in the same sentence is not the ask)
    add("guidance", symbol=SYM, isin=ISIN, metric="revenue_growth", target_period="FY27", low=12.0, high=14.0,
        unit="pct", direction="up", said_on=CALL, doc_key=CALL_DOC, page=3,
        quote="we are confident of exceeding our previously communicated FY27 consolidated revenue growth guidance "
              "of 12% to 14% by 300 basis points.", speaker="MD", known_at=f"{FILED}T12:00:00", extractor_rule="t")
    add("guidance", symbol=SYM, isin=ISIN, metric="revenue_growth", target_period="FY27", low=15.0, high=17.0,
        unit="pct", direction="up", said_on=CALL, doc_key=CALL_DOC, page=6,
        quote="we remain confident of delivering on our upgraded guidance of 15% to 17% revenue growth for FY27 with "
              "Hotel segment growing from 17% to 19%.", speaker="MD", known_at=f"{FILED}T12:00:00", extractor_rule="t")
    # 2. an AUM-growth remark about disbursement growth (its quote never prints AUM) beside the real target
    add("guidance", symbol=SYM, isin=ISIN, metric="aum_growth", target_period="FY27", low=22.0, high=22.0,
        unit="pct", direction="up", said_on=CALL, doc_key=CALL_DOC, page=14,
        quote="the disbursement for this quarter and growth of roughly 22% is highly encouraging for us and helps "
              "us more confidently move towards our guidance range of growth that we talked about.",
        speaker="MD", known_at=f"{FILED}T12:00:00", extractor_rule="t")
    add("guidance", symbol=SYM, isin=ISIN, metric="aum_growth", target_period="FY27", low=25.0, high=30.0,
        unit="pct", direction="up", said_on=CALL, doc_key=CALL_DOC, page=6,
        quote="We are targeting an AUM growth, as we had said in the guidance, between 25% to 30% for this year.",
        speaker="MD", known_at=f"{FILED}T12:00:00", extractor_rule="t")
    # 3. a target the quote itself gives to another entity, stored with an empty entity column
    add("guidance", symbol=SYM, isin=ISIN, metric="ebitda_margin", target_period="FY27", low=25.0, high=25.0,
        unit="pct", direction="flat", said_on="2026-05-14", doc_key=CALL_DOC, page=7,
        quote="Operating EBITDA margin at 25% for the year was in line with Syngene's revised full year guidance.",
        speaker=None, known_at="2026-05-14T12:00:00", extractor_rule="t")
    # 4. the same AUM value restated by two filings: the deck card prints "INR 7,597" and the store holds 75.97 crore
    add("kpi_series", symbol=SYM, metric="aum", dimension="total", value=75.97, unit="inr_cr", scale=1e7,
        period_type="Q", fiscal_period="Q2FY27", basis="not_stated", doc_key=DECK_DOC, page=17,
        quote="AUM Sep-26\nINR 7,597", known_at="2026-10-29T12:00:00", raw_label="AUM", extractor_rule="t")
    add("kpi_series", symbol=SYM, metric="aum", dimension="total", value=7597.0, unit="inr_cr", scale=1e7,
        period_type="Q", fiscal_period="Q2FY27", basis="not_stated", doc_key=CALL_DOC, page=3,
        quote="assets under management stood at INR7,597 crores", known_at=f"{FILED}T12:00:00",
        raw_label="AUM", extractor_rule="t")
    # 5. the spelled-out ratio names the store files under its short code
    add("ratio_panel", symbol=SYM, isin=ISIN, fiscal_period="Q2FY27", period_type="Q", basis="standalone",
        metric="roe", value=18.1, unit="pct", scale=1.0, known_at=f"{FILED}T12:00:00", known_at_source="t")
    add("fin_quarter_xbrl", symbol=SYM, isin=ISIN, fiscal_period="Q2FY27", basis="consolidated", line_item="eps_basic",
        value=26.76, unit="inr_per_share", scale=1.0, known_at=f"{FILED}T12:00:00", known_at_source="t")
    # 6. one answer turn, two sentences: the asked one is the paragraph's LAST sentence (obs_fact holds the whole
    #    paragraph, so the old 600-character cut and one-sentence-per-turn both dropped it)
    add("transcript_statement", symbol=SYM, doc_key=CALL_DOC, call_date=CALL, call_period="Q2FY27", page=5,
        speaker="CFO", role="cfo", section="prepared", topics="cost",
        quote="Employee expenses were INR39.2 crores compared with INR30.8 crores in H1 FY26.",
        statement="Employee expenses were INR39.2 crores compared with INR30.8 crores in H1 FY26.",
        is_fragment=0, answer_turn=-4, seq=1, known_at=f"{FILED}T12:00:00", entities="",
        period_discussed="Q2FY27", numbers_json="[]", extractor_rule="t")
    add("obs_fact", symbol=SYM, measure="NEW:expenses_and_finance_costs", record_type="statement",
        status="unverified", period="", statement="On expenses front, expenses and finance costs were INR43 crores. "
        "Employee expenses were INR39.2 crores compared with INR30.8 crores in H1 FY26. Other expenses were INR25 "
        "crores compared to INR18.3 crores.", speaker="CFO", doc_key=CALL_DOC, page=5, doc_type="transcript",
        known_at=f"{FILED}T12:00:00", observation_id=1)
    c.commit()
    c.close()
    old = os.environ.get("REALITY_PILOT3_DB")
    os.environ["REALITY_PILOT3_DB"] = str(db)
    p3.reset_store()
    yield db
    p3.close()
    p3.reset_store()
    if old is None:
        os.environ.pop("REALITY_PILOT3_DB", None)
    else:
        os.environ["REALITY_PILOT3_DB"] = old
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)


# --- C1a: the superseded sibling -------------------------------------------------------------------
def test_a_previous_guidance_loses_to_the_upgraded_sibling(store: Path) -> None:
    reply = p3.guidance(SYM, "revenue growth", "FY27")
    assert reply["found"], reply
    assert (reply["rows"][0]["low"], reply["rows"][0]["high"]) == (15.0, 17.0), reply["rows"][0]
    alts = reply.get("alternatives") or []
    assert any(alt["low"] == 12.0 and "previously communicated" in str(alt["why_not_preferred"]) for alt in alts), alts


def test_an_upgraded_sentence_beats_a_component_word_in_the_same_quote(store: Path) -> None:
    # the 15-17% quote says "Hotel segment growing" later in the sentence: the upgraded phrase marks it the company's
    reply = p3.guidance(SYM, "revenue growth", "FY27")
    assert reply["found"] and reply["rows"][0]["high"] == 17.0, reply["rows"][:2]


# --- C1b: the digits the quote prints ---------------------------------------------------------------
def test_a_value_its_own_quote_cannot_reproduce_is_never_elected_first(store: Path) -> None:
    reply = p3.kpi(SYM, "AUM", "Q2FY27")
    assert reply["found"], reply
    assert reply["rows"][0]["value"] == 7597.0, reply["rows"][0]
    mismatched = [row for row in reply["rows"] if row.get("scale_mismatch")]
    assert mismatched and mismatched[0]["value"] == 75.97, reply["rows"]
    fact = p3.fact(SYM, "AUM", "Q2FY27")
    assert fact["found"] and fact["answer"]["value"] == 7597.0, fact


# --- C1c: another entity's target -------------------------------------------------------------------
def test_another_entitys_target_is_never_the_companys(store: Path) -> None:
    reply = p3.guidance(SYM, "EBITDA margin", "FY27")
    assert not any(row.get("low") == 25.0 for row in reply.get("rows") or []), reply["rows"]
    alts = reply.get("alternatives") or []
    assert any(str(alt.get("entity")) == "Syngene" and "another entity" in str(alt.get("why_not_preferred"))
               for alt in alts), alts


# --- C1d: the measure's own subject word ------------------------------------------------------------
def test_a_looser_growth_sibling_loses_to_the_measured_target(store: Path) -> None:
    reply = p3.guidance(SYM, "AUM growth", "FY27")
    assert reply["found"], reply
    assert (reply["rows"][0]["low"], reply["rows"][0]["high"]) == (25.0, 30.0), reply["rows"][0]
    alts = reply.get("alternatives") or []
    assert any(alt["low"] == 22.0 for alt in alts), alts


# --- C3: spelled-out metric names -------------------------------------------------------------------
def test_return_on_equity_resolves_like_roe(store: Path) -> None:
    reply = p3.fact(SYM, "return on equity", "Q2FY27")
    assert reply["found"], reply
    assert reply["answer"]["value"] == 18.1, reply["answer"]


def test_earnings_per_share_resolves_like_eps(store: Path) -> None:
    reply = p3.fact(SYM, "earnings per share", "Q2FY27")
    assert reply["found"], reply
    assert reply["answer"]["value"] == 26.76, reply["answer"]


def test_the_spelled_out_alias_map_covers_the_brief() -> None:
    assert p3._MEASURE_ALIASES["return_on_equity"] == "roe"
    assert p3._MEASURE_ALIASES["return_on_capital_employed"] == "roce"
    assert p3._MEASURE_ALIASES["return_on_assets"] == "roa"
    assert p3._MEASURE_ALIASES["earnings_per_share"] == "eps"
    assert p3._MEASURE_ALIASES["net_interest_margin"] == "nim"
    assert p3._MEASURE_ALIASES["gross_non_performing_assets"] == "gnpa"
    assert p3._MEASURE_ALIASES["assets_under_management"] == "aum"


# --- C2: a second sentence of one named-call turn ---------------------------------------------------
def test_the_second_sentence_of_one_turn_is_served(store: Path) -> None:
    reply = p3.statements(SYM, topic="cost", rank_terms="other expenses versus year ago",
                          date_from=CALL, date_to=CALL)
    assert reply["found"], reply
    first = str(reply["rows"][0].get("quote") or "")
    assert "Other expenses were INR25" in first, first
