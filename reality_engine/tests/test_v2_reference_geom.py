import pytest
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


def test_equal_values_in_two_columns_of_one_row_keep_both_cells():
    """T-199: "Current ratio | 1.23 | ... | 1.23" prints the same figure twice; the second cell is placed on the
    next matching word of its own line, never merged into the first (12 of 18 recall misses on financial pages)."""
    band = [_w(200, 10, "31.03.2026"), _w(260, 10, "31.03.2025"),
            _w(10, 30, "Current ratio"), _w(200, 30, "1.23"), _w(260, 30, "1.23")]
    cells, _unread = rg.settle_page([[_cell("Current ratio", "31.03.2026", "1.23"),
                                      _cell("Current ratio", "31.03.2025", "1.23")]], band)
    assert sorted(c["col_header"] for c in cells) == ["31.03.2025", "31.03.2026"]
    assert all(c["verdict"] == "confirmed" for c in cells), [c["verdict"] for c in cells]
    # with no header band the columns cannot be confirmed, but both cells are still kept, each one unverified
    plain = [_w(10, 30, "Current ratio"), _w(200, 30, "1.23"), _w(260, 30, "1.23")]
    cells, _unread = rg.settle_page([[_cell("Current ratio", "As at 31.03.2026", "1.23"),
                                      _cell("Current ratio", "As at 31.03.2025", "1.23")]], plain)
    assert len(cells) == 2
    assert {c["col_header"] for c in cells} == {"As at 31.03.2026", "As at 31.03.2025"}
    assert all(c["value_text"] == "1.23" and not c["settled_by"] for c in cells)
    # only one word printed: the second column's claim stays a loose unverified cell, never merged into the first
    single = [_w(10, 30, "Current ratio"), _w(200, 30, "1.23")]
    cells, _unread = rg.settle_page([[_cell("Current ratio", "Q2FY26", "1.23"),
                                      _cell("Current ratio", "Q1FY26", "1.23")]], single)
    assert len(cells) == 2
    assert {c["col_header"] for c in cells} == {"Q1FY26", "Q2FY26"}


def test_every_settled_cell_key_is_written_to_the_reference_csv():
    """``run`` writes the cells with ``csv.DictWriter(COLS)``: a key COLS lacks would crash the reference run."""
    cells, _unread = rg.settle_page([[_cell("Revenue", "Q2FY26", "100")]], _results_page())
    assert set(cells[0]) <= set(rg.COLS), set(cells[0]) - set(rg.COLS)


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



# -- T-225 checker rebuild, round 1 ------------------------------------------------------------------------------

def test_indian_grouped_number_is_a_value_not_a_date():
    assert not rg._is_header_word("1,03,086")
    assert rg._is_header_word("31,03,2022") and rg._is_header_word("31.03.22")


def test_month_year_word_is_a_header():
    assert all(rg._is_header_word(t) for t in ("Dec22", "Mar-23", "March2023", "Dec'22"))
    assert not rg._is_header_word("Decor")


def _month_year_page():
    """f013 shape: 'Particulars Dec22 Mar23' header, an Indian-grouped first row, narrow numbers below."""
    return [
        _w(10, 10, "Particulars"), _w(200, 10, "Dec22"), _w(260, 10, "Mar23"),
        _w(10, 25, "Assets"), _w(190, 25, "1,03,086"), _w(250, 25, "1,12,075"),
        _w(10, 40, "Cash"), _w(205, 40, "5,054"), _w(265, 40, "2,961"),
    ]


def test_row_under_an_indian_grouped_row_keeps_its_column():
    cells, _ = rg.settle_page([[_cell("Cash", "Dec22", "5,054"), _cell("Cash", "Mar23", "2,961")]],
                              _month_year_page())
    assert {c["value_text"]: c["settled_by"] for c in cells} == {"5,054": "position", "2,961": "position"}


def test_wrapped_label_word_on_the_left_is_not_a_header():
    words = _results_page() + [_w(10, 90, "year"), _w(10, 105, "-"), _w(20, 105, "Owner"), _w(200, 105, "55"),
                               _w(260, 105, "44")]
    cells, _ = rg.settle_page([[_cell("Owner", "Q1FY26", "44")]], words)
    assert cells[0]["settled_by"] == "position"


def test_malformed_value_is_never_confirmed():
    assert rg.well_formed("1,23,456.78") and rg.well_formed("(0.45)") and rg.well_formed("12.5%")
    assert not any(rg.well_formed(v) for v in ("206,61", "4,7t186", "1.24.285.61", "7,O7,180,78"))
    words = _results_page() + [_w(10, 90, "Other"), _w(200, 90, "206,61")]
    cells, _ = rg.settle_page([[_cell("Other", "Q2FY26", "206,61")]], words)
    assert not cells[0]["settled_by"] and cells[0]["conflict"] == "malformed_value"


