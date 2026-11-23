"""T-241: move a finished universe company's raw files to Drive and archive its stores, while the build runs.

    python -m reality_engine.scripts.universe_to_drive --root D:/RealityEngine/tg_build/universe_fy27 --delete

The follow builder writes ``cNN/cNN_measure.json`` when a company is done (``universe_follow_build``). Every
``--poll`` seconds this asks the state database ``<root>/to_drive.db`` which of those companies are not recorded
yet, maps queue position NN to its ISIN and symbol through ``<root>/universe_fy27.csv``, and for each:

  raw     the ISIN's ``status='ok'`` paths from the history fetch manifest
          (``pilot/pilot60_history_manifest.db``) go through ``raw_to_drive``'s hash/compare/upload with
          ``--files-from``, so only this company's files move. ``--delete`` removes a local file only when its md5
          and size are on Drive. A company with no measure json is never touched, so a running build keeps the
          files it reads.
  stores  ``cNN.db`` and ``pages.db`` are copied with the sqlite backup API (a consistent snapshot of the live WAL
          database; ``-wal``/``-shm`` are never uploaded) to a temp file, md5-checked, uploaded with
          ``rclone copyto`` to ``gdrive:InfoDiffusion_archive/universe_fy27/stores/cNN_<SYM>/`` and md5-checked
          again on Drive.

A company is recorded in ``to_drive.db`` only when its stores are on Drive and every raw file is on Drive (and,
with ``--delete``, gone locally); a failure keeps the local files, prints the error and is retried on the next
poll. ``--dry-run`` lists the companies and byte totals without hashing, uploading or deleting.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from reality_engine.config import DATA_DIR, RAW_ROOT  # noqa: E402
from reality_engine.scripts import raw_to_drive as raw  # noqa: E402

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
DATA_ROOT = Path(os.environ.get("REALITY_DATA_ROOT") or DATA_DIR)
MANIFEST_DB = DATA_ROOT / "pilot" / "pilot60_history_manifest.db"
STORES_REMOTE = f"{raw.REMOTE}/universe_fy27/stores"


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def rclone(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """rclone with no console window and no shell (T-241 pitfall)."""
    return subprocess.run(["rclone", *args], check=check, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", creationflags=CREATE_NO_WINDOW)


def open_state(path: Path, readonly: bool = False) -> sqlite3.Connection | None:
    if readonly:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True) if path.is_file() else None
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS company (name TEXT PRIMARY KEY, symbol TEXT, isin TEXT, "
                "measure_at TEXT, raw_files INTEGER, raw_bytes INTEGER, raw_on_drive INTEGER, "
                "raw_deleted_at TEXT, stores_at TEXT, store_md5 TEXT)")
    con.commit()
    return con


def recorded(state: sqlite3.Connection | None) -> dict[str, tuple[str | None, int | None]]:
    """name -> (raw_deleted_at, raw_files) for the companies already moved ({} for a new state db)."""
    if state is None:
        return {}
    try:
        return {name: (deleted, files) for name, deleted, files in state.execute(
            "SELECT name, raw_deleted_at, raw_files FROM company")}
    except sqlite3.OperationalError:
        return {}


def pending(root: Path, state: sqlite3.Connection | None, delete: bool) -> list[tuple[str, Path]]:
    """Finished companies (``cNN/cNN_measure.json``) not in the state db, or whose kept raw files still need deleting."""
    done = recorded(state)
    out: list[tuple[str, Path]] = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        name = d.name
        if not d.is_dir() or not name.startswith("c") or not name[1:].isdigit():
            continue
        if not (d / f"{name}_measure.json").is_file():
            continue
        row = done.get(name)
        if row is None or (delete and row[1] and not row[0]):
            out.append((name, d))
    return out


def queue(universe: Path) -> list[dict[str, str]]:
    with universe.open(encoding="utf-8", newline="") as fh:
        return [r for r in csv.DictReader(fh) if str(r.get("symbol") or "").strip()]


def raw_paths(manifest_db: Path, isin: str) -> list[tuple[str, int]]:
    """(local path, bytes) of every file the history fetch downloaded for ``isin``."""
    con = sqlite3.connect(f"file:{manifest_db}?mode=ro", uri=True, timeout=120)
    try:
        rows = con.execute("SELECT DISTINCT local_path, bytes FROM docs WHERE isin=? AND status='ok' "
                           "AND local_path IS NOT NULL", (isin,)).fetchall()
    finally:
        con.close()
    return [(str(p), int(b or 0)) for p, b in rows]


def statuses(raw_con: sqlite3.Connection, paths: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in range(0, len(paths), 400):
        chunk = paths[i:i + 400]
        marks = ",".join("?" * len(chunk))
        for p, s in raw_con.execute(f"SELECT path, status FROM local_file WHERE path IN ({marks})", chunk):
            if s:
                out[p] = s
    return out


def move_raws(paths: list[str], args: argparse.Namespace, raw_con: sqlite3.Connection, listing_dir: Path) -> None:
    """Move exactly ``paths`` with raw_to_drive's steps; raise (keeping the local files) unless all are on Drive."""
    raw.step_hash(raw_con, [str(args.raw_root)], paths)
    raw.step_compare(raw_con, listing_dir, paths)
    marks = statuses(raw_con, paths)
    missing = [p for p in paths if marks.get(p) != "on_drive"]
    if missing:
        print(f"upload: {len(missing)} raw files", flush=True)
        raw.step_upload(raw_con, listing_dir, [str(args.raw_root)], "0", files=paths)
        marks = statuses(raw_con, paths)
        missing = [p for p in paths if marks.get(p) != "on_drive"]
        if missing:
            raise RuntimeError(f"{len(missing)} raw files are not on Drive after upload; local copies kept")
    if args.delete:
        raw.step_delete(raw_con, really=True, roots=[str(args.raw_root)], files=paths)
        left = [p for p in paths if os.path.isfile(p)]
        if left:
            raise RuntimeError(f"{len(left)} raw files could not be deleted; local copies kept")


