"""T-090: one preferred financial figure in the data, point in time, and ``pilot3_fin`` agreeing with it.

Fixture only: a scratch SQLite file built from the real DDL, no store, no network, no model.  The path is a unique
file under ``.tmp/`` (not a fresh directory: a created directory needs a Windows ACL this sandbox does not grant).
Run it in its own process (``python -m pytest reality_engine/tests/test_pilot3_preferred_data.py -q``): the lookup
module caches one connection per process, as ``test_pilot3_preferred.py`` states.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

from reality_engine.pilot3 import preferred, schema

SERVER = Path(__file__).resolve().parents[2] / "plugins" / "reality-data" / "server"
SYM = "BAJFINANCE"
OTHER = "HINDALCO"
ASOF = "2026-11-04"
SCRATCH = Path(".tmp")

COLUMNS_XBRL = ("symbol, isin, period_start, period_end, fiscal_period, basis, audited, statement, line_item, "
                "xbrl_tag, value, unit, scale, source_file, source_db, source_table, source_rowid, known_at, "
                "known_at_source, is_reported")
COLUMNS_PRINTED = ("symbol, isin, period_start, period_end, fiscal_period, period_type, column_role, basis, "
                   "statement, line_item, caption, value, unit, scale, raw_token, quote, doc_key, page, known_at, "
                   "known_at_source, check_status, check_detail, is_reported")


def _conn():
    SCRATCH.mkdir(exist_ok=True)
    path = SCRATCH / f"t090_{uuid.uuid4().hex}.db"
    conn = sqlite3.connect(path)
    schema.create(conn, list(schema.TABLES))
    for symbol, isin, bse, name in ((SYM, "INE296A01024", "500034", "Bajaj Finance Limited"),
                                    (OTHER, "INE038A01020", "500440", "Hindalco Industries Limited")):
        conn.execute("INSERT INTO company VALUES (?,?,NULL,NULL,?,?,?)", (symbol, isin, bse, bse, name))
    conn.commit()
    return conn, path


def _printed(conn, period, end, role, value, known, status, item="total_income", basis="consolidated",
             symbol=SYM, token=None, period_type="quarter"):
    conn.execute(f"INSERT INTO fin_quarter_printed ({COLUMNS_PRINTED}) VALUES ("
                 + ",".join("?" * 23) + ")",
                 (symbol, "I", end[:7] + "-01", end, period, period_type, role, basis, "P&L", item, item, value,
                  "inr", 1.0, token if token is not None else f"{value:.2f}", f"{item} {value}",
                  f"doc-{known[:10]}", 1, known, "x", status, "", 1))


def _xbrl(conn, period, end, item, value, known, basis="consolidated", symbol=SYM):
    conn.execute(f"INSERT INTO fin_quarter_xbrl ({COLUMNS_XBRL}) VALUES (?,?,?,?,?,?,'A','P&L',?,?,?, 'inr',1,"
                 "'f','d','t','r',?,'s',1)",
                 (symbol, "I", end[:7] + "-01", end, period, basis, item, item, value, known))


def _at(conn, day, symbol=SYM, item="total_income", period="Q2FY26", basis="consolidated"):
    """Exactly the row the columns call preferred on ``day`` (the contract ``pilot3_sql`` tells a model to read)."""
    return conn.execute(
        "SELECT source_table, value, scale, preferred_from, preferred_to FROM ("
        "  SELECT 'fin_quarter_xbrl' AS source_table, symbol, line_item, fiscal_period, basis, value, scale, "
        "         preferred_from, preferred_to FROM fin_quarter_xbrl"
        "  UNION ALL"
        "  SELECT 'fin_quarter_printed', symbol, line_item, fiscal_period, basis, value, scale, "
        "         preferred_from, preferred_to FROM fin_quarter_printed) "
        "WHERE preferred_from <= ? AND (preferred_to IS NULL OR preferred_to > ?) "
        "AND symbol=? AND line_item=? AND fiscal_period=? AND basis=?",
        (day, day, symbol, item, period, basis)).fetchall()


def _current(conn, symbol, item, period, basis):
    return conn.execute("SELECT value, scale FROM fin_quarter_current WHERE symbol=? AND line_item=? AND "
                        "fiscal_period=? AND basis=?", (symbol, item, period, basis)).fetchall()


@pytest.fixture()
def lookups(monkeypatch):
    made = []

    def make(path):
        monkeypatch.setenv("REALITY_PILOT3_DB", str(path))
        if str(SERVER) not in sys.path:
            sys.path.insert(0, str(SERVER))
        spec = importlib.util.spec_from_file_location("lookups_pilot3", SERVER / "lookups_pilot3.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        made.append((module, path))
        return module

    yield make
    for module, path in made:
        module.close()
        try:
            path.unlink(missing_ok=True)
        except OSError:      # a failed test may still hold the file open on Windows
            pass


def _bajaj_restatement(conn):
    """The live T-090 evidence: the Q2 FY26 current figure, its print in the Q3 FY26 filing (same value), and the
    Q2 FY27 filing's year-ago column, which restates it lower."""
    _printed(conn, "Q2FY26", "2025-09-30", "current", 20_180.76e7, "2025-11-10T17:11:10", "xbrl_ok")
    _printed(conn, "Q2FY26", "2025-09-30", "preceding", 20_180.76e7, "2026-02-03T17:07:39", "xbrl_ok")
    _printed(conn, "Q2FY26", "2025-09-30", "year_ago", 19_992.38e7, "2026-10-19T17:19:48", "unchecked",
             token="19,992.38")
    conn.commit()


