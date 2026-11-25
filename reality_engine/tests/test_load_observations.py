"""T-242: the widened deck read loads BESIDE the primary deck db - page-disjoint, ids offset, checks by original id."""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from reality_engine.scripts import load_observations as lo

TMP = Path(__file__).resolve().parents[2] / ".tmp" / "obs_supplement_fixtures"

OBS_DDL = """
CREATE TABLE observation (
    observation_id INTEGER PRIMARY KEY, symbol TEXT, doc_key TEXT, page INTEGER, known_at TEXT,
    measure TEXT, period TEXT, record_type TEXT, value REAL, unit TEXT, scale REAL, statement TEXT,
    status TEXT, reader TEXT)
"""
MEASURE_DDL = """CREATE TABLE measure_new (new_id TEXT, definition TEXT, driver_node TEXT,
    observations INTEGER, pages INTEGER, examples TEXT, first_known_at TEXT)"""
EVENT_DDL = "CREATE TABLE event (symbol TEXT, kind TEXT, status TEXT, quote TEXT)"
OBS_COLS = ["observation_id", "symbol", "doc_key", "page", "known_at", "measure", "period", "record_type",
            "value", "unit", "scale", "statement", "status", "reader"]
OFFSET = 10_000_000


def _make_db(path: Path, *ddl: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    for d in ddl:
        con.execute(d)
    con.commit()
    return con


def _obs(con: sqlite3.Connection, **kw) -> None:
    row = {"symbol": "AAA", "doc_key": "d.pdf", "page": 1, "known_at": "2026-11-01T00:00:00",
           "measure": "revenue", "period": "Q2FY27", "record_type": "number", "value": 1.0, "unit": "INR",
           "scale": 1e7, "statement": None, "status": "verified", "reader": "hy4-flash-free"}
    row.update(kw)
    con.execute(f"INSERT INTO observation ({','.join(OBS_COLS)}) VALUES ({','.join('?' * len(OBS_COLS))})",
                [row[c] for c in OBS_COLS])


@pytest.fixture()
def w(monkeypatch: pytest.MonkeyPatch) -> dict:
    """primary deck db page 1 (2 rows); supplement page 1 (a competing row, never loaded) + page 2 (added)."""
    if TMP.exists():
        shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True)
    primary, sup, ev, store = (TMP / n for n in ("deck_fy27.db", "deck_wide.db", "events.db", "store.db"))
    con = _make_db(primary, OBS_DDL, MEASURE_DDL)
    _obs(con, observation_id=1, measure="revenue", value=100.0)
    _obs(con, observation_id=2, measure="ebitda", value=50.0)
    con.commit()
    con.close()
    con = _make_db(sup, OBS_DDL, MEASURE_DDL)
    _obs(con, observation_id=1, measure="revenue", value=999.0)
    _obs(con, observation_id=2, measure="capex", value=7.0, page=2)
    con.commit()
    con.close()
    con = _make_db(ev, EVENT_DDL)
    con.close()
    con = _make_db(store)
    con.close()
    monkeypatch.setattr(lo, "OBS_SOURCES", [("deck_fy27", str(primary), "deck")])
    monkeypatch.setattr(lo, "SUPPLEMENTS", [("deck_wide", str(sup), "deck", OFFSET)])
    monkeypatch.setattr(lo, "EVENTS_DB", str(ev))
    monkeypatch.setattr(lo, "EVENTS_PRIORITY", [])
    monkeypatch.setattr(lo, "CHECKS", {})
    monkeypatch.setattr(lo, "OBS_COLS", None)
    return {"primary": primary, "sup": sup, "store": store}


def _deck(store: Path) -> list[tuple]:
    con = sqlite3.connect(store)
    rows = con.execute("SELECT observation_id, page, measure, value, reader, check_status FROM obs_fact "
                       "WHERE source='deck' ORDER BY observation_id").fetchall()
    con.close()
    return rows


def test_supplement_adds_only_pages_the_primary_lacks(w: dict) -> None:
    stats = lo._load_store(w["store"], "AAA")
    assert _deck(w["store"]) == [
        (1, 1, "revenue", 100.0, "hy4-flash-free", None),          # primary rows kept as they were
        (2, 1, "ebitda", 50.0, "hy4-flash-free", None),
        (OFFSET + 2, 2, "capex", 7.0, "hy4-flash-free [deck_wide]", None),  # only the page the primary lacked
    ]
    assert stats["obs"] == {"deck": 2, "deck_wide": 1}
    assert stats["obs_db"]["deck_wide"] == str(w["sup"])


def test_reload_is_idempotent(w: dict) -> None:
    lo._load_store(w["store"], "AAA")
    before = _deck(w["store"])
    lo._load_store(w["store"], "AAA")
    assert _deck(w["store"]) == before and len(before) == 3


def test_checks_are_looked_up_with_the_original_id(w: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    verdicts = w["store"].parent / "verdicts.jsonl"
    verdicts.write_text(json.dumps({"id": 2, "verdict": "fix", "period": "Q3FY27", "evidence": "Capex 7",
                                    "header": "Q3 FY27"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(lo, "CHECKS", {str(w["sup"]): [str(verdicts)]})
    lo._load_store(w["store"], "AAA")
    rows = {r[0]: r for r in _deck(w["store"])}
    assert rows[OFFSET + 2][5] == "model_checked"          # the supplement row carries the check of id 2
    con = sqlite3.connect(w["store"])
    fields = con.execute("SELECT check_fields FROM obs_fact WHERE observation_id=?", (OFFSET + 2,)).fetchone()[0]
    con.close()
    assert json.loads(fields) == {"period": "Q3FY27"}
    assert rows[2][5] is None                              # the primary row has no verdict


def test_symbol_without_primary_rows_gets_every_supplement_page(w: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lo, "OBS_COLS", lo._cols(str(w["primary"]), "observation"))
    monkeypatch.setattr(lo, "OBS_SOURCES", [])             # no primary deck db holds this symbol
    lo._load_store(w["store"], "AAA")
    rows = _deck(w["store"])
    assert [r[0] for r in rows] == [OFFSET + 1, OFFSET + 2]
