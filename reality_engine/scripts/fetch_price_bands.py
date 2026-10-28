"""Daily NSE price band per security (Shivam decision 5, 2026-10-27). Raw fetch only.

Source: ``https://nsearchives.nseindia.com/content/equities/sec_list_DDMMYYYY.csv``, one file per
session. Columns: ``Symbol, Series, Security Name, Band, Remarks``; ``Band`` is the circuit limit in
percent (2 / 5 / 10 / 20 / 40 / ``No Band``), ``Remarks`` carries the GSM stage. This is the same
file that produced ``equity_intelligence.price_bands`` (538 dates in the live DB after the
2026-10-21 restore; 1,680 dates in ``truth_2026-10-19.duckdb``).

Earliest file: 2019-12-30 (2019-01-01..2019-12-27 return 404). Every weekday from there on returns
a file (holidays 404); 2019-12-30 -> today at a 3 s interval is about 1.6 h, under the 3-hour rule.

The upper/lower circuit *hit* is derived later from OHLC vs the band: compare the session's
high/low/close against the previous close grown by ``band_pct`` (F&O names have no band). This
script does not build it.

    python -m reality_engine.scripts.fetch_price_bands --from 2019-12-30 --out .tmp/price_bands
    python -m reality_engine.scripts.fetch_price_bands --sample 30 --from 2019-12-30  # timed test
"""
import argparse
import csv
import datetime as dt
import io
import json
import sys
import time
from pathlib import Path

import requests

from reality_engine.config import RAW_ROOT

URL = "https://nsearchives.nseindia.com/content/equities/sec_list_{d:%d%m%Y}.csv"
WARM = "https://www.nseindia.com/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
RETRY_STATUS = (403, 429, 503)
MAX_ATTEMPTS = 4


def weekdays(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += dt.timedelta(days=1)


def even_sample(items, n):
    """n items spread evenly over the list (for the timed test)."""
    items = list(items)
    if n is None or n >= len(items):
        return items
    if n <= 0:
        return []
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def band_pct(value):
    """'2'/'5'/'10'/'20'/'40' -> int; 'No Band'/'' -> None."""
    v = (value or "").strip()
    if not v or v.lower().startswith("no"):
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def parse_band_csv(text, date):
    """One sec_list file -> tidy rows (date, symbol, series, isin, band_pct, remarks)."""
    rows = []
    for r in csv.DictReader(io.StringIO(text.lstrip("\ufeff").replace("\r\n", "\n"))):
        sym = (r.get("Symbol") or "").strip()
        if not sym:
            continue
        remarks = (r.get("Remarks") or "").strip()
        rows.append({
            "date": date,
            "symbol": sym,
            "series": (r.get("Series") or "").strip() or None,
            "isin": None,  # sec_list carries no ISIN; resolve through symbol_isin_history later
            "band_pct": band_pct(r.get("Band")),
            "remarks": None if remarks in ("", "-") else remarks,
        })
    return rows


def session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "text/csv,*/*",
                      "Accept-Language": "en-US,en;q=0.9", "Referer": WARM})
    try:
        s.get(WARM, timeout=30)  # cookie warm-up; archives also serve without it
    except requests.RequestException:
        pass
    return s


