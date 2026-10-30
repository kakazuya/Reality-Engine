"""The v4 strict grader (§H.4): coverage against the Ask, not against the prose.

Two jobs, one file:

1. **v4 answers** (``--results`` + ``--cases``).  A case is ANSWERED only when
   every part of its Ask has exactly one result, that result's ``answer_type`` is
   one of measured/estimate/proxy/not_in_data, and it carries the contract the
   type promises (§D.4).  ``real_answered`` (measured + estimate) and
   ``proxy_answered`` (a proxy with both a ``search_log`` ref and an
   ``approved_by``) are separate numbers; a typed NOT IN DATA never counts, and a
   result whose part_index names no part is an unrelated row and fails the case.
   That part-by-part rule is strictly stricter than the hardened v3 grader's
   "every sub-question must be evidence-backed": a multi-part ask needs every
   part, not the union of them.

2. **The 1.0% anchor** (``--anchor``).  Regrades the old answer rows that commit
   ``4199be2`` graded (they are committed inside its ``*_strict.jsonl`` files,
   while the raw ``GATE_RESULTS_*.jsonl`` files are gitignored) with the hardened
   v3 grader the anchor was measured by, and compares against
   **27 / 2,681 ANSWERED**.  The number is printed, never adjusted: if the
   regrade disagrees, the changed cases are listed with their current reason and
   the command exits 3, because a grader that is tuned until it matches its own
   anchor proves nothing.

Usage::

    python tasks/answer_bench/grade_v2.py --anchor
    python tasks/answer_bench/grade_v2.py --cases cases.jsonl --results results.jsonl
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from reality_engine.query.v4.execute import (  # noqa: E402
    ANSWER_TYPES, approved_proxy, as_part, as_result)

ANCHOR_COMMIT = "4199be2"
ANCHOR_ROWS = 2681
ANCHOR_ANSWERED = 27
ANCHOR_FILES = ("GATE_RESULTS_originals_strict.jsonl",
                "GATE_RESULTS_instances_strict.jsonl")
SPECIAL_DIMS = {"each", "sum"}
DIM_IGNORE = {"entity_id", "isin", "est_atom", "rule", "rule_id"}


# ---------------------------------------------------------------------------
# per-part contract
# ---------------------------------------------------------------------------
def _blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _dims_ok(part, result) -> str | None:
    asked = {str(key): str(value) for key, value in (part.dims or {}).items()
             if key not in DIM_IGNORE and str(value).lower() not in SPECIAL_DIMS}
    got = {str(key): str(value) for key, value in (result.dims or {}).items()}
    for key, value in asked.items():
        if str(got.get(key, "")).lower() != value.lower():
            return (f"asked {key}={value}, the block carries {key}={got.get(key) or 'nothing'}")
    return None


def _measured_gap(result) -> str | None:
    """The fields a measured block must print (§D.4)."""
    if _blank(result.source_ref):
        return "measured block has no source table"
    if _blank(result.known_at):
        return "measured block has no known_at"
    shape = str(result.shape or "")
    if shape == "verdict" or result.verdict is not None:
        if not result.rule_used:
            return "verdict block does not state the rule it applied"
        return None
    if shape == "ranked_list" or (result.entities and not result.values):
        if not result.entities:
            return "ranked block carries no entities"
        if any(_blank(row.get("entity_id")) or row.get("value") is None
               for row in result.entities):
            return "ranked block has an entity row without a value"
        return None
    if shape == "passage" or result.values:
        rows = result.values
        if not rows:
            return "passage block carries no passage"
        if all(_blank(row.get("quote")) and row.get("value") is None for row in rows):
            return "passage block carries no quote or value"
        if (shape == "series" and _blank(result.unit)
                and not any(row.get("unit") for row in rows)):
            return "series block has no unit"
        return None
    if result.value is None:
        return "measured block carries no value"
    if _blank(result.unit):
        return "measured block has no unit"
    if _blank(result.period):
        return "measured block has no period"
    if _blank(result.isin):
        return "measured block has no entity/ISIN"
    return None


def _estimate_gap(result) -> str | None:
    if _blank(result.method):
        return "estimate block has no method (§A.8 ladder)"
    if _blank(result.inputs):
        return "estimate block has no inputs"
    if result.confidence is None:
        return "estimate block has no confidence"
    if _blank(result.source_ref) or _blank(result.known_at):
        return "estimate block has no source/known_at"
    if result.value is None or _blank(result.unit) or _blank(result.period):
        return "estimate block has no value/unit/period"
    return None


def _proxy_gap(result) -> str | None:
    if not result.search_log:
        return "proxy has no search_log ref: it does not count as answered (§D.4)"
    if not result.approved_by:
        return "proxy has no approved_by: it does not count as answered (§D.4)"
    if _blank(result.assumption):
        return "approved proxy states no assumption (a proxy without one is a ticket)"
    if result.confidence is None:
        return "approved proxy has no confidence"
    if result.value is None and _blank(result.values):
        return "proxy carries no value"
    return None


def part_status(part: Any, result: Any) -> dict[str, Any]:
    """Covered? counted as real or proxy? and why not, for one part."""
    p = as_part(part)
    status: dict[str, Any] = {"part_index": p.index,
                              "measure": p.measure or p.atom or p.formula,
                              "covered": False, "answer_type": None,
                              "counts_as": "not_answered", "reason": None}
    if result is None:
        status["reason"] = f"no result for part {p.index + 1} ({p.measure or '?'})"
        return status
    r = as_result(result)
    status["answer_type"] = r.answer_type
    if r.answer_type not in ANSWER_TYPES:
        status["reason"] = (f"answer_type {r.answer_type!r} is not one of "
                            f"{'|'.join(ANSWER_TYPES)}")
        return status
    dims_reason = _dims_ok(p, r)
    if dims_reason:
        status["reason"] = dims_reason
        return status
    gap = None
    if r.answer_type == "measured":
        gap = _measured_gap(r)
        status["counts_as"] = "real_answered"
    elif r.answer_type == "estimate":
        gap = _estimate_gap(r)
        status["counts_as"] = "real_answered"
    elif r.answer_type == "proxy":
        gap = _proxy_gap(r)
        status["counts_as"] = "proxy_answered" if gap is None else "not_answered"
    else:  # not_in_data: never an answer, but it must be triaged
        status["counts_as"] = "not_answered"
        if not r.nid_reason:
            gap = "typed NOT IN DATA has no nid_reason"
        elif not r.tried:
            gap = "typed NOT IN DATA does not list what was tried (four-gate wording)"
        elif not r.to_close:
            gap = "typed NOT IN DATA has no closing action"
    if gap:
        status["reason"] = gap
        return status
    status["covered"] = r.answer_type in ("measured", "estimate") or approved_proxy(r)
    if not status["covered"] and not status["reason"]:
        status["reason"] = (f"part {p.index + 1} is NOT IN DATA: "
                            f"{r.nid_reason or 'no reason recorded'}")
    return status


# ---------------------------------------------------------------------------
# per-case coverage (the strict counter the gate reads)
# ---------------------------------------------------------------------------
def case_status(ask: Mapping[str, Any], results: Iterable[Any]) -> dict[str, Any]:
    parts = [as_part(part, index) for index, part in enumerate(ask.get("parts") or [])]
    rows = [as_result(row) for row in results or []]
    grouped: dict[int, list[Any]] = defaultdict(list)
    unrelated = []
    for row in rows:
        if 0 <= row.part_index < len(parts):
            grouped[row.part_index].append(row)
        else:
            unrelated.append(f"result for part_index {row.part_index} "
                             f"({row.measure or row.formula or '?'}) named no part")
    statuses = []
    for part in parts:
        found = grouped.get(part.index) or []
        if len(found) > 1:
            statuses.append({"part_index": part.index,
                             "measure": part.measure or part.atom or part.formula,
                             "covered": False, "answer_type": None,
                             "counts_as": "not_answered",
                             "reason": f"{len(found)} results for part {part.index + 1}"})
            continue
        statuses.append(part_status(part, found[0] if found else None))
    real = sum(1 for status in statuses if status["counts_as"] == "real_answered"
               and status["covered"])
    proxy = sum(1 for status in statuses if status["counts_as"] == "proxy_answered"
                and status["covered"])
    reasons = [status["reason"] for status in statuses if status["reason"]]
    reasons += unrelated
    covered = (bool(parts) and real + proxy == len(parts) and not unrelated
               and len(statuses) == len(parts))
    return {"parts": len(parts), "real_answered": real, "proxy_answered": proxy,
            "not_answered": len(parts) - real - proxy, "unrelated": unrelated,
            "covered": covered, "reasons": reasons, "part_status": statuses}


def grade_run(cases: Sequence[Mapping[str, Any]],
              results_by_mid: Mapping[str, Sequence[Any]]) -> dict[str, Any]:
    """Grade a run of v4 answers: per-case status plus the gate counters."""
    graded = []
    for case in cases:
        mid = str(case.get("mid") or "")
        ask = case.get("ask") or case
        status = case_status(ask, results_by_mid.get(mid) or [])
        status["mid"] = mid
        graded.append(status)
    rows = len(graded)
    answered = sum(1 for row in graded if row["covered"])
    summary = {
        "rows": rows,
        "answered": answered,
        "answered_pct": round(100.0 * answered / rows, 1) if rows else 0.0,
        "real_answered_parts": sum(row["real_answered"] for row in graded),
        "proxy_answered_parts": sum(row["proxy_answered"] for row in graded),
        "not_answered_parts": sum(row["not_answered"] for row in graded),
        "unrelated_rows": sum(len(row["unrelated"]) for row in graded),
        "by_reason": dict(Counter(reason for row in graded
                                  for reason in row["reasons"]).most_common(20)),
    }
    return {"summary": summary, "rows": graded}


# ---------------------------------------------------------------------------
# the 1.0% anchor: regrade the answers embedded in commit 4199be2
# ---------------------------------------------------------------------------
def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"skip truncated line in {path.name}", flush=True)
    return out


def _git_rows(commit: str, name: str) -> list[dict[str, Any]]:
    blob = subprocess.run(
        ["git", "-C", str(REPO), "show", f"{commit}:tasks/answer_bench/{name}"],
        check=True, capture_output=True).stdout.decode("utf-8")
    return [json.loads(line) for line in blob.splitlines() if line.strip()]


def _anchor_cases() -> tuple[dict[str, dict], dict[str, dict]]:
    bank = {row["mid"]: row for row in _load_jsonl(
        REPO / "tasks" / "master_bank" / "MASTER_BANK.jsonl")}
    instances = {row["mid"]: row for row in _load_jsonl(
        REPO / "tasks" / "pilot60" / "INSTANCES.jsonl")}
    return bank, instances


def anchor(commit: str = ANCHOR_COMMIT, out_dir: Path | None = None,
           quiet: bool = False) -> dict[str, Any]:
    """Regrade the old answers with the hardened v3 grader; never tune the result."""
    import grade_v1  # the hardened grader the anchor was measured by

    bank, instances = _anchor_cases()
    index = grade_v1.DocIndex()
    out_dir = out_dir or (REPO / ".tmp")
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"commit": commit, "rows": 0, "answered": 0,
                              "files": {}, "changed": [], "doc_index":
                              "snapshot" if index.ok else "row-text fallback"}
    total = Counter()
    for name, cases in ((ANCHOR_FILES[0], bank), (ANCHOR_FILES[1], instances)):
        try:
            rows = _git_rows(commit, name)
        except subprocess.CalledProcessError as exc:
            report["files"][name] = {"rows": 0, "grades": {},
                                     "error": f"git show failed: {exc}"}
            continue
        graded = []
        changed = []
        for row in rows:
            result = grade_v1.grade_row(cases.get(row["mid"], {}), row, index)
            graded.append(result)
            if result.get("strict_grade") != row.get("strict_grade"):
                changed.append({"mid": row.get("mid"),
                                "was": row.get("strict_grade"),
                                "now": result.get("strict_grade"),
                                "why": (result.get("strict_reasons") or [""])[0][:160]})
        counts = Counter(row["strict_grade"] for row in graded)
        total.update(counts)
        report["files"][name] = {"rows": len(rows), "grades": dict(counts),
                                 "answered": counts.get("ANSWERED", 0)}
        report["changed"].extend(changed)
        if not quiet:
            print(f"{name}: {len(rows)} rows {dict(counts)}", flush=True)
        (out_dir / f"grade_v2_anchor_{name}").write_text(
            "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n"
                    for row in graded), encoding="utf-8")
    answered = total.get("ANSWERED", 0)
    report["rows"] = sum(total.values())
    report["answered"] = answered
    report["pct"] = round(100.0 * answered / max(1, report["rows"]), 2)
    report["reproduced"] = (answered == ANCHOR_ANSWERED and
                            report["rows"] == ANCHOR_ROWS)
    report["all_grades"] = dict(total)
    if not quiet:
        verdict = "ANCHOR REPRODUCED" if report["reproduced"] else "ANCHOR NOT REPRODUCED"
        print(f"{verdict}: {answered}/{report['rows']} = "
              f"{report['pct']:.1f}% strict ANSWERED "
              f"(anchor {ANCHOR_ANSWERED}/{ANCHOR_ROWS}); "
              f"doc index {report['doc_index']}", flush=True)
        for item in report["changed"][:12]:
            print(f"  {item['mid']}: {item['was']} -> {item['now']} ({item['why']})",
                  flush=True)
        print(f"changed vs the anchor's own grades: {len(report['changed'])} row(s)",
              flush=True)
    return report


# ---------------------------------------------------------------------------
# v4 run grading
# ---------------------------------------------------------------------------
def _cases(path: Path) -> list[dict[str, Any]]:
    return _load_jsonl(path)


def _results(path: Path) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for row in _load_jsonl(path):
        mid = str(row.get("mid") or "")
        payload = row.get("results")
        if payload is None:
            payload = row.get("parts") or []
        out[mid] = list(payload or [])
    return out


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--anchor", action="store_true",
                        help="regrade the old answers at 4199be2 and check 27/2,681")
    parser.add_argument("--commit", default=ANCHOR_COMMIT, help="anchor commit")
    parser.add_argument("--cases", type=Path, help="v4 Ask cases jsonl (mid + ask)")
    parser.add_argument("--results", type=Path, help="v4 results jsonl (mid + results)")
    parser.add_argument("--out", type=Path, help="write the graded rows here (jsonl)")
    args = parser.parse_args(list(argv))

    if args.anchor or not (args.cases and args.results):
        report = anchor(args.commit)
        if args.out:
            args.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
        return 0 if report["reproduced"] else 3

    asked = _cases(args.cases)
    run = _results(args.results)
    graded = grade_run(asked, run)
    if args.out:
        args.out.write_text(
            "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n"
                    for row in graded["rows"]), encoding="utf-8")
    print(json.dumps(graded["summary"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
