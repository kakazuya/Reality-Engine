"""End-of-day market update (Shivam OK 2026-10-19): fetch the last 7 days of exchange files and load them.

Daily files only: NSE full bhavcopy (all series incl. SME, with delivery), NSE indices, BSE bhavcopy + deliverables,
NSE participant OI / volume, NSE FII derivative stats. Both steps are resumable, so a missed day is picked up on the
next run (files already fetched / loaded are skipped). Scheduled task 'RealityEngine-EODMarket', weekdays 19:35 IST.
Log: reality_engine/data/logs/eod_market.log

    python -m reality_engine.scripts.run_eod_market
"""
import datetime as dt
import subprocess
import sys

SOURCES = "nse_full,nse_index,bse_bhav,bse_deliv,nse_part_oi,nse_part_vol,nse_fii_stats"


def main():
    end = dt.date.today()
    start = end - dt.timedelta(days=7)
    rc = subprocess.call([sys.executable, "-u", "-m", "reality_engine.scripts.fetch_market_raw", "--sources", SOURCES,
                          "--start", start.isoformat(), "--end", end.isoformat()])
    rc2 = subprocess.call([sys.executable, "-u", "-m", "reality_engine.scripts.load_market_raw", "--sources", SOURCES])
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M}] eod fetch rc={rc} load rc={rc2}", flush=True)
    return rc or rc2


if __name__ == "__main__":
    sys.exit(main())
