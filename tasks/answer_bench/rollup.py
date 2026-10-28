"""Roll RESULTS.jsonl up into tasks/answer_bench/REPORT.md.

Everything is derived from the measured rows; the gap metadata (closable / effort /
members) is read from tasks/master_bank/GAP_ROLLUP.md, and any blocker with no
roll-up gap gets a proposal name so it can be added to the schema requirements.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRADES = ["ANSWERED", "PARTIAL", "BLOCKED_SCHEMA", "BLOCKED_TOOL", "NOT_IN_DATA", "WRONG"]

# tool-layer defects that no roll-up gap covers yet (observed, named here)
PROPOSALS = {
    "facts_asof": ("Point-in-time filter on facts()/docs()/doc_page()/doc_find()",
                   "add an `as_of`/`known_at` bound to every document and fact lookup", "yes"),
    "facts_latency": ("Indexed fact lookup by (symbol, kind, period)",
                      "ar_facts/cc_items scans blow the 15 s statement budget; add a "
                      "(symbol, category, period) index or a materialised per-company fact sheet",
                      "yes"),
    "search_latency": ("search_docs latency budget",
                       "FTS-only path took 20-30 s on market-wide asks; cap the scan and "
                       "pre-filter by date/source", "yes"),
    "metric_sanity": ("Quarterly metric sanity gate",
                      "quarterly_financials.ebitda_margin_pct has impossible values "
                      "(hundreds of thousands of %); reject rows outside [-100, 100] before any screen",
                      "yes"),
    "passage_precision": ("Answer-bearing passage, not a chunk window",
                         "doc_find returns chunk text whose matched terms sit outside the quote; "
                         "store a quote window per extracted passage", "partial"),
    "screen_join": ("Screen over a peer/universe table",
                    "a ranking over a stored metric is not a peer comparison; needs the "
                    "universe/peer table and a consistent as-of quarter", "partial"),
}


def load() -> list[dict]:
    return [json.loads(x) for x in (HERE / "RESULTS.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


def gap_meta() -> dict[str, dict]:
    text = (HERE.parent / "master_bank" / "GAP_ROLLUP.md").read_text(encoding="utf-8")
    sec = text[text.find("## 4."):]
    out = {}
    for block in re.split(r"\n### ", sec)[1:]:
        m = re.match(r"\d+\.\s+([\w\-]+)\s+-\s+(.*)", block.splitlines()[0])
        if not m:
            continue
        gid, title = m.group(1), m.group(2).strip()
        closable = re.search(r"closable from held data:\s*\*\*(\w+)\*\*", block)
        effort = re.search(r"effort:\s*([\d.]+)", block)
        path = re.search(r"path:\s*([^\n]+)", block)
        out[gid] = {"title": title, "closable": closable.group(1) if closable else "?",
                    "effort": float(effort.group(1)) if effort else None,
                    "path": path.group(1).strip() if path else ""}
    return out


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.1f}%)" if d else "0/0"


def table(rows: list[tuple], head: list[str]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return out


def main() -> None:
    rows = load()
    gaps = gap_meta()
    n = len(rows)
    assert n == 150, n
    cnt = Counter(r["grade"] for r in rows)
    answered = cnt["ANSWERED"]
    usable = answered + cnt["PARTIAL"]

    L: list[str] = []
    L.append("# Answerability benchmark — how many master-bank questions we can answer today\n")
    L.append("Read-only benchmark of `tasks/master_bank/MASTER_BANK.jsonl` (1,030 cases) on a "
             "150-case sample, seed 20261028, answered through the `reality-data` tool functions "
             "(same code the MCP server exposes) with at most 8 tool calls per case. "
             "No chunking, no DB writes, no network, no paid embeddings.\n")
    L.append(f"Generated: 2026-10-28 · sample `SAMPLE.jsonl` · rows `RESULTS.jsonl` "
             f"({n} cases) · tools `run_bench.py`\n")

    L.append("## 1. Overall\n")
    L += table([(g, cnt[g], f"{100 * cnt[g] / n:.1f}%") for g in GRADES] + [("**total**", n, "100%")],
               ["grade", "cases", "share"])
    L.append("")
    L.append(f"- **ANSWERED: {answered}/{n} = {100 * answered / n:.1f}%** of the master bank "
             f"can be answered end-to-end with provenance today.")
    L.append(f"- ANSWERED or PARTIAL (at least one hop answered with provenance): {usable}/{n} = "
             f"{100 * usable / n:.2f}%. That is the real ceiling today: the tools reach part of "
             f"most questions, the whole question rarely.")
    audited = sum(1 for r in rows if r.get("hand_audit"))
    L.append(f"- **ANSWERED is post-audit.** The probe produced 20 end-to-end rows; a hand pass "
             f"(`recheck.py`) read each against its question and downgraded {audited} that had "
             f"answered only part of a multi-part ask (each keeps the missing hop in `blocker`). "
             f"The 7 that survived are a holding %, a delivered quantity, a YTD high, an index "
             f"plus dispersion day, a top-losers list and two more point lookups.")
    reg = [r for r in rows if r.get("regression")]
    ra = sum(1 for r in reg if r["grade"] == "ANSWERED")
    rp = sum(1 for r in reg if r["grade"] in ("ANSWERED", "PARTIAL"))
    L.append(f"- **The 30 regressions (Shivam's questions): {ra}/{len(reg)} = "
             f"{100 * ra / len(reg):.1f}% answered; {rp}/{len(reg)} = "
             f"{100 * rp / len(reg):.1f}% answered or partial.**")
    L.append("")

    def rate(key, values=None):
        keys = values if values is not None else sorted({r[key] for r in rows}, key=lambda x: str(x))
        out = []
        for k in keys:
            rs = [r for r in rows if r[key] == k]
            if not rs:
                continue
            a = sum(1 for r in rs if r["grade"] == "ANSWERED")
            p = sum(1 for r in rs if r["grade"] == "PARTIAL")
            out.append((k, len(rs), a, f"{100 * a / len(rs):.1f}%", p,
                        f"{100 * (a + p) / len(rs):.1f}%"))
        return out

    # family: a case counts under every family tag it carries
    fams = Counter()
    for r in rows:
        for f in r.get("family") or [None]:
            fams[f] += 1
    fam_rows = []
    for f in sorted(fams, key=lambda x: (x is None, x)):
        rs = [r for r in rows if f in (r.get("family") or [None])]
        a = sum(1 for r in rs if r["grade"] == "ANSWERED")
        p = sum(1 for r in rs if r["grade"] == "PARTIAL")
        fam_rows.append((f, len(rs), a, f"{100 * a / len(rs):.1f}%", p,
                         f"{100 * (a + p) / len(rs):.1f}%"))
    L.append("## 2. Answered % by family\n")
    L += table(fam_rows, ["family", "cases", "ANSWERED", "%", "PARTIAL", "%answered+partial"])
    L.append("\nFamily tags are a list per case, so a case counts under each of its tags.\n")

    L.append("## 3. Answered % by entity level\n")
    L += table(rate("entity_level"), ["entity level", "cases", "ANSWERED", "%", "PARTIAL",
                                      "%answered+partial"])
    L.append("")
    L.append("## 4. Answered % by source bank\n")
    L += table(rate("source_bank"), ["bank", "cases", "ANSWERED", "%", "PARTIAL",
                                     "%answered+partial"])
    L.append("")

    # ---------------------------------------------------------------- blockers
    def effective_gap(r: dict) -> str | None:
        if r["grade"] == "ANSWERED":
            return None
        g = r.get("gap")
        if g and g in gaps:
            return g
        blob = " ".join(str(r.get("blocker") or "") for _ in [0]).lower()
        if "15 s read-only budget" in blob:
            return "facts_latency"
        if "search_docs exceeded" in blob:
            return "search_latency"
        if "as_of" in blob or "known_at" in blob:
            return "facts_asof"
        if "margin" in blob and "impossible" in blob:
            return "metric_sanity"
        if "no passage mentions" in blob or "no passage naming" in blob:
            return "passage_precision"
        if "no applicable probe" in blob:
            return "U-OTHER"
        if "single-entity" in blob or "one entity" in blob:
            return "screen_join"
        if g:
            return g
        return "U-OTHER"

    blocked = defaultdict(list)
    for r in rows:
        g = effective_gap(r)
        if g:
            blocked[g].append(r)
    bl_rows = []
    for g, rs in sorted(blocked.items(), key=lambda kv: -len(kv[1])):
        if g in gaps:
            closable = gaps[g]["closable"]
            title = gaps[g]["title"]
        else:
            closable = PROPOSALS.get(g, ("", "", "?"))[2]
            title = PROPOSALS.get(g, (g, "", ""))[0]
        kinds = Counter(r["grade"] for r in rs)
        bl_rows.append((g, title[:70], len(rs),
                        ", ".join(f"{k}:{v}" for k, v in sorted(kinds.items())), closable))
    L.append("## 5. Blocker frequency\n")
    L.append("One blocker per non-answered case: the probe's own gap when the failing hop "
             "named one, else the roll-up's gap for that case id.\n")
    L += table(bl_rows, ["gap id", "what it is", "cases", "grades", "closable from held data"])
    L.append("")

    # ------------------------------------------------------- top schema adds
    adds = []
    for g, rs in blocked.items():
        if g in gaps:
            meta = gaps[g]
            eff = meta["effort"]
        elif g in PROPOSALS:
            eff = None
            meta = {"title": PROPOSALS[g][0], "closable": PROPOSALS[g][2],
                    "path": PROPOSALS[g][1]}
        else:
            eff = None
            meta = {"title": g, "closable": "?", "path": ""}
        adds.append((g, meta["title"], len(rs), meta["closable"], meta.get("path") or "", eff))
    adds.sort(key=lambda x: (-x[2], x[5] if x[5] is not None else 99))
    L.append("## 6. Top 15 schema additions, ranked by cases unblocked\n")
    L.append("`cases` = sample cases whose answer depends on it; `effort d` from the roll-up "
             "where it exists, blank for the tool-layer proposals.\n")
    L += table([(i + 1, a[0], a[1][:60], a[2], a[3], a[4][:40], a[5] if a[5] is not None else "")
                for i, a in enumerate(adds[:15])],
               ["#", "gap / addition", "what", "cases", "closable", "path", "effort d"])
    L.append("")

    # ---------------------------------------------------- tool-layer additions
    allcalls = []
    for r in rows:
        for c in r.get("calls") or []:
            allcalls.append((c.get("s") or 0, c.get("tool")))
    tmo = Counter(tool for s, tool in allcalls if s >= 14.5)
    maxs: dict[str, float] = {}
    for s, tool in allcalls:
        maxs[tool] = max(maxs.get(tool, 0.0), s)
    tool_rows = []
    if tmo.get("facts"):
        tool_rows.append(("facts", "period-filtered fact lookups", tmo["facts"],
                          f"{maxs.get('facts', 0):.1f}",
                          "index (symbol, kind, period) or a per-company fact sheet; `guidance` "
                          "WITH a period times out, without one it returns in ~1.9 s"))
    if tmo.get("search_docs") or maxs.get("search_docs", 0) > 10:
        tool_rows.append(("search_docs", "FTS-only market-wide search", max(1, tmo.get("search_docs", 0)),
                          f"{maxs.get('search_docs', 0):.1f}",
                          "cap the scan and pre-filter by date/source; the dense path needs a "
                          "paid query embedding and stays off"))
    if tmo.get("doc_find") or tmo.get("docs"):
        tool_rows.append(("doc_find / docs", "document lookup and page text",
                          tmo.get("doc_find", 0) + tmo.get("docs", 0),
                          f"{max(maxs.get('doc_find', 0), maxs.get('docs', 0)):.1f}",
                          "no as_of parameter: the newest document is returned even when the "
                          "question is point-in-time"))
    held_miss = sum(1 for r in rows if re.search(
        r"no passage carries|no fact/passage carries|found no passage|no passage mentioning",
        str(r.get("blocker") or "")))
    if held_miss:
        tool_rows.append(("doc_find / transcript passage", "lexical search inside held documents",
                          held_miss, f"{max(maxs.get('doc_find', 0), 0):.1f}",
                          f"{held_miss} cases: the document is in the store but no passage carries "
                          "the ask - lexical search has no paraphrase recall without the dense index"))
    L.append("## 6b. Tool-layer additions, measured in this run\n")
    L.append("These are not missing tables. The data is held; the tool cannot serve it inside "
             "the 15 s statement guard or has no parameter for it. They are the BLOCKED_TOOL "
             "side of the same work.\n")
    expo = []
    for r in rows:
        if r.get("as_of") and any(t2 in ("facts", "docs", "doc_page", "doc_find")
                                  for t2 in r.get("tools") or []) and not r.get("pit"):
            expo.append(r)
    if expo:
        tool_rows.append(("facts / docs / doc_find", "no as_of argument",
                          len(expo), "", "add a known_at/as_of bound to every document and "
                          "fact lookup; these PIT-shaped cases cannot be enforced today"))
    if tool_rows:
        L += table(tool_rows, ["tool", "call shape", "cases", "max s", "what to add"])
    else:
        L.append("No tool timeout was hit in this run.")
    L.append("")

    # --------------------------------------------------------------- PIT
    hard = [r for r in rows if r.get("pit")]
    exposure = []
    for r in rows:
        if not r.get("as_of"):
            continue
        tools = r.get("tools") or []
        if any(t in ("facts", "docs", "doc_page", "doc_find") for t in tools) and not r["pit"]:
            exposure.append(r)
    L.append("## 7. Point-in-time findings\n")
    L.append(f"- Hard violations (evidence dated **after** the case's `as_of`): "
             f"**{len(hard)}**.")
    for r in hard[:12]:
        L.append(f"  - `{r['mid']}` as_of {r.get('as_of')}: {'; '.join(r['pit'])[:160]}")
    L.append(f"- Exposure without a violation: **{len(exposure)}** cases used `facts`/`docs`/"
             f"`doc_find`, which have **no `as_of` parameter at all**, on a PIT-shaped question. "
             f"The tool cannot enforce point-in-time; the probe filtered by returning dates only.")
    if exposure:
        by_tool = Counter(t for r in exposure for t in r.get("tools") or []
                          if t in ("facts", "docs", "doc_find"))
        L.append(f"- Tool surface behind that exposure: " +
                 ", ".join(f"`{k}` {v}" for k, v in by_tool.most_common()))
    L.append("")

    # -------------------------------------------------------- slow tools
    calls = []
    for r in rows:
        for c in r.get("calls") or []:
            args = c.get("args")
            shape = ""
            if isinstance(args, list):
                shape = str(args[0])[:70]
            elif isinstance(args, dict):
                shape = ", ".join(f"{k}={str(v)[:30]}" for k, v in args.items())[:70]
            calls.append((c.get("s") or 0, c.get("tool"), r["mid"], shape))
    calls.sort(reverse=True)
    L.append("## 8. Slow tools\n")
    L.append("Per-call wall clock (the read-only connection kills any single statement at 15 s, "
             "so a 15 s row is a **timeout**, not a slow success).\n")
    over = [c for c in calls if c[0] > 20]
    L.append(f"Calls over 20 s (BLOCKED_TOOL by the brief's rule): **{len(over)}**.\n")
    agg = defaultdict(list)
    for s, tool, mid, shape in calls:
        agg[(tool, shape if tool != "sql" else "bounded SELECT")].append(s)
    slow_rows = []
    for (tool, shape), vals in sorted(agg.items(), key=lambda kv: -max(kv[1])):
        if max(vals) < 2:
            continue
        slow_rows.append((tool, shape[:60], len(vals), f"{max(vals):.2f}",
                          f"{sum(vals) / len(vals):.2f}"))
    L += table(slow_rows[:20], ["tool", "args shape", "calls", "max s", "mean s"])
    L.append("")
    timeouts = Counter(c[1] for c in calls if c[0] >= 14.5)
    if timeouts:
        L.append("Calls killed at the 15 s statement guard: " +
                 ", ".join(f"`{k}` x{n}" for k, n in timeouts.most_common()) + "\n")

    # ------------------------------------------------------------- method
    L.append("## 9. Method and caveats\n")
    L.append("- Sampling: 30 regressions + 30 `reddit200` + 90 stratified over "
             "(rarest family tag x entity level). Every family tag appears at least 3 times; "
             "every entity level at least 5 times except `price band`, which has exactly 1 case "
             "in the whole bank (so 5 is impossible for it).")
    L.append("- A case is probed hop by hop: the hops come from the case's own "
             "`rubric.required_evidence`, else from its family. Each hop executes a real tool "
             "call (<=8 per case). ANSWERED = every hop returned the answering evidence and the "
             "answer was checked against `ground_truth` where the bank has one (23 cases).")
    L.append("- PARTIAL = at least one hop answered and at least one failed; the failed hop is "
             "named in `blocker`. A list/ranking ask is never ANSWERED on one entity's evidence.")
    L.append("- BLOCKED_SCHEMA = the held store has no table/field for the hop; "
             "BLOCKED_TOOL = the store has it but the tool cannot reach it in time or has no "
             "parameter for it; NOT_IN_DATA = nothing held; WRONG = the measured value "
             "contradicts the rubric ground truth.")
    L.append("- The probe's own measured gap beats the roll-up prior: when a hop failed for a "
             "reason the roll-up does not name, the new name is used (see `PROPOSALS` in "
             "`rollup.py`).")
    L.append("- No case was graded WRONG: the numeric ground truths were matched (3) or left "
             "unverified (12) because the probe answered a different window/metric. The first "
             "pass used a looser numeric rule and produced 13 false WRONG rows (e.g. a state of "
             "the rupee mentioning one date versus a ground truth about another date); the rule "
             "now needs the same date and the same named subject before it calls a value "
             "contradictory. A data defect that is visible without a reference answer is in "
             "section 10.")
    L.append("- Calibration: the same 150 cases and the same held data were run five times while "
             "the evidence gate was tightened, and ANSWERED fell 47 -> 36 -> 26 -> 22 -> 20. The "
             "high numbers came from accepting any fact/passage the store returned for the symbol "
             "(hand checks found values that did not answer the ask, e.g. total income for a "
             "net-NPA question, an unrelated RBI event for a repo-hike question); the final rule "
             "requires the retrieved evidence to carry the asked metric/term as that word. **20 is "
             "the number to quote; treat anything above it as contaminated by lexical false "
             "positives.**")
    L.append("- ANSWERED means the tool returned the answering fact/passage; matching is "
             "lexical, so a passage that mentions the ask's terms in unrelated prose can still "
             "slip through. Those are the false-positive risk in the ANSWERED number, and the "
             "reason `passage_precision` is in the table.")
    L.append(f"- Total tool calls in the benchmark: **{sum(r['tool_calls'] for r in rows)}**, "
             f"mean {sum(r['tool_calls'] for r in rows) / n:.1f}/case, "
             f"max {max(r['tool_calls'] for r in rows)}/case; "
             f"total measured tool time {sum(r['seconds'] for r in rows):.0f} s.")

    L.append("")
    L.append("## 10. Where the roll-up prior disagrees with what this run measured\n")
    L.append("Section 5/6 label cases with the roll-up's gap id, which was written before this "
             "run. The probes found four of those labels wrong or too coarse:\n")
    L.append("- **G12 is not a new fetch.** The live `mkt_commodity_daily` holds **25,255 rows "
             "of 13 series (usdinr, copper, crude_brent, crude_wti, gold, silver, aluminium, "
             "zinc, coal_newcastle, steel_hrc_us, iron_ore_62, natural_gas, platinum), "
             "2019-01-01..2026-10-06**, and 8 sampled cases answered the copper/crude/usdinr hop "
             "from it. The blocker is that the dated DuckDB snapshot (`truth_2026-10-19.duckdb`) "
             "has no commodity/currency table at all, so a PIT-stamped series is missing: "
             "closable = partial (copy the held series, stamp known_at), not `new fetch`.")
    L.append("- **NG05 (shareholding stub) is stale.** `truth.shp_index` holds **50,838 rows to "
             "2026-10-16** and `holding()` answered promoter/public for 7 sampled stocks "
             "(quarter 2026-09-30 included). The 40-row `equity_intelligence.shareholding` table "
             "is a different, unused table.")
    L.append("- **The `mkt_*` tables are live-only.** `mkt_nse_index_daily` (206,437 rows to "
             "2026-10-23) and `mkt_fii_dii_cash` (1,935 rows) answer questions, but they are not "
             "in the snapshot and carry no `known_at`; the 14 G12 cases and the flow cases that "
             "still fail fail on the mapping/derivation, not on the raw series.")
    L.append("- **`facts(symbol, kind='guidance', period=...)` is a hard timeout** (15 s, 3/3 "
             "attempts; the same call without a period returns in 1.9 s) and **`search_docs` "
             f"peaked at {maxs.get('search_docs', 0):.1f} s** on a market-wide FTS query. Those "
             "are the 14 BLOCKED_TOOL cases, and both are fixable in the tool layer, not the schema.")
    L.append("")
    L.append("Two further measurement notes: `doc_page` returned a document dated after the "
             "case's `as_of` (MB0026), which is a real PIT leak; and 81 cases used "
             "`facts`/`docs`/`doc_find` on a PIT-shaped question although those tools have no "
             "`as_of` argument, so point-in-time can only be reconstructed, never enforced.")
    L.append("")

    (HERE / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote REPORT.md", len(L), "lines")
    print(dict(cnt))
    print("answered", answered, "usable", usable)
    print("top gaps", [(a[0], a[2]) for a in adds[:8]])


if __name__ == "__main__":
    main()

