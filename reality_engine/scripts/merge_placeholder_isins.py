"""Merge every remaining INE_AUTO_* placeholder ISIN into its real ISIN, across all tables (2026-10-16).

Follows rekey_placeholder_isins.py (documents/AR facts, by symbol). Mapping file: RAW_ROOT/ar_queue/
placeholder_isin_map.json  {placeholder: [source, real_isin, history]} where source is master (one real ISIN in
master_companies for the symbol), nse / bse (latest ISIN the symbol traded under in mkt_nse_eq_daily /
mkt_bse_eq_daily) or none (left alone).

Per table:
  - plain re-key (rows are keyed by symbol/id/date, so the ISIN column cannot collide): UPDATE isin.
  - keyed by ISIN (quarterly_financials, annual_financials, company_forensic_health, company_distilled_parameters):
    rows whose key is free move to the real ISIN; rows whose key the real ISIN already holds stay out: the real
    row wins and the placeholder row moves to <table>_placeholder_archive (then is removed from the table).
master_companies: a real ISIN missing from master gets a row (copied from the stub, symbol/scrip set); the stub is
set is_active=0 (kept, so old references stay valid). Every change is logged in isin_rekey_log.

    python -m reality_engine.scripts.merge_placeholder_isins            # dry run
    python -m reality_engine.scripts.merge_placeholder_isins --apply
"""
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from reality_engine.config import raw_dir

DATA = Path(__file__).resolve().parents[1] / "data"
EQ_PLAIN = ["corporate_documents", "daily_price_delivery", "eod_scrip_calls", "intelligence_fts", "document_chunks",
            "moat_evaluations", "business_model_profiles", "financial_metrics", "regulatory_political_risks",
            "telegram_post_tags"]
EQ_KEYED = {"quarterly_financials": ["quarter_end_date"], "annual_financials": ["fiscal_year"],
            "company_forensic_health": [], "company_distilled_parameters": ["parameter_key"]}
OTHER = [("ar_facts.db", "ar_docs"), ("ar_facts.db", "ar_facts"), ("ar_facts.db", "ar_facts_replaced"),
         ("ar_facts.db", "ar_facts_dropped"), ("deck_figures.db", "pages")]


