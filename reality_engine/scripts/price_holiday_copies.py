"""Holiday copy rows in ``daily_price_delivery``: find them, never touch them (T-089).

A *holiday copy* is a stored date whose rows repeat the previous stored date
exactly on the traded fields (open, high, low, close, prev_close, total_volume,
num_trades, deliverable_volume).  ``nse_client.fetch_bhavcopy`` overwrites the
file's date with the date it asked for and validates only the column set, so a
non-session date that served the previous session's bhavcopy becomes a full
duplicate session; the derived indicator columns differ because the backfill
recomputes them on top.

Read-only: the store is opened ``file:...?mode=ro`` with ``query_only``.  The
optional ``--apply-plan`` writes the (date, symbol) rows it would delete to a
CSV and deletes nothing; it covers only dates the NSE calendar says were not
sessions.  A copy on a real session (2021-11-04 is one: its Muhurat session was
overwritten by the previous day's file) is reported separately and must be
replaced from the bhavcopy, not deleted.

    python -m reality_engine.scripts.price_holiday_copies
    python -m reality_engine.scripts.price_holiday_copies --start 2025-12-01 --end 2026-03-31
    python -m reality_engine.scripts.price_holiday_copies --apply-plan .tmp/T-089_delete_plan.csv
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional, Sequence

from reality_engine import config as cfg
from reality_engine.pipeline.data_audit import NSE_WEEKDAY_HOLIDAYS

# The fields a stale bhavcopy copies exactly; the SMA/RSI/delivery-spike columns
# are recomputed by the backfill and only match by the coincidence of a repeat.
TRADED_FIELDS = (
    "open", "high", "low", "close", "prev_close",
    "total_volume", "num_trades", "deliverable_volume",
)

# NSE's own session calendar: a weekday an NSE bhavcopy/index file exists for is
# a session; one it does not cover is a holiday (or an ingest gap, hence "yes"
# is reported with that caveat).
NSE_SESSION_TABLES = ("mkt_nse_eq_daily", "mkt_nse_full_daily", "mkt_nse_index_daily")

DEFAULT_PLAN = Path(".tmp") / "T-089_delete_plan.csv"


def connect_ro(db: Path) -> sqlite3.Connection:
    """Open ``db`` read-only (mode=ro URI), never writable."""
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=60)
    con.execute("PRAGMA query_only=1")
    con.execute("PRAGMA temp_store=MEMORY")
    return con


def _identical(alias_a: str = "a", alias_b: str = "b") -> str:
    """SQL predicate: every traded field of a equals b, NULL included."""
    return " AND ".join(f"{alias_a}.{f} IS {alias_b}.{f}" for f in TRADED_FIELDS)


def _nse_tables(con: sqlite3.Connection) -> list[str]:
    have = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return [t for t in NSE_SESSION_TABLES if t in have]


def holiday_label(con: sqlite3.Connection, day: date, tables: Sequence[str]) -> str:
    """``yes`` / ``no`` / ``weekend`` / ``unknown`` for one stored date."""
    if day.weekday() >= 5:
        return "weekend"
    if day.isoformat() in NSE_WEEKDAY_HOLIDAYS:
        return "yes"
    if not tables:
        return "unknown"
    for table in tables:
        if con.execute(f"SELECT 1 FROM {table} WHERE date = ? LIMIT 1", (day.isoformat(),)).fetchone():
            return "no"
    return "yes"


def scan(
    con: sqlite3.Connection,
    start: Optional[str] = None,
    end: Optional[str] = None,
    min_share: float = 0.5,
) -> list[dict]:
    """Return the dates whose rows mostly repeat the previous stored date.

    One pass: each row is matched, by ``(symbol, date)``, to the same symbol on
    the previous stored date of the whole table, so a symbol absent that day
    simply is not a copy row.
    """
    where, params = "", []
    if start:
        where += " AND a.date >= ?"
        params.append(start)
    if end:
        where += " AND a.date <= ?"
        params.append(end)
    sql = f"""
        WITH pairs AS (
            SELECT date AS d, LAG(date) OVER (ORDER BY date) AS p
            FROM (SELECT DISTINCT date FROM daily_price_delivery)
        )
        SELECT a.date, COUNT(*) AS rows_,
               SUM(CASE WHEN b.symbol IS NOT NULL AND {_identical()}
                        THEN 1 ELSE 0 END) AS identical_,
               pairs.p AS prev_date
        FROM daily_price_delivery a
        JOIN pairs ON pairs.d = a.date
        LEFT JOIN daily_price_delivery b
               ON b.symbol = a.symbol AND b.date = pairs.p
        WHERE pairs.p IS NOT NULL{where}
        GROUP BY a.date
        ORDER BY a.date
    """
    tables = _nse_tables(con)
    out: list[dict] = []
    for stored, rows, identical, prev in con.execute(sql, params):
        if not rows or identical / rows < min_share:
            continue
        day = date.fromisoformat(str(stored)[:10])
        out.append({
            "date": day.isoformat(),
            "weekday": day.strftime("%a"),
            "rows": int(rows),
            "identical": int(identical),
            "share": round(identical / rows, 4),
            "holiday": holiday_label(con, day, tables),
            "prev_date": str(prev)[:10],
        })
    return out


def write_plan(con: sqlite3.Connection, copies: Sequence[dict], path: Path) -> int:
    """Write the (date, symbol) copy rows a delete would remove; never delete.

    Callers pass holiday-labelled dates only: deleting a copy that overwrote a
    real session would remove the session, not a duplicate.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "symbol"])
        for copy in copies:
            sql = f"""
                SELECT a.symbol FROM daily_price_delivery a
                JOIN daily_price_delivery b
                  ON b.symbol = a.symbol AND b.date = ?
                WHERE a.date = ? AND {_identical()}
                ORDER BY a.symbol
            """
            for (symbol,) in con.execute(sql, (copy["prev_date"], copy["date"])):
                writer.writerow([copy["date"], symbol])
                written += 1
    return written


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="List holiday copies in daily_price_delivery (read-only; never deletes)."
    )
    parser.add_argument("--db", default=str(cfg.DB_PATH), help="store to read (default: config DB_PATH)")
    parser.add_argument("--start", help="first stored date to report (YYYY-MM-DD)")
    parser.add_argument("--end", help="last stored date to report (YYYY-MM-DD)")
    parser.add_argument("--min-share", type=float, default=0.5,
                        help="report a date when this share of its rows equals the prior date (default 0.5)")
    parser.add_argument("--apply-plan", nargs="?", const=str(DEFAULT_PLAN), default=None,
                        metavar="CSV", help=f"write the (date, symbol) rows a delete would remove (default: {DEFAULT_PLAN})")
    args = parser.parse_args(argv)

    db = Path(args.db)
    if not db.exists():
        print(f"error: no database at {db}")
        return 2
    try:
        con = connect_ro(db)
        scanned = con.execute("SELECT COUNT(DISTINCT date) FROM daily_price_delivery").fetchone()[0]
    except sqlite3.Error as exc:
        print(f"error: cannot read {db}: {exc}")
        return 2

    t0 = time.time()
    copies = scan(con, start=args.start, end=args.end, min_share=args.min_share)
    try:
        print(f"store            {db}")
        window = f"{args.start or 'first'} .. {args.end or 'last'}"
        print(f"window           {window}  ({scanned} stored dates)")
        print(f"equal fields     {', '.join(TRADED_FIELDS)}")
        print(f"threshold        {args.min_share:.2f} of a date's rows identical to the prior stored date")
        print()
        if not copies:
            print("no holiday copies found")
        else:
            print(f"{'date':12} {'day':4} {'rows':>7} {'identical':>10} {'share':>6}  nse holiday")
            print("-" * 66)
            for copy in copies:
                print(f"{copy['date']:12} {copy['weekday']:4} {copy['rows']:>7} "
                      f"{copy['identical']:>10} {copy['share']:>6.3f}  {copy['holiday']}")
            print(f"\n{len(copies)} suspect date(s), "
                  f"{sum(c['identical'] for c in copies)} copy row(s)")
            print("nse holiday is inferred from NSE bhavcopy/index absence; "
                  "'yes' can also be a market-feed gap.")
            if any(c["holiday"] != "yes" for c in copies):
                print("a full copy on nse holiday 'no' is a real session overwritten by the "
                      "previous file: replace it from the bhavcopy, do not delete.")
        if args.apply_plan:
            holiday_copies = [c for c in copies if c["holiday"] == "yes"]
            plan_path = Path(args.apply_plan)
            written = write_plan(con, holiday_copies, plan_path)
            skipped = sum(c["identical"] for c in copies if c["holiday"] != "yes")
            print(f"\nplan: {written} (date, symbol) rows would be deleted -> {plan_path} (nothing deleted)")
            if skipped:
                print(f"      {skipped} row(s) on dates NSE did publish are not in the plan: "
                      "replace from the bhavcopy, do not delete")
    finally:
        con.close()
    print(f"({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
