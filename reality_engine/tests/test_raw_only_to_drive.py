"""T-241: raw-only move to Drive picks only fully fetched companies and old-enough files."""
from __future__ import annotations

import os
import sqlite3
import time

from reality_engine.scripts import raw_only_to_drive as r


def _manifest(tmp_path, rows):
    db = tmp_path / "m.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE docs (isin TEXT, status TEXT, local_path TEXT, bytes INTEGER)")
    con.executemany("INSERT INTO docs VALUES (?,?,?,?)", rows)
    con.commit()
    con.close()
    return db


def test_finished_companies_skip_pending_and_empty(tmp_path):
    db = _manifest(tmp_path, [("A", "ok", "a1", 1), ("A", "skipped", None, 0),
                              ("B", "ok", "b1", 1), ("B", "pending", None, 0),
                              ("C", "no_file", None, 0)])
    assert r.finished_companies(db) == ["A"]


def test_local_files_only_existing_and_old(tmp_path):
    old, new = tmp_path / "old.pdf", tmp_path / "new.pdf"
    old.write_bytes(b"x")
    new.write_bytes(b"y")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    db = _manifest(tmp_path, [("A", "ok", str(old), 1), ("A", "ok", str(new), 1), ("A", "ok", str(tmp_path / "gone"), 1)])
    assert r.local_files(db, "A", min_age=900) == [str(old)]
