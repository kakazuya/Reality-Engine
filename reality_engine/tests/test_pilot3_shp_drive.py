"""T-218 repair note R-004: the full shareholding pattern of a company outside the pilot folder.

``build_shp`` read only the local pilot folder, so a store built for any other company held the index's promoter and
public lines and no FPI, mutual fund, insurance, holder or pledge row.  The files the company's own ``shp_index``
rows name are now looked up in the pilot folder and then the universe folder (T-209), on disk or, through
``raw_store``, on Drive; a Drive copy is deleted once it is read.  Fixture files only, a fake rclone, no network.

    python -m pytest reality_engine/tests/test_pilot3_shp_drive.py -q
"""
from __future__ import annotations

import gzip
import hashlib
import io
import sqlite3
from pathlib import Path

import pytest

from reality_engine import raw_store
from reality_engine.pilot3 import schema, stores
from reality_engine.tests.test_pilot3_shp_holder import _shp_xml

NAME = "SHP_0001_01102026100000_WEB.xml"
OTHER = "SHP_0002_01102026100000_WEB.xml"          # another company's filing: never asked for
ROOT = "nse_shp_xbrl_universe"


def _gz(data: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as fh:
        fh.write(data)
    return buf.getvalue()


def _index(*names: str) -> list[dict]:
    return [{"file": name, "isin": "INE000A01010", "quarter_end": "2026-09-30", "promoter_pct": 36.0,
             "public_pct": 54.0, "record_id": str(i), "revised": None, "broadcast_at": "2026-10-01T10:00:00",
             "submission_date": "2026-09-30"} for i, name in enumerate(names, 1)]


@pytest.fixture()
def shp(tmp_path, monkeypatch):
    """Empty pilot and universe folders, one company whose index names ``NAME``; Drive on, no real raw store."""
    pilot, universe = tmp_path / "raw" / "nse_shp_xbrl_pilot", tmp_path / ROOT
    pilot.mkdir(parents=True)
    universe.mkdir()
    monkeypatch.delenv("REALITY_RAW_FETCH", raising=False)
    monkeypatch.setattr(stores, "SHP_XBRL", pilot)
    monkeypatch.setattr(stores, "SHP_XBRL_UNIVERSE", universe)
    monkeypatch.setattr(stores.profile, "symbols", lambda: ("KEC",))
    monkeypatch.setattr(stores, "fetch", lambda symbol, table: _index(NAME) if table == "shp_index" else [])
    monkeypatch.setattr(stores, "all_isins", lambda symbol: ("INE000A01010",))
    monkeypatch.setattr(stores, "_shp_raw_store", lambda: raw_store.RawStore(
        manifest=tmp_path / "none.db", roots={"raw": tmp_path / "raw", ROOT: universe}))
    return tmp_path


def _drive(tmp_path: Path, monkeypatch, files: dict[str, bytes]) -> dict:
    """A manifest that maps the universe folder's files to Drive and a fake rclone that serves them."""
    manifest = tmp_path / "manifest.db"
    con = sqlite3.connect(manifest)
    con.execute("CREATE TABLE local_file (path TEXT PRIMARY KEY, root TEXT, rel TEXT, size INTEGER, mtime REAL, "
                "md5 TEXT, status TEXT, drive_path TEXT, deleted_at TEXT)")
    for name, data in files.items():
        con.execute("INSERT INTO local_file VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"D:/x/{ROOT}\\{name}.gz", ROOT, f"{name}.gz", len(data), 0.0, hashlib.md5(data).hexdigest(),
                     "on_drive", f"msi_raw/{ROOT}/{name}.gz", "2026-11-15"))
    con.commit()
    con.close()
    seen: dict = {"asked": [], "dirs": []}

    def runner(cmd: list[str]) -> None:
        dest = Path(cmd[2])
        seen["dirs"].append(dest)
        for rest in Path(cmd[cmd.index("--files-from") + 1]).read_text(encoding="utf-8").split():
            seen["asked"].append(rest)
            target = dest / rest
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(files[Path(rest).name[:-3]])

    monkeypatch.setattr(stores, "_shp_raw_store", lambda: raw_store.RawStore(
        manifest=manifest, roots={"raw": tmp_path / "raw", ROOT: tmp_path / ROOT}, runner=runner))
    return seen


def _build() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    schema.create(conn, list(schema.TABLES))
    stores.build_shp(conn)
    return conn


def _counts(conn: sqlite3.Connection) -> tuple:
    return (conn.execute("SELECT COUNT(*) FROM shp_category WHERE source_kind='xbrl'").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM shp_holder").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM shp_pledge").fetchone()[0])


