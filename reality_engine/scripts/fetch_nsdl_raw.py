"""
Raw NSDL FPI report fetcher (download only, no DB writes).

Saves HTML pages from fpi.nsdl.co.in into ``reality_engine/data/raw_market/<dataset>/``:

  nsdl_fpi_daily       Daily FPI flows (equity / debt / debt-VRR / hybrid, by route).
                       The Archive form returns every day of the month up to the
                       chosen date, so one request per month-end covers a month.
  nsdl_fpi_fortnight   Fortnightly sector-wise FPI holdings (AUC) and net flows.
                       Static HTML per fortnight, listed on FPI_Fortnightly_Selection.aspx.
  nsdl_reports         One-shot pages that carry their own history: FPI AUC
                       country-wise, AUC category-wise, custodian AUC by category,
                       ODI / P-note values, calendar / financial-year and quarterly
                       FPI totals.
  nsdl_limits          Current snapshot only (no history is published): aggregate
                       foreign-investment limits per listed company, red-flag list,
                       breach list. Saved with today's date so repeated runs build
                       a history going forward.

Resumable via ``_manifest.csv`` for the daily and fortnightly sets.

Usage:
    python -m reality_engine.scripts.fetch_nsdl_raw --datasets all
"""

import argparse
import csv
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1] / "data" / "raw_market"
BASE = "https://www.fpi.nsdl.co.in/web/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
PACE_SEC = 2.0

ONE_SHOT_REPORTS = {
    "auc_country_top10": "Reports/ReportDetail.aspx?RepID=14",
    "auc_category": "Reports/ReportDetail.aspx?RepID=18",
    "auc_custodian_category": "Reports/ReportDetail.aspx?RepID=22",
    "odi_pnotes": "Reports/ReportDetail.aspx?RepID=28",
    "fpi_calendar_year": "Reports/Yearwise.aspx?RptType=6",
    "fpi_financial_year": "Reports/Yearwise.aspx?RptType=5",
    "fpi_quarterly": "Reports/QuarterlyWise.aspx",
}
LIMIT_PAGES = {
    "limits_all_companies": "Reports/Film_List_All.aspx",
    "red_flag_list": "Reports/frmRedFlagList.aspx",
    "breach_list": "Reports/frmThresholdlist.aspx",
}


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    return s


def hidden_fields(html: str) -> dict:
    return dict(re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', html))


class Manifest:
    def __init__(self, folder: Path):
        self.path = folder / "_manifest.csv"
        self.done = {}
        if self.path.exists():
            with self.path.open(newline="") as f:
                self.done = {r["key"]: r["status"] for r in csv.DictReader(f)}

    def record(self, key: str, status: str, nbytes: int):
        new = not self.path.exists()
        with self.path.open("a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["key", "status", "bytes", "fetched_at"])
            w.writerow([key, status, nbytes, datetime.now().isoformat(timespec="seconds")])


def fetch_daily(start: date, end: date):
    out = ROOT / "nsdl_fpi_daily"
    out.mkdir(parents=True, exist_ok=True)
    m = Manifest(out)
    s = session()
    url = BASE + "Reports/Archive.aspx"
    counts = {"ok": 0, "error": 0, "skipped": 0}
    d = start.replace(day=1)
    while d <= end:
        month_end = min((d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1), end)
        key = f"{month_end:%Y-%m}"
        # The current (possibly partial) month is always refetched.
        if m.done.get(key) == "ok" and month_end < end:
            counts["skipped"] += 1
        else:
            status, body = "error", ""
            for attempt in range(3):
                try:
                    form = hidden_fields(s.get(url, timeout=60).text)
                    label = f"{month_end:%d-%b-%Y}"
                    form.update({"txtDate": label, "hdnDate": label, "__EVENTTARGET": "btnSubmit1"})
                    body = s.post(url, data=form, timeout=90, headers={"Referer": url}).text
                    status = "ok" if "Investment Route" in body else "error"
                    break
                except Exception:
                    time.sleep(PACE_SEC * (2 ** (attempt + 1)))
            if status == "ok":
                (out / f"fpi_daily_{key}.html").write_text(body, encoding="utf-8")
            m.record(key, status, len(body))
            counts[status] += 1
            time.sleep(PACE_SEC)
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return counts


def fetch_fortnightly(start: date):
    out = ROOT / "nsdl_fpi_fortnight"
    out.mkdir(parents=True, exist_ok=True)
    m = Manifest(out)
    s = session()
    page = s.get(BASE + "Reports/FPI_Fortnightly_Selection.aspx", timeout=60).text
    options = re.findall(r'<option[^>]*value="(~/StaticReports/[^"]+)"[^>]*>([^<]*)', page)
    counts = {"ok": 0, "error": 0, "skipped": 0, "before_start": 0}
    for path, label in options:
        try:
            when = datetime.strptime(re.sub(r"\s+", " ", label.strip()).title(), "%b %d, %Y").date()
        except ValueError:
            try:
                when = datetime.strptime(re.sub(r"\s+", " ", label.strip()), "%B %d, %Y").date()
            except ValueError:
                when = None
        if when and when < start:
            counts["before_start"] += 1
            continue
        key = path.rsplit("/", 1)[-1]
        if m.done.get(key) == "ok":
            counts["skipped"] += 1
            continue
        status, body = "error", b""
        try:
            body = s.get(BASE + path[2:], timeout=90).content
            status = "ok" if len(body) > 5000 else "error"
        except Exception:
            pass
        if status == "ok":
            (out / key).write_bytes(body)
        m.record(key, status, len(body))
        counts[status] += 1
        time.sleep(PACE_SEC)
    return counts


def fetch_pages(folder: str, pages: dict, dated: bool):
    out = ROOT / folder
    out.mkdir(parents=True, exist_ok=True)
    s = session()
    stamp = f"_{date.today():%Y-%m-%d}" if dated else ""
    counts = {"ok": 0, "error": 0}
    for name, path in pages.items():
        try:
            body = s.get(BASE + path, timeout=120).content
            (out / f"{name}{stamp}.html").write_bytes(body)
            counts["ok"] += 1
        except Exception:
            counts["error"] += 1
        time.sleep(PACE_SEC)
    return counts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    names = ["nsdl_fpi_daily", "nsdl_fpi_fortnight", "nsdl_reports", "nsdl_limits"]
    ap.add_argument("--datasets", default="all", help="comma list or 'all' (" + ",".join(names) + ")")
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat())
    args = ap.parse_args()
    wanted = names if args.datasets == "all" else args.datasets.split(",")
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    for n in wanted:
        if n == "nsdl_fpi_daily":
            res = fetch_daily(start, end)
        elif n == "nsdl_fpi_fortnight":
            res = fetch_fortnightly(start)
        elif n == "nsdl_reports":
            res = fetch_pages("nsdl_reports", ONE_SHOT_REPORTS, dated=True)
        else:
            res = fetch_pages("nsdl_limits", LIMIT_PAGES, dated=True)
        print(f"{n:20} {res}", flush=True)


if __name__ == "__main__":
    main()
