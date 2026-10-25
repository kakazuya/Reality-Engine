"""
Raw market-data fetcher (download only, no DB writes).

Downloads daily exchange files and commodity series from 2019-01-01 into
``RAW_ROOT/raw_market/<source>/`` so they can be loaded into the DB
later under the single-writer queue lock. Raw files are kept as the audit /
replay copy (AGENTS.md rule 4).

Sources (one thread each, paced, resumable — an existing valid file is skipped):
  nse_cm     NSE CM bhavcopy (old format zip)          2019-01-01 .. 2021-10-31
  nse_mto    NSE security-wise delivery (MTO .DAT)      2019-01-01 .. 2021-10-31
  nse_full   NSE sec_bhavdata_full, all series + delivery (served from ~2019-10)
  nse_part_oi / nse_part_vol  participant-wise (Client/DII/FII/Pro) derivatives OI / volume
  nse_fii_stats              NSE daily FII derivative statistics (.xls)
  nse_sme    NSE Emerge (SME) bhavcopy                  2019-01-01 .. end
  nse_index  NSE all-index close                        2019-01-01 .. end
  bse_bhav   BSE bhavcopy (legacy zip <= 2024-06-30, UDiFF csv after)
  bse_deliv  BSE gross deliverables (SCBSEALL zip via form post)
  commod     Commodity futures + USDINR (yfinance), World Bank monthly pink sheet

Each source writes ``_manifest.csv`` (date, status, bytes). A weekday that
returns the exchange's error page is recorded as ``missing`` (usually a holiday).

Usage:
    python -m reality_engine.scripts.fetch_market_raw --sources all
    python -m reality_engine.scripts.fetch_market_raw --sources bse_deliv --start 2019-01-01 --end 2019-01-31
"""

import argparse
import csv
import io
import re
import threading
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from reality_engine.config import raw_dir

import requests

ROOT = raw_dir("raw_market")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
NSE_OLD_FORMAT_END = date(2021, 10, 31)   # DB already holds NSE full bhavcopy from 2021-10-27
BSE_LEGACY_END = date(2024, 6, 30)        # legacy zip served to at least 2024-07-01 (probed 2026-10-06)
BSE_DELIV_URL = "https://beta.bseindia.com/markets/equity/EQReports/GrossDeliverables.aspx"
PACE_SEC = 1.0

COMMODITY_TICKERS = {
    "GC=F": "gold", "SI=F": "silver", "HG=F": "copper", "ALI=F": "aluminium",
    "ZNC=F": "zinc", "PL=F": "platinum", "CL=F": "crude_wti", "BZ=F": "crude_brent",
    "NG=F": "natural_gas", "HRC=F": "steel_hrc_us", "TIO=F": "iron_ore_62",
    "MTF=F": "coal_newcastle", "INR=X": "usdinr",
}
WB_PINK_SHEET_URL = ("https://thedocs.worldbank.org/en/doc/18675f1d1639c7a34d463f59263ba0a2-"
                     "0050012025/related/CMO-Historical-Data-Monthly.xlsx")


def weekdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def session(referer: str = "") -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    if referer:
        s.headers["Referer"] = referer
    return s


