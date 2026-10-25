"""Store investor-presentation page text in ``deck_figures.db:deck_page_text``.

The deck reader currently re-fetches each PDF from Drive (about 15 s) whenever a
page is read.  This job extracts the text layer once with PyMuPDF and indexes it
in FTS5, newest decks first and resumable.

Source of a PDF: ``deck_sources.local_path`` when the file exists; otherwise a
copy already under ``REALITY_RAW_ROOT/deck_page_text/<sha[:2]>/<sha>.pdf``;
otherwise ``reality_engine.toolbelt.drive_fetch`` (by sha256, from the Drive
``decks`` folder).  Downloaded PDFs stay in the raw root, never in
``reality_engine/data``.

A page with fewer than 40 characters is stored with ``method='empty'`` (OCR is a
later pass).  A deck is committed in one transaction, so a crash retries the
whole deck instead of leaving a hole.

Usage:
    python -m reality_engine.scripts.build_deck_page_text
    python -m reality_engine.scripts.build_deck_page_text --limit 50 --since 2026-01-01
    python -m reality_engine.scripts.build_deck_page_text --offline   # local/cached PDFs only
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from reality_engine.toolbelt._common import resolve_db
from reality_engine.toolbelt import drive_fetch

EMPTY_CHARS = 40
METHOD = "pymupdf"
DEFAULT_RAW_ROOT = r"D:\RealityEngine\raw"

DDL = """
CREATE TABLE IF NOT EXISTS deck_page_text (
  sha256 TEXT NOT NULL,
  page_no INTEGER NOT NULL,
  text TEXT NOT NULL,
  chars INTEGER NOT NULL,
  method TEXT NOT NULL,
  extracted_at TEXT NOT NULL,
  PRIMARY KEY (sha256, page_no));
CREATE VIRTUAL TABLE IF NOT EXISTS deck_page_text_fts USING fts5(
  text, content='deck_page_text', content_rowid='rowid', tokenize='unicode61');
CREATE TRIGGER IF NOT EXISTS deck_page_text_ai AFTER INSERT ON deck_page_text BEGIN
  INSERT INTO deck_page_text_fts(rowid, text) VALUES (new.rowid, new.text);
