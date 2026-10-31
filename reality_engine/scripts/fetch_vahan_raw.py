"""Raw Vahan public-dashboard fetcher (download only, no DB writes).

The legacy VAHAN 4 dashboard (``vahan.parivahan.gov.in/vahan4dashboard``) no longer
serves a month-wise table: every Maker x "Month Wise" refresh answers with a
server-side ``javax.faces.el.EvaluationException: Not supported yet.`` and renders
no table (details in ``tasks/VAHAN_COVERAGE_2026-11-01.md``).

The public analytics dashboard (``analytics.parivahan.gov.in``) does serve it as
JSON, so this job reads those endpoints and saves the payloads unchanged::

    GET /analytics/publicdashboard/vahandashboard/top5Makerchart
        top-5 makers for the current filter (two-wheelers, EV fuels)
    GET /analytics/publicdashboard/vahandashboard/durationWiseRegistrationTable
        calendarType=3 -> one row per month ("2026-October") per filter
    GET /analytics/publicdashboard/lazy/vehicle-makers
        the full maker list (7,775 names; only with --all-makers)

Output under ``RAW_ROOT/vahan``:
    monthly_2w_ev/<maker>.json   one raw payload per maker
    top5_2w_ev.json              the maker list used by default
    monthly_2w_ev_by_maker.csv   combined tidy view (derived from the JSON files)
    _manifest.csv                one row per maker fetch

Usage::

    python -m reality_engine.scripts.fetch_vahan_raw            # dashboard top-5
    python -m reality_engine.scripts.fetch_vahan_raw --makers "OLA ELECTRIC TECHNOLOGIES PVT LTD"
    python -m reality_engine.scripts.fetch_vahan_raw --check    # consistency check
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime

import requests

from reality_engine.config import RAW_ROOT

ROOT = RAW_ROOT / "vahan"
MONTHLY_DIR = ROOT / "monthly_2w_ev"
TOP5_FILE = ROOT / "top5_2w_ev.json"
COMBINED = ROOT / "monthly_2w_ev_by_maker.csv"
MANIFEST = ROOT / "_manifest.csv"
MANIFEST_FIELDS = ["maker", "status", "months", "first_month", "last_month", "total",
                   "bytes", "seconds", "fetched_at", "error"]

SITE = "https://analytics.parivahan.gov.in"
PAGE = SITE + "/analytics/publicdashboard/vahan?lang=en"
TABLE = SITE + "/analytics/publicdashboard/vahandashboard/durationWiseRegistrationTable"
TOP5_API = SITE + "/analytics/publicdashboard/vahandashboard/top5Makerchart"
MAKERS_API = SITE + "/analytics/publicdashboard/lazy/vehicle-makers"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
HEADERS = {"X-Requested-With": "XMLHttpRequest", "Referer": PAGE,
           "Accept": "application/json, */*"}
# The dashboard's own Fuel filter, restricted to the EV codes. Both are needed:
# ELECTRIC(BOV) is the older code and carries pre-2023 registrations.
EV_FUELS = ("PURE EV", "ELECTRIC(BOV)")
FALLBACK_MAKERS = ("TVS MOTOR COMPANY LTD", "OLA ELECTRIC TECHNOLOGIES PVT LTD",
                   "BAJAJ AUTO LTD", "ATHER ENERGY LTD", "HERO MOTOCORP LTD")


def session():
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.get(PAGE, timeout=90)  # session cookie only; best effort
    return s


def call(s, url, params, tries=4, timeout=180):
    """(payload, seconds, error) - retries timeouts and 5xx/429 with backoff."""
    started, last = time.time(), None
    for attempt in range(tries):
        try:
            r = s.get(url, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r.json(), round(time.time() - started, 3), None
            last = f"HTTP {r.status_code}"
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(2 ** attempt * 5, 60))
                continue
            return None, round(time.time() - started, 3), last
        except Exception as exc:  # noqa: BLE001 - transient network
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(min(2 ** attempt * 5, 60))
    return None, round(time.time() - started, 3), last


def base_params(from_year, to_year):
    return {"stateCode": "", "rtoCode": "0", "fromYear": str(from_year),
            "toYear": str(to_year), "vehicleClasses": "", "vehicleSubCategories": "",
            "vehicleEmissions": "", "timePeriod": "2", "vehicleCategoryGroup": "Two Wheeler",
            "evType": "", "vehicleStatus": "", "vehicleOwnerType": "", "fitnessCheck": "0",
            "vehicleType": "", "calendarType": "3", "archiveTypeAC": "",
            "archiveTypeANC": "", "archiveTypePA": "", "archiveTypeTA": "",
            "archiveTypeNA": ""}


def monthly_params(maker, from_year, to_year):
    """The table endpoint takes the EV fuels as repeated ``vehicleFuels`` params."""
    params = list(base_params(from_year, to_year).items())
    params.append(("vehicleMakers", maker.upper()))
    params += [("vehicleFuels", fuel) for fuel in EV_FUELS]
    return params


def top5_params(from_year, to_year):
    params = dict(base_params(from_year, to_year), calendarType="", vehicleMakers="",
                  vehicleFuels=",".join(EV_FUELS))
    return list(params.items())


def months_of(payload):
    """[{month: 'YYYY-MM', registrations: int}] newest first; [] if not a list."""
    rows = []
    for item in payload or []:
        label = str((item or {}).get("yearAsString") or "")
        try:
            when = datetime.strptime(label, "%Y-%B").strftime("%Y-%m")
        except ValueError:
            continue
        rows.append({"month": when, "registrations": int(item.get("registeredVehicleCount") or 0)})
    return rows


def slug(maker):
    return re.sub(r"[^a-z0-9]+", "_", maker.lower()).strip("_")


def fetch_top5(s, from_year, to_year):
    payload, seconds, error = call(s, TOP5_API, top5_params(from_year, to_year))
    if payload:
        TOP5_FILE.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return payload or {}, seconds, error


def fetch_maker(s, maker, from_year, to_year, refresh=False):
    """Raw monthly payload for one maker, saved as-is. Skips a held file unless --refresh."""
    path = MONTHLY_DIR / f"{slug(maker)}.json"
    MONTHLY_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists() and not refresh:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload, 0.0, None
    payload, seconds, error = call(s, TABLE, monthly_params(maker, from_year, to_year))
    if payload is not None:
        path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return payload, seconds, error


def list_makers(s, size=1000):
    names, page = [], 0
    while page < 20:
        payload, _seconds, error = call(s, MAKERS_API, {"page": page, "size": size, "search": ""})
        if error or not payload:
            break
        names.extend(str(name) for name in payload)
        if len(payload) < size:
            break
        page += 1
    return names


def rebuild_combined():
    """maker, month, registrations for every held raw file (derived view)."""
    rows = []
    for path in sorted(MONTHLY_DIR.glob("*.json")):
        maker = path.stem.replace("_", " ").upper()
        for row in months_of(json.loads(path.read_text(encoding="utf-8"))):
            rows.append((maker, row["month"], row["registrations"]))
    rows.sort(key=lambda r: (r[0], r[1]))
    tmp = COMBINED.with_suffix(".csv.part")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["maker", "month", "registrations"])
        w.writerows(rows)
    tmp.replace(COMBINED)
    return len(rows)


def write_manifest(rows):
    with MANIFEST.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        w.writerows(rows)


def check():
    """Offline consistency check: parse every held file and match the top-5 totals."""
    files = sorted(MONTHLY_DIR.glob("*.json"))
    if not files:
        sys.exit("no raw Vahan files under " + str(MONTHLY_DIR))
    totals = {}
    sample = None
    for path in files:
        rows = months_of(json.loads(path.read_text(encoding="utf-8")))
        assert rows, f"{path.name}: no parseable months"
        assert all(re.fullmatch(r"\d{4}-\d{2}", r["month"]) for r in rows), path.name
        assert all(r["registrations"] >= 0 for r in rows), path.name
        assert rows[0]["month"] >= rows[-1]["month"], f"{path.name}: not newest first"
        totals[path.stem] = sum(r["registrations"] for r in rows)
        sample = sample or rows[0]
    top5 = json.loads(TOP5_FILE.read_text(encoding="utf-8")) if TOP5_FILE.exists() else {}
    matched = 0
    for label, total in zip(top5.get("labels") or [], (top5.get("datasets") or [{}])[0].get("data") or []):
        key = slug(label)
        if key in totals:
            assert totals[key] == int(total), f"{label}: monthly sum {totals[key]} != top5 {total}"
            matched += 1
    print(f"OK {len(files)} maker files, {matched} matched the top-5 totals; "
          f"sample {sample}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--makers", default="", help="comma list; default: dashboard top-5 EV two-wheeler makers")
    ap.add_argument("--all-makers", action="store_true",
                    help="query every maker in the dashboard list (7,775 names; slow)")
    ap.add_argument("--from-year", type=int, default=1982)
    ap.add_argument("--to-year", type=int, default=datetime.now().year)
    ap.add_argument("--interval", type=float, default=0.5, help="seconds between requests")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--refresh", action="store_true", help="re-fetch files already held")
    ap.add_argument("--check", action="store_true", help="offline consistency check only")
    args = ap.parse_args(argv)
    if args.check:
        return check()

    ROOT.mkdir(parents=True, exist_ok=True)
    s = session()
    top5, seconds, error = fetch_top5(s, args.from_year, args.to_year)
    if error:
        print(f"top-5 makers: {error}", file=sys.stderr)
    if args.makers:
        makers = [m.strip() for m in args.makers.split(",") if m.strip()]
    elif args.all_makers:
        makers = list_makers(s)
        print(f"maker list: {len(makers)} names")
    else:
        makers = [str(name).upper() for name in top5.get("labels") or []] or list(FALLBACK_MAKERS)
    if args.limit:
        makers = makers[:args.limit]

    rows = []
    for i, maker in enumerate(makers, 1):
        payload, seconds, error = fetch_maker(s, maker, args.from_year, args.to_year,
                                             refresh=args.refresh)
        months = months_of(payload) if payload is not None else []
        row = {"maker": maker, "status": "error" if error else "ok", "months": len(months),
               "first_month": months[-1]["month"] if months else "",
               "last_month": months[0]["month"] if months else "",
               "total": sum(m["registrations"] for m in months),
               "bytes": (MONTHLY_DIR / f"{slug(maker)}.json").stat().st_size
               if (MONTHLY_DIR / f"{slug(maker)}.json").exists() else 0,
               "seconds": seconds, "error": error or "",
               "fetched_at": datetime.now().isoformat(timespec="seconds")}
        rows.append(row)
        print(f"{i}/{len(makers)} {maker}: {row['status']} {len(months)} months "
              f"{row['first_month']}..{row['last_month']} total {row['total']} "
              f"({seconds:.2f}s) {error or ''}", flush=True)
        if i < len(makers):
            time.sleep(max(0.0, args.interval))

    write_manifest(rows)
    print(f"combined rows: {rebuild_combined()}")
    errors = [r for r in rows if r["status"] != "ok"]
    if errors:
        print(f"{len(errors)} maker(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