def test_garbled_layer_confirms_nothing():
    junk = ["18,527,91J", "6rn.18", "4,7t186", "1,301,.24", "1,,799.94"]
    words = _results_page() + [_w(10, 100 + 15 * k, f"Row{k}") for k in range(5)] \
        + [_w(200, 100 + 15 * k, t) for k, t in enumerate(junk)] \
        + [_w(260, 100 + 15 * k, f"{k + 1},234.56") for k in range(5)]
    assert not rg.layer_garbled(words)                 # 10 figure tokens: too few to judge
    many = words + [_w(10, 200 + 15 * k, f"Row{k}x") for k in range(12)]         + [_w(200, 200 + 15 * k, f"{k}6rn.1{k}") for k in range(12)]
    assert rg.layer_garbled(many)
    assert not rg.layer_garbled(_results_page())
    assert rg.well_formed("₹2.40crore") and rg.well_formed("(₹0.00crore).") and not rg.well_formed("₹2.4Ocrore")
    words = many
    cells, _ = rg.settle_page([[_cell("Revenue", "Q2FY26", "100")]], words)
    assert not cells[0]["settled_by"] and cells[0]["conflict"] == "garbled_layer"


def test_reader_header_with_an_unprinted_number_is_not_confirmed():
    cells, _ = rg.settle_page([[_cell("Profit", "Q2FY26 Mat 37", "40")]], _results_page())
    assert not cells[0]["settled_by"]


def test_word_headers_place_a_column_without_period_words():
    """p008 shape: 'No. of shares | Amount' over two number columns, no period word anywhere."""
    words = [
        _w(200, 10, "No."), _w(220, 10, "of"), _w(235, 10, "shares"), _w(300, 10, "Amount"),
        _w(10, 25, "Opening"), _w(200, 25, "97,18,084"), _w(300, 25, "97.18"),
        _w(10, 40, "Closing"), _w(200, 40, "95,91,514"), _w(300, 40, "95.91"),
    ]
    cells, _ = rg.settle_page([[_cell("Closing", "Equity > Amount", "95.91"),
                                _cell("Opening", "Equity > Amount", "97,18,084")]], words)
    by = {c["value_text"]: c for c in cells}
    assert by["95.91"]["settled_by"] == "position"
    assert not by["97,18,084"]["settled_by"] and by["97,18,084"]["conflict"] == "column_elsewhere"


def test_ocr_second_look_confirms_a_value_the_layer_misprints():
    layer = _results_page() + [_w(10, 90, "Tax2"), _w(200, 90, "(359,72)")]
    ocr = _results_page() + [_w(10, 90, "Tax2"), _w(200, 90, "(359.72)")]
    cells, _ = rg.settle_page([[_cell("Tax2", "Q2FY26", "(359.72)")]], layer)
    assert not cells[0]["settled_by"]
    cells, _ = rg.settle_page([[_cell("Tax2", "Q2FY26", "(359.72)")]], layer, alt_words=ocr)
    assert cells[0]["settled_by"] == "position" and cells[0]["how"] == "ocr"
    cells, _ = rg.settle_page([[_cell("Tax2", "Q1FY26", "(359.72)")]], layer, alt_words=ocr)
    assert not cells[0]["settled_by"]                     # OCR places it under Q2FY26, not Q1FY26


# -- T-225 round 2: the independent review's failing inputs (agy 20261118T155709Z-739f82b1) ------------------

def _conf(cells, value):
    return next(c for c in cells if c["value_text"] == value)["settled_by"]


def test_unprinted_number_in_reader_header_blocks_the_word_fallback():
    words = [_w(200, 10, "31-Dec-23"), _w(300, 10, "31-Dec-22"),
             _w(200, 25, "Shares"), _w(300, 25, "Amount"),
             _w(10, 40, "Equity"), _w(205, 40, "100"), _w(305, 40, "50"),
             _w(10, 55, "Other"), _w(205, 55, "200"), _w(305, 55, "60")]
    cells, _ = rg.settle_page([[_cell("Equity", "31-Dec-21 > Shares", "100")]], words)
    assert not _conf(cells, "100")


def test_word_header_blank_rival_and_single_letter_columns():
    words = [_w(200, 10, "India"), _w(300, 10, "Export"), _w(200, 25, "Gross"), _w(300, 25, "Gross"),
             _w(10, 40, "Sales"), _w(205, 40, "100"), _w(305, 40, "-"),
             _w(10, 55, "Other"), _w(205, 55, "20"), _w(305, 55, "30")]
    cells, _ = rg.settle_page([[_cell("Sales", "Export > Gross", "100")]], words)
    assert not _conf(cells, "100")
    words = [_w(200, 10, "Segment"), _w(240, 10, "A"), _w(300, 10, "Segment"), _w(340, 10, "B"),
             _w(10, 25, "Revenue"), _w(205, 25, "100"), _w(305, 25, "150"),
             _w(10, 40, "Cost"), _w(205, 40, "60"), _w(305, 40, "70")]
    cells, _ = rg.settle_page([[_cell("Revenue", "Segment B", "100"), _cell("Revenue", "Segment B", "150")]], words)
    assert not _conf(cells, "100") and _conf(cells, "150") == "position"


