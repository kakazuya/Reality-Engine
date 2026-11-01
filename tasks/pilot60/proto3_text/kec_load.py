"""Load the 10 KEC concall transcripts into a chunks store (T-038).

Each PDF listed in ``_known_at.json`` becomes one ``doc`` row (doc_type ``concall``, ISIN
INE389H01022, symbol KEC) whose ``known_at`` is copied from that file and never from a
fetch or the site's own dates, plus one ``chunk`` row per page.  Content is keyed by
sha256, so a second run adds nothing.  The raw directory is read only: the loader never
writes, moves or deletes a PDF, and the cover letters beside the transcripts stay.

    python tasks/pilot60/proto3_text/kec_load.py --db .tmp/proto3/chunks_v3_pilot.db

The store is created with the reviewed chunk schema when ``--db`` does not exist; an
existing store keeps its own columns (the loader writes the intersection).
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
RAW_DIR = Path(r"D:\RealityEngine\raw\kec_transcripts")
MANIFEST = RAW_DIR / "_known_at.json"
ISIN = "INE389H01022"
SYMBOL = "KEC"
DOC_TYPE = "concall"

#: the reviewed ``chunk`` columns (tasks/pilot_t2/build_chunks_v3.py §A); a store that
#: carries fewer keeps its own shape.
CHUNK_COLUMNS = ("doc_id", "chunk_index", "header", "body", "char_len", "section", "speaker",
                 "speaker_role", "unit_kind", "page_from", "page_to", "span_start", "span_end",
                 "isin", "symbol_at_time", "doc_type", "source_class", "known_at", "event_date",
                 "fiscal_period", "n_numbers", "forward_looking", "quality_grade", "pit_conf",
                 "content_tags")
DOC_COLUMNS = ("doc_id", "sha256", "source", "doc_type", "source_class", "isin",
               "symbol_at_time", "title", "event_date", "known_at", "known_at_src", "pit_conf",
               "fiscal_period", "page_count", "parse_route", "quality_grade", "char_count",
               "raw_path", "raw_url", "build_run", "needs_ocr")

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS doc(
    doc_id TEXT PRIMARY KEY, sha256 TEXT, source TEXT NOT NULL, doc_type TEXT NOT NULL,
    source_class TEXT NOT NULL, isin TEXT, symbol_at_time TEXT, title TEXT NOT NULL,
    event_date TEXT, known_at TEXT NOT NULL, known_at_src TEXT NOT NULL,
    pit_conf REAL NOT NULL DEFAULT 1.0, fiscal_period TEXT, page_count INTEGER,
    parse_route TEXT, quality_grade TEXT, char_count INTEGER, raw_path TEXT, raw_url TEXT,
    build_run TEXT, needs_ocr INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS chunk(
    chunk_id INTEGER PRIMARY KEY, doc_id TEXT NOT NULL, chunk_index INTEGER NOT NULL,
    header TEXT NOT NULL, body TEXT NOT NULL, char_len INTEGER NOT NULL, section TEXT,
    speaker TEXT, speaker_role TEXT, unit_kind TEXT, page_from INTEGER, page_to INTEGER,
    span_start INTEGER, span_end INTEGER, isin TEXT, symbol_at_time TEXT, doc_type TEXT,
    source_class TEXT, known_at TEXT, event_date TEXT, fiscal_period TEXT, n_numbers INTEGER,
    forward_looking INTEGER, quality_grade TEXT, pit_conf REAL, content_tags TEXT);
CREATE INDEX IF NOT EXISTS ix_chunk_isin ON chunk(isin, known_at);
"""

_NUMBERS = re.compile(r"\d")
_QUARTER = re.compile(r"\b(Q[1-4])\s*FY\s?'?(\d{2})\b", re.I)


def _table_columns(con: sqlite3.Connection, table: str) -> dict[str, tuple]:
    return {row[1]: row for row in con.execute(f"PRAGMA table_info({table})")}


def _insert(con: sqlite3.Connection, table: str, values: dict[str, Any]) -> None:
    """Insert the columns this store actually carries; fill its required ones."""
    columns = _table_columns(con, table)
    use = {key: value for key, value in values.items() if key in columns}
    for name, info in columns.items():
        if name in use or not info[3]:        # not NOT NULL -> let the store default it
            continue
        use[name] = 0 if "INT" in str(info[2]).upper() else ""
    names = ", ".join(use)
    marks = ", ".join("?" for _ in use)
    con.execute(f"INSERT OR REPLACE INTO {table}({names}) VALUES ({marks})", tuple(use.values()))


