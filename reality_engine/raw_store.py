"""Content-addressed raw store: identical bytes are stored once (sha256 + hard links).

Companies file the same PDF twice (standalone/consolidated, revisions) and re-file decks
under new names, so the D raw pile is heading for hundreds of GB. A fetcher that writes
through ``store_bytes`` makes the second path a hard link to the first instead of a
second copy; the sha index lives in ``RAW_ROOT/_dedupe/sha_index.db``.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from reality_engine.config import RAW_ROOT

INDEX_PATH = RAW_ROOT / "_dedupe" / "sha_index.db"
CHUNK = 1 << 20

_LOCK = threading.Lock()                      # sqlite3 handle is shared by fetcher workers
_CONNS: dict[Path, sqlite3.Connection] = {}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sha_index (
  sha256 TEXT PRIMARY KEY,
  size INTEGER NOT NULL,
  first_path TEXT NOT NULL,
  stored_at TEXT NOT NULL);
"""


def sha256_file(path: Path) -> str:
    """sha256 of a whole file, read in ``CHUNK`` blocks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def same_file(a: Path, b: Path) -> bool:
    """True when both paths already name one file (a link appears twice in a scan)."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def link_file(src: Path, dest: Path) -> None:
    """Make ``dest`` a hard link to ``src``: link to ``<dest>.lnk-tmp``, then replace.

    ``os.replace`` swaps the name atomically, so ``dest`` never vanishes between unlink
    and link and the group's canonical copy is untouched throughout.
    """
    tmp = dest.with_name(dest.name + ".lnk-tmp")
    tmp.unlink(missing_ok=True)
    try:
        os.link(src, tmp)
        os.replace(tmp, dest)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _write(dest: Path, data: bytes) -> None:
    """``dest`` via ``<dest>.part`` -> fsync -> replace, so a crash never leaves half a file."""
    part = dest.with_name(dest.name + ".part")
    try:
        with open(part, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(part, dest)
    except OSError:
        part.unlink(missing_ok=True)
        raise


def _connection(index_path: Path) -> sqlite3.Connection:
    con = _CONNS.get(index_path)
    if con is None:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(index_path, timeout=60, check_same_thread=False)
        con.executescript(_SCHEMA)
        con.commit()
        _CONNS[index_path] = con
    return con


def store_bytes(dest: Path, data: bytes, index_path: Path | None = None) -> Path:
    """Store ``data`` at ``dest``; reuse an already stored copy of the same bytes.

    When the sha is in the index and the indexed file still holds those bytes, ``dest``
    becomes a hard link to it (same volume only — a cross-volume link raises, and the
    bytes are written normally instead). Otherwise the bytes are written atomically and
    recorded as the canonical copy.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(data).hexdigest()
    size = len(data)
    index = Path(index_path or INDEX_PATH)
    with _LOCK:
        con = _connection(index)
        row = con.execute(
            "SELECT first_path FROM sha_index WHERE sha256=? AND size=?", (sha, size)
        ).fetchone()
        if row:
            canonical = Path(row[0])
            try:
                if canonical.stat().st_size == size and sha256_file(canonical) == sha:
                    if same_file(dest, canonical):
                        return dest
                    link_file(canonical, dest)
                    return dest
            except OSError:
                pass                          # stale entry (moved/edited): store our own copy
        _write(dest, data)
        con.execute(
            "INSERT OR REPLACE INTO sha_index (sha256, size, first_path, stored_at) VALUES (?,?,?,?)",
            (sha, size, str(dest), datetime.now().isoformat(timespec="seconds")),
        )
        con.commit()
    return dest
