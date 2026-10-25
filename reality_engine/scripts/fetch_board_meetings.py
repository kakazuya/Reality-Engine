"""Board-meeting calendar, NSE (PIPELINE_TODO phase C: forward board-meeting calendar / results dates ahead; 2026-10-19).

NSE corporate-board-meetings (equities + SME), month windows. Each row: symbol, ISIN, meeting_date (the date the
board meets, e.g. results day), purpose, description, intimated_at = bm_timestamp (IST, when the exchange published the
intimation: the point in time from which the market knew the date), attachment.
Table board_meetings (equity_intelligence.db). Raw JSON: raw_market/nse_board_meetings/.

    python -m reality_engine.scripts.fetch_board_meetings --start 2019-01 [--end 2026-12]   # history
    python -m reality_engine.scripts.fetch_board_meetings --ahead 90                         # nightly: -10 .. +90 days
"""
import argparse
import datetime as dt
import json
import re
import sqlite3
import time
from pathlib import Path
from reality_engine.config import raw_dir

DATA = Path(__file__).resolve().parents[1] / "data"
DB = DATA / "equity_intelligence.db"
OUT = raw_dir("raw_market") / "nse_board_meetings"
DDL = """CREATE TABLE IF NOT EXISTS board_meetings (symbol TEXT, isin TEXT, idx TEXT, meeting_date TEXT, purpose TEXT,
    description TEXT, intimated_at TEXT, industry TEXT, attachment TEXT, fetched_at TEXT,
    PRIMARY KEY (symbol, meeting_date, purpose, intimated_at));
CREATE INDEX IF NOT EXISTS idx_bm_date ON board_meetings(meeting_date);
CREATE INDEX IF NOT EXISTS idx_bm_isin ON board_meetings(isin, meeting_date)"""
MON = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def iso(s):
    m = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})(?: (\d{2}:\d{2}:\d{2}))?", (s or "").strip())
    if not m:
        return None
    d = f"{m.group(3)}-{MON[m.group(2).upper()]:02d}-{int(m.group(1)):02d}"
    return d + (f"T{m.group(4)}" if m.group(4) else "")


def fetch(db, a, b):
    from reality_engine.scripts.fetch_nse_api_raw import API, NseFetcher
    f = NseFetcher("nse_board_meetings", dt.date.today(), dt.date.today())
    OUT.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now().isoformat(timespec="seconds")
    while a <= b:
        e = min(b, (a.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1))
        for idx in ("equities", "sme"):
            data = None
            for attempt in range(4):
                try:
                    j = f.get(f"{API}corporate-board-meetings?index={idx}&from_date={a:%d-%m-%Y}&to_date={e:%d-%m-%Y}").json()
                    data = j if isinstance(j, list) else (j.get("data") or [])
                    break
                except Exception:  # noqa: BLE001
                    f.s = None; time.sleep(5 * (attempt + 1))
            if data is None:
                print(a, idx, "failed", flush=True); continue
            (OUT / f"{idx}_{a:%Y-%m-%d}_{e:%Y-%m-%d}.json").write_text(json.dumps(data), encoding="utf-8")
            rows = [(r.get("bm_symbol"), r.get("sm_isin"), idx, iso(r.get("bm_date")), r.get("bm_purpose"),
                     r.get("bm_desc"), iso(r.get("bm_timestamp")),
                     None if r.get("sm_indusrty") in (None, "-") else r.get("sm_indusrty"), r.get("attachment"), now)
                    for r in data if r.get("bm_symbol") and r.get("bm_date")]
            with db:
                db.executemany("INSERT OR REPLACE INTO board_meetings VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            print(f"{a}..{e} {idx}: {len(rows)}", flush=True)
            time.sleep(1.0)
        a = e + dt.timedelta(days=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--ahead", type=int, default=0)
    a = ap.parse_args()
    db = sqlite3.connect(DB, timeout=600)
    db.executescript(DDL)
    if a.ahead:
        fetch(db, dt.date.today() - dt.timedelta(days=10), dt.date.today() + dt.timedelta(days=a.ahead))
    else:
        start = dt.date.fromisoformat((a.start or "2019-01") + "-01")
        end = dt.date.fromisoformat(a.end + "-28") if a.end else dt.date.today() + dt.timedelta(days=90)
        fetch(db, start, end)
    print(db.execute("SELECT COUNT(*), MIN(meeting_date), MAX(meeting_date), SUM(intimated_at IS NULL) FROM board_meetings").fetchone())


if __name__ == "__main__":
    main()
