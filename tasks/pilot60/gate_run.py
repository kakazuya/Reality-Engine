"""The entity/ask/period gate run: hand-60 calibration, 40-row precision, full bank.

    python tasks/pilot60/gate_run.py hand60     # rerun the 60 hand-checked rows
    python tasks/pilot60/gate_run.py bank       # 1,073 originals + 1,608 instances
    python tasks/pilot60/gate_run.py sample40   # draw 40 gated ANSWERED rows
    python tasks/pilot60/gate_run.py report     # GATE_RUN_2026-10-29.md

Everything is read-only on the databases (the pilot stores on D: are opened
immutable); the outputs are written next to this script / in tasks/answer_bench.
One bench process at a time (the runner peaks at ~1.8 GB).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BENCH = REPO / "tasks" / "answer_bench"
OUT = REPO / "tasks" / "pilot60"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(BENCH))

# SSD copies: the D: (HDD) copies thrash on the bench's random reads.
PILOT = r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\pilot\pilot60"
os.environ.setdefault("REALITY_CHUNKS_V3", str(Path(PILOT) / "chunks_v3_pilot.db"))
os.environ.setdefault("REALITY_PILOT_T1", PILOT)
os.environ.setdefault("REALITY_MACRO_PILOT_DB",
                      r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\pilot\macro_all.db")

HAND_JSON = OUT / "HAND_CHECK_60.json"
HAND_RESULTS = OUT / "RESULTS_HAND60.jsonl"
BANK_ORIGINALS = BENCH / "GATE_RESULTS_originals.jsonl"
BANK_INSTANCES = BENCH / "GATE_RESULTS_instances.jsonl"
SAMPLE40 = OUT / "GATE_SAMPLE40.jsonl"
SEED40 = 20261030


def _load(path: Path) -> list[dict]:
    """Rows of a jsonl result file; a truncated last line (killed process) is skipped."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"skip truncated line in {path.name}", flush=True)
    return out


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")


def cases_by_mid() -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    bank = {row["mid"]: row for row in _load(REPO / "tasks" / "master_bank" / "MASTER_BANK.jsonl")}
    inst = {row["mid"]: row for row in _load(OUT / "INSTANCES.jsonl")}
    return bank, inst


def _ctx_and_cmap(inst: dict[str, dict]):
    import run_v0
    from reality_engine.query import Ctx
    cmap = run_v0.case_map()
    for mid, case in inst.items():
        parent = cmap.get(case.get("parent_mid") or "", {})
        cmap.setdefault(mid, parent)
    ctx = Ctx()
    return ctx, cmap


def _warm() -> None:
    try:
        sys.path.insert(0, str(REPO / "plugins" / "reality-data" / "server"))
        import search_docs as _search_docs
        _search_docs.warm()
    except Exception:  # noqa: BLE001 - corpus search degrades to FTS
        pass


def _run(cases: list[dict], label: str, out_path: Path | None,
         skip: set[str] | None = None, append: bool = False) -> list[dict]:
    import run_v0
    ctx, cmap = _ctx_and_cmap({case["mid"]: case for case in cases})
    _warm()
    rows = []
    started = time.perf_counter()
    skip = skip or set()
    mode = "a" if append else "w"
    handle = out_path.open(mode, encoding="utf-8") if out_path is not None else None
    try:
        for i, case in enumerate(cases, 1):
            if case.get("mid") in skip:
                continue
            try:
                print(f"START {case.get('mid')}", flush=True)
                row = run_v0.run_case(case, ctx, cmap)
            except Exception as exc:  # noqa: BLE001 - a planner bug is data, not a crash
                row = {"mid": case.get("mid"), "grade": "PARTIAL", "answer": "",
                       "seconds": 0.0, "tool_calls": 0, "tools": [],
                       "blocker": f"runner error: {type(exc).__name__}: {exc}",
                       "hops_ok": [], "hops_failed": [], "hops_na": [], "pit": [],
                       "gate": [], "family": case.get("family"),
                       "question": case.get("question"), "as_of": case.get("as_of"),
                       "period": case.get("period"), "entity_level": case.get("entity_level"),
                       "source_bank": case.get("source_bank"), "regression": bool(
                           case.get("regression"))}
            row["bucket"] = case.get("bucket")
            row["sector"] = case.get("sector")
            row["kind"] = case.get("kind", "original")
            row["parent_mid"] = case.get("parent_mid")
            rows.append(row)
            if handle is not None:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
            if i % 25 == 0 or i == len(cases):
                print(f"{label} {i}/{len(cases)} {row.get('seconds')}s "
                      f"{(case.get('question') or '')[:60]}", flush=True)
    finally:
        if handle is not None:
            handle.close()
        ctx.close()
    print(f"{label}: {len(rows)} rows in {time.perf_counter() - started:.0f}s")
    return rows


