"""One-call document lookups across the five document stores.

The stores key a filing differently (deck ``sha256``, concall/AR ``doc_id``,
BSE ``NEWSID``) and disagree about its date (``doc_date`` is sometimes a crawl
date).  These three functions hide that:

* ``docs()``      list a company's documents, newest first, with store keys
* ``doc_page()``  the document nearest a date, one page of its text + facts
* ``doc_find()``  lexical search inside that company's documents

Read-only: every query goes through ``core``'s warm connections.  ``doc_page``
uses PyMuPDF when the PDF is local and falls back to the stored per-page
extraction (``deck_figures.outputs`` / ``facts``) when it is not; a Drive fetch
is attempted by sha256 and reported as ``fetched: true``.
"""
from __future__ import annotations

import datetime as dt
import posixpath
import re
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import core
from core import (
    DataError,
    _identity_isins,
    _identity_symbols,
    _in_clause,
    _parse_date,
    _run_duck,
    _run_sqlite,
    provenance,
    quarantined_doc_ids,
)

MAX_LIMIT = 100
DEFAULT_SLACK_DAYS = 3
_FETCH_TIMEOUT = 90.0
STORE_BUDGET_S = 2.0

_TYPE_ALIASES = {
    "deck": "deck", "decks": "deck", "presentation": "deck", "ppt": "deck",
    "investor presentation": "deck", "investor_presentation": "deck",
    "transcript": "transcript", "transcripts": "transcript", "concall": "transcript",
    "con-call": "transcript", "call": "transcript", "earnings call": "transcript",
    "concall transcript": "transcript",
    "ar": "ar", "annual report": "ar", "annual_report": "ar", "annualreport": "ar",
    "announcement": "announcement", "announcements": "announcement",
    "filing": "announcement", "other filing": "announcement", "other_filing": "announcement",
}
_CD_TYPE = {
    "INVESTOR_PRESENTATION": "deck",
    "CONCALL_TRANSCRIPT": "transcript",
    "ANNUAL_REPORT": "ar",
}
_CHUNK_TYPE = {
    "CONCALL_TRANSCRIPT": "transcript",
    "INVESTOR_PRESENTATION": "deck",
    "ANNUAL_REPORT": "ar",
    "ANNOUNCEMENT": "announcement",
    "OTHER_FILING": "announcement",
    "PRESS_RELEASE": "announcement",
}
_PAGE_RE = re.compile(r"page\s*(\d{1,4})\s*(?:of|/)\s*(\d{1,4})", re.IGNORECASE)
_META_RE = re.compile(r"^\[Metadata:[^\]]*\]\s*")
_DOC_TYPE_RE = re.compile(r"Doc:\s*([A-Z_]+)")
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9&.'-]{1,}", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _norm_type(value: str | None) -> str | None:
    if not value:
        return None
    key = str(value).strip().lower().replace("_", " ")
    return _TYPE_ALIASES.get(key.replace("  ", " "))


def _iso(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)[:10]


