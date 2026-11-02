"""Registry and page text: ``company`` (every ISIN a symbol has had), ``doc`` and ``doc_page`` + FTS5.

Pages come from the gap loop's three sandbox databases (``doc_text`` / ``docs``): they are copied, no PDF is
re-read.  ``known_at`` is the sandbox's filing-record date, never the crawl date."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from reality_engine.pilot3 import SANDBOX_DB, SYMBOLS, schema
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


def build_doc(conn: sqlite3.Connection) -> dict:
    schema.create(conn, ("doc",))
    counts = {}
    for symbol in SYMBOLS:
        sb = _sandbox(symbol)
        isin = COMPANIES[symbol].isins[-1]
        rows = sb.execute("SELECT doc_key, doc_type, title, filing_date, known_at, pages, source, source_key "
                          "FROM docs").fetchall()
        conn.executemany("INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         [(f"{symbol}:{r[0]}", symbol, isin, r[1], FAMILY.get(r[1], r[1]), r[2], r[3], r[4],
                           r[5], None, r[6], r[7]) for r in rows])
        counts[symbol] = len(rows)
        sb.close()
    conn.commit()
    return counts


def build_pages(conn: sqlite3.Connection) -> dict:
    schema.create(conn, ("doc_page",))
    counts = {}
    for symbol in SYMBOLS:
        sb = _sandbox(symbol)
        cur = sb.execute("SELECT doc_key, page, text, method, known_at FROM doc_text")
        n = 0
        while True:
            batch = cur.fetchmany(2000)
            if not batch:
                break
            conn.executemany("INSERT INTO doc_page VALUES (?,?,?,?,?,?,?)",
                             [(f"{symbol}:{r[0]}", symbol, r[1], r[2], r[3], len(r[2] or ""), r[4]) for r in batch])
            n += len(batch)
        counts[symbol] = n
        sb.close()
    conn.execute(schema.FTS)
    conn.execute("INSERT INTO doc_page_fts(rowid, text) SELECT rowid, text FROM doc_page")
    conn.commit()
    return counts