# --------------------------------------------------------------------------
# hand-60 calibration
# --------------------------------------------------------------------------
GENERIC_MARKERS = ("corporate governance report", "business responsibility",
                   "financial statements", "directors report", "directors’ report",
                   "management discussion and analysis")


def classify_failure(note: str, row: dict) -> str:
    """The failure mode of one hand verdict (the gate reason first, then the note)."""
    answer = str(row.get("answer") or "").lower()
    gates = [str(run.get("gate") or "") for run in row.get("gate") or []]
    reasons = " ".join(gates)
    if "entity_match" in reasons:
        return "wrong_entity"
    if "period_match" in reasons:
        return "wrong_period"
    if any(marker in answer for marker in GENERIC_MARKERS) and \
            sum(1 for marker in GENERIC_MARKERS if marker in answer) >= 2:
        return "generic_text"
    if "ask_match" in reasons or "GATE" in reasons:
        return "wrong_metric"
    low = note.lower()
    if any(word in low for word in ("not products", "products not", "no product",
                                    "not the quarter", "not answered", "not a product",
                                    "does not address", "not mention", "no public",
                                    "no concept", "not 2026", "unrelated", "another metric")):
        return "ask_unaddressed"
    if any(word in low for word in ("answer gives", "answer returns", "answer is")):
        return "wrong_metric"
    return "unclassified"


def confusion(rows: list[dict]) -> str:
    """Hand verdict x strict grade table + the failure-mode counts."""
    hand = {row["mid"]: row for row in json.loads(
        HAND_JSON.read_text(encoding="utf-8"))["rows"]}
    table: dict[tuple[str, str], int] = Counter()
    modes: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        verdict = hand.get(row["mid"], {}).get("verdict", "?")
        table[(verdict, row["strict_grade"])] += 1
        if verdict != "OK":
            note = hand.get(row["mid"], {}).get("note", "")
            modes[verdict][classify_failure(note, row)] += 1
    grades = ["ANSWERED", "PARTIAL", "BLOCKED_SCHEMA", "BLOCKED_TOOL", "NOT_IN_DATA",
              "WRONG"]
    lines = ["| hand verdict | " + " | ".join(grades) + " | total |",
             "|---|" + "|".join("---" for _ in grades) + "|---:|"]
    for verdict in ("OK", "PARTIAL", "WRONG"):
        counts = [table.get((verdict, grade), 0) for grade in grades]
        lines.append(f"| {verdict} | " + " | ".join(str(n) for n in counts) +
                     f" | {sum(counts)} |")
    lines.append("")
    for verdict in ("WRONG", "PARTIAL"):
        lines.append(f"**{verdict} failure modes:** " + ", ".join(
            f"{mode} {count}" for mode, count in modes[verdict].most_common()))
    return "\n".join(lines)


def hand60() -> int:
    hand = {row["mid"]: row for row in json.loads(
        HAND_JSON.read_text(encoding="utf-8"))["rows"]}
    _, inst = cases_by_mid()
    cases = [inst[mid] for mid in hand if mid in inst]
    print(f"hand60: {len(cases)} cases, {len(hand) - len(cases)} missing from INSTANCES.jsonl")
    rows = _run(cases, "hand60", HAND_RESULTS)
    strict = _strict(cases, rows)
    print(confusion(strict))
    counts = Counter(row["strict_grade"] for row in strict)
    print(dict(counts))
    return 0


def _strict(cases: list[dict], rows: list[dict]) -> list[dict]:
    """Re-grade with the strict grader (bench grade + its own independent rules)."""
    import grade_v1
    by_mid = {case["mid"]: case for case in cases}
    index = grade_v1.DocIndex()
    print(f"strict grader doc index: {'snapshot' if index.ok else 'row-text fallback'}")
    out = []
    for row in rows:
        graded = grade_v1.grade_row(by_mid.get(row["mid"], {}), row, index)
        graded.update({key: row.get(key) for key in ("bucket", "sector", "kind",
                                                     "parent_mid", "question")})
        out.append(graded)
    _write(HAND_RESULTS.with_name("RESULTS_HAND60_strict.jsonl"), out)
    return out


