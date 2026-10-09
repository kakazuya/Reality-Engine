"""
Daily FII / DII cash-market flows from Moneycontrol (third-party archive; approved by
Shivam 2026-10-08 because NSE publishes only the latest day).

API (found in moneycontrol.com's FII/DII page code, 2026-10-08):
  https://api.moneycontrol.com/swiftapi/v1/fii_dii/cash?section=daily&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD
It answers in protobuf (message FiiDiiPackage.FiiDiiCashResponse, schema at
moneycontrol.com/mc-react/proto/FiiDiiPackage.proto). Every field we need is a string,
so a tiny wire-format decoder is enough; no protobuf dependency.

Plain HTTP clients get 403; curl_cffi with Chrome impersonation works.

Writes raw responses to ``raw_market/mc_fiidii/<year>.pb`` and a decoded CSV next to
them. Loading into the DB is done by load_market_raw.py (source ``mc_fiidii``).

Usage:
    python -m reality_engine.scripts.fetch_fiidii_moneycontrol --start 2019-01-01
"""

import argparse
import csv
import time
from datetime import date, timedelta
from pathlib import Path

from curl_cffi import requests as cffi_requests

ROOT = Path(__file__).resolve().parents[1] / "data" / "raw_market" / "mc_fiidii"
API = "https://api.moneycontrol.com/swiftapi/v1/fii_dii/cash?section=daily&startDate={a}&endDate={b}"
# Field numbers of message Cash in FiiDiiPackage.proto
CASH_FIELDS = {1: "date", 2: "fii_purchase", 3: "fii_sales", 4: "fii_net", 5: "dii_purchase",
               6: "dii_sale", 7: "dii_net", 8: "nifty_close", 9: "nifty_prev_close", 10: "nifty_change_pct"}


def _varint(buf: bytes, i: int):
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def _fields(buf: bytes):
    """Yield (field_number, value) for one protobuf message; bytes for length-delimited."""
    i = 0
    while i < len(buf):
        key, i = _varint(buf, i)
        num, wire = key >> 3, key & 7
        if wire == 0:
            val, i = _varint(buf, i)
        elif wire == 2:
            n, i = _varint(buf, i)
            val, i = buf[i:i + n], i + n
        elif wire == 5:
            val, i = buf[i:i + 4], i + 4
        elif wire == 1:
            val, i = buf[i:i + 8], i + 8
        else:
            raise ValueError(f"unsupported wire type {wire}")
        yield num, val


def decode_cash(body: bytes):
    """FiiDiiCashResponse -> list of dicts (one per trading day)."""
    rows = []
    for num, val in _fields(body):
        if num != 3:  # data: CashData
            continue
        for n2, cash in _fields(val):
            if n2 != 1:  # repeated Cash
                continue
            rec = {name: "" for name in CASH_FIELDS.values()}
            for n3, v in _fields(cash):
                if n3 in CASH_FIELDS:
                    rec[CASH_FIELDS[n3]] = v.decode("utf-8", "replace")
            rows.append(rec)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat())
    args = ap.parse_args()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    ROOT.mkdir(parents=True, exist_ok=True)
    s = cffi_requests.Session(impersonate="chrome")
    s.headers.update({"Referer": "https://www.moneycontrol.com/", "Origin": "https://www.moneycontrol.com"})
    total = 0
    for year in range(start.year, end.year + 1):
        a, b = max(date(year, 1, 1), start), min(date(year, 12, 31), end)
        body = s.get(API.format(a=a.isoformat(), b=b.isoformat()), timeout=60).content
        (ROOT / f"{year}.pb").write_bytes(body)
        rows = [r for r in decode_cash(body) if a.isoformat() <= r["date"] <= b.isoformat()]
        with (ROOT / f"{year}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(CASH_FIELDS.values()))
            w.writeheader()
            w.writerows(sorted(rows, key=lambda r: r["date"]))
        dates = [r["date"] for r in rows]
        print(f"{year}: {len(rows)} days {min(dates) if dates else '-'} -> {max(dates) if dates else '-'}", flush=True)
        total += len(rows)
        time.sleep(2)
    print(f"total days: {total}")


if __name__ == "__main__":
    main()
