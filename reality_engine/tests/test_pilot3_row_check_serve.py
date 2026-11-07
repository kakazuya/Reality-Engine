"""T-113 B: the row-check verdicts built into the database and served by ``pilot3_kpi`` / ``pilot3_guidance``.

Fixture only: scratch SQLite files under ``.tmp/`` built from the real DDL (``reality_engine.pilot3.schema``,
``kpi.SCHEMA``); no production database, network or model.  The build part runs the real checker on the fixture
(so ``row_check`` / ``row_check_fail`` are written by ``row_checks.py`` itself); the serving tests insert verdicts
directly, so each status is exercised without depending on the checker's rules.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import uuid
from pathlib import Path
from types import ModuleType

import pytest

from reality_engine.pilot3 import build, kpi as kpi_mod, schema

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "plugins" / "reality-data" / "server"
SCRATCH = ROOT / ".tmp"
SYM = "KEC"
DOC = "pdfs/KEC/deck1.pdf"

# the checker's own output DDL (row_checks.write): the serving tests insert verdicts into the same shape
_CHECK_DDL = """
CREATE TABLE row_check (tbl TEXT, row_id INTEGER, symbol TEXT, metric TEXT, canon TEXT, sector TEXT,
    doc_type TEXT, rule TEXT, status TEXT, corroborated INTEGER, checker TEXT, PRIMARY KEY (tbl, row_id));
