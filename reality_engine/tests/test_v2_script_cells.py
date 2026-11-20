import sqlite3

from reality_engine.v2 import script_cells as sc


def _c(status, value="1,200.50", **kw):
    c = {"doc_key": "d1", "page": 3, "symbol": "ABC", "known_at": "2025-11-10", "title": "Statement of results",
         "section": "", "row_label": "Revenue from operations", "col_header": "Quarter ended 30.09.2025",
         "value_text": value, "unit_scale": 1e5, "period_end": "2025-09-30", "kind": "quarter",
         "basis": "consolidated", "status": status, "witness": "xbrl", "gate": "single_filing",
         "box": (200.0, 50.0, 240.0, 58.0)}
    c.update(kw)
    return c


STATS = {"pages": 1, "cells_read": 3, "verified": 1, "unverified": 1, "refused": 1, "errors": 0}


def test_only_served_cells_are_written_and_a_rebuild_replaces_them(tmp_path):
    db = tmp_path / "s.db"
    sqlite3.connect(db).execute("CREATE TABLE doc (doc_key TEXT)").connection.commit()
    cells = [_c("verified"), _c("unverified", witness="cross", gate="pass"), _c("refused", witness="")]
    assert sc.write_store(db, cells, STATS, 1.0) == 2
    assert sc.write_store(db, cells[:1], STATS, 1.0) == 1
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM script_cell").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM script_cell_run").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM doc").fetchone() is not None       # the store's own tables untouched


def test_row_keeps_printed_and_resolved_fields():
    row = sc._row(_c("verified", value="(1,200.50)", period_inferred=True))
    cols = ("doc_key page symbol known_at reader version table_title section row_label col_header value_text value "
            "unit_scale period_end period_kind basis period_inferred basis_inferred status witness gate "
            "x0 y0 x1 y1 line_item line_source fiscal_period").split()
    r = dict(zip(cols, row))
    assert r["value_text"] == "(1,200.50)" and r["value"] == -1200.50e5
    assert (r["period_end"], r["period_kind"], r["basis"]) == ("2025-09-30", "quarter", "consolidated")
    assert r["period_inferred"] == 1 and r["basis_inferred"] == 0 and r["reader"] == "script"
    assert (r["line_item"], r["line_source"], r["fiscal_period"]) == ("revenue_from_operations", "lexicon", "Q2FY26")
    xr = dict(zip(cols, sc._row(_c("verified", _xline="total_income"))))
    assert (xr["line_item"], xr["line_source"]) == ("total_income", "xbrl")


def test_no_unit_gives_no_numeric_value():
    r = sc._row(_c("unverified", unit_scale=None))
    assert r[11] is None


def test_fiscal_period_labels():
    f = sc.fiscal_period
    assert [f("2025-09-30", "quarter", 3), f("2026-03-31", "year", 3), f("2025-09-30", "half", 3),
            f("2025-12-31", "quarter", 12), f("2025-03-31", "as_at", 3)] == ["Q2FY26", "FY26", "H1FY26", "Q4FY25", ""]
