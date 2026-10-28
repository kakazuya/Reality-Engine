"""Build the 200-row Reddit-mined question bank from the three content modules.

Validates: 200 rows, unique qids, exact group split (75/75/50), every symbol
resolves to an active ISIN in master_companies, no forbidden seeded event name.
Writes the .jsonl and the readable .md.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"

SPECS = [
    ("bank_indian.py", "indian", "RD-I", 75),
    ("bank_intl.py", "international", "RD-N", 75),
    ("bank_tech.py", "technical", "RD-T", 50),
]
BANNED = re.compile(
    r"\b(NUCLEAR_MISSION|RAIL_CAPEX_PUSH|STEEL_SAFEGUARD_DUTY|"
    r"US_TARIFF_TEXTILE_RELIEF|PHASE5_)", re.I
)


def load_module(filename: str):
    spec = importlib.util.spec_from_file_location(filename.replace(".py", ""), HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    companies = {c["symbol"]: c for c in
                 json.loads((WORK / "companies.json").read_text(encoding="utf-8"))}
    rows = []
    problems = []
    for filename, group, prefix, expected in SPECS:
        mod = load_module(filename)
        modrows = mod.ROWS
        if len(modrows) != expected:
            problems.append(f"{filename}: {len(modrows)} rows, expected {expected}")
        for i, r in enumerate(modrows, 1):
            qid = f"{prefix}-{i:03d}"
            entities = []
            for sym in r["syms"]:
                c = companies.get(sym)
                if c is None:
                    problems.append(f"{qid}: symbol {sym} not in master_companies")
                    continue
                entities.append({
                    "type": "stock", "symbol": sym, "isin": c["isin"],
                    "bse_code": c["bse_code"], "name": c["name"],
                    "sector": c["sector"], "basic_industry": c["industry"],
                    "market_cap_tier": c["tier"], "fno_eligible": bool(c["fno"]),
                })
            ev = r["ev"]
            table = ev.split()[0].strip(",") if ev else ""
            row = {
                "qid": qid,
                "group": group,
                "archetype": r["arch"],
                "family": r["family"],
                "question": r["q"],
                "entities": entities,
                "period": r["period"],
                "as_of": r["as_of"],
                "answer_kind": r["kind"],
                "rubric": {
                    "required_evidence": ev,
                    "required_steps": r["steps"],
                    "forbidden": r["forb"],
                    "ground_truth": None,
                    "ground_truth_query": table,
                    "ground_truth_note": "not asserted in this bank; compute at answer time from the listed evidence",
                },
                "coverage": {"verdict": r["verdict"], "note": r["note"], "gap_id": None},
                "why": r["why"],
                "reddit_pattern": r["rp"],
            }
            if BANNED.search(r["q"]):
                problems.append(f"{qid}: banned seeded event name in question")
            if not row["question"].strip() or not row["entities"]:
                problems.append(f"{qid}: empty question or no resolved entity")
            rows.append(row)

    qids = [r["qid"] for r in rows]
    if len(qids) != len(set(qids)):
        problems.append("duplicate qids")
    counts = {g: sum(1 for r in rows if r["group"] == g) for g in
              ("indian", "international", "technical")}
    if counts != {"indian": 75, "international": 75, "technical": 50}:
        problems.append(f"group split {counts}")
    if problems:
        print("VALIDATION FAILED")
        for p in problems:
            print(" -", p)
        return 1

    jsonl = HERE / "QUESTION_BANK_REDDIT_2026-10-28.jsonl"
    jsonl.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                     encoding="utf-8")

    verdicts = {}
    for r in rows:
        verdicts[r["coverage"]["verdict"]] = verdicts.get(r["coverage"]["verdict"], 0) + 1
    lines = [
        "# Reddit-mined question bank — 200 questions (2026-10-28)",
        "",
        "Mined from 15 Indian-market subreddits (since 2024-04-01), 15 international",
        "value/fundamentals subreddits and 10 trading subreddits (last year).",
        "Every question is original wording modelled on a pattern, not a copied post.",
        "Every entity resolves to an active ISIN in `master_companies`.",
        "",
        "## Summary",
        "",
        f"- 200 rows: Indian {counts['indian']}, international-pattern {counts['international']}, technical {counts['technical']}.",
        f"- Coverage: " + ", ".join(f"{k} {v}" for k, v in sorted(verdicts.items())) + ".",
        "- Each row carries `reddit_pattern`, the pattern it was modelled on.",
        "- No `ground_truth` is asserted here; `ground_truth_query` names the first table to compute from.",
        "",
        "| qid range | group | rows | patterns |",
        "|---|---|---|---|",
    ]
    for prefix, group in (("RD-I", "indian"), ("RD-N", "international"), ("RD-T", "technical")):
        n = sum(1 for r in rows if r["qid"].startswith(prefix))
        pats = len({r["reddit_pattern"] for r in rows if r["qid"].startswith(prefix)})
        lines.append(f"| {prefix}-001…{prefix}-{n:03d} | {group} | {n} | {pats} |")
    lines += ["", "---", ""]
    for prefix, title in (("RD-I", "Indian-market patterns"),
                          ("RD-N", "International value patterns, translated"),
                          ("RD-T", "Technical / entry-timing patterns")):
        lines += [f"## {title}", ""]
        for r in rows:
            if not r["qid"].startswith(prefix):
                continue
            ents = ", ".join(f"{e['symbol']} ({e['isin']})" for e in r["entities"])
            lines += [
                f"### {r['qid']} · {r['archetype']} · family {r['family']} · `{r['reddit_pattern']}`",
                "",
                f"**Q.** {r['question']}",
                "",
                f"- Entities: {ents}",
                f"- Period: {r['period']} · as-of: {r['as_of']} · answer: {r['answer_kind']}",
                f"- Evidence: {r['rubric']['required_evidence']}",
                f"- Steps: {r['rubric']['required_steps']}",
                f"- Forbidden: {r['rubric']['forbidden']}",
                f"- Coverage: **{r['coverage']['verdict']}** — {r['coverage']['note']}",
                f"- Why: {r['why']}",
                "",
            ]
    (HERE / "QUESTION_BANK_REDDIT_2026-10-28.md").write_text("\n".join(lines), encoding="utf-8")

    print("wrote", jsonl.name, "and", "QUESTION_BANK_REDDIT_2026-10-28.md")
    print("rows", len(rows), "groups", counts, "verdicts", verdicts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
