"""Market-data session coverage: does every dataset hold every NSE trading session?

The check the P1 market-gap brief asks for, and the one that cannot lie: the expected set is the
trading calendar rebuilt from the bhavcopies we hold (NSE legacy ``mkt_nse_eq_daily`` 2019-01 ..
2021-10, NSE ``mkt_nse_full_daily`` 2019-06-27 .., BSE ``mkt_bse_eq_daily``), minus the known
weekday holidays in ``pipeline.data_audit``, instead of a weekday count or a log line.

Two kinds of dataset, checked differently:

  daily series (bhavcopy, delivery, FII/DII cash, NSDL FPI)
      every session must have rows -> sessions held / calendar, rows, distinct ISINs, missing
      sessions listed as date ranges.  The two NSE bhavcopy tables are reported as one series
      because the full format replaced the legacy one in Oct 2021; either one covers a session.

  event feeds (bulk/block deals)
      a session with no block deal is normal (most have none), so "has rows" is NOT coverage.
      What must hold is that we ASKED the exchange about every session: the raw-file manifest
      (``ok``/``empty`` windows) must cover the calendar.  Rows, sessions with rows and the
      never-fetched sessions are reported; `bulk_block_deals` labels are summarised after.

Read-only.  Uses the live DB from config unless ``--db`` is given.

    python -m reality_engine.scripts.market_session_coverage
    python -m reality_engine.scripts.market_session_coverage --start 2019-01-01 --end 2026-10-23
"""

import argparse
import csv
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from reality_engine import config as cfg
from reality_engine.pipeline.data_audit import NSE_WEEKDAY_HOLIDAYS

DAILY = [
    # label, table, extra WHERE, ISIN expression
    ("NSE bhavcopy (legacy+full, delivery)", "mkt_nse_eq_daily", None, "isin",
     ["mkt_nse_full_daily"]),
    ("BSE bhavcopy", "mkt_bse_eq_daily", None, "isin", []),
    ("BSE delivery", "mkt_bse_delivery_daily", None, None, []),
    ("FII/DII cash", "mkt_fii_dii_cash", None, None, []),
    ("NSDL FPI daily", "mkt_nsdl_fpi_daily", None, None, []),
]

# event feed -> (table, deal_type, raw folder, exchange column or None)
DEALS = [
    ("NSE bulk", "mkt_nse_deals", "BULK", "nse_bulk"),
    ("NSE block", "mkt_nse_deals", "BLOCK", "nse_block"),
    ("BSE bulk", "mkt_bse_deals", "BULK", "bse_bulk"),
    ("BSE block", "mkt_bse_deals", "BLOCK", "bse_block"),
]


def ranges(days):
    """['2019-01-02','2019-01-03','2019-02-01'] -> '2019-01-02..2019-01-03, 2019-02-01'."""
    out, run = [], []
    for day in sorted(days):
        if run and date.fromisoformat(run[-1]) + timedelta(days=1) != date.fromisoformat(day):
            out.append(run[0] if len(run) == 1 else f"{run[0]}..{run[-1]}")
            run = []
        run.append(day)
    if run:
        out.append(run[0] if len(run) == 1 else f"{run[0]}..{run[-1]}")
    return out


