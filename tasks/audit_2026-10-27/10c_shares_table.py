"""A10c - shares outstanding: coverage + 20-company XBRL-derived vs AR-exact comparison."""
import os
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = Path(os.environ["REALITY_DATA_ROOT"])
con = duckdb.connect(str(DATA / "snapshots" / "truth_2026-10-19.duckdb"), read_only=True)
print("== FY25+ files with both concepts, joined to filings")
print(con.execute("""
WITH f AS (SELECT file FROM results_facts
           WHERE concept IN ('PaidUpValueOfEquityShareCapital','FaceValueOfEquityShareCapital')
           GROUP BY 1 HAVING COUNT(DISTINCT concept)=2)
SELECT COUNT(*) filings, COUNT(DISTINCT rf.isin) isins,
       SUM(CASE WHEN rf.period_end >= '2024-03-31' THEN 1 ELSE 0 END) fy25
FROM results_filings rf JOIN f USING(file)
""").fetchall())
print("== paid-up sample (units?)")
print(con.execute("SELECT file, value, unit FROM results_facts WHERE concept='PaidUpValueOfEquityShareCapital' AND value IS NOT NULL LIMIT 5").fetchall())
print("== face values distribution")
print(con.execute("SELECT value, COUNT(*) c FROM results_facts WHERE concept='FaceValueOfEquityShareCapital' GROUP BY 1 ORDER BY 2 DESC LIMIT 10").fetchall())
print("== paid-up values ending in 000 (thousand-rounding) share")
print(con.execute("SELECT SUM(CASE WHEN value % 1000=0 THEN 1 ELSE 0 END), COUNT(*) FROM results_facts WHERE concept='PaidUpValueOfEquityShareCapital' AND value IS NOT NULL").fetchall())
con.close()

eq = connect_ro(DATA / "equity_intelligence.db", timeout_s=60)
rx = connect_ro(DATA / "results_xbrl.db", timeout_s=60)
ar = connect_ro(DATA / "ar_facts.db", timeout_s=180)

print("\n== ar_facts: what share-count items exist")
print(ar.execute("""SELECT item, COUNT(*) c FROM ar_facts
                    WHERE unit='number' AND item LIKE '%number%share%' GROUP BY 1 ORDER BY 2 DESC LIMIT 12""").fetchall())

picks = eq.execute("""
SELECT isin, nse_symbol, bse_code, company_name, market_cap_tier
FROM master_companies
WHERE is_active=1 AND is_screenable=1 AND nse_symbol IS NOT NULL AND nse_symbol<>''
ORDER BY (isin % 97), isin LIMIT 20
""").fetchall()
print("\n== 20-company check")
hdr = f"{'symbol':13s}{'tier':6s}{'period':11s}{'paid_cr':>9s}{'face':>6s}{'derived':>13s}{'ar_exact':>13s}{'err%':>8s}{'ar_fy':>7s}{'xbrl_basis':>10s}"
print(hdr)
errs, no_ar = [], 0
for isin, sym, bse, name, tier in picks:
    files = rx.execute("""SELECT file, period_end, consolidated, dissem_ts FROM filings
                          WHERE isin=? AND period_end IS NOT NULL ORDER BY period_end DESC LIMIT 8""", (isin,)).fetchall()
    best = None
    for f in files:
        vals = dict(rx.execute("SELECT concept, value FROM facts WHERE file=? AND concept IN "
                               "('PaidUpValueOfEquityShareCapital','FaceValueOfEquityShareCapital')", (f[0],)).fetchall())
        paid, face = vals.get("PaidUpValueOfEquityShareCapital"), vals.get("FaceValueOfEquityShareCapital")
        if paid and face:
            best = (f[1], paid, face, int(round(paid / face)), f[2], f[3])
            break
    exact = ar.execute("""SELECT value, fiscal_year FROM ar_facts
                          WHERE isin=? AND unit='number' AND item LIKE '%total%' AND item LIKE '%share%'
                            AND value > 100000 ORDER BY fiscal_year DESC LIMIT 5""", (isin,)).fetchall()
    if not best:
        print(f"{sym:13s} {str(tier):6s} no paid-up/face pair in the last 8 filings")
        continue
    period, paid, face, derived, basis, dissem = best
    if exact:
        v = int(exact[0][0])
        e = 100 * (derived - v) / v
        errs.append((sym, abs(e), e, v, derived, exact[0][1]))
        print(f"{sym:13s}{str(tier):6s}{str(period):11s}{paid/1e7:9.2f}{face:6.2f}{derived:13,d}{v:13,d}{e:8.3f}{str(exact[0][1]):>7s}{str(basis):>10s}")
    else:
        no_ar += 1
        print(f"{sym:13s}{str(tier):6s}{str(period):11s}{paid/1e7:9.2f}{face:6.2f}{derived:13,d}{'NO AR FACT':>13s}{'':8s}{'':7s}{str(basis):>10s}")

print(f"\ncompared {len(errs)}, no-AR {no_ar}, mean|err| {sum(e[1] for e in errs)/len(errs):.4f}%, "
      f"max|err| {max(e[1] for e in errs):.3f}%, within 0.5%: {sum(1 for e in errs if e[1] <= 0.5)}/{len(errs)}")
for e in errs:
    if e[1] > 0.5:
        print("   outside 0.5%:", e)
ar.close()
rx.close()
eq.close()
