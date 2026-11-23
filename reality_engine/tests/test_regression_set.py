"""Tests for the frozen hand-labelled regression set (``reality_engine/pilot3/regression_set.py``, T-122).

Run from the repo root:
    python -m pytest reality_engine/tests/test_regression_set.py -q

The fixtures are tiny sqlite databases: a source database with one hand-read row, a verdict database with one
status, and a labels CSV holding that row's content key.  No test reads the live data or the frozen labels.
"""
from __future__ import annotations

import csv
import shutil
import sqlite3
import uuid
from pathlib import Path

import pytest

from reality_engine.pilot3 import regression_set as rs

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def tmp_path():
    """A writable scratch directory (the repo's .tmp; pytest's own tmp_path cannot be listed in this sandbox)."""
    base = ROOT / ".tmp" / f"regression_set_{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


SOURCE_DDL = """
CREATE TABLE kpi_series (id INTEGER PRIMARY KEY, symbol TEXT, metric TEXT, dimension TEXT, fiscal_period TEXT,
    basis TEXT, value REAL, unit TEXT, doc_key TEXT, page INTEGER, quote TEXT);
CREATE TABLE guidance (id INTEGER PRIMARY KEY, symbol TEXT, metric TEXT, target_period TEXT, low REAL, high REAL,
    unit TEXT, doc_key TEXT, page INTEGER, quote TEXT);
"""

ROW = {"symbol": "KIMS", "metric": "net_debt", "dimension": "total", "fiscal_period": "Q4FY26",
       "basis": "consolidated", "value": 31886.0, "unit": "inr_cr", "doc_key": "KIMS/ar/aa.pdf", "page": 12,
       "quote": "Net debt 31,886"}


def build_source(tmp_path: Path, rows: list[dict] | None = None, name: str = "src.db") -> str:
    db = tmp_path / name
    con = sqlite3.connect(db)
    con.executescript(SOURCE_DDL)
    for r in rows if rows is not None else [ROW]:
        con.execute("INSERT INTO kpi_series (symbol, metric, dimension, fiscal_period, basis, value, unit, doc_key,"
                    " page, quote) VALUES (:symbol, :metric, :dimension, :fiscal_period, :basis, :value, :unit,"
                    " :doc_key, :page, :quote)", r)
    con.commit()
    con.close()
    return str(db)


def build_rc(tmp_path: Path, verdicts: list[tuple[str, int, str]], name: str = "rc.db") -> str:
    db = tmp_path / name
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE row_check (tbl TEXT, row_id INTEGER, status TEXT, PRIMARY KEY (tbl, row_id));")
    con.executemany("INSERT INTO row_check VALUES (?,?,?)", verdicts)
    con.commit()
    con.close()
    return str(db)


def key_of(row: dict, table: str = "kpi_series") -> dict:
    """The content key a label would store for this source row, computed the way the frozen CSV stores it."""
    if table == "guidance":
        dim, period, basis, value, high = "", row["target_period"], "", row["low"], row["high"]
    else:
        dim, period, basis, value, high = row["dimension"], row["fiscal_period"], row["basis"], row["value"], None
    return {"table": table, "symbol": row["symbol"], "metric": row["metric"], "dimension": dim, "period": period,
            "basis": basis, "value": f"{value:.6f}".rstrip("0").rstrip("."),
            "high": "" if high is None else f"{high:.6f}".rstrip("0").rstrip("."),
            "unit": row["unit"], "doc_key": row["doc_key"], "page": str(row["page"]),
            "quote80": rs.row_checks.squash(row["quote"])[:80]}


HEADER = ["set", "table", "symbol", "metric", "dimension", "period", "basis", "value", "high", "unit", "doc_key",
          "page", "quote80", "label", "reason", "source"]


def write_labels(tmp_path: Path, entries: list[dict], name: str = "labels.csv") -> str:
    path = tmp_path / name
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HEADER)
        w.writeheader()
        for e in entries:
            w.writerow({**{h: "" for h in HEADER}, "set": "hold6", **e})
    return str(path)