# --- 1. the columns: one preferred row per key, tiling the timeline ---------------------------------
def test_columns_elect_the_restatement_point_in_time():
    conn, _path = _conn()
    _bajaj_restatement(conn)
    preferred.apply(conn, [SYM])
    rows = conn.execute("SELECT column_role, value, preferred_from, preferred_to FROM fin_quarter_printed "
                        "WHERE symbol=? AND line_item='total_income' AND fiscal_period='Q2FY26' ORDER BY known_at",
                        (SYM,)).fetchall()
    assert [r[2] is not None for r in rows] == [True, True, True]          # the windows tile the timeline
    assert rows[0][0] == "current" and rows[0][3] == "2026-02-03T17:07:39"
    assert rows[1][0] == "preceding" and rows[1][3] == "2026-10-19T17:19:48"
    assert rows[2][0] == "year_ago" and rows[2][3] is None                  # current now
    assert [r[1] for r in _at(conn, ASOF)] == [19_992.38e7]
    assert [r[1] for r in _at(conn, "2026-01-01")] == [20_180.76e7]
    assert len(_at(conn, "2026-02-03")) == 1 and len(_at(conn, "2026-10-19")) == 1
    assert [(r[0], r[1]) for r in _current(conn, SYM, "total_income", "Q2FY26", "consolidated")] == \
           [(19_992.38e7, 1.0)]


def test_view_holds_one_row_per_key():
    conn, _path = _conn()
    _bajaj_restatement(conn)
    _xbrl(conn, "Q2FY27", "2026-09-30", "revenue_from_operations", 49_244.0, "2026-10-23T20:16:14")
    preferred.apply(conn, [SYM])
    keys = conn.execute("SELECT COUNT(*) FROM (SELECT DISTINCT symbol, fiscal_period, basis, line_item "
                        "FROM fin_quarter_current)").fetchone()[0]
    rows = conn.execute("SELECT COUNT(*) FROM fin_quarter_current").fetchone()[0]
    assert (keys, rows) == (2, 2)


# --- 2. pilot3_fin returns the column figure at both dates ------------------------------------------
def test_pilot3_fin_agrees_with_the_columns(lookups):
    conn, path = _conn()
    _bajaj_restatement(conn)
    preferred.apply(conn, [SYM])
    module = lookups(path)
    now = module.fin(SYM, "total_income", "Q2FY26", basis="consolidated", as_of=ASOF)
    assert now["n"] == 1 and now["rows"][0]["preferred"] is True and now["rows"][0]["restated"] is True
    assert now["rows"][0]["value_inr"] == pytest.approx(19_992.38e7)
    before = module.fin(SYM, "total_income", "Q2FY26", basis="consolidated", as_of="2026-01-01")
    assert before["rows"][0]["value_inr"] == pytest.approx(20_180.76e7)


