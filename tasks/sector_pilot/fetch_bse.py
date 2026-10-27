"""Fetch BSE company headers for exactly the 200 sampled scrip codes.

Pacing: bse_client.bse_json already sleeps 1-2 s; this wrapper adds 2.5 s before
each call, so the long-run rate stays at ~14-15 requests/min (<= 20/min).
Raw responses land in .tmp/bse_header/<scripcode>.json; the run is resumable.
"""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from reality_engine.ingestion.bse_client import bse_json
from reality_engine.ingestion.bse_fundamentals_client import EP_HEADER, fetch_header

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".tmp" / "bse_header"
OUT.mkdir(parents=True, exist_ok=True)
SAMPLE = Path(__file__).resolve().parent / "sample.json"
EXTRA_SLEEP = 2.5

rows = json.loads(SAMPLE.read_text(encoding="utf-8"))["rows"]
codes = []
seen = set()
for r in rows:
    c = str(r["bse_code"]).strip()
    if c and c not in seen:
        seen.add(c)
        codes.append(c)
print(f"codes to fetch: {len(codes)}", flush=True)


def paced(path, params=None):
    time.sleep(EXTRA_SLEEP)
    payload = bse_json(path, params)
    code = str((params or {}).get("scripcode", "")).strip()
    if payload is not None and code:
        (OUT / f"{code}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


results = {}
done = 0
for code in codes:
    f = OUT / f"{code}.json"
    if f.exists() and f.stat().st_size > 2:
        payload = json.loads(f.read_text(encoding="utf-8"))
        parsed = fetch_header(code, fetcher=lambda p, q=None: payload)
        results[code] = {"ok": parsed is not None, "cached": True,
                         "industry": (parsed or {}).get("industry"),
                         "industry_new": (parsed or {}).get("industry_new"),
                         "sector": (parsed or {}).get("sector")}
        continue
    try:
        parsed = fetch_header(code, fetcher=paced)
    except Exception as exc:  # network hiccup: record and move on
        parsed = None
        err = f"{type(exc).__name__}: {exc}"
        results[code] = {"ok": False, "error": err}
        print(f"{code} ERROR {err}", flush=True)
        continue
    ok = parsed is not None
    results[code] = {
        "ok": ok,
        "industry": (parsed or {}).get("industry"),
        "industry_new": (parsed or {}).get("industry_new"),
        "sector": (parsed or {}).get("sector"),
    }
    done += 1
    if done % 10 == 0:
        (ROOT / ".tmp" / "bse_header_results.json").write_text(
            json.dumps(results, indent=1), encoding="utf-8")
        print(f"{done}/{len(codes)} fetched, last={code} ok={ok}", flush=True)

(ROOT / ".tmp" / "bse_header_results.json").write_text(
    json.dumps(results, indent=1), encoding="utf-8")
ok = sum(1 for v in results.values() if v.get("ok"))
print(f"DONE ok={ok} failed={len(results) - ok} of {len(codes)}", flush=True)
