"""T-177/T-180: reference cells settled by printed position; page text laid out as printed."""
from reality_engine.v2 import reference_geom as rg
from reality_engine.v2.page_layout import layout_text


def _w(x0, y0, text, cw=5.0, h=8.0):
    return (x0, y0, x0 + cw * len(text), y0 + h, text)


def _results_page():
    """Two columns; the second row is blank in the first column (the cell a column-major reading shifts into)."""
    return [
        _w(200, 10, "Q2FY26"), _w(260, 10, "Q1FY26"),
        _w(10, 30, "Revenue"), _w(200, 30, "100"), _w(260, 30, "90"),
        _w(10, 45, "Exceptional"), _w(70, 45, "items"), _w(260, 45, "7"),
        _w(10, 60, "Profit"), _w(200, 60, "40"), _w(260, 60, "30"),
        _w(10, 75, "Tax"), _w(200, 75, "12"), _w(260, 75, "9"),
    ]


def _cell(label, col, value):
    return {"table": "P&L", "row_label": label, "col_header": col, "value": value, "unit": ""}


def test_position_settles_true_cells_and_rejects_a_shifted_number():
    words = _results_page()
    good = [_cell("Revenue", "Q2FY26", "100"), _cell("Exceptional items", "Q1FY26", "7"),
            _cell("Profit", "Q2FY26", "40")]
    shifted = [_cell("Revenue", "Q2FY26", "100"), _cell("Exceptional items", "Q2FY26", "40"),
               _cell("Profit", "Q2FY26", "30")]
    cells, _unread = rg.settle_page([good, shifted], words)
    by = {(c["row_label"], c["value_text"]): c for c in cells}
    assert by[("Revenue", "100")]["settled_by"] == "script+position"
    assert by[("Exceptional items", "7")]["settled_by"] == "position"
    assert by[("Profit", "40")]["settled_by"] == "position"
    assert not by[("Exceptional items", "40")]["settled_by"]          # 40 is printed on the Profit line
    assert not by[("Profit", "30")]["settled_by"]                     # 30 is under Q1FY26, not Q2FY26


def test_unread_numbers_lists_table_numbers_no_reader_gave():
    cells, unread = rg.settle_page([[_cell("Revenue", "Q2FY26", "100")]], _results_page())
    assert {u["value_text"] for u in unread} == {"90", "7", "40", "30", "12", "9"}


def test_layout_keeps_the_blank_cell():
    text = layout_text(_results_page(), width=60).splitlines()
    exc = next(line for line in text if line.startswith("Exceptional"))
    rev = next(line for line in text if line.startswith("Revenue"))
    assert exc.rstrip().endswith("7") and exc.index("7") == rev.index("90")
