"""doc_map: section labels from the YAML map, fiscal year of an annual report, and the must-exist rows."""
from __future__ import annotations

import sqlite3

from reality_engine.pilot3 import doc_map


def test_sections_are_labelled_from_heading_and_row_labels():
    head, secs = doc_map.load()
    cf = ("Consolidated Cash Flow Statement for the year ended 31 March 2024\n"
          "A. Cash flow from operating activities\nProfit before tax 120.5\nB. Cash flow from investing activities")
    assert "cash_flow" in doc_map.label(cf, "annual_report", secs, head)
    # the same words on a results page are the results' own cash-flow section, not the annual report's
    assert doc_map.label(cf, "results", secs, head) == ["cash_flow"]
    bs = ("Standalone Balance Sheet as at 31 March 2025\nNon-current assets\nProperty, plant and equipment\n"
          "Total equity and liabilities 4,512.3")
    labels = doc_map.label(bs, "annual_report", secs, head)
    assert "balance_sheet" in labels and "cash_flow" not in labels
    ratios = ("Note 48 Ratios\nCurrent ratio 1.4 1.3\nDebt-equity ratio 0.2 0.3\nReturn on capital employed 14% 12%")
    assert "key_ratios_note" in doc_map.label(ratios, "annual_report", secs, head)
    assert doc_map.label("", "annual_report", secs, head) == []
    # a heading-only section needs its heading in the first characters of the page
    assert "mdna" not in doc_map.label("x " * 400 + "Management Discussion and Analysis", "annual_report", secs, head)


def test_annual_report_fiscal_year_from_filing_date():
    assert doc_map.fiscal_year("annual_report", "2024-07-12") == "FY24"
    assert doc_map.fiscal_year("annual_report", "2026-02-05") == "FY25"
    assert doc_map.fiscal_year("deck", "2024-07-12") == ""


def test_scan_counts_rows_the_section_must_have(tmp_path):
    db = tmp_path / "c01.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE company(symbol TEXT); INSERT INTO company VALUES('ACME');"
        "CREATE TABLE doc(doc_key TEXT, doc_type TEXT, filing_date TEXT, pages INT);"
        "INSERT INTO doc VALUES('ar24','annual_report','2024-07-12',10), ('ar25','annual_report','2025-07-12',10);"
        "CREATE TABLE doc_page(doc_key TEXT, page INT, text TEXT);"
        "CREATE TABLE fin_annual_line(fiscal_year TEXT, statement TEXT, line_item TEXT);"
        "INSERT INTO fin_annual_line VALUES('FY25','CF','cash_flow_from_operations');")
    page = "Cash Flow Statement\nCash flow from operating activities\nCash flow from investing activities"
    con.executemany("INSERT INTO doc_page VALUES(?,?,?)", [("ar24", 7, page), ("ar25", 7, page)])
    con.commit()
    con.close()
    out_db = tmp_path / "map.db"
    (tmp_path / "c01").mkdir()
    db.rename(tmp_path / "c01" / "c01.db")
    doc_map.scan(tmp_path, None, out_db)
    rows = dict(((s, fy), n) for s, fy, n in sqlite3.connect(out_db).execute(
        "SELECT section, fiscal_year, rows FROM section_rows"))
    assert rows[("cash_flow", "FY24")] == 0 and rows[("cash_flow", "FY25")] == 1
    xlsx = doc_map.report(out_db, tmp_path / "map.xlsx")
    from openpyxl import load_workbook
    wb = load_workbook(xlsx)
    gaps = [[c.value for c in r] for r in wb["gaps"].iter_rows(min_row=2)]
    assert ["c01", "ACME", "annual_report", "cash_flow", "FY24", 0, "fin_annual_line (statement CF)"] in gaps
