"""Fetch BSE headers for sample codes missing from the main fetch (resumable)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from reality_engine.ingestion.bse_client import bse_json
from reality_engine.ingestion.bse_fundamentals_client import fetch_header

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".tmp" / "bse_header"
OUT.mkdir(parents=True, exist_ok=True)
SAMPLE = Path(__file__).resolve().parent / "sample.json"
RES = ROOT / ".tmp" / "bse_header_results.json"

rows = json.loads(SAMPLE.read_text(encoding="utf-8"))["rows"]
results = json.loads(RES.read_text(encoding="utf-8"))
missing = []
seen = set()
for r in rows:
    c = str(r["bse_code"]).strip()
    if c and c not in seen and c not in results:
        seen.add(c)
        missing.append(c)
print("missing:", missing, flush=True)


def paced(path, params=None):
    time.sleep(2.5)
    payload = bse_json(path, params)
    code = str((params or {}).get("scripcode", "")).strip()
    if payload is not None and code:
        (OUT / f"{code}.json").write_text(json.dumps(payload, ensure_ascii=False),
                                          encoding="utf-8")
    return payload


for code in missing:
    parsed = fetch_header(code, fetcher=paced)
    results[code] = {"ok": parsed is not None,
                     "industry": (parsed or {}).get("industry"),
                     "industry_new": (parsed or {}).get("industry_new"),
                     "sector": (parsed or {}).get("sector")}
    print(code, results[code], flush=True)
RES.write_text(json.dumps(results, indent=1), encoding="utf-8")
print("now", sum(1 for v in results.values() if v.get("ok")), "ok of", len(results))
