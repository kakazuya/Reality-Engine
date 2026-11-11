"""T-177/T-180/T-185: reference cells settled by printed position; page text laid out as printed."""
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


def _spanning_page():
    """Two groups over one date row: "Quarter ended" over the first two columns, "Nine months ended" over the
    last two, with the same column dates printed over both groups (the page the old presence rule mis-confirms)."""
    return [
        _w(160, 10, "Quarter"), _w(196, 10, "ended"),
        _w(370, 10, "Nine"), _w(396, 10, "months"), _w(432, 10, "ended"),
        _w(180, 25, "31-Dec-23"), _w(260, 25, "30-Sep-23"), _w(380, 25, "31-Dec-23"), _w(460, 25, "30-Sep-23"),
        _w(10, 40, "Revenue"), _w(190, 40, "100"), _w(270, 40, "90"), _w(390, 40, "200"), _w(470, 40, "180"),
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


def test_spanning_header_confirm_the_own_group_and_flag_the_other():
    words = _spanning_page()
    good = [_cell("Revenue", "Quarter ended 31-Dec-23", "100"),
            _cell("Revenue", "Nine months ended 31-Dec-23", "200")]
    bad = [_cell("Revenue", "Quarter ended 31-Dec-23", "180")]     # 180 is the nine-month column
    cells, _unread = rg.settle_page([good, bad], words)
    by = {(c["value_text"], c["col_header"]): c for c in cells}
    assert by[("100", "Quarter ended 31-Dec-23")]["verdict"] == "confirmed"
    assert by[("100", "Quarter ended 31-Dec-23")]["how"] == "line"
    assert by[("100", "Quarter ended 31-Dec-23")]["col_ok"] is True
    assert by[("200", "Nine months ended 31-Dec-23")]["verdict"] == "confirmed"
    assert by[("200", "Nine months ended 31-Dec-23")]["col_ok"] is True
    wrong = by[("180", "Quarter ended 31-Dec-23")]
    assert wrong["verdict"] == "reader_error_column"
    assert wrong["col_ok"] is False and not wrong["settled_by"]


def test_spanning_header_date_printed_over_both_groups_still_holds():
    words = _spanning_page()
    cells, _unread = rg.settle_page([[_cell("Revenue", "31-Dec-23", "100")]], words)
    assert cells[0]["verdict"] == "confirmed"


def test_three_line_wrapped_label_joins_the_value_line():
    words = [
        _w(200, 10, "Q2FY26"), _w(260, 10, "Q1FY26"),
        _w(10, 30, "Employee"), _w(10, 45, "benefit"), _w(10, 60, "expense"),
        _w(200, 75, "100"), _w(260, 75, "90"),
        _w(10, 90, "Revenue"), _w(200, 90, "50"), _w(260, 90, "40"),
    ]
    cells, _unread = rg.settle_page([[_cell("Employee benefit expense", "Q2FY26", "100")]], words)
    assert cells[0]["verdict"] == "confirmed"
    assert cells[0]["how"] == "wrap"
    assert cells[0]["row_label"] == "Employee benefit expense"


def test_wrapped_label_can_continue_on_one_line_below_the_numbers():
    words = [
        _w(200, 10, "Q2FY26"), _w(260, 10, "Q1FY26"),
        _w(10, 30, "Deferred"), _w(200, 30, "55"), _w(260, 30, "45"),
        _w(10, 45, "tax expense"), _w(200, 45, "60"), _w(260, 45, "50"),
    ]
    cells, _unread = rg.settle_page([[_cell("Deferred tax expense", "Q2FY26", "55")]], words)
    assert cells[0]["verdict"] == "confirmed"


def test_chart_panel_takes_the_title_above_and_the_axis_below():
    words = [
        _w(250, 10, "Revenue"),
        _w(300, 100, "5,448"),
        _w(280, 120, "Q1"), _w(293, 120, "FY26"), _w(380, 120, "Q2"), _w(393, 120, "FY26"),
    ]
    cells, _unread = rg.settle_page([[_cell("Revenue", "Q1 FY26", "5,448")]], words)
    assert cells[0]["verdict"] == "confirmed"
    assert cells[0]["how"] == "chart"


def test_verdicts_separate_a_reader_error_from_a_checker_miss_and_an_unplaced_cell():
    words = _results_page()
    # another reader puts 40 on the Profit line: "Exceptional items 40" is a reader error, not a checker miss
    pair, _unread = rg.settle_page([[_cell("Profit", "Q2FY26", "40")],
                                    [_cell("Exceptional items", "Q2FY26", "40")]], words)
    by = {(c["row_label"], c["value_text"]): c for c in pair}
    assert by[("Profit", "40")]["verdict"] == "confirmed"
    assert by[("Exceptional items", "40")]["verdict"] == "reader_error_row"
    # alone, the same cell could be right; nothing contradicts it -> checker miss
    alone, _unread = rg.settle_page([[_cell("Exceptional items", "Q2FY26", "40")]], words)
    assert alone[0]["verdict"] == "checker_miss"
    # not printed / unknown label -> unplaced
    missing, _unread = rg.settle_page([[_cell("Revenue", "Q2FY26", "999")]], words)
    assert missing[0]["verdict"] == "unplaced"
    unknown, _unread = rg.settle_page([[_cell("Nonexistent row", "Q2FY26", "100")]], words)
    assert unknown[0]["verdict"] == "unplaced"

