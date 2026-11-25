"""T-242 retrieval fix 4: a named call serves only its own call (by the transcript's printed call date or the
document's filing date within 3 days), the 25-statement window arrives whole under the 19 kB reply cap, and a
share-capital line asked WITH a period elects the printed figure over the latest share count.

    python -m pytest -q plugins/reality-data/tests/test_retrieval_fix4.py

Written as pytest functions on purpose: ``python -m unittest`` does not collect them.
"""
from __future__ import annotations

import json
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
AUG, AUG_FILE = "2026-08-10", "2026-08-13"      # called 10 Aug, filed 13 Aug: the same call, 3 days apart
NOV = "2026-11-04"
AUG_DOC, NOV_DOC, DECK_DOC = "calls/aug.pdf", "calls/nov.pdf", "decks/mar.pdf"
ASKED = "Our margin expanded on operating leverage and we expect the margin to hold through the year."
NOVEMBER_ONLY = "NOVEMBER-ONLY remark: the November margin held at a different level."
FILLER = "The business held steady through the quarter on steady demand and stable operations. "


def _long_quote(asked: str) -> str:
    """A ~620-character remark with the asked words in the middle, so a 240-character trim must keep the match."""
    return FILLER * 4 + asked + " " + FILLER * 4


@pytest.fixture(scope="module")
def store() -> Iterator[Path]:
    tmp_root = ROOT / ".tmp"
    tmp_root.mkdir(exist_ok=True)
    db = tmp_root / f"t242_fix4_{uuid4().hex}.db"
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
        (AUG_DOC, SYM, ISIN, "transcript", "transcript", "Transcript of call held on 10 August 2026",
         AUG_FILE, f"{AUG_FILE}T12:00:00", 17, None, "sandbox", "aug"),
        (NOV_DOC, SYM, ISIN, "transcript", "transcript", "Transcript of call held on 4 November 2026",
         NOV, f"{NOV}T12:00:00", 20, None, "sandbox", "nov"),
        (DECK_DOC, SYM, ISIN, "deck", "deck", "Investor Presentation", "2026-05-20",
         "2026-05-20T17:00:00", 30, None, "sandbox", "mar")])
    c.commit()

    def add(table: str, **kw) -> None:
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        kept = {k: v for k, v in kw.items() if k in cols}
        c.execute(f"INSERT INTO {table} ({','.join(kept)}) VALUES ({','.join(['?'] * len(kept))})",
                  list(kept.values()))

    # 30 long remarks in the August call: the asked one first, and enough turns to fill a 25-statement window
    for i in range(1, 31):
        asked = f"{i:02d}" == "01"
        add("transcript_statement", symbol=SYM, doc_key=AUG_DOC, call_date=AUG, call_period="Q1FY27",
            page=3 + i % 8, speaker="August Speaker", role="cfo", section="qa", topics="margin",
            quote=_long_quote(ASKED if asked else f"August remark {i:02d}: the margin held at the guided level."),
            statement=_long_quote(ASKED if asked else f"August remark {i:02d}: the margin held at the guided level."),
            is_fragment=0, answer_turn=i, seq=i, known_at=f"{AUG_FILE}T12:00:00", entities="",
            period_discussed="Q1FY27", numbers_json="[]", extractor_rule="t")
    # 5 remarks in the November call, filed and printed 2026-11-04; a named August call must never serve them
    for i in range(1, 6):
        add("transcript_statement", symbol=SYM, doc_key=NOV_DOC, call_date=NOV, call_period="Q2FY27",
            page=4, speaker="November Speaker", role="ceo", section="qa", topics="margin",
            quote=NOVEMBER_ONLY if i == 1 else f"November remark {i:02d}: margin guidance for the year ahead.",
            statement=NOVEMBER_ONLY if i == 1 else f"November remark {i:02d}: margin guidance for the year ahead.",
            is_fragment=0, answer_turn=i, seq=i, known_at=f"{NOV}T12:00:00", entities="",
            period_discussed="Q2FY27", numbers_json="[]", extractor_rule="t")
    # the obs_fact source of both calls: rows of the November call must be dropped from the August reply too
    add("obs_fact", symbol=SYM, measure="margin", record_type="statement", status="verified", doc_type="transcript",
        doc_key=AUG_DOC, page=4, speaker="August Speaker", statement=ASKED,
        known_at=f"{AUG_FILE}T12:00:00", observation_id=1)
    add("obs_fact", symbol=SYM, measure="margin", record_type="statement", status="verified", doc_type="transcript",
        doc_key=NOV_DOC, page=4, speaker="November Speaker", statement=NOVEMBER_ONLY,
        known_at=f"{NOV}T12:00:00", observation_id=2)
    # the printed Share Capital line (Mar-25) and the newer share count: the period asked must elect the line
    add("obs_fact", symbol=SYM, measure="equity_share_capital", record_type="number", status="verified",
        period="Mar-25", printed_label="Share Capital", value=313.0, unit="Rs Mn", scale=1000000.0,
        doc_type="deck", doc_key=DECK_DOC, page=8, known_at="2026-05-20T17:00:00", observation_id=3)
    add("share_capital", symbol=SYM, isin=ISIN, as_of_date="2026-09-30", basis="standalone", event=None,
        shares_outstanding=31_250_000.0, paid_up_capital=312_500_000.0, face_value=10.0, unit="shares",
        scale=1.0, known_at="2026-10-13T19:57:01", known_at_source="test", source_db="test",
        source_table="quarterly", source_rowid="t1", count_basis="derived_from_capital")
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


