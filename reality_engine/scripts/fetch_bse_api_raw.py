"""
Raw BSE disclosure fetcher (download only, no DB writes).

Uses the shared BSE session from ``bse_client`` (curl_cffi browser TLS; plain
``requests`` gets HTTP 403 from api.bseindia.com) and writes one file per month
into ``reality_engine/data/raw_market/<dataset>/``.

Datasets:
  bse_bulk      Bulk deals    BulkDealData_ng/w?DealType=1  monthly JSON
  bse_block     Block deals   BulkDealData_ng/w?DealType=2  monthly JSON
  bse_insider   SEBI PIT disclosures (RTAPITDataDownload_ng CSV). Probed
                2026-10-06: populated 2019-01 .. 2022-12, header-only from
                2023 onward, so later months are recorded as empty.

Resumable via ``_manifest.csv``.

Usage:
    python -m reality_engine.scripts.fetch_bse_api_raw --datasets all
"""

import argparse
import csv
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from reality_engine.ingestion.bse_client import BSE_HEADERS, _module_session

ROOT = Path(__file__).resolve().parents[1] / "data" / "raw_market"
API = "https://api.bseindia.com/BseIndiaAPI/api/"
PACE_SEC = 1.5


def month_windows(start: date, end: date):
    d = start.replace(day=1)
    while d <= end:
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield max(d, start), min(nxt - timedelta(days=1), end)
        d = nxt


def url_for(name: str, a: date, b: date) -> str:
    if name == "bse_corpact":
        # Corporate actions (DefaultData, from bseindia.com/corporates/corporate_act); dates YYYYMMDD.
        return (f"{API}DefaultData/w?scripcode=&Fdate={a:%Y%m%d}&Purposecode=&TDate={b:%Y%m%d}"
                "&ddlcategorys=E&ddlindustrys=&segment=0&strSearch=S")
    if name in ("bse_bulk", "bse_block"):
        deal_type = 1 if name == "bse_bulk" else 2
        return f"{API}BulkDealData_ng/w?DealType={deal_type}&sc_code=&FDate={a:%d/%m/%Y}&TDate={b:%d/%m/%Y}"
    return f"{API}RTAPITDataDownload_ng/w?COMPANYSEARCH=&FROMDATE={a:%Y/%m/%d}&TODATE={b:%Y/%m/%d}&SCRIPCODE="


def run(name: str, start: date, end: date):
    out = ROOT / name
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "_manifest.csv"
    done = {}
    if manifest.exists():
        with manifest.open(newline="") as f:
            done = {r["window"]: r["status"] for r in csv.DictReader(f)}
    s = _module_session()
    counts = {"ok": 0, "empty": 0, "error": 0, "skipped": 0}
    for a, b in month_windows(start, end):
        key = f"{a.isoformat()}_{b.isoformat()}"
        if done.get(key) in ("ok", "empty"):
            counts["skipped"] += 1
            continue
        status, rows = "error", 0
        for attempt in range(3):
            try:
                r = s.get(url_for(name, a, b), headers=BSE_HEADERS, timeout=120)
                if r.status_code != 200:
                    raise ValueError(r.status_code)
                if name == "bse_insider":
                    rows = max(r.content.count(b"\n"), 0)
                    if rows:
                        (out / f"{key}.csv").write_bytes(r.content)
                else:
                    payload = r.json()
                    data = payload if isinstance(payload, list) else (payload.get("Table") or [])
                    rows = len(data)
                    if rows:
                        (out / f"{key}.json").write_text(json.dumps(data), encoding="utf-8")
                status = "ok" if rows else "empty"
                break
            except Exception:
                time.sleep(PACE_SEC * (2 ** (attempt + 1)))
        new = not manifest.exists()
        with manifest.open("a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["window", "status", "rows", "fetched_at"])
            w.writerow([key, status, rows, datetime.now().isoformat(timespec="seconds")])
        counts[status] += 1
        time.sleep(PACE_SEC)
    return counts


def run_index(start: date, end: date):
    """Daily OHLC + PE/PB/yield for every BSE index, one JSON per index per year.

    The index list comes from FillddlIndex (the dropdown on bseindia.com/indices/IndexArchiveData);
    history from IndexArchDailyPAR with dd/mm/yyyy dates.
    """
    out = ROOT / "bse_index"
    out.mkdir(parents=True, exist_ok=True)
    s = _module_session()
    listing = s.get(f"{API}FillddlIndex/w?fmdt=&todt=", headers=BSE_HEADERS, timeout=60).json()
    # 149 indices on 2026-10-08. Codes can carry trailing spaces ("IPO   "); the API wants them stripped.
    codes = sorted({(r.get("Indx_cd") or "").strip() for r in (listing.get("Table") or [])} - {""})
    (out / "_index_list.json").write_text(json.dumps(listing.get("Table") or []), encoding="utf-8")
    counts = {"indices": len(codes), "ok": 0, "empty": 0, "error": 0, "skipped": 0}
    for code in codes:
        for year in range(start.year, end.year + 1):
            a, b = max(date(year, 1, 1), start), min(date(year, 12, 31), end)
            path = out / f"{code.replace(' ', '_')}_{year}.json"
            if path.exists() and year < end.year:
                counts["skipped"] += 1
                continue
            try:
                r = s.get(f"{API}IndexArchDailyPAR/w?fmdt={a:%d/%m/%Y}&index={code}&period=D&todt={b:%d/%m/%Y}",
                          headers=BSE_HEADERS, timeout=120)
                rows = r.json().get("Table") or []
                if rows:
                    path.write_text(json.dumps(rows), encoding="utf-8")
                    counts["ok"] += 1
                else:
                    counts["empty"] += 1
            except Exception:
                counts["error"] += 1
            time.sleep(PACE_SEC)
    return counts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    names = ["bse_bulk", "bse_block", "bse_insider", "bse_index", "bse_corpact"]
    ap.add_argument("--datasets", default="all", help="comma list or 'all' (" + ",".join(names) + ")")
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat())
    args = ap.parse_args()
    wanted = names if args.datasets == "all" else args.datasets.split(",")
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    for n in wanted:
        res = run_index(start, end) if n == "bse_index" else run(n, start, end)
        print(f"{n:12} {res}", flush=True)


if __name__ == "__main__":
    main()
