"""NSE F&O daily bhavcopy fetcher + tidy parser (download only, no DB writes).

The schema's ``fno_oi_daily`` (tasks/arch_v3/SCHEMA_V3.sql §C) says its source
is the NSE F&O bhavcopy and that the file is "not held -> needs_new_fetch".
This script fetches it: one zip per session, 2019-01-01 to today, into
``--out`` (default ``D:\\RealityEngine\\raw\\fo_bhavcopy``).

Two eras, both from ``nsearchives.nseindia.com`` (free, no login):

  legacy  ``/content/historical/DERIVATIVES/<YYYY>/<MMM>/fo<DD><MMM><YYYY>bhav.csv.zip``
          2019-01-01 .. 2024-07-05, columns INSTRUMENT..TIMESTAMP
  UDiFF   ``/content/fo/BhavCopy_NSE_FO_0_0_0_<YYYYMMDD>_F_0000.csv.zip``
          from 2024-07-08, columns TradDt..Rsvd06

Both are parsed by :func:`parse_fo_bhavcopy` into one tidy row per contract:
date, symbol, instrument, expiry, strike, option type, OHLC, settle, OI, change
in OI, contracts, value in rupees, ISIN (UDiFF only).

Resumable and polite: ``_manifest.csv`` records each session, ``--interval``
paces requests (default 0.4 s; NSE took 400/min bursts unblocked in the 2026-10
probes), 403/429/503 back off with Retry-After and re-warm the cookie session
via ``reality_engine.ingestion.nse_client.NSEClient``. ``--dry-run`` plans the
run without a single network call.

Usage:
    python -m reality_engine.scripts.fetch_fo_bhavcopy --dry-run
    python -m reality_engine.scripts.fetch_fo_bhavcopy --from 2019-01-01 --to 2026-10-24
    python -m reality_engine.scripts.fetch_fo_bhavcopy --parse-only
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from reality_engine.config import NSE_HEADERS

DEFAULT_OUT = r"D:\RealityEngine\raw\fo_bhavcopy"
LEGACY_END = date(2024, 7, 5)          # last session served in the old column layout
UDIFF_FROM = date(2024, 7, 8)          # first UDiFF F&O file
BLOCK_STATUS = {403, 429, 503}
REWARM_EVERY = 200                     # sessions between cookie warm-ups
MAX_ATTEMPTS = 5

TIDY_COLUMNS = ("date", "symbol", "instrument", "expiry", "strike", "option_type",
                "open", "high", "low", "close", "settle", "oi", "oi_change",
                "contracts", "value_inr", "isin")

#: Exchange file column -> tidy column. The legacy file carries value in lakh.
LEGACY_COLS = {
    "INSTRUMENT": "instrument", "SYMBOL": "symbol", "EXPIRY_DT": "expiry",
    "STRIKE_PR": "strike", "OPTION_TYP": "option_type", "OPEN": "open",
    "HIGH": "high", "LOW": "low", "CLOSE": "close", "SETTLE_PR": "settle",
    "CONTRACTS": "contracts", "VAL_INLAKH": "value_lakh", "OPEN_INT": "oi",
    "CHG_IN_OI": "oi_change",
}
UDIFF_COLS = {
    "TckrSymb": "symbol", "FinInstrmTp": "instrument", "XpryDt": "expiry",
    "StrkPric": "strike", "OptnTp": "option_type", "OpnPric": "open",
    "HghPric": "high", "LwPric": "low", "ClsPric": "close", "SttlmPric": "settle",
    "OpnIntrst": "oi", "ChngInOpnIntrst": "oi_change", "TtlTradgVol": "contracts",
    "TtlTrfVal": "value_inr", "ISIN": "isin",
}
_NUMERIC = ("strike", "open", "high", "low", "close", "settle", "oi", "oi_change",
            "contracts", "value_lakh", "value_inr")
_MONTHS = {m: i for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


def weekdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def sessions(start: date, end: date, only=None):
    """Weekdays in the window, or exactly the sessions in ``only``."""
    return sorted(set(only)) if only else list(weekdays(start, end))


def fo_filename(d: date) -> str:
    """Exchange filename for the session (UDiFF after 2024-07-08, else legacy)."""
    if d >= UDIFF_FROM:
        return f"BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    return f"fo{d:%d}{d:%b}{d:%Y}bhav.csv.zip".replace(f"{d:%b}", f"{d:%b}".upper())


def fo_url(d: date) -> str:
    if d >= UDIFF_FROM:
        return "https://nsearchives.nseindia.com/content/fo/" + fo_filename(d)
    mon = f"{d:%b}".upper()
    return (f"https://nsearchives.nseindia.com/content/historical/DERIVATIVES/"
            f"{d:%Y}/{mon}/fo{d:%d}{mon}{d:%Y}bhav.csv.zip")


def normalise_expiry(raw: str) -> str:
    """``31-Jan-2019`` / ``2019-01-31`` -> ``2019-01-31``; unknown unchanged."""
    s = (raw or "").strip()
    if not s:
        return ""
    if len(s) == 11 and s[2] == "-" and s[6] == "-":
        mon = _MONTHS.get(s[3:6].upper())
        if mon:
            return f"{int(s[7:11]):04d}-{mon:02d}-{int(s[0:2]):02d}"
    return s


def normalise_option_type(raw: str) -> str:
    """Legacy files write ``XX`` for a future and ``CA``/``PA`` for options."""
    s = (raw or "").strip().upper()
    return {"XX": "FUT", "CA": "CE", "PA": "PE", "": "FUT"}.get(s, s)


def _num(raw, scale: float = 1.0):
    s = (raw or "").strip().replace(",", "")
    if not s or s in {"-", "NA", "N/A"}:
        return None
    try:
        return float(s) * scale
    except ValueError:
        return None


def _csv_member(zf: zipfile.ZipFile) -> str:
    for name in zf.namelist():
        if name.lower().endswith(".csv"):
            return name
    raise ValueError(f"no .csv member in the archive ({zf.namelist()[:3]})")


def parse_fo_bhavcopy(payload: bytes, trade_date: str | None = None) -> list[dict]:
    """Parse one NSE F&O bhavcopy zip (legacy or UDiFF) into tidy contract rows.

    Pure function of the bytes: no clock, no network, no DB. A future layout
    change yields ``[]`` (loud) rather than plausible rows under wrong keys.
    """
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        text = zf.read(_csv_member(zf)).decode("utf-8-sig", "replace")
    reader = csv.DictReader(io.StringIO(text))
    fields = [f.strip() for f in (reader.fieldnames or [])]
    if not fields:
        return []
    cols = UDIFF_COLS if "TradDt" in fields else LEGACY_COLS if "INSTRUMENT" in fields else None
    if cols is None:
        return []
    missing = [c for c in cols if c not in fields]
    if missing:
        return []

    rows = []
    for raw in reader:
        out = {}
        for src_col, tidy_col in cols.items():
            if src_col in raw:
                out[tidy_col] = (raw.get(src_col) or "").strip()
        for key in _NUMERIC:
            if key in out:
                out[key] = _num(out[key])
        if out.get("value_lakh") is not None:          # lakh -> rupees
            out["value_inr"] = out.pop("value_lakh") * 100_000.0
        out["option_type"] = normalise_option_type(out.get("option_type", ""))
        out["expiry"] = normalise_expiry(out.get("expiry", ""))
        out["date"] = trade_date or (raw.get("TradDt") or "").strip()[:10] or None
        out.setdefault("isin", None)
        if not out.get("symbol"):
            continue
        rows.append({k: out.get(k) for k in TIDY_COLUMNS})
    return rows


def _valid_fo_zip(body: bytes) -> bool:
    if body[:4] != b"PK\x03\x04":
        return False
    try:
        return bool(parse_fo_bhavcopy(body))
    except (zipfile.BadZipFile, ValueError, KeyError):
        return False


class FoFetcher:
    """Paced, resumable daily-zip downloader for one exchange file family."""

    def __init__(self, out: Path, interval: float = 0.4, warmup: bool = True):
        self.dir = out
        self.interval = interval
        self.manifest = out / "_manifest.csv"
        self.done = self._read_manifest()
        self.counts = {"ok": 0, "missing": 0, "error": 0, "skipped": 0}
        self._client = None
        self._requests = 0
        if warmup:
            self._warm()

    def _warm(self):
        """Cookie warm-up through the repo's NSE client (TLS-impersonating)."""
        try:
            from reality_engine.ingestion.nse_client import NSEClient
            self._client = NSEClient()
            self._client._warmup_session()
            self._requests = 0
        except Exception as exc:                                  # noqa: BLE001
            print(f"  warm-up failed ({exc}); continuing without cookies", file=sys.stderr)
            self._client = None

    def _read_manifest(self) -> dict:
        if not self.manifest.exists():
            return {}
        with self.manifest.open(newline="") as f:
            return {r["date"]: r["status"] for r in csv.DictReader(f)}

    def _record(self, d: date, status: str, nbytes: int, url: str):
        new = not self.manifest.exists()
        with self.manifest.open("a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["date", "status", "bytes", "url", "fetched_at"])
            w.writerow([d.isoformat(), status, nbytes, url,
                        datetime.now().isoformat(timespec="seconds")])

    def _get(self, url: str):
        if self._client is not None and self._requests >= REWARM_EVERY:
            self._warm()
        self._requests += 1
        if self._client is None:
            import requests
            r = requests.get(url, headers=NSE_HEADERS, timeout=30)
        else:
            r = self._client.session.get(url, headers=NSE_HEADERS, timeout=30)
        return r

    def fetch_one(self, d: date) -> tuple[bytes, str, str]:
        """(body, status, url) for one session, with back-off on block statuses."""
        url = fo_url(d)
        body = b""
        for attempt in range(MAX_ATTEMPTS):
            try:
                r = self._get(url)
            except Exception as exc:                              # noqa: BLE001
                if attempt == MAX_ATTEMPTS - 1:
                    print(f"  {d} transport error: {exc}", file=sys.stderr)
                time.sleep(self.interval * (2 ** (attempt + 1)))
                continue
            if r.status_code in BLOCK_STATUS:
                retry_after = r.headers.get("Retry-After") if hasattr(r, "headers") else None
                wait = float(retry_after) if (retry_after or "").isdigit() else 5.0 * (attempt + 1)
                print(f"  {d} HTTP {r.status_code}; backing off {wait:.0f}s", file=sys.stderr)
                time.sleep(wait)
                if attempt >= 2:
                    self._warm()
                continue
            body = r.content
            break
        return body, ("ok" if _valid_fo_zip(body) else "missing"), url

    def run(self, dates):
        for d in dates:
            key = d.isoformat()
            if self.done.get(key) == "ok" or (
                    self.done.get(key) == "missing" and (date.today() - d).days > 3):
                self.counts["skipped"] += 1
                continue
            body, status, url = self.fetch_one(d)
            if status == "ok":
                (self.dir / fo_filename(d)).write_bytes(body)
            self._record(d, status, len(body), url)
            self.done[key] = status
            self.counts[status] += 1
            print(f"  {key} {status} {len(body)} B", flush=True)
            time.sleep(self.interval)
        return self.counts


def parse_only(out: Path) -> dict:
    """Re-parse every fetched zip into ``tidy/<date>.csv``; skip existing tidy files."""
    tidy = out / "tidy"
    tidy.mkdir(parents=True, exist_ok=True)
    manifest = out / "_manifest.csv"
    if not manifest.exists():
        return {"parsed": 0, "skipped": 0, "failed": 0}
    counts = {"parsed": 0, "skipped": 0, "failed": 0}
    with manifest.open(newline="") as f:
        for row in csv.DictReader(f):
            if row["status"] != "ok":
                continue
            d = date.fromisoformat(row["date"])
            target = tidy / f"{d.isoformat()}.csv"
            if target.exists():
                counts["skipped"] += 1
                continue
            src = out / fo_filename(d)
            if not src.exists():
                counts["failed"] += 1
                continue
            rows = parse_fo_bhavcopy(src.read_bytes(), d.isoformat())
            if not rows:
                counts["failed"] += 1
                continue
            with target.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=TIDY_COLUMNS)
                w.writeheader()
                w.writerows(rows)
            counts["parsed"] += 1
    return counts


