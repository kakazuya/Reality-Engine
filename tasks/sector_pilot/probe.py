"""Throwaway schema probe for the sector-label pilot (read-only)."""
import os
from pathlib import Path
from reality_engine.db.readonly import connect_ro

D = Path(os.environ["REALITY_DATA_ROOT"])
con = connect_ro(D / "ar_facts.db", timeout_s=60)
print("ar_docs cols:", [r[1] for r in con.execute("PRAGMA table_info(ar_docs)")])
print("ar_facts cols:", [r[1] for r in con.execute("PRAGMA table_info(ar_facts)")])
print("fy:", con.execute("select fiscal_year,count(*) from ar_docs group by 1 order by 1 desc limit 8").fetchall())
q = ("select category,count(*) c from ar_facts where doc_id in "
     "(select doc_id from ar_docs where fiscal_year in ('2024-25','FY25')) group by 1 order by c desc limit 20")
print("cats:", con.execute(q).fetchall())

eq = connect_ro(D / "equity_intelligence.db", timeout_s=60)
print("nse sectors:", eq.execute(
    "select count(distinct sector) from company_industry").fetchone())
print("ci sample:", eq.execute("select * from company_industry limit 3").fetchall())
print("tier x label:", eq.execute("""
select m.market_cap_tier, (ci.isin is not null) has_nse, count(*) n
from master_companies m left join company_industry ci on ci.isin=m.isin
group by 1,2 order by 1,2""").fetchall())
print("distinct sectors in ci:", eq.execute(
    "select count(distinct macro), count(distinct sector), count(distinct industry), count(distinct basic_industry) from company_industry").fetchone())
