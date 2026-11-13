"""Blind grading for N answer sets (T-205 round 13): shuffled labels, a private key, one agy grader per batch.

Generalises ``report_r12/make_blind.py`` from three fixed sets (X/Y/Z) to any number of named sets (labels A, B, C
...), keeps the label order shuffled per question with a fixed seed, and keeps the key in a private directory the
grader is told never to open. Each grader run reads one batch of questions (8 by default) and replies with ONE JSON
line per (qid, label); a batch whose reply does not parse is re-asked once and then reported, never silently dropped.

Three steps, one command each:

    python -m reality_engine.answer.blind_grade make  --set pack=PATH --set seeded=PATH --out DIR
    python -m reality_engine.answer.blind_grade run   --out DIR [--model claude-opus-5-5-medium]
    python -m reality_engine.answer.blind_grade decode --out DIR

The grader is ``claude-opus-5-5-medium`` through agy (``agy_call``); its instructions are the GRADING_1.md rules with
the shell's ``p3ask`` swapped for the same ``pilot3_*`` MCP tools, because the Opus grader in agy has no shell.
Grades are ``right``, ``partly``, ``wrong`` and ``not_held`` (a confirmed absence counts as right, ruling 9 Nov).
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

from reality_engine.answer import agy_call

MODEL = "claude-opus-5-5-medium"
BATCH = 8
SEED = 20261114
LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GRADES = ("right", "partly", "wrong", "not_held")
RIGHT_EQUIVALENT = {"right", "not_held"}

RULES = """# T-205 blind grading: Blue Star (NSE BLUESTARCO)

Several answer sets answered the same frozen questions from the store `D:/RealityEngine/bluestar/bluestar.db`. They
are labelled only A, B, C ...; the label order is shuffled per question and you are not told how any set was made.
Grade ONLY the answers in your batch file. Do not open D:/RealityEngine/bluestar/questions/, truth/, truth2/,
answers*/, pack*/, report/, report_r12/ (any earlier grades), report_r12/grade_in_* of other batches, or
key_private/: the key says which set each label is and must stay closed.

For each question:
1. Find the truth yourself in the store, independently of the answers, ONCE per question. Use the reality-data MCP
   tools with symbol=BLUESTARCO and as_of=<the question's as_of>: pilot3_fact (a single number first), pilot3_fin,
   pilot3_ratio, pilot3_kpi, pilot3_guidance, pilot3_statements, pilot3_topic, pilot3_cells, pilot3_holding,
   pilot3_tech, pilot3_docs, pilot3_search, pilot3_sql, pilot3_calc. Read the cited pages (pilot3_docs,
   pilot3_search, pilot3_cells) and prefer the printed page (results statement, deck, transcript) over any derived
   row. Respect as_of: a document known after the question's as_of may not be used.
2. Redo every arithmetic step (growth, margins, shares, sums). A figure off by more than rounding is wrong.
3. Grade each answer:
   - `right`: every figure or fact asked is correct (value, unit, period, basis), nothing material missing, nothing
     invented. For "what did management say" questions: the substance matches the transcript.
   - `partly`: some parts right, some missing or wrong. Partly right is NOT right.
   - `wrong`: the main figure or claim is wrong, or the answer says "not found" when the store holds it.
   - `not_held`: the answer says data not found AND you confirm the store truly lacks it (search + pilot3_sql on
     doc_page) AND the answer's search was reasonable and it labelled the nearest point. Counts as right (ruling
     9 Nov).
   - An answer citing a document known after the question's as_of is at best partly (look-ahead).
4. Root cause for every non-right grade: `raw_missing` (document not in the store), `not_extracted` (in a page but
   no row/atom), `wrong_row` (a stored row/atom is wrong), `reading` (a page-reader figure wrong), `routing`
   (answerer used the wrong tool or stopped early / missed a part), `compute` (arithmetic or definition error),
   `question` (ambiguous). Use "" for a right grade.

