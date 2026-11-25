"""T-242 retrieval fix 8: the paraphrase reaches the prepared-remark sentence, a quarantined KPI stays held and never
served (fix 8b), and a target its own page disclaims or calls an aspiration is never elected first; a money ask skips
allocation-share noise and "capital expenditure" reaches capex.

    python -m pytest -q plugins/reality-data/tests/test_retrieval_fix8.py

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

PREPARED = [
    ("prepared", -2, 3, "other", "So, there are a lot of partnerships that we have already done."),
    ("prepared", -2, 4, "revenue", "Revenue grew strongly this quarter."),
    ("prepared", -2, 5, "customer",
     "Customer inquiries remain robust, but large contracts are taking longer to conclude as clients evaluate "
     "technology choices."),
]


@pytest.fixture(scope="module")
def store() -> Iterator[Path]:
    tmp_root = ROOT / ".tmp"
    tmp_root.mkdir(exist_ok=True)
    db = tmp_root / f"t242_fix8_{uuid4().hex}.db"
    c = sqlite3.connect(db)
    schema.create(c, list(schema.TABLES))
    c.executescript(kpi_mod.SCHEMA + transcripts.SCHEMA)
    c.executescript(schema.ROW_CHECK_SCHEMA)
    c.execute(schema.FTS)
    c.execute(f"CREATE TABLE obs_fact ({OBS_COLUMNS})")
    c.execute("INSERT INTO company VALUES (?,?,NULL,NULL,'t','532714','Test Company Limited')", (SYM, ISIN))
    c.executemany(f"INSERT INTO doc VALUES ({','.join('?' * 12)})", [
        (CALL_DOC, SYM, ISIN, "transcript", "transcript", "Transcript of call held on 4 November 2026",
         FILED, f"{FILED}T12:00:00", 20, None, "sandbox", "nov"),
        (DECK_DOC, SYM, ISIN, "deck", "deck", "Investor Presentation", "2026-11-14",
         "2026-11-14T12:00:00", 8, None, "sandbox", "deck")])
    c.commit()

    def add(table: str, **kw) -> int:
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        kept = {k: v for k, v in kw.items() if k in cols}
        cur = c.execute(f"INSERT INTO {table} ({','.join(kept)}) VALUES ({','.join(['?'] * len(kept))})",
                        list(kept.values()))
        return int(cur.lastrowid or 0)

    # 1. a paraphrased ask: one prepared-remarks turn prints the asked sentence, not first in the turn
    for section, turn, seq, topics, quote in PREPARED:
        add("transcript_statement", symbol=SYM, doc_key=CALL_DOC, call_date=CALL, call_period="Q2FY27", page=4,
            speaker="Management", role="md", section=section, topics=topics, quote=quote, statement=quote,
            is_fragment=0, answer_turn=turn, seq=seq, known_at=f"{FILED}T12:00:00", entities="",
            period_discussed="Q2FY27", numbers_json="[]", extractor_rule="t")
    add("transcript_statement", symbol=SYM, doc_key=CALL_DOC, call_date=CALL, call_period="Q2FY27", page=6,
        speaker="Analyst", role="md", section="qa", topics="demand",
        quote="We see demand growing strongly across the business and the year looks good.",
        statement="We see demand growing strongly across the business and the year looks good.",
        is_fragment=0, answer_turn=8, seq=100, known_at=f"{FILED}T12:00:00", entities="",
        period_discussed="Q2FY27", numbers_json="[]", extractor_rule="t")
    # 2. "capital expenditure" reaches the row the store files as capex (audit 8: ALKEM AR p330)
    add("kpi_series", symbol=SYM, metric="capex", dimension="total", value=10360.0, unit="inr_mn", scale=1e6,
        period_type="actual", fiscal_period="FY26", basis="consolidated", doc_key=DECK_DOC, page=330,
        quote="capital expenditure of Rs 10,360 Million", known_at="2026-08-20T12:00:00", raw_label="capital expenditure",
        extractor_rule="t")
    # 3. a quarantined KPI whose page prints the value: held and disclosed, never served (fix 8b, standing ruling)
    add("kpi_series", symbol=SYM, metric="order intake", dimension="total", value=22.0, unit="inr_cr", scale=1.0,
        period_type="actual", fiscal_period="Q1FY27", basis="not_stated", doc_key=CALL_DOC, page=3,
        quote="Orders worth Rs.22 Crores", known_at=f"{FILED}T12:00:00", raw_label="order intake",
        extractor_rule="t")
    # 3b. beside a clean row of the same metric the quarantined one is never served
    add("kpi_series", symbol=SYM, metric="aum", dimension="total", value=100.0, unit="inr_cr", scale=1.0,
        period_type="actual", fiscal_period="Q2FY27", basis="consolidated", doc_key=DECK_DOC, page=6,
        quote="AUM 100 crore", known_at="2026-11-14T12:00:00", raw_label="AUM", extractor_rule="t")
    q_aum = add("kpi_series", symbol=SYM, metric="aum", dimension="total", value=999.0, unit="inr_cr", scale=1.0,
                period_type="actual", fiscal_period="Q2FY27", basis="standalone", doc_key=CALL_DOC, page=9,
                quote="AUM 999 crore", known_at=f"{FILED}T12:00:00", raw_label="AUM", extractor_rule="t")
    c.execute("INSERT INTO row_check (tbl, row_id, symbol, metric, status) VALUES ('kpi_series', ?, ?, 'order intake', "
              "'quarantined')", (c.execute("SELECT id FROM kpi_series WHERE metric='order intake'").fetchone()[0], SYM))
    c.execute("INSERT INTO row_check (tbl, row_id, symbol, metric, status) VALUES ('kpi_series', ?, ?, 'aum', "
              "'quarantined')", (q_aum, SYM))
    # 4. guidance: the newest target is an aspiration the page itself disclaims; a clear older one is the target
    c.execute("INSERT INTO guidance (id, symbol, isin, metric, target_period, low, high, unit, direction, said_on, "
              "doc_key, page, quote, speaker, known_at, revision_of, extractor_rule) VALUES "
              "(1,?,?, 'ebitda_margin','FY27',10.0,10.0,'pct','flat','2026-11-05',?,18,"
              "'In fact, it should be aspiring for 10% margin, but you compete in an open market.','MD',"
              "?,NULL,'t')", (SYM, ISIN, CALL_DOC, "2026-11-05T12:00:00"))
    c.execute("INSERT INTO guidance (id, symbol, isin, metric, target_period, low, high, unit, direction, said_on, "
              "doc_key, page, quote, speaker, known_at, revision_of, extractor_rule) VALUES "
              "(2,?,?, 'ebitda_margin','FY27',6.5,7.0,'pct','flat','2026-08-13',?,4,"
              "'We expect the full-year EBITDA margin to be 6.5% to 7%.','MD',"
              "?,NULL,'t')", (SYM, ISIN, CALL_DOC, "2026-08-13T12:00:00"))
    # 5. a money ask ("capex") must not be answered by allocation shares filed under a NEW: measure
    for i, pct in enumerate((5.0, 3.0, 8.0, 30.0, 41.0), 1):
        add("obs_fact", symbol=SYM, measure="NEW:capex_allocation_share", record_type="guidance", status="unverified",
            period="", value=pct, unit="%", scale=1.0, doc_type="deck", doc_key=DECK_DOC, page=17,
            statement="", known_at="2026-11-14T12:00:00", observation_id=100 + i)
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


def test_a_paraphrased_ask_reaches_the_prepared_remark_sentence(store: Path) -> None:
    # audit 8 Q04 ADSL: "large enterprise deals taking longer to close" must reach the prepared remark's
    # "large contracts are taking longer to conclude", which is not the turn's first sentence
    reply = p3.statements(SYM, topic="demand", date_from=CALL, date_to=CALL,
                          rank_terms="large enterprise deals taking longer to close")
    assert reply["found"], reply
    first = str(reply["rows"][0].get("quote") or "")
    assert "large contracts are taking longer to conclude" in first, first


def test_the_rarest_ask_word_weighs_most() -> None:
    items = [
        [{"quote": "Bokaro plant commissioned."}],
        [{"quote": "Capacity grew in the year."}],
        [{"quote": "Capacity grew again."}],
        [{"quote": "Capacity and year and demand."}],
    ]
    weights = p3._ask_weights(items, ["bokaro", "capacity", "year"])
    assert weights["bokaro"] == 2.5, weights
    assert weights["capacity"] < 2.0, weights


def test_capital_expenditure_reaches_the_capex_row(store: Path) -> None:
    reply = p3.fact(SYM, "capital expenditure", "FY26")
    assert reply["found"], reply
    assert reply["route"] == "kpi", reply
    assert reply["answer"]["value"] == 10360.0, reply["answer"]
    assert reply["answer"]["value_cr"] == 1036.0, reply["answer"]


def test_a_quarantined_kpi_is_held_and_never_served(store: Path) -> None:
    # fix 8b: Shivam's 8 Nov ruling is that a quarantined row is NEVER served.  The only match is quarantined, so
    # the reply is found=false with held_quarantined naming the period/dimension and the include_quarantined=true way.
    reply = p3.kpi(SYM, "order intake", "Q1FY27")
    assert reply["found"] is False, reply
    assert not reply["rows"], reply
    held = " ".join(reply.get("held_quarantined") or [])
    assert "Q1FY27" in held and "quarantined" in held and "include_quarantined=true" in held, reply
    shown = p3.kpi(SYM, "order intake", "Q1FY27", include_quarantined=True)
    assert shown["rows"][0]["value"] == 22.0 and shown["rows"][0]["check_status"] == "quarantined", shown["rows"][0]


def test_a_clean_kpi_row_is_never_preceded_by_a_quarantined_one(store: Path) -> None:
    reply = p3.kpi(SYM, "AUM", "Q2FY27")
    assert reply["found"], reply
    assert reply["rows"][0]["value"] == 100.0, reply["rows"][0]
    assert all(row.get("check_status") != "quarantined" for row in reply["rows"]), reply["rows"]


def test_a_disclaimed_target_is_never_elected_first(store: Path) -> None:
    # audit 8 Q18 BLUESTARCO: "aspiring for 10% margin" on the page that says "no guidance at the moment"
    reply = p3.guidance(SYM, "EBITDA margin", "FY27")
    assert reply["found"], reply
    assert reply["rows"][0]["low"] == 6.5, reply["rows"][0]
    alts = reply.get("alternatives") or []
    assert any(alt.get("low") == 10.0 and "disclaim" in str(alt.get("why_not_preferred")) for alt in alts), alts


def test_a_money_ask_skips_allocation_share_noise(store: Path) -> None:
    # audit 8 Q36 AZTEC: five NEW:capex_allocation_share percentages are not a capex target
    reply = p3.guidance(SYM, "capex")
    assert reply["found"] is False, reply
    assert not any("allocation" in str(row.get("metric") or "") for row in reply.get("rows") or []), reply
