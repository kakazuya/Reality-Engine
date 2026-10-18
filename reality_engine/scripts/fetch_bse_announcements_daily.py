"""Market-wide BSE announcements by date -> analysis/bse_announcements.db table `ann` (2026-10-19).

The original harvest (analysis/bse_announcement_harvest.py) walks company by company and ends 2026-10-18. This fetches
ALL companies for each day in [start, end] (no scrip filter: ~870 rows on a results day, 50 per page), so the feed stays
current daily: order wins ('Award of Order / Receipt of Order', Reg. 30), concall transcripts, investor presentations,
results, board meetings, everything, each with BSE's dissemination time (DissemDT / DT_TM). Rows are keyed by NEWSID
(INSERT OR IGNORE), so re-runs and overlap with the per-company harvest are harmless. symbol = NSE symbol from
security_master when the ISIN-less row's scrip code is known.

    python -m reality_engine.scripts.fetch_bse_announcements_daily [--start 2026-10-10] [--end 2026-10-19]
"""
import argparse
import datetime as dt
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analysis"))
from bse_announcement_harvest import COLS, H, URL, session  # noqa: E402

OUT = ROOT / "analysis/bse_announcements.db"
MAIN = ROOT / "reality_engine/data/equity_intelligence.db"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=(dt.date.today() - dt.timedelta(days=7)).isoformat())
    ap.add_argument("--end", default=dt.date.today().isoformat())
    a = ap.parse_args()
    db = sqlite3.connect(OUT, timeout=120)
    sym = {}
    try:
        m = sqlite3.connect(f"file:{MAIN}?mode=ro", uri=True)
        for code, s in m.execute("SELECT bse_code, nse_symbol FROM security_master WHERE bse_code IS NOT NULL"):
            sym[str(code)] = s
        for code, s in m.execute("SELECT bse_code, nse_symbol FROM master_companies WHERE bse_code IS NOT NULL"):
            sym.setdefault(str(code), s)
    except sqlite3.Error:
        pass
    s = session()
    d = dt.date.fromisoformat(a.start)
    end = dt.date.fromisoformat(a.end)
    total_new = 0
    while d <= end:
        day = f"{d:%Y%m%d}"
        p, new, rows_day = 1, 0, 0
        while True:
            for attempt in range(4):
                try:
                    r = s.get(URL.format(p=p, f=day, c="", t=day), headers=H, timeout=30)
                    if r.status_code == 403:
                        time.sleep(600); s = session(); continue
                    tb = r.json().get("Table", [])
                    break
                except Exception:
                    time.sleep(10 * (attempt + 1)); s = session()
            else:
                tb = []
            before = db.total_changes
            db.executemany(f"INSERT OR IGNORE INTO ann({','.join(COLS)},symbol) VALUES({','.join('?' * (len(COLS) + 1))})",
                           [tuple(x.get(c) for c in COLS) + (sym.get(str(x.get("SCRIP_CD"))),) for x in tb])
            new += db.total_changes - before; rows_day += len(tb)
            if len(tb) < 50:
                break
            p += 1
            time.sleep(0.3)
        db.commit()
        print(f"{d} rows {rows_day} new {new}", flush=True)
        total_new += new
        d += dt.timedelta(days=1)
    print(f"done: {total_new} new announcements; feed max", db.execute("SELECT MAX(DT_TM) FROM ann").fetchone()[0])


if __name__ == "__main__":
    main()
