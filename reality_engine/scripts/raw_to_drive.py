"""T-102: move every local raw file to the Drive archive, so raw files live only on Drive (Shivam, 7 Nov 2026).

Four steps, each resumable, each recorded in the manifest (a small SQLite file, ``--manifest``):

    hash     md5 of every non-database file under each ``--root`` (Drive's own hash is md5, so a local file can be
             matched with any Drive file whatever its path); a file with the same size and mtime is not re-read
    compare  ``on_drive`` when some Drive file in ``--listing-dir`` (the ``listing_*.json`` written by
             ``rclone lsjson -R --files-only --hash``) has the same md5 and size; otherwise ``missing``
    upload   ``rclone copy --files-from`` of the missing files to ``gdrive:InfoDiffusion_archive/msi_raw/<root>/<rel>``
             with ``--checksum``, then a fresh listing of ``msi_raw`` re-runs ``compare``
    delete   removes a local file only when its md5 and size are on Drive (``--delete``; the default lists what it
             would remove). Only files under this call's ``--root`` folders (T-215). Never touches a database file.

    ``--files-from`` (T-241) names a text file of absolute paths: hash, upload and delete then act on exactly those
    files, so ``universe_to_drive`` can move one finished company's files without touching another's.

    python -m reality_engine.scripts.raw_to_drive --root D:/RealityEngine/raw --root D:/RealityEngine/pdfs \\
        --listing-dir D:/RealityEngine/drive_index --manifest D:/RealityEngine/drive_index/raw_to_drive.db hash compare
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

REMOTE = "gdrive:InfoDiffusion_archive"
UPLOAD_PREFIX = "msi_raw"
DB_EXT = {".db", ".sqlite", ".sqlite3", ".duckdb", ".db-wal", ".db-shm", ".wal", ".shm", ".sql", ".parquet",
          ".lance", ".npy"}
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def is_database(path: str) -> bool:
    low = path.lower()
    return any(low.endswith(e) for e in DB_EXT)


def open_manifest(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS local_file (path TEXT PRIMARY KEY, root TEXT, rel TEXT, size INTEGER, "
                "mtime REAL, md5 TEXT, status TEXT, drive_path TEXT, deleted_at TEXT)")
    return con


def md5_of(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(4 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def step_hash(con: sqlite3.Connection, roots: list[str], files: list[str] | None = None) -> None:
    known = {p: (s, m) for p, s, m in con.execute("SELECT path, size, mtime FROM local_file WHERE md5 IS NOT NULL")}
    t, n, read = time.time(), 0, 0
    for p, root in _candidates(roots, files):
        if is_database(p):
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        n += 1
        if known.get(p) == (st.st_size, st.st_mtime):
            continue
        try:
            digest = md5_of(p)
        except OSError:
            continue
        read += st.st_size
        rel = os.path.relpath(p, root).replace("\\", "/")
        con.execute("INSERT OR REPLACE INTO local_file (path, root, rel, size, mtime, md5, status) "
                    "VALUES (?,?,?,?,?,?,NULL)", (p, Path(root).name, rel, st.st_size, st.st_mtime, digest))
        if n % 2000 == 0:
            con.commit()
            print(f"hash: {n} files, {read / 1e9:.1f} GB read, {time.time() - t:.0f} s", flush=True)
    con.commit()
    print(f"hash: done, {n} files, {read / 1e9:.1f} GB read, {time.time() - t:.0f} s", flush=True)


def drive_md5(listing_dir: Path) -> dict[tuple[str, int], str]:
    out: dict[tuple[str, int], str] = {}
    for f in sorted(listing_dir.glob("listing_*.json")):
        top = f.stem[len("listing_"):]
        for item in json.loads(f.read_text(encoding="utf-8")):
            md5 = ((item.get("Hashes") or {}).get("md5") or (item.get("Hashes") or {}).get("MD5") or "").lower()
            if md5:
                out.setdefault((md5, int(item.get("Size") or 0)), f"{top}/{item['Path']}")
    return out


def step_compare(con: sqlite3.Connection, listing_dir: Path, files: list[str] | None = None) -> None:
    """Mark ``on_drive``/``missing`` from the listings; ``files`` limits the rows re-marked (T-241)."""
    index = drive_md5(listing_dir)
    wanted = _wanted(files)
    rows = [r for r in con.execute("SELECT path, md5, size FROM local_file "
                                   "WHERE md5 IS NOT NULL AND deleted_at IS NULL").fetchall()
            if wanted is None or _norm(r[0]) in wanted]
    on, missing_bytes = 0, 0
    for path, md5, size in rows:
        hit = index.get((md5, size))
        on += bool(hit)
        missing_bytes += 0 if hit else (size or 0)
        con.execute("UPDATE local_file SET status = ?, drive_path = ? WHERE path = ?",
                    ("on_drive" if hit else "missing", hit, path))
    con.commit()
    print(f"compare: {on} of {len(rows)} on Drive, {len(rows) - on} missing ({missing_bytes / 1e9:.1f} GB)")


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _under(path: str, folders: list[str]) -> bool:
    """True when ``path`` is one of ``folders`` (normalised) or inside one, on a folder boundary: ``raw_other`` is
    not under ``raw`` (T-215)."""
    p = _norm(path)
    return any(p == f or p.startswith(f.rstrip(os.sep) + os.sep) for f in folders)


def _kept(path: str, prefixes: list[str]) -> bool:
    return _under(path, prefixes)


def _wanted(files: list[str] | None) -> set[str] | None:
    return None if files is None else {_norm(p) for p in files}


def _candidates(roots: list[str], files: list[str] | None) -> Iterator[tuple[str, str]]:
    """(path, root) pairs: every file under ``roots``, or exactly ``files`` when given (T-241)."""
    if files is not None:
        norm_roots = [(r, _norm(r)) for r in roots]
        for p in files:
            for root, norm in norm_roots:
                if _under(p, [norm]):
                    yield p, root
                    break
        return
    for root in roots:
        for dirpath, _dirs, names in os.walk(root):
            for name in names:
                yield os.path.join(dirpath, name), root


def step_upload(con: sqlite3.Connection, listing_dir: Path, roots: list[str], bwlimit: str,
                keep: list[str] | None = None, files: list[str] | None = None) -> None:
    """``keep``: path prefixes not uploaded either (the research library is already on the shared Drive).
    ``files``: upload only these paths (T-241)."""
    prefixes = [_norm(k) for k in (keep or [])]
    wanted = _wanted(files)
    by_root = {Path(r).name: r for r in roots}
    for name, root in by_root.items():
        rels = [r for (p, r) in con.execute("SELECT path, rel FROM local_file WHERE status='missing' AND root=? "
                                            "AND deleted_at IS NULL", (name,))
                if not _kept(p, prefixes) and (wanted is None or _norm(p) in wanted)]
        if not rels:
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            fh.write("\n".join(rels) + "\n")
            listfile = fh.name
        dest = f"{REMOTE}/{UPLOAD_PREFIX}/{name}"
        print(f"upload: {len(rels)} files from {root} to {dest}", flush=True)
        rc = subprocess.run(["rclone", "copy", root, dest, "--files-from", listfile, "--checksum", "--copy-links", "--transfers", "8",
                             "--checkers", "8", "--drive-chunk-size", "32M", "--tpslimit", "10", "--retries", "10",
                             "--low-level-retries", "20", "--bwlimit", bwlimit, "--stats", "5m", "--stats-one-line",
                             "-v"], creationflags=NO_WINDOW).returncode
        os.unlink(listfile)
        print(f"upload: {name} rclone exit {rc}", flush=True)
    listing = listing_dir / f"listing_{UPLOAD_PREFIX}.json"
    with open(listing, "w", encoding="utf-8") as fh:
        subprocess.run(["rclone", "lsjson", "-R", "--files-only", "--hash", "--fast-list", f"{REMOTE}/{UPLOAD_PREFIX}"],
                       stdout=fh, check=True, creationflags=NO_WINDOW)
    step_compare(con, listing_dir, files)


def step_delete(con: sqlite3.Connection, really: bool, keep: list[str] | None = None,
                roots: list[str] | None = None, files: list[str] | None = None) -> None:
    """Delete only files under ``roots`` (the ``--root`` folders of this call; T-215: the manifest keeps every root
    ever hashed, and a global delete would have removed 603 GB). ``keep``: path prefixes never deleted (Shivam 7 Nov:
    the research library ``raw/user_research`` stays local). ``files``: delete only these paths (T-241)."""
    if not roots:
        raise ValueError("step_delete needs the --root folders to delete from")
    folders = [_norm(r) for r in roots]
    prefixes = [_norm(k) for k in (keep or [])]
    wanted = _wanted(files)
    rows = [(p, s) for p, s in con.execute(
        "SELECT path, size FROM local_file WHERE status='on_drive' AND deleted_at IS NULL")
        if _under(p, folders) and not _kept(p, prefixes) and (wanted is None or _norm(p) in wanted)]
    total = sum(s for _, s in rows)
    if not really:
        print(f"delete (dry run): {len(rows)} files, {total / 1e9:.1f} GB would be removed; pass --delete")
        return
    gone = 0
    for path, _size in rows:
        if is_database(path):
            continue
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"delete: kept {path}: {exc}")
            continue
        gone += 1
        con.execute("UPDATE local_file SET deleted_at = datetime('now') WHERE path = ?", (path,))
        if gone % 2000 == 0:
            con.commit()
    con.commit()
    print(f"delete: {gone} files removed, {total / 1e9:.1f} GB")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", action="append", required=True)
    ap.add_argument("--listing-dir", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--bwlimit", default="0")
    ap.add_argument("--delete", action="store_true", help="really delete in the delete step")
    ap.add_argument("--keep", action="append", default=[], help="path prefix never uploaded or deleted (repeatable)")
    ap.add_argument("--files-from", default=None,
                    help="text file of absolute paths; only these are hashed, uploaded and deleted (T-241)")
    ap.add_argument("steps", nargs="+", choices=["hash", "compare", "upload", "delete"])
    a = ap.parse_args(argv)
    files = None
    if a.files_from:
        text = Path(a.files_from).read_text(encoding="utf-8")
        files = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    con = open_manifest(a.manifest)
    for step in a.steps:
        if step == "hash":
            step_hash(con, a.root, files)
        elif step == "compare":
            step_compare(con, Path(a.listing_dir))
        elif step == "upload":
            step_upload(con, Path(a.listing_dir), a.root, a.bwlimit, a.keep, files)
        else:
            step_delete(con, a.delete, a.keep, a.root, files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