def plan(start: date, end: date, out: Path, interval: float, only=None) -> dict:
    """Request count and wall-clock estimate for a run; touches nothing."""
    dates = sessions(start, end, only)
    manifest = out / "_manifest.csv"
    done = {}
    if manifest.exists():
        with manifest.open(newline="") as f:
            done = {r["date"]: r["status"] for r in csv.DictReader(f)}
    todo = [d for d in dates if done.get(d.isoformat()) != "ok"]
    return {
        "sessions": len(dates),
        "already_ok": len(dates) - len(todo),
        "requests": len(todo),
        "max_requests": len(todo) * MAX_ATTEMPTS,
        "est_minutes_p50": round(len(todo) * (interval + 0.30) / 60, 1),
        "est_minutes_p95": round(len(todo) * (interval + 1.50) / 60, 1),
        "legacy_files": sum(1 for d in todo if d <= LEGACY_END),
        "udiff_files": sum(1 for d in todo if d >= UDIFF_FROM),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", default="2019-01-01")
    ap.add_argument("--to", dest="end", default=date.today().isoformat())
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--interval", type=float, default=0.4,
                    help="seconds between requests (default 0.4 = 400/min bursts)")
    ap.add_argument("--dates", default="",
                    help="comma list of explicit sessions instead of the weekday range")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; no network, no writes")
    ap.add_argument("--parse-only", action="store_true",
                    help="parse already-fetched zips into tidy/ (no network)")
    args = ap.parse_args(argv)

    out = Path(args.out)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    only = [date.fromisoformat(d.strip()) for d in args.dates.split(",") if d.strip()]

    if args.parse_only:
        print(f"parse-only {out}: {parse_only(out)}")
        return 0

    stats = plan(start, end, out, args.interval, only)
    print(f"F&O bhavcopy -> {out}")
    for k, v in stats.items():
        print(f"  {k:18} {v}")
    if args.dry_run:
        print("dry-run: no request made")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    dates = sessions(start, end, only)
    counts = FoFetcher(out, interval=args.interval).run(dates)
    print(f"fetched: {counts}")
    print(f"parse:   {parse_only(out)}")
    return 0 if counts["error"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
