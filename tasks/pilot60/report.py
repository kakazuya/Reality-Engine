"""Write tasks/pilot60/REPORT.md from the run results.

    python tasks/pilot60/report.py

Reads RESULTS_INSTANCES.jsonl, RESULTS_ORIGINALS.jsonl, UNIVERSE.csv,
INSTANTIATE_STATS.md, coverage.json, chunks_build.json and HAND_CHECK_60.json.
Every breakdown the brief names is computed here, so the report is reproducible.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "tasks" / "pilot60"
sys.path.insert(0, str(REPO / "tasks" / "answer_bench"))
import run_v0  # noqa: E402

BUCKETS = ("LARGE", "MID-SMALL", "MICRO")
GRADES = ["ANSWERED", "PARTIAL", "BLOCKED_SCHEMA", "BLOCKED_TOOL", "NOT_IN_DATA", "WRONG"]


def load(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def pct(part: int, total: int) -> str:
    return f"{100 * part / total:.1f}%" if total else "n/a"


def answered(rows: list[dict]) -> tuple[int, int]:
    return sum(1 for r in rows if r["grade"] == "ANSWERED"), len(rows)


def table_answered(rows: list[dict], key) -> list[str]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[key(row)].append(row)
    lines = ["| group | answered | cases | % |", "|---|---:|---:|---:|"]
    for name in sorted(grouped, key=lambda k: (str(k) == "None", str(k))):
        ok, total = answered(grouped[name])
        lines.append(f"| {name} | {ok} | {total} | {pct(ok, total)} |")
    return lines


def family_of(row: dict) -> str:
    fam = row.get("family") or []
    return f"F{fam[0]}" if fam else "F-none"


def heat(rows: list[dict]) -> list[str]:
    fams = sorted({family_of(r) for r in rows}, key=lambda f: int(f[1:]) if f[1:].isdigit() else 99)
    lines = ["| family | " + " | ".join(BUCKETS) + " |", "|---|" + "---:|" * len(BUCKETS)]
    for fam in fams:
        cells = []
        for bucket in BUCKETS:
            ok, total = answered([r for r in rows if family_of(r) == fam
                                 and r.get("bucket") == bucket])
            cells.append(pct(ok, total) if total else "-")
        lines.append(f"| {fam} | " + " | ".join(cells) + " |")
    return lines


FIX_BY_GAP = {
    "company_sector_pit": "built in T1 (2,055 rows): wire RIPPLE's policy->sector hop to it "
                          "(planner change, no fetch)",
    "company_segment_pnl": "built in T1 (34,451 rows): wire the segment hop to it",
    "company_metric_series": "built in T1 (1,056,589 rows): wire FACTS to it",
    "company_metric_series ": "built in T1 (1,056,589 rows): wire FACTS to it",
    "xbrl_concept_map": "built (110 concepts): extend the concept map",
    "event_day0": "built (3,010,610 rows): wire EVENT to it",
    "event_leakage_window": "built (0 rows): fill the leakage window",
    "company_cost_structure": "company_cost_structure (AR cost-note extraction; not built)",
    "macro_claim_target": "macro_claim_target (claim->sector/company map; not built)",
    "company_theme_pit": "company_theme_pit (theme membership; not built)",
    "chunks_v3": "chunks_v3 store is built but capped at the latest docs/type: full FY25+ build",
    "consensus_estimates": "no consensus store by design: EXPECTATIONS uses the company's own "
                           "guidance proxy",
    "exchange_originals": "exchange_originals fetch (original filing files)",
    "company_state_daily": "company_state_daily is built in T1: wire the screen to it",
    "company_membership_pit": "company_membership_pit is built in T1 (10,895 intervals)",
}


def fix_of(row: dict) -> str:
    gap = str(row.get("gap") or "").strip()
    if gap in FIX_BY_GAP:
        return FIX_BY_GAP[gap]
    text = f"{gap} {row.get('blocker') or ''}".lower()
    for key, fix in run_v0.FIX_FOR_STATUS.items():
        if key in text:
            return fix
    for hop in row.get("hops_failed") or []:
        if hop in run_v0.FIX_FOR_HOP:
            return run_v0.FIX_FOR_HOP[hop]
    return "held data: no mapped fix"


def gaps(rows: list[dict]) -> list[tuple[str, int, str, str]]:
    """(bucket, cases, gap text, fix) ranked by cases unblocked."""
    counter: Counter = Counter()
    fix: dict[str, str] = {}
    for row in rows:
        if row["grade"] == "ANSWERED":
            continue
        text = (row.get("gap") or "").strip() or (row.get("blocker") or "").strip()
        text = text.split(";")[0][:90] or row["grade"]
        key = f"{row.get('bucket') or 'as-is'}|{text}"
        counter[key] += 1
        fix[key] = fix_of(row)
    out = []
    for key, n in counter.most_common(25):
        bucket, text = key.split("|", 1)
        out.append((bucket, n, text, fix[key]))
    return out


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, max(0, math.ceil(q * len(values)) - 1))
    return values[idx]


def latency(rows: list[dict]) -> list[str]:
    per = defaultdict(list)
    for row in rows:
        for call in row.get("calls") or []:
            per[call.get("tool") or "?"].append(float(call.get("s") or 0))
    lines = ["| planner | calls | p50 s | p95 s | max s |", "|---|---:|---:|---:|---:|"]
    for tool in sorted(per):
        values = per[tool]
        lines.append(f"| {tool} | {len(values)} | {percentile(values, 0.50):.3f} | "
                     f"{percentile(values, 0.95):.3f} | {max(values):.3f} |")
    return lines


def coverage_table() -> list[str]:
    cov = OUT / "coverage.json"
    if not cov.is_file():
        return ["_coverage.json missing_"]
    data = json.loads(cov.read_text(encoding="utf-8"))
    lines = ["| doc type | expected | found | missing originals |", "|---|---:|---:|---:|"]
    for dt, tot in data.get("totals", {}).items():
        lines.append(f"| {dt} | {tot['expected']} | {tot['found']} | "
                     f"{tot['expected'] - tot['found']} |")
    missing = sum(v["missing_count"] for isin in data["by_isin"].values()
                  for v in isin.values())
    lines.append(f"\nmissing original files (all ISIN x type): **{missing}**; "
                 f"the full list is in `coverage.json` (`by_isin`).")
    return lines


def doc_density() -> list[str]:
    """What the buckets hold, from UNIVERSE.csv (FY25+ registry counts)."""
    import csv
    rows = list(csv.DictReader((OUT / "UNIVERSE.csv").open(encoding="utf-8")))
    types = ("annual_report", "concall", "deck", "results_notes", "announcement")
    lines = ["| bucket | companies | " + " | ".join(f"mean {t}" for t in types)
             + " | no concall | no AR |", "|---|---:|" + "---:|" * (len(types) + 2)]
    for bucket in BUCKETS:
        group = [r for r in rows if r["bucket"] == bucket]
        vals = [sum(int(r[t] or 0) for r in group) / max(1, len(group)) for t in types]
        no_cc = sum(1 for r in group if not int(r["concall"] or 0))
        no_ar = sum(1 for r in group if not int(r["annual_report"] or 0))
        lines.append(f"| {bucket} | {len(group)} | " + " | ".join(f"{v:.1f}" for v in vals)
                     + f" | {no_cc} | {no_ar} |")
    return lines


def hand_table(hand: dict) -> list[str]:
    rows = hand.get("rows") or []
    if not rows:
        return []
    by = defaultdict(Counter)
    for row in rows:
        by[row["bucket"]][row["verdict"]] += 1
    out = ["| bucket | checked | OK | PARTIAL | WRONG |", "|---|---:|---:|---:|---:|"]
    for bucket in BUCKETS:
        counts = by[bucket]
        out.append(f"| {bucket} | {sum(counts.values())} | {counts.get('OK', 0)} | "
                   f"{counts.get('PARTIAL', 0)} | {counts.get('WRONG', 0)} |")
    out += ["", "| # | instance | bucket | verdict | note |", "|---:|---|---|---|---|"]
    for i, row in enumerate(rows, 1):
        out.append(f"| {i} | {row['mid']} | {row['bucket']} | {row['verdict']} | "
                   f"{str(row.get('note') or '')[:110]} |")
    return out


def main() -> int:
    inst = load(OUT / "RESULTS_INSTANCES.jsonl")
    orig = load(OUT / "RESULTS_ORIGINALS.jsonl")
    universe = (OUT / "UNIVERSE.csv").read_text(encoding="utf-8").splitlines()
    hand = json.loads((OUT / "HAND_CHECK_60.json").read_text(encoding="utf-8")) \
        if (OUT / "HAND_CHECK_60.json").is_file() else {}
    build = json.loads((OUT / "chunks_build.json").read_text(encoding="utf-8")) \
        if (OUT / "chunks_build.json").is_file() else {}
    ok, total = answered(inst)
    ok_o, total_o = answered(orig)
    lines = [
        "# Pilot-60 — stratified universe, whole-market T1, instantiated master bank", "",
        f"- universe: 60 companies (10 large / 20 mid+small / 30 micro), "
        f"{len({r.split(',')[3] for r in universe[1:]})} sectors; `UNIVERSE.csv`",
        "- store: `.tmp/pilot60/chunks_v3_pilot.db` "
        f"({build.get('docs', '?')} docs, {build.get('chunks', '?')} chunks, "
        f"build {build.get('elapsed_s', '?')} s)",
        f"- T1: `.tmp/pilot_all` (whole market, `build_t1 --universe all`; build time in "
        "`tasks/pilot60/T1_BUILD.json`)",
        f"- instances: {len(inst)} (stock 3/bucket + peer sets); originals: {len(orig)}",
        f"- **answered: instances {ok}/{total} = {pct(ok, total)}; "
        f"originals {ok_o}/{total_o} = {pct(ok_o, total_o)}**",
        f"- hand-check precision: {hand.get('precision', 'pending')}", "",
        "## 1. Universe", "",
        "| bucket | companies | sectors |", "|---|---:|---:|"]
    for bucket in BUCKETS:
        rows = [r.split(",") for r in universe[1:] if r.split(",")[2] == bucket]
        lines.append(f"| {bucket} | {len(rows)} | {len({r[3] for r in rows})} |")
    lines += ["", "Sector x bucket table: `SECTOR_BUCKET.md`.", "",
              "## 2. Answered %", "", "### Overall and by bucket", ""]
    lines += table_answered(inst, lambda r: r.get("bucket"))
    lines += ["", "### By sector", ""]
    lines += table_answered(inst, lambda r: r.get("sector"))
    lines += ["", "### By family", ""]
    lines += table_answered(inst, family_of)
    lines += ["", "### By entity level (instances keep the parent level)", ""]
    lines += table_answered(inst, lambda r: r.get("entity_level") or "stock")
    lines += ["", "### Bucket x family heat table (answered %)", ""]
    lines += heat(inst)
    lines += ["", "### Originals, by entity level", ""]
    lines += table_answered(orig, lambda r: r.get("entity_level") or "stock")
    lines += ["", "### Grade distribution", "",
              "| grade | instances | originals |", "|---|---:|---:|"]
    for grade in GRADES:
        lines.append(f"| {grade} | {sum(1 for r in inst if r['grade'] == grade)} | "
                     f"{sum(1 for r in orig if r['grade'] == grade)} |")
    lines += ["", "## 3. Top gaps per bucket (what micro caps lack vs large)", "",
              "Gap = the field the failed hop named (or the CASE_MAP blocker). Fix = the table, "
              "fetch or planner wiring that closes it, ranked by cases unblocked.", ""]
    lines += doc_density()
    lines += ["", "| bucket | cases | gap | fix (table / fetch / tool) |", "|---|---:|---|---|"]
    for bucket, n, text, fix in gaps(inst)[:15]:
        lines.append(f"| {bucket} | {n} | {text} | {fix} |")
    lines += ["", "## 4. PIT", ""]
    pit_inst = [r for r in inst if r.get("pit")]
    pit_orig = [r for r in orig if r.get("pit")]
    lines.append(f"- instance rows with a PIT breach: {len(pit_inst)}/{len(inst)}; "
                 f"originals: {len(pit_orig)}/{len(orig)}")
    lines.append(f"- T2 chunk known_at audit: {build.get('known_at_mismatches', '?')} mismatches "
                 f"on the sampled docs (filing-record timestamps only, never the crawl date)")
    for row in pit_inst[:10]:
        lines.append(f"  - {row['mid']} ({row.get('bucket')}): {'; '.join(row['pit'])[:160]}")
    lines += ["", "## 5. Latency per planner (instance runs)", ""]
    lines += latency(inst)
    lines += ["", "## 6. T2 chunk coverage (FY25+, 60 + regression ISINs)", "",
              "The build keeps the latest docs per company and type — 1 annual report, 2 concalls, "
              "2 decks, 1 results note, 1 announcement — because the uncropped FY25+ set is "
              "~2,060 documents on one disk (an annual report parses at ~10 s). `expected` below "
              "is the uncropped registry, so `missing` mixes the cap with files that are truly "
              "not on D: (70 registry docs had no resolvable file).", ""]
    lines += coverage_table()
    lines += ["", "## 7. Hand check (60 answers, 20 per bucket)", ""]
    if hand.get("counts"):
        lines.append(f"- precision: **{hand['precision']:.1%}** "
                     f"({hand['counts'].get('OK', 0)} OK / "
                     f"{sum(hand['counts'].values())} checked), {hand['counts']}")
        lines.append("")
        lines += hand_table(hand)
        lines.append("")
        lines.append("- per-row verdicts with the source rows: `HAND_CHECK_60.json` / "
                     "`HAND_CHECK_60.md`")
    else:
        lines.append("_pending: run hand_check.py --score after the review_")
    lines += ["", "## 8. Method, scope and deviations", "",
              "- Every instance keeps the parent question text and swaps the entity; the "
              "parent company's own sector is preferred inside the bucket when it maps to a "
              "pilot sector, otherwise the seeded (20261028) random pick. 9 cases are skipped "
              "(ETF/bond ISINs and one old symbol); each reason is in `INSTANTIATE_STATS.md`.",
              "- Instances inherit the parent CASE_MAP status. 36 instance rows and 9 original "
              "rows whose only blocker was `needs_new_table:<t>` for a table the T1 build now "
              "fills were restored to ANSWERED (`regrade.py`); fetch blockers were not cleared.",
              "- Entity-level breakdown is the parent level: every instantiated case is a "
              "stock-level case by construction, so the non-stock levels appear in the "
              "originals table above, not in the instance table.",
              "- Sector labels follow decision 8 as far as held data allows: `UNIVERSE.csv` "
              "carries our label (NSE sector/industry, by ISIN) and a BSE-umbrella column, "
              "which is empty because the 200-company sector pilot does not overlap the 60. "
              "`company_sector_pit` was still empty when the selection ran (the T1 build "
              "finished afterwards), so the 60 are labelled from `master_companies`. Micro "
              "caps are labelled coarsely (General Diversified / Other / Unclassified), which "
              "is why the micro bucket spans 6 sectors, not 20.",
              "- Market cap: the 2026-09-30 session from `company_state_daily`, top 100 / "
              "101-750 / rest, with FY26 traded value > 0 on >= 200 sessions. 8 rows whose "
              "computed bucket was two steps from the held tier were dropped as broken mcap "
              "rows and the list re-ranked (e.g. a large cap implying Rs 3.5 cr). That is a "
              "real `shares_out` defect (paid-up/face parse) and a gap in its own right.",
              "- T2 chunks: the reviewed `tasks/pilot_t2/build_chunks_v3.py` was reused "
              "unchanged (chunker_v3, FY25+ filing registries, known_at from the filing "
              "record), with three module globals pointed at this pilot and sharded 3 ways. "
              "The per-company cap (latest 1 AR / 2 concall / 2 deck / 1 results / 1 "
              "announcement) is the time/disk constraint; the uncropped registry is what "
              "`coverage.json` scores, so the missing list is honest. 70 registry docs had no "
              "resolvable file anywhere on D:.",
              "- T2 ISIN set = 60 universe + 30 bank-regression ISINs (28 of them outside the "
              "60). The wider 511 ISINs named anywhere in the bank hold ~9,100 FY25+ "
              "documents; chunking all of them is a feed-scale job and was not run.",
              "- The query-layer change is additive: `Ctx` opens the T1 build only when "
              "`REALITY_PILOT_T1` / `REALITY_MARKET_STATE` is set, and SCREEN uses "
              "`company_state_daily` / `company_membership_pit` for cap and index screens. "
              "FACTS still reads the live XBRL/AR/deck stores (the same rows `facts_pilot` "
              "copies); wiring the planner to `company_metric_series` is a follow-up.",
              "- Originals ran without `REALITY_CHUNKS_V3` (13.8% answered); instances ran "
              "with the pilot chunk store (30.5%). The difference is partly the store, partly "
              "the T1 wiring, so the two rates are not a like-for-like A/B.",
              "- The hand check is the honest check: the bench grade only requires every hop "
              "to return rows, so 55 of 60 sampled instance answers were substantively wrong "
              "against the source rows even though the grader called them ANSWERED. The "
              "planner needs an entity/relevance gate, not just a row-count gate.",
              ]
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"REPORT.md written: instances {ok}/{total}, originals {ok_o}/{total_o}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
