"""Store every page of quarterly-results PDFs in ``results_xbrl.db:results_notes``.

Each BSE ``Result`` announcement (``bse_announcements.db:ann``) is downloaded once
into ``REALITY_RAW_ROOT/results_notes_text/<NEWSID>.pdf`` (never under
``reality_engine/data``) and linked to every NSE filing of that scrip whose own
timestamp lands within ``MATCH_WINDOW_SECONDS`` of the announcement.  Every page
of the PDF is stored — ``has_note_word`` marks the pages whose text mentions
"note" — with the announcement time as ``known_at``.  FTS5 indexes the page text.

An announcement is processed once (a standalone/consolidated filing pair does not
duplicate it) and a filing keeps every announcement that matches it, so no basis
is lost.  Resumable: a cached PDF is reused only after it opens as a valid PDF,
and an existing partial store (the old note-pages-only version) is completed from
the cached PDF when it holds fewer pages than the PDF has.

Usage:
    python -m reality_engine.scripts.fetch_results_notes_text
    python -m reality_engine.scripts.fetch_results_notes_text --limit 20 --since 2026-06-30
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from reality_engine.toolbelt._common import resolve_db

DEFAULT_RAW_ROOT = r"D:\RealityEngine\raw"
BSE_PDF = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/{name}"
BSE_HEADERS = {"Referer": "https://www.bseindia.com/",
               "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
NOTE_RE = re.compile(r"\bnotes?\b", re.IGNORECASE)
MATCH_WINDOW_SECONDS = 4 * 24 * 3600
DOWNLOAD_ATTEMPTS = 4  # first try plus 3 backoff retries: 0.5 s, 1 s, 2 s

DDL = """
CREATE TABLE IF NOT EXISTS results_notes (
  isin TEXT NOT NULL,
  period_end TEXT NOT NULL,
  source_newsid TEXT NOT NULL,
  page_no INTEGER NOT NULL,
  text TEXT NOT NULL,
  known_at TEXT,
  has_note_word INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (isin, period_end, source_newsid, page_no));
CREATE INDEX IF NOT EXISTS ix_results_notes_newsid ON results_notes(source_newsid);
CREATE VIRTUAL TABLE IF NOT EXISTS results_notes_fts USING fts5(
  text, content='results_notes', content_rowid='rowid', tokenize='unicode61');