def test_word_header_does_not_bleed_into_the_next_column():
    words = [_w(200, 10, "No."), _w(215, 10, "of"), _w(228, 10, "shares"), _w(262, 10, "Amount"),
             _w(10, 25, "Opening"), _w(200, 25, "1,000"), _w(270, 25, "10"),
             _w(10, 40, "Bonus"), _w(210, 40, "-"), _w(270, 40, "12")]
    cells, _ = rg.settle_page([[_cell("Bonus", "No. of shares", "12")]], words)
    assert not _conf(cells, "12")


def test_month_year_headers_form_a_band_with_groups():
    words = [_w(200, 10, "Consolidated"), _w(400, 10, "Standalone"),
             _w(180, 25, "Mar'23"), _w(260, 25, "Dec22"), _w(380, 25, "Mar'23"), _w(460, 25, "Dec22"),
             _w(10, 40, "Revenue"), _w(185, 40, "100"), _w(265, 40, "90"), _w(385, 40, "50"), _w(465, 40, "40"),
             _w(10, 55, "Cost"), _w(185, 55, "60"), _w(265, 55, "55"), _w(385, 55, "30"), _w(465, 55, "25")]
    cells, _ = rg.settle_page([[_cell("Revenue", "Consolidated > Mar'23", "50"),
                                _cell("Revenue", "Standalone > Mar'23", "50")]], words)
    assert all(c["settled_by"] != "position" or c["col_header"].startswith("Standalone") for c in cells)


def test_well_formed_accepts_printed_variants():
    for v in ("(12.9%)", "(12.5x)", "—0.45", "−0.45", "(-0.45)", "12.5X", "-₹1,234", "(€1,234)", "Rs.1,234",
              "2.40crore*", "1,234‡", "1,234^", "{24,300)"):
        assert rg.well_formed(v), v
    assert not rg._figure_token("2.1.1") and not rg._figure_token("2022.01.31")
    assert rg._figure_token("l,234.56")
    assert not rg._is_header_word("45,67,89")


# -- T-225 round 3: review round 2's failing inputs (agy 20261118T161741Z-92d10f2d) ----------------------------

def test_group_split_does_not_snap_to_a_far_period_kind_change():
    words = [_w(200, 10, "Consolidated"), _w(400, 10, "Standalone"),
             _w(180, 25, "FY24"), _w(260, 25, "Q4FY24"), _w(380, 25, "Q3FY24"), _w(460, 25, "FY23"),
             _w(10, 40, "Revenue"), _w(185, 40, "100"), _w(265, 40, "25"), _w(385, 40, "30"), _w(465, 40, "90"),
             _w(10, 55, "Cost"), _w(185, 55, "60"), _w(265, 55, "15"), _w(385, 55, "20"), _w(465, 55, "55")]
    cells, _ = rg.settle_page([[_cell("Revenue", "Standalone > Q4FY24", "25")]], words)
    assert not _conf(cells, "25")


def test_group_beyond_the_word_header_gap_blocks_the_word_fallback():
    words = [_w(190, 10, "Quarter"), _w(230, 10, "ended"), _w(340, 10, "Nine"), _w(365, 10, "months"),
             _w(190, 44, "31-Dec-23"), _w(340, 44, "31-Dec-23"),
             _w(190, 56, "Shares"), _w(340, 56, "Amount"),
             _w(10, 72, "Equity"), _w(195, 72, "100"), _w(345, 72, "50"),
             _w(10, 86, "Other"), _w(195, 86, "200"), _w(345, 86, "60")]
    cells, _ = rg.settle_page([[_cell("Equity", "Nine months > 31-Dec-23 > Shares", "100")]], words)
    assert not _conf(cells, "100")


def test_year_first_headers_keep_their_years():
    words = [_w(180, 10, "2024"), _w(205, 10, "Q1"), _w(225, 10, "2023"), _w(250, 10, "Q1"),
             _w(10, 25, "Revenue"), _w(205, 25, "100"), _w(250, 25, "80"),
             _w(10, 40, "Cost"), _w(205, 40, "60"), _w(250, 40, "50")]
    cells, _ = rg.settle_page([[_cell("Revenue", "2023 Q1", "100")]], words)
    assert not _conf(cells, "100")


