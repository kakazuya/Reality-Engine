"""T-220: ``{view:<name> where <filter>}`` expands into the view's SELECT filtered before its GROUP BY."""
import sqlite3

import pytest

from reality_engine.gap_loop.prepare import _filtered_view


def _con():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE filings (file TEXT PRIMARY KEY, isin TEXT, status TEXT);
        CREATE TABLE facts (file TEXT, concept TEXT, value REAL);
        CREATE VIEW q AS SELECT f.file, f.isin, MAX(CASE WHEN x.concept='R' THEN x.value END) AS R
            FROM filings f JOIN facts x ON x.file=f.file WHERE f.status='ok' GROUP BY f.file;
        CREATE VIEW nogroup AS SELECT * FROM filings;
        INSERT INTO filings VALUES ('a','I1','ok'),('b','I2','ok'),('c','I1','bad');
        INSERT INTO facts VALUES ('a','R',1),('b','R',2),('c','R',3);
    """)
    return con


def test_filtered_view_same_rows_as_view_filter():
    con = _con()
    old = con.execute("SELECT * FROM q WHERE isin IN (?) ORDER BY file", ("I1",)).fetchall()
    new = con.execute(_filtered_view(con, "SELECT * FROM {view:q where f.isin IN (?)} AS q ORDER BY file"),
                      ("I1",)).fetchall()
    assert old == new == [("a", "I1", 1.0)]


def test_filtered_view_needs_group_by_and_known_view():
    con = _con()
    with pytest.raises(RuntimeError):
        _filtered_view(con, "SELECT * FROM {view:nogroup where isin='x'}")
    with pytest.raises(RuntimeError):
        _filtered_view(con, "SELECT * FROM {view:missing where isin='x'}")


def test_plain_sql_untouched():
    con = _con()
    assert _filtered_view(con, "SELECT 1") == "SELECT 1"
