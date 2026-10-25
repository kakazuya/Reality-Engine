"""
Normalize the raw NSE/BSE bulk+block deal tables into the labelled ``bulk_block_deals`` contract.

``mkt_nse_deals`` and ``mkt_bse_deals`` hold every published deal exactly as the exchange served
it (no ISIN, no exchange column, separate tables). ``bulk_block_deals`` is what the screener and
the news explainer read, so it is keyed by ISIN and exchange and can be joined to the ISIN anchor
and to price history. This script is the one-way bridge between the two:

  deal_date   from the source row
  exchange    'NSE' / 'BSE'
  symbol      NSE symbol; for BSE the published scrip symbol (scripname, sc_code if absent)
  isin        resolved ON THE DEAL DATE: NSE through symbol_isin_history (validity windows), BSE
              through mkt_bse_eq_daily (ISIN per scrip per day). A ticker is not unique to an ISIN
              over time, so the label is the ISIN valid on that date; unresolved stays NULL and is
              counted, never guessed.
  client_name, buy_sell, quantity, trade_price, deal_type ('BULK'/'BLOCK'),
  is_marquee_institution

Idempotent: ids are deterministic (deals_client's NSE ids unchanged, exchange-scoped for BSE),
so a re-run REPLACES instead of duplicating. Commits per year.

Usage:
    python -m reality_engine.scripts.build_bulk_block_deals
    python -m reality_engine.scripts.build_bulk_block_deals --dry-run --start 2019-01-01
"""

import argparse
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import date

from reality_engine import config as cfg
from reality_engine.ingestion.deals_client import DealsClient, is_marquee_institution, make_deal_id

NSE_SQL = ("SELECT date, client_name, buy_sell, quantity, price, deal_type, symbol, symbol "
           "FROM mkt_nse_deals WHERE date BETWEEN ? AND ?")
BSE_SQL = ("SELECT date, client_name, buy_sell, quantity, price, deal_type, sc_code, "
           "COALESCE(scrip_name, sc_code) FROM mkt_bse_deals WHERE date BETWEEN ? AND ?")


def window_map(conn, sql):
    """{key: [(first_date, last_date, isin), ...]} sorted by first_date; 12-char ISINs only."""
    out = defaultdict(list)
    for key, isin, first, last in conn.execute(sql):
        if isin and len(str(isin)) == 12:
            out[str(key)].append((first or "", last or "", isin))
    for wins in out.values():
        wins.sort()
    return out


def pick(wins, day):
    """The ISIN whose validity window contains ``day``; else the nearest one before it."""
    if not wins:
        return None
    best = None
    for first, last, isin in wins:
        if first <= day <= last:
            return isin
        if first <= day:
            best = isin
    return best if best is not None else wins[0][2]


def load_windows(conn):
    """ISIN maps: dated NSE symbol windows, dated BSE scrip windows, then static fallbacks."""
    nse_wins = window_map(conn, "SELECT symbol, isin, first_date, last_date "
                                "FROM symbol_isin_history WHERE exchange='NSE'")
    bse_wins = window_map(conn, "SELECT sc_code, isin, MIN(date), MAX(date) "
                                "FROM mkt_bse_eq_daily WHERE isin IS NOT NULL GROUP BY sc_code, isin")
    static = {"NSE": {}, "BSE": {}}
    for symbol, isin in conn.execute(
            "SELECT nse_symbol, isin FROM master_companies WHERE nse_symbol IS NOT NULL AND isin IS NOT NULL"):
        static["NSE"].setdefault(symbol, isin)
    for code, isin in conn.execute(
            "SELECT bse_code, isin FROM master_companies WHERE bse_code IS NOT NULL AND isin IS NOT NULL"):
        static["BSE"].setdefault(str(code), isin)
    for isin, symbol, code in conn.execute("SELECT isin, nse_symbol, bse_code FROM security_master"):
        if isin:
            if symbol:
                static["NSE"].setdefault(symbol, isin)
            if code:
                static["BSE"].setdefault(str(code).strip(), isin)
    return {"NSE": nse_wins, "BSE": bse_wins}, static


def resolver(windows, static):
    def resolve(label, day, exchange):
        return pick(windows[exchange].get(label), day) or static[exchange].get(label)
    return resolve


def collect(conn, lo, hi, resolve):
    """Raw deal rows in [lo, hi] -> (bulk_block_deals records, per-bucket counts, unmatched)."""
    records, per, unmatched = [], defaultdict(int), defaultdict(int)
    for exchange, sql in (("NSE", NSE_SQL), ("BSE", BSE_SQL)):
        for deal_date, client, side, qty, price, deal_type, label, symbol in conn.execute(sql, (lo, hi)):
            symbol = str(symbol or "").strip().upper()
            side = str(side or "").strip().upper()
            if not deal_date or not symbol or not client or side not in ("BUY", "SELL") \
                    or qty is None or price is None:
                unmatched[f"{exchange}:malformed"] += 1
                continue
            client = str(client).strip()
            qty, price = int(float(qty)), float(price)
            isin = resolve(str(label), deal_date, exchange)
            if isin is None:
                unmatched[f"{exchange}:no_isin"] += 1
            per[(exchange, deal_type)] += 1
            records.append({
                "id": make_deal_id(deal_date, symbol, client, side, qty, price,
                                   exchange="" if exchange == "NSE" else exchange),
                "deal_date": deal_date, "symbol": symbol, "client_name": client,
                "deal_type": deal_type, "buy_sell": side, "quantity": qty,
                "trade_price": price, "is_marquee_institution": is_marquee_institution(client),
                "exchange": exchange, "isin": isin,
            })
    return records, per, unmatched


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    conn = sqlite3.connect(str(cfg.DB_PATH), timeout=180)
    for p in cfg.SQLITE_PRAGMAS:
        if "foreign_keys" not in p.lower():
            conn.execute(p)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = {"mkt_nse_deals", "mkt_bse_deals", "bulk_block_deals", "symbol_isin_history"} - tables
    if missing:
        sys.exit(f"missing tables: {', '.join(sorted(missing))}")

    print(f"reading ISIN windows from {cfg.DB_PATH} ...", flush=True)
    windows, static = load_windows(conn)
    resolve = resolver(windows, static)
    print(f"  NSE {len(windows['NSE'])} symbols, BSE {len(windows['BSE'])} scrips  "
          f"({time.time() - t0:.0f}s)", flush=True)

    repo = None
    if not args.dry_run:
        from reality_engine.db.repository import repo as _repo  # lazy: no live-DB touch on a dry run
        repo = _repo

    total = 0
    for year in range(int(args.start[:4]), int(args.end[:4]) + 1):
        lo, hi = max(f"{year}-01-01", args.start), min(f"{year}-12-31", args.end)
        records, per, unmatched = collect(conn, lo, hi, resolve)
        if records and repo is not None:
            DealsClient.persist(records, repo=repo)
        total += len(records)
        print(f"{year}  written={len(records):>7}  "
              + "  ".join(f"{e}-{t}={n}" for (e, t), n in sorted(per.items()))
              + (f"  unmatched={dict(unmatched)}" if unmatched else ""), flush=True)

    print(f"\n{total} deal rows {'(dry run)' if args.dry_run else 'upserted'} in {time.time() - t0:.0f}s")
    conn.close()


if __name__ == "__main__":
    main()