class Fetcher:
    def __init__(self, out, interval):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.interval = interval
        self.s = session()
        self.latencies = []
        self.counts = {"ok": 0, "absent": 0, "skipped": 0}
        self.missing = self.out / "_missing.txt"
        self.manifest = self.out / "_manifest.jsonl"

    def record(self, date, status, rows, size, seconds):
        with self.manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"date": date, "status": status, "rows": rows, "bytes": size,
                                "seconds": round(seconds, 3),
                                "at": dt.datetime.now().isoformat(timespec="seconds")}) + "\n")

    def get(self, url):
        """GET with backoff on 403/429/503. Returns the response or None when absent."""
        for attempt in range(MAX_ATTEMPTS):
            t0 = time.monotonic()
            try:
                r = self.s.get(url, timeout=60)
            except requests.RequestException:
                r = None
            self.latencies.append(time.monotonic() - t0)
            if r is not None and r.status_code == 200:
                return r
            if r is not None and r.status_code == 404:
                return None
            if r is None or r.status_code in RETRY_STATUS:
                if attempt + 1 < MAX_ATTEMPTS:
                    time.sleep(min(90, 10 * 2 ** attempt))
                    self.s = session()
                    continue
            # any other status after a retryable one, or retries exhausted
            code = "network" if r is None else r.status_code
            raise SystemExit(f"BLOCKED by NSE on {url}: {code}. Stopped after "
                             f"{MAX_ATTEMPTS} attempts; re-run later (files present are kept).")
        raise SystemExit(f"BLOCKED by NSE on {url}")

    def fetch_day(self, day):
        name = f"sec_list_{day:%d%m%Y}.csv"
        path = self.out / name
        if path.exists() and path.stat().st_size > 0:
            self.counts["skipped"] += 1
            return path, "skipped"
        r = self.get(URL.format(d=day))
        if r is None:
            with self.missing.open("a", encoding="utf-8") as f:
                f.write(day.isoformat() + "\n")
            self.counts["absent"] += 1
            self.record(day.isoformat(), "absent", 0, 0, self.latencies[-1])
            return None, "absent"
        body = r.content
        head = body[:200].decode("utf-8-sig", "replace").lower()
        if not head.startswith("symbol") or "series" not in head:
            # An empty or odd file for one day is a gap, not a block; 5 in a row stops.
            self.bad_streak = getattr(self, "bad_streak", 0) + 1
            if self.bad_streak >= 5:
                raise SystemExit(f"unexpected content x5 in a row, last {day}: {head[:80]!r}")
            print(f"unexpected content (not sec_list) for {day}, logged as missing: {head[:60]!r}",
                  flush=True)
            with self.missing.open("a", encoding="utf-8") as f:
                f.write(day.isoformat() + "\n")
            self.counts["absent"] += 1
            self.record(day.isoformat(), "not_sec_list", 0, len(body), self.latencies[-1])
            return None, "absent"
        self.bad_streak = 0
        path.write_bytes(body)
        self.counts["ok"] += 1
        self.record(day.isoformat(), "ok", len(parse_band_csv(body.decode("utf-8-sig", "replace"),
                                                              day.isoformat())), len(body),
                    self.latencies[-1])
        return path, "ok"


def project(full, interval, latencies):
    mean = sum(latencies) / len(latencies) if latencies else 0.0
    seconds = full * (interval + mean)
    return mean, seconds


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", default="2019-01-01",
                    help="first date (earliest file is 2019-12-30)")
    ap.add_argument("--to", dest="end", default=dt.date.today().isoformat())
    ap.add_argument("--out", default=str(RAW_ROOT / "price_bands"))
    ap.add_argument("--interval", type=float, default=3.0, help="seconds between requests (>=2)")
    ap.add_argument("--sample", type=int, default=None, help="fetch only N dates spread over the range")
    a = ap.parse_args()
    if a.interval < 2:
        ap.error("--interval must be >= 2 s on NSE")
    start, end = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    grid = list(weekdays(start, end))
    todo = even_sample(grid, a.sample)
    f = Fetcher(a.out, a.interval)
    print(f"{len(grid)} weekdays {start}..{end}; fetching {len(todo)}", flush=True)
    t0 = time.monotonic()
    parsed, examples = 0, []
    for n, day in enumerate(todo, 1):
        path, status = f.fetch_day(day)
        if path is not None and status != "skipped":
            rows = parse_band_csv(path.read_bytes().decode("utf-8-sig", "replace"), day.isoformat())
            parsed += len(rows)
            examples.extend(rows[:1])
        if n % 10 == 0 or n == len(todo):
            print(f"{n}/{len(todo)} {day} {f.counts}", flush=True)
        if n < len(todo) and status != "skipped":
            time.sleep(a.interval)
    elapsed = time.monotonic() - t0
    if not f.latencies:
        print(f"\nno requests: all {f.counts['skipped']} files already present; {elapsed:.1f}s")
        return
    mean, seconds = project(len(grid), a.interval, f.latencies)
    print(f"\nrequests {len(f.latencies)} ({f.counts}); wall {elapsed:.1f}s; "
          f"mean latency {mean:.3f}s/request at {a.interval:.1f}s interval")
    print(f"projected full run: {len(grid)} requests x ({a.interval:.1f}+{mean:.3f}) s = "
          f"{seconds / 3600:.2f} h -> {'<= 3 h: fetch from 2019' if seconds <= 3 * 3600 else '> 3 h: FY25 only'}")
    print(f"parsed {parsed} tidy rows from {f.counts['ok']} files; examples:")
    for r in examples[:3]:
        print("  ", r)
    print("earliest file available: 2019-12-30 (2019-01-01..2019-12-27 are 404)", flush=True)
    if f.counts["absent"] and f.counts["ok"] == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