def fiscal_period(title: str) -> str | None:
    match = _QUARTER.search(title or "")
    return f"{match.group(1).upper()}{match.group(2)}" if match else None


def chunks_for(pdf_path: Path, title: str, known_at: str) -> list[dict[str, Any]]:
    """One chunk per page of the transcript; ``body`` is the page's own extracted text."""
    import pymupdf

    out: list[dict[str, Any]] = []
    with pymupdf.open(pdf_path) as pdf:
        for index, page in enumerate(pdf, 1):
            body = (page.get_text("text") or "").strip()
            if not body:
                continue
            out.append({
                "chunk_index": index - 1, "header": f"{SYMBOL} · concall · {title} · p{index}",
                "body": body, "char_len": len(body), "section": "", "speaker": None,
                "speaker_role": "unknown", "unit_kind": "text", "page_from": index,
                "page_to": index, "n_numbers": len(_NUMBERS.findall(body)),
                "forward_looking": 0, "quality_grade": "A", "pit_conf": 1.0,
                "content_tags": "", "known_at": known_at,
            })
    return out


def load(db: Path, manifest: Path, raw_dir: Path, limit: int | None = None) -> dict[str, Any]:
    """Load every transcript the manifest lists; a sha256 already in the store is skipped."""
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    if limit:
        entries = entries[:limit]
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA_DDL)
    added = skipped = chunks = 0
    for entry in entries:
        sha = str(entry.get("sha256") or "")
        pdf_path = raw_dir / f"{sha}.pdf"
        doc_id = f"sha256:{sha}"
        if not sha or not pdf_path.is_file():
            skipped += 1
            continue
        if con.execute("SELECT 1 FROM doc WHERE doc_id = ? OR sha256 = ?",
                       (doc_id, sha)).fetchone():
            skipped += 1
            continue
        title = str(entry.get("title") or pdf_path.stem)
        known_at = str(entry.get("known_at") or "")   # the manifest's value, never the site's
        if not known_at:
            skipped += 1
            continue
        rows = chunks_for(pdf_path, title, known_at)
        if not rows:
            skipped += 1
            continue
        event_date = str(entry.get("site_publish_date") or "")[:10]
        _insert(con, "doc", {
            "doc_id": doc_id, "sha256": sha, "source": "company_site", "doc_type": DOC_TYPE,
            "source_class": "truth", "isin": ISIN, "symbol_at_time": SYMBOL, "title": title,
            "event_date": event_date, "known_at": known_at,
            "known_at_src": "manifest:_known_at.json", "pit_conf": 1.0,
            "fiscal_period": fiscal_period(title), "page_count": len(rows),
            "parse_route": "pymupdf_text", "quality_grade": "A",
            "char_count": sum(row["char_len"] for row in rows), "raw_path": str(pdf_path),
            "raw_url": str(entry.get("url") or ""), "build_run": "tasks/pilot60/proto3_text/"
            "kec_load.py", "needs_ocr": 0})
        for row in rows:
            _insert(con, "chunk", dict(row, doc_id=doc_id, isin=ISIN, symbol_at_time=SYMBOL,
                                       doc_type=DOC_TYPE, source_class="truth",
                                       event_date=event_date,
                                       fiscal_period=fiscal_period(title)))
        added += 1
        chunks += len(rows)
    fts = con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'chunk_fts'"
                      ).fetchone()
    if fts:
        try:                                  # keep an external-content FTS in step
            con.execute("INSERT INTO chunk_fts(chunk_fts) VALUES('rebuild')")
        except sqlite3.Error:
            pass
    con.commit()
    con.close()
    return {"docs_added": added, "docs_skipped": skipped, "chunks": chunks,
            "raw_files": len(list(raw_dir.glob("*.pdf")))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True, help="chunks store to write")
    parser.add_argument("--dir", default=str(RAW_DIR), help="the raw transcript directory")
    parser.add_argument("--manifest", help="known_at manifest (default: <dir>/_known_at.json)")
    parser.add_argument("--limit", type=int, help="load at most N manifests (a smoke run)")
    args = parser.parse_args(argv)
    raw_dir = Path(args.dir)
    manifest = Path(args.manifest) if args.manifest else raw_dir / "_known_at.json"
    stats = load(Path(args.db), manifest, raw_dir, args.limit)
    print(f"docs added {stats['docs_added']} (skipped {stats['docs_skipped']}), "
          f"page chunks {stats['chunks']}, PDFs left in the raw dir {stats['raw_files']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
