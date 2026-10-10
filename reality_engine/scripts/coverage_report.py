"""
Coverage report: for every company that traded on BSE or NSE in a year (2019 onwards), which datasets we hold.

Why: work was loaded tier by tier (Nifty200 first) and later tiers were never finished, but logs said "complete".
This report compares each dataset with the full traded universe, per year, so a gap is visible before any test.

Universe: an ISIN (INE..., equity) with at least one trading day that calendar year in mkt_bse_eq_daily,
mkt_nse_eq_daily, daily_price_delivery, mkt_nse_full_daily or mkt_nse_sme_daily (NSE symbol-only tables mapped to
ISIN through master_companies.nse_symbol or the ISINs seen in the ISIN-bearing NSE tables).

Datasets per (isin, year), year = the real filing/trading year:
  price_days        trading days with a price row on either exchange
  ar_indexed / ar_downloaded                annual reports by filing year (v_document_pit)
  concall_indexed / concall_downloaded      concall transcripts by filing year
  ppt_indexed                               investor presentations: corporate_documents + historical decks (deck_sources)
  quarterly_rows                            rows in quarterly_financials by quarter-end year

Writes reality_engine/data/reports/coverage_<date>.csv (one row per isin-year) and prints the summary:
companies traded that year, and how many of them have each dataset. Read-only on the databases.

    python -m reality_engine.scripts.coverage_report
"""
import csv
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
LIVE = DATA / "equity_intelligence.db"
DECKS = DATA / "deck_figures.db"
OUT = DATA / "reports"
FIRST_YEAR = 2019
FIELDS = ["price_days", "ar_indexed", "ar_downloaded", "concall_indexed", "concall_downloaded", "ppt_indexed", "quarterly_rows"]


def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=120)


def main():
    db = ro(LIVE)
    sym2isin = {s: i for s, i in db.execute("SELECT nse_symbol, isin FROM master_companies WHERE nse_symbol IS NOT NULL AND isin LIKE 'INE%'")}
    days = defaultdict(set)   # (isin, year) -> set of dates

    def add(rows):
        for isin, d in rows:
            if isin and isin.startswith("INE") and d and d[:4].isdigit() and int(d[:4]) >= FIRST_YEAR:
                days[(isin, int(d[:4]))].add(d[:10])

    print("reading prices ...", flush=True)
    # older BSE bhavcopy formats carry no ISIN: map scrip code -> ISIN from rows that have one, then master_companies
    code2isin = {str(c): i for c, i in db.execute("SELECT sc_code, MAX(isin) FROM mkt_bse_eq_daily WHERE isin LIKE 'INE%' GROUP BY sc_code")}
    for c, i in db.execute("SELECT bse_code, isin FROM master_companies WHERE bse_code IS NOT NULL AND isin LIKE 'INE%'"):
        code2isin.setdefault(str(c), i)
    add((i if i and i.startswith("INE") else code2isin.get(str(c)), d)
        for c, i, d in db.execute(f"SELECT sc_code, isin, date FROM mkt_bse_eq_daily WHERE date >= '{FIRST_YEAR}'"))
    for t in ("mkt_nse_eq_daily", "daily_price_delivery"):
        rows = db.execute(f"SELECT symbol, isin, date FROM {t} WHERE date >= '{FIRST_YEAR}'").fetchall()
        for s, i, _ in rows:
            if s and i:
                sym2isin.setdefault(s, i)
        add((i, d) for _, i, d in rows)
    for t in ("mkt_nse_full_daily", "mkt_nse_sme_daily"):
        add((sym2isin.get(s), d) for s, d in db.execute(f"SELECT symbol, date FROM {t} WHERE date >= '{FIRST_YEAR}'"))

    cov = defaultdict(lambda: dict.fromkeys(FIELDS, 0))
    for k, v in days.items():
        cov[k]["price_days"] = len(v)

    print("reading documents ...", flush=True)
    q = """SELECT d.isin, substr(v.pit_date,1,4), d.doc_type, d.local_file_path IS NOT NULL
           FROM corporate_documents d JOIN v_document_pit v ON v.id = d.id
           WHERE d.doc_type IN ('ANNUAL_REPORT','CONCALL_TRANSCRIPT','INVESTOR_PRESENTATION') AND v.pit_date >= ?"""
    for isin, y, dt, got in db.execute(q, (str(FIRST_YEAR),)):
        if not isin or not y:
            continue
        key = {"ANNUAL_REPORT": "ar", "CONCALL_TRANSCRIPT": "concall", "INVESTOR_PRESENTATION": "ppt"}[dt]
        c = cov[(isin, int(y))]
        if key == "ppt":
            c["ppt_indexed"] += 1
        else:
            c[f"{key}_indexed"] += 1
            c[f"{key}_downloaded"] += int(got)
    if DECKS.exists():
        dk = ro(DECKS)
        if dk.execute("SELECT 1 FROM sqlite_master WHERE name='deck_sources'").fetchone():
            for isin, y in dk.execute("SELECT isin, substr(known_at,1,4) FROM deck_sources WHERE status='ok' AND known_at >= ?", (str(FIRST_YEAR),)):
                if isin and y:
                    cov[(isin, int(y))]["ppt_indexed"] += 1
    for isin, y, n in db.execute("SELECT isin, substr(quarter_end_date,1,4), COUNT(*) FROM quarterly_financials GROUP BY 1, 2"):
        if isin and y and int(y) >= FIRST_YEAR:
            cov[(isin, int(y))]["quarterly_rows"] += n

    OUT.mkdir(exist_ok=True)
    path = OUT / f"coverage_{date.today().isoformat()}.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["isin", "year", "traded"] + FIELDS)
        for (isin, y), c in sorted(cov.items()):
            w.writerow([isin, y, int(c["price_days"] > 0)] + [c[k] for k in FIELDS])

    # summary over companies that traded in the year
    print(f"\nwrote {path}\n")
    print("year  traded  " + "  ".join(f"{k:>18}" for k in FIELDS[1:]))
    for y in sorted({y for _, y in cov}):
        traded = [c for (i, yy), c in cov.items() if yy == y and c["price_days"] > 0]
        if not traded:
            continue
        cells = [f"{sum(1 for c in traded if c[k] > 0):>7} ({100 * sum(1 for c in traded if c[k] > 0) / len(traded):3.0f}%)" for k in FIELDS[1:]]
        print(f"{y}  {len(traded):>6}  " + "  ".join(f"{x:>18}" for x in cells))
    print("\nA company counts as covered for a dataset in a year when it has at least one row of it filed that year.")
    print("Annual reports and concalls are once-a-year / quarterly, so 100% is not expected for the current partial year.")


if __name__ == "__main__":
    main()
