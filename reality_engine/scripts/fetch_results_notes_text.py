"""Store the notes pages of quarterly-results PDFs in ``results_xbrl.db:results_notes``.

Each results filing in ``results_xbrl.filings`` is matched to its BSE
announcement (``bse_announcements.db:ann``, category ``Result``) by BSE scrip
code and announcement time.  The attached PDF is downloaded once into
``REALITY_RAW_ROOT/results_notes_text/<NEWSID>.pdf`` (never under
``reality_engine/data``), and every page whose text mentions "note" is stored
with the announcement time as ``known_at``.  FTS5 indexes the page text.

Resumable: a filing already present under its ``source_newsid`` is skipped, and
a cached PDF is reused.  ``--offline`` never downloads.

Usage:
    python -m reality_engine.scripts.fetch_results_notes_text
    python -m reality_engine.scripts.fetch_results_notes_text --limit 20 --since 2026-06-30
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
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

DDL = """
CREATE TABLE IF NOT EXISTS results_notes (
  isin TEXT NOT NULL,
  period_end TEXT NOT NULL,
  source_newsid TEXT NOT NULL,
  page_no INTEGER NOT NULL,
  text TEXT NOT NULL,
  known_at TEXT,
  PRIMARY KEY (isin, period_end, source_newsid, page_no));
CREATE INDEX IF NOT EXISTS ix_results_notes_newsid ON results_notes(source_newsid);
CREATE VIRTUAL TABLE IF NOT EXISTS results_notes_fts USING fts5(
  text, content='results_notes', content_rowid='rowid', tokenize='unicode61');
CREATE TRIGGER IF NOT EXISTS results_notes_ai AFTER INSERT ON results_notes BEGIN
  INSERT INTO results_notes_fts(rowid, text) VALUES (new.rowid, new.text);
END;
"""


def raw_root(override: str | None) -> Path:
    return Path(override) if override else Path(os.environ.get("REALITY_RAW_ROOT", DEFAULT_RAW_ROOT))


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(DDL)
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


def pick_announcement(candidates: list[tuple[str, str, str]], ref_ts: str) -> tuple[str, str, str] | None:
    """Closest announcement to the NSE filing time (BSE can lead or lag by hours)."""
    try:
        ref = datetime.fromisoformat(ref_ts.replace("Z", "")[:19])
    except (ValueError, TypeError):
        return None
    best = None
    for dissem, newsid, attachment in candidates:
        try:
            at = datetime.fromisoformat(dissem.replace("Z", "")[:19])
        except ValueError:
            continue
        delta = abs((at - ref).total_seconds())
        if delta <= MATCH_WINDOW_SECONDS and (best is None or delta < best[0]):
            best = (delta, dissem, newsid, attachment)
    return None if best is None else (best[1], best[2], best[3])


def download(newsid: str, attachment: str, root: Path, offline: bool) -> Path | None:
    dest = root / "results_notes_text" / f"{newsid}.pdf"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    if offline:
        return None
    request = urllib.request.Request(BSE_PDF.format(name=attachment), headers=BSE_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            content = response.read()
    except Exception as exc:  # noqa: BLE001 - one filing must not stop the run
        print(f"  download failed {newsid}: {type(exc).__name__}: {exc}")
        return None
    if not content.startswith(b"%PDF"):
        print(f"  not a PDF {newsid}: {content[:20]!r}")
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return dest


def note_pages(pdf: Path, isin: str, period_end: str, newsid: str,
               known_at: str) -> list[tuple[str, str, str, int, str, str]]:
    import pymupdf

    rows: list[tuple[str, str, str, int, str, str]] = []
    try:
        doc = pymupdf.open(pdf)
    except Exception as exc:  # noqa: BLE001
        print(f"  unreadable {pdf.name}: {type(exc).__name__}: {exc}")
        return rows
    try:
        for page_no in range(1, doc.page_count + 1):
            text = doc[page_no - 1].get_text("text").strip()
            if NOTE_RE.search(text):
                rows.append((isin, period_end, newsid, page_no, text, known_at))
    except Exception as exc:  # noqa: BLE001
        print(f"  failed {pdf.name}: {type(exc).__name__}: {exc}")
        return []
    finally:
        doc.close()
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extract results-PDF notes pages into results_xbrl.db:results_notes.")
    ap.add_argument("--db", help="results_xbrl database (default: REALITY_DATA_ROOT/results_xbrl.db)")
    ap.add_argument("--ann-db", help="bse_announcements database (default: REALITY_DATA_ROOT/bse_announcements.db)")
    ap.add_argument("--limit", type=int, help="filings to process in this run")
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

    announcements = announcement_index(ann_db)
    print(f"result announcements: {sum(len(v) for v in announcements.values())} for "
          f"{len(announcements)} scrips; filings: {len(filings)}")

    processed = skipped = pages = 0
    # ponytail: BSE downloads are sequential; parallelise only if a full history backfill matters.
    selected = filings[: args.limit] if args.limit else filings
    for _file, isin, scrip_code, period_end, broadcast_ts, filing_ts in selected:
        candidates = announcements.get(str(scrip_code).strip())
        if not candidates:
            skipped += 1
            continue
        picked = pick_announcement(candidates, broadcast_ts or filing_ts or f"{period_end}T23:59:59")
        if picked is None:
            skipped += 1
            continue
        known_at, newsid, attachment = picked
        if con.execute("SELECT 1 FROM results_notes WHERE source_newsid = ? LIMIT 1", (newsid,)).fetchone():
            skipped += 1
            continue
        pdf = download(newsid, attachment, root, args.offline)
        if pdf is None:
            skipped += 1
            continue
        rows = note_pages(pdf, isin, period_end, newsid, known_at)
        with con:
            con.executemany("INSERT OR IGNORE INTO results_notes VALUES (?,?,?,?,?,?)", rows)
        processed += 1
        pages += len(rows)
        print(f"  {isin} {period_end} {newsid[:8]}: {len(rows)} note pages")

    con.close()
    print(f"results_notes: {processed} filings, {pages} note pages, {skipped} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
