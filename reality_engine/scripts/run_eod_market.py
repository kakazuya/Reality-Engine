"""End-of-day market + disclosure update (Shivam OK 2026-10-19). Scheduled task 'RealityEngine-EODMarket', weekdays
19:35 IST. Every step looks back 10 days and is resumable (fetched files / loaded files / known NEWSIDs are skipped),
so a missed day is picked up on the next run. One failing step does not stop the others.

Steps
  1 exchange daily files: NSE full bhavcopy (all series incl. SME, delivery), NSE CM bhavcopy with ISIN (security
    master), NSE indices, BSE bhavcopy + deliverables, NSE participant OI / volume, NSE FII derivative stats
  2 NSE API: bulk / block / short deals, insider (new PIT feed + XMLs), SAST, corporate actions (main + SME)
  3 BSE API: bulk / block deals, insider, indices, corporate actions
  4 NSDL FPI daily; Moneycontrol FII/DII cash
  5 load everything above into the mkt_* tables
  6 BSE announcements, all companies (order wins, transcripts, decks, results, board meetings ...) ->
    analysis/bse_announcements.db, then new concall transcripts / decks into corporate_documents
  7 rebuild security_master / symbol_isin_history
  8 PIB English releases of the last 3 days (pib_feed.py)
  9 trading ISIN for results XBRL filings (resolve_results_isin.py -> filings_isin)
 10 query speed check (query_speed_check.py; over-limit queries go into the watchdog report)
Log: reality_engine/data/logs/eod_market.log

    python -m reality_engine.scripts.run_eod_market
"""
import datetime as dt
import subprocess
import sys

DAILY = "nse_full,nse_cm_isin,nse_index,bse_bhav,bse_deliv,nse_part_oi,nse_part_vol,nse_fii_stats"
NSE_API = "nse_bulk,nse_block,nse_short,nse_pit_gg,nse_pit_gg_sme,nse_pit_gg_xml,nse_sast,nse_corpact,nse_corpact_sme"
BSE_API = "bse_bulk,bse_block,bse_insider,bse_index,bse_corpact"
LOAD = ("nse_full,nse_index,bse_bhav,bse_deliv,nse_part_oi,nse_part_vol,nse_fii_stats,nse_bulk,nse_block,nse_short,"
        "nse_pit_gg,nse_pit_gg_sme,nse_pit_gg_xml,nse_sast,nse_corpact,bse_bulk,bse_block,bse_insider,bse_index,"
        "nsdl_fpi_daily,mc_fiidii")


def step(name, args):
    t0 = dt.datetime.now()
    rc = subprocess.call([sys.executable, "-u", "-m", *args])
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M}] {name} rc={rc} ({(dt.datetime.now() - t0).seconds}s)", flush=True)
    return rc


def main():
    end = dt.date.today()
    start = (end - dt.timedelta(days=10)).isoformat()
    e = end.isoformat()
    rcs = [
        step("exchange files", ["reality_engine.scripts.fetch_market_raw", "--sources", DAILY, "--start", start, "--end", e]),
        step("nse api", ["reality_engine.scripts.fetch_nse_api_raw", "--datasets", NSE_API, "--start", start, "--end", e]),
        step("bse api", ["reality_engine.scripts.fetch_bse_api_raw", "--datasets", BSE_API, "--start", start, "--end", e]),
        step("nsdl fpi", ["reality_engine.scripts.fetch_nsdl_raw", "--datasets", "nsdl_fpi_daily", "--start", start, "--end", e]),
        step("fii/dii cash", ["reality_engine.scripts.fetch_fiidii_moneycontrol", "--start", start, "--end", e]),
        step("load", ["reality_engine.scripts.load_market_raw", "--sources", LOAD]),
        step("bse announcements", ["reality_engine.scripts.fetch_bse_announcements_daily", "--start", start, "--end", e]),
        step("new transcripts/decks", ["reality_engine.scripts.discover_bse_feed_docs", "--since", start]),
        step("security master", ["reality_engine.scripts.build_security_master"]),
        step("pib releases", ["reality_engine.scripts.pib_feed", "--start", (end - dt.timedelta(days=3)).isoformat(), "--end", e]),
        step("results isin", ["reality_engine.scripts.resolve_results_isin"]),
        step("query speed check", ["reality_engine.scripts.query_speed_check"]),
    ]
    rcs[-1] = 0   # an over-limit query is reported (watchdog report), it is not a failed EOD run
    return max(rcs)


if __name__ == "__main__":
    sys.exit(main())
