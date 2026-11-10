"""T-179: draw the 120 test questions for the raw-SQL A/B answer test.

    python -m reality_engine.scripts.sql_ab_sample --out .tmp/t179

Writes ``questions.csv`` (qid, symbol, store path, as_of, question, earlier_grade, source_run)
to ``--out``. 60 from pilot10 (20 graded R, 40 graded P on the 5 Nov run) and 60 from
u8 + q12 (30 graded right, 30 not right; scope_out rows excluded). Stratified by company
so no company has more than 12. Fixed ``--seed`` (default 20261110) -> identical file.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

PILOT10_DB_DEFAULT = "D:/RealityEngine/pilot10/pilot10.db"
U8_DB_DEFAULT = "D:/RealityEngine/u8/u8.db"
Q12_DB_DEFAULT = "D:/RealityEngine/q12/q12.db"


def load_pilot10(pilot10_dir, grades_path=None, store_path=PILOT10_DB_DEFAULT):
    pilot10_dir = Path(pilot10_dir)
    if grades_path is None:
        grades_path = pilot10_dir / "answer_a3" / "grades.tsv"
    grade_map = {}
    if grades_path is not None and Path(grades_path).exists():
        with open(grades_path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                grade_map[row["qid"]] = row["grade"]
    qdir = pilot10_dir / "answer_a3"
    questions = []
    if qdir.exists():
        for qf in sorted(qdir.glob("*_questions.json")):
            questions.extend(json.load(open(qf, encoding="utf-8")))
    r_cands, p_cands = [], []
    for q in questions:
        qid = q["qid"]
        g = grade_map.get(qid)  # None => right
        sym = qid.split("-")[0]
        row = {
            "qid": qid,
            "symbol": sym,
            "store path": store_path,
            "as_of": q["as_of"],
            "question": q["question"],
            "company": sym,
        }
        if g == "P":
            row["earlier_grade"] = "P"
            row["source_run"] = "pilot10"
            p_cands.append(row)
        elif g is None:
            row["earlier_grade"] = "R"
            row["source_run"] = "pilot10"
            r_cands.append(row)
        # W and others excluded
    return r_cands, p_cands


def load_u8_q12(u8_csv, q12_csv, store_paths=None):
    if store_paths is None:
        store_paths = {"u8": U8_DB_DEFAULT, "q12": Q12_DB_DEFAULT}
    right, notright = [], []
    for path, source in ((Path(u8_csv), "u8"), (Path(q12_csv), "q12")):
        if not path.exists():
            continue
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                grade = (r.get("grade") or "").strip()
                if grade == "scope_out":
                    continue
                sym = r["symbol"]
                row = {
                    "qid": r["qid"],
                    "symbol": sym,
                    "store path": store_paths.get(source, ""),
                    "as_of": r.get("as_of", ""),
                    "question": r.get("question", ""),
                    "company": sym,
                    "earlier_grade": grade,
                    "source_run": source,
                }
                if grade == "right":
                    right.append(row)
                else:
                    notright.append(row)
    return right, notright


def stratified_sample(candidates, n, max_per_company, rng, counts=None):
    if counts is None:
        counts = {}
    counts = dict(counts)
    by_co = defaultdict(list)
    for c in candidates:
        by_co[c["company"]].append(c)
    for co in by_co:
        rng.shuffle(by_co[co])
    companies = sorted(by_co)
    idx = {co: 0 for co in companies}
    run_counts = {co: 0 for co in companies}
    selected = []
    selected_set = set()
    while len(selected) < n:
        progressed = False
        for co in companies:
            if len(selected) >= n:
                break
            if run_counts[co] + counts.get(co, 0) >= max_per_company:
                continue
            # advance past already selected
            while idx[co] < len(by_co[co]) and id(by_co[co][idx[co]]) in selected_set:
                idx[co] += 1
            if idx[co] < len(by_co[co]):
                row = by_co[co][idx[co]]
                idx[co] += 1
                selected.append(row)
                selected_set.add(id(row))
                run_counts[co] += 1
                progressed = True
        if not progressed:
            break
    return selected


def build_sample(pilot10_dir, grades_path=None, pilot10_db=PILOT10_DB_DEFAULT,
                u8_csv=None, q12_csv=None, u8_db=U8_DB_DEFAULT, q12_db=Q12_DB_DEFAULT,
                seed=20261110, max_per_company=12):
    r_cands, p_cands = load_pilot10(pilot10_dir, grades_path, store_path=pilot10_db)
    right_cands, notright_cands = load_u8_q12(
        u8_csv or "D:/RealityEngine/reports/2026-11-09_t130_u8_answers.csv",
        q12_csv or "D:/RealityEngine/reports/2026-11-09_t124_q12_answers.csv",
        store_paths={"u8": u8_db, "q12": q12_db},
    )

    rng = random.Random(seed)
    sel_r = stratified_sample(r_cands, 20, max_per_company, rng)
    counts = Counter(s["company"] for s in sel_r)
    sel_p = stratified_sample(p_cands, 40, max_per_company, rng, counts=counts)

    counts2 = Counter(s["company"] for s in (sel_r + sel_p))
    # u8+q12 right/notright share the same company pool; reset counts for new pool? 
    # Keep global max across all: combine capacity
    # We'll sample right first, then notright with updated counts
    sel_right = stratified_sample(right_cands, 30, max_per_company, rng, counts=counts2)
    counts3 = counts2 + Counter(s["company"] for s in sel_right)
    sel_notright = stratified_sample(notright_cands, 30, max_per_company, rng, counts=counts3)

    out_rows = []
    for r in (sel_r + sel_p + sel_right + sel_notright):
        out_rows.append({
            "qid": r["qid"],
            "symbol": r["symbol"],
            "store path": r["store path"],
            "as_of": r["as_of"],
            "question": r["question"],
            "earlier_grade": r["earlier_grade"],
            "source_run": r["source_run"],
        })
    return out_rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="draw the 120 T-179 test questions")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=20261110)
    ap.add_argument("--pilot10-dir", type=Path, default=Path("D:/RealityEngine/pilot10"))
    ap.add_argument("--pilot10-grades", type=Path, default=None)
    ap.add_argument("--pilot10-db", type=str, default=PILOT10_DB_DEFAULT)
    ap.add_argument("--u8-csv", type=Path, default=Path("D:/RealityEngine/reports/2026-11-09_t130_u8_answers.csv"))
    ap.add_argument("--q12-csv", type=Path, default=Path("D:/RealityEngine/reports/2026-11-09_t124_q12_answers.csv"))
    ap.add_argument("--u8-db", type=str, default=U8_DB_DEFAULT)
    ap.add_argument("--q12-db", type=str, default=Q12_DB_DEFAULT)
    args = ap.parse_args(argv)

    rows = build_sample(
        pilot10_dir=args.pilot10_dir,
        grades_path=args.pilot10_grades,
        pilot10_db=args.pilot10_db,
        u8_csv=args.u8_csv,
        q12_csv=args.q12_csv,
        u8_db=args.u8_db,
        q12_db=args.q12_db,
        seed=args.seed,
    )
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "questions.csv"
    fieldnames = ["qid", "symbol", "store path", "as_of", "question", "earlier_grade", "source_run"]
    with open(out_csv, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"wrote {out_csv} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
