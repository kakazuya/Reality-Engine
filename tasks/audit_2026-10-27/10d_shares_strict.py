"""A10d - shares: strict AR exact-count matcher, 20 companies, and rounding error."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = Path(os.environ["REALITY_DATA_ROOT"])
eq = connect_ro(DATA / "equity_intelligence.db", timeout_s=60)
rx = connect_ro(DATA / "results_xbrl.db", timeout_s=60)
ar = connect_ro(DATA / "ar_facts.db", timeout_s=180)

STRICT = ("total number of shares", "number of equity shares", "total number of equity shares",
          "total number of shares outstanding", "number of shares outstanding")
BAD = ("weighted", "basic", "diluted", "eps", "held", "shareholder", "promoter", "allotted", "forfeit")

picks = eq.execute("""
SELECT isin, nse_symbol, market_cap_tier FROM master_companies
WHERE is_active=1 AND is_screenable=1 AND nse_symbol IS NOT NULL AND nse_symbol<>''
ORDER BY (isin % 97), isin LIMIT 20
""").fetchall()
print(f"{'symbol':13s}{'tier':6s}{'xbrl_period':11s}{'face':>6s}{'derived':>14s}{'ar_total':>14s}{'ar_fy':>10s}{'err%':>9s}{'split_between':>14s}")
res = []
for isin, sym, tier in picks:
    files = rx.execute("""SELECT file, period_end, consolidated FROM filings
                          WHERE isin=? AND period_end IS NOT NULL ORDER BY period_end DESC LIMIT 8""", (isin,)).fetchall()
    best = None
    for f in files:
        vals = dict(rx.execute("SELECT concept, value FROM facts WHERE file=? AND concept IN "
                               "('PaidUpValueOfEquityShareCapital','FaceValueOfEquityShareCapital')", (f[0],)).fetchall())
        paid, face = vals.get("PaidUpValueOfEquityShareCapital"), vals.get("FaceValueOfEquityShareCapital")
        if paid and face:
            best = (f[1], paid, face, int(round(paid / face)), f[2])
            break
    if not best:
        print(f"{sym:13s}{str(tier):6s} no paid-up/face pair")
        continue
    period, paid, face, derived, basis = best
    rows = []
    for v, fy, item in ar.execute("""SELECT value, fiscal_year, item FROM ar_facts
                                     WHERE isin=? AND unit='number' AND value>10000
                                       AND item LIKE '%share%' ORDER BY fiscal_year DESC LIMIT 120""", (isin,)):
        low = str(item or "").lower()
        if low in STRICT or (low.startswith("total") and "share" in low and "held" not in low):
            if not any(b in low for b in BAD):
                rows.append((int(v), fy, low))
    exact = rows[0] if rows else None
    split = eq.execute("""SELECT COUNT(*) FROM corporate_actions ca
                          WHERE ca.isin=? AND ca.action_type IN ('SPLIT','BONUS') AND ca.ex_date > ? """,
                       (isin, str(exact[1])[-4:] + "-03-31" if exact else "")).fetchone()[0] if exact else 0
    if exact:
        e = 100 * (derived - exact[0]) / exact[0]
        res.append((sym, abs(e), e, derived, exact[0], exact[1], split))
        print(f"{sym:13s}{str(tier):6s}{str(period):11s}{face:6.2f}{derived:14,d}{exact[0]:14,d}{str(exact[1]):>10s}{e:9.3f}{split:14d}")
    else:
        print(f"{sym:13s}{str(tier):6s}{str(period):11s}{face:6.2f}{derived:14,d}{'no strict AR row':>14s}")

ok = [r for r in res if r[1] <= 0.5]
print(f"\ncompared {len(res)}; within 0.5%: {len(ok)}; mean|err| {sum(r[1] for r in res)/len(res):.3f}%")
print("outside 0.5% and no split/bonus between AR and XBRL:",
      [(r[0], round(r[2], 2), r[3], r[4]) for r in res if r[1] > 0.5 and r[6] == 0])
print("outside 0.5% WITH a split/bonus between:", [(r[0], round(r[2], 2)) for r in res if r[1] > 0.5 and r[6] > 0])
ar.close()
rx.close()
eq.close()

