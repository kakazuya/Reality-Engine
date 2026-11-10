"""Shivam (8 Nov): every answer run leaves an Excel + CSV report of questions, answers, grades, errors, documents, root causes."""
import json

import openpyxl
import pytest

from reality_engine.scripts import answer_run_report as ar


def _rows():
    return [
        {"run_id": "t", "qid": "r1", "symbol": "DLF", "question": "q1", "answer": "a", "grade": "right",
         "root_cause": "", "sources": [{"doc_key": "DLF/t.pdf", "doc_type": "transcript", "page": 3, "known_at": "2026-08-07"}]},
        {"run_id": "t", "qid": "r2", "symbol": "DLF", "question": "q2", "answer": "", "grade": "not_held",
         "error": "no pre-sales row", "root_cause": "not_extracted", "source_if_missing": "", "sources": []},
        {"run_id": "t", "qid": "r3", "symbol": "SAIL", "question": "q3", "answer": "x", "grade": "wrong",
         "error": "9M as FY", "root_cause": "wrong_row", "sources": [{"doc_key": "SAIL/d.pdf"}]},
        {"run_id": "t", "qid": "r4", "symbol": "SAIL", "question": "q4", "grade": "scope_out", "root_cause": "question"},
    ]


def test_report_sheets_and_csv(tmp_path):
    run = tmp_path / "g.jsonl"
    run.write_text("\n".join(json.dumps(r) for r in _rows()), encoding="utf-8")
    x, c = ar.write(ar.load(run), "unit", tmp_path)
    wb = openpyxl.load_workbook(x)
    assert wb.sheetnames == ["Summary", "Answers", "Errors", "Documents", "Root causes", "Wishlist"]
    assert wb["Answers"].max_row == 5 and wb["Errors"].max_row == 3
    assert "1 of 3" in wb["Summary"]["A2"].value
    assert c.read_text(encoding="utf-8-sig").count("\n") == 5


def test_bad_grade_or_cause_is_refused(tmp_path):
    run = tmp_path / "g.jsonl"
    run.write_text(json.dumps({"qid": "x", "grade": "maybe"}), encoding="utf-8")
    with pytest.raises(ValueError):
        ar.load(run)


def test_call_log_columns():
    base = __import__("pathlib").Path("arr_t179")
    base.mkdir(exist_ok=True)
    run = base / "g.jsonl"
    rows = [
        {"run_id": "t", "qid": "r1", "symbol": "DLF", "question": "q1", "answer": "a", "grade": "right",
         "root_cause": "", "sources": []},
    ]
    run.write_text("\n".join(__import__("json").dumps(r) for r in rows), encoding="utf-8")
    log = base / "calls.jsonl"
    import time
    ts = time.time()
    log.write_text(__import__("json").dumps({"ts_start": ts, "ts_end": ts + 1.0, "seconds": 1.0, "qid": "r1",
                              "tool": "sql", "args": "{}", "ok": True, "reply bytes": 10}) + "\n",
                   encoding="utf-8")
    x, c = ar.write(ar.load(run), "unit", base, call_log=log)
    wb = openpyxl.load_workbook(x)
    hdr = [cell.value for cell in wb["Answers"][1]]
    assert "calls" in hdr
    assert "wall_seconds" in hdr
    x2, c2 = ar.write(ar.load(run), "unit2", base)
    wb2 = openpyxl.load_workbook(x2)
    hdr2 = [cell.value for cell in wb2["Answers"][1]]
    assert "calls" not in hdr2