def _day(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _bounds(date_from: str | None, date_to: str | None) -> tuple[str, str]:
    lo = date_from or "0001-01-01"
    hi = date_to or "9999-12-31"
    if len(hi) == 10:
        hi += "T23:59:59"
    return lo, hi


def _window(date: dt.date, slack: int = DEFAULT_SLACK_DAYS) -> tuple[str, str]:
    delta = dt.timedelta(days=slack)
    return (date - delta).isoformat(), (date + delta).isoformat()


def _owner_clause(isins: Sequence[str], symbols: Sequence[str],
                  isin_col: str, symbol_col: str) -> tuple[str, list[str]]:
    """Index-friendly owner filter: ISIN when known, symbol only as fallback.

    An ``isin IN (...) OR upper(symbol) IN (...)`` disjunction defeats both
    indexes (the symbol side is an expression); every caller has an ISIN for a
    resolved company, so query the ISIN column alone.
    """
    if isins:
        clause, values = _in_clause(isins)
        return f"{isin_col} IN {clause}", values
    if symbols:
        clause, values = _in_clause([s.upper() for s in symbols])
        return f"upper({symbol_col}) IN {clause}", values
    return "0", []


def _query(store: str, sql: str, params: Sequence[Any], checked: list[str],
           label: str, warnings: list[str] | None = None) -> list[Any]:
    """Run one store query; a missing/broken store is reported, never fatal."""
    try:
        checked.append(label)
        return _run_sqlite(store, sql, params, timeout=12.0)
    except DataError as exc:
        note = f"{label}: {exc.code}"
        checked.append(note)
        if warnings is not None:
            warnings.append(note)
        return []
    except Exception as exc:  # a broken satellite DB must not take the tool down
        note = f"{label}: {type(exc).__name__}"
        checked.append(note)
        if warnings is not None:
            warnings.append(note)
        return []


def _duck(label: str, sql: str, params: Sequence[Any], checked: list[str],
          warnings: list[str]) -> list[dict[str, Any]]:
    """DuckDB counterpart of :func:`_query` for the document-list tables."""
    try:
        checked.append(label)
        columns, rows = _run_duck(sql, params, timeout=4.0)
        return [dict(zip(columns, row)) for row in rows]
    except DataError as exc:
        note = f"{label}: {exc.code}"
    except Exception as exc:
        note = f"{label}: {type(exc).__name__}"
    checked.append(note)
    warnings.append(note)
    return []


def _budget(name: str, column: str, label: str, collect: Callable[[], list[Any]],
            warnings: list[str]) -> list[Any]:
    """Run one store collector, dropping it when it misses the 2 s budget."""
    started = time.perf_counter()
    try:
        rows = collect()
    except DataError as exc:
        warnings.append(f"{label}: {exc.code}")
        return []
    except Exception as exc:  # a broken satellite DB must not take the tool down
        warnings.append(f"{label}: {type(exc).__name__}")
        return []
    if time.perf_counter() - started > STORE_BUDGET_S:
        warnings.append(f"{name} skipped: no index on {column}")
        return []
    return rows


def _entry(doc_type: str, date: str | None, known_at: str | None, title: str | None,
           pages: int | None, store: str, keys: dict[str, Any], has_text: bool,
           has_facts: bool, **extra: Any) -> dict[str, Any]:
    record = {
        "store": store, "keys": keys, "has_text": bool(has_text), "has_facts": bool(has_facts),
        "title": title, "pages": pages,
    }
    record.update({k: v for k, v in extra.items() if v not in (None, "")})
    return {
        "doc_type": doc_type,
        "date": date,
        "known_at": known_at or (f"{date}T00:00:00" if date else None),
        "title": title,
        "pages": pages,
        "keys": dict(keys),
        "has_text": bool(has_text),
        "has_facts": bool(has_facts),
        "stores": [record],
    }


def _merge_key(entry: dict[str, Any]) -> tuple:
    """Identity of ONE filing: same type/date are not enough (4 decks a day)."""
    keys = entry["keys"]
    store = entry["stores"][0]["store"]
    if keys.get("sha256"):
        identity: tuple = ("sha256", keys["sha256"])
    elif keys.get("newsid"):
        identity = ("newsid", keys["newsid"])
    elif keys.get("doc_id") is not None:
        # doc ids are per-store sequences: corporate_documents.id and ar doc_id
        # collide on value while naming different filings.
        identity = (store, "doc_id", keys["doc_id"])
    elif keys.get("chunks_doc_id") is not None:
        identity = ("chunks", keys["chunks_doc_id"])
    else:
        identity = ("title", entry.get("title") or "")
    return (entry["doc_type"], entry["date"], identity)


def _merge(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple, dict[str, Any]] = {}
    for entry in entries:
        key = _merge_key(entry)
        old = merged.get(key)
        if old is None:
            merged[key] = entry
            continue
        seen = {s["store"] for s in old["stores"]}
        old["stores"].extend(s for s in entry["stores"] if s["store"] not in seen)
        old["has_text"] = old["has_text"] or entry["has_text"]
        old["has_facts"] = old["has_facts"] or entry["has_facts"]
        page_values = [p for p in (old["pages"], entry["pages"]) if p]
        old["pages"] = max(page_values) if page_values else None
        if not old.get("title") and entry.get("title"):
            old["title"] = entry["title"]
        elif entry.get("title") and len(str(entry["title"])) > len(str(old.get("title") or "")):
            old["title"] = entry["title"]
        for k, v in entry["keys"].items():
            old["keys"].setdefault(k, v)
        old["known_at"] = max(filter(None, [old.get("known_at"), entry.get("known_at")]),
                              default=None)
    out = list(merged.values())
    out.sort(key=lambda e: (e.get("date") or "", e.get("known_at") or ""), reverse=True)
    return out


# ---------------------------------------------------------------------------
# Per-store collectors
# ---------------------------------------------------------------------------
def _deck_docs(identity: dict[str, Any], lo: str, hi: str, limit: int,
               checked: list[str], warnings: list[str]) -> list[dict[str, Any]]:
    isins = _identity_isins(identity)
    symbols = _identity_symbols(identity)
    where, params = _owner_clause(isins, symbols, "isin", "symbol")
    rows = _query(
        "deck_figures",
        "SELECT sha256, source, source_id, symbol, isin, known_at, title, url, local_path, status "
        f"FROM deck_sources WHERE {where} AND known_at >= ? AND known_at <= ? "
        "ORDER BY known_at DESC LIMIT ?",
        [*params, lo, hi, limit], checked, "deck_figures.deck_sources",
        warnings=warnings,
    )
    shas = [r["sha256"] for r in rows if r["sha256"]]
    pages: dict[str, int] = {}
    text_chars: dict[str, int] = {}
    fact_counts: dict[str, int] = {}
    if shas:
        clause, values = _in_clause(shas)
        for r in _query("deck_figures", f"SELECT sha256, n_pages FROM doc_pages WHERE sha256 IN {clause}",
                        values, checked, "deck_figures.doc_pages", warnings=warnings):
            pages[r["sha256"]] = r["n_pages"]
        for r in _query("deck_figures",
                        "SELECT sha256, sum(text_chars) AS chars FROM pages "
                        f"WHERE sha256 IN {clause} GROUP BY sha256", values, checked, "deck_figures.pages",
                        warnings=warnings):
            text_chars[r["sha256"]] = int(r["chars"] or 0)
        for r in _query("deck_figures",
                        f"SELECT sha256, count(*) AS n FROM facts WHERE sha256 IN {clause} GROUP BY sha256",
                        values, checked, "deck_figures.facts", warnings=warnings):
            fact_counts[r["sha256"]] = int(r["n"] or 0)
    out = []
    for row in rows:
        sha = row["sha256"]
        known_at = row["known_at"]
        title = row["title"]
        if not title or str(title).upper() in ("ANNOUNCEMENT", "INVESTOR_PRESENTATION"):
            title = f"{row['symbol'] or ''} investor presentation".strip()
        out.append(_entry(
            "deck", _iso(known_at), known_at, title, pages.get(sha),
            "deck_figures", {"sha256": sha, "source": row["source"], "source_id": row["source_id"]},
            has_text=text_chars.get(sha, 0) > 0, has_facts=fact_counts.get(sha, 0) > 0,
            local_path=row["local_path"], url=row["url"], status=row["status"],
        ))
    return out


def _cc_docs(identity: dict[str, Any], lo: str, hi: str, limit: int,
             checked: list[str], warnings: list[str]) -> list[dict[str, Any]]:
    # cc_docs has no index on isin/filed_at in SQLite: list from the DuckDB
    # snapshot instead, and touch SQLite only for cc_items (indexed by isin).
    isins = _identity_isins(identity)
    symbols = _identity_symbols(identity)
    where, params = _owner_clause(isins, symbols, "isin", "symbol")
    rows = _duck(
        "truth_duckdb.cc_docs",
        "SELECT doc_id, symbol, isin, filed_at, chars, period_discussed, status FROM cc_docs "
        f"WHERE {where} AND filed_at >= ? AND filed_at <= ? ORDER BY filed_at DESC LIMIT ?",
        [*params, lo, hi, limit], checked, warnings,
    )
    counts: dict[int, int] = {}
    if rows and isins:
        clause, values = _in_clause(isins)
        for r in _query("concall_facts",
                        "SELECT doc_id, count(*) AS n FROM cc_items "
                        f"WHERE isin IN {clause} AND filed_at >= ? AND filed_at <= ? GROUP BY doc_id",
                        [*values, lo, hi], checked, "concall_facts.cc_items", warnings=warnings):
            counts[int(r["doc_id"])] = int(r["n"] or 0)
    out = []
    for row in rows:
        out.append(_entry(
            "transcript", _iso(row["filed_at"]), row["filed_at"],
            row["period_discussed"] or f"{row['symbol'] or ''} earnings call".strip(),
            None, "concall_facts", {"doc_id": row["doc_id"]},
            has_text=bool(row["chars"]), has_facts=counts.get(int(row["doc_id"]), 0) > 0,
            status=row["status"],
        ))
    return out


def _chunk_docs(identity: dict[str, Any], lo: str, hi: str, limit: int,
                checked: list[str], warnings: list[str]) -> list[dict[str, Any]]:
    symbols = _identity_symbols(identity)
    if not symbols:
        return []
    clause, values = _in_clause(symbols)
    rows = _query(
        "equity_intelligence",
        "SELECT doc_id, published_date, count(*) AS n, min(substr(content, 1, 140)) AS meta "
        f"FROM document_chunks WHERE symbol IN {clause} "
        "AND published_date >= ? AND published_date <= ? "
        "GROUP BY doc_id, published_date ORDER BY published_date DESC LIMIT ?",
        [*values, lo, hi, limit], checked, "equity_intelligence.document_chunks",
        warnings=warnings,
    )
    out = []
    for row in rows:
        match = _DOC_TYPE_RE.search(row["meta"] or "")
        doc_type = _CHUNK_TYPE.get(match.group(1) if match else "", None)
        if not doc_type:
            continue
        date = _iso(row["published_date"])
        out.append(_entry(
            doc_type, date, f"{date}T00:00:00", f"{row['doc_id']} ({doc_type})", None,
            "document_chunks", {"chunks_doc_id": row["doc_id"], "chunks": int(row["n"] or 0)},
            has_text=True, has_facts=False,
        ))
    return out


def _ar_docs(identity: dict[str, Any], lo: str, hi: str, limit: int,
             checked: list[str], quarantine: set[int],
             warnings: list[str]) -> list[dict[str, Any]]:
    isins = _identity_isins(identity)
    symbols = _identity_symbols(identity)
    where, params = _owner_clause(isins, symbols, "isin", "symbol")
    rows = _duck(
        "truth_duckdb.ar_docs",
        "SELECT doc_id, symbol, isin, fiscal_year, filed_at, sha256, n_pages, n_text_pages, status "
        f"FROM ar_docs WHERE {where} AND filed_at >= ? AND filed_at <= ? "
        "ORDER BY filed_at DESC LIMIT ?",
        [*params, lo, hi, limit], checked, warnings,
    )
    ids = [int(r["doc_id"]) for r in rows if r["doc_id"] is not None
           and int(r["doc_id"]) not in quarantine]
    paths: dict[int, str | None] = {}
    if ids:
        # The DuckDB snapshot has no local path; open SQLite by primary key only.
        clause, values = _in_clause([str(i) for i in ids])
        for r in _query("ar_facts", f"SELECT doc_id, path FROM ar_docs WHERE doc_id IN {clause}",
                        values, checked, "ar_facts.ar_docs", warnings=warnings):
            paths[int(r["doc_id"])] = r["path"]
    counts: dict[int, int] = {}
    if ids:
        clause, values = _in_clause([str(i) for i in ids])
        for r in _query("ar_facts", f"SELECT doc_id, count(*) AS n FROM ar_facts "
                                    f"WHERE doc_id IN {clause} GROUP BY doc_id",
                        values, checked, "ar_facts.ar_facts", warnings=warnings):
            counts[int(r["doc_id"])] = int(r["n"] or 0)
    out = []
    for row in rows:
        if int(row["doc_id"] or 0) in quarantine:
            continue
        title = f"{row['symbol'] or ''} annual report {row['fiscal_year'] or ''}".strip()
        doc_id = int(row["doc_id"])
        out.append(_entry(
            "ar", _iso(row["filed_at"]), row["filed_at"], title, row["n_pages"],
            "ar_facts", {"doc_id": doc_id, "sha256": row["sha256"]},
            has_text=bool(row["n_text_pages"]), has_facts=counts.get(doc_id, 0) > 0,
            local_path=paths.get(doc_id), fiscal_year=row["fiscal_year"], status=row["status"],
        ))
    return out


def _corporate_docs(identity: dict[str, Any], lo: str, hi: str, limit: int,
                    checked: list[str], warnings: list[str]) -> list[dict[str, Any]]:
    # Filter on the real indexed column (idx_docs_sym_date); the COALESCE stamp
    # is only applied to rows the symbol index already reduced.
    symbols = _identity_symbols(identity)
    if not symbols:
        return []
    clause, values = _in_clause(symbols)
    date_expr = "COALESCE(bse_dissem_ts, publication_date, call_date, doc_date)"
    rows = _query(
        "equity_intelligence",
        "SELECT id, symbol, isin, doc_type, title, doc_date, bse_dissem_ts, publication_date, "
        "call_date, source_url, local_file_path, sha256_hash, bse_newsid FROM corporate_documents "
        f"WHERE symbol IN {clause} AND {date_expr} >= ? AND {date_expr} <= ? "
        f"ORDER BY {date_expr} DESC LIMIT ?",
        [*values, lo, hi, limit], checked, "equity_intelligence.corporate_documents",
        warnings=warnings,
    )
    out = []
    for row in rows:
        # quarantined_doc_ids() is the ar_facts key set; corporate_documents.id
        # is a different sequence and must not be filtered by it.
        if row["id"] is None:
            continue
        doc_type = _CD_TYPE.get(str(row["doc_type"] or "").upper(), "announcement")
        stamp = row["bse_dissem_ts"] or row["publication_date"] or row["call_date"] or row["doc_date"]
        path = row["local_file_path"]
        out.append(_entry(
            doc_type, _iso(stamp), stamp, row["title"], None, "corporate_documents",
            {"doc_id": row["id"], "sha256": row["sha256_hash"], "newsid": row["bse_newsid"]},
            has_text=bool(path and Path(str(path)).exists()), has_facts=False,
            doc_type_raw=row["doc_type"], local_path=path, url=row["source_url"],
        ))
    return out


def _bse_docs(identity: dict[str, Any], lo: str, hi: str, limit: int,
              checked: list[str], warnings: list[str]) -> list[dict[str, Any]]:
    # bse_announcements.db has no index on symbol/SCRIP_CD/date (1.95M rows):
    # list announcements from the columnar DuckDB snapshot instead.
    symbols = _identity_symbols(identity)
    scrip = str(identity.get("bse_code") or "").strip()
    clauses: list[str] = []
    params: list[Any] = []
    if scrip:
        clauses.append("SCRIP_CD = ?")
        params.append(scrip)
    if symbols:
        clause, values = _in_clause(symbols)
        clauses.append(f"upper(symbol) IN {clause}")
        params.extend(values)
    if not clauses:
        return []
    date_expr = "COALESCE(DissemDT, NEWS_DT)"
    rows = _duck(
        "truth_duckdb.bse_ann",
        "SELECT NEWSID, SCRIP_CD, symbol, NEWS_DT, DissemDT, NEWSSUB, HEADLINE, ATTACHMENTNAME "
        f"FROM bse_ann WHERE ({' OR '.join(clauses)}) AND {date_expr} >= ? AND {date_expr} <= ? "
        f"ORDER BY {date_expr} DESC LIMIT ?",
        [*params, lo, hi, limit], checked, warnings,
    )
    out = []
    for row in rows:
        stamp = row["DissemDT"] or row["NEWS_DT"]
        attachment = row["ATTACHMENTNAME"]
        title = row["NEWSSUB"] or row["HEADLINE"] or "BSE announcement"
        url = None
        if attachment:
            url = f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{attachment}"
        out.append(_entry(
            "announcement", _iso(stamp), stamp, str(title)[:240], None, "bse_announcements",
            {"newsid": row["NEWSID"], "attachment": attachment}, has_text=False, has_facts=False,
            url=url, scrip_code=str(row["SCRIP_CD"] or ""),
        ))
    return out


def _collect(identity: dict[str, Any], doc_type: str | None = None,
             date_from: str | None = None, date_to: str | None = None,
             limit: int = 20) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    lo, hi = _bounds(date_from, date_to)
    checked: list[str] = []
    warnings: list[str] = []
    quarantine = quarantined_doc_ids()
    wanted = {doc_type} if doc_type else {"deck", "transcript", "ar", "announcement"}
    per_store = max(limit, 20)
    entries: list[dict[str, Any]] = []
    if "deck" in wanted:
        entries += _budget(
            "deck_figures", "isin", "deck_figures",
            lambda: _deck_docs(identity, lo, hi, per_store, checked, warnings), warnings)
    chunk_entries = _budget(
        "document_chunks", "symbol", "document_chunks",
        lambda: _chunk_docs(identity, lo, hi, per_store, checked, warnings), warnings)
    if "transcript" in wanted:
        entries += _budget(
            "concall_facts", "isin", "concall_facts",
            lambda: _cc_docs(identity, lo, hi, per_store, checked, warnings), warnings)
    for chunk_entry in chunk_entries:
        if chunk_entry["doc_type"] in wanted:
            entries.append(chunk_entry)
    if "ar" in wanted:
        entries += _budget(
            "ar_facts", "isin", "ar_facts",
            lambda: _ar_docs(identity, lo, hi, per_store, checked, quarantine, warnings), warnings)
    # corporate_documents holds decks/transcripts/ARs too, so collect it for
    # every type and filter the merged rows below.
    entries += _budget(
        "corporate_documents", "symbol", "corporate_documents",
        lambda: _corporate_docs(identity, lo, hi, per_store, checked, warnings), warnings)
    if "announcement" in wanted:
        entries += _budget(
            "bse_announcements", "SCRIP_CD", "bse_announcements",
            lambda: _bse_docs(identity, lo, hi, per_store, checked, warnings), warnings)
    entries = [entry for entry in entries if entry["doc_type"] in wanted]
    return _merge(entries), checked, warnings


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------
def _pdf_page_text(path: Path, page: int) -> tuple[str | None, int | None]:
    try:
        import fitz  # PyMuPDF
    except Exception:
        return None, None
    try:
        with fitz.open(str(path)) as doc:
            count = int(doc.page_count)
            if page < 1 or page > count:
                return None, count
            return doc[page - 1].get_text("text"), count
    except Exception:
        return None, None


def _drive_folder(local_path: str | None) -> str | None:
    try:
        from reality_engine.toolbelt.drive_fetch import local_to_remote
        remote = local_to_remote(local_path or "")
        return posixpath.dirname(remote) or None
    except Exception:
        return None


def _fetch_pdf(local_path: str | None, sha256: str | None) -> tuple[Path | None, str]:
    """Fetch one document from the Drive archive; returns (path, status-note)."""
    item = sha256 or local_path
    if not item:
        return None, "no local path or sha256"
    dest = core.ROOT / ".tmp" / "lookups_docs"
    try:
        from reality_engine.toolbelt.drive_fetch import fetch
        result = fetch([item], dest=str(dest), folder=_drive_folder(local_path),
                       timeout=_FETCH_TIMEOUT)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    record = (result.get("items") or [{}])[0]
    target = Path(str(record.get("dest") or ""))
    if record.get("status") == "ok" and target.exists():
        return target, ""
    return None, f"{record.get('status') or 'missing'}: {record.get('reason') or ''}".strip()


def _clean_page(text: str | None) -> str | None:
    if not text:
        return None
    return str(text).strip() or None


def _deck_page(sha: str, page: int, local_path: str | None) -> dict[str, Any]:
    if local_path and Path(str(local_path)).exists():
        text, pages = _pdf_page_text(Path(str(local_path)), page)
        if text:
            return {"text": _clean_page(text), "text_source": "pdf", "page_count": pages,
                    "fetched": False}
    target, note = _fetch_pdf(local_path, sha)
    if target is not None:
        text, pages = _pdf_page_text(target, page)
        if text:
            return {"text": _clean_page(text), "text_source": "pdf", "page_count": pages,
                    "fetched": True}
    fetched = bool(target is not None)
    rows = _run_sqlite("deck_figures",
                       "SELECT raw_output FROM outputs WHERE sha256=? AND page_no=?",
                       (sha, page), timeout=10.0)
    raw = _clean_page(rows[0]["raw_output"]) if rows else None
    facts = _run_sqlite(
        "deck_figures",
        "SELECT metric, period, raw_number, value, unit FROM facts "
        "WHERE sha256=? AND page_no=? ORDER BY line_no LIMIT 100",
        (sha, page), timeout=10.0,
    )
    lines = [raw] if raw else []
    for row in facts:
        sentence = " ".join(str(v) for v in (row["metric"], row["raw_number"] or row["value"],
                                             row["unit"]) if v not in (None, ""))
        if sentence:
            lines.append(sentence)
    text = "\n".join(lines) if lines else None
    return {"text": text, "text_source": "stored_extraction" if text else None,
            "page_count": None, "fetched": fetched,
            "fetch_note": note or None}


def _chunk_page_text(chunk_doc_id: Any, page: int) -> dict[str, Any]:
    if chunk_doc_id is None:
        return {"text": None, "text_source": None, "page_count": None, "fetched": False}
    rows = _run_sqlite(
        "equity_intelligence",
        "SELECT chunk_index, content FROM document_chunks WHERE doc_id=? ORDER BY chunk_index",
        (chunk_doc_id,), timeout=12.0,
    )
    if not rows:
        return {"text": None, "text_source": None, "page_count": None, "fetched": False}
    page_count = None
    chosen = None
    for row in rows:
        content = row["content"] or ""
        match = _PAGE_RE.search(content)
        if match:
            page_count = page_count or int(match.group(2))
            if int(match.group(1)) == page:
                chosen = content
                break
    if chosen is None:
        # No explicit "page N of M": use the proportional chunk for that page.
        if page_count:
            ratio = min(max((page - 1) / max(page_count, 1), 0.0), 1.0)
            index = min(int(ratio * len(rows)), len(rows) - 1)
            chosen = rows[index]["content"]
    text = _clean_page(_META_RE.sub("", chosen or ""))
    return {"text": text, "text_source": "stored_chunk" if text else None,
            "page_count": page_count, "fetched": False}


def _ar_page(doc_id: Any, page: int, local_path: str | None, sha: str | None) -> dict[str, Any]:
    if local_path and Path(str(local_path)).exists():
        text, pages = _pdf_page_text(Path(str(local_path)), page)
        if text:
            return {"text": _clean_page(text), "text_source": "pdf", "page_count": pages,
                    "fetched": False}
    target, note = _fetch_pdf(local_path, sha)
    if target is not None:
        text, pages = _pdf_page_text(target, page)
        if text:
            return {"text": _clean_page(text), "text_source": "pdf", "page_count": pages,
                    "fetched": True}
    fetched = bool(target is not None)
    rows = _run_sqlite(
        "ar_facts",
        "SELECT quote FROM ar_facts WHERE doc_id=? AND page=? AND quote IS NOT NULL LIMIT 50",
        (doc_id, page), timeout=10.0,
    )
    text = "\n\n".join(str(r["quote"]).strip() for r in rows if r["quote"])
    return {"text": _clean_page(text), "text_source": "stored_facts" if text else None,
            "page_count": None, "fetched": fetched, "fetch_note": note or None}


def _page_facts(entry: dict[str, Any], page: int) -> list[dict[str, Any]]:
    store = next((s for s in entry["stores"] if s["store"] == "deck_figures"), None)
    if store:
        sha = store["keys"].get("sha256")
        rows = _run_sqlite(
            "deck_figures",
            "SELECT metric, period, raw_number, value, unit, is_final FROM facts "
            "WHERE sha256=? AND page_no=? ORDER BY line_no LIMIT 200",
            (sha, page), timeout=10.0,
        )
        return [dict(r) for r in rows]
    store = next((s for s in entry["stores"] if s["store"] == "ar_facts"), None)
    if store:
        doc_id = store["keys"].get("doc_id")
        rows = _run_sqlite(
            "ar_facts",
            "SELECT category, item, value_raw, value, unit, period, quote FROM ar_facts "
            "WHERE doc_id=? AND page=? LIMIT 200",
            (doc_id, page), timeout=10.0,
        )
        return [dict(r) for r in rows]
    return []


def _page_text(entry: dict[str, Any], page: int) -> dict[str, Any]:
    doc_type = entry["doc_type"]
    stores = {s["store"]: s for s in entry["stores"]}
    if doc_type == "deck" and "deck_figures" in stores:
        store = stores["deck_figures"]
        result = _deck_page(store["keys"].get("sha256"), page, store.get("local_path"))
        if store.get("pages"):
            result["page_count"] = result.get("page_count") or store["pages"]
        return result
    if doc_type == "ar" and "ar_facts" in stores:
        store = stores["ar_facts"]
        result = _ar_page(store["keys"].get("doc_id"), page, store.get("local_path"),
                          store["keys"].get("sha256"))
        result["page_count"] = result.get("page_count") or store.get("pages")
        return result
    if doc_type == "transcript":
        store = stores.get("corporate_documents")
        if store and store.get("local_path") and Path(str(store["local_path"])).exists():
            text, pages = _pdf_page_text(Path(str(store["local_path"])), page)
            if text:
                return {"text": _clean_page(text), "text_source": "pdf", "page_count": pages,
                        "fetched": False}
        chunk_store = stores.get("document_chunks")
        return _chunk_page_text(chunk_store["keys"].get("chunks_doc_id") if chunk_store else None,
                                page)
    store = stores.get("corporate_documents")
    if store and store.get("local_path") and Path(str(store["local_path"])).exists():
        text, pages = _pdf_page_text(Path(str(store["local_path"])), page)
        if text:
            return {"text": _clean_page(text), "text_source": "pdf", "page_count": pages,
                    "fetched": False}
    return {"text": None, "text_source": None, "page_count": None, "fetched": False}


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------
def _identity_head(identity: dict[str, Any]) -> dict[str, Any]:
    name = identity.get("name") or ""
    if not name:
        # resolve_one can pick an old, nameless ISIN row for a renamed/re-keyed
        # company; the master table still has the current name.
        try:
            rows = _run_sqlite(
                "equity_intelligence",
                "SELECT company_name FROM master_companies WHERE upper(nse_symbol)=? "
                "OR upper(isin)=? LIMIT 1",
                (str(identity.get("nse_symbol") or "").upper(), identity.get("isin") or ""),
                timeout=5.0,
            )
            name = rows[0]["company_name"] if rows else name
        except Exception:
            name = ""
    return {
        "symbol": identity.get("nse_symbol") or identity.get("bse_symbol") or "",
        "company": name or "",
        "isin": identity.get("isin") or "",
        "bse_code": identity.get("bse_code") or "",
        "isin_history": [h.get("isin") for h in identity.get("isin_history", []) if h.get("isin")],
    }


def _distance(entry: dict[str, Any], requested: dt.date) -> int:
    day = _day(entry.get("date"))
    return abs((day - requested).days) if day else 10 ** 6


def _not_found(kind: str, identity: dict[str, Any], doc_type: str | None,
               checked: list[str], now: dt.date | None, hint: str,
               extra: dict[str, Any] | None = None,
               warnings: Sequence[str] | None = None) -> dict[str, Any]:
    recent, extra_checked, extra_warnings = _collect(identity, doc_type, None, None, limit=60)
    checked = checked + [c for c in extra_checked if c not in checked]
    warnings = list(warnings or [])
    warnings += [w for w in extra_warnings if w not in warnings]
    if now is not None:
        recent = sorted(recent, key=lambda e: _distance(e, now))
    nearest = []
    for entry in recent[:5]:
        item = {"doc_type": entry["doc_type"], "date": entry.get("date"),
                "title": entry.get("title"), "keys": entry.get("keys")}
        day = _day(entry.get("date"))
        item["days_apart"] = abs((day - now).days) if (day and now) else None
        nearest.append(item)
    out = {
        "found": False,
        kind: None,
        "checked": checked,
        "nearest": nearest,
        "hint": hint,
        "warnings": warnings,
        "partial": bool(warnings),
        **_identity_head(identity),
        "provenance": provenance("truth_duckdb", ["security_master", "symbol_isin_history"],
                                 note="identity only; no document text returned"),
    }
    if extra:
        out.update(extra)
    return out


def docs(symbol: str, doc_type: str | None = None, date_from: str | None = None,
         date_to: str | None = None, limit: int = 20) -> dict[str, Any]:
    """List a company's documents across all stores, newest first."""
    identity = core.resolve_one(symbol)
    canonical = _norm_type(doc_type)
    if doc_type and canonical is None:
        raise DataError("bad_doc_type",
                        f"unknown doc_type {doc_type!r}; use deck, transcript, ar or announcement")
    start = _iso(_parse_date(date_from, "date_from"))
    end = _iso(_parse_date(date_to, "date_to"))
    if start and end and end < start:
        raise DataError("bad_range", f"date_to {end} is before date_from {start}")
    try:
        limit = max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        raise DataError("bad_limit", f"limit must be an integer between 1 and {MAX_LIMIT}")
    entries, checked, warnings = _collect(identity, canonical, start, end, limit)
    entries = entries[:limit]
    if not entries:
        return _not_found("documents", identity, canonical, checked,
                          _day(end or start), "no document of that type in the requested window; "
                          "nearest is listed above (dates are the filing/known_at date)",
                          warnings=warnings)
    return {
        "found": True,
        "count": len(entries),
        "documents": entries,
        "checked": checked,
        "warnings": warnings,
        "partial": bool(warnings),
        **_identity_head(identity),
        "filters": {"doc_type": canonical, "date_from": start, "date_to": end, "limit": limit},
        "provenance": provenance("truth_duckdb", ["security_master", "symbol_isin_history"],
                                 documents="deck_figures, concall_facts, ar_facts, "
                                           "equity_intelligence, bse_announcements"),
    }


def doc_page(symbol: str, date: str, page: int, doc_type: str | None = None) -> dict[str, Any]:
    """The document nearest ``date`` (within ±3 days) and one page of its text."""
    identity = core.resolve_one(symbol)
    requested = _parse_date(date, "date")
    if requested is None:
        raise DataError("bad_date", "date is required, YYYY-MM-DD")
    try:
        page_no = int(page)
    except (TypeError, ValueError):
        raise DataError("bad_page", "page must be a positive integer")
    if page_no < 1 or page_no > 10000:
        raise DataError("bad_page", "page must be between 1 and 10000")
    canonical = _norm_type(doc_type)
    if doc_type and canonical is None:
        raise DataError("bad_doc_type",
                        f"unknown doc_type {doc_type!r}; use deck, transcript, ar or announcement")
    lo, hi = _window(requested)
    entries, checked, warnings = _collect(identity, canonical, lo, hi, limit=60)
    if not entries:
        return _not_found(
            "document", identity, canonical, checked, requested,
            f"no {canonical or 'document'} within ±{DEFAULT_SLACK_DAYS} days of "
            f"{requested.isoformat()}; nearest is listed above", {"page": page_no},
            warnings=warnings,
        )
    ordered = sorted(entries, key=lambda e: (
        _distance(e, requested),
        0 if e.get("date") == requested.isoformat() else 1,
        0 if e.get("has_text") else 1,
        0 if e.get("has_facts") else 1,
    ))
    chosen = ordered[0]
    text_info: dict[str, Any] = {"text": None, "text_source": None, "page_count": None,
                                 "fetched": False}
    for candidate in ordered:
        # Same filing seen by several stores (cc_docs text marker, chunk text,
        # corporate_documents PDF) stays separate in the list but shares a page.
        if candidate is not chosen and not (
                candidate["doc_type"] == chosen["doc_type"]
                and candidate.get("date") == chosen.get("date")):
            continue
        try:
            info = _page_text(candidate, page_no)
        except DataError as exc:
            warnings.append(f"page_text: {exc.code}")
            continue
        if info.get("text") or candidate is chosen:
            chosen, text_info = candidate, info
        if text_info.get("text"):
            break
    try:
        facts = _page_facts(chosen, page_no)
    except DataError as exc:
        warnings.append(f"page_facts: {exc.code}")
        facts = []
    page_count = text_info.get("page_count") or chosen.get("pages")
    days = abs((_day(chosen.get("date")) - requested).days) if _day(chosen.get("date")) else None
    why = (f"nearest {chosen['doc_type']} to {requested.isoformat()}: filed "
           f"{chosen.get('date')}" + (f" ({days} day(s) away)" if days else " (same day)")
           + f"; {len(entries)} candidate(s) within ±{DEFAULT_SLACK_DAYS} days")
    out = {
        "found": True,
        "date_requested": requested.isoformat(),
        "date_matched": chosen.get("date"),
        "days_apart": days,
        "why": why,
        "page": page_no,
        "page_count": page_count,
        "page_label": f"page {page_no} of {page_count}" if page_count else f"page {page_no}",
        "text": text_info.get("text"),
        "text_source": text_info.get("text_source"),
        "full_page_text": text_info.get("text_source") == "pdf",
        "fetched": bool(text_info.get("fetched")),
        "facts": facts,
        "document": chosen,
        "checked": checked,
        "warnings": warnings,
        "partial": bool(warnings),
        **_identity_head(identity),
        "provenance": provenance("truth_duckdb", ["security_master", "symbol_isin_history"],
                                 document_stores=", ".join(s["store"] for s in chosen["stores"])),
    }
    if text_info.get("fetch_note"):
        out["fetch_note"] = text_info["fetch_note"]
    if text_info.get("text") is None:
        out["hint"] = ("no stored text for that page; the PDF is not on disk and the Drive "
                       "fetch did not return it" if not out["fetched"] else
                       "the fetched PDF has no text on that page")
    return out


def _tokens(terms: str) -> list[str]:
    seen: list[str] = []
    for token in _TOKEN_RE.findall(str(terms or "").lower()):
        if len(token) > 1 and token not in seen:
            seen.append(token)
    return seen[:6]


def _quote(text: str, tokens: Sequence[str], width: int = 420) -> str:
    body = _META_RE.sub("", str(text or "")).strip()
    low = body.lower()
    hits = [low.find(t) for t in tokens]
    hits = [h for h in hits if h >= 0]
    if not hits:
        return body[:width].strip()
    phrase = " ".join(tokens)
    best = (-1, 0, min(len(body), width))
    for pos in hits:
        start = max(0, pos - width // 3)
        end = min(len(body), start + width)
        window = low[start:end]
        covered = sum(1 for h in hits if start <= h < end)
        score = covered + (2 if phrase in window else 0)
        if score > best[0]:
            best = (score, start, end)
    return body[best[1]:best[2]].strip()


def _chunk_passages(identity: dict[str, Any], tokens: Sequence[str], doc_type: str | None,
                    lo: str | None, hi: str | None, limit: int,
                    checked: list[str], warnings: list[str]) -> list[dict[str, Any]]:
    symbols = _identity_symbols(identity)
    if not symbols:
        return []
    clause, values = _in_clause(symbols)
    sql = ("SELECT chunk_id, doc_id, chunk_index, published_date, content FROM document_chunks "
           f"WHERE symbol IN {clause}")
    params: list[Any] = list(values)
    if lo and hi:
        sql += " AND published_date >= ? AND published_date <= ?"
        params += [lo, hi]
    for token in tokens:
        sql += " AND lower(content) LIKE ?"
        params.append(f"%{token}%")
    sql += " ORDER BY published_date DESC LIMIT ?"
    params.append(max(limit * 4, 40))
    rows = _query("equity_intelligence", sql, params, checked,
                  "equity_intelligence.document_chunks", warnings=warnings)
    out = []
    for row in rows:
        content = row["content"] or ""
        match = _DOC_TYPE_RE.search(content[:160])
        kind = _CHUNK_TYPE.get(match.group(1) if match else "", None)
        if kind is None:
            kind = "transcript" if "concall" in content[:160].lower() else None
        if doc_type and kind != doc_type:
            continue
        page_match = _PAGE_RE.search(content)
        out.append({
            "store": "document_chunks",
            "doc_type": kind,
            "date": _iso(row["published_date"]),
            "doc_id": row["doc_id"],
            "page": int(page_match.group(1)) if page_match else None,
            "page_count": int(page_match.group(2)) if page_match else None,
            "chunk_index": row["chunk_index"],
            "quote": _quote(content, tokens),
            "score": 3 if " ".join(tokens) in content.lower() else 1,
        })
    return out


def _ar_passages(identity: dict[str, Any], tokens: Sequence[str], lo: str | None,
                 hi: str | None, limit: int, checked: list[str],
                 quarantine: set[int], warnings: list[str]) -> list[dict[str, Any]]:
    isins = _identity_isins(identity)
    where, params = _owner_clause(isins, _identity_symbols(identity), "isin", "symbol")
    sql = ("SELECT doc_id, page, filed_at, symbol, category, item, quote FROM ar_facts "
           f"WHERE {where}")
    args: list[Any] = list(params)
    if lo and hi:
        sql += " AND filed_at >= ? AND filed_at <= ?"
        args += [lo, hi]
    for token in tokens:
        sql += " AND (lower(item) LIKE ? OR lower(quote) LIKE ?)"
        args += [f"%{token}%", f"%{token}%"]
    sql += " ORDER BY filed_at DESC LIMIT ?"
    args.append(max(limit * 4, 40))
    rows = _query("ar_facts", sql, args, checked, "ar_facts.ar_facts", warnings=warnings)
    out = []
    for row in rows:
        if row["doc_id"] is not None and int(row["doc_id"]) in quarantine:
            continue
        out.append({
            "store": "ar_facts",
            "doc_type": "ar",
            "date": _iso(row["filed_at"]),
            "doc_id": row["doc_id"],
            "page": row["page"],
            "page_count": None,
            "quote": _quote(row["quote"] or row["item"] or "", tokens),
            "score": 2,
        })
    return out


def _deck_passages(identity: dict[str, Any], tokens: Sequence[str], lo: str | None,
                   hi: str | None, limit: int, checked: list[str],
                   warnings: list[str]) -> list[dict[str, Any]]:
    isins = _identity_isins(identity)
    where, params = _owner_clause(isins, _identity_symbols(identity), "isin", "symbol")
    sql = ("SELECT sha256, symbol, known_at, title, local_path FROM deck_sources "
           f"WHERE {where}")
    args: list[Any] = list(params)
    if lo and hi:
        sql += " AND known_at >= ? AND known_at <= ?"
        args += [lo, hi]
    sql += " ORDER BY known_at DESC LIMIT ?"
    args.append(max(limit, 10))
    decks = _query("deck_figures", sql, args, checked, "deck_figures.deck_sources",
                   warnings=warnings)
    out = []
    for deck in decks:
        sha = deck["sha256"]
        local_hit = False
        if deck["local_path"] and Path(str(deck["local_path"])).exists():
            try:
                import fitz
                with fitz.open(str(deck["local_path"])) as pdf:
                    for page in range(1, int(pdf.page_count) + 1):
                        text = pdf[page - 1].get_text("text")
                        low = (text or "").lower()
                        if all(t in low for t in tokens):
                            local_hit = True
                            out.append({"store": "deck_figures", "doc_type": "deck",
                                        "date": _iso(deck["known_at"]), "doc_id": sha,
                                        "page": page, "page_count": int(pdf.page_count),
                                        "quote": _quote(text, tokens), "score": 3})
            except Exception:
                pass
        if local_hit:
            continue
        rows = _query(
            "deck_figures",
            "SELECT page_no, raw_output FROM outputs WHERE sha256=? AND "
            + " AND ".join("lower(raw_output) LIKE ?" for _ in tokens)
            + " ORDER BY page_no LIMIT ?",
            [sha, *[f"%{t}%" for t in tokens], limit], checked, "deck_figures.outputs",
            warnings=warnings,
        )
        for row in rows:
            out.append({"store": "deck_figures", "doc_type": "deck",
                        "date": _iso(deck["known_at"]), "doc_id": sha,
                        "page": row["page_no"], "page_count": None,
                        "quote": _quote(row["raw_output"] or "", tokens), "score": 2})
    return out


def _announcement_passages(identity: dict[str, Any], tokens: Sequence[str], lo: str | None,
                           hi: str | None, limit: int,
                           checked: list[str], warnings: list[str]) -> list[dict[str, Any]]:
    symbols = _identity_symbols(identity)
    scrip = str(identity.get("bse_code") or "").strip()
    clauses: list[str] = []
    params: list[Any] = []
    if scrip:
        clauses.append("SCRIP_CD = ?")
        params.append(scrip)
    if symbols:
        clause, values = _in_clause(symbols)
        clauses.append(f"upper(symbol) IN {clause}")
        params.extend(values)
    if not clauses:
        return []
    date_expr = "COALESCE(DissemDT, NEWS_DT)"
    sql = ("SELECT NEWSID, NEWS_DT, DissemDT, NEWSSUB, HEADLINE, ATTACHMENTNAME FROM bse_ann "
           f"WHERE ({' OR '.join(clauses)})")
    args: list[Any] = list(params)
    if lo and hi:
        sql += f" AND {date_expr} >= ? AND {date_expr} <= ?"
        args += [lo, hi]
    for token in tokens:
        sql += " AND (lower(NEWSSUB) LIKE ? OR lower(HEADLINE) LIKE ?)"
        args += [f"%{token}%", f"%{token}%"]
    sql += f" ORDER BY {date_expr} DESC LIMIT ?"
    args.append(max(limit, 10))
    rows = _duck("truth_duckdb.bse_ann", sql, args, checked, warnings)
    return [{
        "store": "bse_announcements", "doc_type": "announcement",
        "date": _iso(row["DissemDT"] or row["NEWS_DT"]), "doc_id": row["NEWSID"],
        "page": None, "page_count": None,
        "quote": _quote(row["NEWSSUB"] or row["HEADLINE"] or "", tokens),
        "score": 2,
    } for row in rows]


def doc_find(symbol: str, terms: str, doc_type: str | None = None, date: str | None = None,
             top_k: int = 8) -> dict[str, Any]:
    """Lexical search inside one company's documents; passages with page and quote."""
    identity = core.resolve_one(symbol)
    text = " ".join(str(terms or "").split())
    tokens = _tokens(text)
    if not tokens:
        raise DataError("bad_query", "terms needs at least one word of two letters or more")
    canonical = _norm_type(doc_type)
    if doc_type and canonical is None:
        raise DataError("bad_doc_type",
                        f"unknown doc_type {doc_type!r}; use deck, transcript, ar or announcement")
    try:
        top_k = max(1, min(int(top_k), 30))
    except (TypeError, ValueError):
        raise DataError("bad_limit", "top_k must be an integer between 1 and 30")
    requested = _parse_date(date, "date") if date else None
    lo = hi = None
    if requested:
        lo, hi = _window(requested)
        hi += "T23:59:59"
    checked: list[str] = []
    warnings: list[str] = []
    quarantine = quarantined_doc_ids()
    passages: list[dict[str, Any]] = []
    if canonical in (None, "transcript", "ar", "announcement", "deck"):
        passages += _budget(
            "document_chunks", "symbol", "document_chunks",
            lambda: _chunk_passages(identity, tokens, canonical, lo, hi, top_k, checked, warnings),
            warnings)
    if canonical in (None, "ar"):
        passages += _budget(
            "ar_facts", "isin", "ar_facts",
            lambda: _ar_passages(identity, tokens, lo, hi, top_k, checked, quarantine, warnings),
            warnings)
    if canonical in (None, "deck"):
        passages += _budget(
            "deck_figures", "isin", "deck_figures",
            lambda: _deck_passages(identity, tokens, lo, hi, top_k, checked, warnings), warnings)
    if canonical in (None, "announcement"):
        passages += _budget(
            "bse_announcements", "SCRIP_CD", "bse_announcements",
            lambda: _announcement_passages(identity, tokens, lo, hi, top_k, checked, warnings),
            warnings)

    def _key(p: dict[str, Any]) -> tuple:
        return (p.get("doc_id"), p.get("date"), p.get("page"), str(p.get("quote"))[:80])
    dedup: dict[tuple, dict[str, Any]] = {}
    for passage in sorted(passages, key=lambda p: (p.get("score", 0), p.get("date") or ""),
                          reverse=True):
        dedup.setdefault(_key(passage), passage)
    ranked = list(dedup.values())[:top_k]
    if not ranked:
        return _not_found(
            "passages", identity, canonical, checked, requested,
            f"no passage matching {text!r} in the {canonical or 'available'} documents; "
            "try fewer or more general words, or drop the date filter", {"terms": text},
            warnings=warnings,
        )
    return {
        "found": True,
        "terms": text,
        "doc_type": canonical,
        "date_requested": requested.isoformat() if requested else None,
        "count": len(ranked),
        "passages": ranked,
        "checked": checked,
        "warnings": warnings,
        "partial": bool(warnings),
        **_identity_head(identity),
        "provenance": provenance("truth_duckdb", ["security_master", "symbol_isin_history"],
                                 searched=", ".join(dict.fromkeys(p["store"] for p in ranked))),
    }
