"""Accuracy, error-type and change tables for the sector-label pilot.

Reads the re-graded `sector_label_pilot.csv` and, when present, the frozen
`v1` snapshot, and prints the two side by side so REPORT.md can quote both.
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent
COLS = [("nse_sector_grade", "NSE sector"),
        ("nse_industry_grade", "NSE industry"),
        ("bse_sector_grade", "BSE sector"),
        ("bse_industry_grade", "BSE industry"),
        ("bse_industry_new_grade", "BSE industry_new")]


def load(name):
    p = OUT / name
    if not p.exists():
        return None
    return list(csv.DictReader(p.open(encoding="utf-8")))


new = load("sector_label_pilot.csv")
old = load("sector_label_pilot_v1.csv")


def graded(rows, col):
    c = Counter(r[col] for r in rows)
    n = sum(c[k] for k in ("correct", "partly", "wrong", "stale"))
    return c, n


def acc(c, n):
    return f"{100 * c['correct'] / n:.1f}%" if n else "-"


def row(label, sel_new, sel_old, col, name):
    cn, nn = graded(sel_new, col)
    co, no = graded(sel_old, col) if sel_old else (Counter(), 0)
    print(f"| {label} | {name} | {co['correct']} | {acc(co, no)} | "
          f"{cn['correct']} | {acc(cn, nn)} | {cn['partly']} | {cn['wrong']} | {cn['stale']} | "
          f"{cn['cannot_tell']} | {nn} |")


def groups(rows):
    if rows is None:
        return []
    A = [r for r in rows if r["bucket"].startswith("A")]
    B = [r for r in rows if r["bucket"].startswith("B")]
    return [("all 200", rows), ("A (NSE-labelled)", A), ("B (unlabelled)", B),
            ("A single-segment", [r for r in A if r["multi_segment"] == "no"]),
            ("A multi-segment", [r for r in A if r["multi_segment"] == "yes"]),
            ("A SMALL", [r for r in A if r["cap_tier"] == "SMALL"]),
            ("A MICRO", [r for r in A if r["cap_tier"] == "MICRO"])]


print(f"rows v2={len(new)} v1={len(old) if old else 0}\n")
print("| group | level | v1 correct | v1 acc | v2 correct | v2 acc | partly | wrong | stale | cannot_tell | n graded |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
go = dict(groups(old)) if old else {}
for label, sel in groups(new):
    for col, name in COLS:
        if col not in new[0]:
            continue
        row(label, sel, go.get(label), col, name)
    print("|---|---|---|---|---|---|---|---|---|---|---|")

print("\n### error types (v2)")
e = Counter()
for r in new:
    for x in (r["error_types"] or "").split(";"):
        if x:
            e[x] += 1
for k, v in e.most_common():
    print(f"| {k} | {v} |")

if old:
    print("\n### error types (v1)")
    eo = Counter()
    for r in old:
        for x in (r["error_types"] or "").split(";"):
            if x:
                eo[x] += 1
    print(dict(eo.most_common()))

print("\n### rows with any `wrong` (v2)")
w = [r for r in new if any(r[c] == "wrong" for c, _ in COLS)]
print("count:", len(w))
for r in w:
    bad = [n for c, n in COLS if r[c] == "wrong"]
    print(f"- {'/'.join(bad)} | {r['symbol'] or r['isin']} | main {r['main_business_family']} "
          f"| quote: \"{r['evidence_quote']}\" | {r['quote_ref']}")

print("\n### rows with any `stale` (v2)")
for r in new:
    if any(r[c] == "stale" for c, _ in COLS):
        print(f"- {r['symbol'] or r['isin']} | main {r['main_business_family']} "
              f"| quote: \"{r['evidence_quote']}\" | {r['quote_ref']}")

print("\n### cannot_tell (v2)")
for r in new:
    if r["main_business_family"] == "":
        print(f"- {r['symbol'] or r['isin']} {r['bucket'][:1]} | "
              f"{r['nse_sector'] or '-'} / {r['bse_industry'] or '-'} | \"{r['evidence_quote'][:70]}\"")

if old:
    print("\n### grade changes v1 -> v2")
    rank = {"correct": 3, "partly": 2, "stale": 2, "wrong": 1, "cannot_tell": 0, "n/a": 0}
    om = {r["isin"]: r for r in old}
    better = worse = rows_changed = cells = 0
    for r in new:
        o = om.get(r["isin"])
        if not o:
            continue
        ch = False
        for c, _ in COLS:
            if c not in o:
                continue
            if o[c] != r[c]:
                cells += 1
                ch = True
                if rank[r[c]] > rank[o[c]]:
                    better += 1
                else:
                    worse += 1
        rows_changed += ch
    print(f"cells changed={cells} rows changed={rows_changed} "
          f"cells improved={better} cells worsened={worse}")
