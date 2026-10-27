"""A13 - non-equity rows, announcement volume, events PIT, and 5 equity spot checks."""
import os
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = Path(os.environ["REALITY_DATA_ROOT"])
eq = connect_ro(DATA / "equity_intelligence.db", timeout_s=90)
boa = connect_ro(DATA / "bse_announcements.db", timeout_s=60)
rx = connect_ro(DATA / "results_xbrl.db", timeout_s=60)
snap = duckdb.connect(str(DATA / "snapshots" / "truth_2026-10-19.duckdb"), read_only=True)

print("== non-equity / synthetic rows in master_companies")
print(eq.execute("""SELECT CASE WHEN isin LIKE 'INE_AUTO_%' THEN 'synthetic INE_AUTO'
                                WHEN substr(isin,1,3) <> 'INE' THEN 'non-INE prefix'
                                ELSE 'INE equity' END k, COUNT(*), SUM(is_active), SUM(is_screenable)
                     FROM master_companies GROUP BY 1""").fetchall())
print("non-INE samples:", eq.execute("SELECT isin, nse_symbol, company_name FROM master_companies WHERE substr(isin,1,3)<>'INE' AND isin NOT LIKE 'INE_AUTO_%' LIMIT 10").fetchall())
print("symbols ending PP (partly paid):", eq.execute("SELECT COUNT(*) FROM master_companies WHERE nse_symbol LIKE '%PP'").fetchone())
print("screenable and INE equity:", eq.execute("SELECT COUNT(*) FROM master_companies WHERE is_screenable=1 AND substr(isin,1,3)='INE' AND isin NOT LIKE 'INE_AUTO_%'").fetchone())

print("\n== BSE announcements FY25+ and material category volume")
print(boa.execute("SELECT COUNT(*), MIN(DissemDT), MAX(DissemDT) FROM ann WHERE DissemDT >= '2024-04-01'").fetchone())
for r in boa.execute("""SELECT SUBCATNAME, COUNT(*) c FROM ann WHERE DissemDT >= '2024-04-01'
                        GROUP BY 1 ORDER BY 2 DESC LIMIT 20"""):
    print("  ", r)
boa.close()

print("\n== duckdb.events (PIT backbone) FY25+")
print(snap.execute("""SELECT kind, COUNT(*), COUNT(DISTINCT isin) FROM events
                      WHERE known_at_utc >= TIMESTAMP '2024-04-01' GROUP BY 1 ORDER BY 2 DESC""").fetchall())

print("\n== 5 equity spot checks (concall date + XBRL revenue + price)")
ents = eq.execute("""SELECT mc.isin, mc.nse_symbol FROM master_companies mc
                     WHERE mc.is_active=1 AND mc.is_screenable=1 AND substr(mc.isin,1,3)='INE'
                       AND mc.isin NOT LIKE 'INE_AUTO_%'
                     ORDER BY (mc.isin % 71), mc.isin LIMIT 5""").fetchall()
for isin, sym in ents:
    doc = eq.execute("""SELECT id, bse_newsid, bse_dissem_ts, publication_date, call_date, doc_date
                        FROM corporate_documents WHERE isin=? AND doc_type='CONCALL_TRANSCRIPT'
                        ORDER BY bse_dissem_ts DESC LIMIT 1""", (isin,)).fetchone()
    rd = eq.execute("""SELECT published_date, event_date FROM raw_documents
                       WHERE isin=? AND source_type='CONCALL_TRANSCRIPT' ORDER BY published_date DESC LIMIT 1""", (isin,)).fetchone()
    print(f"\n  {sym} {isin}")
    if doc:
        ann = eq.execute("SELECT DissemDT FROM bse_announcements.ann WHERE NEWSID=?", (doc[1],)).fetchone() if False else None
        print(f"    concall doc: dissem={doc[2]} pub={doc[3]} call={doc[4]} crawl={doc[5]}")
    print(f"    raw_documents: published={rd[0] if rd else None} event={rd[1] if rd else None}")
    fin = rx.execute("""SELECT f.period_end, f.dissem_ts, f.consolidated,
                        (SELECT value FROM facts x WHERE x.file=f.file AND x.concept='RevenueFromOperations'
                         AND x.period_end=f.period_end LIMIT 1) rev
                        FROM filings f WHERE f.isin=? ORDER BY f.period_end DESC LIMIT 1""", (isin,)).fetchone()
    qf = eq.execute("SELECT quarter_end_date, revenue_inr_cr FROM quarterly_financials WHERE isin=? ORDER BY quarter_end_date DESC LIMIT 1", (isin,)).fetchone()
    print(f"    XBRL latest: {fin}")
    print(f"    quarterly_financials latest: {qf}")
    px = snap.execute("SELECT date, close, adj_close FROM px_daily WHERE isin=? ORDER BY date DESC LIMIT 1", (isin,)).fetchone()
    print(f"    snapshot px_daily latest: {px}")
rx.close()

print("\n== crawl-date drift: corporate_documents.doc_date vs bse_dissem_ts (FY25+ sample)")
print(eq.execute("""SELECT COUNT(*),
  SUM(julianday(bse_dissem_ts) - julianday(doc_date) > 30) over_30d,
  SUM(julianday(bse_dissem_ts) - julianday(doc_date) BETWEEN 1 AND 30) between_1_30,
  SUM(abs(julianday(bse_dissem_ts) - julianday(doc_date)) <= 1) same_day
FROM corporate_documents WHERE bse_dissem_ts >= '2024-04-01' AND doc_date IS NOT NULL""").fetchall())

print("\n== concall date fill for FY25+ docs")
print(eq.execute("""SELECT COUNT(*), SUM(bse_dissem_ts >= '2024-04-01'), SUM(call_date IS NOT NULL AND call_date<>''),
                           SUM(publication_date IS NOT NULL AND publication_date<>'')
                    FROM corporate_documents WHERE doc_type='CONCALL_TRANSCRIPT'""").fetchall())
eq.close()
snap.close()
