"""
Raw NSE disclosure fetcher (download only, no DB writes).

Pulls NSE's historical disclosure APIs from 2019-01-01 into
``RAW_ROOT/raw_market/<dataset>/`` as one file per window, so they
can be loaded into the DB later under the single-writer queue lock.

Datasets:
  nse_pit       SEBI PIT insider disclosures (buy/sell qty, value, mode)  monthly JSON
  nse_sast      SAST Reg 29 takeover disclosures                          monthly JSON
  nse_corpact   Corporate actions (dividend, split, bonus, rights...)     monthly JSON
  nse_pit_gg    New PIT filing feed (from ~2026-05), equities / SME       monthly JSON
  nse_pit_gg_xml  per-filing XBRL XML with the transaction details
  nse_bulk      Bulk deals                                                daily CSV
  nse_block     Block deals                                               daily CSV
  nse_short     Short-selling disclosures                                 daily CSV

The bulk/block/short JSON endpoint silently caps a response at 70 rows; the
``csv=true`` export of the same endpoint is not capped (2026-09-18: 224 rows vs
70), so deals are pulled as daily CSV. Resumable via ``_manifest.csv``.

Usage:
    python -m reality_engine.scripts.fetch_nse_api_raw --datasets all
    python -m reality_engine.scripts.fetch_nse_api_raw --datasets nse_bulk,nse_block --window year
"""

import argparse
import csv
import json
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from reality_engine.config import raw_dir

import requests

ROOT = raw_dir("raw_market")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
API = "https://www.nseindia.com/api/"
PACE_SEC = 1.5
SESSION_REFRESH = 150  # requests between cookie refreshes

MONTHLY = {
    "nse_pit": "corporates-pit?index=equities&from_date={a}&to_date={b}",
    "nse_sast": "corporate-sast-reg29?index=equities&from_date={a}&to_date={b}",
    "nse_corpact": "corporates-corporateActions?index=equities&from_date={a}&to_date={b}",
    # SME (Emerge) actions are a separate feed; bonuses there were missing from the equities feed.
    "nse_corpact_sme": "corporates-corporateActions?index=sme&from_date={a}&to_date={b}",
    # NSE moved PIT filings to a new system around 2026-05: the old corporates-pit feed is
    # empty from 2026-06, and the new feed lists filings only (details are in each XML).
    "nse_pit_gg": "corporates-pit-gg?index=equities&from_date={a}&to_date={b}",
    "nse_pit_gg_sme": "corporates-pit-gg?index=sme&from_date={a}&to_date={b}",
}
DAILY_CSV = {
    "nse_bulk": "bulk_deals",
    "nse_block": "block_deals",
    "nse_short": "short_selling",
}


def month_windows(start: date, end: date):
    d = start.replace(day=1)
    while d <= end:
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield max(d, start), min(nxt - timedelta(days=1), end)
        d = nxt


