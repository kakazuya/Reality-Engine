"""A1 - inventory: every table/column the audit will need, per DB. Read-only."""
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = Path(os.environ.get("REALITY_DATA_ROOT") or Path(__file__).resolve().parents[2] / "reality_engine" / "data")

WANT = {
    "equity_intelligence.db": [
        "master_companies", "company_industry", "index_membership", "symbol_isin_history",
        "security_master", "shareholding", "shp_index", "price_bands", "corporate_documents",
        "raw_documents", "document_chunks", "annual_financials", "quarterly_financials",
        "daily_price_delivery", "mkt_nse_full_daily", "mkt_bse_eq_daily", "corporate_actions",
        "market_cap", "company_state_daily", "nse_master", "sector_master", "industry_master",
        "telegram_posts", "policy_events", "events",
    ],
    "results_xbrl.db": ["filings", "facts", "filings_pivoted"],
    "bse_announcements.db": ["ann", "fetch_ledger"],
    "chunks_v2.db": None,
    "results_notes.db": None,
}


def tables(con):
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}


for db, want in WANT.items():
    p = DATA / db
    print(f"\n=== {db} exists={p.exists()} size={p.stat().st_size // 1_000_000 if p.exists() else 0}MB")
    if not p.exists():
        continue
    con = connect_ro(p, timeout_s=30)
    have = tables(con)
    print(f"tables/views: {len(have)}")
    names = want if want else sorted(have)
    for t in names:
        if t not in have:
            print(f"  MISSING table: {t}")
            continue
        cols = [r[1] for r in con.execute(f"PRAGMA table_info('{t}')")]
        try:
            n = con.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            n = f"?{exc}"
        print(f"  {t} [{n}] :: {', '.join(cols)}")
    if want is None:
        print("  all:", sorted(have))
    con.close()

# extra: tables matching keywords anywhere
print("\n=== keyword scan in equity_intelligence.db")
con = connect_ro(DATA / "equity_intelligence.db", timeout_s=30)
have = tables(con)
for kw in ("state", "mcap", "market_cap", "index", "isin", "fno", "f_and_o", "band", "sector", "industry", "action"):
    hits = sorted(t for t in have if kw in t.lower())
    print(f"  {kw}: {hits}")
con.close()
