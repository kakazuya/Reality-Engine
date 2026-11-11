"""T-177: tests for the per-page completeness report and its gate.

Small fixtures only: a fake pilot3 store, a fake v2 cell store and a generated PDF, all
under ``tmp_path``.  No network, no real store.
"""
from __future__ import annotations

import csv
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pymupdf
import pytest

from reality_engine.v2 import completeness


@pytest.fixture
def tmp_path(request):
    """A fresh temp dir per test.

    The builtin ``tmp_path`` is not usable in this sandbox: ``tempfile.gettempdir()``
    resolves to the repo's ``.tmp``, where an earlier SYSTEM session left
    ``pytest-of-SYSTEM`` ACL-locked, and a ``tempfile.mkdtemp`` directory there is
    created with an ACL that denies the test's own writes.  A plainly created
    directory under the same root is writable, so the fixture makes one itself.
    """
    path = Path(tempfile.gettempdir()) / f"t177-tests-{os.getpid()}" / request.node.name
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)

DOC_KEY = "fixtures/acme/deck/one.pdf"
SHA = "abc123"
COLUMN_RIGHTS = (360.0, 430.0, 500.0)
ROWS = [("Revenue", (11, 21, 31)), ("Costs", (2, 3, 4)), ("Total", (13, 24, 35))]


def _line_text(label: str, values: tuple[int, ...]) -> str:
    return " ".join([label, *(str(value) for value in values)])


def _make_pdf(path: Path, pages: list[list[str]]) -> None:
    """One line list per page: a label printed at x=72 and figures right-aligned on the
    column rights, so the text layer carries aligned numeric columns."""
    document = pymupdf.open()
    for lines in pages:
        page = document.new_page()
        y = 100.0
        for line in lines:
            label, *numbers = line.split()
            page.insert_text((72, y), label, fontsize=10)
            for right, number in zip(COLUMN_RIGHTS, numbers):
                width = pymupdf.get_text_length(number, fontsize=10)
                page.insert_text((right - width, y), number, fontsize=10)
            y += 20
    document.save(str(path))
    document.close()


