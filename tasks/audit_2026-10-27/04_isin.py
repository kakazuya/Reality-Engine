"""A4 - ISIN-history map: what exists (entity), and 10 real change cases with joins."""
import os
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = Path(os.environ["REALITY_DATA_ROOT"])
con = duckdb.connect(str(DATA / "snapshots" / "truth_2026-10-19.duckdb"), read_only=True)

for t in ("entity", "bse_code_isin", "nse_symbol_isin"):
    cols = [c[0] for c in con.execute(f"DESCRIBE {t}").fetchall()]
    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"-- {t} [{n}] :: {cols}")
    print("   sample:", con.execute(f"SELECT * FROM {t} LIMIT 3").fetchall())

print("\n== px_daily entity->isin windows")
rows = con.execute("""
    SELECT entity_id, isin, MIN(date) d0, MAX(date) d1, COUNT(*) n, COUNT(DISTINCT symbol) nsym,
           string_agg(DISTINCT symbol, ',' ORDER BY symbol) syms
    FROM px_daily GROUP BY 1,2
""").fetchall()
from collections import defaultdict
ent = defaultdict(list)
for r in rows:
    ent[r[0]].append(r)
multi = {k: v for k, v in ent.items() if len(v) > 1}
print(f"entities={len(ent)} multi-isin={len(multi)}")
# how many change inside the window (sequential, not parallel exchanges)
seq = 0
for k, v in multi.items():
    v = sorted(v, key=lambda r: r[2])
    if all(v[i][3] < v[i + 1][2] for i in range(len(v) - 1)):
        seq += 1
print("sequential (d1 < next d0):", seq)

print("\n== 25 sequential examples with dates")
cases = []
for k, v in multi.items():
    v = sorted(v, key=lambda r: r[2])
    if len(v) == 2 and v[0][3] < v[1][2]:
        cases.append((k, v))
print("2-window sequential cases:", len(cases))
for k, v in cases[:25]:
    print(f"  entity={k} syms={v[0][6]}|{v[1][6]}  old={v[0][1]} {v[0][2]}..{v[0][3]} ({v[0][4]}) "
          f"new={v[1][1]} {v[1][2]}..{v[1][3]} ({v[1][4]})")

con.close()

print("\n== master_companies: do old ISINs exist there?")
eq = connect_ro(DATA / "equity_intelligence.db", timeout_s=60)
old_isins = [v[0][1] for k, v in cases]
new_isins = [v[1][1] for k, v in cases]
for label, lst in (("old", old_isins), ("new", new_isins)):
    marks = ",".join("?" * len(lst))
    got = eq.execute(
        f"SELECT COUNT(*), SUM(is_active), SUM(sector IS NOT NULL AND sector<>'') FROM master_companies "
        f"WHERE isin IN ({marks})", lst).fetchone()
    print(f"{label}: in master {got[0]}/{len(lst)} active={got[1]} has_sector={got[2]}")
# for each case: is old ISIN present as its own master row?
pairs = []
for k, v in cases[:12]:
    for label, isin in (("old", v[0][1]), ("new", v[1][1])):
        row = eq.execute("SELECT isin, nse_symbol, bse_code, company_name, is_active, sector FROM master_companies WHERE isin=?",
                         (isin,)).fetchone()
        pairs.append((v[0][6], label, isin, row))
for p in pairs:
    print("  ", p)
eq.close()
