"""One command: what data do we hold for a symbol, per store, with row counts and date ranges.

Before a backtest we need to know which company-level stores have rows for a stock
and how fresh they are.  This resolves one symbol to its ISINs and asks every live
store that keys company data:

* filings registry (``equity_intelligence.corporate_documents``)
* BSE announcements (``bse_announcements.ann``)
* concall transcripts and extracted items (``concall_facts``)
* annual reports and extracted AR facts (``ar_facts``)
* investor decks and extracted deck figures (``deck_figures``)
* quarterly XBRL results filings and their facts (``results_xbrl``)
* NSE price + delivery history (``equity_intelligence.daily_price_delivery``)

All connections are read-only.  An unknown symbol prints ``not found`` and exits 2.

Examples:
    python -m reality_engine.toolbelt.coverage_peek --symbol DEEDEV
    python -m reality_engine.toolbelt.coverage_peek --symbol DEEDEV --json

    from reality_engine.toolbelt.coverage_peek import coverage
    data = coverage("DEEDEV")
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from ._common import connect, format_table, main_guard

_DATABASES = ("equity_intelligence", "bse_announcements", "concall_facts",
              "ar_facts", "deck_figures", "results_xbrl")
_COLUMNS = ("store", "dataset", "key", "rows", "first_date", "last_date", "date_field")


def _open_stores(timeout_s: float = 60.0) -> dict[str, sqlite3.Connection]:
    """Open every store that exists; a missing database is skipped, not fatal."""
    stores: dict[str, sqlite3.Connection] = {}
    for name in _DATABASES:
        try:
            stores[name] = connect(name, timeout_s)
        except FileNotFoundError:
            continue
    return stores


def _resolve(con: sqlite3.Connection, symbol: str) -> list[str]:
    """All ISINs ever used by ``symbol`` (master row plus the symbol/ISIN history)."""
    isins: set[str] = set()
    for (isin,) in con.execute(
            "SELECT isin FROM master_companies WHERE nse_symbol = ? OR bse_code = ?",
            (symbol, symbol)):
        if isin:
            isins.add(isin)
    for exchange in ("NSE", "BSE"):
        for (isin,) in con.execute(
                "SELECT DISTINCT isin FROM symbol_isin_history WHERE exchange = ? AND symbol = ?",
                (exchange, symbol)):
            if isin:
                isins.add(isin)
    if not isins:  # delisted before the master snapshot, but still on file
        for (isin,) in con.execute(
                "SELECT DISTINCT isin FROM corporate_documents "
                "WHERE symbol = ? AND isin IS NOT NULL", (symbol,)):
            isins.add(isin)
    return sorted(isins)


def _specs(symbol: str, isins: list[str]) -> list[tuple]:
    """(db, dataset, table, key column, date field, SQL, params) per store."""
    ph = ",".join("?" * len(isins))
    isin_params = tuple(isins)
    either = isin_params + (symbol,)  # stores that carry both isin and symbol
    return [
        ("equity_intelligence", "filings (all doc types)", "corporate_documents", "symbol",
         "filing date",
         "SELECT count(*), min(d), max(d) FROM ("
         "SELECT COALESCE(bse_dissem_ts, publication_date, call_date, doc_date) AS d "
         "FROM corporate_documents WHERE symbol = ?)", (symbol,)),
        # ponytail: ann has no index on symbol, so this scans ~1.9M rows (~5 s);
        # add an index on ann(symbol) if coverage_peek ever runs over a universe.
        ("bse_announcements", "announcements", "ann", "symbol", "DT_TM",
         "SELECT count(*), min(DT_TM), max(DT_TM) FROM ann WHERE symbol = ?", (symbol,)),
        ("concall_facts", "concall transcripts", "cc_docs", "isin/symbol", "filed_at",
         f"SELECT count(*), min(filed_at), max(filed_at) FROM cc_docs "
         f"WHERE isin IN ({ph}) OR symbol = ?", either),
        ("concall_facts", "concall facts", "cc_items", "isin", "filed_at",
         f"SELECT count(*), min(filed_at), max(filed_at) FROM cc_items WHERE isin IN ({ph})",
         isin_params),
        ("ar_facts", "annual reports", "ar_docs", "isin/symbol", "filed_at",
         f"SELECT count(*), min(filed_at), max(filed_at) FROM ar_docs "
         f"WHERE isin IN ({ph}) OR symbol = ?", either),
        ("ar_facts", "AR facts", "ar_facts", "isin", "filed_at",
         f"SELECT count(*), min(filed_at), max(filed_at) FROM ar_facts WHERE isin IN ({ph})",
         isin_params),
        ("deck_figures", "investor decks", "deck_sources", "isin", "known_at",
         f"SELECT count(*), min(known_at), max(known_at) FROM deck_sources "
         f"WHERE isin IN ({ph})", isin_params),
        ("deck_figures", "deck figures", "facts", "isin", "known_at",
         "SELECT count(*), min(p.known_at), max(p.known_at) FROM facts f "
         "JOIN pages p ON p.sha256 = f.sha256 AND p.page_no = f.page_no "
         "AND p.prompt_version = f.prompt_version "
         f"WHERE p.isin IN ({ph})", isin_params),
        ("results_xbrl", "quarterly results", "filings", "isin", "period_end",
         f"SELECT count(*), min(period_end), max(period_end) FROM filings "
         f"WHERE isin IN ({ph})", isin_params),
        ("results_xbrl", "quarterly result facts", "facts", "isin", "period_end",
         "SELECT count(*), min(period_end), max(period_end) FROM facts WHERE file IN ("
         f"SELECT file FROM filings WHERE isin IN ({ph}))", isin_params),
        ("equity_intelligence", "prices (NSE + delivery)", "daily_price_delivery", "isin", "date",
         f"SELECT count(*), min(date), max(date) FROM daily_price_delivery "
         f"WHERE isin IN ({ph})", isin_params),
    ]


def coverage(symbol: str, stores: Mapping[str, sqlite3.Connection] | None = None) -> dict[str, Any]:
    """Row count and date range per store for one symbol; ``found`` is False if unknown.

    ``stores`` lets callers (tests) inject connections; when omitted the live
    read-only databases under ``REALITY_DATA_ROOT`` are opened and closed.
    """
    symbol = (symbol or "").strip().upper()
    owned = stores is None
    opened: dict[str, sqlite3.Connection] = _open_stores() if owned else dict(stores)
    try:
        equity = opened.get("equity_intelligence")
        if equity is None:
            raise ValueError("equity_intelligence store not found (set REALITY_DATA_ROOT)")
        isins = _resolve(equity, symbol)
        if not isins:
            return {"symbol": symbol, "found": False, "isins": [], "stores": [],
                    "stores_with_data": 0, "total_rows": 0}
        rows = []
        for db, dataset, table, key, date_field, sql, params in _specs(symbol, isins):
            con = opened.get(db)
            if con is None:
                continue
            count, first, last = con.execute(sql, params).fetchone()
            rows.append({"store": f"{db}.{table}", "dataset": dataset, "key": key,
                         "rows": int(count), "first_date": first, "last_date": last,
                         "date_field": date_field})
        return {"symbol": symbol, "found": True, "isins": isins, "stores": rows,
                "stores_with_data": sum(1 for row in rows if row["rows"]),
                "total_rows": sum(row["rows"] for row in rows)}
    finally:
        if owned:
            for con in opened.values():
                con.close()


def main(argv: list[str] | None = None,
         stores: Mapping[str, sqlite3.Connection] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m reality_engine.toolbelt.coverage_peek",
        description="Row counts and date ranges per company-level store for one symbol.")
    ap.add_argument("--symbol", required=True, help="NSE/BSE symbol (e.g. DEEDEV)")
    ap.add_argument("--json", action="store_true", help="JSON instead of the table")
    args = ap.parse_args(argv)
    result = coverage(args.symbol, stores=stores)
    if not result["found"]:
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"symbol not found: {result['symbol']}")
        return 2
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0
    print(f"{result['symbol']}  isins={', '.join(result['isins'])}")
    print()
    print(format_table(result["stores"], _COLUMNS))
    print(f"\n{result['stores_with_data']}/{len(result['stores'])} stores hold data, "
          f"{result['total_rows']:,} rows")
    return 0


if __name__ == "__main__":
    main_guard(main)