# --------------------------------------------------------------------------
# full bank
# --------------------------------------------------------------------------
def bank(limit_originals: int | None = None, limit_instances: int | None = None,
         shard: int = 0, shards: int = 1, resume: bool = False,
         chunk: int = 0, skip_file: str | None = None) -> int:
    originals, inst = cases_by_mid()
    skip: set[str] = set()
    if skip_file and Path(skip_file).exists():
        skip = {line.strip() for line in Path(skip_file).read_text(encoding="utf-8")
                .splitlines() if line.strip()}
        print(f"skipping {len(skip)} known-crashing case(s): {', '.join(sorted(skip))}",
              flush=True)
    orig = list(originals.values())
    if limit_originals:
        orig = orig[:limit_originals]
    inst_rows = [case for case in inst.values() if case.get("kind") != "as_is"]
    if limit_instances:
        inst_rows = inst_rows[:limit_instances]
    print(f"bank: {len(orig)} originals, {len(inst_rows)} instances", flush=True)
    if shards > 1:
        orig = orig[shard::shards]
        inst_rows = inst_rows[shard::shards]
    orig_path = BENCH / ("GATE_RESULTS_originals.jsonl" if shards == 1
                         else f"GATE_RESULTS_originals_part{shard}.jsonl")
    inst_path = BENCH / ("GATE_RESULTS_instances.jsonl" if shards == 1
                         else f"GATE_RESULTS_instances_part{shard}.jsonl")
    for cases, path, label in ((orig, orig_path, "originals"),
                               (inst_rows, inst_path, "instances")):
        done = {row["mid"] for row in _load(path)} if resume else set()
        todo = [case for case in cases if case.get("mid") not in done
                and case.get("mid") not in skip]
        if chunk:
            todo = todo[:chunk]
        print(f"{label}: {len(done)} already done, {len(todo)} in this chunk", flush=True)
        if todo:
            _run(todo, label, path, append=bool(done and resume))
        if chunk and len(todo) == chunk and len(done) + len(todo) < len(cases):
            break  # one chunk per process: keep the RSS bounded
    return 0


# --------------------------------------------------------------------------
# 40-row precision sample
# --------------------------------------------------------------------------
def sample40() -> int:
    # The pool is every row the strict grader calls ANSWERED: the bench grade
    # answered, every part of the ask carried, no unrelated row, in period.
    orig = _load(BENCH / "GATE_RESULTS_originals_strict.jsonl")
    inst = _load(BENCH / "GATE_RESULTS_instances_strict.jsonl")
    if orig or inst:
        def gate_ok(row: dict) -> bool:
            return row.get("strict_grade") == "ANSWERED"
    else:  # not graded yet: fall back to the planner's own grade
        orig = _load(BENCH / "GATE_RESULTS_originals.jsonl")
        inst = _load(BANK_INSTANCES)

        def gate_ok(row: dict) -> bool:
            return row.get("grade") == "ANSWERED"
    rows = orig + inst
    hand = {row["mid"] for row in json.loads(
        HAND_JSON.read_text(encoding="utf-8"))["rows"]}
    answered = [row for row in rows if gate_ok(row) and row["mid"] not in hand]
    strata: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in answered:
        family = row.get("family") or []
        bucket = row.get("bucket") or row.get("entity_level") or "None"
        key = (str(bucket), f"F{family[0]}" if isinstance(family, list) and family else "F?")
        strata[key].append(row)
    rng = random.Random(SEED40)
    keys = sorted(strata)
    picked: list[dict] = []
    # round-robin across bucket x family so the sample is stratified, not the
    # 40 biggest strata; break by the seeded shuffle inside each stratum.
    pools = {key: rng.sample(strata[key], len(strata[key])) for key in keys}
    while len(picked) < 40 and any(pools.values()):
        for key in keys:
            if pools[key] and len(picked) < 40:
                picked.append(pools[key].pop())
    _write(SAMPLE40, picked)
    print(f"sample40: {len(picked)} rows from {len(answered)} gated ANSWERED "
          f"({len(strata)} strata) -> {SAMPLE40.name}")
    for row in picked:
        print(f"  {row['mid']:12s} {str(row.get('bucket') or row.get('entity_level')):10s} "
              f"F{(row.get('family') or ['?'])[0]} {row.get('question')[:60]}")
    return 0


