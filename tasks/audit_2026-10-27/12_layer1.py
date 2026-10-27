"""A12 - layer-1 tag coverage, PIT sources, and 5-entity spot checks."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = Path(os.environ["REALITY_DATA_ROOT"])
eq = connect_ro(DATA / "equity_intelligence.db", timeout_s=90)

print("== raw_documents by source_type (FY25+ = published_date >= 2024-04-01)")
for r in eq.execute("""SELECT source_type, COUNT(*) n,
                              SUM(CASE WHEN published_date >= '2024-04-01' THEN 1 ELSE 0 END) fy25,
                              SUM(published_date IS NULL OR published_date='') nodate
                       FROM raw_documents GROUP BY 1 ORDER BY 2 DESC LIMIT 20"""):
    print("  ", r)

print("\n== document_chunks label fill (first 100k chunk ids, one column at a time)")
N = eq.execute("SELECT COUNT(*) FROM document_chunks WHERE chunk_id <= 100000").fetchone()[0]
from collections import OrderedDict as _OD
for col in ("fiscal_period", "sector_id", "industry_id", "isin", "symbol", "event_date", "published_date", "fiscal_confidence"):
    filled = eq.execute(f"SELECT SUM(CASE WHEN {col} IS NOT NULL AND CAST({col} AS TEXT)<>'' THEN 1 ELSE 0 END) FROM document_chunks WHERE chunk_id <= 100000").fetchone()[0]
    print(f"   {col:18s} {filled}/{N} = {100*(filled or 0)/N:.1f}%")
print("\n== corporate_documents: doc types + PIT fields")
for r in eq.execute("""SELECT doc_type, COUNT(*) n,
                              SUM(bse_dissem_ts IS NOT NULL AND bse_dissem_ts<>'') dissem,
                              SUM(publication_date IS NOT NULL AND publication_date<>'') pub,
                              SUM(call_date IS NOT NULL AND call_date<>'') call,
                              SUM(doc_date IS NOT NULL AND doc_date<>'') crawl
                       FROM corporate_documents GROUP BY 1 ORDER BY 2 DESC"""):
    print("  ", r)

print("\n== corporate_documents FY25+ known_at availability")
print(eq.execute("""SELECT COUNT(*),
  SUM(CASE WHEN bse_dissem_ts IS NOT NULL AND bse_dissem_ts<>'' THEN 1 ELSE 0 END) by_dissem,
  SUM(CASE WHEN (bse_dissem_ts IS NULL OR bse_dissem_ts='') AND publication_date IS NOT NULL AND publication_date<>'' THEN 1 ELSE 0 END) by_pub,
  SUM(CASE WHEN (bse_dissem_ts IS NULL OR bse_dissem_ts='') AND (publication_date IS NULL OR publication_date='') THEN 1 ELSE 0 END) none
FROM corporate_documents WHERE (publication_date >= '2024-04-01' OR bse_dissem_ts >= '2024-04-01')""").fetchall())

print("\n== results_notes.db (new store)")
rn = connect_ro(DATA / "results_notes.db", timeout_s=60)
print("docs:", rn.execute("SELECT COUNT(*), COUNT(DISTINCT isin), MIN(quarter_end), MAX(quarter_end), SUM(known_at IS NOT NULL) FROM docs").fetchone())
print("notes:", rn.execute("SELECT COUNT(*), COUNT(DISTINCT isin), SUM(has_numbers), SUM(basis='consolidated') FROM notes").fetchone())
print("by fy_q:", rn.execute("SELECT fy_q, COUNT(*) FROM docs GROUP BY 1 ORDER BY 1 DESC LIMIT 8").fetchall())
print("status:", rn.execute("SELECT status, COUNT(*) FROM docs GROUP BY 1").fetchall())
rn.close()

print("\n== chunks_v2.db (decks)")
cv = connect_ro(DATA / "chunks_v2.db", timeout_s=60)
print("deck_docs:", cv.execute("SELECT COUNT(*), COUNT(DISTINCT isin), MIN(known_at), MAX(known_at), SUM(known_at IS NULL) FROM deck_docs").fetchone())
print("fy25+ decks:", cv.execute("SELECT COUNT(*), COUNT(DISTINCT isin) FROM deck_docs WHERE known_at >= '2024-04-01'").fetchone())
print("chunks:", cv.execute("SELECT COUNT(*), COUNT(DISTINCT isin) FROM deck_chunks").fetchone())
cv.close()

print("\n== new stores that the design requires")
for f in ("chunks_v3.db", "market_state.db", "opinions.db"):
    print("  ", f, (DATA / f).exists())

print("\n== 5-entity spot checks")
# deterministic 5: hash picks among active screenable with docs
ents = eq.execute("""SELECT mc.isin, mc.nse_symbol, mc.company_name FROM master_companies mc
                     WHERE mc.is_active=1 AND mc.nse_symbol IS NOT NULL AND mc.nse_symbol<>''
                     ORDER BY (mc.isin % 101), mc.isin LIMIT 5""").fetchall()
boa = connect_ro(DATA / "bse_announcements.db", timeout_s=60)
for isin, sym, name in ents:
    ci = eq.execute("SELECT sector, industry, basic_industry FROM company_industry WHERE isin=?", (isin,)).fetchone()
    mc = eq.execute("SELECT sector, industry, market_cap_tier, is_fno_eligible FROM master_companies WHERE isin=?", (isin,)).fetchone()
    doc = eq.execute("""SELECT id, doc_type, bse_newsid, bse_dissem_ts, publication_date, doc_date
                        FROM corporate_documents WHERE isin=? AND bse_newsid IS NOT NULL
                        ORDER BY bse_dissem_ts DESC LIMIT 1""", (isin,)).fetchone()
    ann = boa.execute("SELECT DissemDT, NEWS_DT, headline FROM ann WHERE NEWSID=?", (doc[2],)).fetchone() if doc else None
    px1 = eq.execute("SELECT date, close FROM mkt_nse_full_daily WHERE symbol=? ORDER BY date DESC LIMIT 1", (sym,)).fetchone()
    px2 = eq.execute("SELECT date, close FROM daily_price_delivery WHERE symbol=? ORDER BY date DESC LIMIT 1", (sym,)).fetchone()
    qf = eq.execute("SELECT quarter_end_date, revenue_inr_cr, net_profit_inr_cr FROM quarterly_financials WHERE isin=? ORDER BY quarter_end_date DESC LIMIT 1", (isin,)).fetchone()
    print(f"\n  {sym} ({name}) isin={isin}")
    print(f"    master: sector={mc[0]!r} industry={mc[1]!r} tier={mc[2]} fno={mc[3]}")
    print(f"    NSE classification: sector={ci[0]!r} industry={ci[1]!r} basic={ci[2]!r}" if ci else "    NSE classification: MISSING")
    if doc:
        print(f"    doc id={doc[0]} type={doc[1]} newsid={doc[2]}")
        print(f"      corporate_documents.bse_dissem_ts={doc[3]!r} publication_date={doc[4]!r} doc_date(crawl)={doc[5]!r}")
        print(f"      bse_ann.DissemDT={ann[0]!r} News_DT={ann[1]!r}" if ann else "      bse_ann: no match")
    print(f"    price: mkt_nse_full_daily={px1} daily_price_delivery={px2}")
    print(f"    latest quarterly_financials={qf}")
boa.close()
eq.close()

