"""Probe 9: active counts, cap coverage, deck_sources columns."""
import os
from pathlib import Path
from reality_engine.db.readonly import connect_ro

D = Path(os.environ["REALITY_DATA_ROOT"])
eq = connect_ro(D / "equity_intelligence.db", timeout_s=30)
print("active x tier:", eq.execute(
    "select is_active,market_cap_tier,count(*) from master_companies group by 1,2 order by 1,2").fetchall())
print("forensic cap dist:", eq.execute("""
select case when market_cap_inr_cr>=50000 then 'LARGE' when market_cap_inr_cr>=10000 then 'MID'
            when market_cap_inr_cr>=1000 then 'SMALL' else 'MICRO' end t, count(*)
from company_forensic_health where market_cap_inr_cr is not null group by 1""").fetchall())
print("deck_sources cols:", [r[1] for r in eq.execute("PRAGMA table_info(deck_figures)")] if False else "n/a")
print("bf cols:", [r[1] for r in eq.execute("PRAGMA table_info(company_industry)")])
# how many small/micro active with a bse code and NSE label
print("poolA rough:", eq.execute("""
select count(*) from master_companies m join company_industry ci on ci.isin=m.isin
where m.is_active=1 and m.market_cap_tier in ('SMALL','MICRO') and (m.bse_code is not null and m.bse_code<>'')""").fetchone())
print("poolB rough:", eq.execute("""
select count(*) from master_companies m left join company_industry ci on ci.isin=m.isin
where ci.isin is null and m.is_active=1 and m.market_cap_tier in ('SMALL','MICRO') and (m.bse_code is not null and m.bse_code<>'')""").fetchone())
