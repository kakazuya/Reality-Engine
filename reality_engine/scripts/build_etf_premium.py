"""Materialise ``equity_intelligence.db:etf_premium_daily`` (price vs NAV, plus the iNAV gap).

``fetch_etf_nav.py`` owns the live ``etf_premium`` view over ``etf_px`` and
``fund_nav``; this job must not create, drop or replace it.  It upserts one row per
(ETF, date) into ``etf_premium_daily``, adding ``inav`` and ``inav_gap_pct`` from
``etf_inav``, so the two writers no longer share one table.

Idempotent: one UPSERT per (date, isin).

Usage:
    python -m reality_engine.scripts.build_etf_premium
    python -m reality_engine.scripts.build_etf_premium --since 2026-09-01
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime

from reality_engine.toolbelt._common import resolve_db

DAILY_TABLE = """
CREATE TABLE IF NOT EXISTS etf_premium_daily (
  date TEXT NOT NULL,
  isin TEXT NOT NULL,
  symbol TEXT,
  close REAL,
  nav REAL,
  premium_pct REAL,
  inav REAL,
  inav_gap_pct REAL,
  built_at TEXT NOT NULL,
  PRIMARY KEY (date, isin));
"""

UPSERT = """INSERT INTO etf_premium_daily
    (date, isin, symbol, close, nav, premium_pct, inav, inav_gap_pct, built_at)
    VALUES (?,?,?,?,?,?,?,?,?)
    ON CONFLICT(date, isin) DO UPDATE SET
      symbol = excluded.symbol, close = excluded.close, nav = excluded.nav,
      premium_pct = excluded.premium_pct, inav = excluded.inav,
      inav_gap_pct = excluded.inav_gap_pct, built_at = excluded.built_at"""


def ensure_schema(con: sqlite3.Connection) -> None:
    con.execute(DAILY_TABLE)
    con.commit()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build etf_premium_daily from etf_px, fund_nav and etf_inav.")
    ap.add_argument("--db", help="equity_intelligence database (default: REALITY_DATA_ROOT/equity_intelligence.db)")
    ap.add_argument("--since", help="only prices on/after YYYY-MM-DD")
    args = ap.parse_args(argv)

    db = resolve_db(args.db or "equity_intelligence")
    con = sqlite3.connect(db, timeout=600)
    con.execute("PRAGMA busy_timeout = 600000")
    ensure_schema(con)

    sql = """SELECT p.isin, p.symbol, p.date, p.close, n.nav,
                    i.inav, i.premium_vs_inav_pct
             FROM etf_px p
             JOIN fund_nav n ON n.isin = p.isin AND n.date = p.date
             LEFT JOIN etf_inav i ON i.isin = p.isin AND i.date = p.date
             WHERE p.close > 0 AND n.nav > 0"""
    params: list[object] = []
    if args.since:
        sql += " AND p.date >= ?"
        params.append(args.since)
    sql += " ORDER BY p.date, p.isin"
    source = con.execute(sql, params).fetchall()

    built_at = datetime.now().isoformat(timespec="seconds")
    rows = []
    for isin, symbol, date, close, nav, inav, gap in source:
        premium = 100.0 * (close / nav - 1)
        if gap is None and inav:
            gap = 100.0 * (close / inav - 1)
        rows.append((date, isin, symbol, close, nav, premium, inav, gap, built_at))
    with con:
        con.executemany(UPSERT, rows)

    count, first, last = con.execute(
        "SELECT COUNT(*), MIN(date), MAX(date) FROM etf_premium_daily").fetchone()
    con.close()
    print(f"etf_premium_daily: {len(rows)} rows upserted; {count} rows, {first} .. {last}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