Reply with ONE JSON object per line and nothing else -- one line per (qid, label) in the batch:
{"qid": "BS-001", "label": "A", "grade": "right|partly|wrong|not_held", "root_cause": "", "truth": "<the correct
figure(s) with source doc + page>", "note": "<= 250 chars"}
Work question by question and keep every note short."""


# --- making the blind inputs -------------------------------------------------------------------------
def read_answers(folder: str | Path) -> dict[str, str]:
    """One set's answer text by qid: ``answers.jsonl`` (ds_a shape) or an ``answer_<qid>.json`` per question."""
    path = Path(folder)
    out: dict[str, str] = {}
    if (path / "answers.jsonl").is_file():
        for line in (path / "answers.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                out[str(row.get("qid"))] = str(row.get("answer") or "(no answer)")
    for f in sorted(path.glob("answer_*.json")):
        qid = f.stem[len("answer_"):]
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out[qid] = str(data.get("final_answer") or "(no answer)")
    return out


def make(sets: dict[str, str | Path], out_dir: str | Path, *, questions: str | Path, seed: int = SEED,
         batch: int = BATCH, key_path: str | Path | None = None, rules: str = RULES) -> dict:
    """Write the blind batches, the grading rules and the private key. Returns a small summary."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    key = Path(key_path) if key_path else out.parent / "key_private" / f"key_{out.name}.csv"
    qs = json.loads(Path(questions).read_text(encoding="utf-8"))
    answers = {name: read_answers(folder) for name, folder in sets.items()}
    rng = random.Random(seed)
    batches: dict[int, list[dict]] = {}
    key_rows: list[dict] = []
    for i, q in enumerate(qs):
        names = list(sets)
        rng.shuffle(names)
        blind = {}
        for label, name in zip(LABELS, names):
            blind[label] = {"answer": answers[name].get(q["qid"], "(no answer)")}
            key_rows.append({"qid": q["qid"], "label": label, "set": name})
        batches.setdefault(i // batch, []).append(
            {"qid": q["qid"], "question": q["question"], "as_of": q["as_of"], "answers": blind})
    key.parent.mkdir(parents=True, exist_ok=True)
    with key.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["qid", "label", "set"])
        writer.writeheader()
        writer.writerows(key_rows)
    texts = []
    for n, rows in batches.items():
        path = out / f"grade_in_{n}.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        texts.append(path.name)
    (out / "GRADING.md").write_text(rules, encoding="utf-8")
    summary = {"sets": list(sets), "questions": len(qs), "batches": len(batches), "batch": batch,
               "files": texts, "key": str(key), "labels": LABELS[:len(sets)], "seed": seed}
    (out / "make.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


# --- running the grader ------------------------------------------------------------------------------
def parse_grades(text: str, wanted: set[tuple[str, str]]) -> list[dict]:
    """Every strict JSON line that is a usable grade for a (qid, label) the batch asked about."""
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for line in (text or "").splitlines():
        line = line.strip().strip("`")
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        key = (str(row.get("qid") or ""), str(row.get("label") or "").strip().upper())
        if key not in wanted or key in seen:
            continue
        grade = str(row.get("grade") or "").strip().lower()
        if grade not in GRADES:
            continue
        seen.add(key)
        rows.append({"qid": key[0], "label": key[1], "grade": grade,
                     "root_cause": str(row.get("root_cause") or "").strip(),
                     "truth": str(row.get("truth") or "").strip(),
                     "note": str(row.get("note") or "").strip()[:250]})
    return rows


def grade_batch(path: Path, model: str = MODEL, *, run=agy_call.run_agy, workspace: str | Path = ".",
                timeout: int = 1800, retries: int = 1) -> dict:
    """Ask the grader for one batch; a reply that does not parse the batch is re-asked ONCE, then reported."""
    questions = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    wanted = {(q["qid"], label) for q in questions for label in q["answers"]}
    body = "".join(json.dumps(q, ensure_ascii=False) + "\n" for q in questions)
    prompt = (f"{RULES}\n\nYOUR BATCH ({len(questions)} questions, {len(wanted)} grades to return):\n{body}\n"
              "Grade every answer now: one JSON object per line, nothing else.")
    attempts, rows, error = 0, [], ""
    while attempts <= retries and len(rows) < len(wanted):
        reply = run(prompt, model, cwd=workspace, timeout=timeout,
                    log_path=path.with_name(f"{path.stem}_agy_{attempts + 1}.jsonl"))
        attempts += 1
        if reply.get("ok"):
            rows = parse_grades(reply.get("text") or "", wanted) or rows
            error = ""
        else:
            error = reply.get("error", "")
        if len(rows) >= len(wanted):
            break
        prompt += ("\n\nYOUR PREVIOUS REPLY DID NOT PARSE AS ONE JSON LINE PER (qid, label). Reply again with the "
                   "missing lines only, one JSON object per line and nothing else.")
    got = {(r["qid"], r["label"]) for r in rows}
    missing = [{"qid": qid, "label": label} for qid, label in sorted(wanted) if (qid, label) not in got]
    return {"batch": path.stem, "grades": rows, "missing": missing, "attempts": attempts,
            "error": error if not rows else ""}


def run(out_dir: str | Path, *, model: str = MODEL, workspace: str | Path = ".", run_fn=agy_call.run_agy,
        limit: int = 0) -> dict:
    """Grade every ``grade_in_*.jsonl`` batch and write ``grades_<n>.jsonl`` plus one combined ``grades.jsonl``."""
    out = Path(out_dir)
    files = sorted(out.glob("grade_in_*.jsonl"))
    if limit:
        files = files[:limit]
    all_rows, reports = [], []
    for path in files:
        report = grade_batch(path, agy_call.model_id(model), run=run_fn, workspace=workspace)
        rows = [dict(r, batch=path.stem) for r in report["grades"]]
        (out / f"grades_{path.stem.split('_')[-1]}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        all_rows.extend(rows)
        reports.append({k: report[k] for k in ("batch", "attempts", "error")} |
                       {"graded": len(rows), "missing": report["missing"]})
    (out / "grades.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in all_rows), encoding="utf-8")
    summary = {"model": model, "batches": len(files), "graded": len(all_rows),
               "unparsed": sum(len(r["missing"]) for r in reports),
               "bad_batches": [r["batch"] for r in reports if r["error"]],
               "report": reports}
    (out / "grade_run.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


# --- decoding ----------------------------------------------------------------------------------------
def decode(out_dir: str | Path, key_path: str | Path | None = None) -> dict:
    """Per-set totals, a per-question table and pairwise agreement between the sets."""
    out = Path(out_dir)
    key = Path(key_path) if key_path else out.parent / "key_private" / f"key_{out.name}.csv"
    with key.open(newline="", encoding="utf-8") as fh:
        mapping = {(r["qid"], r["label"]): r["set"] for r in csv.DictReader(fh)}
    rows = [json.loads(line) for line in (out / "grades.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    table: dict[str, dict[str, str]] = {}
    for row in rows:
        set_name = mapping.get((row["qid"], row["label"]))
        if set_name:
            table.setdefault(row["qid"], {})[set_name] = row["grade"]
    sets = sorted({name for name in mapping.values()})
    totals: dict[str, dict[str, float]] = {s: {g: 0 for g in GRADES} for s in sets}
    for by_set in table.values():
        for name, grade in by_set.items():
            totals[name][grade] = totals[name].get(grade, 0) + 1
    for name, counts in totals.items():
        graded = sum(counts.values())
        counts["graded"] = graded
        counts["right_equivalent"] = counts["right"] + counts["not_held"]
        counts["right_pct"] = round(100.0 * counts["right_equivalent"] / graded, 1) if graded else 0.0
    pairs: dict[str, dict] = {}
    for i, a in enumerate(sets):
        for b in sets[i + 1:]:
            same = right = both = 0
            for by_set in table.values():
                if a in by_set and b in by_set:
                    both += 1
                    same += 1 if by_set[a] == by_set[b] else 0
                    right += 1 if by_set[a] in RIGHT_EQUIVALENT and by_set[b] in RIGHT_EQUIVALENT else 0
            pairs[f"{a}|{b}"] = {"questions": both, "agree_grade": same, "agree_right": right,
                                 "agree_right_pct": round(100.0 * right / both, 1) if both else 0.0}
    per_question = [{"qid": qid, **{s: table[qid].get(s, "") for s in sets}} for qid in sorted(table)]
    result = {"sets": sets, "questions": len(table), "totals": totals,
              "coverage": {s: sum(1 for v in table.values() if s in v) for s in sets},
              "pairwise": pairs, "per_question": per_question}
    (out / "decoded.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    with (out / "per_question.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["qid", *sets])
        writer.writeheader()
        writer.writerows(per_question)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m reality_engine.answer.blind_grade")
    sub = ap.add_subparsers(dest="cmd", required=True)
    mk = sub.add_parser("make", help="write the blind batches, the rules and the private key")
    mk.add_argument("--set", action="append", default=[], metavar="NAME=DIR", required=True)
    mk.add_argument("--out", required=True)
    mk.add_argument("--questions", default="")
    mk.add_argument("--seed", type=int, default=SEED)
    mk.add_argument("--batch", type=int, default=BATCH)
    mk.add_argument("--key", default="")
    gr = sub.add_parser("run", help="one agy grader run per batch")
    gr.add_argument("--out", required=True)
    gr.add_argument("--model", default=MODEL)
    gr.add_argument("--workspace", default=".")
    gr.add_argument("--limit", type=int, default=0)
    dc = sub.add_parser("decode", help="per-set totals, the per-question table, pairwise agreement")
    dc.add_argument("--out", required=True)
    dc.add_argument("--key", default="")
    args = ap.parse_args(argv)
    if args.cmd == "make":
        sets = {}
        for item in args.set:
            name, _, folder = item.partition("=")
            if not folder:
                ap.error(f"--set needs NAME=DIR, got {item!r}")
            sets[name.strip()] = folder.strip()
        questions = args.questions or f"D:/RealityEngine/{next(iter(sets))}/answers/questions_in.json"
        summary = make(sets, args.out, questions=questions, seed=args.seed, batch=args.batch,
                       key_path=args.key or None)
        print(json.dumps(summary, indent=1))
        return 0
    if args.cmd == "run":
        summary = run(args.out, model=args.model, workspace=args.workspace, limit=args.limit)
        print(json.dumps(summary, indent=1))
        return 0 if not summary["bad_batches"] and not summary["unparsed"] else 2
    result = decode(args.out, args.key or None)
    print(json.dumps({k: result[k] for k in ("sets", "questions", "totals", "pairwise")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
