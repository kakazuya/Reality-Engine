"""Missing indexes and text indexes for the query layer (PIPELINE_TODO Q3, 2026-10-19). Idempotent: every statement is
IF NOT EXISTS, and an FTS index is only (re)built when its row count differs from its source table.

FTS5 tables use external content (no second copy of the text) and are kept in sync by insert / delete / update
triggers, so writers (deck extraction, concall_deepseek, policy_register) need no change.

  deck_figures.db      pages(isin, known_at), deck_sources(isin, known_at), facts_metric_fts on facts(metric)
  concall_facts.db     cc_items_fts on cc_items(metric, statement, quote)
  equity_intelligence  policy_events(published_at) exists; adds (instrument), (stage), policy_events_fts(policy_name, quote)
  results_xbrl.db      filings(period_end); covering ix_facts_cover(file, concept, context, value)
  equity_intelligence  covering price indexes (one stock's history from the index alone: cold read 0.24 s -> target
                       < 0.1 s); writers there wait up to 600 s for the build lock

    python -m reality_engine.scripts.build_query_indexes [--only deck,concall,policy,results]
Then run query_speed_check.py.
"""
import argparse
import sqlite3
import time
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"


def fts(con, name, table, cols, rowid="rowid"):
    """External-content FTS5 over `table` (keyed on its rowid) + sync triggers; (re)build when counts differ."""
    col_list = ", ".join(cols)
    new_list = ", ".join(f"new.{c}" for c in cols)
    old_list = ", ".join(f"old.{c}" for c in cols)
    con.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS {name} USING fts5({col_list}, content='{table}', "
                f"content_rowid='{rowid}', tokenize='unicode61')")
    con.execute(f"CREATE TRIGGER IF NOT EXISTS {name}_ai AFTER INSERT ON {table} BEGIN "
                f"INSERT INTO {name}(rowid, {col_list}) VALUES (new.{rowid}, {new_list}); END")
    con.execute(f"CREATE TRIGGER IF NOT EXISTS {name}_ad AFTER DELETE ON {table} BEGIN "
                f"INSERT INTO {name}({name}, rowid, {col_list}) VALUES ('delete', old.{rowid}, {old_list}); END")
    con.execute(f"CREATE TRIGGER IF NOT EXISTS {name}_au AFTER UPDATE OF {col_list} ON {table} BEGIN "
                f"INSERT INTO {name}({name}, rowid, {col_list}) VALUES ('delete', old.{rowid}, {old_list}); "
                f"INSERT INTO {name}(rowid, {col_list}) VALUES (new.{rowid}, {new_list}); END")
    con.commit()
    n_src = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    n_idx = con.execute(f"SELECT COUNT(*) FROM {name}_docsize").fetchone()[0]
    if n_src != n_idx:
        t0 = time.time()
        con.execute(f"INSERT INTO {name}({name}) VALUES ('rebuild')")
        con.commit()
        print(f"  {name}: rebuilt over {n_src:,} rows in {time.time() - t0:.0f}s")
    else:
        print(f"  {name}: in sync ({n_src:,} rows)")


def run(db, stmts, ftss=(), analyze=()):
    con = sqlite3.connect(DATA / db, timeout=120)
    con.execute("PRAGMA busy_timeout = 120000")
    print(db)
    for s in stmts:
        t0 = time.time()
        con.execute(s)
        con.commit()
        print(f"  {s[:90]} ({time.time() - t0:.1f}s)")
    for args in ftss:
        fts(con, *args)
    for t in analyze:
        con.execute(f"ANALYZE {t}")
        con.commit()
    con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="deck,concall,policy,results,prices")
    only = set(ap.parse_args().only.split(","))
    if "deck" in only:
        run("deck_figures.db",
            ["CREATE INDEX IF NOT EXISTS ix_pages_isin ON pages(isin, known_at)",
             "CREATE INDEX IF NOT EXISTS ix_deck_sources_isin ON deck_sources(isin, known_at)"],
            [("facts_metric_fts", "facts", ["metric"])], ["pages", "deck_sources"])
    if "concall" in only:
        run("concall_facts.db", [], [("cc_items_fts", "cc_items", ["metric", "statement", "quote"])])
    if "policy" in only:
        run("equity_intelligence.db",
            ["CREATE INDEX IF NOT EXISTS idx_policy_instrument ON policy_events(instrument)",
             "CREATE INDEX IF NOT EXISTS idx_policy_stage ON policy_events(stage)"],
            [("policy_events_fts", "policy_events", ["policy_name", "quote"], "id")])
    if "results" in only:
        run("results_xbrl.db", ["CREATE INDEX IF NOT EXISTS ix_filings_period ON filings(period_end)",
                                "CREATE INDEX IF NOT EXISTS ix_facts_cover ON facts(file, concept, context, value)"])
    if "prices" in only:
        run("equity_intelligence.db",
            ["CREATE INDEX IF NOT EXISTS idx_mkt_nse_full_cover ON mkt_nse_full_daily(symbol, date, series, open, high, "
             "low, close, volume, turnover_lacs, delivery_pct)",
             "CREATE INDEX IF NOT EXISTS idx_mkt_bse_eq_cover ON mkt_bse_eq_daily(isin, date, open, high, low, close, "
             "volume, turnover_inr)"])


if __name__ == "__main__":
    main()