#: Hand verdicts of the 57 non-OK rows of HAND_CHECK_60.json, classed by the
#: failure mode the note names (the gate's own view is printed next to it).
FAILURE_MODES = {
    "MB0001#L": "generic_text", "MB0002#L": "generic_text",
    "MB0010#L": "wrong_metric",
    "MB0022#L": "wrong_metric", "MB0023#L": "wrong_period",
    "MB0024#L": "wrong_metric", "MB0034#L": "wrong_metric",
    "MB0035#L": "wrong_metric", "MB0071#L": "wrong_metric",
    "MB0079#L": "wrong_period", "MB0086#L": "wrong_metric",
    "MB0089#L": "wrong_period", "MB0096#L": "wrong_period",
    "MB0099#L": "wrong_period", "MB0109#L": "wrong_metric",
    "MB0121#L": "wrong_metric", "MB0122#L": "wrong_metric",
    "MB0397#MS": "wrong_metric", "MB0441#MS": "wrong_metric",
    "MB0577#MS": "wrong_period", "MB0890#MS": "wrong_metric",
    "MB0899#MS": "wrong_metric", "MB0900#MS": "wrong_metric",
    "MB0901#MS": "wrong_metric", "MB0916#MS": "wrong_metric",
    "MB0944#MS": "wrong_metric", "MB0946#MS": "wrong_metric",
    "MB0951#MS": "wrong_metric", "MB0955#MS": "wrong_metric",
    "MB0956#MS": "wrong_metric", "MB0957#MS": "wrong_metric",
    "MB0961#MS": "wrong_metric", "MB0963#MS": "wrong_metric",
    "MB0964#MS": "wrong_metric", "MB0966#MS": "wrong_metric",
    "MB0968#MS": "wrong_metric", "MB0970#MS": "wrong_metric",
    "MB0530#MI": "wrong_metric", "MB0621#MI": "wrong_metric",
    "MB0863#MI": "wrong_metric", "MB1060#MI": "wrong_metric",
    "MB1061#MI": "wrong_metric", "MB1062#MI": "wrong_metric",
    "MB1063#MI": "wrong_metric", "MB0397#MI": "wrong_metric",
    "MB0441#MI": "wrong_metric", "MB0577#MI": "wrong_period",
    "MB0890#MI": "wrong_metric", "MB0899#MI": "wrong_metric",
    "MB0900#MI": "wrong_metric", "MB0901#MI": "wrong_metric",
    "MB0916#MI": "wrong_metric", "MB0944#MI": "wrong_metric",
    "MB0946#MI": "wrong_metric", "MB0951#MI": "wrong_entity",
    "MB0955#MI": "wrong_metric", "MB0956#MI": "wrong_metric",
}

#: Blocker pattern -> the table / wiring / fetch that closes it.
FIXES = [
    ("gate: ask_match", "planner wiring: the metric/concept alias table in "
                        "reality_engine/query/gate.py (extend ASK_CONCEPTS)"),
    ("ask_match", "planner wiring: extend ASK_CONCEPTS / route the named concept to a planner"),
    ("gate: period_match", "planner wiring: route the named quarter/month into the FACTS "
                           "period filter (router.period_bounds)"),
    ("period_match", "planner wiring: the named period -> FACTS period filter"),
    ("entity_match", "planner wiring: one entity-scope check per planner; rows must carry "
                     "the asked ISIN"),
    ("consensus", "no fetch: EXPECTATIONS is the company's own guidance by design"),
    ("EVENT", "fetch: event_day0 (15:30 session rule) + announcement dissemination index"),
    ("exchange_originals", "fetch: BSE/NSE original filing files"),
    ("company_sector_pit", "planned: wire RIPPLE's policy->sector hop to the T1 table"),
    ("company_segment_pnl", "planned: wire the segment hop to the T1 table"),
    ("company_cost_structure", "planned: wire the cost-structure hop to the T1 table"),
    ("RIPPLE", "fetch/table: macro claim target + sector transmission (T1 company_sector_pit)"),
    ("EVIDENCE", "table: chunks_v3 coverage for the ISIN/doc type (T2 build)"),
    ("FACTS", "table: the fact store for the asked metric (results_xbrl/ar_facts/deck)"),
    ("SERIES", "table: the price/index series for the entity/period"),
    ("SCREEN", "table: the universe/membership table for the screen"),
    ("COMPARE", "table: peer set / same-metric rows for the peers"),
    ("no source", "no fetch: the fact is not published (paid-only or out of scope)"),
]


def wilson_lower(ok: int, n: int, z: float = 1.96) -> float:
    if not n:
        return 0.0
    p = ok / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    spread = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return max(0.0, (centre - spread) / denom)


def _pct(a: int, b: int) -> str:
    return f"{a}/{b} = {100.0 * a / b:.1f}%" if b else "0/0"


def _table(header: list[str], body: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in body]
    return "\n".join(lines)


def _latency(values: list[float]) -> tuple[float, float, float]:
    if not values:
        return 0.0, 0.0, 0.0
    ordered = sorted(values)

    def pick(q: float) -> float:
        return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]
    return pick(0.5), pick(0.95), ordered[-1]


