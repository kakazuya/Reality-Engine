"""T-241: move fetched raw files to Drive without building stores first (Shivam, 24 Nov 2026 13:35).

    python -m reality_engine.scripts.raw_only_to_drive --delete --poll 600

Shivam: "Don't worry about the store build ... Just download their files and send them up onto Google Drive." The
store build is paused; hy4 keeps reading the stores already built. This loop takes every company (ISIN) of the history
fetch manifest (``pilot/pilot60_history_manifest.db``, table ``docs``) that has no ``pending`` document left, and moves
its ``status='ok'`` files that still exist locally through ``universe_to_drive.move_raws`` (raw_to_drive's md5 hash,
compare with the Drive listing, upload, and with ``--delete`` a local delete only when md5 and size are on Drive). A
later store build reads these files back from Drive through ``raw_store``.

It never touches stores or the ``to_drive.db`` state of ``universe_to_drive``; that one still uploads the stores of
companies whose build finished. A company still being fetched (any ``pending`` row) is skipped until the next poll.
Files newer than ``--min-age`` seconds are left for the next poll as well, so a file being written is never moved.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from reality_engine.config import RAW_ROOT  # noqa: E402
from reality_engine.scripts import raw_to_drive as raw  # noqa: E402
from reality_engine.scripts import universe_to_drive as u2d  # noqa: E402


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def finished_companies(manifest_db: Path) -> list[str]:
    """ISINs whose every manifest row has left ``pending`` (the fetch is done with them)."""
    con = sqlite3.connect(f"file:{manifest_db}?mode=ro", uri=True, timeout=120)
    try:
        return [r[0] for r in con.execute(
            "SELECT isin FROM docs WHERE isin IS NOT NULL GROUP BY isin "
            "HAVING SUM(status='pending') = 0 AND SUM(status='ok') > 0 ORDER BY isin")]
    finally:
        con.close()


def local_files(manifest_db: Path, isin: str, min_age: float, now_ts: float | None = None) -> list[str]:
    """This ISIN's downloaded files still on disk and older than ``min_age`` seconds."""
    now_ts = time.time() if now_ts is None else now_ts
    out = []
    for path, _ in u2d.raw_paths(manifest_db, isin):
        try:
            st = os.stat(path)
        except OSError:
            continue                    # already moved (or never kept)
        if now_ts - st.st_mtime >= min_age:
            out.append(path)
    return out


def one_pass(args: argparse.Namespace) -> tuple[int, int]:
    """Move every finished company's local files in ONE batch (one hash, one upload, one Drive listing per pass;
    a per-company call would list all of msi_raw once per company). Returns (companies, files deleted or on Drive)."""
    raw_con = raw.open_manifest(str(args.raw_manifest))
    try:
        batch: list[str] = []
        companies = 0
        for isin in finished_companies(Path(args.manifest)):
            paths = local_files(Path(args.manifest), isin, args.min_age)
            if paths:
                batch += paths
                companies += 1
            if len(batch) >= args.max_files:
                break
        if not batch:
            return 0, 0
        print(f"{now()} pass: {companies} companies, {len(batch)} files", flush=True)
        roots = [str(args.raw_root)]
        raw.step_hash(raw_con, roots, batch)
        raw.step_compare(raw_con, Path(args.listing_dir), batch)
        marks = u2d.statuses(raw_con, batch)
        missing = [p for p in batch if marks.get(p) != "on_drive"]
        if missing:
            raw.step_upload(raw_con, Path(args.listing_dir), roots, "0", files=missing)
        on_drive = [p for p, st in u2d.statuses(raw_con, batch).items() if st == "on_drive"]
        if args.delete and on_drive:
            raw.step_delete(raw_con, really=True, roots=roots, files=on_drive)   # md5+size on Drive, checked again
        left = [p for p in batch if os.path.isfile(p)] if args.delete else []
        print(f"{now()} on Drive {len(on_drive)} of {len(batch)}; still local {len(left)}", flush=True)
        return companies, len(on_drive)
    finally:
        raw_con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", default=str(u2d.MANIFEST_DB), help="history fetch manifest (docs table)")
    ap.add_argument("--raw-root", default=str(RAW_ROOT), help="parent of pilot60_history; its name is the rclone top")
    ap.add_argument("--raw-manifest", default=None, help="default <raw-root>/../drive_index/raw_to_drive.db")
    ap.add_argument("--delete", action="store_true", help="delete a local file once its md5 and size are on Drive")
    ap.add_argument("--min-age", type=float, default=900, help="leave files younger than this (seconds)")
    ap.add_argument("--poll", type=int, default=0, help="seconds between passes; 0 = one pass")
    ap.add_argument("--max-files", type=int, default=20000, help="files per pass (one upload + listing each)")
    ap.add_argument("--listing-dir", default=None, help="Drive listings (default <raw-root>/../drive_index)")
    a = ap.parse_args(argv)
    a.raw_root = Path(a.raw_root)
    shared = a.raw_root.parent / "drive_index"
    a.raw_manifest = a.raw_manifest or str(shared / "raw_to_drive.db")
    a.listing_dir = a.listing_dir or str(shared)
    Path(a.listing_dir).mkdir(parents=True, exist_ok=True)
    while True:
        companies, files = one_pass(a)
        print(f"{now()} pass done: {companies} companies, {files} files", flush=True)
        if not a.poll:
            return 0
        time.sleep(a.poll)


if __name__ == "__main__":
    raise SystemExit(main())
