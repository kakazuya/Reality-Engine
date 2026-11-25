"""T-242 retrieval fix 6: held guidance is reported (quarantine is never "not in data", and obs_fact guidance is
served), "profit after tax" and a printed point-in-time period resolve like "PAT" and "Q2 FY27", a transcript number
a filing contradicts by >20% is served filed-first with ``conflict: true``, the sentence carrying every ask word
ranks first inside a named call, and each row shows the printed call date and the filing date.

    python -m pytest -q plugins/reality-data/tests/test_retrieval_fix6.py

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
CALL, FILED = "2026-11-03", "2026-11-10"          # printed call date vs filing date, 7 days apart
CALL_DOC, Q4_DOC, DECK_DOC = "calls/nov.pdf", "results/q4.pdf", "decks/nov.pdf"
ASKED = "The gross margin expansion came from a better channel mix and we expect it to hold."
SPLIT = "Gross margin improved this quarter. Expansion is guided for the next year."


@pytest.fixture(scope="module")
def store() -> Iterator[Path]:
    tmp_root = ROOT / ".tmp"
    tmp_root.mkdir(exist_ok=True)
    db = tmp_root / f"t242_fix6_{uuid4().hex}.db"
    c = sqlite3.connect(db)
    schema.create(c, list(schema.TABLES))
    c.executescript(kpi_mod.SCHEMA + transcripts.SCHEMA)
    c.execute(schema.FTS)
    c.execute("CREATE TABLE obs_fact (observation_id INTEGER, symbol TEXT, measure TEXT, record_type TEXT, "
              "status TEXT, period TEXT, period_source TEXT, basis TEXT, basis_source TEXT, printed_label TEXT, "
              "statement TEXT, speaker TEXT, direction TEXT, question_context TEXT, segment TEXT, geography TEXT, "
              "customer TEXT, entity_scope TEXT, series_title TEXT, value REAL, value_high REAL, unit TEXT, "
              "scale REAL, doc_key TEXT, page INTEGER, source TEXT, doc_type TEXT, known_at TEXT, "
              "check_status TEXT, checker TEXT, check_evidence TEXT, check_fields TEXT)")
    c.execute("CREATE TABLE row_check (tbl TEXT, row_id INTEGER, symbol TEXT, metric TEXT, canon TEXT, "
              "sector TEXT, doc_type TEXT, rule TEXT, status TEXT, corroborated INTEGER, checker TEXT)")
    c.execute("CREATE TABLE row_check_fail (tbl TEXT, row_id INTEGER, check_name TEXT, hard INTEGER, why TEXT)")
    c.execute("INSERT INTO company VALUES (?,?,NULL,NULL,'t','532714','Test Company Limited')", (SYM, ISIN))
    c.executemany(f"INSERT INTO doc VALUES ({','.join('?' * 12)})", [
        (CALL_DOC, SYM, ISIN, "transcript", "transcript", "Transcript of call held on 3 November 2026",
         FILED, f"{FILED}T12:00:00", 20, None, "sandbox", "nov"),
        (Q4_DOC, SYM, ISIN, "results", "results", "Q4 FY26 results", "2026-04-30",
         "2026-04-30T12:00:00", 24, None, "sandbox", "q4"),
        (DECK_DOC, SYM, ISIN, "deck", "deck", "Investor Presentation", "2026-11-12",
         "2026-11-12T12:00:00", 8, None, "sandbox", "deck")])
    c.commit()

    def add(table: str, **kw) -> None:
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        kept = {k: v for k, v in kw.items() if k in cols}
        c.execute(f"INSERT INTO {table} ({','.join(kept)}) VALUES ({','.join(['?'] * len(kept))})",
                  list(kept.values()))

    # statements of ONE call: three fillers first by the old order, then the asked sentence, then a sentence whose
    # ask words sit in different sentences (never an all-word match)
    fillers = ["Margins held at the guided level this quarter.",
               "We saw healthy demand across the portfolio.",
               "The online channel grew strongly in the quarter."]
    for i, quote in enumerate(fillers, 1):
        add("transcript_statement", symbol=SYM, doc_key=CALL_DOC, call_date=CALL, call_period="Q2FY27", page=4,
            speaker="Filler Speaker", role="cfo", section="qa", topics="margin", quote=quote, statement=quote,
            is_fragment=0, answer_turn=i, seq=i, known_at=f"{FILED}T12:00:00", entities="",
            period_discussed="Q2FY27", numbers_json="[]", extractor_rule="t")
    add("transcript_statement", symbol=SYM, doc_key=CALL_DOC, call_date=CALL, call_period="Q2FY27", page=4,
        speaker="Asked Speaker", role="ceo", section="qa", topics="margin", quote=ASKED, statement=ASKED,
        is_fragment=0, answer_turn=9, seq=9, known_at=f"{FILED}T12:00:00", entities="",
        period_discussed="Q2FY27", numbers_json="[]", extractor_rule="t")
    add("transcript_statement", symbol=SYM, doc_key=CALL_DOC, call_date=CALL, call_period="Q2FY27", page=5,
        speaker="Split Speaker", role="cfo", section="qa", topics="margin", quote=SPLIT, statement=SPLIT,
        is_fragment=0, answer_turn=10, seq=10, known_at=f"{FILED}T12:00:00", entities="",
        period_discussed="Q2FY27", numbers_json="[]", extractor_rule="t")
    # the same call's obs_fact statement (the row that shows the filing date beside the printed call date)
    add("obs_fact", symbol=SYM, measure="margin", record_type="statement", status="verified", doc_type="transcript",
        doc_key=CALL_DOC, page=4, speaker="Asked Speaker", statement="Margins were steady on a better mix.",
        known_at=f"{FILED}T12:00:00", observation_id=1)

    # C1: a target held only in obs_fact (no target period printed) and one the checker quarantined
    add("obs_fact", symbol=SYM, measure="NEW:<motor_loss_ratio>", record_type="guidance", status="unverified",
        period="", value=65.0, value_high=67.0, unit="%", doc_type="transcript", doc_key=CALL_DOC, page=15,
        statement="And the range that we have always spoken is to kind of see the book running at between 65% to "
                  "67%.", known_at=f"{FILED}T12:00:00", observation_id=2)
    c.execute("INSERT INTO guidance (id, symbol, isin, metric, target_period, low, high, unit, direction, said_on, "
              "doc_key, page, quote, speaker, known_at, revision_of, extractor_rule) VALUES "
              "(1,?,?, 'opex_to_nti','FY27',3.0,3.1,'pct','flat','2026-11-04',?,12,"
              "'Opex continues to remain in the range of 3.0% to 3.1%.','CFO',?,NULL,'t')",
              (SYM, ISIN, CALL_DOC, f"{FILED}T12:00:00"))
    c.execute("INSERT INTO row_check VALUES ('guidance',1,?, 'opex_to_nti','', '', 'transcript','r','quarantined',0,'c')",
              (SYM,))

    # C2: "profit after tax" must resolve to the filed "pat" line
    add("fin_quarter_xbrl", symbol=SYM, isin=ISIN, period_start="2026-07-01", period_end="2026-09-30",
        fiscal_period="Q2FY27", basis="consolidated", audited="a", statement="PL", line_item="pat", xbrl_tag="Tag",
        value=1_630_340_000.0, unit="inr", scale=1.0, source_file="q.xml", source_db="results_xbrl.db",
        source_table="quarterly", source_rowid="q.xml", known_at="2026-10-28T10:00:00", known_at_source="x",
        is_reported=1)
    # C2: a printed point-in-time label, resolved through its own date
    add("obs_fact", symbol=SYM, measure="capacity.total", record_type="number", status="verified",
        period="As on 30th Sept, 2026", printed_label="Installed Capacity", value=156950.0, unit="MTPA",
        scale=1.0, doc_type="deck", doc_key=DECK_DOC, page=8, known_at="2026-11-12T12:00:00", observation_id=3)

    # W: the call remark says 44.3 crore for Q4FY26, the filed results print 10.8 crore for the same measure
    add("obs_fact", symbol=SYM, measure="pat", record_type="number", status="verified", period="Q4FY26",
        value=44.3, unit="INR crore", scale=1.0, doc_type="transcript", doc_key=CALL_DOC, page=4,
        known_at="2026-05-08T12:00:00", observation_id=4)
    add("obs_fact", symbol=SYM, measure="pat", record_type="number", status="unverified", period="Q4FY26",
        value=10.8, unit="Rs. Crore", scale=1.0, doc_type="results", doc_key=Q4_DOC, page=2,
        known_at="2026-04-30T12:00:00", observation_id=5)
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


def _quotes(reply: dict) -> list[str]:
    return [str(row.get("quote") or "") for row in reply.get("rows") or []]


def test_a_quarantined_guidance_row_is_reported_not_absent(store: Path) -> None:
    reply = p3.guidance(SYM, "opex to net total income", period="FY27")
    assert reply["found"] is False, reply
    held = reply.get("held_quarantined") or []
    assert any("opex_to_nti" in line and "quarantined" in line for line in held), held
    assert any("3-3.1" in line or "3.0-3.1" in line for line in held), held
    # include_quarantined=true still serves the row itself
    served = p3.guidance(SYM, "opex to net total income", period="FY27", include_quarantined=True)
    assert served["found"] and served["rows"][0]["low"] == 3.0, served


def test_guidance_held_only_in_obs_fact_is_served(store: Path) -> None:
    reply = p3.guidance(SYM, "motor loss ratio", period="FY27")
    assert reply["found"], reply
    row = reply["rows"][0]
    assert row["source"] == "obs_fact", row
    assert (row["low"], row["high"], row["unit"]) == (65.0, 67.0, "%"), row
    assert row["period"] == "FY27", row


def test_profit_after_tax_resolves_like_pat(store: Path) -> None:
    reply = p3.fact(SYM, "profit after tax", period="Q2 FY27")
    assert reply["found"], reply
    assert reply["route"] == "fin", reply
    assert reply["answer"]["value"] == 1_630_340_000.0, reply


def test_printed_as_on_period_matches_the_point_in_time_row(store: Path) -> None:
    reply = p3.fact(SYM, "installed capacity", period="As on 30th Sept, 2026")
    assert reply["found"], reply
    assert reply["answer"]["value"] == 156950.0, reply
    assert reply["answer"]["unit"] == "MTPA", reply
    assert "2026" in str(reply["answer"]["period"]), reply


def test_a_filed_value_that_contradicts_a_call_remark_is_served_first(store: Path) -> None:
    reply = p3.fact(SYM, "profit after tax", period="Q4 FY26")
    assert reply["found"], reply
    assert reply["answer"]["value"] == 10.8, reply
    conflicts = [alt for alt in reply.get("alternatives") or [] if alt.get("conflict") is True]
    assert conflicts, reply.get("alternatives")
    assert conflicts[0]["value"] == 44.3, conflicts
    assert "call remark" in reply["why_this_one"], reply["why_this_one"]


def test_the_sentence_carrying_every_ask_word_ranks_first(store: Path) -> None:
    reply = p3.statements(SYM, topic="gross margin expansion", date_from=CALL, date_to=CALL)
    assert reply["found"], reply
    first = str(reply["rows"][0].get("quote") or "").lower()
    for word in ("gross", "margin", "expansion"):
        assert word in first, (word, first)
    assert reply["rows"][0]["quote"].startswith("The gross margin expansion"), reply["rows"][0]
    # the sentence that splits the words across sentences is still served, just never as the all-word match
    assert any("Expansion is guided" in quote for quote in _quotes(reply)), _quotes(reply)


def test_each_named_call_row_shows_the_printed_call_date_and_the_filing_date(store: Path) -> None:
    reply = p3.statements(SYM, topic="gross margin expansion", date_from=CALL, date_to=CALL)
    rows = reply.get("rows") or []
    printed = [row for row in rows if row.get("match") == "tag"]
    assert printed and printed[0].get("call_date") == CALL, printed[:1]
    assert printed[0].get("filed") == FILED, printed[0]
    obs = [row for row in rows if row.get("match") == "obs"]
    assert obs, rows
    assert obs[0].get("call_date") == FILED, obs[0]
    assert obs[0].get("call_date_printed") == CALL, obs[0]
