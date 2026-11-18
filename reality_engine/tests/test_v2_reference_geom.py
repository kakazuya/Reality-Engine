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
