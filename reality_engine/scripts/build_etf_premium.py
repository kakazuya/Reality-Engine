"""Materialise ``equity_intelligence.db:etf_premium`` (price vs NAV, plus the iNAV gap).

``fetch_etf_nav.py`` creates ``etf_premium`` as a live view over ``etf_px`` and
``fund_nav``; it has no iNAV gap and cannot be upserted.  This job keeps the raw
rows in ``etf_premium_rows`` (primary key isin, date) and exposes the same
public name as a view that also adds ``inav`` and ``inav_gap_pct`` from
``etf_inav``.  Re-running ``fetch_etf_nav`` recreates its own view, so this job
must run after it (it does not touch any other table).

Idempotent: one UPSERT per (isin, date).

Usage:
    python -m reality_engine.scripts.build_etf_premium
    python -m reality_engine.scripts.build_etf_premium --since 2026-09-01
"""
from __future__ import annotations

import argparse
import sqlite3

from reality_engine.toolbelt._common import resolve_db

ROW_TABLE = """
CREATE TABLE IF NOT EXISTS etf_premium_rows (
  isin TEXT NOT NULL,
  symbol TEXT,
  date TEXT NOT NULL,
  close REAL,
  nav REAL,
  premium_pct REAL,
  value_inr REAL,
  inav REAL,
  inav_gap_pct REAL,
  PRIMARY KEY (isin, date));
"""

VIEW_SQL = """CREATE VIEW etf_premium AS
    SELECT isin, symbol, date, close, nav, premium_pct, value_inr, inav, inav_gap_pct
    FROM etf_premium_rows"""

UPSERT = """INSERT INTO etf_premium_rows
    (isin, symbol, date, close, nav, premium_pct, value_inr, inav, inav_gap_pct)
    VALUES (?,?,?,?,?,?,?,?,?)
    ON CONFLICT(isin, date) DO UPDATE SET
      symbol = excluded.symbol, close = excluded.close, nav = excluded.nav,
      premium_pct = excluded.premium_pct, value_inr = excluded.value_inr,
      inav = excluded.inav, inav_gap_pct = excluded.inav_gap_pct"""


def ensure_schema(con: sqlite3.Connection) -> None:
    con.execute(ROW_TABLE)
    kind = con.execute("SELECT type FROM sqlite_master WHERE name = 'etf_premium'").fetchone()
    if kind:
        # An older materialisation of this feed: rebuild it from the rows table.
        con.execute("DROP TABLE etf_premium" if kind[0] == "table" else "DROP VIEW etf_premium")
    con.execute(VIEW_SQL)
    con.commit()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build etf_premium from etf_px, fund_nav and etf_inav.")
    ap.add_argument("--db", help="equity_intelligence database (default: REALITY_DATA_ROOT/equity_intelligence.db)")
    ap.add_argument("--since", help="only prices on/after YYYY-MM-DD")
    args = ap.parse_args(argv)

    db = resolve_db(args.db or "equity_intelligence")
    con = sqlite3.connect(db, timeout=600)
    con.execute("PRAGMA busy_timeout = 600000")
    ensure_schema(con)

    sql = """SELECT p.isin, p.symbol, p.date, p.close, n.nav, p.value_inr,
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

    rows = []
    for isin, symbol, date, close, nav, value_inr, inav, gap in source:
        premium = 100.0 * (close / nav - 1)
        if gap is None and inav:
            gap = 100.0 * (close / inav - 1)
        rows.append((isin, symbol, date, close, nav, premium, value_inr, inav, gap))
    with con:
        con.executemany(UPSERT, rows)

    count, first, last = con.execute(
        "SELECT COUNT(*), MIN(date), MAX(date) FROM etf_premium").fetchone()
    con.close()
    print(f"etf_premium: {len(rows)} rows upserted; {count} rows, {first} .. {last}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
