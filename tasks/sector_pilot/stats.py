"""Compute the accuracy tables for REPORT.md from grades.json."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import taxonomy as tx

OUT = Path(__file__).resolve().parent
rows = json.loads((OUT / "grades.json").read_text(encoding="utf-8"))


def graded(r, col):
    return r[col] in ("correct", "partly", "wrong", "stale")


def acc(sel, col, strict=False):
    g = [r for r in sel if graded(r, col) or r[col] == "stale"]
    c = sum(1 for r in g if r[col] == "correct")
    if strict:
        c = sum(1 for r in g if r[col] == "correct"
                and tx.family_of_label(r["nse_sector" if col.startswith("nse")
                                       else "bse_industry"]) == r["main_business"].upper())
    return c, len(g)


def table(title, groups):
    print(f"\n### {title}")
    print("| group | level | correct | partly | wrong | stale | cannot_tell | n graded | accuracy |")
    print("|---|---|---|---|---|---|---|---|---|")
    for name, sel in groups:
        for col, lvl in (("nse_sector_grade", "NSE sector"),
                         ("nse_industry_grade", "NSE industry"),
                         ("bse_sector_grade", "BSE sector"),
                         ("bse_industry_grade", "BSE industry"),
                         ("bse_industry_new_grade", "BSE industry_new (sector granularity)")):
            if not any(col in r for r in sel):
                continue
            c = Counter(r[col] for r in sel)
            g = sum(c[k] for k in ("correct", "partly", "wrong", "stale"))
            cor = c["correct"]
            pct = f"{100 * cor / g:.1f}%" if g else "-"
            print(f"| {name} | {lvl} | {cor} | {c['partly']} | {c['wrong']} | {c['stale']} "
                  f"| {c['cannot_tell']} | {g} | {pct} |")


A = [r for r in rows if r["bucket"].startswith("A")]
B = [r for r in rows if r["bucket"].startswith("B")]
print(f"rows={len(rows)} A={len(A)} B={len(B)}")

table("Overall", [("all 200", rows), ("A (NSE-labelled 150)", A), ("B (unlabelled 50)", B)])
table("NSE-labelled split", [
    ("single-segment", [r for r in A if r["multi_segment"] == "no"]),
    ("multi-segment", [r for r in A if r["multi_segment"] == "yes"]),
    ("SMALL cap", [r for r in A if r["cap_tier"] == "SMALL"]),
    ("MICRO cap", [r for r in A if r["cap_tier"] == "MICRO"]),
])
table("Strict family match (no parent/acceptance sets)", [("A", A), ("B", B)])

print("\n### strict NSE/BSE family equality")
for col, lvl in (("nse_sector_grade", "NSE sector"), ("nse_industry_grade", "NSE industry"),
                 ("bse_sector_grade", "BSE sector"), ("bse_industry_grade", "BSE industry")):
    sel = [r for r in rows if graded(r, col)]
    c = sum(1 for r in sel if r[col] == "correct")
    print(f"{lvl}: correct {c}/{len(sel)} graded = {100 * c / len(sel):.1f}%" if sel else "none")

print("\n### error types")
e = Counter()
for r in rows:
    for x in (r["error_types"] or "").split(";"):
        if x:
            e[x] += 1
print(dict(e.most_common()))

print("\n### cannot_tell rows")
for r in rows:
    if "cannot_tell" in (r["nse_sector_grade"], r["bse_sector_grade"]):
        print(r["symbol"] or r["isin"], r["bucket"], r["nse_sector"], r["bse_industry"],
              r["nse_sector_grade"], r["bse_sector_grade"], "|", r["segment_split"][:50])

print("\n### non-correct detail (for examples)")
for r in rows:
    if r["nse_sector_grade"] in ("wrong", "partly", "stale") or \
       r["bse_industry_grade"] in ("wrong", "partly", "stale"):
        print(f"{r['symbol'] or r['isin']:<12} {r['bucket'][:1]} {r['cap_tier']:<5} "
              f"NSE {r['nse_sector'][:24]:<24}/{r['nse_industry'][:22]:<22} "
              f"BSE {r['bse_sector'][:14]:<14}/{r['bse_industry'][:26]:<26} "
              f"-> {r['main_business']:<14} "
              f"{r['nse_sector_grade']}/{r['nse_industry_grade']}/{r['bse_sector_grade']}/{r['bse_industry_grade']}")
