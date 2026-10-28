"""Fill the equity-bhavcopy date gaps in the held price tables (download only).

Two questions, one script:

1. **Date level** — which sessions did the exchange publish but our bhavcopy
   tables do not hold? ``mkt_nse_index_daily`` is the session calendar (the
   index bhavcopy is published every trading day); a session is *held* if any
   of ``mkt_nse_eq_daily`` / ``mkt_nse_full_daily`` / ``mkt_bse_eq_daily`` /
   ``mkt_nse_sme_daily`` has a row for it. Only those dates are fetched.
2. **Name level** — NSE symbols in ``symbol_isin_history`` with no row in
   ``mkt_nse_full_daily`` (delisted / SME / BSE-only names, the 19
   ``needs_new_fetch:bhavcopy_backfill`` cases). A name can only be recovered
   by re-fetching the sessions inside its own trading window, so ``--names``
   adds those dates. It is expensive by design and off by default.

The actual downloads are delegated to ``fetch_market_raw``'s already-tested
``Source`` classes (manifest, resume, per-source validity check): this script
only decides *which dates* they should run for, via their ``only=`` argument.

All database access is read-only and bounded (``connect_ro``).

Usage:
    python -m reality_engine.scripts.fetch_eq_bhavcopy_gaps --dry-run
    python -m reality_engine.scripts.fetch_eq_bhavcopy_gaps
    python -m reality_engine.scripts.fetch_eq_bhavcopy_gaps --names --from 2024-01-01
"""

from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from reality_engine.db.readonly import connect_ro

CALENDAR_TABLE = "mkt_nse_index_daily"
HELD_TABLES = ("mkt_nse_eq_daily", "mkt_nse_full_daily",
               "mkt_bse_eq_daily", "mkt_nse_sme_daily")
DEFAULT_SOURCES = ("nse_full", "bse_bhav")   # serve every date in 2019-01-01..
PACE_SEC = 1.0                               # fetch_market_raw.PACE_SEC


def _db_path(explicit: str = "") -> Path:
    if explicit:
        return Path(explicit)
    root = os.environ.get("REALITY_DATA_ROOT")
    return Path(root) / "equity_intelligence.db" if root else \
        Path(__file__).resolve().parents[1] / "data" / "equity_intelligence.db"


def date_set(con, table: str, start: str = "", end: str = "") -> set[str]:
    """Distinct dates in one table (one indexed/covering column scan)."""
    sql = f"SELECT DISTINCT date FROM {table}"
    where, params = [], []
    if start:
        where.append("date >= ?")
        params.append(start)
    if end:
        where.append("date <= ?")
        params.append(end)
    if where:
        sql += " WHERE " + " AND ".join(where)
    return {r[0] for r in con.execute(sql, params)}


def gap_dates(con, start: str = "", end: str = "") -> tuple[list[str], list[str]]:
    """(real sessions missing, weekend calendar rows that are not sessions)."""
    calendar = date_set(con, CALENDAR_TABLE, start, end)
    held: set[str] = set()
    for table in HELD_TABLES:
        held |= date_set(con, table, start, end)
    missing = sorted(calendar - held)
    real = [d for d in missing if date.fromisoformat(d).weekday() < 5]
    suspect = [d for d in missing if date.fromisoformat(d).weekday() >= 5]
    return real, suspect


def name_gaps(con, start: str = "", limit: int = 5000) -> list[dict]:
    """NSE symbols with a trading window but no row in EITHER NSE bhavcopy table.

    ``mkt_nse_full_daily`` starts 2019-06-27 and ``mkt_nse_eq_daily`` (the
    old-format file) covers 2019-01..2021-10, so a symbol missing from one can
    still be held in the other; checking only one would invent gaps. Two
    single-column distinct scans, then a filtered scan of the symbol history:
    bounded, and no per-symbol probe on a table without a symbol index.

    BSE-only names cannot be checked the same way because ``mkt_bse_eq_daily``
    has no ``sc_code`` index; that gap is reported, not guessed at.
    """
    held = {r[0] for r in con.execute("SELECT DISTINCT symbol FROM mkt_nse_full_daily")}
    held |= {r[0] for r in con.execute("SELECT DISTINCT symbol FROM mkt_nse_eq_daily")}
    rows = con.execute(
        """SELECT symbol, MIN(first_date), MAX(last_date)
           FROM symbol_isin_history
           WHERE exchange = 'NSE' AND (last_date >= ? OR last_date IS NULL)
           GROUP BY symbol ORDER BY 2""",
        (start or "1900-01-01",))
    out = [{"symbol": symbol, "first_date": first, "last_date": last}
           for symbol, first, last in rows if symbol not in held]
    return out[:limit]