def has_isin(con, t):
    try:
        return "isin" in [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
    except sqlite3.Error:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    m = {p: v[1] for p, v in json.loads((raw_dir("ar_queue") / "placeholder_isin_map.json").read_text()).items() if v[1]}
    src = {p: v[0] for p, v in json.loads((raw_dir("ar_queue") / "placeholder_isin_map.json").read_text()).items()}
    eq = sqlite3.connect(DATA / "equity_intelligence.db", timeout=300)
    ts = datetime.now().isoformat(timespec="seconds")
    log = []

    # master rows for real ISINs not yet in master
    bse_code = dict(eq.execute("SELECT isin, MAX(sc_code) FROM mkt_bse_eq_daily WHERE isin LIKE 'IN%' GROUP BY isin").fetchall()) if a.apply else {}
    added = 0
    for p, real in m.items():
        if eq.execute("SELECT 1 FROM master_companies WHERE isin=?", (real,)).fetchone():
            continue
        stub = eq.execute("SELECT company_name, industry, sector FROM master_companies WHERE isin=?", (p,)).fetchone()
        sym = p[len("INE_AUTO_"):]
        added += 1
        if a.apply:
            nse = sym if src[p] == "nse" and not eq.execute("SELECT 1 FROM master_companies WHERE nse_symbol=?", (sym,)).fetchone() else None
            bse = (bse_code.get(real),) if bse_code.get(real) else None
            bse = bse[0] if bse and not eq.execute("SELECT 1 FROM master_companies WHERE bse_code=?", (bse[0],)).fetchone() else None
            eq.execute("""INSERT INTO master_companies (isin, nse_symbol, bse_code, company_name, industry, sector, is_active)
                          VALUES (?,?,?,?,?,?,1)""", (real, nse, bse, (stub[0] if stub else sym), stub[1] if stub else None,
                                                      stub[2] if stub else None))
    print(f"master_companies: {'added' if a.apply else 'would add'} {added} real ISINs")

    def present(con, t):   # one scan per table: placeholder ISINs it holds, with row counts
        return dict(con.execute(f"SELECT isin, COUNT(*) FROM \"{t}\" WHERE isin LIKE 'INE_AUTO%' GROUP BY isin").fetchall())

    def plain(con, db, t):   # one UPDATE per table through a temp mapping table (tables are large, isin unindexed)
        have = present(con, t)
        hits = {p: k for p, k in have.items() if p in m}
        n = sum(hits.values())
        if a.apply and hits and db == "ar_facts.db":   # live AR workers write here: short per-ISIN commits (isin indexed)
            for p, k in hits.items():
                con.execute(f'UPDATE "{t}" SET isin=? WHERE isin=?', (m[p], p)); con.commit()
            log.extend((db, t, p[len("INE_AUTO_"):], p, m[p], k, ts) for p, k in hits.items())
        elif a.apply and hits:
            con.execute("CREATE TEMP TABLE IF NOT EXISTS isin_map (p TEXT PRIMARY KEY, r TEXT)")
            con.execute("DELETE FROM isin_map")
            con.executemany("INSERT INTO isin_map VALUES (?,?)", [(p, m[p]) for p in hits])
            con.execute(f'UPDATE "{t}" SET isin=(SELECT r FROM isin_map WHERE p="{t}".isin) '
                        f"WHERE isin LIKE 'INE_AUTO%' AND isin IN (SELECT p FROM isin_map)")
            con.commit()
            log.extend((db, t, p[len("INE_AUTO_"):], p, m[p], k, ts) for p, k in hits.items())
        print(f"{db}:{t}: {'re-keyed' if a.apply else 'would re-key'} {n:,} rows")

    for t in EQ_PLAIN:
        if has_isin(eq, t):
            plain(eq, "equity_intelligence.db", t)
    for db, t in OTHER:
        con = sqlite3.connect(DATA / db, timeout=300)
        if has_isin(con, t):
            plain(con, db, t)
    for t, keycols in EQ_KEYED.items():
        if not has_isin(eq, t):
            continue
        if a.apply:
            eq.execute(f'CREATE TABLE IF NOT EXISTS "{t}_placeholder_archive" AS SELECT *, \'\' AS archived_reason, '
                       f'\'\' AS archived_ts FROM "{t}" WHERE 0')
        moved = clash = 0
        have = present(eq, t)
        for p, real in m.items():
            k = have.get(p, 0)
            if not k:
                continue
            same = " AND ".join(f'r."{c}" IS o."{c}"' for c in keycols) or "1"
            c = eq.execute(f'SELECT COUNT(*) FROM "{t}" o WHERE o.isin=? AND EXISTS (SELECT 1 FROM "{t}" r WHERE r.isin=? AND {same})',
                           (p, real)).fetchone()[0]
            clash += c; moved += k - c
            if a.apply:
                eq.execute(f'INSERT INTO "{t}_placeholder_archive" SELECT o.*, ?, ? FROM "{t}" o WHERE o.isin=? AND EXISTS '
                           f'(SELECT 1 FROM "{t}" r WHERE r.isin=? AND {same})', (f"real ISIN {real} already has this row", ts, p, real))
                same_t = " AND ".join(f'r."{c}" IS "{t}"."{c}"' for c in keycols) or "1"
                eq.execute(f'DELETE FROM "{t}" WHERE "{t}".isin=? AND EXISTS (SELECT 1 FROM "{t}" r WHERE r.isin=? AND {same_t})',
                           (p, real))
                eq.execute(f'UPDATE "{t}" SET isin=? WHERE isin=?', (real, p))
                eq.commit()
                log.append(("equity_intelligence.db", t, p[len("INE_AUTO_"):], p, real, k, ts))
        print(f"equity_intelligence.db:{t}: {'moved' if a.apply else 'would move'} {moved:,} rows; "
              f"{clash:,} rows already held by the real ISIN {'archived' if a.apply else 'would be archived'}")
    if a.apply:
        for p in m:
            eq.execute("UPDATE master_companies SET is_active=0 WHERE isin=?", (p,))
        eq.executemany("INSERT INTO isin_rekey_log VALUES (?,?,?,?,?,?,?)", log)
        eq.commit()
    else:
        print("dry run: nothing changed (use --apply)")


if __name__ == "__main__":
    main()