class Source:
    """One paced, resumable daily-file downloader."""

    name = ""
    referer = ""

    def __init__(self, start: date, end: date):
        self.start, self.end = start, end
        self.dir = ROOT / self.name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest = self.dir / "_manifest.csv"
        self.done = self._read_manifest()
        self.s = session(self.referer)
        self.counts = {"ok": 0, "missing": 0, "error": 0, "skipped": 0}

    def _read_manifest(self):
        if not self.manifest.exists():
            return {}
        with self.manifest.open(newline="") as f:
            return {r["date"]: r["status"] for r in csv.DictReader(f)}

    def _record(self, d: date, status: str, nbytes: int):
        new = not self.manifest.exists()
        with self.manifest.open("a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["date", "status", "bytes", "fetched_at"])
            w.writerow([d.isoformat(), status, nbytes, datetime.now().isoformat(timespec="seconds")])

    def dates(self):
        return weekdays(self.start, self.end)

    def filename(self, d: date) -> str:
        raise NotImplementedError

    def fetch(self, d: date) -> bytes:
        raise NotImplementedError

    def valid(self, body: bytes) -> bool:
        raise NotImplementedError

    def run(self):
        for d in self.dates():
            key = d.isoformat()
            # 'missing' is final only once the day is > 3 days old: a run before the exchange publishes (e.g. the
            # daily EOD task, or a manual run at 01:00) used to mark today missing for good (2026-10-19)
            if self.done.get(key) == "ok" or (self.done.get(key) == "missing" and (date.today() - d).days > 3):
                self.counts["skipped"] += 1
                continue
            body, status = b"", "error"
            for attempt in range(3):
                try:
                    body = self.fetch(d)
                    status = "ok" if self.valid(body) else "missing"
                    break
                except Exception:
                    time.sleep(PACE_SEC * (2 ** (attempt + 1)))
            if status == "ok":
                (self.dir / self.filename(d)).write_bytes(body)
            self._record(d, status, len(body))
            self.counts[status] += 1
            time.sleep(PACE_SEC)
        return self.counts


class NseCm(Source):
    name = "nse_cm"
    referer = "https://www.nseindia.com/"

    def filename(self, d):
        return f"cm{d:%d}{d:%b}{d:%Y}".upper().replace("CM", "cm", 1) + "bhav.csv.zip"

    def fetch(self, d):
        mon = f"{d:%b}".upper()
        url = (f"https://nsearchives.nseindia.com/content/historical/EQUITIES/{d:%Y}/{mon}/"
               f"cm{d:%d}{mon}{d:%Y}bhav.csv.zip")
        return self.s.get(url, timeout=30).content

    def valid(self, body):
        return body[:4] == b"PK\x03\x04"


class NseCmIsin(NseCm):
    """NSE CM bhavcopy for its ISIN column (2026-10-19): sec_bhavdata_full, our NSE price file since 2021-11, has
    no ISIN, so symbols could not be mapped to ISINs after Oct 2021 (615 symbols trading in 2026 had no ISIN).
    Old-format zip up to 2024-07-05, UDiFF CSV zip from 2024-07-08. Used by build_security_master.py only."""
    name = "nse_cm_isin"
    UDIFF_FROM = date(2024, 7, 8)

    def filename(self, d):
        return (f"BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip" if d >= self.UDIFF_FROM else super().filename(d))

    def fetch(self, d):
        if d >= self.UDIFF_FROM:
            return self.s.get(f"https://nsearchives.nseindia.com/content/cm/{self.filename(d)}", timeout=30).content
        return super().fetch(d)


class NseMto(Source):
    name = "nse_mto"
    referer = "https://www.nseindia.com/"

    def filename(self, d):
        return f"MTO_{d:%d%m%Y}.DAT"

    def fetch(self, d):
        return self.s.get(f"https://nsearchives.nseindia.com/archives/equities/mto/MTO_{d:%d%m%Y}.DAT",
                          timeout=30).content

    def valid(self, body):
        return body.startswith(b"Security Wise Delivery")


class NseFull(Source):
    """sec_bhavdata_full: prices + delivery, every series. Served from about 2019-10."""

    name = "nse_full"
    referer = "https://www.nseindia.com/"

    def filename(self, d):
        return f"sec_bhavdata_full_{d:%d%m%Y}.csv"

    def fetch(self, d):
        return self.s.get(f"https://nsearchives.nseindia.com/products/content/{self.filename(d)}",
                          timeout=30).content

    def valid(self, body):
        return body.lstrip().startswith(b"SYMBOL")


class NseParticipant(Source):
    """Participant-wise (Client / DII / FII / Pro) open interest or volume in equity derivatives."""

    kind = "oi"
    referer = "https://www.nseindia.com/"

    def filename(self, d):
        return f"fao_participant_{self.kind}_{d:%d%m%Y}.csv"

    def fetch(self, d):
        return self.s.get(f"https://nsearchives.nseindia.com/content/nsccl/{self.filename(d)}", timeout=30).content

    def valid(self, body):
        # From ~2019-08 the title line is wrapped in doubled quotes (""Participant wise ...).
        return b"Participant wise" in body[:40]


class NseParticipantOi(NseParticipant):
    name = "nse_part_oi"
    kind = "oi"


class NseParticipantVol(NseParticipant):
    name = "nse_part_vol"
    kind = "vol"


class NseFiiStats(Source):
    """Daily FII derivative statistics (buy/sell contracts and value, OI) by product."""

    name = "nse_fii_stats"
    referer = "https://www.nseindia.com/"

    def filename(self, d):
        return f"fii_stats_{d:%d-%b-%Y}.xls"

    def fetch(self, d):
        return self.s.get(f"https://nsearchives.nseindia.com/content/fo/{self.filename(d)}", timeout=30).content

    def valid(self, body):
        return body[:4] in (b"\xd0\xcf\x11\xe0", b"PK\x03\x04")


class NseSme(Source):
    name = "nse_sme"
    referer = "https://www.nseindia.com/"

    def filename(self, d):
        return f"sme{d:%d%m%y}.csv"

    def fetch(self, d):
        return self.s.get(f"https://nsearchives.nseindia.com/archives/sme/bhavcopy/sme{d:%d%m%y}.csv",
                          timeout=30).content

    def valid(self, body):
        return body.startswith(b"MARKET,")


class NseIndex(Source):
    name = "nse_index"
    referer = "https://www.nseindia.com/"

    def filename(self, d):
        return f"ind_close_all_{d:%d%m%Y}.csv"

    def fetch(self, d):
        return self.s.get(f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv",
                          timeout=30).content

    def valid(self, body):
        return body.startswith(b"Index Name")


class BseBhav(Source):
    name = "bse_bhav"
    referer = "https://www.bseindia.com/"

    def filename(self, d):
        if d <= BSE_LEGACY_END:
            return f"EQ{d:%d%m%y}_CSV.ZIP"
        return f"BhavCopy_BSE_CM_0_0_0_{d:%Y%m%d}_F_0000.CSV"

    def fetch(self, d):
        return self.s.get("https://www.bseindia.com/download/BhavCopy/Equity/" + self.filename(d),
                          timeout=30).content

    def valid(self, body):
        return body[:4] == b"PK\x03\x04" or body.startswith(b"TradDt,")


class BseDeliv(Source):
    name = "bse_deliv"
    referer = BSE_DELIV_URL

    def filename(self, d):
        return f"SCBSEALL_{d:%Y%m%d}.zip"

    def fetch(self, d):
        page = self.s.get(BSE_DELIV_URL, timeout=30).text
        form = dict(re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', page))
        form.update({
            "ctl00$ContentPlaceHolder1$rblDT": "rbRefNo",
            "ctl00$ContentPlaceHolder1$txtDate": f"{d:%d/%m/%Y}",
            "ctl00$ContentPlaceHolder1$ddlstlement": "0",
            "ctl00$ContentPlaceHolder1$btnSubmit": "Submit",
        })
        return self.s.post(BSE_DELIV_URL, data=form, timeout=60).content

    def valid(self, body):
        if body[:4] != b"PK\x03\x04":
            return False
        # The zip must hold a file for the requested date, not a stale default.
        try:
            z = zipfile.ZipFile(io.BytesIO(body))
            first = z.read(z.namelist()[0]).decode("latin1").splitlines()
            return len(first) > 1
        except zipfile.BadZipFile:
            return False


def fetch_commodities(start: date):
    out = ROOT / "commod"
    out.mkdir(parents=True, exist_ok=True)
    import yfinance as yf
    summary = {}
    for ticker, label in COMMODITY_TICKERS.items():
        df = yf.download(ticker, start=start.isoformat(), progress=False, auto_adjust=False)
        if len(df):
            df.to_csv(out / f"{label}__{ticker.replace('=', '_')}.csv")
        summary[label] = len(df)
    body = session().get(WB_PINK_SHEET_URL, timeout=120).content
    if body[:4] == b"PK\x03\x04":
        (out / "worldbank_pink_sheet_monthly.xlsx").write_bytes(body)
        summary["worldbank_pink_sheet"] = len(body)
    return summary


SOURCES = {
    "nse_cm": (NseCm, NSE_OLD_FORMAT_END),
    "nse_mto": (NseMto, NSE_OLD_FORMAT_END),
    "nse_cm_isin": (NseCmIsin, None),
    "nse_full": (NseFull, None),
    "nse_part_oi": (NseParticipantOi, None),
    "nse_part_vol": (NseParticipantVol, None),
    "nse_fii_stats": (NseFiiStats, None),
    "nse_sme": (NseSme, None),
    "nse_index": (NseIndex, None),
    "bse_bhav": (BseBhav, None),
    "bse_deliv": (BseDeliv, None),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", default="all", help="comma list or 'all' (" + ",".join([*SOURCES, "commod"]) + ")")
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat())
    args = ap.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    wanted = [*SOURCES, "commod"] if args.sources == "all" else args.sources.split(",")

    results, threads = {}, []

    def work(name):
        if name == "commod":
            results[name] = fetch_commodities(start)
            return
        cls, cap = SOURCES[name]
        results[name] = cls(start, min(end, cap) if cap else end).run()

    for name in wanted:
        t = threading.Thread(target=work, args=(name,), name=name)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    for name in wanted:
        print(f"{name:10} {results.get(name)}")


if __name__ == "__main__":
    main()