END;
"""


def raw_root(override: str | None) -> Path:
    return Path(override) if override else Path(os.environ.get("REALITY_RAW_ROOT", DEFAULT_RAW_ROOT))


def cached_pdf(sha256: str, root: Path) -> Path:
    return root / "deck_page_text" / sha256[:2] / f"{sha256}.pdf"


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(DDL)
    con.commit()
    # The FTS table may be missing rows if it was created after the base table.
    n_src = con.execute("SELECT COUNT(*) FROM deck_page_text").fetchone()[0]
    n_idx = con.execute("SELECT COUNT(*) FROM deck_page_text_fts_docsize").fetchone()[0]
    if n_src != n_idx:
        con.execute("INSERT INTO deck_page_text_fts(deck_page_text_fts) VALUES ('rebuild')")
        con.commit()


def extract_pdf(sha: str, pdf: Path) -> list[tuple[str, int, str, int, str, str]] | None:
    """``(sha, page_no, text, chars, method, extracted_at)`` per page, or None."""
    import pymupdf

    try:
        doc = pymupdf.open(pdf)
    except Exception as exc:  # noqa: BLE001 - one bad PDF must not stop the run
        print(f"  unreadable {pdf.name}: {type(exc).__name__}: {exc}")
        return None
    now = datetime.now().isoformat(timespec="seconds")
    rows: list[tuple[str, int, str, int, str, str]] = []
    try:
        for page_no in range(1, doc.page_count + 1):
            text = doc[page_no - 1].get_text("text").strip()
            chars = len(text)
            method = METHOD if chars >= EMPTY_CHARS else "empty"
            rows.append((sha, page_no, text, chars, method, now))
    except Exception as exc:  # noqa: BLE001
        print(f"  failed {pdf.name}: {type(exc).__name__}: {exc}")
        return None
    finally:
        doc.close()
    return rows


def fetch_missing(shas: list[str], root: Path) -> dict[str, Path]:
    """Download the shas that are not cached; returns sha -> destination."""
    if not shas:
        return {}
    try:
        result = drive_fetch.fetch(shas, dest=str(root / "deck_page_text"),
                                   folder="decks", verify=True, transfers=8)
    except Exception as exc:  # noqa: BLE001 - network/rclone failure is not fatal
        print(f"  drive fetch failed: {type(exc).__name__}: {exc}")
        return {}
    out: dict[str, Path] = {}
    for item in result["items"]:
        sha = item["input"]
        if item.get("status") != "ok":
            print(f"  no PDF for {sha[:12]}: {item.get('status')} {item.get('reason') or ''}".rstrip())
            continue
        source = Path(item["dest"])
        target = cached_pdf(sha, root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source != target:
            if target.exists():
                source.unlink(missing_ok=True)
            else:
                source.replace(target)
        out[sha] = target
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extract deck page text into deck_figures.db:deck_page_text.")
    ap.add_argument("--db", help="deck_figures database (default: REALITY_DATA_ROOT/deck_figures.db)")
    ap.add_argument("--limit", type=int, help="decks to process in this run")
    ap.add_argument("--since", help="only decks with known_at >= YYYY-MM-DD")
    ap.add_argument("--raw-root", help=f"raw PDF root (default: REALITY_RAW_ROOT or {DEFAULT_RAW_ROOT})")
    ap.add_argument("--offline", action="store_true", help="use only local/cached PDFs, never Drive")
    args = ap.parse_args(argv)

    db = resolve_db(args.db or "deck_figures")
    root = raw_root(args.raw_root)
    con = sqlite3.connect(db, timeout=600)
    con.execute("PRAGMA busy_timeout = 600000")
    ensure_schema(con)

    sql = """SELECT s.sha256, max(s.local_path)
             FROM deck_sources s
             WHERE s.status = 'ok' AND s.sha256 IS NOT NULL AND s.sha256 <> ''
               AND NOT EXISTS (SELECT 1 FROM deck_page_text t WHERE t.sha256 = s.sha256)"""
    params: list[object] = []
    if args.since:
        sql += " AND s.known_at >= ?"
        params.append(args.since)
    sql += " GROUP BY s.sha256 ORDER BY max(s.known_at) DESC"
    if args.limit:
        sql += " LIMIT ?"
        params.append(args.limit)
    decks = con.execute(sql, params).fetchall()

    pdfs: dict[str, Path] = {}
    missing: list[str] = []
    for sha, local_path in decks:
        if local_path and Path(local_path).exists():
            pdfs[sha] = Path(local_path)
        elif cached_pdf(sha, root).exists():
            pdfs[sha] = cached_pdf(sha, root)
        elif not args.offline:
            missing.append(sha)
    if missing:
        print(f"fetching {len(missing)} PDFs from Drive ...")
        pdfs.update(fetch_missing(missing, root))

    done = skipped = pages = empty = 0
    # ponytail: one process, decks one by one; parallelise if extraction dominates a full backfill.
    for sha, _local_path in decks:
        pdf = pdfs.get(sha)
        if pdf is None:
            skipped += 1
            continue
        rows = extract_pdf(sha, pdf)
        if rows is None:
            skipped += 1
            continue
        with con:
            con.executemany("INSERT OR IGNORE INTO deck_page_text VALUES (?,?,?,?,?,?)", rows)
        done += 1
        pages += len(rows)
        deck_empty = sum(1 for row in rows if row[4] == "empty")
        empty += deck_empty
        print(f"  {sha[:12]} {pdf.name[:48]}: {len(rows)} pages ({deck_empty} empty)")

    con.close()
    print(f"deck_page_text: {done} decks, {pages} pages ({empty} empty), {skipped} skipped, "
          f"{len(decks)} selected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
