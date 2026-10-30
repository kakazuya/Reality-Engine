"""Evaluate the v4 decomposer against hand-checked gold (tasks/arch_v4/QUERY_V4_DESIGN.md §C.3).

No model, no network, no database.  The decomposer reads the question text (plus the run-date
``as_of``) and the concept registry; the evaluator reads the hand-written gold file and the
bank's own ``period``/``as_of`` for the window check only.

Gold line:

    {"mid": "MB0125", "split": "dev", "required": [{"measure": "hold.pct",
                                                    "dims": {"holder_class": ["promoter"],
                                                             "public"]}}],
     "evidence": ["hold.pct"], "expect_status": "mapped"}

* ``required`` — the readings an ask must carry.  A reading is matched when some part has that
  measure and, for every dim it names, that value (a part carries one value per dim).
* ``evidence`` — the concepts that legitimately *answer* the ask (the rubric's evidence set).
* ``expect_status`` — asserted only where the design is explicit (the 26 unmapped cases).

Measured on a held-out split: every even-indexed case of the deterministic stride-4 sample is
``test``; the cases used while developing are ``dev``.  The 26 measured-unmapped cases of
§A.7/registry_coverage 4.4 are oversampled into ``test`` so the "never guessed" rule is measured
on all of them.

    python tasks/arch_v4/eval_decomposer.py            # all splits, exit 1 if test fails
    python tasks/arch_v4/eval_decomposer.py --split dev --show 10
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reality_engine.query.router import period_bounds  # noqa: E402
from reality_engine.query.v4.decompose import decompose, load_registry  # noqa: E402

GOLD = ROOT / "tasks" / "arch_v4" / "decompose_gold.jsonl"
BANK = ROOT / "tasks" / "master_bank" / "MASTER_BANK.jsonl"

TARGETS = {"part_recall": 0.97, "precision": 0.97, "dim_completeness": 1.0,
           "unmapped_recall": 1.0}


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _concept_surfaces(registry, concept: str) -> list[str]:
    """Every lexicon surface that names this measure, so the audit can ask "is it in the text"."""
    out = [e["surface"] for e in registry.lexicon
           if e["id"] == concept and e["kind"] in ("atom", "formula")]
    if concept == "claim.claim":
        out += [e["surface"] for e in registry.lexicon if e["kind"] == "claim_topic"]
        out += sorted({e["surface"] for e in registry.lexicon
                       if e["kind"] == "dim" and e["id"].startswith("doctype=")})
    elif concept == "text.passage":
        out += sorted({e["surface"] for e in registry.lexicon
                       if e["kind"] == "dim" and e["id"].startswith("doctype=")})
    return sorted(set(out), key=len, reverse=True)


def _named_in(text_norm: str, surfaces: list[str]) -> bool:
    for surface in surfaces:
        if surface and f" {surface} " in f" {text_norm} ":
            return True
        if surface and re.search(rf"(?<![a-z0-9]){re.escape(surface)}(?![a-z0-9])", text_norm):
            return True
    return False

def _reading_present(ask, measure: str, dims: dict[str, list[str]]) -> bool:
    """Some part carries the measure and *every* named dim value (each on some reading)."""
    parts = [p for p in ask.parts if p.concept == measure]
    if not parts:
        return False
    for dim_id, values in dims.items():
        for value in values:
            if not any(value in p.dim_values(dim_id) for p in parts):
                return False
    return True


def evaluate(gold: list[dict], cases: dict[str, dict], registry) -> dict:
    req_concepts = req_hit = 0
    req_readings = reading_hit = 0
    parts_n = parts_ok = 0
    dim_pairs = dim_hit = 0
    dim_cases = 0
    window_n = window_ok = window_unresolved = 0
    unmapped_expected = unmapped_ok = 0
    false_unmapped = 0
    expr_readings = expr_hit = unnamed_readings = 0
    named_parts = named_parts_ok = default_parts = 0
    surfaces: dict[str, list[str]] = {}
    rows: list[dict] = []
    missing_counter: dict[str, int] = {}
    extra_counter: dict[str, int] = {}

    def concept_surfaces(concept: str) -> list[str]:
        if concept not in surfaces:
            surfaces[concept] = _concept_surfaces(registry, concept)
        return surfaces[concept]

    for g in gold:
        case = cases.get(g["mid"], {})
        question = case.get("question") or ""
        ask = decompose(question, case.get("as_of") or "", registry)
        text_norm = " " + re.sub(r"[^a-z0-9%]+", " ", question.lower()) + " "

        required = g.get("required") or []
        evidence = set(g.get("evidence") or [])
        concepts = {p.concept for p in ask.parts}
        missing_required = [r["measure"] for r in required if r["measure"] not in concepts]
        not_evidence = [p.concept for p in ask.parts if p.concept not in evidence]
        for concept in missing_required:
            missing_counter[concept] = missing_counter.get(concept, 0) + 1
        for concept in not_evidence:
            extra_counter[concept] = extra_counter.get(concept, 0) + 1
        for r in required:
            req_concepts += 1
            found = r["measure"] in concepts
            req_hit += found
            req_readings += 1
            reading_hit += _reading_present(ask, r["measure"], r.get("dims") or {})
            if _named_in(text_norm, concept_surfaces(r["measure"])):
                expr_readings += 1
                expr_hit += found
            else:
                unnamed_readings += 1
        for p in ask.parts:
            parts_n += 1
            ok = p.concept in evidence
            parts_ok += ok
            if _named_in(text_norm, concept_surfaces(p.concept)):
                named_parts += 1
                named_parts_ok += ok
            else:
                default_parts += 1
        named = [(d, v) for r in required for d, vs in (r.get("dims") or {}).items() for v in vs]
        missing_dims: list[str] = []
        if named:
            dim_cases += 1
            for dim_id, value in named:
                dim_pairs += 1
                if any(value in p.dim_values(dim_id) for p in ask.parts):
                    dim_hit += 1
                else:
                    missing_dims.append(f"{dim_id}={value}")

        # window (§C.3): exact match with period_bounds(case) or a stated "unresolved"
        want = period_bounds(case) if case else (None, None, "none")
        window_n += 1
        if (ask.windows[0].from_, ask.windows[0].to) == want[:2]:
            window_ok += 1
        elif ask.windows[0].basis in ("as_of", "none"):
            window_unresolved += 1

        expect = g.get("expect_status")
        if expect == "unmapped":
            unmapped_expected += 1
            unmapped_ok += ask.status == "unmapped"
        elif ask.status == "unmapped":
            false_unmapped += 1

        bad = (missing_required or missing_dims or any(p.concept not in evidence for p in ask.parts)
               or (expect == "unmapped" and ask.status != "unmapped"))
        if bad:
            rows.append({
                "mid": g["mid"],
                "question": question,
                "status": ask.status,
                "parts": [p.concept for p in ask.parts],
                "dims": [dict(p.dims) for p in ask.parts],
                "missing_required": missing_required,
                "missing_dims": missing_dims,
                "not_in_evidence": [p.concept for p in ask.parts if p.concept not in evidence],
                "residues": ask.residues,
            })

    pct = lambda a, b: round(100.0 * a / b, 2) if b else 100.0
    return {
        "n": len(gold),
        "part_recall": pct(req_readings and reading_hit, req_readings) if req_readings else 100.0,
        "concept_recall": pct(req_concepts and req_hit, req_concepts) if req_concepts else 100.0,
        "precision": pct(parts_ok, parts_n),
        "dim_completeness": pct(dim_hit, dim_pairs) if dim_pairs else 100.0,
        "dim_cases": dim_cases,
        "dim_pairs": dim_pairs,
        "window_exact": pct(window_ok, window_n),
        "window_unresolved": pct(window_unresolved, window_n),
        "window_mismatch": pct(window_n - window_ok - window_unresolved, window_n),
        "unmapped_recall": pct(unmapped_ok, unmapped_expected) if unmapped_expected else 100.0,
        "unmapped_cases": unmapped_expected,
        "false_unmapped": false_unmapped,
        # audit: a text-only decomposer can only recall a measure the question text names
        "expressible_readings": expr_readings,
        "expressible_recall": pct(expr_hit, expr_readings) if expr_readings else 100.0,
        "unnameable_readings": unnamed_readings,
        "named_parts": named_parts,
        "named_parts_precision": pct(named_parts_ok, named_parts) if named_parts else 100.0,
        "default_parts": default_parts,
        "missing_top": sorted(missing_counter.items(), key=lambda kv: -kv[1])[:12],
        "extra_top": sorted(extra_counter.items(), key=lambda kv: -kv[1])[:12],
        "failing": rows,
    }


# --------------------------------------------------------------------------- #
# the three asks the acceptance names, checked by hand (no bank involved)
# --------------------------------------------------------------------------- #
MULTIPART = [
    ("M & B Engineering (NSE: MBEL) mein public shareholding Sep 2026 tak kitni hai? "
     "Promoter aur public dono ka percentage filing se batao.",
     {"atom": "hold.pct", "readings": {"holder_class": ["promoter", "public"]}}),
    ("Ather delivery volume 13 April 2026 and 14 April 2026, NSE + BSE combined, "
     "give NSE, BSE and the sum per day.",
     {"atom": "price.delivery_qty", "readings": {"exchange": ["NSE", "BSE", "sum"]}}),
    ("Polycab: give the raw and adjusted close for 2026.",
     {"atom": "price.close", "readings": {"basis": ["raw", "adjusted"]}}),
]


def multipart_check(registry) -> list[str]:
    failures = []
    for question, want in MULTIPART:
        ask = decompose(question, "2026-10-19", registry)
        parts = [p for p in ask.parts if p.concept == want["atom"]]
        for dim_id, values in want["readings"].items():
            for value in values:
                if not any(value in p.dim_values(dim_id) for p in parts):
                    failures.append(f"{want['atom']} {dim_id}={value} missing from: {question}")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="all", choices=["all", "dev", "test"])
    ap.add_argument("--gold", default=str(GOLD))
    ap.add_argument("--show", type=int, default=0, help="print this many failing cases")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    gold = load_jsonl(Path(args.gold))
    cases = {c["mid"]: c for c in load_jsonl(BANK)}
    registry = load_registry()

    splits = ["dev", "test"] if args.split == "all" else [args.split]
    code = 0
    print(f"gold: {args.gold} | {len(gold)} hand-checked cases | registry {ROOT}/tasks/arch_v4")
    for split in splits:
        subset = [g for g in gold if g.get("split") == split]
        if not subset:
            continue
        r = evaluate(subset, cases, registry)
        print(f"\n[{split}] n={r['n']}  part_recall={r['part_recall']}%  "
              f"concept_recall={r['concept_recall']}%  precision={r['precision']}%  "
              f"dim_completeness={r['dim_completeness']}% ({r['dim_cases']} dim-naming cases, "
              f"{r['dim_pairs']} named values)")
        print(f"[{split}] window: exact={r['window_exact']}%  "
              f"unresolved(as_of)={r['window_unresolved']}%  mismatch={r['window_mismatch']}%")
        print(f"[{split}] unmapped: recall={r['unmapped_recall']}% "
              f"({r['unmapped_cases']} cases)  false_unmapped={r['false_unmapped']}")
        print(f"[{split}] audit: required readings the question text *names*: "
              f"{r['expressible_readings']} at recall {r['expressible_recall']}%  |  "
              f"required readings with no measure word in the text: {r['unnameable_readings']}")
        print(f"[{split}] audit: parts whose concept the text names: {r['named_parts']} at "
              f"precision {r['named_parts_precision']}%  |  parts from a declared default: "
              f"{r['default_parts']}")
        print(f"[{split}] most-missed required measures: {r['missing_top']}")
        print(f"[{split}] most-common parts outside the evidence set: {r['extra_top']}")
        if split == "test":
            for name, target in TARGETS.items():
                value = r[name]
                ok = value >= target * 100
                print(f"  {'PASS' if ok else 'FAIL'} {name}: {value}% (target {target * 100:.0f}%)")
                code |= 0 if ok else 1
        if args.show:
            for row in r["failing"][:args.show]:
                print(f"  - {row['mid']} status={row['status']} parts={row['parts']} "
                      f"missing={row['missing_required']} not-evidence={row['not_in_evidence']}"
                      f" missing-dims={row['missing_dims']} residues={row['residues']}")
                print(f"    Q: {row['question'][:160]}")

    failures = multipart_check(registry)
    print(f"\nmulti-part asks: {'PASS' if not failures else 'FAIL'} ({len(MULTIPART)} asks)")
    for f in failures:
        print("  -", f)
    code |= 1 if failures else 0
    print("\nALL CHECKS PASSED" if code == 0 else "\nCHECKS FAILED")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
