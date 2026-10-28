"""Commodity series fetcher for the G12 gap (free, official, no login, no API key).

Why: ``COVERAGE.md`` §3 ranks ``commodity_price_daily`` second by marginal
cases (62) and ``SCHEMA_V3.sql`` §D says the 13 series held in
``mkt_commodity_daily`` carry **no ``known_at``**, so they cannot be used as
point-in-time evidence. This script fetches the missing series from sources
that publish them for free, and stamps each row with the source's own
publication time.

Sources
-------
``pink``  World Bank "Monthly Prices" (CMO pink sheet): crude (avg/Brent/WTI),
          natural gas (US/Europe), coal (Australia/South Africa), LME metals
          (aluminium, copper, lead, nickel, tin, zinc), iron ore, gold, silver,
          platinum, cotton, rubber, palm/soybean oil, urea, DAP.
          ``known_at`` = the workbook's own ``Updated on <date>`` cell, parsed
          by ``reality_engine.processing.factor_loaders`` (reused, not rewritten).
          No stamp -> the load is REFUSED rather than dated today.
``fred``  FRED public CSV (``/graph/fredgraph.csv?id=``, no key): daily Brent,
          WTI, Henry Hub and the H.10 USD/INR. ``known_at`` = the series'
          documented release lag (energy series next business day; H.10 the
          Monday after the observation week), ``pit_conf`` 0.85 because FRED
          serves the latest vintage, not an as-first-published snapshot.
``rbi``   RBI reference rate archive (same-day publication ~13:00 IST), one
          POST per calendar month, ``known_at`` = observation day 13:00 IST.

Deliberately not fetched
------------------------
MCX bhavcopy: its only public endpoint is a POST-only ASP.NET grid page, so
the row contract cannot be verified offline; and every MCX contract it would
add (INR gold/silver/crude/cotton) is already derivable as the World Bank USD
series times the RBI USDINR rate. Domestic HRC, pet coke, soda ash, pulp and
ammonia are paid (ICIS/ChemAnalyst) and stay NOT IN DATA.

Usage:
    python -m reality_engine.scripts.fetch_commodity_series --dry-run
    python -m reality_engine.scripts.fetch_commodity_series --sources pink,fred,rbi
    python -m reality_engine.scripts.fetch_commodity_series --pink-file sheet.xlsx
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from reality_engine.processing.factor_loaders import (
    WB_LANDING_URL,
    parse_world_bank_pink_sheet,
    resolve_pink_sheet_url,
)

DEFAULT_OUT = r"D:\RealityEngine\raw\commodity_series"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
PACE_SEC = 1.0
CSV_COLUMNS = ("series_code", "date", "close", "unit", "known_at", "pit_conf", "source")

#: G12 series the master bank asks for, as (series_code, Pink Sheet header).
#: Matched by normalised header text (``'Iron ore, cfr spot'`` ->
#: ``'iron_ore_cfr_spot'``), never by column letter: the sheet reorders columns.
PINK_MATCHERS = (
    ("wb_crude_avg", "crude_oil_average"),
    ("wb_crude_brent", "crude_oil_brent"),
    ("wb_crude_wti", "crude_oil_wti"),
    ("wb_natgas_us", "natural_gas_us"),
    ("wb_natgas_eu", "natural_gas_europe"),
    ("wb_coal_aus", "coal_australian"),
    ("wb_coal_sa", "coal_south_african"),
    ("wb_aluminium", "aluminium"),
    ("wb_copper", "copper"),
    ("wb_lead", "lead"),
    ("wb_nickel", "nickel"),
    ("wb_tin", "tin"),
    ("wb_zinc", "zinc"),
    ("wb_iron_ore", "iron_ore_cfr_spot"),
    ("wb_gold", "gold"),
    ("wb_silver", "silver"),
    ("wb_platinum", "platinum"),
    ("wb_cotton_a", "cotton_a_index"),
    ("wb_rubber", "rubber_rss3"),
    ("wb_palm_oil", "palm_oil"),
    ("wb_soybean_oil", "soybean_oil"),
    ("wb_urea", "urea"),
    ("wb_dap", "dap"),
    ("wb_steel_hrc", "steel"),
)

#: FRED series id -> (series_code, unit, release lag in days, pit_conf).
FRED_SERIES = {
    "DCOILBRENTEU": ("fred_crude_brent_d", "usd_per_bbl", 1, 0.85),
    "DCOILWTICO": ("fred_crude_wti_d", "usd_per_bbl", 1, 0.85),
    "DHHNGSP": ("fred_natgas_hh_d", "usd_per_mmbtu", 1, 0.85),
    "DEXINUS": ("fred_usdinr_d", "inr_per_usd", 3, 0.85),
}
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
FRED_SOURCE = "vendor:fred_csv"

RBI_URL = "https://rbi.org.in/Scripts/ReferenceRateArchive.aspx"
RBI_SERIES = ("rbi_usdinr", "inr_per_usd")
RBI_SOURCE = "vendor:rbi_reference_rate"
RBI_PUBLISH_TIME = "13:00:00+05:30"      # the daily rate is up by ~13:00 IST


# ---------------------------------------------------------------------------
# HTTP (stdlib): one request, browser-shaped, no cookies needed
# ---------------------------------------------------------------------------
def http_get(url: str, timeout: int = 120, referer: str = "") -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_post(url: str, form: dict, timeout: int = 120) -> bytes:
    body = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"User-Agent": USER_AGENT, "Referer": url,
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# Parsers — pure functions of bytes, so they are testable offline
# ---------------------------------------------------------------------------
def pink_rows(parsed: dict) -> list[dict]:
    """Pink Sheet parse result -> tidy rows stamped with the workbook's own date."""
    as_of = parsed.get("as_of_date")
    if parsed.get("status") != "ok" or not as_of:
        return []
    units = parsed.get("units") or {}
    rows = []
    for row in parsed.get("rows") or []:
        for code, value in (row.get("values") or {}).items():
            if value is None:
                continue
            rows.append({"series_code": code, "date": row["period_end"],
                         "close": value, "unit": (units.get(code) or "").strip(),
                         "known_at": as_of, "pit_conf": 1.0, "source": "worldbank_pink_sheet"})
    return rows


