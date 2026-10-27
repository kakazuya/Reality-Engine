"""A6 - which ISIN is real? Cross-source check with corrected Luhn."""
import os
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = Path(os.environ["REALITY_DATA_ROOT"])
snap = duckdb.connect(str(DATA / "snapshots" / "truth_2026-10-19.duckdb"), read_only=True)
eq = connect_ro(DATA / "equity_intelligence.db", timeout_s=60)


def luhn_isin(isin: str) -> bool:
    """ISIN check digit: letters -> 2-digit numbers, then standard Luhn."""
    if not isin or len(isin) != 12 or not isin[:2].isalpha():
        return False
    digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in isin)
    if not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


KNOWN = ["INE040A01034", "INE066F01012", "INE571A01038", "INE009A01021", "INE002A01018",
         "INE467B01029", "INE009A01021", "INE585B01010", "INE860A01027", "INE030A01027"]
print("== Luhn on known ISINs")
for i in KNOWN:
    print(f"  {i} {luhn_isin(i)}")

print("\n== Luhn across sources")
checks = [
    ("equity_intelligence.master_companies", "SELECT isin FROM master_companies"),
    ("equity_intelligence.security_master", "SELECT isin FROM security_master"),
    ("equity_intelligence.shp_index", "SELECT DISTINCT isin FROM shp_index"),
    ("equity_intelligence.corporate_documents", "SELECT DISTINCT isin FROM corporate_documents WHERE isin IS NOT NULL AND isin<>''"),
    ("equity_intelligence.symbol_isin_history", "SELECT DISTINCT isin FROM symbol_isin_history"),
    ("equity_intelligence.company_industry", "SELECT isin FROM company_industry"),
]
for label, sql in checks:
    vals = [r[0] for r in eq.execute(sql)]
    bad = [v for v in vals if not luhn_isin(v or "")]
    print(f"  {label}: {len(vals)} distinct, bad={len(bad)} ({100*len(bad)/len(vals):.1f}%) e.g. {bad[:3]}")
rx = connect_ro(DATA / "results_xbrl.db", timeout_s=60)
vals = [r[0] for r in rx.execute("SELECT DISTINCT isin FROM filings WHERE isin IS NOT NULL AND isin<>''")]
bad = [v for v in vals if not luhn_isin(v)]
print(f"  results_xbrl.filings: {len(vals)} distinct, bad={len(bad)} ({100*len(bad)/len(vals):.1f}%) e.g. {bad[:3]}")
rx.close()
sv = [r[0] for r in snap.execute("SELECT DISTINCT isin FROM px_daily").fetchall()]
bad = [v for v in sv if not luhn_isin(v)]
print(f"  duckdb.px_daily: {len(sv)} distinct, bad={len(bad)} ({100*len(bad)/len(sv):.1f}%) e.g. {bad[:3]}")

print("\n== per-case: ISIN seen by each source")
cases = [("HAL", "2021-10-27"), ("IPCALAB", "2021-10-27"), ("TRIDENT", "2019-12-16"),
         ("LAURUSLABS", "2020-09-30"), ("DIXON", "2021-03-19"), ("SUPPETRO", "2022-05-24"),
         ("HEXAWARE", "2025-02-19"), ("FOURTHDIM", "2023-07-31"), ("SUNDARMFIN", "2020-11-20"),
         ("MOTHERSUMI", "2021-01-01"), ("SONAMCLOCK", "2023-11-15"), ("EICHERMOT", "2020-08-25")]
for sym, d in cases:
    px = snap.execute("SELECT isin, MIN(date), MAX(date) FROM px_nse WHERE symbol=? GROUP BY 1 ORDER BY 2", (sym,)).fetchall()
    nm = snap.execute("SELECT isin FROM nse_master WHERE symbol=?", (sym,)).fetchall()
    sm = eq.execute("SELECT isin, nse_symbol, bse_code, bse_status FROM security_master WHERE nse_symbol=?", (sym,)).fetchall()
    mc = eq.execute("SELECT isin, is_active FROM master_companies WHERE nse_symbol=?", (sym,)).fetchall()
    sh = eq.execute("SELECT DISTINCT isin FROM shp_index WHERE symbol=?", (sym,)).fetchall()
    cd = eq.execute("SELECT isin, COUNT(*) FROM corporate_documents WHERE symbol=? GROUP BY 1 ORDER BY 2 DESC", (sym,)).fetchall()
    rxr = rx if False else None
    rf = connect_ro(DATA / "results_xbrl.db", timeout_s=30).execute(
        "SELECT isin, COUNT(*) FROM filings WHERE symbol=? GROUP BY 1", (sym,)).fetchall()
    print(f"\n {sym} ({d})")
    print(f"   px_nse   {px}")
    print(f"   nse_master {nm}  security_master {sm}")
    print(f"   master   {mc}  shp {sh}")
    print(f"   docs     {cd[:4]}")
    print(f"   xbrl     {rf[:4]}")
snap.close()
eq.close()


