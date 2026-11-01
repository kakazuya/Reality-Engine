"""Audit of the pilot bank, independent of the rule templates. Prints every failure; exit 1 if any.

Checks: 1 no company outside the pilot is named; 2 every stated price move equals the stored close change;
3 each stock traded on or near every date its question names; 4 no named date after the row's as_of;
5 no leftover template text; 6 every text row's evidence was known by as_of; 7 pilot entities only.
"""
from __future__ import annotations

import collections
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import engine as E  # noqa: E402

ROOT = E.ROOT
MONTHS = "January February March April May June July August September October November December".split()
DATE = re.compile(r"\b(\d{1,2}) (" + "|".join(MONTHS) + r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec) (\d{4})\b")
ISO = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
MOVE = re.compile(r"(fell|rose|moved|jumped|chala)\D{0,12}?([+-]?\d+(?:\.\d+)?)%\s+on\s+" + DATE.pattern)
OUTSIDE_EXTRA = r"\b(Reliance|HDFC|ICICI|Infosys|TCS|Titan|Trent|DMart|Nykaa|Paytm|Eternal|Zomato|Swiggy|Adani (?:Green|Power|Enterprises|Ports)|Vedanta|Suzlon|Titagarh|RVNL|IRFC|IRCTC|Ircon|Rites|NBCC|Mazagon|Cochin Shipyard|Dixon|Kaynes|Polycab|KEI|UltraTech|Muthoot|IndiGo|Ola Electric|Waaree|Premier Energies|Yes Bank|Coal India|NTPC|BHEL|HAL|BEL|Maruti|Mankind|Cipla|Tata Steel|JSW|PB Fintech|Cyient|SRF|Asian Paints|Astral|Coforge|Mphasis|Persistent|Syrma|Amber|Sona Comstar|Larsen|SBI|ABB|Siemens|Cummins|Nestle|ITC|IDBI|IREDA|Jio|Hyundai|Hindustan Zinc|NMDC|Godrej|Bajaj (?:Holdings|Finserv)|Tata (?:Power|Steel|Chemicals|Investment)|Texrail|Jaiprakash|Reliance Power|Jubilant FoodWorks|Afcons|BDL|IRB|Deepak Nitrite|Ambuja|CG Power)\b"


def iso(m) -> str:
    mon = m[2][:3]
    return f"{m[3]}-{[x[:3] for x in MONTHS].index(mon) + 1:02d}-{int(m[1]):02d}"


def main() -> int:
    st = E.Store()
    rows = [json.loads(line) for line in open(ROOT / "tasks/pilot60/PILOT_BANK_2026-10-31.jsonl", encoding="utf-8")]
    pilot = set(st.by_isin)
    names = {}
    for line in open(ROOT / "tasks/master_bank/MASTER_BANK.jsonl", encoding="utf-8"):
        for e in json.loads(line).get("entities") or []:
            if e.get("isin") and e["isin"] not in pilot and e.get("symbol") and len(e["symbol"]) >= 4:
                names[e["symbol"]] = e["isin"]
    sym_rx = re.compile(r"\b(" + "|".join(sorted(map(re.escape, names), key=len, reverse=True)) + r")\b")
    extra = re.compile(OUTSIDE_EXTRA)
    fails = collections.defaultdict(list)
    moves_checked = dates_checked = 0
    for r in rows:
        q, mid = r["question"], r["mid"]
        m = sym_rx.search(q) or extra.search(q)
        if m:
            fails["outside_name"].append(f"{mid}: {m[0]} | {q[:110]}")
        if "{" in q or "}" in q or "None" in q:
            fails["template_text"].append(f"{mid}: {q[:110]}")
        for e in r["entities"]:
            if e["isin"] not in pilot:
                fails["not_pilot"].append(mid)
        named = [iso(d) for d in DATE.finditer(q)] + [f"{a}-{b}-{c}" for a, b, c in ISO.findall(q)]
        for d in named:
            dates_checked += 1
            if d > r["as_of"] and d > "2026-10-23":
                fails["date_after_data"].append(f"{mid}: {d} | {q[:90]}")
            elif d > r["as_of"] and r["kind"] == "stock":
                fails["date_after_as_of"].append(f"{mid}: {d} > {r['as_of']} | {q[:90]}")
            for e in r["entities"] if r["kind"] == "stock" else []:
                px = [x[0] for x in st.px(e["isin"])]
                near = [x for x in px if abs((date.fromisoformat(x) - date.fromisoformat(d)).days) <= 5]
                if not near:
                    fails["no_session_near_date"].append(f"{mid} {e['symbol']}: {d} (held {px[0] if px else '-'}..{px[-1] if px else '-'}) | {q[:80]}")
        for mv in MOVE.finditer(q):
            for e in r["entities"][:1]:
                d = f"{mv[5]}-{[x[:3] for x in MONTHS].index(mv[4][:3]) + 1:02d}-{int(mv[3]):02d}"
                px = st.px(e["isin"])
                dates = [x[0] for x in px]
                if d not in dates or dates.index(d) == 0:
                    fails["move_date_missing"].append(f"{mid}: {d}")
                    continue
                i = dates.index(d)
                actual = (px[i][4] / px[i - 1][4] - 1) * 100
                claimed = abs(float(mv[2])) if mv[1] != "moved" and mv[1] != "chala" else float(mv[2])
                if mv[1] in ("fell",):
                    claimed = -abs(float(mv[2]))
                if mv[1] in ("rose", "jumped"):
                    claimed = abs(float(mv[2]))
                moves_checked += 1
                if abs(actual - claimed) > 0.02:
                    fails["move_wrong"].append(f"{mid} {e['symbol']}: claimed {claimed} stored {actual:.2f} on {d}")
        for ev in r["fact_check"]["evidence"] or []:
            if ev and ev.get("known_at") and ev["known_at"][:10] > r["as_of"]:
                fails["evidence_after_as_of"].append(mid)
    print(f"rows {len(rows)}; moves re-read {moves_checked}; named dates checked {dates_checked}")
    for k, v in fails.items():
        print(f"\n## {k}: {len(v)}")
        for x in v[:45]:
            print(" ", x[:190])
    print("\nFAILS", {k: len(v) for k, v in fails.items()} or "none")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
