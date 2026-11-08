"""T-126: Drive files the T-102 manifest did not list become manifest rows a RawStore walk sees."""
import json
import sqlite3

from reality_engine import raw_store
from reality_engine.scripts import drive_index_unlisted as d


def test_map_path():
    assert d.map_path("pdfs/DLF/CONCALL_TRANSCRIPT/a.pdf") == ("pdfs", "DLF/CONCALL_TRANSCRIPT/a.pdf")
    assert d.map_path("arch17/InfoDiffusion_to_upload/pdfs/UBL/AR/b.pdf") == ("pdfs", "UBL/AR/b.pdf")
    assert d.map_path("msi_raw/raw/decks/bse/1/c.pdf") == ("raw", "decks/bse/1/c.pdf")
    assert d.map_path("results_pdfs/2025-12-31/x.pdf") == ("raw", "results_pdfs/2025-12-31/x.pdf")
    assert d.map_path("hp_raw/hp_raw.tar") is None


def test_index_adds_unlisted_and_keeps_known(tmp_path, monkeypatch):
    man = tmp_path / "m.db"
    con = sqlite3.connect(man)
    con.execute("CREATE TABLE local_file (path TEXT PRIMARY KEY, root TEXT, rel TEXT, size INTEGER, mtime REAL,"
                " md5 TEXT, status TEXT, drive_path TEXT, deleted_at TEXT)")
    con.execute("INSERT INTO local_file VALUES ('D:/x','pdfs','KEC/A/k.pdf',1,0,'aa','on_drive','msi_raw/pdfs/KEC/A/k.pdf',NULL)")
    con.commit(); con.close()
    lst = tmp_path / "lst"; lst.mkdir()
    (lst / "pdfs.json").write_text(json.dumps([
        {"Path": "DLF/T/new.pdf", "Size": 5, "Hashes": {"md5": "bb", "sha256": "cc"}, "ID": "1"},
        {"Path": "KEC/A/k.pdf", "Size": 1, "Hashes": {"md5": "aa"}, "ID": "2"}]))
    (lst / "msi_raw.json").write_text(json.dumps([{"Path": "pdfs/KEC/A/k.pdf", "Size": 1, "Hashes": {"md5": "aa"}}]))
    stats = d.index(lst, man)
    assert stats["added"] == 1 and stats["same_key"] == 2
    store = raw_store.RawStore(manifest=man, roots={"pdfs": tmp_path / "pdfs"})
    monkeypatch.setenv("REALITY_RAW_FETCH", "1")
    assert store.drive_path(tmp_path / "pdfs" / "DLF" / "T" / "new.pdf") == "pdfs/DLF/T/new.pdf"
    assert sqlite3.connect(man).execute("SELECT COUNT(*) FROM drive_file").fetchone()[0] == 3
    assert d.index(lst, man)["added"] == 0      # idempotent


def test_drive_file_listed_under_another_local_path_gets_its_own_row(tmp_path):
    """T-102 matched by md5, so a pdfs/ Drive file can be 'known' as the copy of raw/concall_pdfs/<sha>.pdf."""
    man = tmp_path / "m.db"
    con = sqlite3.connect(man)
    con.execute("CREATE TABLE local_file (path TEXT PRIMARY KEY, root TEXT, rel TEXT, size INTEGER, mtime REAL,"
                " md5 TEXT, status TEXT, drive_path TEXT, deleted_at TEXT)")
    con.execute("INSERT INTO local_file VALUES ('D:/r','raw','concall_pdfs/16/s.pdf',1,0,'aa','on_drive','pdfs/A/T/f.pdf',NULL)")
    con.commit(); con.close()
    lst = tmp_path / "lst"; lst.mkdir()
    (lst / "pdfs.json").write_text(json.dumps([{"Path": "A/T/f.pdf", "Size": 1, "Hashes": {"md5": "aa"}}]))
    assert d.index(lst, man)["added"] == 1
    store = raw_store.RawStore(manifest=man, roots={"pdfs": tmp_path / "pdfs", "raw": tmp_path / "raw"})
    assert store.drive_path(tmp_path / "pdfs" / "A" / "T" / "f.pdf") == "pdfs/A/T/f.pdf"
