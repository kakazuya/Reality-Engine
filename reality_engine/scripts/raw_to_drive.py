"""T-102: move every local raw file to the Drive archive, so raw files live only on Drive (Shivam, 7 Nov 2026).

Four steps, each resumable, each recorded in the manifest (a small SQLite file, ``--manifest``):

    hash     md5 of every non-database file under each ``--root`` (Drive's own hash is md5, so a local file can be
             matched with any Drive file whatever its path); a file with the same size and mtime is not re-read
    compare  ``on_drive`` when some Drive file in ``--listing-dir`` (the ``listing_*.json`` written by
             ``rclone lsjson -R --files-only --hash``) has the same md5 and size; otherwise ``missing``
    upload   ``rclone copy --files-from`` of the missing files to ``gdrive:InfoDiffusion_archive/msi_raw/<root>/<rel>``
             with ``--checksum``, then a fresh listing of ``msi_raw`` re-runs ``compare``
    delete   removes a local file only when its md5 and size are on Drive (``--delete``; the default lists what it
             would remove). Never touches a database file.

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
from pathlib import Path

REMOTE = "gdrive:InfoDiffusion_archive"
UPLOAD_PREFIX = "msi_raw"
DB_EXT = {".db", ".sqlite", ".sqlite3", ".duckdb", ".db-wal", ".db-shm", ".wal", ".shm", ".sql", ".parquet",
          ".lance", ".npy"}


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


def step_hash(con: sqlite3.Connection, roots: list[str]) -> None:
    known = {p: (s, m) for p, s, m in con.execute("SELECT path, size, mtime FROM local_file WHERE md5 IS NOT NULL")}
    t, n, read = time.time(), 0, 0
    for root in roots:
        name = Path(root).name
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                p = os.path.join(dirpath, f)
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
                            "VALUES (?,?,?,?,?,?,NULL)", (p, name, rel, st.st_size, st.st_mtime, digest))
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


def step_compare(con: sqlite3.Connection, listing_dir: Path) -> None:
    index = drive_md5(listing_dir)
    rows = con.execute("SELECT path, md5, size FROM local_file WHERE md5 IS NOT NULL AND deleted_at IS NULL").fetchall()
    on = 0
    for path, md5, size in rows:
        hit = index.get((md5, size))
        on += bool(hit)
        con.execute("UPDATE local_file SET status = ?, drive_path = ? WHERE path = ?",
                    ("on_drive" if hit else "missing", hit, path))
    con.commit()
    print(f"compare: {on} of {len(rows)} on Drive, {len(rows) - on} missing "
          f"({(con.execute('SELECT SUM(size) FROM local_file WHERE status=?', ('missing',)).fetchone()[0] or 0) / 1e9:.1f} GB)")


def step_upload(con: sqlite3.Connection, listing_dir: Path, roots: list[str], bwlimit: str) -> None:
    by_root = {Path(r).name: r for r in roots}
    for name, root in by_root.items():
        rels = [r for (r,) in con.execute("SELECT rel FROM local_file WHERE status='missing' AND root=? "
                                          "AND deleted_at IS NULL", (name,))]
        if not rels:
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            fh.write("\n".join(rels) + "\n")
            listfile = fh.name
        dest = f"{REMOTE}/{UPLOAD_PREFIX}/{name}"
        print(f"upload: {len(rels)} files from {root} to {dest}", flush=True)
        rc = subprocess.run(["rclone", "copy", root, dest, "--files-from", listfile, "--checksum", "--transfers", "8",
                             "--checkers", "8", "--drive-chunk-size", "32M", "--tpslimit", "10", "--retries", "10",
                             "--low-level-retries", "20", "--bwlimit", bwlimit, "--stats", "5m", "--stats-one-line",
                             "-v"]).returncode
        os.unlink(listfile)
        print(f"upload: {name} rclone exit {rc}", flush=True)
    listing = listing_dir / f"listing_{UPLOAD_PREFIX}.json"
    with open(listing, "w", encoding="utf-8") as fh:
        subprocess.run(["rclone", "lsjson", "-R", "--files-only", "--hash", "--fast-list", f"{REMOTE}/{UPLOAD_PREFIX}"],
                       stdout=fh, check=True)
    step_compare(con, listing_dir)


def step_delete(con: sqlite3.Connection, really: bool) -> None:
    rows = con.execute("SELECT path, size FROM local_file WHERE status='on_drive' AND deleted_at IS NULL").fetchall()
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
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", action="append", required=True)
    ap.add_argument("--listing-dir", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--bwlimit", default="0")
    ap.add_argument("--delete", action="store_true", help="really delete in the delete step")
    ap.add_argument("steps", nargs="+", choices=["hash", "compare", "upload", "delete"])
    a = ap.parse_args(argv)
    con = open_manifest(a.manifest)
    for step in a.steps:
        if step == "hash":
            step_hash(con, a.root)
        elif step == "compare":
            step_compare(con, Path(a.listing_dir))
        elif step == "upload":
            step_upload(con, Path(a.listing_dir), a.root, a.bwlimit)
        else:
            step_delete(con, a.delete)
    return 0


if __name__ == "__main__":
    sys.exit(main())