def next_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def parse_fred_csv(payload: bytes, series_id: str) -> list[tuple[str, float]]:
    """FRED ``observation_date,<ID>`` CSV -> [(iso_date, value)]; ``.`` is missing."""
    text = payload.decode("utf-8-sig", "replace")
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or len(header) < 2:
        return []
    out = []
    for row in reader:
        if len(row) < 2:
            continue
        d, raw = row[0].strip(), row[1].strip()
        if not d or raw in {"", "."}:
            continue
        try:
            out.append((d[:10], float(raw)))
        except ValueError:
            continue
    return out


def fred_rows(payload: bytes, series_id: str) -> list[dict]:
    code, unit, lag, pit = FRED_SERIES[series_id]
    rows = []
    for d, value in parse_fred_csv(payload, series_id):
        try:
            known = next_weekday(date.fromisoformat(d) + timedelta(days=lag))
        except ValueError:
            continue
        rows.append({"series_code": code, "date": d, "close": value, "unit": unit,
                     "known_at": known.isoformat(), "pit_conf": pit,
                     "source": FRED_SOURCE})
    return rows


_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_DMY_RE = re.compile(r"(\d{2})[/.-](\d{2})[/.-](\d{4})")


def _cell_text(raw: str) -> str:
    return _TAG_RE.sub(" ", raw).replace("&nbsp;", " ").strip()


