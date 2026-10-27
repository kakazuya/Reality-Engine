"""A9 - final 12 ISIN-change examples (splits + restructure/rename) with join results."""
import os
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = Path(os.environ["REALITY_DATA_ROOT"])
snap = duckdb.connect(str(DATA / "snapshots" / "truth_2026-10-19.duckdb"), read_only=True)
eq = connect_ro(DATA / "equity_intelligence.db", timeout_s=60)

print("== corp_action kinds in snapshot, by count and sample text")
for k in ("restructure", "consolidation", "bonus", "split"):
    rows = snap.execute("SELECT COUNT(*), MIN(ex_date), MAX(ex_date) FROM corp_action WHERE kind=?", (k,)).fetchone()
    print(f"  {k}: {rows}")
print(snap.execute("SELECT ex_date, kind, text FROM corp_action WHERE kind='restructure' ORDER BY ex_date DESC LIMIT 8").fetchall())

# NSE ISIN windows per symbol (from px_nse, native ISIN only where the source carried it)
print("\n== merger / restructure driven ISIN changes (NSE windows, action within 30d)")
cand = snap.execute("""
WITH w AS (SELECT symbol, isin, MIN(date) d0, MAX(date) d1 FROM px_nse GROUP BY 1,2),
     s AS (SELECT symbol, isin old_isin, LEAD(isin) OVER w nxt, LEAD(d0) OVER w nxt0, d1
           FROM w WINDOW w AS (PARTITION BY symbol ORDER BY d0))
SELECT symbol, old_isin, nxt, nxt0, d1 FROM s
WHERE nxt IS NOT NULL AND nxt0 > d1 AND d1 >= DATE '2019-01-01'
""").fetchall()
print("NSE symbols with a clean sequential ISIN change:", len(cand))
merges = []
for sym, old, new, sw, last in cand:
    a = snap.execute("SELECT kind, ex_date, text FROM corp_action WHERE ex_date BETWEEN ? - INTERVAL 40 DAY AND ? + INTERVAL 5 DAY "
                     "AND kind IN ('restructure','consolidation') AND text LIKE '%'||?||'%' LIMIT 3",
                     (sw, sw, sym)).fetchall()
    if a:
        merges.append((sym, old, new, sw, a))
print("with restructure/consolidation text match:", len(merges))
for m in merges[:10]:
    print("  ", m)

print("\n== FINAL table: 12 cases")
CASES = [
    ("HDFCBANK", "split 2->1", "2019-09-20"),
    ("TRIDENT", "split 10->1", "2019-12-16"),
    ("LAURUSLABS", "split 10->2", "2020-09-30"),
    ("EICHERMOT", "split 10->1", "2020-08-25"),
    ("DIXON", "split 10->2", "2021-03-19"),
    ("APLAPOLLO", "split 10->2", "2020-12-16"),
    ("ALKYLAMINE", "split 5->2", "2021-05-12"),
    ("FINPIPE", "split 10->2", "2021-04-19"),
]
for sym, kind, d in CASES:
    w = snap.execute("SELECT isin, MIN(date), MAX(date) FROM px_nse WHERE symbol=? GROUP BY 1 ORDER BY 2", (sym,)).fetchall()
    old = [r[0] for r in w if r[2].isoformat() < d][-1] if [r for r in w if r[2].isoformat() < d] else None
    new = [r[0] for r in w if r[1].isoformat() >= d][0] if [r for r in w if r[1].isoformat() >= d] else None
    act = eq.execute("SELECT action_type, ex_date, subject FROM corporate_actions WHERE symbol=? AND ex_date BETWEEN date(?,'-3 day') AND date(?, '+1 day')",
                     (sym, d, d)).fetchall()
    sd = eq.execute("SELECT bse_code FROM master_companies WHERE isin=?", (new,)).fetchone()
    docs_old = eq.execute("SELECT COUNT(*) FROM corporate_documents WHERE isin=?", (old,)).fetchone()[0] if old else -1
    docs_new = eq.execute("SELECT COUNT(*) FROM corporate_documents WHERE isin=?", (new,)).fetchone()[0] if new else -1
    shp_old = eq.execute("SELECT COUNT(*) FROM shp_index WHERE isin=?", (old,)).fetchone()[0] if old else -1
    shp_new = eq.execute("SELECT COUNT(*) FROM shp_index WHERE isin=?", (new,)).fetchone()[0] if new else -1
    mc_old = eq.execute("SELECT is_active FROM master_companies WHERE isin=?", (old,)).fetchone() if old else None
    ent = snap.execute("SELECT entity_id FROM px_daily WHERE isin=? LIMIT 1", (new,)).fetchone() if new else None
    pre = snap.execute("SELECT COUNT(*) FROM px_daily WHERE entity_id=(SELECT entity_id FROM px_daily WHERE isin=? LIMIT 1) AND date < ?",
                       (new, d)).fetchone()[0] if new else -1
    print(f"  {sym:12s} {kind:12s} {d} old={old} new={new} bse_code={sd and sd[0]} ent={ent and ent[0]}")
    print(f"      action={act[:2]} docs old/new={docs_old}/{docs_new} shp old/new={shp_old}/{shp_new} master_old_active={mc_old} px_days_before_switch={pre}")

print("\n== rename / demerger cases (entity has >1 symbol)")
for ent in ("INE214T", "INE220B", "INE126M", "INE03CM", "INE639K", "INE724A"):
    rows = snap.execute("""SELECT symbol, isin, MIN(date), MAX(date) FROM px_daily WHERE entity_id=? GROUP BY 1,2 ORDER BY 3""", (ent,)).fetchall()
    print(f"  {ent}: {rows}")
snap.close()
eq.close()
