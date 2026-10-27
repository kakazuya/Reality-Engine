"""A8 - real ISIN changes confirmed by the independent BSE feed, with join results."""
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

# BSE scrip code -> ISIN windows (BSE bhavcopy always carries the ISIN)
rows = snap.execute("""SELECT sc_code, isin, MIN(date), MAX(date), COUNT(*), string_agg(DISTINCT symbol,',')
                       FROM px_bse GROUP BY 1,2""").fetchall()
by = defaultdict(list)
for r in rows:
    by[r[0]].append(r)
bse_changes = []
for sc, v in by.items():
    v = sorted(v, key=lambda r: r[2])
    if len(v) == 2 and v[0][3] < v[1][2]:
        bse_changes.append({"sc": sc, "old": v[0][1], "new": v[1][1], "d": v[1][2], "d0": v[0][2],
                            "last": v[0][3], "sym": v[0][5], "nsym": v[1][5]})
print("BSE scrips with a sequential 2-window ISIN change:", len(bse_changes))
# NSE agreement
for c in bse_changes:
    c["nse_old"] = snap.execute(
        "SELECT COUNT(*) FROM px_nse WHERE symbol=? AND isin=? AND date<=?",
        (c["sym"], c["old"], c["last"])).fetchone()[0]
    c["nse_new"] = snap.execute(
        "SELECT COUNT(*) FROM px_nse WHERE symbol=? AND isin=? AND date>=?",
        (c["sym"], c["new"], c["d"])).fetchone()[0]

print("\n== classify by action")
def act(sym, d):
    return eq.execute(
        "SELECT action_type, ex_date, subject FROM corporate_actions WHERE symbol=? "
        "AND ex_date BETWEEN date(?, '-25 day') AND date(?, '+5 day') ORDER BY ex_date",
        (sym, d.isoformat(), d.isoformat())).fetchall()

real = []
for c in bse_changes:
    a = act(c["sym"], c["d"]) or act(c["nsym"], c["d"])
    kinds = {r[0] for r in a}
    c["a"] = a
    if kinds & {"SPLIT", "BONUS", "MERGER", "RIGHTS"}:
        real.append(c)
print("with split/bonus/merger within 25d:", len(real))
print("without any action (likely defect):", len(bse_changes) - len(real))
print("2021-10-27 or 2021-10-26:", sum(1 for c in bse_changes if c["d"].isoformat() in ("2021-10-27", "2021-10-26")))

print("\n== 10 real cases, both ISINs confirmed by BSE, with join checks")
for c in real[:10]:
    sym = c["sym"]
    # documents / filings under each ISIN
    docs_old = eq.execute("SELECT COUNT(*) FROM corporate_documents WHERE isin=?", (c["old"],)).fetchone()[0]
    docs_new = eq.execute("SELECT COUNT(*) FROM corporate_documents WHERE isin=?", (c["new"],)).fetchone()[0]
    mc_old = eq.execute("SELECT isin, is_active FROM master_companies WHERE isin=?", (c["old"],)).fetchone()
    mc_new = eq.execute("SELECT isin, is_active FROM master_companies WHERE isin=?", (c["new"],)).fetchone()
    shp_old = eq.execute("SELECT COUNT(*) FROM shp_index WHERE isin=?", (c["old"],)).fetchone()[0]
    shp_new = eq.execute("SELECT COUNT(*) FROM shp_index WHERE isin=?", (c["new"],)).fetchone()[0]
    ent = snap.execute("SELECT entity_id FROM px_daily WHERE isin=? LIMIT 1", (c["new"],)).fetchone()
    print(f"  {sym}->{c['nsym']} {c['old']} -> {c['new']} on {c['d']} (last old {c['last']}) act={[x[0] for x in c['a']]}")
    print(f"     BSE days old={sum(1 for _ in [0])} nse_old={c['nse_old']} nse_new={c['nse_new']} entity={ent and ent[0]}"
          f" | docs old/new={docs_old}/{docs_new} master_old={mc_old} master_new={mc_new} shp old/new={shp_old}/{shp_new}")

print("\n== symbol renames (entity with >1 symbol, single ISIN)")
ren = snap.execute("""
WITH e AS (SELECT entity_id, string_agg(DISTINCT symbol,',') syms, COUNT(DISTINCT symbol) ns,
                  COUNT(DISTINCT isin) ni, MIN(date) d0, MAX(date) d1
           FROM px_daily GROUP BY 1)
SELECT * FROM e WHERE ns > 1 AND ni = 1 ORDER BY ns DESC LIMIT 20
""").fetchall()
for r in ren:
    print("  ", r)
print("renames total (single ISIN, multi symbol):",
      snap.execute("SELECT COUNT(*) FROM (SELECT entity_id FROM px_daily GROUP BY 1 HAVING COUNT(DISTINCT symbol)>1 AND COUNT(DISTINCT isin)=1)").fetchone())

print("\n== multi-window (>2) entities: mergers/demergers?")
m = snap.execute("""SELECT entity_id, COUNT(*) n, string_agg(isin||'@'||d0||'..'||d1, ' | ') FROM (
     SELECT entity_id, isin, MIN(date) d0, MAX(date) d1 FROM px_daily GROUP BY 1,2)
     GROUP BY 1 HAVING COUNT(*)>2 ORDER BY 2 DESC LIMIT 10""").fetchall()
for r in m:
    print("  ", r)
snap.close()
eq.close()