def day_windows(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d, d
        d += timedelta(days=1)


def year_windows(start: date, end: date):
    d = date(start.year, 1, 1)
    while d <= end:
        nxt = date(d.year + 1, 1, 1)
        yield max(d, start), min(nxt - timedelta(days=1), end)
        d = nxt


class NseFetcher:
    def __init__(self, name: str, start: date, end: date, window: str = "day"):
        self.name = name
        self.window = window
        self.dir = ROOT / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest = self.dir / "_manifest.csv"
        self.done = {}
        if self.manifest.exists():
            with self.manifest.open(newline="") as f:
                self.done = {r["window"]: r["status"] for r in csv.DictReader(f)}
        self.start, self.end = start, end
        self.calls = 0
        self.s = None
        self.counts = {"ok": 0, "empty": 0, "error": 0, "skipped": 0}

    def _session(self):
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept": "application/json,text/csv,*/*",
                          "Referer": "https://www.nseindia.com/"})
        s.get("https://www.nseindia.com/report-detail/display-bulk-and-block-deals", timeout=30)
        time.sleep(PACE_SEC)
        return s

    def get(self, url: str) -> requests.Response:
        if self.s is None or self.calls % SESSION_REFRESH == 0:
            self.s = self._session()
        self.calls += 1
        return self.s.get(url, timeout=60)

    def record(self, window: str, status: str, rows: int):
        new = not self.manifest.exists()
        with self.manifest.open("a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["window", "status", "rows", "fetched_at"])
            w.writerow([window, status, rows, datetime.now().isoformat(timespec="seconds")])

    def run(self):
        monthly = self.name in MONTHLY
        span = {"day": day_windows, "month": month_windows, "year": year_windows}[
            "month" if monthly else self.window]
        windows = span(self.start, self.end)
        for a, b in windows:
            key = f"{a.isoformat()}_{b.isoformat()}"
            if self.done.get(key) in ("ok", "empty"):
                self.counts["skipped"] += 1
                continue
            status, rows = "error", 0
            for attempt in range(4):
                try:
                    if monthly:
                        url = API + MONTHLY[self.name].format(a=f"{a:%d-%m-%Y}", b=f"{b:%d-%m-%Y}")
                        r = self.get(url)
                        data = r.json()
                        data = data.get("data", data) if isinstance(data, dict) else data
                        rows = len(data)
                        if rows:
                            (self.dir / f"{key}.json").write_text(json.dumps(data), encoding="utf-8")
                    else:
                        url = (API + "historicalOR/bulk-block-short-deals?optionType="
                               f"{DAILY_CSV[self.name]}&from={a:%d-%m-%Y}&to={b:%d-%m-%Y}&csv=true")
                        r = self.get(url)
                        if "text/csv" not in r.headers.get("content-type", ""):
                            raise ValueError(f"not csv: {r.status_code}")
                        rows = max(r.text.strip().count("\n"), 0)
                        if rows:
                            (self.dir / f"{key}.csv").write_bytes(r.content)
                    status = "ok" if rows else "empty"
                    break
                except Exception:
                    self.s = None  # force a fresh cookie session
                    time.sleep(PACE_SEC * (2 ** (attempt + 1)))
            self.record(key, status, rows)
            self.counts[status] += 1
            time.sleep(PACE_SEC)
        return self.counts


RESULT_INDICES = ("equities", "sme")
RESULT_PERIODS = ("Quarterly", "Half-Yearly", "Annual", "Others")


def fetch_results_index(start: date, end: date):
    """Financial-results filing index (one JSON per index/period/week) with broadcast and
    dissemination timestamps, period, consolidated flag and the XBRL link.
    Weekly windows keep each response small (about 450 quarterly filings in a busy fortnight)."""
    counts = {}
    for idx in RESULT_INDICES:
        name = f"nse_results_{idx}"
        f = NseFetcher(name, start, end)
        c = {"ok": 0, "empty": 0, "error": 0, "skipped": 0}
        d = start
        while d <= end:
            b = min(d + timedelta(days=6), end)
            for per in RESULT_PERIODS:
                key = f"{per}_{d.isoformat()}_{b.isoformat()}"
                if f.done.get(key) in ("ok", "empty") and b < end:
                    c["skipped"] += 1
                    continue
                status, rows = "error", 0
                for attempt in range(4):
                    try:
                        r = f.get(f"{API}corporates-financial-results?index={idx}&period={per}"
                                  f"&from_date={d:%d-%m-%Y}&to_date={b:%d-%m-%Y}")
                        data = r.json()
                        data = data if isinstance(data, list) else data.get("data", [])
                        rows = len(data)
                        if rows:
                            (f.dir / f"{key}.json").write_text(json.dumps(data), encoding="utf-8")
                        status = "ok" if rows else "empty"
                        break
                    except Exception:
                        f.s = None
                        time.sleep(PACE_SEC * (2 ** (attempt + 1)))
                f.record(key, status, rows)
                c[status] += 1
                time.sleep(PACE_SEC)
            d = b + timedelta(days=1)
        counts[name] = c
    return counts


def fetch_results_xbrl():
    """Download every XBRL file listed in the results index (deduplicated by URL)."""
    out = ROOT / "nse_results_xbrl"
    out.mkdir(parents=True, exist_ok=True)
    have = {p.name for p in out.iterdir()}
    urls = set()
    for idx in RESULT_INDICES:
        for jf in (ROOT / f"nse_results_{idx}").glob("*.json"):
            for rec in json.loads(jf.read_text(encoding="utf-8")):
                u = rec.get("xbrl")
                if u and u.startswith("http") and u.rsplit("/", 1)[-1] not in have:
                    urls.add(u)
    f = NseFetcher("nse_results_xbrl", date.today(), date.today())
    counts = {"todo": len(urls), "ok": 0, "error": 0}
    for u in sorted(urls):
        try:
            body = f.get(u).content
            if body.lstrip()[:1] == b"<":
                (out / u.rsplit("/", 1)[-1]).write_bytes(body)
                counts["ok"] += 1
            else:
                counts["error"] += 1
        except Exception:
            counts["error"] += 1
            f.s = None
        time.sleep(0.4)
    return counts


def fetch_pit_xml():
    """Download the per-filing XBRL XML listed in the nse_pit_gg* JSON files."""
    out = ROOT / "nse_pit_gg_xml"
    out.mkdir(parents=True, exist_ok=True)
    have = {p.name for p in out.glob("*.xml")}
    f = NseFetcher("nse_pit_gg", date.today(), date.today())
    counts = {"ok": 0, "error": 0, "skipped": 0}
    for folder in ("nse_pit_gg", "nse_pit_gg_sme"):
        for jf in sorted((ROOT / folder).glob("*.json")):
            for rec in json.loads(jf.read_text(encoding="utf-8")):
                url = rec.get("xmlFileName")
                if not url:
                    continue
                name = url.rsplit("/", 1)[-1]
                if name in have:
                    counts["skipped"] += 1
                    continue
                try:
                    body = f.get(url).content
                    if body.lstrip().startswith(b"<"):
                        (out / name).write_bytes(body)
                        have.add(name)
                        counts["ok"] += 1
                    else:
                        counts["error"] += 1
                except Exception:
                    counts["error"] += 1
                    f.s = None
                time.sleep(0.5)
    return counts


INTEGRATED_TYPE = "Integrated%20Filing-%20Financials"


def fetch_integrated_index():
    """Results filed as 'Integrated Filing - Financials' (SEBI format from the Mar-2025 quarter; the old
    corporates-financial-results feed has almost nothing after Feb 2025). One JSON per page of 500, newest first;
    every page is re-fetched (the list is small and revisions are inserted near the top). Fields: symbol, qe_Date,
    consolidated, audited, broadcast_Date / creation_Date (IST), type_Sub Original/Revision, xbrl URL."""
    counts = {}
    for idx in RESULT_INDICES:
        name = f"nse_integrated_{idx}"
        f = NseFetcher(name, date.today(), date.today())
        c = {"ok": 0, "error": 0, "rows": 0}
        page, total = 1, None
        while total is None or (page - 1) * 500 < total:
            for attempt in range(4):
                try:
                    j = f.get(f"{API}integrated-filing-results?index={idx}&type={INTEGRATED_TYPE}&page={page}&size=500").json()
                    total = int(j.get("totalCount") or 0)
                    data = j.get("data") or []
                    (f.dir / f"page_{page:03d}.json").write_text(json.dumps(data), encoding="utf-8")
                    c["ok"] += 1; c["rows"] += len(data)
                    break
                except Exception:
                    f.s = None
                    time.sleep(PACE_SEC * (2 ** (attempt + 1)))
            else:
                c["error"] += 1
                total = total or 0
            page += 1
            time.sleep(PACE_SEC)
        counts[name] = c
    return counts


def fetch_integrated_xbrl():
    """Download every XBRL listed in the integrated-filing index into nse_results_xbrl/ (same folder and parser)."""
    out = ROOT / "nse_results_xbrl"
    out.mkdir(parents=True, exist_ok=True)
    have = {p.name for p in out.iterdir()}
    urls = set()
    for idx in RESULT_INDICES:
        for jf in (ROOT / f"nse_integrated_{idx}").glob("*.json"):
            for rec in json.loads(jf.read_text(encoding="utf-8")):
                u = rec.get("xbrl")
                if u and u.startswith("http") and u.endswith(".xml") and u.rsplit("/", 1)[-1] not in have:
                    urls.add(u)
    f = NseFetcher("nse_results_xbrl", date.today(), date.today())
    counts = {"todo": len(urls), "ok": 0, "error": 0}
    for n, u in enumerate(sorted(urls), 1):
        try:
            body = f.get(u).content
            if body.lstrip()[:1] == b"<":
                (out / u.rsplit("/", 1)[-1]).write_bytes(body); counts["ok"] += 1
            else:
                counts["error"] += 1
        except Exception:
            f.s = None; counts["error"] += 1
        if n % 500 == 0:
            print(f"integrated xbrl {n}/{len(urls)} {counts}", flush=True)
        time.sleep(0.4)
    return counts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    names = [*MONTHLY, *DAILY_CSV, "nse_pit_gg_xml", "nse_results", "nse_results_xbrl", "nse_integrated", "nse_integrated_xbrl"]
    ap.add_argument("--datasets", default="all", help="comma list or 'all' (" + ",".join(names) + ")")
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat())
    # The historical deals/short CSV endpoint honours a from/to range (a whole year comes back
    # complete; checks cross-checked against the monthly sum), so a backfill does not need one
    # request per weekday. Monthly stays the default fetch granularity for the daily feeds.
    ap.add_argument("--window", default="day", choices=("day", "month", "year"),
                    help="window size for the daily CSV feeds (bulk/block/short)")
    args = ap.parse_args()
    wanted = names if args.datasets == "all" else args.datasets.split(",")
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)

    results, threads = {}, []
    # Two threads only: NSE throttles aggressively, so monthly APIs share one, daily CSVs the other.
    groups = [[n for n in wanted if n in MONTHLY], [n for n in wanted if n in DAILY_CSV]]

    def work(group):
        for n in group:
            results[n] = NseFetcher(n, start, end, args.window).run()

    for g in groups:
        if g:
            t = threading.Thread(target=work, args=(g,))
            t.start()
            threads.append(t)
    for t in threads:
        t.join()
    if "nse_pit_gg_xml" in wanted:
        results["nse_pit_gg_xml"] = fetch_pit_xml()
    if "nse_results" in wanted:
        results["nse_results"] = fetch_results_index(start, end)
    if "nse_results_xbrl" in wanted:
        results["nse_results_xbrl"] = fetch_results_xbrl()
    if "nse_integrated" in wanted:
        results["nse_integrated"] = fetch_integrated_index()
    if "nse_integrated_xbrl" in wanted:
        results["nse_integrated_xbrl"] = fetch_integrated_xbrl()
    for n in wanted:
        print(f"{n:12} {results.get(n)}")


if __name__ == "__main__":
    main()
