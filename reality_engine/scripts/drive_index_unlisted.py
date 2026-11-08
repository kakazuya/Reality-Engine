"""T-126: put every Drive raw file the T-102 manifest does not know into that manifest, so readers find it.

The T-102 manifest (``raw_to_drive.db``, table ``local_file``) lists only the files THIS laptop uploaded.  Files
another machine put on Drive (``pdfs/``, ``D_pdfs/``, the 17 Oct ``arch17`` upload, ``msi_raw/``, ``decks/``,
``results_pdfs/``) were invisible to ``raw_store.RawStore`` and so to ``pilot3.docs_collect``: on 8 Nov the hold-out
stores of 10 of 12 companies stopped at March 2024 although 282 of their 308 FY25-FY27 transcripts, decks and
annual reports sit on Drive.

    1. list    ``rclone lsjson -R --files-only --hash`` of each Drive top into ``--listing-dir/<top>.json``
               (``arch17`` through the read-only remote ``raw_store`` already uses)
    2. index   every listed file goes into table ``drive_file`` (Drive path, size, md5, sha256, Drive id); a file
               whose Drive path no ``local_file`` row names, and whose top maps onto a raw-store root, also gets a
               ``local_file`` row (``status='on_drive_unlisted'``, ``path='drive:<drive path>'``) so the
               ``RawStore`` walk, ``exists`` and fetch see it.  A (root, rel) already in ``local_file`` is left as is.

    python -m reality_engine.scripts.drive_index_unlisted --listing-dir <dir> list index [--dry-run]

Idempotent: re-running replaces ``drive_file`` rows and skips paths already indexed.  The manifest is copied to
``<manifest>.bak-<stamp>`` before the first write of a run.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from reality_engine import raw_store

#: Drive top -> (raw-store root name, prefix under that root) by the leading path parts.  Longest match wins.
MAP: list[tuple[str, str, str]] = [
    ("arch17/InfoDiffusion_to_upload/pdfs/", "pdfs", ""),
    ("arch17/InfoDiffusion_to_upload/decks/", "raw", "decks/"),
    ("arch17/pdfs/", "pdfs", ""),
    ("msi_raw/pdfs/", "pdfs", ""),
    ("msi_raw/raw/", "raw", ""),
    ("msi_raw/sandbox/", "sandbox", ""),
    ("pdfs/", "pdfs", ""),
    ("D_pdfs/", "pdfs", ""),
    ("decks/", "raw", "decks/"),
    ("results_pdfs/", "raw", "results_pdfs/"),
]
TOPS = ("pdfs", "D_pdfs", "msi_raw", "hp_raw", "decks", "results_pdfs", raw_store.ARCH17_TOP)

SCHEMA = """CREATE TABLE IF NOT EXISTS drive_file (
  drive_path TEXT PRIMARY KEY, size INTEGER, md5 TEXT, sha256 TEXT, drive_id TEXT, mod_time TEXT,
  root TEXT, rel TEXT, listed_at TEXT);
CREATE INDEX IF NOT EXISTS drive_file_sha ON drive_file(sha256);
CREATE INDEX IF NOT EXISTS drive_file_md5 ON drive_file(md5);"""


def map_path(drive_path: str) -> tuple[str, str] | None:
    """(root, rel) a reader would ask for, or None when the top has no raw-store root."""
    for prefix, root, under in sorted(MAP, key=lambda m: len(m[0]), reverse=True):
        if drive_path.startswith(prefix):
            rest = drive_path[len(prefix):]
            return (root, under + rest) if rest else None
    return None


def list_tops(listing_dir: Path, tops=TOPS) -> None:
    listing_dir.mkdir(parents=True, exist_ok=True)
    for top in tops:
        if top == raw_store.ARCH17_TOP:
            src, extra = raw_store.ARCH17_REMOTE, [f"--drive-root-folder-id={raw_store.ARCH17_ROOT_ID}"]
        else:
            src, extra = f"{raw_store.ARCHIVE}/{top}", []
        out = listing_dir / f"{top}.json"
        with open(out, "w", encoding="utf-8") as handle:
            proc = subprocess.run(["rclone", "lsjson", "-R", "--files-only", "--hash", "--fast-list", *extra, src],
                                  stdout=handle, stderr=subprocess.PIPE, text=True, timeout=3600)
        if proc.returncode != 0:
            raise RuntimeError(f"rclone lsjson {top} exited {proc.returncode}: {proc.stderr[-500:]}")
        print(f"listed {top}: {out.stat().st_size} bytes")


def index(listing_dir: Path, manifest: Path, dry_run: bool = False) -> dict:
    con = sqlite3.connect(manifest, timeout=60)
    known = {r[0] for r in con.execute("SELECT drive_path FROM local_file WHERE drive_path IS NOT NULL")}
    keys = {(str(r[0]).lower(), str(r[1]).replace("\\", "/").lower())
            for r in con.execute("SELECT root, rel FROM local_file WHERE drive_path IS NOT NULL AND drive_path != ''")}
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    files, local_rows, stats = [], [], {"listed": 0, "unlisted": 0, "added": 0, "unmapped": 0, "same_key": 0}
    for top in TOPS:
        path = listing_dir / f"{top}.json"
        if not path.is_file():
            continue
        for item in json.load(open(path, encoding="utf-8")):
            drive = f"{top}/{item['Path']}"
            hashes = item.get("Hashes") or {}
            mapped = map_path(drive)
            files.append((drive, item.get("Size"), hashes.get("md5"), hashes.get("sha256"), item.get("ID"),
                          item.get("ModTime"), *(mapped or (None, None)), now))
            stats["listed"] += 1
            if drive in known:
                continue
            stats["unlisted"] += 1
            if mapped is None:
                stats["unmapped"] += 1
                continue
            key = (mapped[0], mapped[1].lower())
            if key in keys:
                stats["same_key"] += 1          # this laptop's own upload of the same path already serves it
                continue
            keys.add(key)
            local_rows.append((f"drive:{drive}", mapped[0], mapped[1], item.get("Size"), None, hashes.get("md5"),
                               "on_drive_unlisted", drive, None))
            stats["added"] += 1
    if not dry_run:
        con.close()
        shutil.copy2(manifest, manifest.with_name(manifest.name + f".bak-{time.strftime('%Y%m%d%H%M%S')}"))
        con = sqlite3.connect(manifest, timeout=60)
        con.executescript(SCHEMA)
        with con:
            con.executemany("INSERT OR REPLACE INTO drive_file VALUES (?,?,?,?,?,?,?,?,?)", files)
            con.executemany("INSERT OR IGNORE INTO local_file (path, root, rel, size, mtime, md5, status, drive_path,"
                            " deleted_at) VALUES (?,?,?,?,?,?,?,?,?)", local_rows)
    con.close()
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("steps", nargs="+", choices=["list", "index"])
    ap.add_argument("--listing-dir", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, default=raw_store.MANIFEST)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if "list" in args.steps:
        list_tops(args.listing_dir)
    if "index" in args.steps:
        print(json.dumps(index(args.listing_dir, args.manifest, args.dry_run)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