def upload_store(store_dir: Path, name: str, symbol: str, dbname: str) -> str | None:
    """Backup ``dbname`` (consistent WAL snapshot) and put it on Drive; returns its md5, or None when absent."""
    src = store_dir / dbname
    if not src.is_file():
        return None
    tmp = store_dir / f".to_drive_{dbname}"
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass
    try:
        src_con = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=120)
        try:
            dst = sqlite3.connect(tmp)
            try:
                src_con.backup(dst)
            finally:
                dst.close()
        finally:
            src_con.close()
        md5 = raw.md5_of(str(tmp))
        remote = f"{STORES_REMOTE}/{name}_{symbol}/{dbname}"
        cur = rclone(["md5sum", remote], check=False)
        first = (cur.stdout or "").split()
        if cur.returncode == 0 and first and first[0].lower() == md5:
            return md5
        rclone(["copyto", str(tmp), remote, "--checksum", "--retries", "10", "--low-level-retries", "20",
                "--tpslimit", "10"])
        got = rclone(["md5sum", remote])
        if not (got.stdout or "").startswith(md5):
            raise RuntimeError(f"{dbname}: Drive md5 differs from the local backup")
        return md5
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def process(d: Path, isin: str, symbol: str, args: argparse.Namespace, state: sqlite3.Connection,
            raw_con: sqlite3.Connection, listing_dir: Path) -> None:
    name = d.name
    measure = d / f"{name}_measure.json"
    old = state.execute("SELECT stores_at, store_md5 FROM company WHERE name=?", (name,)).fetchone()
    if old and old[0]:
        stores_at, store_md5 = str(old[0]), str(old[1] or "{}")
    else:
        md5s: dict[str, str] = {}
        for dbname in (f"{name}.db", "pages.db"):
            digest = upload_store(d, name, symbol, dbname)
            if digest:
                md5s[dbname] = digest
        if not md5s:
            raise RuntimeError(f"no store database under {d}")
        stores_at, store_md5 = now(), json.dumps(md5s)
        print(f"stores: {', '.join(md5s)} -> {STORES_REMOTE}/{name}_{symbol}/", flush=True)
    paths = raw_paths(args.manifest_db, isin)
    local = [p for p, _b in paths if os.path.isfile(p)]
    if local:
        move_raws(local, args, raw_con, listing_dir)
    marks = statuses(raw_con, [p for p, _b in paths])
    # A manifest path with no local file and no row here was moved by an earlier raw_to_drive run (its own manifest
    # db) or never landed; only a file still on this disk and not on Drive blocks the record (Wolf, 24 Nov).
    lost = [p for p, _b in paths if marks.get(p) != "on_drive" and os.path.isfile(p)]
    if lost:
        raise RuntimeError(f"{len(lost)} raw files are not on Drive; local copies kept")
    state.execute("INSERT OR REPLACE INTO company (name, symbol, isin, measure_at, raw_files, raw_bytes, "
                  "raw_on_drive, raw_deleted_at, stores_at, store_md5) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (name, symbol, isin, datetime.fromtimestamp(measure.stat().st_mtime).isoformat(timespec="seconds"),
                   len(paths), sum(b for _p, b in paths), len(paths), now() if args.delete else None,
                   stores_at, store_md5))
    state.commit()