def name_gap_dates(names: list[dict], start: str = "", end: str = "") -> list[date]:
    """Union of the named symbols' trading windows, clipped to [start, end]."""
    lo = date.fromisoformat(start) if start else date(1900, 1, 1)
    hi = date.fromisoformat(end) if end else date.today()
    dates: set[date] = set()
    for n in names:
        try:
            a = max(date.fromisoformat(n["first_date"]), lo)
            b = min(date.fromisoformat(n["last_date"] or hi.isoformat()), hi)
        except (TypeError, ValueError):
            continue
        while a <= b:
            dates.add(a)
            a = date.fromordinal(a.toordinal() + 1)
    return sorted(d for d in dates if d.weekday() < 5)


def plan(dates: list[date], sources: tuple[str, ...], interval: float = PACE_SEC) -> dict:
    return {
        "sessions": len(dates),
        "sources": ",".join(sources),
        "requests": len(dates) * len(sources),
        "max_requests": len(dates) * len(sources) * 3,
        "est_minutes_p50": round(len(dates) * len(sources) * (interval + 0.30) / 60, 1),
        "est_minutes_p95": round(len(dates) * len(sources) * (interval + 2.0) / 60, 1),
    }


def fetch(dates: list[date], sources: tuple[str, ...]) -> dict:
    """Run the existing fetch_market_raw sources for exactly ``dates``."""
    from reality_engine.scripts import fetch_market_raw as fmr

    results = {}
    for name in sources:
        cls, cap = fmr.SOURCES[name]
        start = min(dates)
        end = max(dates) if cap is None else min(max(dates), cap)
        results[name] = cls(start, end, only=dates).run()
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="", help="equity_intelligence.db (default: REALITY_DATA_ROOT)")
    ap.add_argument("--from", dest="start", default="")
    ap.add_argument("--to", dest="end", default="")
    ap.add_argument("--sources", default=",".join(DEFAULT_SOURCES))
    ap.add_argument("--names", action="store_true",
                    help="also add the delisted/SME names' windows (expensive)")
    ap.add_argument("--limit-names", type=int, default=5000)
    ap.add_argument("--dry-run", action="store_true", help="plan only: no network, no writes")
    args = ap.parse_args(argv)

    con = connect_ro(_db_path(args.db), timeout_s=120)
    try:
        real, suspect = gap_dates(con, args.start, args.end)
        names = name_gaps(con, args.start, args.limit_names)
    finally:
        con.close()

    dates = [date.fromisoformat(d) for d in real]
    if args.names:
        dates = sorted(set(dates) | set(name_gap_dates(names, args.start, args.end)))

    print(f"calendar {CALENDAR_TABLE}: {'..'.join(x for x in (args.start, args.end) if x) or 'all'}")
    print(f"  date gaps (weekday sessions)   {len(real)}  {real[:12]}")
    print(f"  calendar rows not sessions     {len(suspect)}  {suspect[:12]}"
          "  (index bhavcopy on a weekend: not fetched)")
    print(f"  names with no NSE bhavcopy row {len(names)}"
          f"  first 5: {[(n['symbol'], n['first_date'], n['last_date']) for n in names[:5]]}")
    print(f"  sessions to fetch              {len(dates)}")
    for k, v in plan(dates, tuple(args.sources.split(","))).items():
        print(f"  {k:18} {v}")
    if args.dry_run or not dates:
        print("dry-run: no request made" if args.dry_run else "nothing to fetch")
        return 0

    print(f"fetched: {fetch(dates, tuple(args.sources.split(',')))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