def parse_rbi_reference_rate(html: str) -> list[tuple[str, float]]:
    """RBI archive page -> [(iso_date, inr_per_usd)].

    Deliberately dumb: the archive is one HTML table whose first cell is the
    date (DD/MM/YYYY) and whose second numeric cell is the USD/INR reference
    rate. A layout change yields ``[]`` (loud), never a guessed number.
    """
    out = []
    for chunk in re.split(r"(?i)<tr", html or ""):
        cells = [_cell_text(c) for c in _CELL_RE.findall(chunk)]
        if len(cells) < 2:
            continue
        m = _DMY_RE.search(cells[0])
        if not m:
            continue
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        for cell in cells[1:]:
            try:
                value = float(cell.replace(",", ""))
            except ValueError:
                continue
            if 40.0 < value < 150.0:          # a plausible INR-per-USD level
                out.append((f"{yyyy}-{mm}-{dd}", value))
                break
    return out


def rbi_rows(payload: bytes) -> list[dict]:
    code, unit = RBI_SERIES
    return [{"series_code": code, "date": d, "close": v, "unit": unit,
             "known_at": f"{d}T{RBI_PUBLISH_TIME}", "pit_conf": 1.0, "source": RBI_SOURCE}
            for d, v in parse_rbi_reference_rate(payload.decode("utf-8", "replace"))]


# ---------------------------------------------------------------------------
# Source runners — write the raw payload (audit copy) and return tidy rows
# ---------------------------------------------------------------------------
def fetch_pink(out: Path, from_file: str = "") -> tuple[list[dict], dict]:
    if from_file:
        payload = Path(from_file).read_bytes()
        url = f"file:{from_file}"
    else:
        html = http_get(WB_LANDING_URL, timeout=60).decode("utf-8", "replace")
        url = resolve_pink_sheet_url(html, WB_LANDING_URL)
        if not url:
            return [], {"status": "failed", "reason": "no CMO-Historical-Data-Monthly.xlsx link"}
        payload = http_get(url, timeout=240, referer=WB_LANDING_URL)
    parsed = parse_world_bank_pink_sheet(payload, matchers=PINK_MATCHERS)
    if parsed.get("status") == "ok" and not parsed.get("as_of_date"):
        parsed["status"] = "refused"
        parsed["reason"] = ("workbook carries no 'Updated on <date>' stamp; "
                            "known_at is unknown and today is never substituted")
    if parsed.get("status") == "ok":
        (out / f"worldbank_pink_sheet_{parsed['as_of_date']}.xlsx").write_bytes(payload)
    info = {"status": parsed.get("status"), "reason": parsed.get("reason"),
            "as_of_date": parsed.get("as_of_date"), "url": url,
            "series_matched": len(parsed.get("column_map") or {}),
            "rows": len(parsed.get("rows") or [])}
    return pink_rows(parsed), info


def fetch_fred(out: Path) -> tuple[list[dict], dict]:
    rows, info = [], {}
    for sid in FRED_SERIES:
        try:
            payload = http_get(FRED_URL.format(sid=sid), timeout=120)
        except Exception as exc:                                  # noqa: BLE001
            info[sid] = {"status": "failed", "reason": str(exc)[:200]}
            continue
        (out / f"fred_{sid}.csv").write_bytes(payload)
        got = fred_rows(payload, sid)
        rows += got
        info[sid] = {"status": "ok" if got else "failed", "rows": len(got)}
        time.sleep(PACE_SEC)
    return rows, info


