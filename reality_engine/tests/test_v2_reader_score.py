import csv
import json
import uuid
from pathlib import Path

import pymupdf

from reality_engine.v2 import reader_score as rs
from reality_engine.v2 import reference_geom as rg


def _base():
    base = Path(".tmp/test_reader_score")
    base.mkdir(parents=True, exist_ok=True)
    d = base / uuid.uuid4().hex
    d.mkdir()
    return d


def _make_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=200)
    def t(x, y, s):
        page.insert_text((x, y + 8), s, fontsize=10)
    t(200, 10, "Q2FY26"); t(260, 10, "Q1FY26")
    t(10, 30, "Revenue"); t(200, 30, "100"); t(260, 30, "90")
    t(10, 45, "Exceptional"); t(70, 45, "items"); t(260, 45, "7")
    t(10, 60, "Profit"); t(200, 60, "40"); t(260, 60, "30")
    t(10, 75, "Tax"); t(200, 75, "12"); t(260, 75, "9")
    doc.save(str(path))
    doc.close()


def _make_pages_csv(base):
    pdf_dir = base / "pdf_pages"
    pdf_dir.mkdir()
    _make_pdf(pdf_dir / "p001.pdf")
    pages_csv = base / "pages.csv"
    with pages_csv.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["page_id", "store", "symbol", "doc key", "sha256", "doc type", "page",
                    "stratum", "in_first_build", "split"])
        w.writerow(["p001", "s", "SYM", "dk", "sha", "results", "1", "ruled_table", "False", "dev"])
    return pages_csv, pdf_dir


def _run(base, name, rows):
    d = base / name
    d.mkdir()
    (d / "p001.rows.json").write_text(json.dumps(rows))
    (d / "transcribe_log.csv").write_text(
        "page_id,reader,input,seconds,in_tok,out_tok,error,n_rows\n"
        f"p001,{name},text,1.0,10,20,,{len(rows)}\n")
    return d


def test_good_run_scores_perfect():
    base = _base()
    pages_csv, pdf_dir = _make_pages_csv(base)
    good_rows = [
        {"table": "P&L", "row_label": "Revenue", "col_header": "Q2FY26", "value": "100", "unit": ""},
        {"table": "P&L", "row_label": "Exceptional items", "col_header": "Q1FY26", "value": "7", "unit": ""},
        {"table": "P&L", "row_label": "Profit", "col_header": "Q2FY26", "value": "40", "unit": ""},
    ]
    good_dir = _run(base, "good", good_rows)
    ref = rs.build_reference(pages_csv, pdf_dir, [good_dir])
    res = rs.score_run(good_dir, pages_csv, pdf_dir, ref)
    assert res["precision_verified"] == 1.0
    assert res["recall"] == 1.0


def test_shifted_run_lower():
    base = _base()
    pages_csv, pdf_dir = _make_pages_csv(base)
    good_rows = [
        {"table": "P&L", "row_label": "Revenue", "col_header": "Q2FY26", "value": "100", "unit": ""},
        {"table": "P&L", "row_label": "Exceptional items", "col_header": "Q1FY26", "value": "7", "unit": ""},
        {"table": "P&L", "row_label": "Profit", "col_header": "Q2FY26", "value": "40", "unit": ""},
    ]
    shifted_rows = [
        {"table": "P&L", "row_label": "Revenue", "col_header": "Q2FY26", "value": "100", "unit": ""},
        {"table": "P&L", "row_label": "Exceptional items", "col_header": "Q2FY26", "value": "40", "unit": ""},
        {"table": "P&L", "row_label": "Profit", "col_header": "Q2FY26", "value": "30", "unit": ""},
    ]
    good_dir = _run(base, "good", good_rows)
    shifted_dir = _run(base, "shifted", shifted_rows)
    ref = rs.build_reference(pages_csv, pdf_dir, [good_dir, shifted_dir])
    g = rs.score_run(good_dir, pages_csv, pdf_dir, ref)
    s = rs.score_run(shifted_dir, pages_csv, pdf_dir, ref)
    assert s["precision_verified"] < 1.0
    assert s["recall"] < g["recall"]


def test_pair_self_consistency_one():
    base = _base()
    pages_csv, pdf_dir = _make_pages_csv(base)
    good_rows = [
        {"table": "P&L", "row_label": "Revenue", "col_header": "Q2FY26", "value": "100", "unit": ""},
        {"table": "P&L", "row_label": "Exceptional items", "col_header": "Q1FY26", "value": "7", "unit": ""},
        {"table": "P&L", "row_label": "Profit", "col_header": "Q2FY26", "value": "40", "unit": ""},
    ]
    good_dir = _run(base, "good", good_rows)
    ref = rs.build_reference(pages_csv, pdf_dir, [good_dir])
    res = rs.score_run(good_dir, pages_csv, pdf_dir, ref)
    a, b = rs.consistency(res, res)
    assert a == 1.0 and b == 1.0
