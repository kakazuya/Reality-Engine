import datetime as dt

from reality_engine.v2 import script_reader as sr


def _w(x0, y0, text, cw=5.0, h=8.0):
    return (x0, y0, x0 + cw * len(text), y0 + h, text)


def _page():
    return [
        _w(10, 2, "STATEMENT"), _w(70, 2, "OF"), _w(90, 2, "CONSOLIDATED"), _w(160, 2, "RESULTS"),
        _w(200, 20, "Quarter"), _w(240, 20, "Ended"), _w(300, 20, "Quarter"), _w(340, 20, "Ended"),
        _w(200, 30, "30.09.2025"), _w(300, 30, "30.09.2024"),
        _w(10, 50, "Revenue"), _w(50, 50, "from"), _w(75, 50, "operations"), _w(200, 50, "1,200.50"),
        _w(300, 50, "1,100.25"),
        _w(10, 62, "Other"), _w(40, 62, "income"), _w(200, 62, "45.10"), _w(300, 62, "40.00"),
        _w(10, 74, "Total"), _w(40, 74, "income"), _w(200, 74, "1,245.60"), _w(300, 74, "1,140.25"),
    ]


def test_good_label_refuses_debris_and_continuations():
    assert sr.good_label("Revenue from operations")
    assert sr.good_label("(a) Cost of materials consumed")
    for bad in ("AAGA&A", "GA &", "[i)", "for the period (7-8)", "", "123"):
        assert not sr.good_label(bad), bad


def test_read_page_labels_and_columns_with_no_model():
    cells = {(c["row_label"], c["value"]): c["col_header"] for c in sr.read_page(_page())}
    assert "30.09.2025" in cells[("Revenue from operations", "1,200.50")]
    assert "30.09.2024" in cells[("Revenue from operations", "1,100.25")]
    assert "30.09.2024" not in cells[("Other income", "45.10")]


def test_settled_cells_carry_period_kind_and_basis():
    got = {(c["row_label"], c["value_text"]): c for c in sr.settled(_page())}
    c = got[("Total income", "1,140.25")]
    assert (c["period_end"], c["kind"], c["basis"]) == ("2024-09-30", "quarter", "consolidated")


def _cell(doc, value, pend="2024-09-30", label="Revenue from operations"):
    return {"doc_key": doc, "row_label": label, "value_text": value, "basis": "consolidated",
            "period_end": pend, "kind": "quarter"}


FILED = {"q2fy25": dt.date(2024, 11, 10), "q2fy26": dt.date(2025, 11, 12), "q2fy26_bse": dt.date(2025, 11, 12),
         "q3fy25": dt.date(2025, 2, 10)}


def test_cross_gate_passes_two_filings_apart_that_agree():
    cells = sr.cross_gate([_cell("q2fy25", "1,100.25"), _cell("q2fy26", "1100.25")], FILED)
    assert {c["gate"] for c in cells} == {"pass"}


def test_cross_gate_same_results_filed_twice_is_not_a_second_witness():
    cells = sr.cross_gate([_cell("q2fy26", "1,100.25"), _cell("q2fy26_bse", "1,100.25")], FILED)
    assert {c["gate"] for c in cells} == {"single_filing"}


def test_cross_gate_misread_column_conflicts_instead_of_passing():
    # the Q2FY26 page's current-quarter figure misread under the year-ago date meets the true year-ago figure
    cells = sr.cross_gate([_cell("q2fy25", "1,100.25"), _cell("q2fy26", "1,200.50")], FILED)
    assert {c["gate"] for c in cells} == {"conflict"}


def test_cross_gate_needs_a_period():
    c = _cell("q2fy25", "5")
    c["kind"] = "unprinted"
    assert sr.cross_gate([c], FILED)[0]["gate"] == "no_period"


def test_label_key_drops_list_marks():
    assert sr.label_key("(a) Revenue from operations") == sr.label_key("Revenue from Operations")
    assert sr.label_key("IV. Total income") == "total income"


def test_per_share_line_without_decimal_is_refused():
    c = _cell("q2fy25", "154", label="Basic (Rs)")
    d = _cell("q2fy26", "154", label="Basic (Rs)")
    assert {x["gate"] for x in sr.cross_gate([c, d], FILED)} == {"per_share_no_decimal"}
    assert sr.per_share_ok("Diluted", "1.54") and sr.per_share_ok("Revenue", "154")


class _Xbrl:
    pass


