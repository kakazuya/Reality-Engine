"""T-099: remove the holiday copy rows from ``daily_price_delivery`` and restore 2021-11-04.

T-089 (`price_holiday_copies.py`) found 56 non-session dates whose rows repeat the previous session
(111,535 rows, plan CSV) and 2021-11-04, a real Muhurat session overwritten by 2021-11-03's file.
This script, in order:

1. checks every plan date still repeats the previous stored date on all eight traded fields
   (stops otherwise);
2. backs up the whole table to parquet under ``--backup-dir`` (indicator columns change too);
3. in one transaction deletes the plan rows and replaces 2021-11-04 with the EQ/BE rows of
   ``mkt_nse_full_daily`` (NSE's own full bhavcopy for that day);
4. recomputes the rolling indicators for every symbol in chunks
   (``HistoricalBackfillManager.recalculate_all_technical_indicators(symbols)``).

Dry run by default; ``--apply`` writes. The writer fault itself is fixed in
``nse_client.fetch_bhavcopy`` (DATE1 must print the asked date).
"""
from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
import time
from pathlib import Path

MUHURAT = "2021-11-04"
TRADED = ["open", "high", "low", "close", "prev_close", "total_volume", "num_trades", "deliverable_volume"]


def plan_dates(plan: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    with open(plan, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[row["date"]] = out.get(row["date"], 0) + 1
    return out


def check_copies(conn: sqlite3.Connection, dates: dict[str, int]) -> list[str]:
    """Return problems; empty when every plan date is still an exact copy of the previous stored date."""
    problems = []
    same = " AND ".join(f"a.{c} IS b.{c}" for c in TRADED)
    for d, planned in sorted(dates.items()):
        prev = conn.execute("SELECT MAX(date) FROM daily_price_delivery WHERE date < ?", (d,)).fetchone()[0]
        rows = conn.execute("SELECT COUNT(*) FROM daily_price_delivery WHERE date = ?", (d,)).fetchone()[0]
        copies = conn.execute(
            f"SELECT COUNT(*) FROM daily_price_delivery a JOIN daily_price_delivery b "
            f"ON b.symbol = a.symbol AND b.date = ? WHERE a.date = ? AND {same}", (prev, d)).fetchone()[0]
        if rows != planned or copies != planned:
            problems.append(f"{d}: rows {rows}, copies of {prev} {copies}, plan {planned}")
    return problems


def backup(conn: sqlite3.Connection, out: Path) -> int:
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    out.parent.mkdir(parents=True, exist_ok=True)
    years = [r[0] for r in conn.execute(
        "SELECT DISTINCT substr(date, 1, 4) FROM daily_price_delivery ORDER BY 1")]
    writer = None
    total = 0
    for y in years:
        df = pd.read_sql_query("SELECT * FROM daily_price_delivery WHERE date LIKE ? ORDER BY date, symbol",
                               conn, params=(f"{y}%",))
        table = pa.Table.from_pandas(df, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(out, table.schema, compression="zstd")
        writer.write_table(table.cast(writer.schema))
        total += len(df)
    if writer is not None:
        writer.close()
    return total


def muhurat_rows(conn: sqlite3.Connection) -> list[tuple]:
    """2021-11-04 EQ/BE rows from NSE's full bhavcopy table, shaped like the backfill writer's rows."""
    isin = dict(conn.execute(
        "SELECT symbol, isin FROM daily_price_delivery WHERE date = (SELECT MAX(date) FROM daily_price_delivery "
        "WHERE date < ?)", (MUHURAT,)))
    master = dict(conn.execute(
        "SELECT nse_symbol, isin FROM master_companies WHERE nse_symbol IS NOT NULL"))
    rows = []
    for (sym, series, prev, opn, high, low, close, vol, turn, trades, deliv, dpct) in conn.execute(
            "SELECT symbol, series, prev_close, open, high, low, close, volume, turnover_lacs, num_trades, "
            "deliverable_qty, delivery_pct FROM mkt_nse_full_daily WHERE date = ? AND series IN ('EQ','BE')",
            (MUHURAT,)):
        prev = prev or 0.0
        change = round((close - prev) / prev * 100.0, 2) if prev > 0 else 0.0
        code = isin.get(sym) or master.get(sym) or f"INE_AUTO_{sym}"
        rows.append((MUHURAT, sym, code, series, opn or 0.0, high or 0.0, low or 0.0, close or 0.0, prev,
                     change, int(vol or 0), turn or 0.0, int(trades or 0), int(deliv or 0), dpct or 0.0))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--plan", required=True, help="T-089 delete plan CSV (date,symbol)")
    ap.add_argument("--backup-dir", required=True)
    ap.add_argument("--chunk", type=int, default=400, help="symbols per indicator chunk")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    dates = plan_dates(Path(a.plan))
    if MUHURAT in dates:
        print("plan holds the Muhurat session; refusing"); return 2
    conn = sqlite3.connect(a.db, timeout=60)
    t = time.time()
    problems = check_copies(conn, dates)
    print(f"plan: {len(dates)} dates, {sum(dates.values())} rows; check {time.time() - t:.0f} s, "
          f"problems {len(problems)}")
    for p in problems:
        print("  " + p)
    if problems:
        return 1
    new_rows = muhurat_rows(conn)
    old = conn.execute("SELECT COUNT(*) FROM daily_price_delivery WHERE date = ?", (MUHURAT,)).fetchone()[0]
    print(f"{MUHURAT}: replace {old} copied rows with {len(new_rows)} NSE rows")
    if not a.apply:
        print("dry run: nothing written"); return 0

    out = Path(a.backup_dir) / "daily_price_delivery_before_T-099.parquet"
    n = backup(conn, out)
    print(f"backup {n} rows -> {out} ({out.stat().st_size / 1e6:.0f} MB)")

    marks = ",".join("?" * len(dates))
    with conn:
        gone = conn.execute(f"DELETE FROM daily_price_delivery WHERE date IN ({marks})", list(dates)).rowcount
        conn.execute("DELETE FROM daily_price_delivery WHERE date = ?", (MUHURAT,))
        conn.executemany(
            "INSERT INTO daily_price_delivery (date, symbol, isin, series, open, high, low, close, prev_close, "
            "change_pct, total_volume, turnover_lacs, num_trades, deliverable_volume, delivery_pct) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", new_rows)
    print(f"deleted {gone} holiday rows; {MUHURAT} now {len(new_rows)} rows")
    symbols = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM daily_price_delivery ORDER BY 1")]
    conn.close()

    os.environ["REALITY_ENGINE_DB_PATH"] = str(Path(a.db).resolve())
    from reality_engine.pipeline.backfill import HistoricalBackfillManager

    mgr = HistoricalBackfillManager()
    done = 0
    for i in range(0, len(symbols), a.chunk):
        done += mgr.recalculate_all_technical_indicators(symbols[i:i + a.chunk])
        print(f"indicators: {min(i + a.chunk, len(symbols))}/{len(symbols)} symbols, {done} rows", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
