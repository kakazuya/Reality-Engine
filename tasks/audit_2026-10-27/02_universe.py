"""A2 - universe, fill rates and history-depth measurements. Read-only, bounded."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reality_engine.db.readonly import connect_ro  # noqa: E402

DATA = Path(os.environ["REALITY_DATA_ROOT"])
T = lambda db: connect_ro(DATA / db, timeout_s=60)  # noqa: E731

eq = T("equity_intelligence.db")


def q(title, sql, con=None):
    con = con or eq
    try:
        rows = con.execute(sql).fetchall()
    except Exception as exc:  # noqa: BLE001
        print(f"-- {title}: ERROR {exc}")
        return []
    print(f"-- {title}")
    for r in rows[:40]:
        print("   ", r)
    if len(rows) > 40:
        print(f"    ... {len(rows)} rows")
    return rows


print("## master_companies universe")
q("total / active / screenable",
  "SELECT COUNT(*), SUM(is_active), SUM(is_screenable) FROM master_companies")
q("exchange split (all)",
  """SELECT CASE WHEN nse_symbol IS NOT NULL AND nse_symbol<>'' AND bse_code IS NOT NULL AND bse_code<>'' THEN 'BSE+NSE'
                 WHEN nse_symbol IS NOT NULL AND nse_symbol<>'' THEN 'NSE-only'
                 ELSE 'BSE-only' END k, COUNT(*), SUM(is_active)
     FROM master_companies GROUP BY k""")
q("sector/industry/mcap_tier fill on master",
  """SELECT COUNT(*) n,
            SUM(sector IS NOT NULL AND sector<>'') has_sector,
            SUM(industry IS NOT NULL AND industry<>'') has_industry,
            SUM(market_cap_tier IS NOT NULL AND market_cap_tier<>'') has_tier,
            SUM(is_fno_eligible=1) fno_flag,
            SUM(is_nifty50=1) n50, SUM(is_nifty100=1) n100, SUM(is_nifty200=1) n200, SUM(is_nifty500=1) n500
     FROM master_companies""")
q("missing sector split by exchange",
  """SELECT CASE WHEN nse_symbol IS NOT NULL AND nse_symbol<>'' AND bse_code IS NOT NULL AND bse_code<>'' THEN 'BSE+NSE'
                 WHEN nse_symbol IS NOT NULL AND nse_symbol<>'' THEN 'NSE-only'
                 ELSE 'BSE-only' END k,
            COUNT(*) n, SUM(sector IS NULL OR sector='') no_sector, SUM(industry IS NULL OR industry='') no_industry
     FROM master_companies GROUP BY k""")
q("market_cap_tier values", "SELECT market_cap_tier, COUNT(*) FROM master_companies GROUP BY 1")
q("sector values top", "SELECT sector, COUNT(*) c FROM master_companies GROUP BY 1 ORDER BY c DESC LIMIT 20")
q("company_industry fill",
  """SELECT COUNT(*) n, SUM(sector IS NOT NULL AND sector<>'') has_sector,
            SUM(macro IS NOT NULL AND macro<>'') has_macro,
            SUM(industry IS NOT NULL AND industry<>'') has_ind,
            SUM(basic_industry IS NOT NULL AND basic_industry<>'') has_basic,
            SUM(index_list IS NOT NULL AND index_list<>'') has_index_list
     FROM company_industry""")
q("company_industry in master?",
  """SELECT COUNT(*) FROM company_industry ci JOIN master_companies mc ON mc.isin=ci.isin""")
q("master ISINs with company_industry row",
  """SELECT COUNT(*) FROM master_companies mc WHERE mc.isin IN (SELECT isin FROM company_industry)""")

print("\n## index membership")
q("index_membership rows/as_of", "SELECT index_name, as_of, COUNT(*) FROM index_membership GROUP BY 1,2")
q("index_tri cols/sample", None) if False else None
for t in ("index_tri", "mkt_nse_index_daily", "nse_index_breadth"):
    cols = [r[1] for r in eq.execute(f"PRAGMA table_info('{t}')")]
    n = eq.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
    print(f"-- {t} [{n}] :: {cols}")
q("nse index daily distinct indices",
  "SELECT COUNT(DISTINCT index_name), MIN(date), MAX(date) FROM mkt_nse_index_daily") if "index_name" in [r[1] for r in eq.execute("PRAGMA table_info('mkt_nse_index_daily')")] else None

print("\n## price bands")
q("price_bands range + series",
  "SELECT MIN(date), MAX(date), COUNT(*), COUNT(DISTINCT symbol) FROM price_bands")
q("price_bands band values", "SELECT band, COUNT(*) FROM price_bands GROUP BY 1 ORDER BY 2 DESC")
q("price_bands by year", "SELECT substr(date,1,4) y, COUNT(*), COUNT(DISTINCT symbol) FROM price_bands GROUP BY y")

print("\n## symbol_isin_history / security_master / rekey")
q("symbol_isin_history range",
  "SELECT exchange, COUNT(*), COUNT(DISTINCT symbol), COUNT(DISTINCT isin), MIN(first_date), MAX(last_date) FROM symbol_isin_history GROUP BY 1")
q("symbols with >1 ISIN", "SELECT COUNT(*) FROM (SELECT exchange,symbol FROM symbol_isin_history GROUP BY 1,2 HAVING COUNT(DISTINCT isin)>1)")
q("ISINs with >1 symbol", "SELECT COUNT(*) FROM (SELECT isin FROM symbol_isin_history GROUP BY 1 HAVING COUNT(DISTINCT symbol)>1)")
cols = [r[1] for r in eq.execute("PRAGMA table_info('isin_rekey_log')")]
print("-- isin_rekey_log cols ::", cols)
q("isin_rekey_log sample", "SELECT * FROM isin_rekey_log LIMIT 10")
q("security_master dup issuer", "SELECT COUNT(*), COUNT(DISTINCT issuer) FROM security_master")
q("security_master same name multiple isin",
  "SELECT COUNT(*) FROM (SELECT name FROM security_master GROUP BY name HAVING COUNT(DISTINCT isin)>1)")

print("\n## corporate actions")
q("action_type counts", "SELECT action_type, COUNT(*), MIN(ex_date), MAX(ex_date) FROM corporate_actions GROUP BY 1 ORDER BY 2 DESC")
q("face_value changes", "SELECT COUNT(*) FROM corporate_actions WHERE face_value IS NOT NULL AND face_value<>''")
q("actions with ex_date null", "SELECT SUM(ex_date IS NULL OR ex_date=''), COUNT(*) FROM corporate_actions")

print("\n## ownership")
q("shp_index range/count", "SELECT COUNT(*), COUNT(DISTINCT isin), MIN(quarter_end), MAX(quarter_end), SUM(broadcast_at IS NOT NULL AND broadcast_at<>'') FROM shp_index")
q("shp_index quarters", "SELECT COUNT(DISTINCT quarter_end) FROM shp_index")
q("shp_index fy25+", "SELECT COUNT(*), COUNT(DISTINCT isin) FROM shp_index WHERE quarter_end >= '2024-03-31'")
q("shareholding rows", "SELECT COUNT(*), MIN(quarter_end), MAX(quarter_end), COUNT(DISTINCT symbol) FROM shareholding")

print("\n## results / financials")
rx = T("results_xbrl.db")
q("filings totals", "SELECT COUNT(*), COUNT(DISTINCT isin), MIN(period_end), MAX(period_end), SUM(dissem_ts IS NOT NULL AND dissem_ts<>''), SUM(broadcast_ts IS NOT NULL AND broadcast_ts<>'') FROM filings", rx)
q("filings FY25+ isins", "SELECT COUNT(*), COUNT(DISTINCT isin) FROM filings WHERE period_end >= '2024-03-31'", rx)
q("filings period_end null", "SELECT SUM(period_end IS NULL OR period_end=''), SUM(isin IS NULL OR isin='') FROM filings", rx)
q("filings index_period sample", "SELECT index_period, reporting_quarter, COUNT(*) FROM filings GROUP BY 1,2 ORDER BY 3 DESC LIMIT 12", rx)
q("quarterly_financials nse join", "SELECT COUNT(*), SUM(xbrl_file_path IS NOT NULL AND xbrl_file_path<>''), MIN(quarter_end_date), MAX(quarter_end_date) FROM quarterly_financials")
q("annual_financials", "SELECT COUNT(*), COUNT(DISTINCT isin), MIN(fiscal_year), MAX(fiscal_year) FROM annual_financials")
rx.close()
eq.close()
