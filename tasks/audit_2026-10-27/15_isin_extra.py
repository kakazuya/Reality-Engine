"""A15 - join results for the rename/demerger ISIN cases (fills report section 3.3 rows 9-10)."""
import os
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = Path(os.environ["REALITY_DATA_ROOT"])
eq = connect_ro(DATA / "equity_intelligence.db", timeout_s=60)
rx = connect_ro(DATA / "results_xbrl.db", timeout_s=60)
snap = duckdb.connect(str(DATA / "snapshots" / "truth_2026-10-19.duckdb"), read_only=True)

CASES = [
    ("3IINFOTECH", "INE748C01020", "INE748C01038"),
    ("SUPPETRO", "INE663A01017", "INE663A01033"),
    ("HEXAWARE", "INE093A01033", "INE093A01041"),
    ("FOURTHDIM", "INE382T01014", "INE382T01030"),
    ("SONAMCLOCK", "INE00LM01011", "INE00LM01029"),
    ("PHILIPCARB", "INE602A01023", "INE602A01031"),
    ("KRATOSENER", "INE567L01017", "INE567L01025"),
    ("LTI", "INE214T01019", None),
]
print("symbol      old_isin -> new_isin   docs_old docs_new  shp_old shp_new  master_old/active new/active  xbrl_old xbrl_new  entity")
for sym, old, new in CASES:
    d_old = eq.execute("SELECT COUNT(*) FROM corporate_documents WHERE isin=?", (old,)).fetchone()[0]
    d_new = eq.execute("SELECT COUNT(*) FROM corporate_documents WHERE isin=?", (new,)).fetchone()[0] if new else -1
    s_old = eq.execute("SELECT COUNT(*) FROM shp_index WHERE isin=?", (old,)).fetchone()[0]
    s_new = eq.execute("SELECT COUNT(*) FROM shp_index WHERE isin=?", (new,)).fetchone()[0] if new else -1
    m_old = eq.execute("SELECT is_active FROM master_companies WHERE isin=?", (old,)).fetchone()
    m_new = eq.execute("SELECT is_active FROM master_companies WHERE isin=?", (new,)).fetchone() if new else None
    x_old = rx.execute("SELECT COUNT(*) FROM filings WHERE isin=?", (old,)).fetchone()[0]
    x_new = rx.execute("SELECT COUNT(*) FROM filings WHERE isin=?", (new,)).fetchone()[0] if new else -1
    ent = snap.execute("SELECT entity_id FROM px_daily WHERE isin=? LIMIT 1", (new or old,)).fetchone()
    syms = snap.execute("""SELECT string_agg(DISTINCT symbol, ',') FROM px_daily
                           WHERE entity_id=(SELECT entity_id FROM px_daily WHERE isin=? LIMIT 1)""",
                        (new or old,)).fetchone()[0] if ent else None
    print(f"{sym:12s} {old} -> {str(new):12s} {d_old:8d} {d_new:8d} {s_old:8d} {s_new:8d}  {str(m_old):>12s} {str(m_new):>12s} {x_old:9d} {x_new:8d}  {ent and ent[0]} {syms}")

print("\n== symbol windows for the rename cases")
for ent in ("INE214T", "INE748C"):
    rows = snap.execute("""SELECT symbol, isin, MIN(date), MAX(date) FROM px_daily WHERE entity_id=? GROUP BY 1,2 ORDER BY 3""", (ent,)).fetchall()
    print(f"  {ent}: {rows[:8]}")
rx.close()
eq.close()
snap.close()
