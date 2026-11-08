"""Shivam's per-run answer report (8 Nov 2026): after EVERY question/answer run, one Excel workbook (+ CSV of the
answers) in ``D:\\RealityEngine\\reports\\`` with the questions, the answers given, the grades, the errors found,
the documents involved and the root causes.

Input: a graded JSONL, one object per question (extra keys are kept in the Answers sheet):

    run_id, qid, symbol, question, reframed_question, as_of, use (H/M/L), kind,
    tools (list of tool calls), answer, sources (list of {doc_key, doc_type, page, known_at}),
    grade (right | partly | wrong | not_held | scope_out), error (what is wrong, '' when right),
    root_cause (one of ROOT_CAUSES), fix (ticket or action), source_if_missing (raw source wishlist)

    python -m reality_engine.scripts.answer_run_report --run <graded.jsonl> --name <topic>
        -> D:\\RealityEngine\\reports\\YYYY-MM-DD_<topic>.xlsx and YYYY-MM-DD_<topic>_answers.csv

Sheets: Summary (grades per company and kind, right-rate on what the store should answer), Answers (every
row), Errors (every non-right row), Documents (per source document: rows citing it, wrong/partly among them),
Root causes (counts and examples), Wishlist (raw sources that would answer the not-held rows).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

OUT_DIR = Path(os.environ.get("REALITY_REPORTS_DIR", r"D:\RealityEngine\reports"))
GRADES = ("right", "partly", "wrong", "not_held", "scope_out")
ROOT_CAUSES = {
    "raw_missing": "the document that states it is not held (fetch it)",
    "not_extracted": "the document is held but no row was extracted (extractor gap)",
    "wrong_row": "a stored row is wrong (extractor or checker fault)",
    "quarantined": "the right row exists but the checker hid it",
    "routing": "the model asked the wrong tool or arguments",
    "reading": "the model misread a right row or sum",
    "compute": "a formula or calc step missing or wrong",
    "question": "the question cannot be answered from filings (scope or wording)",
    "": "right answer",
}
COLS = ["run_id", "qid", "symbol", "use", "kind", "question", "reframed_question", "as_of", "answer", "grade",
        "error", "root_cause", "fix", "source_if_missing", "tools", "sources"]


def _flat(v) -> str:
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return "" if v is None else str(v)


def load(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if line.strip():
                r = json.loads(line)
                if r.get("grade") not in GRADES:
                    raise ValueError(f"{path}:{n}: grade {r.get('grade')!r} not in {GRADES}")
                if r.get("root_cause", "") not in ROOT_CAUSES:
                    raise ValueError(f"{path}:{n}: root_cause {r.get('root_cause')!r} not in {sorted(ROOT_CAUSES)}")
                rows.append(r)
    return rows


def write(rows: list[dict], name: str, out_dir: Path | None = None) -> tuple[Path, Path]:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    out_dir = Path(out_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    day = time.strftime("%Y-%m-%d")
    xlsx, csv_path = out_dir / f"{day}_{name}.xlsx", out_dir / f"{day}_{name}_answers.csv"
    extra = sorted({k for r in rows for k in r} - set(COLS))
    cols = COLS + extra

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    total = Counter(r["grade"] for r in rows)
    should = [r for r in rows if r["grade"] != "scope_out"]
    right = sum(1 for r in should if r["grade"] == "right")
    ws.append([f"Run {', '.join(sorted({str(r.get('run_id', '')) for r in rows}))}: {len(rows)} questions"])
    ws.append([f"Right on answerable questions: {right} of {len(should)} ({(100 * right / len(should)) if should else 0:.1f}%)"])
    ws.append([])
    ws.append(["symbol", *GRADES, "total"])
    by_sym = defaultdict(Counter)
    for r in rows:
        by_sym[r.get("symbol", "")][r["grade"]] += 1
    for sym in sorted(by_sym):
        ws.append([sym, *(by_sym[sym][g] for g in GRADES), sum(by_sym[sym].values())])
    ws.append(["ALL", *(total[g] for g in GRADES), len(rows)])
    ws.append([])
    ws.append(["use / kind", *GRADES])
    by_use = defaultdict(Counter)
    for r in rows:
        by_use[f"{r.get('use', '')} / {r.get('kind', '')}"][r["grade"]] += 1
    for k in sorted(by_use):
        ws.append([k, *(by_use[k][g] for g in GRADES)])

    def sheet(title, header, data, widths):
        s = wb.create_sheet(title)
        s.append(header)
        for c in s[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="334155")
        for d in data:
            s.append([_flat(v) for v in d])
        for i, w in enumerate(widths):
            s.column_dimensions[chr(65 + i) if i < 26 else "A"].width = w
        for row in s.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
        s.freeze_panes = "A2"
        if s.max_row > 1:
            s.auto_filter.ref = s.dimensions

    w = [10, 8, 12, 5, 9, 50, 50, 11, 60, 9, 40, 14, 20, 30, 40, 40]
    sheet("Answers", cols, [[r.get(c) for c in cols] for r in rows], w)
    errs = [r for r in rows if r["grade"] in ("partly", "wrong", "not_held")]
    sheet("Errors", cols, [[r.get(c) for c in cols] for r in errs], w)

    docs = defaultdict(lambda: Counter())
    meta = {}
    for r in rows:
        for s in r.get("sources") or []:
            key = s.get("doc_key") if isinstance(s, dict) else str(s)
            docs[key][r["grade"]] += 1
            if isinstance(s, dict):
                meta[key] = (r.get("symbol", ""), s.get("doc_type", ""), s.get("known_at", ""))
    sheet("Documents", ["doc_key", "symbol", "doc_type", "known_at", "rows citing it", *GRADES],
          [[k, *meta.get(k, ("", "", "")), sum(c.values()), *(c[g] for g in GRADES)]
           for k, c in sorted(docs.items(), key=lambda kv: -(kv[1]["wrong"] + kv[1]["partly"]))],
          [60, 12, 14, 20, 10, 8, 8, 8, 8, 8])

    rc = defaultdict(list)
    for r in errs:
        rc[r.get("root_cause", "")].append(r)
    sheet("Root causes", ["root_cause", "meaning", "rows", "symbols", "example qids", "example error"],
          [[k, ROOT_CAUSES.get(k, ""), len(v), ", ".join(sorted({x.get("symbol", "") for x in v})),
            ", ".join(str(x.get("qid")) for x in v[:8]), v[0].get("error", "")]
           for k, v in sorted(rc.items(), key=lambda kv: -len(kv[1]))], [16, 50, 8, 30, 40, 60])

    wish = Counter((r.get("symbol", ""), r.get("source_if_missing", "")) for r in rows
                   if r.get("source_if_missing") and r["grade"] in ("not_held", "partly", "wrong"))
    sheet("Wishlist", ["symbol", "raw source that would answer it", "questions"],
          [[s, src, n] for (s, src), n in wish.most_common()], [14, 80, 10])
    wb.save(xlsx)

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(cols)
        for r in rows:
            wr.writerow([_flat(r.get(c)) for c in cols])
    return xlsx, csv_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="per-run answer report for Shivam")
    ap.add_argument("--run", type=Path, required=True, help="graded JSONL")
    ap.add_argument("--name", required=True, help="topic in the file name, e.g. t124_q12_answers")
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args(argv)
    x, c = write(load(args.run), args.name, args.out_dir)
    print(f"wrote {x}\nwrote {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
