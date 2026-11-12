"""T-199: the atom resolver turns position-checked page cells into one resolved figure each.

Fixtures only: a store with ``doc`` / ``doc_page`` / ``page_cell`` (/ ``kpi_series``), no network, no model.
"""
from __future__ import annotations

import csv
import sqlite3
import uuid
from pathlib import Path

from reality_engine.pilot3 import atoms

BASE = Path(".tmp/test_pilot3_atoms")
KNOWN = "2026-08-10T17:00:00"

DOC = ("CREATE TABLE doc (doc_key TEXT PRIMARY KEY, symbol TEXT, doc_type TEXT, title TEXT, known_at TEXT, "
       "isin TEXT)")
DOC_PAGE = "CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT, method TEXT, PRIMARY KEY (doc_key, page))"
PAGE_CELL = ("CREATE TABLE page_cell (doc_key TEXT, page INTEGER, symbol TEXT, known_at TEXT, reader TEXT, "
             "table_title TEXT, row_label TEXT, col_header TEXT, value_text TEXT, unit_text TEXT, status TEXT, "
             "conflict TEXT, x0 REAL, y0 REAL, x1 REAL, y1 REAL)")
KPI = "CREATE TABLE kpi_series (symbol TEXT, metric TEXT, fiscal_period TEXT, doc_key TEXT)"


def _base() -> Path:
    BASE.mkdir(parents=True, exist_ok=True)
    path = BASE / uuid.uuid4().hex[:12]
    path.mkdir()
    return path


def _cell(doc_key: str = "d1", page: int = 1, row_label: str = "Revenue", col_header: str = "Q2FY26",
          value_text: str = "1,234", unit_text: str = "Rs crore", status: str = "verified",
          table_title: str = "Segment results", known_at: str = KNOWN) -> tuple:
    return (doc_key, page, "TST", known_at, "haiku_sub", table_title, row_label, col_header, value_text,
            unit_text, status)


def _db(base: Path, cells: list[tuple], page_text: str = "", known_at: str = KNOWN,
        doc_type: str = "deck", kpi: list[tuple] | None = None) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    db = base / "store.db"
    con = sqlite3.connect(str(db))
    con.execute(DOC)
    con.execute(DOC_PAGE)
    con.execute(PAGE_CELL)
    con.execute(KPI)
    con.execute("INSERT INTO doc VALUES ('d1','TST',?, 'Segment results', ?,'INE000A01010')", (doc_type, known_at))
    con.execute("INSERT INTO doc VALUES ('d2','TST',?, 'Segment results', ?,'INE000A01010')",
                (doc_type, "2026-09-10T17:00:00"))
    con.execute("INSERT INTO doc_page VALUES ('d1',1,?,'script_text')", (page_text,))
    for cell in cells:
        con.execute("INSERT INTO page_cell VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,NULL)", cell)
    for row in kpi or []:
        con.execute("INSERT INTO kpi_series VALUES (?,?,?,?)", row)
    con.commit()
    con.close()
    return db


def _rows(db: Path) -> list[dict]:
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    rows = [dict(row) for row in con.execute("SELECT * FROM page_atom ORDER BY row_label, col_header")]
    con.close()
    return rows


def test_period_units_value_and_definition_resolve_and_verify():
    base = _base()
    db = _db(base, [_cell()], page_text="Standalone results. Q2FY26 Q1FY26 Revenue 1,234 1,100 in crore")
    out = atoms.run(db)
    assert out["atoms"] == 1 and out["verified"] == 1
    atom = _rows(db)[0]
    assert atom["period"] == "q2fy26"
    assert atom["unit"] == "inr" and atom["scale"] == 1e7
    assert atom["value"] == 1234.0
    assert atom["basis"] == "standalone"
    assert atom["check_status"] == "verified" and atom["check_reasons"] == ""
    assert atom["doc_type"] == "deck" and atom["isin"] == "INE000A01010"


def test_a_relative_header_resolves_only_against_a_fiscal_year_printed_on_the_page():
    base = _base()
    with_year = _db(base / "a", [_cell(col_header="Q2")], page_text="Revenue 1,234\nFY26 results")
    atoms.run(with_year)
    assert _rows(with_year)[0]["period"] == "q2fy26"
    base = _base()
    without = _db(base, [_cell(col_header="Q2")], page_text="Revenue 1,234")
    atoms.run(without)
    atom = _rows(without)[0]
    assert atom["period"] == ""
    assert "period_unresolved" in atom["check_reasons"]
    assert atom["check_status"] == "unverified"


def test_a_page_scale_declaration_sets_unit_and_scale():
    base = _base()
    db = _db(base, [_cell(value_text="1000", unit_text="")], page_text="(Rs. in million)")
    atoms.run(db)
    atom = _rows(db)[0]
    assert atom["unit"] == "inr" and atom["scale"] == 1e6
    assert atom["check_status"] == "verified", atom["check_reasons"]