def _blockers(rows: list[dict], top: int = 15) -> str:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("strict_grade") == "ANSWERED":
            continue
        if row.get("gate_recomputed"):
            reason = row["gate_recomputed"][0]
        elif row.get("blocker"):
            reason = str(row["blocker"])
        elif row.get("strict_reasons"):
            reason = str(row["strict_reasons"][0])
        else:
            reason = "hop did not answer: " + "+".join(row.get("hops_failed") or ["no hop"])
        reason = re.sub(r"\(.*", "", reason).strip()[:80]
        groups[reason].append(row)
    body = []
    for reason, members in sorted(groups.items(), key=lambda item: -len(item[1]))[:top]:
        fix = next((fix for pattern, fix in FIXES if pattern in reason),
                   "planner wiring: route the ask to the planner that holds the field")
        body.append([len(members), reason, fix,
                     ", ".join(str(row.get("mid")) for row in members[:3])])
    return _table(["cases", "blocker (first failing check)", "fix", "examples"], body)


def grade_bank() -> int:
    """Apply the strict grader (which recomputes the gate) to the whole bank."""
    import grade_v1
    bank, inst = cases_by_mid()
    index = grade_v1.DocIndex()
    print(f"strict grader doc index: {'snapshot' if index.ok else 'row-text fallback'}",
          flush=True)
    for path, cases, out_name in (
            (BANK_ORIGINALS, bank, "GATE_RESULTS_originals_strict.jsonl"),
            (BANK_INSTANCES, inst, "GATE_RESULTS_instances_strict.jsonl")):
        rows = _load(path)
        graded = []
        for i, row in enumerate(rows, 1):
            case = cases.get(row["mid"]) or {}
            result = grade_v1.grade_row(case, row, index)
            result.update({key: row.get(key) for key in
                           ("bucket", "sector", "kind", "parent_mid", "entity_level",
                            "seconds", "pit_violations", "family", "question")})
            graded.append(result)
            if i % 100 == 0:
                print(f"{out_name} {i}/{len(rows)}", flush=True)
        _write(BENCH / out_name, graded)
        counts = Counter(row["strict_grade"] for row in graded)
        print(f"{out_name}: {len(graded)} rows {dict(counts)}", flush=True)
    return 0


def dump_sample() -> int:
    """One compact block per sampled row: ask, answer, the returned rows, flags."""
    sample = _load(SAMPLE40)
    hand = {row["mid"] for row in json.loads(
        HAND_JSON.read_text(encoding="utf-8"))["rows"]}
    lines = []
    for row in sample:
        if row["mid"] in hand:
            continue
        lines.append(f"### {row['mid']} {row.get('bucket')} {row.get('sector')} "
                     f"F{(row.get('family') or ['?'])[0]}")
        lines.append(f"Q: {row.get('question')}")
        lines.append(f"A: {str(row.get('answer'))[:600]}")
        for run in row.get("gate") or []:
            lines.append(f"-- run {run.get('index')}: {str(run.get('text'))[:90]} "
                         f"| gate={run.get('gate')}")
            for hop in run.get("hops") or []:
                if hop.get("na"):
                    continue
                lines.append(f"  {hop.get('hop')} ok={hop.get('ok')} "
                             f"e={hop.get('entity_match')} a={hop.get('ask_match')} "
                             f"p={hop.get('period_match')}")
                for fact in (hop.get("rows") or [])[:4]:
                    lines.append("    " + json.dumps(fact, ensure_ascii=False)[:300])
        lines.append("")
    path = OUT / "GATE_SAMPLE40.review.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {path} ({len(sample)} rows)")
    return 0


