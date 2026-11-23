"""A prices-only truth snapshot must not hide the research tables of an older full snapshot."""
import duckdb
import pytest

from reality_engine.gap_loop import prepare


def _snap(path, tables):
    con = duckdb.connect(str(path))
    for name, value in tables.items():
        con.execute(f"CREATE TABLE {name} AS SELECT {value} AS v")
    con.close()


def test_statement_falls_back_to_the_newest_snapshot_holding_its_table(tmp_path, monkeypatch):
    snaps = tmp_path / "snapshots"
    snaps.mkdir()
    _snap(snaps / "truth_2026-11-04.duckdb", {"px_daily": 1, "corporate_actions": 7})
    _snap(snaps / "truth_2026-11-09.duckdb", {"px_daily": 2})          # prices only
    monkeypatch.setattr(prepare, "DATA_ROOT", tmp_path)
    assert prepare._read_duckdb("SELECT v FROM px_daily", ())[0] == [(2,)]            # newest wins when it can
    assert prepare._read_duckdb("SELECT v FROM corporate_actions", ())[0] == [(7,)]   # else the newest that can
    with pytest.raises(duckdb.CatalogException):
        prepare._read_duckdb("SELECT v FROM nowhere", ())