def test_spanning_word_header_and_section_break_confirm_nothing_wrong():
    words = [_w(220, 10, "Total"), _w(190, 25, "Direct"), _w(260, 25, "Amount"),
             _w(10, 40, "Sales"), _w(195, 40, "100"), _w(265, 40, "200"),
             _w(10, 55, "Cost"), _w(195, 55, "60"), _w(265, 55, "120")]
    cells, _ = rg.settle_page([[_cell("Sales", "Total", "100")]], words)
    assert not _conf(cells, "100")
    words = [_w(200, 10, "Shares"), _w(280, 10, "Amount"),
             _w(10, 25, "Row1"), _w(205, 25, "100"), _w(285, 25, "10"),
             _w(10, 40, "Section"), _w(50, 40, "one"),
             _w(10, 55, "Additional"), _w(200, 55, "Amount"),
             _w(10, 70, "Row2"), _w(205, 70, "200"), _w(285, 70, "20")]
    cells, _ = rg.settle_page([[_cell("Row2", "Amount", "200")]], words)
    assert not _conf(cells, "200")


def test_tight_word_headers_do_not_merge():
    words = [_w(200, 10, "No.", cw=5), _w(218, 10, "of", cw=5), _w(230, 10, "shares", cw=5), _w(262, 10, "Amount", cw=5),
             _w(10, 25, "Opening"), _w(205, 25, "1,000"), _w(275, 25, "15"),
             _w(10, 40, "Bonus"), _w(215, 40, "-"), _w(275, 40, "10")]
    cells, _ = rg.settle_page([[_cell("Bonus", "No. of shares", "10")]], words)
    assert not _conf(cells, "10")


def test_one_number_line_and_dash_columns_keep_their_band():
    words = [_w(10, 10, "Particulars"), _w(200, 10, "FY25"), _w(260, 10, "FY24"),
             _w(10, 25, "A"), _w(200, 25, "100"), _w(265, 25, "-"),
             _w(10, 40, "B"), _w(200, 40, "60"), _w(265, 40, "-"),
             _w(10, 55, "C"), _w(205, 55, "10"), _w(265, 55, "5")]
    p = rg.Page(words)
    assert len(p.columns_for(p.line_of[len(words) - 1])) == 2
    assert not rg._is_header_word("12,03,22") and rg._is_header_word("31,03,2022")


# -- T-225 round 4: review round 3's failing inputs (agy 20261118T162632Z-d592e3d2) ----------------------------

def test_group_snap_uses_the_local_gap():
    words = [_w(170, 10, "Consolidated"), _w(325, 10, "Standalone"),
             _w(180, 25, "FY24"), _w(260, 25, "Q4FY24"), _w(340, 25, "Q3FY24"), _w(490, 25, "FY23"),
             _w(10, 40, "Revenue"), _w(185, 40, "100"), _w(265, 40, "25"), _w(345, 40, "30"), _w(495, 40, "90"),
             _w(10, 55, "Cost"), _w(185, 55, "60"), _w(265, 55, "15"), _w(345, 55, "20"), _w(495, 55, "55")]
    cells, _ = rg.settle_page([[_cell("Revenue", "Standalone > Q4FY24", "25")]], words)
    assert not _conf(cells, "25")


def test_day_number_is_not_a_year_part():
    words = [_w(160, 10, "9M"), _w(173, 10, "ended"), _w(200, 10, "31"), _w(213, 10, "Mar"), _w(232, 10, "2024"),
             _w(270, 10, "9M"), _w(283, 10, "ended"), _w(310, 10, "31"), _w(323, 10, "Mar"), _w(342, 10, "2023"),
             _w(10, 25, "Revenue"), _w(190, 25, "100"), _w(300, 25, "80"),
             _w(10, 40, "Cost"), _w(190, 40, "60"), _w(300, 40, "50")]
    cells, _ = rg.settle_page([[_cell("Revenue", "9M ended 31 Mar 2023", "100")]], words)
    assert not _conf(cells, "100")
    assert not rg._is_year_part("31") and rg._is_year_part("FY24") and rg._is_year_part("2024")


def test_shifted_sibling_group_heads_no_column():
    words = [_w(185, 10, "Standalone"), _w(240, 10, "Consolidated"),
             _w(190, 25, "Shares"), _w(300, 25, "Amount"), _w(370, 25, "Total"),
             _w(10, 40, "Equity"), _w(195, 40, "100"), _w(305, 40, "50"), _w(375, 40, "150"),
             _w(10, 55, "Reserve"), _w(195, 55, "200"), _w(305, 55, "60"), _w(375, 55, "260")]
    cells, _ = rg.settle_page([[_cell("Equity", "Consolidated > Shares", "100")]], words)
    assert not _conf(cells, "100")
    words = [_w(175, 10, "Standalone"), _w(225, 10, "Consolidated"),
             _w(190, 22, "31-Dec-23"), _w(290, 22, "31-Dec-23"),
             _w(190, 34, "Shares"), _w(290, 34, "Amount"),
             _w(10, 50, "Equity"), _w(195, 50, "100"), _w(295, 50, "50"),
             _w(10, 65, "Reserve"), _w(195, 65, "200"), _w(295, 65, "60")]
    cells, _ = rg.settle_page([[_cell("Equity", "Consolidated > 31-Dec-23 > Shares", "100")]], words)
    assert not _conf(cells, "100")