def _make_store(path: Path, pdf: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE doc (doc_key TEXT PRIMARY KEY, symbol TEXT, isin TEXT, doc_type TEXT,
                          doc_family TEXT, title TEXT, filing_date TEXT, known_at TEXT,
                          pages INTEGER, sha256 TEXT, source TEXT, source_key TEXT);
        CREATE TABLE doc_page (doc_key TEXT, symbol TEXT, page INTEGER, text TEXT,
                               method TEXT, chars INTEGER, known_at TEXT, ocr_conf REAL);
        CREATE TABLE kpi_series (id INTEGER PRIMARY KEY, symbol TEXT, metric TEXT,
                                 value REAL, unit TEXT, scale REAL, doc_key TEXT,
                                 page INTEGER, raw_value TEXT, raw_label TEXT,
                                 quote TEXT, known_at TEXT);
    """)
    con.execute("INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (DOC_KEY, "ACME", "INE001A01001", "deck", "deck", "Fixture deck",
                 "2026-09-30", "2026-10-01T10:00:00", 2, SHA, "pages.db", str(pdf)))
    text = "\n".join(_line_text(label, values) for label, values in ROWS)
    con.execute("INSERT INTO doc_page VALUES (?,?,?,?,?,?,?,?)",
                (DOC_KEY, "ACME", 1, text, "script_text", len(text),
                 "2026-10-01T10:00:00", None))
    con.execute("INSERT INTO kpi_series (symbol, metric, value, unit, scale, doc_key, page, "
                "raw_value, known_at) VALUES (?,?,?,?,?,?,?,?,?)",
                ("ACME", "revenue", 11.0, "inr_cr", 1e7, DOC_KEY, 1, "11",
                 "2026-10-01T10:00:00"))
    con.commit()
    con.close()


def _make_cells(root: Path, drop_column: bool = False) -> None:
    directory = root / "company"
    directory.mkdir(parents=True)
    con = sqlite3.connect(directory / "INE001A01001.db")
    con.executescript("""
        CREATE TABLE doc (doc_key TEXT PRIMARY KEY, sha256 TEXT, doc_type TEXT);
        CREATE TABLE table_cell (cell_id INTEGER PRIMARY KEY, doc_key TEXT, page INTEGER,
                                 table_no INTEGER, row_no INTEGER, col_no INTEGER,
                                 row_label TEXT, value_text TEXT, value REAL, scale REAL);
    """)
    con.execute("INSERT INTO doc VALUES (?,?,?)", (DOC_KEY, SHA, "deck"))
    cells = []
    for row_no, (label, values) in enumerate(ROWS, start=1):
        for col_no, value in enumerate(values, start=1):
            if drop_column and col_no == len(COLUMN_RIGHTS):
                continue
            cells.append((DOC_KEY, 1, 1, row_no, col_no, label, str(value),
                          float(value), 1.0))
    con.executemany("INSERT INTO table_cell (doc_key, page, table_no, row_no, col_no, "
                    "row_label, value_text, value, scale) VALUES (?,?,?,?,?,?,?,?,?)", cells)
    con.commit()
    con.close()


def _rows(path: Path) -> dict[int, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {int(row["page"]): row for row in csv.DictReader(handle)}


def test_printed_values_words_scales_and_exclusions() -> None:
    text = "\n".join([
        "twenty-five crore",
        "twenty-five percent",
        "1,234.50",
        "31.03.2026",
        "Page 7 of 9",
        "7",
        "Note 5 Other matters",
        "Revenue(1) 12.5",
        "²",
    ])
    printed = completeness.printed_values(text, page_no=7)
    forms = [tuple(sorted(item)) for item in printed]
    assert (25.0, 250000000.0) in forms          # number words + a scale word
    assert (25.0,) in forms                      # 'twenty-five percent'
    assert (1234.5,) in forms
    assert (12.5,) in forms
    assert (1.0,) not in forms                   # a footnote mark, not a value
    assert all(2026 not in item for item in forms)   # the date is excluded
    assert all(7 not in item and 9 not in item for item in forms)   # page numbers
    assert all(5 not in item for item in forms)  # a note reference
    assert len(printed) == 4


def test_run_scores_coverage_grid_and_sums(tmp_path: Path) -> None:
    pdf = tmp_path / "one.pdf"
    _make_pdf(pdf, [[_line_text(label, values) for label, values in ROWS], []])
    store = tmp_path / "store.db"
    _make_store(store, pdf)
    cells = tmp_path / "cells"
    _make_cells(cells)
    out = tmp_path / "out"
    completeness.run([store], out, cells)
    pages = _rows(out / "page_coverage.csv")

    complete = pages[1]
    assert complete["unread"] == "0"
    assert int(complete["cells_built"]) == 1
    assert int(complete["numbers_printed"]) == 9      # 11,21,31,2,3,4,13,24,35
    assert int(complete["numbers_stored"]) == 9
    assert float(complete["number_coverage"]) == 1.0
    assert int(complete["grid_rows"]) == 3
    assert int(complete["grid_cols"]) == 3
    assert int(complete["grid_cells_printed"]) == 9
    assert int(complete["grid_cells_stored"]) == 9
    assert float(complete["grid_coverage"]) == 1.0
    assert int(complete["sums_checked"]) == 3        # one Total row per column
    assert int(complete["sums_closed"]) == 3         # 11+2=13, 21+3=24, 31+4=35
    assert "table_cell" in complete["sources"]
    assert "kpi_series" in complete["sources"]       # a fact table cites doc+page

    unread = pages[2]
    assert unread["unread"] == "1"                   # no doc_page row at all
    assert unread["number_coverage"] == ""           # counted, never scored

    with sqlite3.connect(out / "completeness.db") as con:
        assert con.execute("SELECT COUNT(*) FROM page_coverage").fetchone()[0] == 2


def test_gate_fails_on_dropped_column(tmp_path: Path, capsys) -> None:
    pdf = tmp_path / "one.pdf"
    _make_pdf(pdf, [[_line_text(label, values) for label, values in ROWS], []])
    store = tmp_path / "store.db"
    _make_store(store, pdf)
    complete = tmp_path / "complete"
    _make_cells(complete)
    dropped = tmp_path / "dropped"
    _make_cells(dropped, drop_column=True)
    before = tmp_path / "before"
    after = tmp_path / "after"
    completeness.run([store], before, complete)
    completeness.run([store], after, dropped)

    coverage = _rows(after / "page_coverage.csv")[1]
    assert float(coverage["number_coverage"]) < 1.0
    assert completeness.gate(before / "page_coverage.csv",
                             after / "page_coverage.csv") == 1
    assert "NUMBER_COVERAGE" in capsys.readouterr().out
    assert completeness.gate(before / "page_coverage.csv",
                             before / "page_coverage.csv") == 0


def test_calibrate_scores_dev_pages_only(tmp_path: Path) -> None:
    pdf = tmp_path / "one.pdf"
    _make_pdf(pdf, [[_line_text(label, values) for label, values in ROWS], []])
    store = tmp_path / "store.db"
    _make_store(store, pdf)
    cells = tmp_path / "cells"
    _make_cells(cells)
    out = tmp_path / "out"
    completeness.run([store], out, cells)

    pages = tmp_path / "pages.csv"
    pages.write_text(
        "page_id,store,symbol,doc key,sha256,doc type,page,stratum,in_first_build,split\n"
        f"p001,acme,ACME,{DOC_KEY},{SHA},deck,1,ruled_table,False,dev\n"
        f"p002,acme,ACME,{DOC_KEY},{SHA},deck,1,ruled_table,False,frozen\n",
        encoding="utf-8")
    reference = tmp_path / "reference_cells.csv"
    reference.write_text(
        "page_id,table,row_label,col_header,value_text,unit_text,agreed,verbatim,sums_ok,settled_by\n"
        "p001,revenue,Revenue,column one,11,count,True,True,False,script\n"
        "p001,revenue,Revenue,column two,21,count,True,True,False,script\n"
        "p002,revenue,Revenue,column one,999,count,True,True,False,script\n",
        encoding="utf-8")
    assert completeness.calibrate(out / "page_coverage.csv", reference, pages, "dev") == 0
    with (out / "calibration_dev.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["page_id"] for row in rows] == ["p001"]     # frozen p002 is never read
    assert float(rows[0]["reference_recall"]) == 1.0
    assert completeness.calibrate(out / "page_coverage.csv", reference, pages, "frozen") == 2