CREATE TRIGGER IF NOT EXISTS results_notes_ai AFTER INSERT ON results_notes BEGIN
  INSERT INTO results_notes_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS results_notes_ad AFTER DELETE ON results_notes BEGIN
  INSERT INTO results_notes_fts(results_notes_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;
"""


def raw_root(override: str | None) -> Path:
    return Path(override) if override else Path(os.environ.get("REALITY_RAW_ROOT", DEFAULT_RAW_ROOT))


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(DDL)
    cols = {row[1] for row in con.execute("PRAGMA table_info(results_notes)")}
    if "has_note_word" not in cols:
        con.execute("ALTER TABLE results_notes ADD COLUMN has_note_word INTEGER NOT NULL DEFAULT 0")
        # Rows written by the note-pages-only version: flag the pages that do mention a note.
        updates = [(rowid,) for rowid, text in
                   con.execute("SELECT rowid, text FROM results_notes WHERE has_note_word = 0")
                   if NOTE_RE.search(text)]
        if updates:
            con.executemany("UPDATE results_notes SET has_note_word = 1 WHERE rowid = ?", updates)
    con.commit()
    n_src = con.execute("SELECT COUNT(*) FROM results_notes").fetchone()[0]
    n_idx = con.execute("SELECT COUNT(*) FROM results_notes_fts_docsize").fetchone()[0]
    if n_src != n_idx:
        con.execute("INSERT INTO results_notes_fts(results_notes_fts) VALUES ('rebuild')")
        con.commit()


def announcement_index(ann_db: Path) -> dict[str, list[tuple[str, str, str]]]:
    """BSE scrip code -> [(DissemDT, NEWSID, ATTACHMENTNAME)] newest first."""
    con = sqlite3.connect(f"file:{ann_db}?mode=ro", uri=True, timeout=120)
    try:
        rows = con.execute(
            "SELECT CAST(SCRIP_CD AS TEXT), DissemDT, NEWSID, ATTACHMENTNAME FROM ann "
            "WHERE CATEGORYNAME = 'Result' AND ATTACHMENTNAME LIKE '%.pdf'").fetchall()
    finally:
        con.close()
    out: dict[str, list[tuple[str, str, str]]] = {}
    for code, dissem, newsid, attachment in rows:
        if not code or not dissem or not newsid or not attachment:
            continue
        out.setdefault(code.strip(), []).append((dissem, newsid, attachment))
    for items in out.values():
        items.sort(reverse=True)
    return out


def match_filings(filings: list[tuple[str, str, str]], ref_ts: str) -> list[tuple[str, str]]:
    """``(isin, period_end)`` of every filing filed within the BSE/NSE skew window."""
    try:
        ref = datetime.fromisoformat(str(ref_ts).replace("Z", "")[:19])
    except (ValueError, TypeError):
        return []
    out: list[tuple[str, str]] = []
    for isin, period_end, ts in filings:
        try:
            at = datetime.fromisoformat(str(ts).replace("Z", "")[:19])
        except (ValueError, TypeError):
            continue
        if abs((at - ref).total_seconds()) <= MATCH_WINDOW_SECONDS:
            out.append((isin, period_end))
    return list(dict.fromkeys(out))


def pdf_page_count(pdf: Path) -> int:
    """Pages of a readable PDF, 0 when the file is truncated or not a PDF."""
    import pymupdf

    try:
        doc = pymupdf.open(pdf)
        try:
            return doc.page_count
        finally:
            doc.close()
    except Exception:  # noqa: BLE001 - a bad cache entry is a cache miss
        return 0


def download(newsid: str, attachment: str, root: Path, offline: bool) -> Path | None:
    dest = root / "results_notes_text" / f"{newsid}.pdf"
    if dest.exists() and dest.stat().st_size > 0 and pdf_page_count(dest) > 0:
        return dest
    if offline:
        return None
    part = dest.with_name(dest.name + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(DOWNLOAD_ATTEMPTS):
        try:
            request = urllib.request.Request(BSE_PDF.format(name=attachment), headers=BSE_HEADERS)
            with urllib.request.urlopen(request, timeout=180) as response:
                content = response.read()
            if not content.startswith(b"%PDF"):
                print(f"  not a PDF {newsid}: {content[:20]!r}")
            else:
                part.write_bytes(content)
                if pdf_page_count(part) > 0:
                    os.replace(part, dest)
                    return dest
                print(f"  truncated PDF {newsid}: {len(content)} bytes")
        except urllib.error.HTTPError as exc:
            print(f"  download failed {newsid} try {attempt + 1}: HTTP {exc.code}")
            if exc.code in (404, 410):  # the attachment is gone; retrying cannot help
                break
        except Exception as exc:  # noqa: BLE001 - one filing must not stop the run
            print(f"  download failed {newsid} try {attempt + 1}: {type(exc).__name__}: {exc}")
        if attempt + 1 < DOWNLOAD_ATTEMPTS:
            time.sleep(0.5 * 2 ** attempt)
    part.unlink(missing_ok=True)
    return None


def page_texts(pdf: Path) -> list[str] | None:
    """Stripped text of every page, or None when the PDF cannot be read."""
    import pymupdf

    try:
        doc = pymupdf.open(pdf)
    except Exception as exc:  # noqa: BLE001
        print(f"  unreadable {pdf.name}: {type(exc).__name__}: {exc}")
        return None
    try:
        if doc.page_count <= 0:
            return None
        return [doc[page_no - 1].get_text("text").strip() for page_no in range(1, doc.page_count + 1)]
    except Exception as exc:  # noqa: BLE001
        print(f"  failed {pdf.name}: {type(exc).__name__}: {exc}")
        return None
    finally:
        doc.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Store every results-PDF page into results_xbrl.db:results_notes.")
    ap.add_argument("--db", help="results_xbrl database (default: REALITY_DATA_ROOT/results_xbrl.db)")
    ap.add_argument("--ann-db", help="bse_announcements database (default: REALITY_DATA_ROOT/bse_announcements.db)")
    ap.add_argument("--limit", type=int, help="Result announcements to process in this run")
    ap.add_argument("--since", help="only filings with period_end >= YYYY-MM-DD")
    ap.add_argument("--raw-root", help=f"raw PDF root (default: REALITY_RAW_ROOT or {DEFAULT_RAW_ROOT})")
    ap.add_argument("--offline", action="store_true", help="use only cached PDFs, never download")
    args = ap.parse_args(argv)

    db = resolve_db(args.db or "results_xbrl")
    ann_db = resolve_db(args.ann_db or "bse_announcements")
    root = raw_root(args.raw_root)
    con = sqlite3.connect(db, timeout=600)
    con.execute("PRAGMA busy_timeout = 600000")
    ensure_schema(con)

    sql = """SELECT file, isin, scrip_code, period_end, broadcast_ts, filing_ts
             FROM filings
             WHERE status = 'ok' AND isin IS NOT NULL AND isin <> ''
               AND period_end IS NOT NULL
               AND scrip_code IS NOT NULL AND scrip_code <> '' AND scrip_code <> '000000'"""
    params: list[object] = []
    if args.since:
        sql += " AND period_end >= ?"
        params.append(args.since)
    sql += " ORDER BY period_end DESC, broadcast_ts DESC"
    filings = con.execute(sql, params).fetchall()

    by_scrip: dict[str, list[tuple[str, str, str]]] = {}
    for _file, isin, scrip_code, period_end, broadcast_ts, filing_ts in filings:
        by_scrip.setdefault(str(scrip_code).strip(), []).append(
            (isin, period_end, broadcast_ts or filing_ts or f"{period_end}T23:59:59"))
    announcements = announcement_index(ann_db)
    candidates = [(dissem, code, newsid, attachment)
                  for code, items in announcements.items() if code in by_scrip
                  for dissem, newsid, attachment in items]
    candidates.sort(reverse=True)
    print(f"result announcements: {len(candidates)} for {len(by_scrip)} scrips with filings; filings: {len(filings)}")

    processed = skipped = pages = 0
    # ponytail: BSE downloads are sequential; parallelise only if a full history backfill matters.
    for dissem, code, newsid, attachment in candidates:
        if args.limit and processed >= args.limit:
            break
        matches = match_filings(by_scrip[code], dissem)
        if not matches:
            skipped += 1
            continue
        pdf = download(newsid, attachment, root, args.offline)
        if pdf is None:
            skipped += 1
            continue
        page_count = pdf_page_count(pdf)
        todo = []
        for isin, period_end in matches:
            stored = con.execute(
                "SELECT COUNT(DISTINCT page_no) FROM results_notes "
                "WHERE isin = ? AND period_end = ? AND source_newsid = ?",
                (isin, period_end, newsid)).fetchone()[0]
            if stored != page_count:
                todo.append((isin, period_end))
        if not todo:
            skipped += 1
            continue
        texts = page_texts(pdf)
        if texts is None:
            skipped += 1
            continue
        rows = [(isin, period_end, newsid, page_no, text, dissem, 1 if NOTE_RE.search(text) else 0)
                for isin, period_end in todo
                for page_no, text in enumerate(texts, start=1)]
        with con:
            for isin, period_end in todo:
                con.execute("DELETE FROM results_notes WHERE isin = ? AND period_end = ? AND source_newsid = ?",
                            (isin, period_end, newsid))
            con.executemany("INSERT INTO results_notes VALUES (?,?,?,?,?,?,?)", rows)
        processed += 1
        pages += len(rows)
        linked = ", ".join(f"{isin} {period_end}" for isin, period_end in todo)
        print(f"  {newsid[:8]} {dissem}: {len(texts)} pages for {linked}")

    con.close()
    print(f"results_notes: {processed} announcements, {pages} pages, {skipped} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