def test_column_does_not_climb_into_the_table_above():
    words = [_w(200, 10, "Amount"), _w(280, 10, "Shares"),
             _w(10, 25, "OldRow"), _w(205, 25, "99"), _w(285, 25, "9"),
             _w(10, 40, "Note"), _w(35, 40, "text"),
             _w(10, 55, "More"), _w(35, 55, "text"),
             _w(200, 70, "Shares"), _w(280, 70, "Amount"),
             _w(10, 85, "NewRow"), _w(205, 85, "200"), _w(285, 85, "20")]
    cells, _ = rg.settle_page([[_cell("NewRow", "Amount", "200")]], words)
    assert not _conf(cells, "200")


def test_wide_empty_mark_does_not_bridge_columns():
    words = [_w(10, 10, "Particulars"), _w(200, 10, "FY25"), _w(232, 10, "FY24"),
             _w(10, 25, "Row1"), _w(200, 25, "100"), _w(232, 25, "90"),
             _w(10, 40, "Row2"), _w(200, 40, "100"), _w(218, 40, "n.a."),
             _w(10, 55, "Row3"), _w(200, 55, "50"), _w(232, 55, "40")]
    cells, _ = rg.settle_page([[_cell("Row1", "FY24", "100")]], words)
    assert not _conf(cells, "100")


# -- T-225 round 5: review round 4's inputs (agy 20261118T163526Z-72b4b21b) ------------------------------------

def test_section_heading_never_wraps_onto_a_labelled_row():
    """p023 shape: a reader copies the section heading onto each row; the row's own line names a city."""
    words = [_w(200, 10, "Total"), _w(230, 10, "Beds"),
             _w(10, 25, "Expected"), _w(60, 25, "commissioning"), _w(135, 25, ":"), _w(140, 25, "FY27"),
             _w(10, 38, "Gurgaon,"), _w(55, 38, "NCR"), _w(205, 38, "480"),
             _w(10, 52, "Lucknow"), _w(205, 52, "520")]
    cells, _ = rg.settle_page([[_cell("Expected commissioning : FY27", "Total Beds", "480")]], words)
    assert not _conf(cells, "480")


def test_round4_layouts_confirm_nothing_wrong():
    cases = [
        ([_w(195, 10, "Consolidated"), _w(355, 10, "Standalone"),
          _w(180, 25, "Q4FY24"), _w(260, 25, "Q3FY24"), _w(340, 25, "Q4FY23"), _w(420, 25, "FY24"),
          _w(10, 40, "Revenue"), _w(185, 40, "100"), _w(265, 40, "90"), _w(345, 40, "80"), _w(425, 40, "300"),
          _w(10, 55, "Cost"), _w(185, 55, "60"), _w(265, 55, "55"), _w(345, 55, "50"), _w(425, 55, "180")],
         _cell("Revenue", "Consolidated > Q4FY23", "80"), "80"),
        ([_w(200, 10, "Amount"), _w(280, 10, "Shares"),
          _w(10, 25, "OldRow"), _w(205, 25, "99"), _w(285, 25, "9"),
          _w(10, 40, "Particulars"), _w(200, 40, "Shares"), _w(280, 40, "Amount"),
          _w(10, 55, "Bonus"), _w(205, 55, "-"), _w(285, 55, "10"),
          _w(10, 70, "Closing"), _w(205, 70, "100"), _w(285, 70, "20")],
         _cell("Bonus", "Shares", "10"), "10"),
        ([_w(170, 10, "Q1"), _w(185, 10, "2024"), _w(210, 10, "(3M)"),
          _w(260, 10, "Q2"), _w(275, 10, "2024"), _w(300, 10, "(3M)"),
          _w(10, 25, "Revenue"), _w(210, 25, "100"), _w(300, 25, "120"),
          _w(10, 40, "Cost"), _w(210, 40, "60"), _w(300, 40, "70")],
         _cell("Revenue", "Q2 2024 (3M)", "100"), "100"),
        ([_w(185, 10, "Standalone"), _w(335, 10, "Consolidated"),
          _w(190, 25, "Shares"), _w(290, 25, "Amount"), _w(395, 25, "Total"),
          _w(10, 40, "Equity"), _w(195, 40, "100"), _w(295, 40, "50"), _w(400, 40, "150"),
          _w(10, 55, "Reserve"), _w(195, 55, "200"), _w(295, 55, "60"), _w(400, 55, "260")],
         _cell("Equity", "Consolidated > Amount", "50"), "50"),
        ([_w(100, 10, "Consolidated"), _w(290, 10, "Standalone"),
          _w(190, 25, "Shares"), _w(295, 25, "Amount"),
          _w(10, 40, "Equity"), _w(195, 40, "100"), _w(300, 40, "50"),
          _w(10, 55, "Reserve"), _w(195, 55, "200"), _w(300, 55, "60")],
         _cell("Equity", "Consolidated > Amount", "50"), "50"),
    ]
    for words, cell, value in cases:
        cells, _ = rg.settle_page([[cell]], words)
        assert not _conf(cells, value), cell


