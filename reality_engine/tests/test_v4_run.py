"""The v4 run: question -> decompose -> execute per part -> render, over two stores.

The fixture is the shape the WP2a/WP2b builds actually have: ``fact`` in one file with
the measure column named ``atom`` (not §B.1's ``atom_id``), and ``claim`` /
``own_estimate`` in a second file.  No live database is opened.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tasks" / "answer_bench"))

from reality_engine.query.v4 import execute, run  # noqa: E402
import grade_v2  # noqa: E402

ISIN = "INE0TEST01"


@pytest.fixture()
def store() -> run.Stores:
    # tmp_path is unusable under the worker sandbox (its root is not listable), and the
    # session temp may not be either; .tmp/ in the checkout is writable.
    root = REPO / ".tmp" / f"v4run-{uuid.uuid4().hex[:10]}"
    root.mkdir(parents=True, exist_ok=True)
    fact = sqlite3.connect(root / "fact_v4_pilot.db")
    fact.executescript(
        """
        CREATE TABLE fact(entity_id TEXT, atom TEXT, dims TEXT, period_start TEXT,
                          period_end TEXT, value REAL, unit TEXT, known_at TEXT,
                          source_ref TEXT);
        CREATE TABLE membership(entity_id TEXT, set_kind TEXT, set_value TEXT,
                                valid_from TEXT, valid_to TEXT, weight REAL,
                                source TEXT, known_at TEXT);
        """
    )
    rows = [
        (ISIN, "fin.revenue", "basis=consolidated;period_kind=quarter", "2026-04-01",
         "2026-06-30", 100.0, "INR_CRORE", "2026-07-30T19:00:00", "results_xbrl"),
        (ISIN, "fin.revenue", "basis=standalone;period_kind=quarter", "2026-04-01",
         "2026-06-30", 80.0, "INR_CRORE", "2026-07-30T18:59:00", "results_xbrl"),
        (ISIN, "fin.revenue", "basis=consolidated;period_kind=quarter", "2026-07-01",
         "2026-09-30", 120.0, "INR_CRORE", "2026-11-05T19:00:00", "results_xbrl"),
        (ISIN, "price.close", "", "2026-10-15", "2026-10-15", 250.0, "INR",
         "2026-10-15T15:30:00", "market_state.company_state_daily"),
        (ISIN, "hold.pct", "holder_class=promoter", "2026-06-30", "2026-06-30", 55.0, "%",
         "2026-07-21", "market_state.company_ownership_pit"),
        (ISIN, "hold.pct", "holder_class=public", "2026-06-30", "2026-06-30", 40.0, "%",
         "2026-07-21", "market_state.company_ownership_pit"),
    ]
    fact.executemany("INSERT INTO fact VALUES (?,?,?,?,?,?,?,?,?)", rows)
    fact.commit()
    fact.close()

    second = sqlite3.connect(root / "v4.db")
    second.executescript(
        """
        CREATE TABLE claim(entity_id TEXT, topic TEXT, direction TEXT, magnitude REAL,
                           unit TEXT, horizon TEXT, certainty TEXT, quote TEXT,
                           page_no INT, doc_id INT, doctype TEXT, known_at TEXT);
        CREATE TABLE own_estimate(isin TEXT, est_atom TEXT, period_end TEXT, value REAL,
                                  unit TEXT, method TEXT, inputs_json TEXT, n_obs INT,
                                  confidence REAL, known_at TEXT, as_of TEXT);
        """
    )
    second.execute("INSERT INTO claim VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (ISIN, "demand", "up", None, None, "FY27", "stated",
                    "Demand remained strong through the quarter", 4, 7, "concall",
                    "2026-08-15T18:00:00"))
    second.execute("INSERT INTO own_estimate VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (ISIN, "fin.revenue", "2026-09-30", 110.0, "INR_CRORE", "trend",
                    json.dumps({"series": "fin.revenue", "n": 8}), 8, 0.55,
                    "2026-10-30T19:00:00", "2026-10-31"))
    second.commit()
    second.close()
    return run.Stores(root)


@pytest.fixture()
def resolver() -> run.Resolver:
    return run.Resolver({"TESTCO": ISIN}, {"Test Co Limited": ISIN, "TESTCO": ISIN})


def case(question: str, mid: str = "T1", **extra) -> dict:
    return {"mid": mid, "question": question, "as_of": "2026-10-31", **extra}


# --- end to end ------------------------------------------------------------
def test_question_to_answer_over_both_stores(store, resolver):
    row = run.run_case(case("What is the revenue of Test Co Limited in Q1 FY27?"),
                       store, resolver)
    assert row["entity"] == ISIN and row["entity_how"] == "name"
    part = [p for p in row["ask"]["parts"] if p.get("atom") == "fin.revenue"]
    assert part, row["ask"]["parts"]
    assert row["case_answered"] is True
    assert row["results"][0]["value"] == 100.0
    assert row["results"][0]["unit"] == "INR_CRORE"
    assert row["results"][0]["period"] == "2026-06-30"
    assert row["results"][0]["source_ref"] == "results_xbrl"
    assert "P1 measured" in row["answer"] and "real_answered: 1" in row["answer"]
    status = grade_v2.case_status(row["ask"], row["results"])
    assert status["covered"] is True and status["real_answered"] == 1


def test_pit_cuts_at_the_run_date(store, resolver):
    row = run.run_case(case("What is the revenue of Test Co Limited in Q2 FY27?"),
                       store, resolver)
    results = [result for result in row["results"]
               if result.get("atom") == "fin.revenue"]
    # The only Q2 row is known 2026-11-05, after as_of, so it is invisible; a named
    # period never falls back to an older period's row (2026-06-30 is a different quarter).
    assert results and results[0]["answer_type"] == "not_in_data"
    assert "2026-07-01..2026-09-30" in (results[0].get("nid_reason") or "")
    assert all(str(result.get("known_at") or "") <= "2026-10-30"
               for result in row["results"])
    assert all(result.get("value") != 120.0 for result in row["results"])


def test_default_consolidation_reading_is_not_guessed(store, resolver):
    row = run.run_case(case("Test Co Limited revenue in Q1 FY27"), store, resolver)
    result = row["results"][0]
    assert result["value"] == 100.0               # consolidated, not the standalone 80
    assert result["values"][0]["dims"].get("consolidation") == "consolidated"


def test_claim_reads_the_second_store(store, resolver):
    row = run.run_case(case("TESTCO Aug-2026 concall remark"), store, resolver)
    assert row["parts"] == 1
    result = row["results"][0]
    assert result["answer_type"] == "measured" and result["source_ref"] == "claim"
    assert result["values"][0]["quote"].startswith("Demand remained strong")
    assert "Demand remained strong" in row["answer"]


def test_estimate_reads_the_second_store(store):
    result = execute.execute(
        {"atom": "own.estimate", "dims": {"est_atom": "fin.revenue"}, "window": 0,
         "operator": "value_at", "shape": "estimate", "judgement": False},
        "2026-10-31", store, windows=[{"from": None, "to": "2026-10-31"}],
        entity=ISIN, registry=run.execute_registry())
    assert result.answer_type == "estimate" and result.value == 110.0
    assert result.method == "trend" and result.confidence == 0.55
    assert grade_v2.part_status({"atom": "own.estimate", "window": 0, "dims": {},
                                 "operator": "value_at", "shape": "estimate"},
                                result)["covered"] is True


# --- entity resolution -----------------------------------------------------
def test_resolver_reads_symbol_name_and_prefix(resolver):
    ask = type("Ask", (), {"entities": [type("E", (), {"isin": None, "symbol": "TEST",
                                                       "level": "stock",
                                                       "how": "caps"})()],
                           "question": "TESTCO revenue"})()
    isin, found, how = resolver.resolve(ask)
    assert (isin, how) == (ISIN, "symbol-prefix")
    assert resolver.by_text("what did Test Co Limited say") == [ISIN]


def test_unresolved_entity_is_a_typed_nid(store):
    resolver = run.Resolver({"OTHER": "INE0OTHER1"}, {})
    row = run.run_case(case("AEROFLEX products + close on a date"), store, resolver)
    assert row["entity"] is None
    assert row["case_answered"] is False
    assert all(result["answer_type"] == "not_in_data" for result in row["results"])
    assert all(result["tried"] and result["to_close"] for result in row["results"])


def test_one_day_window_keeps_a_daily_close(store, resolver):
    row = run.run_case(case("TESTCO close on 15 Oct 2026"), store, resolver)
    result = row["results"][0]
    assert result["atom"] == "price.close"
    assert result["value"] == 250.0 and result["period"] == "2026-10-15"


def test_blank_as_of_defaults_to_the_declared_snapshot(store, resolver):
    """A blank as_of is the declared snapshot date, stated as an assumption (MB0345)."""
    row = run.run_case({"mid": "T5", "as_of": None,
                        "question": "What is the revenue of Test Co Limited in Q1 FY27?"},
                       store, resolver)
    assert row["as_of"] == run.DEFAULT_AS_OF
    assert row["assumed_as_of"] and "blank" in row["assumed_as_of"]
    assert f"Assumption: as_of was blank; assumed the declared snapshot date " \
           f"{run.DEFAULT_AS_OF}" in row["answer"]
    assert row["case_answered"] is True


def test_no_store_returns_nid_not_a_crash(resolver):
    row = run.run_case(case("Test Co Limited revenue"), None, resolver)
    assert row["results"] and all(result["answer_type"] == "not_in_data"
                                  for result in row["results"])


def test_case_entity_resolves_when_the_text_names_nobody(store, resolver):
    """An instance row carries its company; the text may still name the old one."""
    row = run.run_case({"mid": "T2", "question": "What was revenue in Q1 FY27?",
                        "as_of": "2026-10-31",
                        "entities": [{"isin": ISIN, "symbol": "TESTCO"}]}, store, resolver)
    assert row["entity"] == ISIN and row["entity_how"] == "case-isin"
    assert row["case_answered"] is True


def test_case_entity_outside_the_pilot_is_a_typed_nid(store, resolver):
    row = run.run_case({"mid": "T3", "question": "What was revenue in Q1 FY27?",
                        "as_of": "2026-10-31",
                        "entities": [{"isin": "INE0OTHER1", "symbol": "OTHER"}]},
                       store, resolver)
    assert row["entity"] is None and row["case_answered"] is False
    assert "not one of the 1 pilot ISIN" in row["entity_how"]
    assert all(result["answer_type"] == "not_in_data" for result in row["results"])


def test_stores_route_macro_oi_to_the_side_file():
    import sqlite3

    from reality_engine.query.v4.run import Stores

    # tmp_path is unusable under the worker sandbox (see the ``store`` fixture).
    root = REPO / ".tmp" / f"v4route-{uuid.uuid4().hex[:10]}"
    root.mkdir(parents=True, exist_ok=True)
    for name, value in (("fact_v4_pilot.db", "core"), ("fact_v4_pilot_oi.db", "side"), ("v4.db", "v4")):
        con = sqlite3.connect(root / name)
        con.execute("CREATE TABLE fact(atom TEXT, value TEXT)")
        con.execute("INSERT INTO fact VALUES ('x', ?)", (value,))
        con.commit()
        con.close()
    with Stores(root) as stores:
        assert stores.oi is not None
        assert stores.execute("SELECT value FROM fact WHERE ?<>''", ("macro.oi",)).fetchone()[0] == "side"
        assert stores.execute("SELECT value FROM fact WHERE ?<>''", ("fin.pat",)).fetchone()[0] == "core"
