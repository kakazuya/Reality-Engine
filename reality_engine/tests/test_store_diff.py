"""T-201: the store diff pairs rows by key, not by row id, and refuses a merge that loses a right row.

Fixture stores only (two tiny sqlite files under ``.tmp``), diffed through ``diff_store`` directly: no real store,
no git, no subprocess.  The failing-part case injects a fake builder, as the CLI's runner is a plain callable.
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from reality_engine.scripts.store_diff import (build_gates, build_side, churn_gates, diff_store, golden_gates)

DDL = """
CREATE TABLE kpi_series (id INTEGER PRIMARY KEY, symbol TEXT, metric TEXT, dimension TEXT, value REAL,
    fiscal_period TEXT, basis TEXT, doc_key TEXT, page INTEGER, quote TEXT, known_at TEXT);
CREATE TABLE guidance (id INTEGER PRIMARY KEY, symbol TEXT, metric TEXT, target_period TEXT, low REAL, high REAL,
    unit TEXT, doc_key TEXT, page INTEGER, quote TEXT, entity TEXT, known_at TEXT);
CREATE TABLE ratio_panel (symbol TEXT, metric TEXT, fiscal_period TEXT, basis TEXT, value REAL);
CREATE TABLE row_check (tbl TEXT, row_id INTEGER, symbol TEXT, metric TEXT, status TEXT);
CREATE TABLE mystery (a TEXT, b REAL);
"""


@pytest.fixture()
def tmp_path():
    """A fresh directory per test under ``.tmp``: pytest's own factory cannot list its temp root in this sandbox."""
    path = Path(".tmp") / "pytest" / uuid.uuid4().hex[:8]
    path.mkdir(parents=True, exist_ok=False)
    return path