def report() -> int:
    hand = {row["mid"]: row for row in json.loads(
        HAND_JSON.read_text(encoding="utf-8"))["rows"]}
    strict60 = {row["mid"]: row for row in _load(
        HAND_RESULTS.with_name("RESULTS_HAND60_strict.jsonl"))}
    originals = _load(BENCH / "GATE_RESULTS_originals_strict.jsonl")
    instances = _load(BENCH / "GATE_RESULTS_instances_strict.jsonl")
    bank = originals + instances
    sample = _load(SAMPLE40)
    verdicts = {}
    verdict_path = OUT / "GATE_SAMPLE40_verdicts.json"
    if verdict_path.exists():
        verdicts = json.loads(verdict_path.read_text(encoding="utf-8"))

    lines = ["# Answer gate run — 2026-10-29", ""]
    lines.append(
        "The entity/ask/period gate (`reality_engine/query/gate.py`) is now part of the "
        "answer contract: a run is ANSWERED only when its rows name the asked entity, carry "
        "the asked concept and sit in the asked period. The strict grader "
        "(`tasks/answer_bench/grade_v1.py`) recomputes those three flags from the returned "
        "rows instead of trusting the planner's flags. No LLM in the loop.")
    lines += ["", "## 1. Failure modes of the pilot-60 hand check (55 WRONG + 2 PARTIAL)", ""]
    modes = Counter(FAILURE_MODES.values())
    lines.append(_table(["failure mode", "rows", "what the note says"],
                        [["wrong_metric / ask unaddressed", modes["wrong_metric"],
                          "the answer returns another metric or a generic line for the ask "
                          "(close for a band/OI/products/ROIC ask)"],
                         ["wrong_period", modes["wrong_period"],
                          "the right metric from the wrong quarter/deck (2024 AR, Feb-2026 "
                          "deck, Q4FY26 for a Q1FY27 ask)"],
                         ["generic_text", modes["generic_text"],
                          "AR page/section headings and boilerplate, no answer content"],
                         ["wrong_entity", modes["wrong_entity"],
                          "evidence from another company's document (Oriental Carbon for "
                          "AGVENTURES)"]]))

    lines += ["", "## 2. Confusion matrix on the 60 hand-checked rows", ""]
    grades = ["ANSWERED", "PARTIAL", "BLOCKED_SCHEMA", "BLOCKED_TOOL", "NOT_IN_DATA"]
    before = Counter()
    after = Counter()
    for mid, verdict in ((mid, row["verdict"]) for mid, row in hand.items()):
        before[(verdict, hand[mid].get("grade", "?"))] += 1
        after[(verdict, strict60.get(mid, {}).get("strict_grade", "?"))] += 1
    body = []
    for verdict in ("OK", "PARTIAL", "WRONG"):
        body.append([verdict] + [before.get((verdict, g), 0) for g in grades] +
                    [after.get((verdict, g), 0) for g in grades])
    lines.append(_table(["hand verdict"] +
                        [f"before: {g}" for g in grades] +
                        [f"after: {g}" for g in grades], body))
    kept = sum(1 for mid, row in hand.items()
               if row["verdict"] == "OK" and strict60.get(mid, {}).get("strict_grade") == "ANSWERED")
    rejected = sum(1 for mid, row in hand.items()
                   if row["verdict"] == "WRONG"
                   and strict60.get(mid, {}).get("strict_grade") != "ANSWERED")
    partial_ok = sum(1 for mid, row in hand.items()
                     if row["verdict"] == "PARTIAL"
                     and strict60.get(mid, {}).get("strict_grade") == "PARTIAL")
    lines.append(f"\n- WRONG rejected: **{rejected}/55**; OK kept: **{kept}/3**; "
                 f"hand PARTIAL still PARTIAL: **{partial_ok}/2**.")
    if len(sample):
        lines.append(f"- The pilot graded all 60 ANSWERED; the gated contract keeps "
                     f"{sum(n for (v, g), n in after.items() if g == 'ANSWERED')} of them "
                     f"ANSWERED.")

    lines += ["", f"## 3. Answer precision (hand-checked strict-ANSWERED rows, seed {SEED40})",
              ""]
    if sample:
        ok = sum(1 for row in sample if verdicts.get(row["mid"], {}).get("verdict") == "OK")
        partial = sum(1 for row in sample
                      if verdicts.get(row["mid"], {}).get("verdict") == "PARTIAL")
        bad = sum(1 for row in sample
                  if verdicts.get(row["mid"], {}).get("verdict") == "WRONG")
        checked = ok + partial + bad
        lines.append(f"- sample: {len(sample)} rows the gated contract calls ANSWERED — the "
                     f"*whole* remaining pool (stratified by bucket x family; the 5 rows the "
                     f"pilot already hand-checked are excluded, and the hardened contract "
                     f"leaves fewer than 40 rows to draw)" if len(sample) < 40 else
                     f"- sample: {len(sample)} rows the gated contract calls ANSWERED, "
                     f"stratified by bucket x family")
        lines.append(f"- hand-checked {checked}: precision **{_pct(ok, checked)}** (OK), "
                     f"{partial} partial, {bad} wrong; Wilson 95% lower bound on OK/checked "
                     f"= **{wilson_lower(ok, checked):.3f}**")
        body = []
        for row in sample:
            verdict = verdicts.get(row["mid"], {})
            body.append([row["mid"], row.get("bucket"), row.get("sector"),
                         f"F{(row.get('family') or ['?'])[0]}",
                         str(row.get("question"))[:70],
                         row.get("unrelated_rows", 0),
                         verdict.get("verdict", "unchecked"),
                         str(verdict.get("note") or "")[:90]])
        lines.append("")
        lines.append(_table(["mid", "bucket", "sector", "family", "question",
                             "unrelated rows", "verdict", "note"], body))
        lines.append("")
        modes: Counter = Counter(
            str(verdicts.get(row["mid"], {}).get("mode") or "unclassified")
            for row in sample
            if verdicts.get(row["mid"], {}).get("verdict") in ("PARTIAL", "WRONG"))
        if modes:
            lines.append("- failure modes of the non-OK rows: " + ", ".join(
                f"**{mode}** {count}" for mode, count in modes.most_common()) + ".")
        lines.append(
            "- The hand check judges the *instance* entity (the substituted company the "
            "answer is produced for), against the row's own returned evidence, at the "
            "strictness the answer contract claims: value/date/period/document as asked, "
            "every named part of the ask, and no unrelated row that carries a number.")
    else:
        lines.append("No sample drawn.")

    lines += ["", "## 4. Full bank", ""]
    if bank:
        def _answered(rows: list[dict]) -> int:
            return sum(1 for row in rows if row.get("strict_grade") == "ANSWERED")

        def _gate_failed(rows: list[dict]) -> int:
            return sum(1 for row in rows if row.get("gate_recomputed"))

        def _gate_only(rows: list[dict]) -> int:
            """Contract grade: answered and no gate check failed (before the
            grader's older stale/named-document rules)."""
            return sum(1 for row in rows
                       if row.get("bench_grade") == "ANSWERED"
                       and not row.get("gate_recomputed"))

        lines.append(_table(
            ["set", "cases", "ANSWERED", "gate-downgraded"],
            [["whole bank", len(bank), _pct(_answered(bank), len(bank)), _gate_failed(bank)],
             ["originals (1,073)", len(originals), _pct(_answered(originals), len(originals)),
              _gate_failed(originals)],
             ["pilot-60 instances", len(instances), _pct(_answered(instances),
                                                          len(instances)),
              _gate_failed(instances)]]))
        lines.append(f"\n- answer contract (the three gate checks only): "
                     f"**{_pct(_gate_only(bank), len(bank))}**; the strict grader after its "
                     f"older stale/named-document rules: **{_pct(_answered(bank), len(bank))}**.")
        pit = sum(len(row.get("pit_violations") or row.get("pit") or []) for row in bank)
        lines.append(f"\n- PIT breaches: **{pit}** rows"
                     + (f" ({sum(1 for r in bank if r.get('pit_violations') or r.get('pit'))}"
                        f" cases)" if pit else " (0 cases)"))
        unrelated = sum(int(row.get("unrelated_rows") or 0) for row in bank)
        with_unrelated = sum(1 for row in bank if row.get("unrelated_rows"))
        lines.append(f"- unrelated rows appended to answers: **{unrelated}** row(s) over "
                     f"**{_pct(with_unrelated, len(bank))}** cases; a case is PARTIAL when two "
                     f"are appended or one of them carries a number")
        p50, p95, pmax = _latency([float(row.get("seconds") or 0.0) for row in bank])
        lines.append(f"- latency (answer seconds): p50 **{p50:.2f}s**, p95 **{p95:.2f}s**, "
                     f"max **{pmax:.2f}s**")
        for label, subset, key in (
                ("bucket (instances)", instances, "bucket"),
                ("entity level (originals)", originals, "entity_level"),
                ("sector (instances)", instances, "sector"),
                ("family (whole bank)", bank, None)):
            groups: dict[str, list[dict]] = defaultdict(list)
            for row in subset:
                if key:
                    groups[str(row.get(key) if row.get(key) is not None else "None")].append(row)
                else:
                    family = row.get("family") or []
                    groups[f"F{family[0]}" if isinstance(family, list) and family
                           else "F?"].append(row)
            body = []
            for name, rows in sorted(groups.items(), key=lambda item: -len(item[1])):
                body.append([name, len(rows), _pct(_answered(rows), len(rows)),
                             _gate_failed(rows)])
            lines += ["", f"### By {label}", ""]
            lines.append(_table([label, "cases", "ANSWERED", "gate-downgraded"], body))
        lines += ["", "### Bucket x family (ANSWERED %, instances)", ""]
        buckets = ["LARGE", "MID-SMALL", "MICRO"]
        families = sorted({f"F{(row.get('family') or ['?'])[0]}" for row in instances
                           if isinstance(row.get("family"), list) and row["family"]})
        body = []
        for family in families:
            cells = []
            for bucket in buckets:
                subset = [row for row in instances
                          if f"F{(row.get('family') or ['?'])[0]}" == family
                          and str(row.get("bucket")) == bucket]
                cells.append(f"{100.0 * _answered(subset) / len(subset):.0f}%" if subset
                             else "-")
            body.append([family] + cells)
        lines.append(_table(["family"] + buckets, body))
        lines += ["", "### Bucket x sector (ANSWERED %, instances)", ""]
        sectors = sorted({str(row.get("sector") or "None") for row in instances})
        body = []
        for sector in sectors:
            cells = []
            for bucket in buckets:
                subset = [row for row in instances if str(row.get("sector") or "None") == sector
                          and str(row.get("bucket")) == bucket]
                cells.append(f"{100.0 * _answered(subset) / len(subset):.0f}%" if subset
                             else "-")
            body.append([sector] + cells + [len([row for row in instances
                                                 if str(row.get("sector") or "None") == sector])])
        lines.append(_table(["sector"] + buckets + ["cases"], body))
        lines += ["", "### Top blockers (cases, first failing check, fix)", ""]
        lines.append(_blockers(bank))
    else:
        lines.append("Bank results not found.")

    lines += ["", "## 5. Method / deviations", ""]
    lines.append(
        "- The hand-60 rerun is the *current* code on the *current* stores, not the stored "
        "pilot answers: two rows (MB0010#L, MB0122#L) now carry the asked public-holding row "
        "the pilot answer lacked, and the gate still downgrades them because the answer mixes "
        "in rows outside the named month.")
    lines.append(
        "- The gate judges only the row fields the answer shows: a hidden numeric key "
        "(\"high\": 1710.0) is not evidence that the answer reported a high, and a fallback "
        "ask needs two key terms, not one generic word. Event/relation asks got their own "
        "aliases (control change, auditor resignation, chart pattern, NIM, loan growth, lag, "
        "credit cost, options).")
    lines.append(
        "- The strict grader recomputes the gate from the 8 recorded rows and the hop's "
        "rendered detail, never from the planner's flags. It disagrees with the planner's "
        "flags on 1,591 rows (2,817 hop flags): the record caps rows at 8 and detail at 600 "
        "characters, so a concept carried only by a later row is invisible to it. The "
        "grader's verdict is the one reported; the disagreement is counted, not resolved in "
        "the planner's favour.")
    lines.append(
        "- The bank was re-run end to end under the fixed gate (1,073 originals + 1,608 "
        "instances); the earlier partial run's files are kept in .tmp/ as *_v1.jsonl.")
    lines.append(
        "- Pilot stores were read immutable: REALITY_CHUNKS_V3=D:\\RealityEngine\\pilot\\"
        "pilot60\\chunks_v3_pilot.db, REALITY_PILOT_T1=\\pilot\\pilot60, "
        "REALITY_MACRO_PILOT_DB=\\pilot\\macro_all.db.")
    lines.append(
        "- 2026-10-29 hardening (this run). The 10-row hand check of the previous strict "
        "ANSWERED set found 4 OK / 3 PARTIAL / 3 WRONG, so the ask gate now requires every "
        "named part: promoter AND public holding, share count AND promoter holding, "
        "business AND segments, raw AND adjusted, the exchange when the question asks for "
        "it (\"on which exchange?\", \"nse bse\") and the side of the RSI band (an "
        "\"oversold days\" row does not answer \"RSI stayed above 70\"). A judgement ask "
        "(\"has the debt fallen, or has it moved into CWIP and JVs\") needs a row carrying "
        "that metric: a price return is not it.")
    lines.append(
        "- The unrelated-row penalty is judged per hop *and* per numeric claim the answer "
        "prints: two unrelated rows, or one that carries a number, make the case PARTIAL, "
        "and `unrelated_rows` is reported per row and in the bank totals.")
    lines.append(
        "- Instance questions are regenerated with the instance company's own name "
        "(`instantiate.py --rename-only`: 1,408 questions renamed, deterministic, 0 left "
        "naming the parent). The approved bank is untouched; its defects are in "
        "`tasks/master_bank/BANK_DEFECTS_2026-10-29.md`.")
    lines.append(
        "- Before/after on the same 2,681 result rows: strict ANSWERED was 137 (5.1%) on "
        "main 3489a87; this hardening leaves 24 (0.9%), and 19 of the 20 hand-checked rows "
        "of that remainder are right (the 20th is an under-specified industry ask, a bank "
        "defect). Recall is the cost of the rule: the answerer still cannot print the "
        "exchange, the adjusted basis, an episode list or page content, so those asks are "
        "now PARTIAL until the planners render them.")
    text = "\n".join(lines) + "\n"
    path = BENCH / "GATE_RUN_2026-10-29.md"
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("hand60", "bank", "grade", "sample40", "dump40",
                                     "report"))
    ap.add_argument("--limit-originals", type=int)
    ap.add_argument("--limit-instances", type=int)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--chunk", type=int, default=0,
                    help="run at most N new cases per process (RSS stays bounded)")
    ap.add_argument("--skip-file", help="mids that hang or crash the runner")
    args = ap.parse_args(argv)
    if args.mode == "hand60":
        return hand60()
    if args.mode == "bank":
        return bank(args.limit_originals, args.limit_instances, args.shard, args.shards,
                    args.resume, args.chunk, args.skip_file)
    if args.mode == "report":
        return report()
    if args.mode == "grade":
        return grade_bank()
    if args.mode == "dump40":
        return dump_sample()
    return sample40()


if __name__ == "__main__":
    sys.exit(main())
