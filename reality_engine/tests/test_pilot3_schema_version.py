"""T-202: every pilot3 store knows its schema version; the numbered migrations move an older one forward.

A version-0 store is one built before ``schema_meta`` existed: the 18-column ``share_capital`` and a ``guidance``
with no ``entity`` columns.  ``migrate`` brings it to ``LATEST`` additively and leaves its rows alone, a second run
is a no-op, and a read-only lookup still answers holding and guidance from it while its provenance names the
version.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

from reality_engine.pilot3 import schema

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "plugins" / "reality-data" / "server"

OLD_SHARE_CAPITAL = """CREATE TABLE share_capital (
    symbol TEXT, isin TEXT, as_of_date TEXT, basis TEXT, event TEXT, ratio TEXT,
    shares_outstanding REAL, paid_up_capital REAL, face_value REAL, unit TEXT, scale REAL,
    known_at TEXT, known_at_source TEXT, source_db TEXT, source_table TEXT, source_rowid TEXT,
    isin_effective_from TEXT, isin_effective_to TEXT)"""

OLD_GUIDANCE = """CREATE TABLE guidance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT, isin TEXT, metric TEXT, target_period TEXT, low REAL, high REAL, unit TEXT,
    direction TEXT, said_on TEXT, doc_key TEXT, page INTEGER, quote TEXT, speaker TEXT,
    known_at TEXT, known_at_source TEXT, revision_of INTEGER, extractor_rule TEXT)"""

OLD_FIN_QUARTER = """CREATE TABLE {name} (
    symbol TEXT, isin TEXT, period_start TEXT, period_end TEXT, fiscal_period TEXT, basis TEXT,
    audited TEXT, statement TEXT, line_item TEXT, xbrl_tag TEXT, value REAL, unit TEXT, scale REAL,
    source_file TEXT, source_db TEXT, source_table TEXT, source_rowid TEXT,
    known_at TEXT, known_at_source TEXT, is_reported INTEGER)"""

# the ``event`` table of a store at v8: the 16 columns T-194 defined, without T-197's doc_type / title /
# body_excerpt
OLD_EVENT = """CREATE TABLE event (
    symbol TEXT, isin TEXT, kind TEXT, event_date TEXT, end_date TEXT, announced TEXT, unit TEXT,
    outcome TEXT, subject TEXT, doc_key TEXT, page INTEGER, quote TEXT, known_at TEXT,
    known_at_source TEXT, source TEXT, extractor_rule TEXT)"""


def old_store(path: Path) -> Path:
    """A store of the schema this ticket found in the wild: no ``schema_meta``, no newer columns."""
    conn = sqlite3.connect(path)
    conn.executescript(
        ";\n".join((
            OLD_SHARE_CAPITAL, OLD_GUIDANCE,
            OLD_FIN_QUARTER.format(name="fin_quarter_xbrl"), OLD_FIN_QUARTER.format(name="fin_quarter_printed"),
            schema.TABLES["company"], schema.TABLES["doc"], schema.TABLES["shp_category"],
            schema.TABLES["shp_holder"], schema.TABLES["shp_pledge"])) + ";")
    conn.execute("INSERT INTO company VALUES ('TST','INE000A01010',NULL,NULL,'t','500000','Test Limited')")
    conn.execute("INSERT INTO doc VALUES ('d1','TST','INE000A01010','transcript','transcript','Q1 call',"
                 "'2026-08-01','2026-08-01T17:00:00',1,'sha','pages.db','k')")
    conn.execute("INSERT INTO share_capital (symbol, isin, as_of_date, basis, shares_outstanding, unit, scale, "
                 "known_at, source_db, source_table, source_rowid) VALUES "
                 "('TST','INE000A01010','2026-06-30','consolidated',12345678.0,'shares',1.0,'2026-08-05T10:00:00',"
                 "'db','quarterly','r1')")
    conn.execute("INSERT INTO guidance (symbol, isin, metric, target_period, low, high, unit, direction, said_on, "
                 "doc_key, page, quote, known_at, extractor_rule) VALUES ('TST','INE000A01010','revenue_growth',"
                 "'FY27',10.0,12.0,'pct','up','2026-08-01','d1',1,'we expect 10-12%','2026-08-01T17:00:00','t')")
    conn.execute("INSERT INTO shp_category (symbol, quarter_end, category, shares, pct, source_kind, known_at) "
                 "VALUES ('TST','2026-06-30','promoter',8000000.0,55.0,'xbrl','2026-07-20T10:00:00')")
    conn.commit()
    conn.close()
    return path


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


@contextmanager
def lookups_at(db: Path, monkeypatch):
    """The read-only server lookups pointed at ``db`` (the plugin server is not importable from the repo root)."""
    sys.path.insert(0, str(SERVER))
    import lookups_pilot3 as p3  # noqa: PLC0415

    monkeypatch.setenv("REALITY_PILOT3_DB", str(db))
    p3.close()
    p3._COLUMN_CACHE.clear()
    p3._VERSION_CACHE.clear()
    try:
        yield p3
    finally:
        p3.close()
        p3._COLUMN_CACHE.clear()
        p3._VERSION_CACHE.clear()


def test_a_version_zero_store_migrates_to_latest_and_keeps_its_rows(tmp_path):
    conn = sqlite3.connect(old_store(tmp_path / "old.db"))
    before = {
        "share_capital": conn.execute("SELECT shares_outstanding, known_at, source_table FROM share_capital").fetchall(),
        "guidance": conn.execute("SELECT metric, low, high, quote FROM guidance").fetchall(),
        "shp_category": conn.execute("SELECT category, shares, pct FROM shp_category").fetchall(),
    }
    assert schema.version(conn) == 0
    assert [number for number, _name in schema.pending(conn)] == [number for number, _name, _fn in schema.MIGRATIONS]
    assert schema.migrate(conn) == (0, schema.LATEST)
    assert schema.version(conn) == schema.LATEST
    assert schema.pending(conn) == []
    assert "count_basis" in columns(conn, "share_capital")
    assert {"entity", "entity_unsure"} <= columns(conn, "guidance")
    for table in ("fin_quarter_xbrl", "fin_quarter_printed"):
        assert {"preferred_from", "preferred_to"} <= columns(conn, table)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert {"event", "row_check", "row_check_fail", "fin_quarter_current", "transcript_statement"} <= tables
    assert {"doc_type", "title", "body_excerpt"} <= columns(conn, "event")
    assert "definition" in columns(conn, "row_check")
    assert conn.execute("SELECT shares_outstanding, known_at, source_table FROM share_capital").fetchall() == \
        before["share_capital"]
    assert conn.execute("SELECT metric, low, high, quote FROM guidance").fetchall() == before["guidance"]
    assert conn.execute("SELECT category, shares, pct FROM shp_category").fetchall() == before["shp_category"]
    conn.close()


def test_a_partial_old_store_migrates_without_raising(tmp_path):
    """A store whose kpi_series predates even the columns the current index names (the old guidance fixture)."""
    conn = sqlite3.connect(tmp_path / "partial.db")
    conn.execute("CREATE TABLE kpi_series (symbol TEXT, metric TEXT, value REAL, unit TEXT)")
    conn.execute("CREATE TABLE transcript_statement (symbol TEXT, doc_key TEXT, call_date TEXT)")
    conn.execute("CREATE TABLE transcript_question (symbol TEXT, question TEXT)")
    conn.commit()
    assert schema.migrate(conn) == (0, schema.LATEST)
    assert "entity" in columns(conn, "kpi_series")
    assert "answer_turn" in columns(conn, "transcript_statement")
    conn.close()


def test_a_version_eight_store_gains_the_t197_event_columns(tmp_path):
    """T-197's ``event.doc_type / title / body_excerpt`` is migration v9: a store built at v8 (the T-194 event
    table) gains the columns in place and keeps its rows."""
    path = old_store(tmp_path / "v8.db")
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE IF EXISTS event")
    conn.execute(OLD_EVENT)
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO schema_meta VALUES ('schema_version', '8')")
    conn.execute("INSERT INTO event (symbol, isin, kind, event_date, announced, doc_key, page, quote, known_at) "
                 "VALUES ('TST','INE000A01010','inspection','2026-07-01','2026-07-02','d1',1,'USFDA inspected',"
                 "'2026-07-02T10:00:00')")
    conn.commit()
    assert schema.version(conn) == 8
    assert [number for number, _name in schema.pending(conn)] == [schema.V_EVENT_BODY]
    assert schema.migrate(conn) == (8, schema.LATEST)
    assert {"doc_type", "title", "body_excerpt"} <= columns(conn, "event")
    row = conn.execute("SELECT symbol, kind, quote FROM event").fetchall()
    assert row == [("TST", "inspection", "USFDA inspected")]
    assert schema.migrate(conn) == (schema.LATEST, schema.LATEST)
    conn.close()


def test_migrating_twice_is_a_no_op(tmp_path):
    conn = sqlite3.connect(old_store(tmp_path / "old.db"))
    schema.migrate(conn)
    tables = sorted(row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    counts = {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
              for table in tables if not table.startswith("sqlite_")}
    assert schema.migrate(conn) == (schema.LATEST, schema.LATEST)
    assert schema.version(conn) == schema.LATEST
    assert {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in tables if not table.startswith("sqlite_")} == counts
    conn.close()


def test_cli_status_and_migrate(tmp_path, capsys):
    db = old_store(tmp_path / "old.db")
    assert schema.main(["--db", str(db), "--status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["version"] == 0 and status["latest"] == schema.LATEST and status["pending"]
    assert schema.main(["--db", str(db), "--migrate"]) == 0
    migrated = json.loads(capsys.readouterr().out)
    assert migrated["version"] == schema.LATEST and migrated["pending"] == []
    assert schema.main(["--db", str(db), "--status"]) == 0
    assert json.loads(capsys.readouterr().out)["version"] == schema.LATEST


def test_a_read_only_lookup_answers_holding_and_guidance_on_a_version_zero_store(tmp_path, monkeypatch):
    db = old_store(tmp_path / "old.db")
    with lookups_at(db, monkeypatch) as p3:
        assert p3.store_version() == 0
        hold = p3.holding("TST", "2026-09-30")
        assert hold["found"] is True
        assert hold["provenance"]["schema_version"] == 0
        assert hold["provenance"]["schema_note"]           # it says the store is older than this server
        assert hold["share_capital"]["shares_outstanding"] == 12345678.0
        assert hold["share_capital"]["count_basis"] is None      # not the exact filed count: the old rule
        guide = p3.guidance("TST")
        assert guide["found"] is True
        assert guide["rows"][0]["metric"] == "revenue_growth"
        assert guide["rows"][0]["low"] == 10.0
        assert guide["provenance"]["schema_version"] == 0


def test_a_migrated_store_reports_its_version_and_answers_the_same(tmp_path, monkeypatch):
    db = old_store(tmp_path / "old.db")
    conn = sqlite3.connect(db)
    schema.migrate(conn)
    conn.close()
    with lookups_at(db, monkeypatch) as p3:
        assert p3.store_version() == schema.LATEST
        hold = p3.holding("TST", "2026-09-30")
        assert hold["provenance"]["schema_version"] == schema.LATEST
        assert "schema_note" not in hold["provenance"]
        assert hold["share_capital"]["shares_outstanding"] == 12345678.0
        guide = p3.guidance("TST")
        assert guide["found"] is True
        assert guide["rows"][0]["metric"] == "revenue_growth"
