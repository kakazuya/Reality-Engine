"""Registry and page text: ``company`` (every ISIN a symbol has had), ``doc`` and ``doc_page`` + FTS5.

Pages come from ``pilot3/pages.db`` (every held document, ``docs_collect.py``); the gap loop's
sandbox pages (``doc_text`` / ``docs``) are kept only for documents pages.db lacks.  They are copied, no PDF is
re-read.  ``known_at`` is the filing-record date, never the crawl date.  ``doc_alias`` maps a sandbox doc_key (what
the KPI and transcript extractors still cite) to the pilot3 ``doc.doc_key``."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from reality_engine.pilot3 import PAGES_DB, SANDBOX_DB, SYMBOLS, schema
from reality_engine.gap_loop import prepare
from reality_engine.gap_loop.company import COMPANIES

FAMILY = {"annual_report": "annual_report", "deck": "deck", "transcript": "transcript", "results": "results",
          "announcement": "announcement", "press_release": "press_release", "audio_link": "transcript"}


def _duck(sql: str, params: tuple = ()) -> list:
    return prepare._read_duckdb(sql, params)[0]


def isin_history(symbol: str) -> list[tuple]:
    """``(isin, from, to, source)`` for every ISIN the symbol had: the truth snapshot's symbol_isin_history,
    plus ISINs that only other stores use (the T-048 review found shareholding rows under older ISINs)."""
    seen: dict[str, tuple] = {}
    for _ex, _sym, isin, start, end, _n in _duck(
            "SELECT * FROM symbol_isin_history WHERE symbol=? ORDER BY 4", (symbol,)):
        seen.setdefault(isin, (isin, str(start), str(end), "symbol_isin_history"))
    for table in ("shp_index", "corporate_actions", "results_key"):
        col = "trading_isin" if table == "results_key" else "isin"
        for (isin,) in _duck(f"SELECT DISTINCT {col} FROM {table} WHERE symbol=? AND {col} IS NOT NULL", (symbol,)):
            seen.setdefault(isin, (isin, None, None, table))
    return list(seen.values())


def all_isins(symbol: str) -> tuple[str, ...]:
    return tuple(row[0] for row in isin_history(symbol))


def build_company(conn: sqlite3.Connection) -> dict:
    schema.create(conn, ("company",))
    counts = {}
    for symbol in SYMBOLS:
        cfg = COMPANIES[symbol]
        rows = isin_history(symbol)
        conn.executemany("INSERT INTO company VALUES (?,?,?,?,?,?,?)",
                         [(symbol, i, a, b, src, cfg.bse_code, cfg.name) for i, a, b, src in rows])
        counts[symbol] = len(rows)
    conn.commit()
    return counts


def _sandbox(symbol: str) -> sqlite3.Connection:
    path = SANDBOX_DB[symbol]
    if not Path(path).is_file():
        raise SystemExit(f"STOPPED: sandbox database missing: {path}")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _pages_db() -> sqlite3.Connection | None:
    """The collector's pages.db (read-only), or None when this machine does not have it."""
    return sqlite3.connect(f"file:{PAGES_DB}?mode=ro", uri=True, timeout=30) if Path(PAGES_DB).is_file() else None


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_SHA = re.compile(r"[0-9a-f]{64}")


def _identity_index(pg: sqlite3.Connection) -> dict:
    """``{(symbol, id): pages.db doc_key}`` over every id one pages.db document is known by: its sha256, the
    file stems of its key and path, and the NEWSID / attachment uuids and sha256 hashes in its filing record."""
    ids: dict = {}
    for key, symbol, sha, record, path in pg.execute("SELECT doc_key, symbol, sha256, source_record, source_path FROM doc"):
        found = {sha, Path(key).stem, Path(path or "").stem}
        found |= set(_UUID.findall(record or "")) | set(_SHA.findall(record or ""))
        for ident in found:
            ids.setdefault((symbol, ident), key)
    return ids