def test_page_title_date_never_heads_a_column():
    """c09 GAYAPROJ Q2FY27 results (real page): the title "... ENDED 30th SEPTEMBER, 2026" sat in the header band
    over the 30.09.2025 comparative column, so a reader's "30.09.2026" for the 2025 figure was confirmed."""
    words = [_w(120, 5, "STATEMENT"), _w(175, 5, "OF"), _w(190, 5, "CONSOLIDATED"), _w(255, 5, "RESULTS"),
             _w(300, 5, "FOR"), _w(320, 5, "QUARTER"), _w(365, 5, "ENDED"), _w(400, 5, "30th"),
             _w(425, 5, "SEPTEMBER,"), _w(480, 5, "2026"),
             _w(200, 20, "Quarter"), _w(240, 20, "Ended"),
             _w(200, 32, "30.09.2026"), _w(300, 32, "30.06.2026"), _w(400, 32, "30.09.2025"),
             _w(10, 47, "Total"), _w(40, 47, "Income"), _w(205, 47, "12,162.59"), _w(305, 47, "25,403.37"),
             _w(405, 47, "8,262.96"),
             _w(10, 62, "Expenses"), _w(205, 62, "11,000.00"), _w(305, 62, "20,000.00"), _w(405, 62, "7,000.00")]
    assert rg.Page(words).title_line(0)
    wrong, _ = rg.settle_page([[_cell("Total Income", "Quarter Ended > 30.09.2026", "8,262.96")]], words)
    right, _ = rg.settle_page([[_cell("Total Income", "Quarter Ended > 30.09.2025", "8,262.96")]], words)
    assert not _conf(wrong, "8,262.96")
    assert _conf(right, "8,262.96") == "position"


def test_group_rows_are_not_titles():
    """Review round 6: a group row split into phrases must stay in the band (it tells repeated dates apart)."""
    for left, right in (("For the quarter ended", "For the year ended"), ("Standalone Results", "Consolidated Results"),
                        ("Segment Revenue", "Segment Results")):
        words = []
        x = 180
        for t in left.split():
            words.append(_w(x, 10, t)); x += 5 * len(t) + 5
        x = 380
        for t in right.split():
            words.append(_w(x, 10, t)); x += 5 * len(t) + 5
        words += [_w(180, 25, "31.03.2025"), _w(260, 25, "31.03.2024"), _w(380, 25, "31.03.2025"), _w(460, 25, "31.03.2024"),
                  _w(10, 40, "Revenue"), _w(185, 40, "100"), _w(265, 40, "90"), _w(385, 40, "400"), _w(465, 40, "350"),
                  _w(10, 55, "Cost"), _w(185, 55, "60"), _w(265, 55, "50"), _w(385, 55, "200"), _w(465, 55, "150")]
        assert not rg.Page(words).title_line(0), left
        cells, _ = rg.settle_page([[_cell("Revenue", f"{right} > 31.03.2025", "100")]], words)
        assert not _conf(cells, "100"), right


def test_merged_column_headers_and_serial_columns_are_not_titles():
    """p057 / p003 (real pages): "SI. Particulars Quarter Quarter Nine Month Year ended" and two "For the year ended
    ..." headers run together are column headers, never a title."""
    words = [_w(10, 10, "SI."), _w(30, 10, "Particulars"), _w(200, 10, "Quarter"), _w(240, 10, "Quarter"),
             _w(280, 10, "Nine"), _w(302, 10, "Month"), _w(332, 10, "Year"), _w(355, 10, "ended"),
             _w(10, 25, "Revenue"), _w(205, 25, "10"), _w(245, 25, "12"), _w(285, 25, "30"), _w(335, 25, "40")]
    assert not rg.Page(words).title_line(0)
    words = [_w(150, 10, "For"), _w(168, 10, "the"), _w(186, 10, "year"), _w(209, 10, "ended"), _w(237, 10, "31"),
             _w(250, 10, "March"), _w(278, 10, "2024"), _w(301, 10, "For"), _w(319, 10, "the"), _w(337, 10, "year"),
             _w(360, 10, "ended"), _w(388, 10, "31"), _w(401, 10, "March"), _w(429, 10, "2023"),
             _w(10, 25, "Revenue"), _w(205, 25, "10"), _w(380, 25, "12")]
    assert not rg.Page(words).title_line(0)