def test_a_file_the_index_names_is_read_from_the_universe_folder(shp):
    (shp / ROOT / f"{NAME}.gz").write_bytes(_gz(_shp_xml()))
    (shp / ROOT / f"{OTHER}.gz").write_bytes(b"not gzip: a file no index row of this store names is never opened")
    conn = _build()
    xbrl, holders, pledges = _counts(conn)
    assert xbrl >= 3 and holders == 3 and pledges == 1
    assert conn.execute("SELECT DISTINCT source_db, source_file FROM shp_category WHERE source_kind='xbrl'"
                        ).fetchall() == [(ROOT, NAME)]
    assert conn.execute("SELECT DISTINCT source_db FROM shp_holder").fetchall() == [(ROOT,)]
    # the index lines stay as they were
    assert conn.execute("SELECT category, pct, source_db FROM shp_category WHERE source_kind='index' "
                        "ORDER BY category").fetchall() == [("promoter", 36.0, "equity_intelligence.db"),
                                                            ("public", 54.0, "equity_intelligence.db")]


def test_the_pilot_folder_wins_and_keeps_its_label(shp):
    with gzip.open(shp / "raw" / "nse_shp_xbrl_pilot" / f"{NAME}.gz", "wb") as fh:
        fh.write(_shp_xml())
    (shp / ROOT / f"{NAME}.gz").write_bytes(b"never read: the pilot copy is used")
    conn = _build()
    assert conn.execute("SELECT DISTINCT source_db FROM shp_category WHERE source_kind='xbrl'"
                        ).fetchall() == [("nse_shp_xbrl_pilot",)]
    assert _counts(conn)[1:] == (3, 1)


def test_a_drive_only_file_is_fetched_once_read_and_deleted(shp, monkeypatch):
    seen = _drive(shp, monkeypatch, {NAME: _gz(_shp_xml()), OTHER: _gz(_shp_xml())})
    conn = _build()
    assert seen["asked"] == [f"{ROOT}/{NAME}.gz"]            # only the file this company's index names
    assert seen["dirs"] and not any(d.exists() or d.parent.exists() for d in seen["dirs"])   # Drive copy deleted
    assert not list((shp / ROOT).iterdir())                  # nothing written into the raw folder
    xbrl, holders, pledges = _counts(conn)
    assert xbrl >= 3 and holders == 3 and pledges == 1
    assert conn.execute("SELECT DISTINCT source_db FROM shp_category WHERE source_kind='xbrl'"
                        ).fetchall() == [(ROOT,)]
    assert conn.execute("SELECT known_at FROM shp_pledge").fetchall() == [("2026-10-01T10:00:00",)]


def test_with_drive_off_the_build_keeps_the_index_rows_and_says_what_is_missing(shp, monkeypatch, capsys):
    seen = _drive(shp, monkeypatch, {NAME: _gz(_shp_xml())})
    monkeypatch.setenv("REALITY_RAW_FETCH", "0")
    conn = _build()
    assert seen["asked"] == [] and _counts(conn) == (0, 0, 0)
    assert conn.execute("SELECT COUNT(*) FROM shp_category WHERE source_kind='index'").fetchone()[0] == 2
    assert "1 of 1 shareholding files" in capsys.readouterr().err


def test_a_file_held_nowhere_and_a_file_that_does_not_parse_are_named_not_fatal(shp, monkeypatch, capsys):
    monkeypatch.setattr(stores, "fetch", lambda symbol, table: _index(NAME, OTHER, "-") if table == "shp_index" else [])
    (shp / ROOT / f"{OTHER}.gz").write_bytes(_gz(b"<broken"))     # corrupt at source (one such file in T-209)
    conn = _build()
    err = capsys.readouterr().err
    assert _counts(conn) == (0, 0, 0)
    assert "1 of 2 shareholding files" in err and OTHER in err and "unreadable" in err


def test_a_consolidated_share_count_far_from_standalone_is_dropped():
    from reality_engine.pilot3 import stores
    row = lambda basis, date, shares: ("S", "I", date, basis, None, None, shares, shares * 2, 2.0)
    rows = [row("standalone", "2026-09-30", 89_166_000), row("consolidated", "2026-09-30", 694_000),
            row("standalone", "2026-06-30", 88_472_000), row("consolidated", "2026-06-30", 88_472_000),
            row("consolidated", "2026-03-31", 83_143_500)]       # no standalone that quarter: kept
    kept = stores._parent_share_count(rows)
    assert [(r[2], r[3]) for r in kept] == [("2026-09-30", "standalone"), ("2026-06-30", "standalone"),
                                            ("2026-06-30", "consolidated"), ("2026-03-31", "consolidated")]