def test_key_matches_after_an_id_change(tmp_path):
    labels = write_labels(tmp_path, [{**key_of(ROW), "label": "right", "reason": "read right"}])
    db = build_source(tmp_path, [ROW])
    rc = build_rc(tmp_path, [("kpi_series", 1, "verified")])
    assert rs.main(["--label", labels, "--set", "hold6", "--db", db, "--rc", rc]) == 0
    # A rebuild puts a different row in id 1 and moves ours to id 2: the content key still finds it.
    other = {**ROW, "metric": "revenue", "value": 1.0, "quote": "Revenue 1"}
    db2 = build_source(tmp_path, [other, ROW], name="src2.db")
    rc2 = build_rc(tmp_path, [("kpi_series", 2, "verified")], name="rc2.db")
    res = rs.score_set(rs.load_labels(Path(labels)), db2, rc2, "hold6")
    assert res.labels == 1 and res.ok == 1 and res.fail == 0


def test_a_right_row_that_became_quarantined_fails(tmp_path):
    labels = write_labels(tmp_path, [{**key_of(ROW), "label": "right", "reason": "read right"}])
    db = build_source(tmp_path, [ROW])
    rc = build_rc(tmp_path, [("kpi_series", 1, "quarantined")])
    res = rs.score_set(rs.load_labels(Path(labels)), db, rc, "hold6")
    assert res.fail == 1 and res.lines and res.lines[0].startswith("FAIL right-row-quarantined")
    assert rs.main(["--label", labels, "--set", "hold6", "--db", db, "--rc", rc]) == 1


def test_a_wrong_row_that_became_verified_fails(tmp_path):
    labels = write_labels(tmp_path, [{**key_of(ROW), "label": "wrong", "reason": "segment amount as total"}])
    db = build_source(tmp_path, [ROW])
    rc = build_rc(tmp_path, [("kpi_series", 1, "verified")])
    res = rs.score_set(rs.load_labels(Path(labels)), db, rc, "hold6")
    assert res.fail == 1 and res.lines and res.lines[0].startswith("FAIL wrong-row-verified")


def test_a_dropped_row_is_reported_as_not_found(tmp_path):
    labels = write_labels(tmp_path, [{**key_of(ROW), "label": "right", "reason": "read right"}])
    db = build_source(tmp_path, [{**ROW, "value": 2.0, "quote": "Net debt 2"}])
    rc = build_rc(tmp_path, [("kpi_series", 1, "verified")])
    res = rs.score_set(rs.load_labels(Path(labels)), db, rc, "hold6")
    assert res.not_found == 1 and res.warn == 1 and res.fail == 0
    assert res.lines[0].startswith("WARN not-found")


def test_a_partly_row_verified_is_a_warning_not_a_failure(tmp_path):
    g = {"symbol": "KIMS", "metric": "capex", "target_period": "FY23", "low": 40.0, "high": 45.0,
         "unit": "inr_cr", "doc_key": "KIMS/call/bb.pdf", "page": 3,
         "quote": "routine capex of INR 40-45 crore"}
    db = tmp_path / "src.db"
    con = sqlite3.connect(db)
    con.executescript(SOURCE_DDL)
    con.execute("INSERT INTO guidance (symbol, metric, target_period, low, high, unit, doc_key, page, quote)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (g["symbol"], g["metric"], g["target_period"], g["low"], g["high"], g["unit"], g["doc_key"],
                 g["page"], g["quote"]))
    con.commit()
    con.close()
    labels = write_labels(tmp_path, [{**key_of(g, "guidance"), "label": "partly", "reason": "routine capex"}])
    rc = build_rc(tmp_path, [("guidance", 1, "verified")])
    res = rs.score_set(rs.load_labels(Path(labels)), str(db), rc, "hold6")
    assert res.warn == 1 and res.fail == 0
    assert res.lines[0].startswith("WARN partly-row-verified")
    assert rs.main(["--label", labels, "--set", "hold6", "--db", str(db), "--rc", rc]) == 0