def test_round7_title_shapes():
    """Review round 7 (agy 20261118T174950Z-f3c64eb4): a two-"ENDED" title sentence is still a title; a right-hand
    Unit column and a repeated "Financial Results" group row do not make a title."""
    W = lambda x0, y0, x1, y1, t: (x0, y0, x1, y1, t)   # noqa: E731
    title = [W(20, 10, 70, 18, "STATEMENT"), W(75, 10, 85, 18, "OF"), W(90, 10, 125, 18, "RESULTS"),
             W(135, 10, 150, 18, "FOR"), W(160, 10, 175, 18, "THE"), W(185, 10, 220, 18, "QUARTER"),
             W(228, 10, 253, 18, "ENDED"), W(265, 10, 315, 18, "30.09.2026"), W(325, 10, 340, 18, "AND"),
             W(350, 10, 370, 18, "YEAR"), W(378, 10, 403, 18, "ENDED"), W(415, 10, 465, 18, "31.03.2026"),
             W(220, 25, 255, 33, "Quarter"), W(262, 25, 287, 33, "Ended"),
             W(370, 25, 405, 33, "Quarter"), W(412, 25, 437, 33, "Ended"),
             W(225, 38, 275, 46, "30.09.2025"), W(375, 38, 425, 46, "30.09.2024"),
             W(10, 55, 70, 63, "Total Income"), W(230, 55, 270, 63, "8,262.96"), W(380, 55, 420, 63, "7,500.00"),
             W(10, 70, 80, 78, "Total Expenses"), W(230, 70, 270, 78, "7,000.00"), W(380, 70, 420, 78, "6,400.00")]
    cells, _ = rg.settle_page([[_cell("Total Income", "Quarter Ended > 30.09.2026", "8,262.96")]], title)
    assert not _conf(cells, "8,262.96")
    unit = [W(180, 10, 210, 18, "Before"), W(218, 10, 273, 18, "exceptional"), W(280, 10, 305, 18, "items"),
            W(312, 10, 327, 18, "and"), W(335, 10, 350, 18, "tax"), W(400, 10, 425, 18, "After"), W(432, 10, 447, 18, "tax"),
            W(180, 25, 230, 33, "31.03.2025"), W(300, 25, 350, 33, "31.03.2025"), W(420, 25, 440, 33, "Unit"),
            W(10, 40, 40, 48, "Profit"), W(185, 40, 200, 48, "100"), W(305, 40, 315, 48, "75"), W(420, 40, 445, 48, "Lakhs"),
            W(10, 55, 30, 63, "Loss"), W(185, 55, 195, 63, "10"), W(305, 55, 310, 63, "7"), W(420, 55, 445, 63, "Lakhs")]
    # KNOWN GAP (review r7 4.2): a group header over a non-figure "Unit" column heads no column, so a reader's
    # "After tax" is ignored and the date alone confirms. Refusing printed-but-unheaded words cost 72 right cells on the
    # 60 dev reference pages, so it is documented, not fixed.
    assert not rg.Page(unit).title_line(1)
    group = [W(180, 10, 230, 18, "Standalone"), W(236, 10, 281, 18, "Financial"), W(286, 10, 321, 18, "Results"),
             W(332, 10, 392, 18, "Consolidated"), W(398, 10, 443, 18, "Financial"), W(448, 10, 483, 18, "Results"),
             W(180, 25, 230, 33, "31.03.2025"), W(260, 25, 310, 33, "31.03.2024"),
             W(340, 25, 390, 33, "31.03.2025"), W(420, 25, 470, 33, "31.03.2024"),
             W(10, 40, 45, 48, "Revenue"), W(185, 40, 200, 48, "100"), W(265, 40, 275, 48, "90"), W(345, 40, 360, 48, "400"),
             W(425, 40, 440, 48, "350"),
             W(10, 55, 30, 63, "Cost"), W(185, 55, 195, 63, "60"), W(265, 55, 275, 63, "55"), W(345, 55, 360, 63, "240"),
             W(425, 55, 440, 63, "210")]
    cells, _ = rg.settle_page([[_cell("Revenue", "Consolidated Financial Results > 31.03.2025", "100")]], group)
    assert not _conf(cells, "100")


# -- T-225 round 9: dsh review round 8 (20261118T181459Z-0d7360da) - captions shared over columns -----------------