# --- 3. the sweep: every key, both tables, an XBRL twin, a glued token, a second symbol --------------
def test_every_key_agrees_with_the_columns_under_the_sweep(lookups):
    conn, path = _conn()
    _bajaj_restatement(conn)
    # an XBRL line suppresses newer printed twins of the same key (the lookup counts them as duplicates)
    _xbrl(conn, "Q2FY27", "2026-09-30", "revenue_from_operations", 49_244.0, "2026-10-23T20:16:14")
    _printed(conn, "Q2FY27", "2026-09-30", "current", 49_244.0, "2026-10-23T16:16:06", "xbrl_ok",
             item="revenue_from_operations")
    _printed(conn, "Q2FY27", "2026-09-30", "year_ago", 1.0, "2026-10-29T16:16:06", "sum_ok",
             item="revenue_from_operations")              # newer, but never the evidence
    # same value printed twice: the newer checked print wins; a token that is not one printed number is not a figure
    _printed(conn, "Q1FY27", "2026-06-30", "current", 17_341.0, "2026-07-28T15:00:00", "sum_ok", item="pat",
             basis="standalone")
    _printed(conn, "Q1FY27", "2026-06-30", "current", 17_341.0, "2026-08-01T10:00:00", "repeat_ok", item="pat",
             basis="standalone")
    _printed(conn, "Q1FY27", "2026-06-30", "current", 9_176.0, "2026-08-02T10:00:00", "unchecked", item="pat",
             basis="standalone", token="9,176 cr")
    # an unchecked single-number cell is displayable and can be preferred
    _printed(conn, "Q2FY26", "2025-09-30", "current", 5_000.0, "2026-02-03T10:00:00", "unchecked", item="ebitda",
             basis="standalone", token="5,000.00")
    # a second symbol, XBRL preferred over a newer printed twin of the same basis
    _xbrl(conn, "Q2FY26", "2025-09-30", "pat", 4_000.0, "2025-11-01T10:00:00", symbol=OTHER)
    _printed(conn, "Q2FY26", "2025-09-30", "current", 4_000.0, "2026-02-01T10:00:00", "xbrl_ok", item="pat",
             symbol=OTHER)
    conn.commit()
    preferred.apply(conn, [SYM, OTHER])
    module = lookups(path)
    keys = conn.execute("SELECT DISTINCT symbol, line_item, fiscal_period, basis FROM fin_quarter_current "
                        "ORDER BY 1,2,3,4").fetchall()
    assert len(keys) == 5
    differences = []
    for symbol, item, period, basis in keys:
        current = _current(conn, symbol, item, period, basis)
        reply = module.fin(symbol, item, period, basis=basis, as_of=ASOF)
        got = [(r["value"] * r["scale"]) for r in reply["rows"]
               if r["measure"] == item and r["period"] == period and r["basis"] == basis]
        want = [(r[0] * r[1]) for r in current]
        if len(got) != 1 or abs(got[0] - want[0]) > 1e-6 * max(1.0, abs(want[0])):
            differences.append((symbol, item, period, basis, got, want))
    assert differences == []
    preferred_values = {(r[0], r[1], r[2], r[3]): r[4] for r in conn.execute(
        "SELECT symbol, line_item, fiscal_period, basis, value FROM fin_quarter_current")}
    assert preferred_values[(SYM, "revenue_from_operations", "Q2FY27", "consolidated")] == 49_244.0
    assert preferred_values[(SYM, "pat", "Q1FY27", "standalone")] == 17_341.0
    assert preferred_values[(OTHER, "pat", "Q2FY26", "consolidated")] == 4_000.0


# --- 4. --symbols: the step only rewrites the companies it is given ---------------------------------
def test_apply_is_scoped_to_the_symbols_it_is_given():
    conn, _path = _conn()
    _bajaj_restatement(conn)
    _xbrl(conn, "Q2FY26", "2025-09-30", "pat", 4_000.0, "2025-11-01T10:00:00", symbol=OTHER)
    conn.commit()
    preferred.apply(conn, [SYM])
    assert conn.execute("SELECT COUNT(*) FROM fin_quarter_printed WHERE symbol=? AND preferred_from IS NOT NULL",
                        (SYM,)).fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM fin_quarter_xbrl WHERE symbol=? AND preferred_from IS NOT NULL",
                        (OTHER,)).fetchone()[0] == 0        # untouched, not cleared
    preferred.apply(conn, [OTHER])
    assert conn.execute("SELECT COUNT(*) FROM fin_quarter_xbrl WHERE symbol=? AND preferred_from IS NOT NULL",
                        (OTHER,)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM fin_quarter_printed WHERE symbol=? AND preferred_from IS NOT NULL",
                        (SYM,)).fetchone()[0] == 3          # still there


def test_a_key_with_only_an_unreadable_cell_has_no_preferred_figure():
    conn, _path = _conn()
    _printed(conn, "Q3FY26", "2025-12-31", "current", 9_176.0, "2026-02-03T10:00:00", "unchecked",
             token="9,176 cr")
    conn.commit()
    preferred.apply(conn, [SYM])
    assert _current(conn, SYM, "total_income", "Q3FY26", "consolidated") == []
    assert conn.execute("SELECT COUNT(*) FROM fin_quarter_printed WHERE preferred_from IS NOT NULL").fetchone()[0] == 0