def manifest_days(folder, start, end):
    """Sessions the fetcher actually asked about (ok + empty windows), from _manifest.csv."""
    path = cfg.raw_dir("raw_market") / folder / "_manifest.csv"
    days = set()
    if not path.exists():
        return None, path
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            if row.get("status") not in ("ok", "empty"):
                continue
            try:
                lo, hi = row["window"].split("_")
                d, last = date.fromisoformat(lo), date.fromisoformat(hi)
            except (ValueError, KeyError):
                continue
            while d <= last:
                if start <= d.isoformat() <= end:
                    days.add(d.isoformat())
                d += timedelta(days=1)
    return days, path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(cfg.DB_PATH))
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2026-10-23")
    args = ap.parse_args()
    start, end = args.start, args.end

    t0 = time.time()
    db = Path(args.db)
    if not db.exists():
        sys.exit(f"no database at {db}")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=180)
    conn.execute("PRAGMA query_only=1")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    holidays = set(NSE_WEEKDAY_HOLIDAYS)

    calendar = set()
    for table in ("mkt_nse_eq_daily", "mkt_nse_full_daily", "mkt_bse_eq_daily"):
        if table in tables:
            calendar |= {d for (d,) in conn.execute(f"SELECT DISTINCT date FROM {table}") if d}
    # A bulk deal or a FII/DII print can only exist on a session, so those feeds also define the
    # calendar. Without them the bhavcopy dates are circular — a session the bhavcopy missed can
    # never show up as missing. That is exactly how 5 Saturday/Muhurat sessions went unnoticed
    # until 2026-10-26 (the weekday-only web loop skipped them while the exchange published).
    for col, table in (("date", "mkt_nse_deals"), ("date", "mkt_bse_deals"), ("date", "mkt_fii_dii_cash")):
        if table in tables:
            calendar |= {d for (d,) in conn.execute(f"SELECT DISTINCT {col} FROM {table}") if d}
    calendar = {d for d in calendar if start <= d <= end and d not in holidays}

    print(f"DB        {db}")
    print(f"window    {start} .. {end}")
    print(f"calendar  {len(calendar)} sessions {min(calendar)} .. {max(calendar)} "
          f"(bhavcopy dates, {len(holidays)} known weekday holidays excluded)")
    if not calendar:
        sys.exit("no bhavcopy sessions in the window: cannot check anything")

    print("\nDAILY SERIES (every session must have rows)")
    print(f"{'dataset':42} {'sessions':>13} {'rows':>10} {'ISINs':>6}  missing")
    print("-" * 118)
    gaps = []
    for label, table, where, isin_col, extra_tables in DAILY:
        if table not in tables:
            print(f"{label:42} {'absent':>13}")
            gaps.append(f"{table} absent")
            continue
        sources = [table] + [t for t in extra_tables if t in tables]
        held_all, rows = set(), 0
        for src in sources:
            cond = f" WHERE {where}" if where else ""
            held_all |= {d for (d,) in conn.execute(f"SELECT DISTINCT date FROM {src}{cond}") if d}
            rows += conn.execute(f"SELECT COUNT(*) FROM {src} WHERE date BETWEEN ? AND ?",
                                 (start, end)).fetchone()[0]
        held_all = {d for d in held_all if start <= d <= end}
        extra = sorted(held_all - calendar)   # published on a day the calendar calls a holiday
        held = held_all & calendar
        missing = sorted(calendar - held)
        n_isin = "-"
        if isin_col:
            n_isin = conn.execute(
                f"SELECT COUNT(DISTINCT {isin_col}) FROM {table} WHERE date BETWEEN ? AND ?",
                (start, end)).fetchone()[0]
        text = "none" if not missing else _short(missing)
        print(f"{label:42} {f'{len(held)}/{len(calendar)}':>13} {rows:>10} {str(n_isin):>6}  {text}")
        if extra:
            print(f"{'':42} {'':13} {'':10} {'':6}  +{len(extra)} outside the calendar: {_short(extra)}")
        if missing:
            gaps.append(f"{label}: {len(missing)}")

    print("\nEVENT FEEDS (only the fetch can be complete; most sessions have no deal)")
    print(f"{'feed':12} {'rows':>9} {'sessions with rows':>19} {'never fetched':>14}  raw windows")
    print("-" * 118)
    for label, table, deal_type, folder in DEALS:
        if table not in tables:
            print(f"{label:12} {'absent':>9}")
            gaps.append(f"{table} absent")
            continue
        rows, with_rows = conn.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT date) FROM {table} "
            f"WHERE deal_type=? AND date BETWEEN ? AND ?", (deal_type, start, end)).fetchone()
        fetched, path = manifest_days(folder, start, end)
        if fetched is None:
            never = "no manifest"
        else:
            never = len(calendar - fetched)
            if never:
                gaps.append(f"{label}: {never} sessions never fetched")
        windows = len(list(csv.DictReader(path.open()))) if path.exists() else 0
        print(f"{label:12} {rows:>9} {with_rows:>19} {str(never):>14}  "
              f"{windows} windows in {path.parent.name}")
        if fetched:
            unasked = sorted(calendar - fetched)
            if unasked:
                print(f"{'':12} not asked for: {_short(unasked)}")

    print("\nNSE delivery for 2019-01-01..2019-06-26 (the mkt_nse_full_daily gap):")
    rows = conn.execute(
        "SELECT date, SUM(deliverable_qty IS NOT NULL) FROM mkt_nse_eq_daily "
        "WHERE date BETWEEN '2019-01-01' AND '2019-06-26' GROUP BY date ORDER BY date").fetchall()
    void = [d for d, n in rows if not n]
    print(f"  mkt_nse_eq_daily: {len(rows)} sessions, {len(void)} without deliverable qty"
          + (f" ({_short(void)})" if void else ""))
    bse = conn.execute("SELECT COUNT(DISTINCT date) FROM mkt_bse_delivery_daily "
                       "WHERE date BETWEEN '2019-01-01' AND '2019-06-26'").fetchone()[0]
    print(f"  mkt_bse_delivery_daily: {bse} sessions")

    print("\nbulk_block_deals labels:")
    for exchange, n, with_isin, n_isin in conn.execute(
            "SELECT exchange, COUNT(*), COUNT(isin), COUNT(DISTINCT isin) FROM bulk_block_deals "
            "WHERE deal_date BETWEEN ? AND ? GROUP BY exchange", (start, end)):
        print(f"  {exchange}: {n} rows, {with_isin} with ISIN "
              f"({100 * with_isin / n:.2f}%), {n_isin} distinct ISINs")
    unresolved = conn.execute(
        "SELECT exchange, symbol, COUNT(*) FROM bulk_block_deals "
        "WHERE isin IS NULL AND deal_date BETWEEN ? AND ? GROUP BY exchange, symbol "
        "ORDER BY 3 DESC LIMIT 12", (start, end)).fetchall()
    if unresolved:
        print("  top unresolved: " + ", ".join(f"{e}:{s}({n})" for e, s, n in unresolved))

    print("\nmkt_nse_insider date columns (raw text kept in <column>_raw):")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(mkt_nse_insider)")}
    for col in ("acq_from", "acq_to", "intimation_date"):
        if col not in cols:
            continue
        n, bad = conn.execute(
            f"SELECT COUNT(*), SUM({col} IS NOT NULL AND NOT ({col} GLOB "
            f"'[12][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]*')) FROM mkt_nse_insider").fetchone()
        future = conn.execute(f"SELECT COUNT(*) FROM mkt_nse_insider "
                              f"WHERE {col} IS NOT NULL AND {col} > ?", (end,)).fetchone()[0]
        kept = f"{col}_raw" in cols
        print(f"  {col}: {n} rows, {bad or 0} non-ISO, {future} after {end}"
              + ("" if kept else "  (no raw column)"))

    print(f"\n{'OK - no session gaps' if not gaps else 'GAPS: ' + '; '.join(gaps)}  "
          f"({time.time() - t0:.0f}s)")
    conn.close()


def _short(days, limit=6):
    out = ranges(days)
    return ", ".join(out[:limit]) + (f" (+{len(out) - limit} ranges)" if len(out) > limit else "")


if __name__ == "__main__":
    main()
