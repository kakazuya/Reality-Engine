"""Clean the date columns of ``mkt_nse_insider`` in place; the published text is kept in ``*_raw``.

The legacy NSE PIT feed published ``intimation_date`` as ``'-'`` (1,170 rows) and as typo dates
that land past the disclosure itself (``2036-02-03``, ``2028-05-29``).  ``load_market_raw``
stores whatever the feed said, so readers see a date that cannot be true, plus a ``'-'`` string
that sorts like a date.  The rule applied here is the one ``build_insider_trades`` already uses
for ``insider_trades_v2``: a date is kept only when it parses to ``YYYY-MM-DD`` and falls inside
``2000-01-01 .. disseminated_at + 1 day`` (``today`` when the row has no dissemination stamp).
Everything else becomes NULL and the published text stays in ``<column>_raw``, so a later pass can
audit the source instead of guessing what the typo meant.

Additive only: ``*_raw`` columns are created when absent, cleaned values are overwritten with
NULL.  Idempotent — a second run finds nothing to change.  One short transaction per column.

Usage:
    python -m reality_engine.scripts.clean_insider_dates --dry-run
    python -m reality_engine.scripts.clean_insider_dates
"""

import argparse
import sqlite3
import sys
import time

from reality_engine import config as cfg
from reality_engine.scripts.build_insider_trades import date_is_implausible, iso_date
from reality_engine.scripts.load_market_raw import acquire_queue_lock

TABLE = "mkt_nse_insider"
COLUMNS = ("acq_from", "acq_to", "intimation_date")
ISO_GLOB = "GLOB '[12][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]*'"


def reason(value, known_at):
    """Why a stored value cannot be a real date, or None when it is fine."""
    if value is None:
        return None
    day = iso_date(value)
    if day is None:
        return "unparseable"
    return "out_of_range" if date_is_implausible(day, known_at) else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(cfg.DB_PATH))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--lock-wait", type=int, default=600)
    args = ap.parse_args()

    t0 = time.time()
    conn = sqlite3.connect(args.db, timeout=180)
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({TABLE})")}
    if not cols:
        sys.exit(f"{TABLE} not found in {args.db}")
    wanted = [c for c in COLUMNS if c in cols]
    if not wanted:
        sys.exit(f"none of {COLUMNS} present in {TABLE}")

    lock = None if args.dry_run else acquire_queue_lock(args.lock_wait)
    if not args.dry_run and lock is None:
        sys.exit("queue lock busy (another writer is running); try again later")
    try:
        if not args.dry_run:
            with conn:
                for col in wanted:
                    if f"{col}_raw" not in cols:
                        conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col}_raw TEXT")
                        print(f"added {TABLE}.{col}_raw")
                    # keep the published text once; never overwrite an already-kept raw value
                    n = conn.execute(f"UPDATE {TABLE} SET {col}_raw = {col} "
                                     f"WHERE {col}_raw IS NULL AND {col} IS NOT NULL").rowcount
                    if n:
                        print(f"{col}_raw: kept the published text of {n} rows")

        for col in wanted:
            raw_col = f"{col}_raw" if f"{col}_raw" in cols else "NULL"
            rows = conn.execute(f"SELECT rowid, {col}, {raw_col}, disseminated_at FROM {TABLE} "
                                f"WHERE {col} IS NOT NULL").fetchall()
            bad = [(rid, value, raw, known) for rid, value, raw, known in rows
                   if reason(value, known)]
            counts = {}
            for _, value, _, known in bad:
                tag = reason(value, known)
                counts[tag] = counts.get(tag, 0) + 1
            print(f"\n{col}: {len(rows)} values, {len(bad)} bad {counts or ''}")
            for rid, value, known in [(r[0], r[1], r[3]) for r in rows if reason(r[1], r[3])][:5]:
                print(f"    rowid={rid} {value!r} disseminated_at={known!r} -> NULL")
            if bad and not args.dry_run:
                with conn:
                    conn.executemany(f"UPDATE {TABLE} SET {col} = NULL WHERE rowid = ?",
                                     [(rid,) for rid, _, _, _ in bad])
            left = conn.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE {col} IS NOT NULL").fetchone()[0]
            print(f"    {'would leave' if args.dry_run else 'leaves'} {left} non-NULL values")

        if not args.dry_run:
            for col in wanted:
                bad = conn.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE {col} IS NOT NULL AND "
                                   f"NOT {col} {ISO_GLOB}").fetchone()[0]
                print(f"non-ISO {col} left: {bad}")
    finally:
        conn.close()
        if lock:
            lock.close()
    print(f"\n{'dry run' if args.dry_run else 'done'} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
