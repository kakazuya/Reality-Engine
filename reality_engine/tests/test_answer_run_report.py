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