def dry_run(root: Path, state: sqlite3.Connection | None, args: argparse.Namespace,
            rows: list[dict[str, str]]) -> None:
    todo = pending(root, state, args.delete)
    total_raw = total_store = 0
    for name, d in todo:
        pos = int(name[1:])
        if pos > len(rows):
            print(f"DRY RUN {name}: no queue row {pos}")
            continue
        info = rows[pos - 1]
        isin = str(info["isin"]).strip().upper()
        symbol = str(info["symbol"]).strip().upper()
        local = [(p, b) for p, b in raw_paths(args.manifest_db, isin) if os.path.isfile(p)]
        raw_bytes = sum(b or os.path.getsize(p) for p, b in local)
        store_bytes = sum(f.stat().st_size for f in (d / f"{name}.db", d / "pages.db") if f.is_file())
        total_raw += raw_bytes
        total_store += store_bytes
        print(f"DRY RUN {name} {symbol} ({isin}): {len(local)} raw files, {raw_bytes / 1e9:.2f} GB; "
              f"stores {store_bytes / 1e6:.1f} MB")
    print(f"DRY RUN: {len(todo)} companies, {total_raw / 1e9:.2f} GB raw, {total_store / 1e6:.1f} MB stores; "
          f"nothing hashed, uploaded or deleted")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="universe build root holding the cNN/ directories")
    ap.add_argument("--universe", default=None, help="default <root>/universe_fy27.csv")
    ap.add_argument("--manifest-db", default=str(MANIFEST_DB), help="history fetch manifest (docs table)")
    ap.add_argument("--raw-root", default=str(RAW_ROOT), help="parent of pilot60_history; its name is the rclone top")
    ap.add_argument("--raw-manifest", default=None, help="default <raw-root>/../drive_index/raw_to_drive.db")
    ap.add_argument("--listing-dir", default=None, help="default <root>/drive_index (raw_to_drive listings)")
    ap.add_argument("--delete", action="store_true", help="delete a local raw file once its md5+size are on Drive")
    ap.add_argument("--dry-run", action="store_true", help="list companies and bytes; hash, upload and delete nothing")
    ap.add_argument("--once", action="store_true", help="one pass, then exit")
    ap.add_argument("--poll", type=float, default=300.0, help="seconds between passes")
    a = ap.parse_args(argv)
    root = Path(a.root)
    universe = Path(a.universe) if a.universe else root / "universe_fy27.csv"
    args = argparse.Namespace(**vars(a))
    args.root, args.universe = root, universe
    args.manifest_db = Path(a.manifest_db)
    args.raw_root = Path(a.raw_root)
    shared = args.raw_root.parent / "drive_index"
    args.raw_manifest = Path(a.raw_manifest) if a.raw_manifest else shared / "raw_to_drive.db"
    args.listing_dir = Path(a.listing_dir) if a.listing_dir else root / "drive_index"
    if not universe.is_file():
        print(f"STOPPED: universe csv not found: {universe}", file=sys.stderr)
        return 2
    if a.dry_run:
        dry_run(root, open_state(root / "to_drive.db", readonly=True), args, queue(universe))
        return 0
    args.listing_dir.mkdir(parents=True, exist_ok=True)
    args.raw_manifest.parent.mkdir(parents=True, exist_ok=True)
    state = open_state(root / "to_drive.db")
    assert state is not None
    raw_con = raw.open_manifest(str(args.raw_manifest))
    rows = queue(universe)
    while True:
        todo = pending(root, state, a.delete)
        # One rclone copy and one Drive listing per pass for every finished company's raw files (Wolf review: per
        # company, each upload re-listed all of msi_raw, minutes per company at 4,652 companies).
        batch_paths = []
        for name, _d in todo:
            pos = int(name[1:])
            if pos <= len(rows) and str(rows[pos - 1].get("isin") or "").strip():
                isin = str(rows[pos - 1]["isin"]).strip().upper()
                batch_paths += [p for p, _b in raw_paths(args.manifest_db, isin) if os.path.isfile(p)]
        if batch_paths:
            try:
                move_raws(batch_paths, args, raw_con, args.listing_dir)
            except Exception as exc:  # per-company processing below reports and retries what is still local
                print(f"batch raw move: ERROR {exc}", flush=True)
        for name, d in todo:
            pos = int(name[1:])
            if pos > len(rows) or not str(rows[pos - 1].get("isin") or "").strip():
                print(f"{name}: no queue row {pos} in {universe}", flush=True)
                continue
            info = rows[pos - 1]
            isin = str(info["isin"]).strip().upper()
            symbol = str(info["symbol"]).strip().upper()
            try:
                process(d, isin, symbol, args, state, raw_con, args.listing_dir)
                print(f"{name} {symbol}: done", flush=True)
            except Exception as exc:  # one company must never stop the sweep; it is retried next poll
                print(f"{name} {symbol}: ERROR {exc}; local files kept, retried next poll", flush=True)
        if a.once:
            return 0
        time.sleep(a.poll)


if __name__ == "__main__":
    sys.exit(main())