def test_xbrl_disagreement_refuses_the_whole_key(monkeypatch):
    from reality_engine.v2 import cell_judge as cj

    monkeypatch.setattr(cj, "judge", lambda cell, x: cj.Verdict("disagree" if cell["value_text"] == "(691)" else "agree"))
    bad = sr.cross_gate([_cell("q2fy25", "(691)", label="Profit / (Loss) Before Tax"),
                         _cell("q2fy26", "(691)", label="Profit / (Loss) Before Tax")], FILED, xbrl=_Xbrl())
    assert {x["gate"] for x in bad} == {"xbrl_disagrees"}
    good = sr.cross_gate([_cell("q2fy25", "1,100.25"), _cell("q2fy26", "1,100.25")], FILED, xbrl=_Xbrl())
    assert {x["gate"] for x in good} == {"pass"}


def test_identifiers_and_split_signs_are_not_figures():
    assert not sr.figure_ok("07027180)")
    assert not sr.figure_ok("00005573")
    assert not sr.figure_ok("19.59)")
    assert sr.figure_ok("(19.59)") and sr.figure_ok("0.00") and sr.figure_ok("1,234.50")
    words = [_w(10, 50, "Net"), _w(40, 50, "loss"), _w(195, 50, "("), _w(200, 50, "19.59"), _w(300, 50, "12.62")]
    order = sorted(range(len(words)), key=lambda j: words[j][0])
    assert sr._lone_bracket_beside(words, order, 3)
    assert not sr._lone_bracket_beside(words, order, 4)


def test_year_column_naming_a_half_or_a_non_march_end_is_refused():
    assert not sr.kind_ok("Year Ended Half September 30, 2025", "year", "2025-09-30")
    assert not sr.kind_ok("Year Ended September 30, 2025", "year", "2025-09-30")
    assert sr.kind_ok("Year Ended March 31, 2025", "year", "2025-03-31")
    assert sr.kind_ok("Half Year Ended September 30, 2025", "half", "2025-09-30")


def test_signature_block_ids_never_pass_the_gate():
    c, d = _cell("q2fy25", "07027180", label="(DIN"), _cell("q2fy26", "07027180", label="(DIN")
    assert {x["gate"] for x in sr.cross_gate([c, d], FILED)} == {"not_a_figure"}


def test_split_number_line_is_refused():
    page = _page() + [_w(10, 86, "Profit"), _w(45, 86, "after"), _w(75, 86, "tax"), _w(200, 86, "20"),
                      _w(212, 86, "971"), _w(300, 86, "13"), _w(312, 86, "938")]
    labels = {c["row_label"] for c in sr.read_page(page)}
    assert "Profit after tax" not in labels and "Revenue from operations" in labels


def test_repeated_label_with_one_section_is_refused():
    page = _page() + [_w(10, 86, "Other"), _w(40, 86, "income"), _w(200, 86, "5.10"), _w(300, 86, "4.00")]
    got = {(c["row_label"], c["value_text"]) for c in sr.settled(page)}
    assert not any(label == "Other income" for label, _ in got)
    assert ("Total income", "1,245.60") in got


# --- T-226 review r5 (dsh 20261119T143028Z-6e23f738): each reproduced wrong-served class is a test ---------------

def _rows_page(dl, dr, rows):
    ws = [_w(10, 2, "STATEMENT"), _w(70, 2, "OF"), _w(90, 2, "CONSOLIDATED"), _w(160, 2, "RESULTS"),
          _w(200, 20, "Quarter"), _w(240, 20, "Ended"), _w(300, 20, "Quarter"), _w(340, 20, "Ended"),
          _w(200, 30, dl), _w(300, 30, dr)]
    y = 50
    for lab, left, right in rows:
        x = 10
        for t in lab:
            ws.append(_w(x, y, t))
            x += 5 * len(t) + 4
        for t in left:
            ws.append(_w(190 if t in ("-", "(Rs.") and t == "-" else (178 if t == "(Rs." else 200), y, t))
        for t in right:
            ws.append(_w(300, y, t))
        y += 12
    return ws


REV = [["Revenue", "from", "operations"], ["1,200.50"], ["1,100.25"]]


def test_r5_f1_f2_detached_minus_or_currency_bracket_is_refused():
    for sign in ("-", "(Rs."):
        page = _rows_page("30.09.2024", "30.09.2023", [REV, (["Net", "loss"], [sign, "19.59"], ["12.62"])])
        values = {c["value_text"] for c in sr.settled(page) if c["row_label"] == "Net loss"}
        assert "19.59" not in values, sign


def test_r5_f3_title_naming_both_bases_leaves_basis_undecided():
    ws = [_w(10, 2, "STATEMENT"), _w(70, 2, "OF"), _w(90, 2, "STANDALONE"), _w(150, 2, "AND"),
          _w(175, 2, "CONSOLIDATED"), _w(250, 2, "RESULTS")]
    assert sr.page_basis(ws) == ""
    c, d = _cell("q2fy25", "5.00"), _cell("q2fy26", "5.00")
    c["basis"] = d["basis"] = ""
    assert {x["gate"] for x in sr.cross_gate([c, d], FILED)} == {"basis_unknown"}