CREATE TABLE row_check_fail (tbl TEXT, row_id INTEGER, check_name TEXT, hard INTEGER, why TEXT);
"""


def _connect(path: Path | None = None) -> tuple[sqlite3.Connection, Path]:
    SCRATCH.mkdir(exist_ok=True)
    path = Path(path or SCRATCH / f"t113_{uuid.uuid4().hex}.db")
    conn = sqlite3.connect(path)
    schema.create(conn, list(schema.TABLES))
    conn.executescript(kpi_mod.SCHEMA)
    conn.execute("INSERT INTO company VALUES (?,?,NULL,NULL,'532714','532714','KEC International Limited')",
                 (SYM, "INE389H01022"))
    conn.execute("INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 (DOC, SYM, "INE389H01022", "deck", "deck", "Investor Presentation", "2026-08-10",
                  "2026-08-10T17:00:00", 1, "sha", "pages.db", "D:/raw/deck1.pdf"))
    conn.execute("INSERT INTO doc_page VALUES (?,?,?,?,?,?,?,?)",
                 (DOC, SYM, 1, "Order book stood at Rs 40,000 crore in June 2026. ROE was 15.1% for FY26.",
                  "script_text", 80, "2026-08-10T17:00:00", None))
    _kpi_rows(conn)
    _guidance_rows(conn)
    conn.commit()
    return conn, path


def _kpi(conn, rid, metric, value, unit, period, quote, known, page=1):
    conn.execute(
        "INSERT INTO kpi_series(id,symbol,metric,dimension,value,unit,scale,period_type,fiscal_period,as_of_date,"
        "basis,doc_key,page,quote,known_at,known_at_source,is_reported,extractor_rule,source_type,entity) "
        "VALUES (?,?,?,'total',?,?,1,'FY',?,'2025-03-31','consolidated',?,?,?,?,'x',1,'sentence_v1','deck','')",
        (rid, SYM, metric, value, unit, period, DOC, page, quote, known))


def _guidance(conn, rid, metric, low, high, period, quote, known):
    conn.execute(
        "INSERT INTO guidance(id,symbol,isin,metric,target_period,low,high,unit,direction,said_on,doc_key,page,quote,"
        "speaker,known_at,known_at_source,revision_of,extractor_rule) VALUES (?,?,?,?,?,?,?,?,'up',?,?,1,?,NULL,?,"
        "'docs.known_at',NULL,'t')",
        (rid, SYM, "INE389H01022", metric, period, low, high, "pct", known[:10], DOC, quote, known))


def _kpi_rows(conn):
    # id 1 is the T-105 trap: a net-NPA metric holding the gross NPA figure -> quarantined
    _kpi(conn, 1, "nnpa_pct", 1.18, "pct", "FY25",
         "Gross NPA stood at 1.18% as on 31 March 2025", "2026-05-10T10:00:00")
    _kpi(conn, 2, "order_book", 40000.0, "inr_cr", "Q1FY27",
         "Order book stood at Rs 40,000 crore in June 2026", "2026-08-10T17:00:00")
    _kpi(conn, 3, "order_book", 45000.0, "inr_cr", "Q2FY27",
         "Order book reached Rs 45,000 crore in September 2026", "2026-11-05T10:00:00")
    # stated ROE: the FY25 row is quarantined, the FY26 row verified
    _kpi(conn, 4, "roe", 14.2, "pct", "FY25", "Return on equity was 14.2% for FY25", "2026-05-10T10:00:00")
    _kpi(conn, 5, "roe", 15.1, "pct", "FY26", "Return on equity was 15.1% for FY26", "2026-08-10T17:00:00")


def _guidance_rows(conn):
    _guidance(conn, 1, "credit_cost", 0.5, 0.6, "FY27",
              "We expect credit cost of 0.5% to 0.6% for FY27.", "2026-08-10T17:00:00")
    _guidance(conn, 2, "revenue_growth", 12.0, 15.0, "FY27",
              "We expect revenue growth of 12% to 15% for FY27.", "2026-08-10T17:00:00")
    _guidance(conn, 3, "revenue_growth", 10.0, 12.0, "FY28",
              "We target revenue growth of 10% to 12% for FY28.", "2026-08-10T17:00:00")


def _verdicts(conn):
    conn.executescript(_CHECK_DDL)
    rows = [("kpi_series", 1, SYM, "nnpa_pct", "quarantined", 0, [("label_conflict", 1, "gross NPA")]),
            ("kpi_series", 2, SYM, "order_book", "verified", 1, []),
            ("kpi_series", 3, SYM, "order_book", "unverified", 0,
             [("multi_number", 0, "several numbers"), ("value_scaled", 0, "only after rescale")]),
            ("kpi_series", 4, SYM, "roe", "quarantined", 0, [("label_conflict", 1, "gross NPA")]),
            ("kpi_series", 5, SYM, "roe", "verified", 1, []),
            ("guidance", 1, SYM, "credit_cost", "quarantined", 0, [("forward_word", 1, "no forward word")]),
            ("guidance", 2, SYM, "revenue_growth", "verified", 1, []),
            ("guidance", 3, SYM, "revenue_growth", "unverified", 0, [("range_spread", 0, "high/low 1.2")])]
    conn.executemany("INSERT INTO row_check VALUES (?,?,?,?,?,'','','',?,?, 'row_checks_v1')",
                     [(tbl, rid, sym, metric, "", status, int(corr))
                      for tbl, rid, sym, metric, status, corr, _ in rows])
    conn.executemany("INSERT INTO row_check_fail VALUES (?,?,?,?,?)",
                     [(tbl, rid, name, hard, why)
                      for tbl, rid, _, _, _, _, fails in rows for name, hard, why in fails])
    conn.commit()


@pytest.fixture()
def lookups(monkeypatch):
    made: list[tuple[ModuleType, Path, sqlite3.Connection | None]] = []

    def make(with_check: bool = True, path: Path | None = None):
        if path is None:
            conn, path = _connect()
            if with_check:
                _verdicts(conn)
        else:
            conn = None
        monkeypatch.setenv("REALITY_PILOT3_DB", str(path))
        if str(SERVER) in sys.path:
            sys.path.remove(str(SERVER))
        sys.path.insert(0, str(SERVER))
        # another plugin's server/core.py may already be imported under the bare name ``core`` (the full
        # reality_engine suite collects those modules too); the lookups module needs the reality-data one
        prior_core = sys.modules.get("core")
        if prior_core is not None and not hasattr(prior_core, "DataError"):
            del sys.modules["core"]
        spec = importlib.util.spec_from_file_location("lookups_pilot3", SERVER / "lookups_pilot3.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        finally:
            if prior_core is not None:      # the lookups module keeps its own reference to the right core
                sys.modules["core"] = prior_core
        made.append((module, path, conn))
        return module

    yield make
    for module, path, conn in made:
        module.close()
        if conn is not None:
            conn.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(f"{path}{suffix}").unlink(missing_ok=True)
            except OSError:      # a failed test may still hold the file open on Windows
                pass


# --- the build part ---------------------------------------------------------------------------------
def test_build_part_runs_the_checker_and_copies_both_tables():
    conn, path = _connect()
    profile = path.with_suffix(".json")
    profile.write_text(json.dumps({"companies": [{"symbol": SYM, "sector": "capital_goods"}]}), encoding="utf-8")
    try:
        summary = build.checks(conn, path, str(profile))
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"row_check", "row_check_fail"} <= names
        assert conn.execute("SELECT COUNT(*) FROM row_check").fetchone()[0] == 8   # 5 kpi + 3 guidance
        assert summary["tables"] == ["guidance", "kpi_series"]
        assert sum(summary["by_table"]["kpi_series"].values()) == 5
        assert sum(summary["by_table"]["guidance"].values()) == 3
        # the verdicts are real checker verdicts, not an empty shell
        assert {r[0] for r in conn.execute("SELECT DISTINCT status FROM row_check")} <= {"verified", "unverified",
                                                                                        "quarantined"}
        assert not path.with_name(f"{path.stem}_row_checks.tmp.db").exists()     # temp file cleaned up
    finally:
        conn.close()
        path.unlink(missing_ok=True)
        profile.unlink(missing_ok=True)


def test_guidance_rebuild_drops_stale_verdicts(monkeypatch, lookups):
    """A part that rewrites guidance gives its rows new ids: the old verdicts must go, or the next row with the same
    id is served with a label it never earned.  The rebuilt row here reuses id 2, the old ``verified`` verdict."""
    from reality_engine.pilot3 import guidance as guidance_mod
    from reality_engine.pilot3 import profile as profile_mod

    conn, path = _connect()
    _verdicts(conn)
    conn.close()
    profile_file = path.with_suffix(".json")
    profile_file.write_text(json.dumps({"name": "t113", "pages_db": "pages.db", "raw_root": "raw",
                                        "manifest": "raw/manifest.csv", "out": "unused.db",
                                        "companies": [{"symbol": SYM, "sector": "capital_goods"}]}),
                            encoding="utf-8")

    def rebuild(out_db, symbols, limit_docs=None):
        c = sqlite3.connect(out_db)
        try:
            c.execute("DELETE FROM guidance WHERE symbol=?", (SYM,))
            _guidance(c, 2, "credit_cost", 0.5, 0.6, "FY27",
                      "We expect credit cost of 0.5% to 0.6% for FY27.", "2026-08-10T17:00:00")
            c.commit()
        finally:
            c.close()
        return {SYM: {"rows": 1}}

    monkeypatch.setattr(guidance_mod, "run", rebuild)
    try:
        profile_mod.activate(profile_mod.load(profile_file))
        build.build(path, "guidance")
    finally:
        profile_mod.activate(None)
        profile_file.unlink(missing_ok=True)
    rows = lookups(path=path).guidance(SYM)["rows"]
    assert [r["metric"] for r in rows] == ["credit_cost"]
    assert rows[0]["check_status"] is None and "check_note" not in rows[0]   # the stale "verified" is gone
    c = sqlite3.connect(path)
    try:
        assert c.execute("SELECT COUNT(*) FROM row_check WHERE tbl='guidance'").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM row_check_fail WHERE tbl='guidance'").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM row_check WHERE tbl='kpi_series'").fetchone()[0] == 5  # untouched
    finally:
        c.close()


# --- serving ----------------------------------------------------------------------------------------
def test_kpi_hides_quarantined_and_labels_check_status(lookups):
    p3 = lookups()
    verified = p3.kpi(SYM, "order_book", "Q1FY27")["rows"]
    assert [(r["value"], r["check_status"]) for r in verified] == [(40000.0, "verified")]
    assert "check_note" not in verified[0]
    unverified = p3.kpi(SYM, "order_book", "Q2FY27")["rows"]
    assert [(r["value"], r["check_status"]) for r in unverified] == [(45000.0, "unverified")]
    assert unverified[0]["check_note"] == "multi_number, value_scaled"
    hidden = p3.kpi(SYM, "nnpa_pct", "FY25")
    assert hidden["found"] is False
    assert "nnpa_pct" not in p3.kpi(SYM, "nonsense")["available"]      # every row of it is quarantined
    assert "order_book" in p3.kpi(SYM, "nonsense")["available"]
    shown = p3.kpi(SYM, "nnpa_pct", "FY25", include_quarantined=True)
    assert [(r["value"], r["check_status"]) for r in shown["rows"]] == [(1.18, "quarantined")]


def test_guidance_hides_quarantined_and_labels_check_status(lookups):
    p3 = lookups()
    out = p3.guidance(SYM)
    assert {(r["metric"], r["period"], r["check_status"]) for r in out["rows"]} == {
        ("revenue_growth", "FY27", "verified"), ("revenue_growth", "FY28", "unverified")}
    unverified = next(r for r in out["rows"] if r["check_status"] == "unverified")
    assert unverified["check_note"] == "range_spread"
    miss = p3.guidance(SYM, metric="credit_cost")
    assert miss["found"] is False
    assert "credit_cost" not in miss["available"]      # the metric exists only as a quarantined row
    assert "revenue_growth" in miss["available"]
    shown = p3.guidance(SYM, metric="credit_cost", include_quarantined=True)
    assert [(r["low"], r["high"], r["check_status"]) for r in shown["rows"]] == [(0.5, 0.6, "quarantined")]


def test_stated_ratio_hides_quarantined_kpi(lookups):
    p3 = lookups()
    rows = p3._stated_ratios(SYM, "roe", None, None, None, 8)
    assert [(r["period"], r["value"], r["check_status"]) for r in rows] == [("FY26", 15.1, "verified")]
    every = p3._stated_ratios(SYM, "roe", None, None, None, 8, include_quarantined=True)
    assert {(r["period"], r["check_status"]) for r in every} == {("FY25", "quarantined"), ("FY26", "verified")}


def test_as_of_still_applies(lookups):
    p3 = lookups()
    assert p3.kpi(SYM, "order_book", as_of="2026-08-01")["found"] is False   # known 2026-08-10
    assert [r["value"] for r in p3.kpi(SYM, "order_book", as_of="2026-08-10")["rows"]] == [40000.0]
    assert p3.guidance(SYM, as_of="2026-08-01")["found"] is False


def test_build_without_row_check_serves_exactly_as_before(lookups):
    p3 = lookups(with_check=False)
    kpi_rows = p3.kpi(SYM, "nnpa_pct", "FY25")["rows"]       # the quarantined-elsewhere row is served unchecked
    assert [(r["value"], "check_status" in r) for r in kpi_rows] == [(1.18, False)]
    guidance_rows = p3.guidance(SYM)["rows"]
    assert "credit_cost" in {r["metric"] for r in guidance_rows}
    assert all("check_status" not in r and "check_note" not in r for r in guidance_rows)