def _store(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(DDL)
    return conn


def _kpi(conn, rid, metric="order_book", period="FY26", value=100.0, page=1, doc="D1"):
    conn.execute("INSERT INTO kpi_series (id, symbol, metric, dimension, value, fiscal_period, doc_key, page, quote) "
                 "VALUES (?, 'T', ?, 'total', ?, ?, ?, ?, 'q')", (rid, metric, value, period, doc, page))


def _guidance(conn, rid, metric="revenue_growth", entity=""):
    conn.execute("INSERT INTO guidance (id, symbol, metric, target_period, low, high, doc_key, page, quote, entity) "
                 "VALUES (?, 'T', ?, 'FY27', 8.0, 10.0, 'D1', 2, 'q', ?)", (rid, metric, entity))


def _check(conn, row_id, status="verified"):
    conn.execute("INSERT INTO row_check VALUES ('guidance', ?, 'T', 'revenue_growth', ?)", (row_id, status))


def _pair(tmp_path):
    base, head = tmp_path / "base.db", tmp_path / "head.db"
    return _store(base), _store(head)


def test_a_changed_period_is_one_changed_row_not_a_removed_plus_an_added(tmp_path):
    """T-192 round 4 relabelled KPI periods: the row keeps its key, so only ``fiscal_period`` changed."""
    base, head = _pair(tmp_path)
    _kpi(base, 1, metric="order_book", period="FY26")
    _kpi(base, 2, metric="aum", period="FY26")
    _kpi(head, 3, metric="order_book", period="Q4FY26")      # same key, relabelled period
    _kpi(head, 4, metric="cash", period="FY26")              # a new key
    base.commit(), head.commit()
    base.close(), head.close()

    info = diff_store(tmp_path / "base.db", tmp_path / "head.db")["tables"]["kpi_series"]
    assert (info["removed"], info["added"], info["changed"]) == (1, 1, 1)
    assert info["columns"] == {"fiscal_period": 1}
    assert info["by_symbol"]["T"] == {"removed": 1, "added": 1, "changed": 1}
    assert info["served"]["lost"] == 1                       # the removed aum row was served
    changes = [c for sample in info["samples"] for c in sample.get("changes", [])]
    assert changes == [{"column": "fiscal_period", "base": "FY26", "head": "Q4FY26"}]


def test_a_guidance_row_hidden_by_entity_or_quarantine_is_no_longer_served(tmp_path):
    """The two hiding rules of the guidance lookup (T-192): a non-empty entity, and a quarantined verdict."""
    base, head = _pair(tmp_path)
    for rid, metric in ((1, "revenue_growth"), (2, "ebitda_margin")):
        _guidance(base, rid, metric)
        _guidance(head, rid, metric)
        _check(base, rid)
        _check(head, rid)
    head.execute("UPDATE guidance SET entity='Subsidiary Ltd' WHERE id=1")
    head.execute("UPDATE row_check SET status='quarantined' WHERE tbl='guidance' AND row_id=2")
    base.commit(), head.commit()
    base.close(), head.close()

    report = diff_store(tmp_path / "base.db", tmp_path / "head.db")
    info = report["tables"]["guidance"]
    assert info["served"]["lost"] == 2
    assert {sample["why"] for sample in info["served"]["samples"]} == {"entity", "row_check"}
    assert info["changed"] == 1 and info["columns"] == {"entity": 1}
    assert "row_check" not in report["tables"]               # verdicts are read through their serving effect


def test_a_value_change_is_matched_and_an_unknown_table_is_row_hashed(tmp_path):
    base, head = _pair(tmp_path)
    for conn, value in ((base, 10.0), (head, 12.0)):
        conn.execute("INSERT INTO ratio_panel VALUES ('T', 'roe', 'FY26', 'consolidated', ?)", (value,))
    head.execute("INSERT INTO mystery VALUES ('new', 1.0)")
    base.commit(), head.commit()
    base.close(), head.close()

    tables = diff_store(tmp_path / "base.db", tmp_path / "head.db")["tables"]
    assert (tables["ratio_panel"]["changed"], tables["ratio_panel"]["columns"]) == (1, {"value": 1})
    assert tables["mystery"]["mode"] == "row_hash"
    assert (tables["mystery"]["removed"], tables["mystery"]["added"]) == (0, 1)


def test_a_part_that_fails_on_head_only_is_a_gate(tmp_path):
    """A fake builder: no subprocess, no build, the failure is a recorded result and a gate."""
    def ok(cmd, cwd, log):
        return 0

    def head_runner(cmd, cwd, log):
        return 1 if cmd[cmd.index("--part") + 1] == "guidance" else 0

    parts = ["guidance", "kpi"]
    base = build_side(tmp_path / "b.db", parts, tmp_path, "profile.json", tmp_path, "base", runner=ok)
    head = build_side(tmp_path / "h.db", parts, tmp_path, "profile.json", tmp_path, "head", runner=head_runner)
    assert base["guidance"]["exit"] == 0 and head["guidance"]["exit"] == 1
    assert head["kpi"]["exit"] == 0 and isinstance(head["guidance"]["seconds"], float)
    gates = build_gates(base, head)
    assert len(gates) == 1 and gates[0]["gate"] == "build" and gates[0]["part"] == "guidance"


def test_a_golden_row_that_changed_or_vanished_is_a_gate(tmp_path):
    head = _store(tmp_path / "head.db")
    head.execute("INSERT INTO ratio_panel VALUES ('T', 'roe', 'FY26', 'consolidated', 12.0)")
    head.commit(), head.close()
    golden = tmp_path / "golden.csv"
    golden.write_text("table,symbol,metric,fiscal_period,basis,value\n"
                      "ratio_panel,T,roe,FY26,consolidated,10\n"
                      "ratio_panel,NOSUCH,roe,FY26,consolidated,10\n", encoding="utf-8")
    gates = golden_gates(tmp_path / "head.db", str(golden))
    assert [g["why"] for g in gates] == ["value changed", "row lost"]


def test_churn_gate_skips_the_named_target_store(tmp_path):
    tables = {"guidance": {"churn_pct": 5.0}}
    assert churn_gates(tables, 2.0, tmp_path / "pilot10.db", None)[0]["gate"] == "churn"
    assert churn_gates(tables, 2.0, tmp_path / "pilot10.db", "pilot10") == []
    assert churn_gates(tables, 6.0, tmp_path / "pilot10.db", "other") == []