def _results_four():
    W = lambda x0, y0, x1, y1, t: (x0, y0, x1, y1, t)   # noqa: E731
    return [W(300, 90, 335, 98, "Quarter"), W(370, 90, 405, 98, "Quarter"), W(440, 90, 475, 98, "Quarter"),
            W(510, 90, 545, 98, "Year"),
            W(300, 102, 330, 110, "Ended"), W(370, 102, 400, 110, "Ended"), W(440, 102, 470, 110, "Ended"),
            W(510, 102, 540, 110, "Ended"),
            W(290, 116, 340, 124, "30.09.2026"), W(360, 116, 410, 124, "30.06.2026"), W(430, 116, 480, 124, "30.09.2025"),
            W(500, 116, 550, 124, "31.03.2026"),
            W(10, 140, 70, 148, "Total"), W(75, 140, 110, 148, "Income"), W(300, 140, 340, 148, "12,162.59"),
            W(370, 140, 410, 148, "25,403.37"), W(440, 140, 480, 148, "8,262.96"), W(510, 140, 550, 148, "98,483.90"),
            W(10, 154, 70, 162, "Total"), W(75, 154, 120, 162, "Expenses"), W(300, 154, 340, 162, "11,000.00"),
            W(370, 154, 410, 162, "20,000.00"), W(440, 154, 480, 162, "7,000.00"), W(510, 154, 550, 162, "80,000.00")]


@pytest.mark.xfail(strict=True, reason="T-225 open: a caption phrase shared over several columns adds its period to every column stack (dsh review r8 4.1-4.3); needs the column-model rework")
def test_shared_caption_period_never_confirms_another_column():
    W = lambda x0, y0, x1, y1, t: (x0, y0, x1, y1, t)   # noqa: E731
    caption = [W(340, 76, 358, 84, "Half"), W(361, 76, 380, 84, "Year"), W(382, 76, 405, 84, "Ended"),
               W(408, 76, 454, 84, "30.09.2026")]
    cells, _ = rg.settle_page([[_cell("Total Income", "Quarter Ended > 30.09.2026", "8,262.96")]],
                              caption + _results_four())
    assert not _conf(cells, "8,262.96")
    cells, _ = rg.settle_page([[_cell("Total Income", "Quarter Ended > 30.09.2025", "8,262.96")]],
                              caption + _results_four())
    assert _conf(cells, "8,262.96") == "position"


@pytest.mark.xfail(strict=True, reason="T-225 open: a caption phrase shared over several columns adds its period to every column stack (dsh review r8 4.1-4.3); needs the column-model rework")
def test_short_deck_title_period_never_confirms_another_column():
    W = lambda x0, y0, x1, y1, t: (x0, y0, x1, y1, t)   # noqa: E731
    words = [W(250, 46, 259, 54, "Q2"), W(262, 46, 280, 54, "FY27"), W(283, 46, 329, 54, "Highlights"),
             W(10, 62, 60, 70, "Particulars"), W(220, 62, 240, 70, "Q2"), W(243, 62, 265, 70, "FY26"),
             W(300, 62, 320, 70, "Q2"), W(323, 62, 345, 70, "FY27"), W(380, 62, 400, 70, "YoY"),
             W(10, 80, 50, 88, "Revenue"), W(220, 80, 265, 88, "4,521.30"), W(300, 80, 345, 88, "5,102.10"),
             W(380, 80, 400, 88, "13%"),
             W(10, 94, 50, 102, "EBITDA"), W(220, 94, 260, 102, "900.10"), W(300, 94, 340, 102, "1,020.50"),
             W(380, 94, 400, 102, "13%")]
    cells, _ = rg.settle_page([[_cell("Revenue", "Q2 FY27", "4,521.30")]], words)
    assert not _conf(cells, "4,521.30")


@pytest.mark.xfail(strict=True, reason="T-225 open: repeated-word split cuts by nearest column, one word late on shifted headers (dsh review r8 4.4); cutting at the repeat cost 21 right cells on the dev reference pages")
def test_repeated_word_split_lands_on_the_second_header():
    words = [_w(209, 86, "Standalone", cw=4.6), _w(258, 86, "Financial", cw=4.6), _w(302, 86, "Results", cw=4.6),
             _w(337, 86, "Consolidated", cw=4.6), _w(396, 86, "Financial", cw=4.6), _w(440, 86, "Results", cw=4.6)]
    p = rg.Page(words + [_w(10, 110, "Revenue"), _w(270, 110, "100"), _w(440, 110, "400"),
                         _w(10, 125, "Cost"), _w(270, 125, "60"), _w(440, 125, "200")])
    texts = [ph[2] for ph in p._header_phrases(0, [{"x0": 270, "x1": 292}, {"x0": 440, "x1": 462}])]
    assert texts == ["Standalone Financial Results", "Consolidated Financial Results"], texts


def test_word_value_and_is_num_are_memoised():
    """T-241: the route asks these for every word on every page; the answer depends on the text only."""
    rg.word_value.cache_clear()
    rg._is_num.cache_clear()
    assert rg.word_value("(1,234)") == "-1234"
    assert rg._is_num("(1,234)") is True
    for _ in range(3):
        assert rg.word_value("(1,234)") == "-1234"
        assert rg._is_num("(1,234)") is True
    assert rg.word_value.cache_info().hits >= 1
    assert rg._is_num.cache_info().hits >= 1