def test_r5_f4_xbrl_judge_sees_the_page_title(monkeypatch):
    from reality_engine.v2 import cell_judge as cj

    seen = []

    def judge(cell, x):
        seen.append(cell["table_title"])
        return cj.Verdict("disagree" if "BALANCE SHEET" in cell["table_title"] else "no_xbrl_line")

    monkeypatch.setattr(cj, "judge", judge)
    cells = [dict(_cell(d, "1,300.00"), title="BALANCE SHEET AS AT 31.03.2025") for d in ("q2fy25", "q2fy26")]
    assert {x["gate"] for x in sr.cross_gate(cells, FILED, xbrl=_Xbrl())} == {"xbrl_disagrees"}
    assert seen and "BALANCE SHEET" in seen[0]


def test_r5_f4_sign_flip_agreement_is_refused(monkeypatch):
    from reality_engine.v2 import cell_judge as cj

    monkeypatch.setattr(cj, "judge", lambda cell, x: cj.Verdict("agree", sign_flip=True))
    cells = [_cell("q2fy25", "19.59"), _cell("q2fy26", "19.59")]
    assert {x["gate"] for x in sr.cross_gate(cells, FILED, xbrl=_Xbrl())} == {"xbrl_disagrees"}


def test_r5_f5_page_phone_fax_pin_lines_are_not_figures():
    for lab, val in (("Page", "2"), ("Telephone:", "1234"), ("Fax:", "5678"), ("PIN", "400001")):
        page = _rows_page("30.09.2024", "30.09.2023", [REV]) + [_w(10, 86, lab), _w(200, 86, val)]
        assert not [c for c in sr.read_page(page) if c["value"] == val], lab


def test_r5_f6_wrapped_label_fragment_is_refused():
    page = _rows_page("30.09.2024", "30.09.2023", [REV]) + [
        _w(10, 74, "Less:"), _w(45, 74, "Provision"), _w(95, 74, "for"), _w(115, 74, "doubtful"),
        _w(10, 86, "Debts"), _w(200, 86, "123.40"), _w(300, 86, "98.00")]
    assert not [c for c in sr.read_page(page) if c["row_label"] == "Debts"]


def test_r5_f7_per_equity_share_wording_needs_a_decimal():
    assert not sr.per_share_ok("Per equity share (in Rs.)", "154")
    assert sr.per_share_ok("Per equity share (in Rs.)", "1.54")


def test_cross_gate_cell_without_a_filing_date_is_refused():
    assert sr.cross_gate([_cell("unknown_doc", "5.00")], FILED)[0]["gate"] == "no_filing_date"


def test_line_with_no_header_band_is_skipped_not_an_error():
    page = [_w(10, 10, "Revenue"), _w(60, 10, "from"), _w(90, 10, "operations"), _w(200, 10, "1,200.50")]
    assert sr.read_page(page) == []


def test_wrapped_label_with_wide_line_spacing_is_refused():
    # c05 cash flow: "Acquisition of Property, Plant and Equipments," wraps to "(Including Capital ... ) (net)"
    page = _rows_page("30.09.2024", "30.09.2023", [REV]) + [
        _w(10, 74, "Acquisition"), _w(70, 74, "of"), _w(85, 74, "Property,"), _w(135, 74, "Plant"),
        _w(10, 86 + 4, "(Including"), _w(65, 90, "Capital"), _w(105, 90, "(net)"), _w(200, 90, "(559.52)"),
        _w(300, 90, "(802.98)")]
    assert not [c for c in sr.read_page(page) if c["row_label"].startswith("(Including")]


def test_generic_label_needs_a_real_section():
    assert sr.generic_unanchored("Total", "")
    assert sr.generic_unanchored("Total", "Quarter ended Nine months ended Year ended")
    assert not sr.generic_unanchored("Total", "Segment Revenue")
    assert not sr.generic_unanchored("Total Income", "")
    assert sr.generic_unanchored("(ii) Others", "")


# --- T-226 re-review (dsh 20261119T150452Z-8f05257b): five bypasses of the r5 fixes, layouts as reproduced -------

def _lw(y, words, x=10):
    out = []
    for t in words:
        out.append(_w(x, y, t))
        x += 5 * len(t) + 4
    return out


def _base():
    return [_w(10, 2, "STATEMENT"), _w(70, 2, "OF"), _w(90, 2, "CONSOLIDATED"), _w(160, 2, "RESULTS"),
            _w(200, 20, "Quarter"), _w(240, 20, "Ended"), _w(300, 20, "Quarter"), _w(340, 20, "Ended"),
            _w(200, 30, "30.09.2024"), _w(300, 30, "30.09.2023")] + _lw(50, ["Revenue", "from", "operations"]) + [
            _w(200, 50, "1,200.50"), _w(300, 50, "1,100.25")]