def month_starts(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        first = date(y, m, 1)
        last = (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)
        yield max(first, start), min(last, end)
        y, m = y + (m == 12), m % 12 + 1


def rbi_month_form(html: str, first: date, last: date) -> dict:
    """The archive's ASP.NET form: every hidden field, the dates, the submit."""
    form = dict(re.findall(
        r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html, re.I))
    form.setdefault("__EVENTTARGET", "")
    form.setdefault("__EVENTARGUMENT", "")
    form.update({
        "txtFromDate": f"{first:%d/%m/%Y}",
        "txtToDate": f"{last:%d/%m/%Y}",
        "btnSubmit": "Submit",
    })
    return form


def fetch_rbi(out: Path, start: date, end: date) -> tuple[list[dict], dict]:
    rows, info = [], {"months": 0, "failed": 0, "rows": 0}
    try:
        shell = http_get(RBI_URL, timeout=60).decode("utf-8", "replace")
    except Exception as exc:                                      # noqa: BLE001
        return [], {"status": "failed", "reason": str(exc)[:200]}
    for first, last in month_starts(start, end):
        target = out / f"rbi_reference_rate_{first:%Y-%m}.html"
        info["months"] += 1
        if target.exists():
            payload = target.read_bytes()
        else:
            try:
                payload = http_post(RBI_URL, rbi_month_form(shell, first, last), timeout=90)
            except Exception as exc:                              # noqa: BLE001
                info["failed"] += 1
                print(f"  rbi {first:%Y-%m} failed: {exc}")
                continue
            target.write_bytes(payload)
            time.sleep(PACE_SEC)
        got = rbi_rows(payload)
        if not got:
            print(f"  rbi {first:%Y-%m}: 0 rows (form/layout drift?)")
            info["failed"] += 1
        rows += got
        info["rows"] += len(got)
    return rows, info


# ---------------------------------------------------------------------------
# Output + plan
# ---------------------------------------------------------------------------
def write_series(out: Path, rows: list[dict], start: str = "", end: str = "") -> int:
    keep = [r for r in rows if (not start or r["date"] >= start) and (not end or r["date"] <= end)]
    keep.sort(key=lambda r: (r["series_code"], r["date"]))
    with (out / "commodity_series.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(keep)
    codes = sorted({r["series_code"] for r in keep})
    with (out / "_manifest.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["series_code", "rows", "min_date", "max_date", "known_at_min", "known_at_max"])
        for code in codes:
            rs = [r for r in keep if r["series_code"] == code]
            w.writerow([code, len(rs), min(r["date"] for r in rs), max(r["date"] for r in rs),
                        min(r["known_at"] for r in rs), max(r["known_at"] for r in rs)])
    return len(keep)


def plan(sources: tuple[str, ...], start: date, end: date) -> dict:
    months = sum(1 for _ in month_starts(start, end))
    requests = (2 if "pink" in sources else 0) + (len(FRED_SERIES) if "fred" in sources else 0) \
        + (months if "rbi" in sources else 0)
    return {
        "series_needed_pink": len(PINK_MATCHERS),
        "requests": requests,
        "max_requests": requests + 2 * (len(sources) - 1),   # one retry per source
        "est_minutes_p50": round(requests * (PACE_SEC + 1.0) / 60, 1),
        "est_minutes_p95": round(requests * (PACE_SEC + 6.0) / 60, 1),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", default="pink,fred,rbi")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--from", dest="start", default="2000-01-01")
    ap.add_argument("--to", dest="end", default=date.today().isoformat())
    ap.add_argument("--pink-file", default="",
                    help="parse an already-downloaded pink sheet xlsx instead of fetching it")
    ap.add_argument("--dry-run", action="store_true", help="plan only: no network, no writes")
    args = ap.parse_args(argv)

    sources = tuple(s.strip() for s in args.sources.split(",") if s.strip())
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    out = Path(args.out)

    for k, v in plan(sources, start, end).items():
        print(f"  {k:20} {v}")
    if args.dry_run:
        print("dry-run: no request made")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    if "pink" in sources:
        got, info = fetch_pink(out, args.pink_file)
        print(f"pink: {info}")
        rows += got
    if "fred" in sources:
        got, info = fetch_fred(out)
        print(f"fred: {info}")
        rows += got
    if "rbi" in sources:
        got, info = fetch_rbi(out, start, end)
        print(f"rbi:  {info}")
        rows += got

    written = write_series(out, rows, args.start, args.end)
    codes = sorted({r["series_code"] for r in rows})
    print(f"wrote {written} rows, {len(codes)} series -> {out / 'commodity_series.csv'}")
    print(f"  {codes}")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