def test_two_page_declarations_leave_the_unit_unresolved():
    base = _base()
    db = _db(base, [_cell(value_text="1000", unit_text="")], page_text="(Rs. in crore)\n(Rs. in million)")
    atoms.run(db)
    atom = _rows(db)[0]
    assert atom["unit"] == ""
    assert "unit_conflict" in atom["check_reasons"]
    assert atom["check_status"] == "unverified"


def test_a_bare_currency_in_the_value_does_not_override_the_cell_unit():
    base = _base()
    db = _db(base, [_cell(value_text="Rs 1,234", unit_text="Rs crore")])
    atoms.run(db)
    atom = _rows(db)[0]
    assert atom["value"] == 1234.0
    assert atom["unit"] == "inr" and atom["scale"] == 1e7


def test_a_printed_parenthesis_is_a_negative_value():
    base = _base()
    db = _db(base, [_cell(value_text="(1,234)")])
    atoms.run(db)
    assert _rows(db)[0]["value"] == -1234.0


def test_a_dash_prints_no_figure_and_no_atom():
    base = _base()
    db = _db(base, [_cell(value_text="-")])
    assert atoms.run(db)["atoms"] == 0


def test_two_values_for_one_row_period_and_basis_are_both_unverified():
    base = _base()
    db = _db(base, [_cell(value_text="100"), _cell(value_text="110")])
    atoms.run(db)
    rows = _rows(db)
    assert len(rows) == 2
    assert all(row["check_status"] == "unverified" for row in rows)
    assert all("same_doc_conflict" in row["check_reasons"] for row in rows)


def test_an_empty_header_takes_the_documents_own_period_and_stays_unverified():
    base = _base()
    db = _db(base, [_cell(col_header="", row_label="Order book", value_text="45,000")],
             kpi=[("TST", "order_book", "Q2FY27", "d1")])
    atoms.run(db)
    atom = _rows(db)[0]
    assert atom["period"] == "q2fy27"
    assert "period_from_document" in atom["check_reasons"]
    assert atom["check_status"] == "unverified"


def test_an_empty_header_with_a_change_marker_is_a_change_never_a_level():
    base = _base()
    db = _db(base, [_cell(col_header="", row_label="Volume", value_text="▲ 50 bps", unit_text="")])
    atoms.run(db)
    atom = _rows(db)[0]
    assert atom["unit"] == "change"
    assert "change_not_level" in atom["check_reasons"]
    assert atom["check_status"] == "unverified"


def test_a_bracket_legend_is_the_definition_and_the_label_is_kept_whole():
    base = _base()
    label = "Segment 1 (EMP & Commercial Air Conditioning Systems)"
    db = _db(base, [_cell(row_label=label)])
    atoms.run(db)
    atom = _rows(db)[0]
    assert atom["row_label"] == label
    assert atom["definition"] == "legend:emp,commercial,air,conditioning,systems"


def test_an_empty_row_label_is_never_verified():
    base = _base()
    db = _db(base, [_cell(row_label="")])
    atoms.run(db)
    atom = _rows(db)[0]
    assert "label_missing" in atom["check_reasons"]
    assert atom["check_status"] == "unverified"


def test_an_unpositioned_cell_is_unverified_even_with_period_and_unit():
    base = _base()
    db = _db(base, [_cell(status="unverified")])
    atoms.run(db)
    atom = _rows(db)[0]
    assert atom["check_status"] == "unverified"
    assert "position_unverified" in atom["check_reasons"]


def test_duplicates_copy_each_atom_with_the_duplicates_own_document_and_known_at():
    base = _base()
    db = _db(base, [_cell()])
    duplicates = base / "duplicates.csv"
    with duplicates.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["canonical_doc_key", "canonical_page",
                                                "duplicate_doc_key", "duplicate_page"])
        writer.writeheader()
        writer.writerow({"canonical_doc_key": "d1", "canonical_page": 1,
                         "duplicate_doc_key": "d2", "duplicate_page": 3})
    out = atoms.run(db, duplicates)
    assert out["atoms"] == 2 and out["copied"] == 1
    copy = next(row for row in _rows(db) if row["doc_key"] == "d2")
    assert copy["page"] == 3
    assert copy["known_at"] == "2026-09-10T17:00:00"
    assert "copied_from=d1#p1" in copy["check_reasons"]


def test_a_rebuild_is_idempotent_and_keeps_one_row_per_figure():
    base = _base()
    db = _db(base, [_cell()])
    first = atoms.run(db)
    second = atoms.run(db)
    assert first["atoms"] == second["atoms"] == 1


def test_a_store_without_page_cell_is_skipped():
    base = _base()
    db = base / "empty.db"
    con = sqlite3.connect(str(db))
    con.execute(DOC)
    con.commit()
    con.close()
    assert atoms.run(db) == {"skipped": "no page_cell table"}