_OTHER = _lw(62, ["Other", "income"]) + [_w(200, 62, "45.10"), _w(300, 62, "40.00")]


def _passed(page):
    cells = sr.settled(page)
    filed = {"a": dt.date(2024, 11, 12), "b": dt.date(2025, 11, 12)}
    gated = sr.cross_gate([dict(c, doc_key="a") for c in cells] + [dict(c, doc_key="b") for c in cells], filed)
    return {(c["row_label"], c["value_text"]) for c in gated if c["gate"] == "pass"}


def test_rr_fa_minus_far_left_in_the_cell_is_refused():
    page = _base() + _lw(62, ["Net", "loss"]) + [_w(183, 62, "-"), _w(200, 62, "19.59"), _w(300, 62, "12.62")]
    got = _passed(page)
    assert ("Net loss", "19.59") not in got and ("Net loss", "12.62") in got


def test_rr_fa_bracket_and_currency_two_words_away_is_refused():
    page = _base() + _lw(62, ["Net", "loss", "after", "exceptional", "items"]) + [
        _w(171, 62, "("), _w(180, 62, "₹"), _w(200, 62, "19.59"), _w(300, 62, "12.62")]
    assert not any(v == "19.59" for _, v in _passed(page))


def test_rr_fa_bullet_dash_before_a_label_is_not_a_minus():
    page = _base() + _lw(62, ["-", "Current", "Tax", "Expense"]) + [_w(200, 62, "82.00"), _w(300, 62, "75.00")]
    assert ("- Current Tax Expense", "82.00") in _passed(page)


def test_rr_fb_wide_spaced_wrap_is_refused():
    page = _base() + _OTHER + _lw(74, ["Acquisition", "of", "Property,", "Plant", "and", "Equipments,"]) + _lw(
        98, ["(Including", "Capital", "Work", "In", "Progress"]) + [_w(200, 98, "(559.52)"), _w(300, 98, "(802.98)")]
    assert not any(label.startswith("(Including") for label, _ in _passed(page))


def test_rr_fc_wrap_whose_first_line_has_a_note_number_is_refused():
    page = _base() + _OTHER + _lw(74, ["Less:", "Provision", "for", "doubtful"]) + [_w(180, 74, "5")] + _lw(
        86, ["Debts"]) + [_w(200, 86, "123.40"), _w(300, 86, "98.00")]
    assert not any(label == "Debts" for label, _ in _passed(page))


def test_rr_fd_wrapped_per_share_label_is_refused():
    page = _base() + _OTHER + _lw(74, ["Per", "equity"]) + _lw(86, ["Share", "(in", "Rs.)"]) + [
        _w(200, 86, "154"), _w(300, 86, "138")]
    assert not any(v in ("154", "138") for _, v in _passed(page))


def test_rr_fe_generic_labels_with_markers_are_refused():
    assert sr.generic_unanchored("Total (A)", "") and sr.generic_unanchored("Net Total", "")
    page = _base() + _lw(62, ["Total", "(A)"]) + [_w(200, 62, "1,245.60"), _w(300, 62, "1,140.25")]
    assert not any(label == "Total (A)" for label, _ in _passed(page))


# --- T-226 third review (dsh 20261119T153807Z-302115b9) ----------------------------------------------------------

def test_r3_1_footnote_between_minus_and_figure_still_refuses():
    page = _base() + _lw(62, ["Net", "loss"]) + [_w(176, 62, "-"), _w(186, 62, "1"), _w(200, 62, "19.59"),
                                                 _w(300, 62, "12.62")]
    assert ("Net loss", "19.59") not in _passed(page)


def test_r3_2_note_reference_is_not_a_figure():
    page = _base() + _OTHER + _lw(74, ["Provision", "for", "doubtful", "debts", "Note"]) + [_w(300, 74, "12.3")]
    assert not any(v == "12.3" for _, v in _passed(page))


def test_r3_4_gross_is_generic():
    assert sr.generic_unanchored("Gross", "")


def test_r3_5_company_name_is_not_a_basis():
    ws = [_w(10, 2, "CONSOLIDATED"), _w(80, 2, "FINVEST"), _w(130, 2, "LIMITED"), _w(180, 2, "UNAUDITED")]
    assert sr.page_basis(ws) == ""
    ws2 = [_w(10, 2, "STATEMENT"), _w(70, 2, "OF"), _w(90, 2, "STANDALONE"), _w(150, 2, "UNAUDITED"),
           _w(210, 2, "RESULTS")]
    assert sr.page_basis(ws2) == "standalone"