def _reply_bytes(reply: dict) -> int:
    return len(json.dumps(reply, ensure_ascii=False, default=str).encode("utf-8"))


def test_named_call_drops_the_rows_of_every_other_call(store: Path) -> None:
    aug = p3.statements(SYM, topic="margin", date_from=AUG, date_to=AUG)
    assert aug["found"], aug
    quotes = _quotes(aug)
    assert any(ASKED in quote for quote in quotes), "the asked remark of the named call must still be served"
    assert all("NOVEMBER-ONLY" not in quote for quote in quotes), "a remark of the November call leaked in"
    outside = aug["coverage"].get("outside_date_filter") or []
    assert any(row["date"] == NOV and row["count"] >= 5 for row in outside), outside

    # the filing-date form of the same call (13 Aug, three days after the date printed) serves the August remarks
    filed = p3.statements(SYM, topic="margin", date_from=AUG_FILE, date_to=AUG_FILE)
    assert filed["found"], filed
    assert all("NOVEMBER-ONLY" not in quote for quote in _quotes(filed))

    # and the November call serves its own remark, never the August one
    nov = p3.statements(SYM, topic="margin", date_from=NOV, date_to=NOV)
    assert nov["found"], nov
    quotes = _quotes(nov)
    assert any("NOVEMBER-ONLY" in quote for quote in quotes), quotes
    assert all(ASKED not in quote for quote in quotes)


def test_named_call_serves_the_whole_25_row_window_under_the_reply_cap(store: Path) -> None:
    out = p3.statements(SYM, topic="margin", date_from=AUG, date_to=AUG)
    assert out["n"] == 25, (out["n"], out["coverage"])
    assert out["coverage"].get("rows_cut") is None, out["coverage"]
    assert _reply_bytes(out) < 19_000, _reply_bytes(out)
    # the quote is trimmed around the matched words, not from the front
    asked = next(row["quote"] for row in out["rows"] if "margin expanded" in row["quote"])
    assert "margin" in asked and len(asked) <= 250
    assert any("margin expanded" in quote for quote in _quotes(out)) or any(
        "margin held at the guided level" in quote for quote in _quotes(out))


def test_share_capital_with_a_period_prefers_the_printed_line(store: Path) -> None:
    printed = p3.fact(SYM, "Share Capital", period="Mar-25")
    assert printed["found"], printed
    assert printed["route"] != "shares", printed
    assert printed["answer"]["value"] == 313.0
    assert printed["answer"]["period"] == "Mar-25"
    assert "shares" not in str(printed["answer"].get("unit") or "").lower()
    # no period asked: the share count is the answer, as before
    counted = p3.fact(SYM, "Share Capital")
    assert counted["found"], counted
    assert counted["route"] == "shares", counted
    assert counted["answer"]["unit"] == "shares"
