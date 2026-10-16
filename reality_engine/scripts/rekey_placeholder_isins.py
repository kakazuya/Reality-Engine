"""Re-key document and annual-report rows from placeholder INE_AUTO_* ISINs to the real ISIN (2026-10-16).

Backfill created INE_AUTO_<SYMBOL> stubs in master_companies. When the real ISIN arrived, the repository's placeholder
promotion re-linked price history only, so filings stayed on the stub: corporate_documents and everything derived from
it (ar_docs, ar_facts, deck pages). AGENTS.md rule 13 quarantines INE_AUTO rows, so real facts were hidden.

Mapping: a row's symbol -> the one real (non-placeholder) master_companies ISIN with that nse_symbol. Symbols with no
real ISIN, or more than one, are left alone. Price and financials tables are NOT touched here (their (isin, date) rows
can collide with the real ISIN's own history; they need a merge, not a re-key).

Every change is logged in equity_intelligence.db table isin_rekey_log (table, old, new, rows, ts), so it can be undone.
Idempotent: a second run finds nothing to do. Updates are committed per symbol so the live AR workers are never blocked
for long.

    python -m reality_engine.scripts.rekey_placeholder_isins            # dry run: counts only
    python -m reality_engine.scripts.rekey_placeholder_isins --apply
"""
import argparse
import collections
import sqlite3
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
TARGETS = [   # (database file, table, symbol column)
    ("equity_intelligence.db", "corporate_documents", "symbol"),
    ("ar_facts.db", "ar_docs", "symbol"),
    ("ar_facts.db", "ar_facts", "symbol"),
    ("ar_facts.db", "ar_facts_replaced", "symbol"),
    ("deck_figures.db", "pages", "symbol"),
]


def real_isin_by_symbol(eq):
    real = collections.defaultdict(set)
    for isin, sym in eq.execute("SELECT isin, nse_symbol FROM master_companies WHERE nse_symbol IS NOT NULL"):
        if isin and isin.startswith("IN") and not isin.startswith("INE_AUTO"):
            real[sym.strip().upper()].add(isin)
    return {s: next(iter(v)) for s, v in real.items() if len(v) == 1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    eq = sqlite3.connect(DATA / "equity_intelligence.db", timeout=300)
    eq.execute("""CREATE TABLE IF NOT EXISTS isin_rekey_log (db TEXT, table_name TEXT, symbol TEXT, old_isin TEXT,
                  new_isin TEXT, n_rows INTEGER, ts TEXT)""")
    mapping = real_isin_by_symbol(eq)
    total = collections.Counter()
    for db, table, symcol in TARGETS:
        con = eq if db == "equity_intelligence.db" else sqlite3.connect(DATA / db, timeout=300)
        pairs = con.execute(f"SELECT {symcol}, isin, COUNT(*) FROM {table} WHERE isin LIKE 'INE_AUTO%' GROUP BY 1, 2").fetchall()
        skipped = 0
        for sym, old, n in pairs:
            new = mapping.get((sym or "").strip().upper())
            if not new:
                skipped += n; continue
            total[(db, table)] += n
            if a.apply:
                cur = con.execute(f"UPDATE {table} SET isin=? WHERE isin=? AND {symcol}=?", (new, old, sym))
                con.commit()
                eq.execute("INSERT INTO isin_rekey_log VALUES (?,?,?,?,?,?,?)",
                           (db, table, sym, old, new, cur.rowcount, datetime.now().isoformat(timespec="seconds")))
                eq.commit()
        print(f"{db}:{table}: {'re-keyed' if a.apply else 'would re-key'} {total[(db, table)]:,} rows; "
              f"{skipped:,} rows left (no single real ISIN for the symbol)")
    if not a.apply:
        print("dry run: nothing changed (use --apply)")


if __name__ == "__main__":
    main()