def plan_docs(symbol: str, pg: sqlite3.Connection | None = None) -> dict:
    """Which documents pilot3 holds for a symbol and where each one's pages come from.

    ``pages_db``: every pages.db document of the symbol (key kept as pages.db has it).  ``sandbox``: sandbox
    documents pages.db does not hold (key ``SYMBOL:<sandbox key>``).  ``alias``: sandbox doc_key -> pilot3 doc_key,
    so a KPI or statement row that cites a sandbox key can be joined to ``doc``."""
    own = pg is None
    pg = pg or _pages_db()
    sb = _sandbox(symbol)
    sandbox_docs = sb.execute("SELECT doc_key, doc_type, title, filing_date, known_at, pages, source, source_key "
                              "FROM docs").fetchall()
    sb.close()
    if pg is None:
        out = {"pages_db": [], "sandbox": sandbox_docs, "alias": {r[0]: f"{symbol}:{r[0]}" for r in sandbox_docs}}
        return out
    ids = _identity_index(pg)
    pages_docs = pg.execute("SELECT doc_key, isin, doc_type, title, filing_date, known_at, pages, sha256, source_path, "
                            "known_at_source FROM doc WHERE symbol=? ORDER BY known_at", (symbol,)).fetchall()
    alias, keep = {}, []
    for row in sandbox_docs:
        hit = ids.get((symbol, row[7])) or ids.get((symbol, Path(row[0]).stem))
        if hit:
            alias[row[0]] = hit
        else:
            keep.append(row)
            alias[row[0]] = f"{symbol}:{row[0]}"
    if own:
        pg.close()
    return {"pages_db": pages_docs, "sandbox": keep, "alias": alias}


def build_doc(conn: sqlite3.Connection) -> dict:
    schema.create(conn, ("doc", "doc_alias"))
    counts = {}
    pg = _pages_db()
    for symbol in SYMBOLS:
        plan = plan_docs(symbol, pg)
        isin = COMPANIES[symbol].isins[-1]
        conn.executemany(
            "INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(r[0], symbol, r[1], r[2], FAMILY.get(r[2], r[2]), r[3], r[4], r[5], r[6], r[7], "pages.db", r[8])
             for r in plan["pages_db"]]
            + [(f"{symbol}:{r[0]}", symbol, isin, r[1], FAMILY.get(r[1], r[1]), r[2], r[3], r[4], r[5], None, r[6], r[7])
               for r in plan["sandbox"]])
        conn.executemany("INSERT INTO doc_alias VALUES (?,?,?)", [(symbol, a, k) for a, k in plan["alias"].items()])
        counts[symbol] = {"pages_db": len(plan["pages_db"]), "sandbox_only": len(plan["sandbox"])}
    if pg:
        pg.close()
    conn.commit()
    return counts


def _insert_pages(conn: sqlite3.Connection, cur, mapper) -> int:
    n = 0
    while True:
        batch = cur.fetchmany(2000)
        if not batch:
            return n
        conn.executemany("INSERT INTO doc_page VALUES (?,?,?,?,?,?,?)", [mapper(r) for r in batch])
        n += len(batch)


def build_pages(conn: sqlite3.Connection) -> dict:
    schema.create(conn, ("doc_page",))
    counts = {}
    pg = _pages_db()
    for symbol in SYMBOLS:
        plan = plan_docs(symbol, pg)
        n = 0
        if plan["pages_db"]:
            cur = pg.execute("SELECT p.doc_key, p.page, p.text, p.method, p.known_at FROM doc_page p "
                             "JOIN doc d ON d.doc_key=p.doc_key WHERE d.symbol=?", (symbol,))
            n += _insert_pages(conn, cur, lambda r: (r[0], symbol, r[1], r[2], r[3], len(r[2] or ""), r[4]))
        kept = {r[0] for r in plan["sandbox"]}
        if kept:
            sb = _sandbox(symbol)
            cur = sb.execute("SELECT doc_key, page, text, method, known_at FROM doc_text")
            rows = [r for r in cur if r[0] in kept]
            conn.executemany("INSERT INTO doc_page VALUES (?,?,?,?,?,?,?)",
                             [(f"{symbol}:{r[0]}", symbol, r[1], r[2], r[3], len(r[2] or ""), r[4]) for r in rows])
            n += len(rows)
            sb.close()
        counts[symbol] = n
    if pg:
        pg.close()
    conn.execute(schema.FTS)
    conn.execute("INSERT INTO doc_page_fts(rowid, text) SELECT rowid, text FROM doc_page")
    conn.commit()
    return counts
