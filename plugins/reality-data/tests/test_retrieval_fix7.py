"""T-242 retrieval fix 7: the company's own figure first (an industry / country / peer / customer figure is never the
answer), the asked period and unit family decide a number, a component's margin is not the company's, a paraphrased
question reaches the call's own sentence, guidance elects the group's full-year target over a WOS approval, and a
stem-only match never earns the rare ask word's weight (fix 7b).

    python -m pytest -q plugins/reality-data/tests/test_retrieval_fix7.py

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
CALL, FILED = "2026-11-03", "2026-11-10"          # printed call date vs filing date
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
    db = tmp_root / f"t242_fix7_{uuid4().hex}.db"
    c = sqlite3.connect(db)
    schema.create(c, list(schema.TABLES))
    c.executescript(kpi_mod.SCHEMA + transcripts.SCHEMA)
    c.execute(schema.FTS)
    c.execute(f"CREATE TABLE obs_fact ({OBS_COLUMNS})")
    c.execute("INSERT INTO company VALUES (?,?,NULL,NULL,'t','532714','Test Company Limited')",
              (SYM, ISIN))
    c.executemany(f"INSERT INTO doc VALUES ({','.join('?' * 12)})", [
        (CALL_DOC, SYM, ISIN, "transcript", "transcript", "Transcript of call held on 3 November 2026",
         FILED, f"{FILED}T12:00:00", 20, None, "sandbox", "nov"),
        (DECK_DOC, SYM, ISIN, "deck", "deck", "Investor Presentation", "2026-11-12",
         "2026-11-12T12:00:00", 8, None, "sandbox", "deck")])
    c.commit()

    def add(table: str, **kw) -> None:
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        kept = {k: v for k, v in kw.items() if k in cols}
        c.execute(f"INSERT INTO {table} ({','.join(kept)}) VALUES ({','.join(['?'] * len(kept))})",
                  list(kept.values()))

    # 1. the company's own figure beside another scope's: the industry capex is larger and also verified
    add("obs_fact", symbol=SYM, measure="capex", record_type="number", status="verified", period="Q2 FY27",
        period_kind="actual", entity_scope="company", value=252.7, unit="Crore", scale=1.0, doc_type="deck",
        doc_key=DECK_DOC, page=12, known_at="2026-11-12T12:00:00", observation_id=1)
    add("obs_fact", symbol=SYM, measure="capex", record_type="number", status="verified", period="Q2 FY27",
        period_kind="actual", entity_scope="industry", value=11887.0, unit="Crore", scale=1.0, doc_type="deck",
        doc_key=DECK_DOC, page=12, known_at="2026-11-12T12:00:00", observation_id=2)
    # a period that holds ONLY a country figure: it is held, so it is shown -- in alternatives, labelled
    add("obs_fact", symbol=SYM, measure="capex", record_type="number", status="verified", period="FY26",
        period_kind="actual", entity_scope="country", value=999.0, unit="Crore", scale=1.0, doc_type="deck",
        doc_key=DECK_DOC, page=13, known_at="2026-11-12T12:00:00", observation_id=8)
    # 2. AUM is money: the deck also prints the AUM growth percentage as an aum.value row
    add("obs_fact", symbol=SYM, measure="aum.value", record_type="number", status="verified", period="Q2 FY27",
        period_kind="actual", entity_scope="company", value=108377.0, unit="Rs. Crores", scale=1.0, doc_type="deck",
        doc_key=DECK_DOC, page=6, known_at="2026-11-12T12:00:00", observation_id=3)
    add("obs_fact", symbol=SYM, measure="aum.value", record_type="number", status="verified", period="Q2 FY27",
        period_kind="actual", entity_scope="company", value=18.4, unit="%", scale=1.0, doc_type="deck",
        doc_key=DECK_DOC, page=6, known_at="2026-11-12T12:00:00", observation_id=4)
    # 3. the ethanol-division slide's margin beside the company's own 7%
    add("obs_fact", symbol=SYM, measure="ebitda_margin", record_type="number", status="verified", period="Q2FY27",
        period_kind="actual", entity_scope="company", value=7.0, unit="%", scale=1.0, doc_type="deck",
        series_title="FINANCIAL HIGHLIGHTS (Q2FY27)", group_path="", doc_key=DECK_DOC, page=6,
        known_at="2026-11-12T12:00:00", observation_id=5)
    add("obs_fact", symbol=SYM, measure="ebitda_margin", record_type="number", status="verified", period="Q2FY27",
        period_kind="actual", entity_scope="company", value=2.0, unit="%", scale=1.0, doc_type="deck",
        series_title="Q2FY27 Highlights from Sale of Ethanol", group_path="Q2FY27 Highlights from Sale of Ethanol",
        doc_key=DECK_DOC, page=40, known_at="2026-11-12T12:00:00", observation_id=6)
    # 4. a paraphrase: the asked sentence never carries the question's own words
    for i, quote in enumerate(["Margins held at the guided level this quarter.",
                               "The online channel grew strongly in the quarter."], 1):
        add("transcript_statement", symbol=SYM, doc_key=CALL_DOC, call_date=CALL, call_period="Q2FY27", page=4,
            speaker="Filler", role="cfo", section="qa", topics="capex", quote=quote, statement=quote,
            is_fragment=0, answer_turn=i, seq=i, known_at=f"{FILED}T12:00:00", entities="",
            period_discussed="Q2FY27", numbers_json="[]", extractor_rule="t")
    asked = ("And during FY27, we estimate to spend around INR1,700 crores towards our capex project with major "
             "outlay towards the new energy business of around INR1,300 crores.")
    add("transcript_statement", symbol=SYM, doc_key=CALL_DOC, call_date=CALL, call_period="Q2FY27", page=4,
        speaker="CEOs", role="ceo", section="qa", topics="capex", quote=asked, statement=asked,
        is_fragment=0, answer_turn=9, seq=9, known_at=f"{FILED}T12:00:00", entities="",
        period_discussed="Q2FY27", numbers_json="[]", extractor_rule="t")
    # 5. guidance: a newer WOS board approval and the call's own group estimate for the same year
    c.execute("INSERT INTO guidance (id, symbol, isin, metric, target_period, low, high, unit, direction, said_on, "
              "doc_key, page, quote, speaker, known_at, revision_of, extractor_rule) VALUES "
              "(1,?,?, 'capex','FY27',1700.0,1700.0,'inr_cr','flat','2026-08-14',?,4,"
              "'And during FY27, we estimate to spend around INR1,700 crores towards our capex project.','CFO',"
              "?,NULL,'t')", (SYM, ISIN, CALL_DOC, "2026-08-14T12:00:00"))
    c.execute("INSERT INTO guidance (id, symbol, isin, metric, target_period, low, high, unit, direction, said_on, "
              "doc_key, page, quote, speaker, known_at, revision_of, extractor_rule) VALUES "
              "(2,?,?, 'capex','FY27',2320.0,2320.0,'inr_cr','flat','2026-11-02',?,1,"
              "'Noted the Capex approvals granted by Board of Test Advanced Cell Technologies Limited (ARACT) the "
              "Company''s Wholly Owned Subsidiary (WOS).','CFO',?,NULL,'t')",
              (SYM, ISIN, CALL_DOC, "2026-11-02T12:00:00"))
    # 6. a guidance observation whose measure is only a placeholder
    add("obs_fact", symbol=SYM, measure="NEW:<revenue_or_ebitda_growth_expectation>", record_type="guidance",
        status="unverified", period="FY27", value=35.0, value_high=40.0, unit="%", scale=1.0, doc_type="transcript",
        doc_key=CALL_DOC, page=5, statement="Minimum, I observe the rise of 35% to 40% as per the last year.",
        known_at=f"{FILED}T12:00:00", observation_id=7)
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


def test_the_company_figure_is_served_before_an_industry_figure(store: Path) -> None:
    reply = p3.fact(SYM, "capex", period="Q2 FY27")
    assert reply["found"], reply
    assert reply["answer"]["value"] == 252.7, reply["answer"]
    alts = reply.get("alternatives") or []
    assert any(alt.get("value") == 11887.0 and alt.get("scope") == "industry figure" for alt in alts), alts


def test_a_lone_industry_figure_is_an_alternative_never_the_answer(store: Path) -> None:
    # FY26 holds only a country figure: it is held, so it comes back labelled in alternatives, never as the answer
    reply = p3.fact(SYM, "capex", period="FY26")
    assert reply["found"] is False, reply
    alts = reply.get("alternatives") or []
    assert any(alt.get("value") == 999.0 and alt.get("scope") == "country figure" for alt in alts), alts


def test_aum_serves_money_not_the_growth_percentage(store: Path) -> None:
    reply = p3.fact(SYM, "AUM", period="Q2 FY27")
    assert reply["found"], reply
    assert reply["answer"]["value"] == 108377.0, reply["answer"]
    assert "crore" in str(reply["answer"]["unit"]).lower(), reply["answer"]


def test_a_component_scope_margin_is_demoted_below_the_company_figure(store: Path) -> None:
    reply = p3.fact(SYM, "EBITDA margin", period="Q2 FY27")
    assert reply["found"], reply
    assert reply["answer"]["value"] == 7.0, reply["answer"]
    alts = reply.get("alternatives") or []
    assert any(alt.get("value") == 2.0 for alt in alts), alts


def test_a_paraphrased_capex_ask_reaches_the_call_sentence(store: Path) -> None:
    reply = p3.statements(SYM, topic="capex", date_from=CALL, date_to=CALL,
                          rank_terms="How much will they invest this year and where?")
    assert reply["found"], reply
    first = str(reply["rows"][0].get("quote") or "")
    assert "we estimate to spend around INR1,700 crores" in first, first


def test_guidance_elects_the_groups_year_target_over_a_wos_approval(store: Path) -> None:
    reply = p3.guidance(SYM, "capex", "FY27")
    assert reply["found"], reply
    assert reply["rows"][0]["low"] == 1700.0, reply["rows"][0]
    alts = reply.get("alternatives") or []
    assert any(alt.get("low") == 2320.0 and "component" in str(alt.get("why_not_preferred")) for alt in alts), alts


def test_an_obs_guidance_placeholder_measure_is_served(store: Path) -> None:
    reply = p3.guidance(SYM, "revenue growth", "FY27")
    assert reply["found"], reply
    answer = reply["rows"][0]
    assert answer["source"] == "obs_fact", answer
    assert (answer["low"], answer["high"]) == (35.0, 40.0), answer


def test_a_stem_match_never_earns_the_rare_word_weight() -> None:
    # T-242 fix 7b: "running" is printed once in the reply, so it weighs 1.5 -- but only in a sentence that prints
    # the word itself.  "run at full gallop" is a stem match and must not outrank "running at full capacity".
    weights = {"running": 1.5, "full": 1.0}
    exact = p3._sentence_hits("We are running at full capacity today.", ["running", "full"], weights=weights)[1]
    stem = p3._sentence_hits("We run at full gallop today.", ["running", "full"], weights=weights)[1]
    assert exact == 3.0, exact
    assert stem == 2.5, stem
