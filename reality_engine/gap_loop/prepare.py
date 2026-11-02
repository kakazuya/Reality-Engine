"""The T-048 prepare stage: code only, no model, before round 1.

A raw ``reality-data`` reply is tens of thousands of tokens, so a 100k session cannot read the
evidence directly.  This module does the bulk work once, in Python, and leaves small rows behind in
the sandbox's company database (``kec.db`` for KEC):

- every PDF under ``raw`` read page by page with ``fitz`` into ``doc_text`` (a page under 50
  characters of text is recorded ``method='needs_ocr'`` with empty text: OCR is a fix-stage job),
  with an FTS5 index over the text;
- one ``docs`` row per PDF: ``doc_key`` (the path under ``raw``), doc type, title, filing date and
  ``known_at``, mapped from BSE's announcement records (file name = NEWSID, else the attachment
  name) or, for KEC only, its own transcript manifest; a file that cannot be dated gets ``known_at`` NULL;
- the company's rows (every ISIN) copied out of the read-only stores the ``reality-data`` server
  reads, each with its source table and key in ``sources``.

Idempotent: a doc already extracted, a page already stored and a table already copied are skipped.
Nothing here calls a model or touches the network.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from reality_engine.db.readonly import connect_ro
from reality_engine.gap_loop import ledger, store
from reality_engine.gap_loop.company import Company, current

RAW = "raw"
MIN_PAGE_CHARS = 50
UNDATED_LIMIT = 1.0 / 3.0
DATA_ROOT = Path(os.environ.get("REALITY_DATA_ROOT")
                 or Path(__file__).resolve().parents[1] / "data")

# Directory under raw -> doc type.  A mapped filing may refine it (a transcript, a BSE category).
DOC_TYPES = {
    "annual_report": "annual_report", "extra_annual_report": "annual_report",
    "investor_presentation": "deck", "extra_decks_full": "deck",
    "material_filing": "announcement", "extra_material_announcement": "announcement",
    "quarterly_results": "results", "results_press_release": "press_release",
    "concall_transcript": "transcript", "company_site_transcripts": "transcript",
    "concall_audio_link": "audio_link",
}


def store_copies(company: Company) -> tuple[dict, ...]:
    """One entry per table copied from a read-only SQLite store, filtered to this company's ISINs
    (every ISIN, so a changed ISIN keeps its history): the table, the store, the table in it, the
    key the rows were filtered by, and the SELECT (which adds ``known_at``)."""
    isin = company.isin_clause()
    params = company.isin_params
    return (
        {"table": "ar_facts", "db": "ar_facts.db", "source": "ar_facts", "key": company.isin_key,
         "sql": f"SELECT *, filed_at AS known_at FROM ar_facts WHERE {isin}", "params": params},
        {"table": "deck_figures", "db": "deck_figures.db", "source": "facts",
         "key": f"{company.isin_key} via pages",
         "sql": "SELECT f.*, p.known_at FROM facts f JOIN (SELECT sha256, MIN(known_at) AS known_at "
                f"FROM pages WHERE {isin} GROUP BY sha256) p ON p.sha256=f.sha256", "params": params},
        {"table": "results_filings", "db": "results_xbrl.db", "source": "filings",
         "key": company.isin_key,
         "sql": "SELECT *, coalesce(filing_ts, broadcast_ts, dissem_ts) AS known_at FROM filings "
                f"WHERE {isin}", "params": params},
        {"table": "results_quarterly", "db": "results_xbrl.db", "source": "quarterly",
         "key": company.isin_key,
         "sql": "SELECT *, coalesce(dissem_ts, broadcast_ts) AS known_at FROM quarterly "
                f"WHERE {isin}", "params": params},
        {"table": "concall_items", "db": "concall_facts.db", "source": "cc_items",
         "key": company.isin_key,
         "sql": f"SELECT *, filed_at AS known_at FROM cc_items WHERE {isin}", "params": params},
        {"table": "shp_index", "db": "equity_intelligence.db", "source": "shp_index",
         "key": company.isin_key,
         "sql": "SELECT *, coalesce(broadcast_at, submission_date) AS known_at FROM shp_index "
                f"WHERE {isin}", "params": params},
        {"table": "announcements", "db": "bse_announcements.db", "source": "ann",
         "key": f"symbol={company.symbol}",
         "sql": "SELECT *, coalesce(DissemDT, News_submission_dt, NEWS_DT) AS known_at FROM ann "
                "WHERE symbol=?", "params": (company.symbol,)},
    )


def duck_copies(company: Company) -> tuple[dict, ...]:
    """Price and delivery rows live in the dated truth snapshot (DuckDB), not in a SQLite store."""
    isin = company.isin_clause()
    return (
        {"table": "px_nse", "source": "px_nse", "key": company.isin_key,
         "sql": f"SELECT *, CAST(date AS VARCHAR) AS known_at FROM px_nse WHERE {isin}",
         "params": company.isin_params},
        {"table": "px_bse", "source": "px_bse", "key": f"{company.isin_key} sc_code={company.bse_code}",
         "sql": f"SELECT *, CAST(date AS VARCHAR) AS known_at FROM px_bse WHERE {isin} OR sc_code=?",
         "params": company.isin_params + (company.bse_code,)},
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_of(value: object) -> str | None:
    """The ``YYYY-MM-DD`` part of a stored date/timestamp, or None."""
    text = str(value or "").strip()
    head = text[:10]
    return head if re.fullmatch(r"\d{4}-\d{2}-\d{2}", head) else None


def _title(*candidates: object) -> str:
    for value in candidates:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if text:
            return text[:200]
    return ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pdfs(sandbox: Path) -> list[Path]:
    root = Path(sandbox) / RAW
    return sorted(root.rglob("*.pdf")) if root.is_dir() else []


def _transcripts(sandbox: Path) -> dict[str, dict]:
    """``sha256 -> manifest row`` for KEC's own site transcripts, from the two json files beside them.
    Other companies have no such manifest: their folder is skipped."""
    folder = Path(sandbox) / RAW / "company_site_transcripts"
    known: dict[str, dict] = {}
    if current().symbol != "KEC":
        return known
    for name in ("_manifest.json", "_known_at.json"):
        file = folder / name
        if not file.is_file():
            continue
        try:
            rows = json.loads(file.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for row in rows if isinstance(rows, list) else []:
            sha = str((row or {}).get("sha256") or "").lower()
            if sha:
                known.setdefault(sha, {}).update(row)
    return known


def _store_index(sandbox: Path) -> dict[str, dict]:
    """Lookup tables that date a held PDF, all from read-only stores (empty when copies are off)."""
    index: dict[str, dict] = {"transcripts": _transcripts(sandbox), "by_newsid": {}, "by_attachment": {},
                              "corp_by_newsid": {}, "corp_by_id": {}, "corp_by_sha": {}}
    company = current()
    if not store_copies(company):
        return index
    path = DATA_ROOT / "bse_announcements.db"
    if path.is_file():
        con = connect_ro(path, timeout_s=120)
        try:
            for newsid, attachment, headline, category, subcat, dissem, submitted, newsdt in con.execute(
                "SELECT NEWSID, ATTACHMENTNAME, HEADLINE, CATEGORYNAME, SUBCATNAME, DissemDT, "
                "News_submission_dt, NEWS_DT FROM ann WHERE symbol=?", (company.symbol,)
            ):
                row = {"NEWSID": newsid, "title": _title(subcat, category, headline),
                       "filing_date": _date_of(submitted or newsdt or dissem),
                       "known_at": dissem or submitted or newsdt}
                index["by_newsid"][str(newsid).lower()] = row
                if attachment:
                    index["by_attachment"][str(attachment).lower()] = row
        finally:
            con.close()
    path = DATA_ROOT / "equity_intelligence.db"
    if path.is_file():
        con = connect_ro(path, timeout_s=120)
        try:  # doc_date is the crawl date, never a filing date: publication/dissemination only
            for doc_id, doc_type, title, publication, call_date, dissem, bse_newsid, sha in con.execute(
                "SELECT id, doc_type, title, publication_date, call_date, bse_dissem_ts, bse_newsid, "
                f"sha256_hash FROM corporate_documents WHERE {company.isin_clause()}",
                company.isin_params
            ):
                when = dissem or publication or call_date
                row = {"id": doc_id, "doc_type": str(doc_type or "").lower(), "title": _title(title),
                       "filing_date": _date_of(when), "known_at": when}
                if bse_newsid:
                    index["corp_by_newsid"][str(bse_newsid).lower()] = row
                index["corp_by_id"][str(doc_id)] = row
                if sha:
                    index["corp_by_sha"][str(sha).lower()] = row
        finally:
            con.close()
    return index


def _doc_rows(sandbox: Path, index: dict[str, dict]) -> list[dict]:
    """One row per PDF under ``raw``: its key, type, title and the date a filing record gives it."""
    rows = []
    for path in _pdfs(sandbox):
        relative = path.relative_to(Path(sandbox) / RAW).as_posix()
        stem, name = path.stem.lower(), path.name.lower()
        row = {"doc_key": relative, "doc_type": DOC_TYPES.get(path.parent.name.lower(), "other"),
               "title": path.stem, "filing_date": None, "known_at": None, "source": "", "source_key": ""}
        transcript = index["transcripts"].get(stem)
        if transcript:
            row.update(doc_type="transcript", title=_title(transcript.get("title"), path.stem),
                       filing_date=_date_of(transcript.get("site_publish_date")),
                       known_at=transcript.get("known_at") or transcript.get("site_publish_date"),
                       source="company_site_transcripts/_known_at.json", source_key=stem)
        else:
            ann = index["by_newsid"].get(stem) or index["by_attachment"].get(name)
            if ann:
                row.update(title=ann["title"], filing_date=ann["filing_date"], known_at=ann["known_at"],
                           source="bse_announcements.ann", source_key=ann["NEWSID"])
            else:
                corp = index["corp_by_newsid"].get(stem) or index["corp_by_id"].get(path.stem)
                if corp is None and index["corp_by_sha"]:
                    corp = index["corp_by_sha"].get(_sha256(path))
                if corp:
                    row.update(doc_type=corp.get("doc_type") or row["doc_type"],
                               title=corp.get("title") or path.stem, filing_date=corp["filing_date"],
                               known_at=corp["known_at"],
                               source="equity_intelligence.corporate_documents",
                               source_key=str(corp["id"]))
        rows.append(row)
    return rows


def _clean_page(text: object) -> str:
    return re.sub(r"[ \t]+", " ", str(text or "").replace("\x00", " ")).strip()


def _extract(conn: sqlite3.Connection, sandbox: Path, rows: list[dict], counts: dict) -> None:
    """Read each PDF page by page into ``doc_text``; a doc already extracted is skipped."""
    import fitz

    for row in rows:
        key = row["doc_key"]
        pages = conn.execute("SELECT pages FROM docs WHERE doc_key=?", (key,)).fetchone()
        pages = int(pages[0]) if pages else 0
        done = conn.execute("SELECT COUNT(*) FROM doc_text WHERE doc_key=?", (key,)).fetchone()[0]
        if pages and done >= pages:
            row["pages"] = pages
            store.put_doc(conn, row)  # refresh the mapping, keep the page count
            continue
        with fitz.open(str(Path(sandbox) / RAW / key)) as doc:
            have = {page for (page,) in conn.execute("SELECT page FROM doc_text WHERE doc_key=?", (key,))}
            for number in range(1, doc.page_count + 1):
                if number in have:
                    continue
                text = _clean_page(doc[number - 1].get_text("text"))
                method = "script_text" if len(text) >= MIN_PAGE_CHARS else "needs_ocr"
                store.put_doc_text(conn, key, number, text if method == "script_text" else "",
                                   method, row.get("known_at"))
                counts["pages"] += 1
                counts[method] += 1
            row["pages"] = doc.page_count
        store.put_doc(conn, row)
        conn.commit()


def _type_of(value: object) -> str:
    if isinstance(value, bool) or isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    if isinstance(value, (bytes, bytearray)):
        return "BLOB"
    return "TEXT"


def _cell(value: object) -> object:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _write_table(conn: sqlite3.Connection, table: str, types: dict[str, str], rows: list) -> None:
    conn.execute(f'DROP TABLE IF EXISTS "{table}"')
    columns = ", ".join(f'"{name}" {kind}' for name, kind in types.items())
    conn.execute(f'CREATE TABLE "{table}" ({columns})')
    if rows:
        clean = [tuple(_cell(value) for value in row) for row in rows]
        conn.executemany(f'INSERT INTO "{table}" VALUES ({",".join("?" * len(types))})', clean)


def _read_sqlite(db: str, source: str, sql: str, params: tuple) -> tuple[list, dict[str, str]]:
    path = DATA_ROOT / db
    if not path.is_file():
        raise RuntimeError(f"cannot read {db} for {current().symbol}: {path} is missing")
    con = connect_ro(path, timeout_s=120)
    try:
        cursor = con.execute(sql, params)
        columns = [item[0] for item in cursor.description]
        kinds = {name: (kind or "TEXT") for _, name, kind, *_ in con.execute(f'PRAGMA table_info("{source}")')}
        return cursor.fetchall(), {name: kinds.get(name, "TEXT") for name in columns}
    finally:
        con.close()


def _snapshot() -> Path:
    found = sorted((DATA_ROOT / "snapshots").glob("truth_*.duckdb"))
    if not found:
        raise RuntimeError(f"cannot read the truth snapshot for {current().symbol}: "
                           f"no truth_*.duckdb under {DATA_ROOT}")
    return found[-1]


def _read_duckdb(sql: str, params: tuple) -> tuple[list, dict[str, str]]:
    import duckdb

    path = _snapshot()
    con = duckdb.connect(str(path), read_only=True)
    try:
        rows = con.execute(sql, params).fetchall()
        columns = [item[0] for item in con.description]
    finally:
        con.close()
    types = {name: _type_of(next((row[i] for row in rows if row[i] is not None), None))
             for i, name in enumerate(columns)}
    return rows, types


def _copied(conn: sqlite3.Connection, table: str) -> int | None:
    """Row count when this table is already copied and complete, else None."""
    row = conn.execute("SELECT rows FROM sources WHERE table_name=?", (table,)).fetchone()
    if row is None:
        return None
    try:
        current = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    except sqlite3.OperationalError:
        return None
    return current if current == int(row[0]) else None


def _copy_stores(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    now = _now_iso()
    company = current()
    for spec in store_copies(company):
        table = spec["table"]
        done = _copied(conn, table)
        if done is not None:
            counts[table] = done
            continue
        rows, types = _read_sqlite(spec["db"], spec["source"], spec["sql"], spec["params"])
        _write_table(conn, table, types, rows)
        store.put_source(conn, table, spec["db"], spec["source"], spec["key"], len(rows), now)
        conn.commit()
        counts[table] = len(rows)
    for spec in duck_copies(company):
        table = spec["table"]
        done = _copied(conn, table)
        if done is not None:
            counts[table] = done
            continue
        rows, types = _read_duckdb(spec["sql"], spec["params"])
        _write_table(conn, table, types, rows)
        store.put_source(conn, table, _snapshot().name, spec["source"], spec["key"], len(rows), now)
        conn.commit()
        counts[table] = len(rows)
    return counts


def summary(counts: dict) -> str:
    tables = ", ".join(f"{name}={rows}" for name, rows in (counts.get("tables") or {}).items()) or "none"
    return (f"prepare: {counts['files']} files, {counts['docs']} docs, {counts['pages']} pages "
            f"({counts['script_text']} script_text, {counts['needs_ocr']} needs_ocr), "
            f"{counts['undated']} undated ({counts['history_undated']}/{counts['history']} under raw\\history), "
            f"tables: {tables}, {counts['seconds']}s")


def undated_share(counts: dict) -> float:
    return counts["history_undated"] / counts["history"] if counts["history"] else 0.0


def blocked(counts: dict) -> str | None:
    """The stop rule: more than a third of the history PDFs undated means answers cannot be dated."""
    if undated_share(counts) <= UNDATED_LIMIT:
        return None
    return (f"{counts['history_undated']} of {counts['history']} PDFs under raw\\history are undated, "
            f"more than a third: fix the attachment mapping before answering")


def prepare(sandbox: Path, *, as_of: str | None = None) -> dict:
    """Run the prepare stage and log it as one ``tier=0`` ledger unit; returns the counts."""
    sandbox = Path(sandbox).resolve()
    started = time.time()
    started_iso = _now_iso()
    conn = store.connect(sandbox)
    counts = {"files": 0, "docs": 0, "pages": 0, "script_text": 0, "needs_ocr": 0,
              "known_at": 0, "undated": 0, "history": 0, "history_undated": 0, "tables": {},
              "seconds": 0.0}
    try:
        index = _store_index(sandbox)
        rows = _doc_rows(sandbox, index)
        counts["files"] = counts["docs"] = len(rows)
        for row in rows:
            if row.get("known_at"):
                counts["known_at"] += 1
            else:
                counts["undated"] += 1
            if row["doc_key"].startswith("history/"):
                counts["history"] += 1
                counts["history_undated"] += 0 if row.get("known_at") else 1
        conn.commit()
        _extract(conn, sandbox, rows, counts)
        counts["tables"] = _copy_stores(conn)
        conn.commit()
    finally:
        conn.close()
    counts["seconds"] = round(time.time() - started, 1)
    ledger.append(sandbox, {
        "ts_start": started_iso, "ts_end": _now_iso(), "stage": "prepare", "unit": "prepare",
        "size": 0, "attempt": 1, "tier": 0, "model": "script", "outcome": "ok", "error": "",
        "tokens": None, "cost_usd": 0.0, "tool_calls": {}, "bash": [], "methods": ["script_text"],
        "pages_model": None, "pages_code": counts["pages"], "as_of": as_of,
        "rows_added": {"doc_text": counts["pages"], "docs": counts["docs"],
                       "needs_ocr": counts["needs_ocr"], **counts["tables"]},
        "files_written": [current().db_name, ledger.LEDGER], "seconds": counts["seconds"],
    })
    return counts
