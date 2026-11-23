"""T-132: printed table cells from the text layer (headers, labels, periods, units, signs)."""
import os
import shutil
import sqlite3
import tempfile
from datetime import date
from pathlib import Path

import pymupdf
import pytest

from reality_engine.v2 import cell_sample, schema
from reality_engine.v2.periods import period_row
from reality_engine.v2.table_cells import (_label_continues, _merge_date_phrases, _rows_of,
                                          _squash_digits, extract, extract_page, label_unit,
                                          period_from_header)

HAVELLS = Path("D:/RealityEngine/raw/pilot60_history/HAVELLS/investor_presentation/"
               "d8b03849-76b8-4a7b-9672-984693e5cfb6.pdf")
ASIANPAINT = Path("D:/RealityEngine/raw/pilot60_history/ASIANPAINT/quarterly_results/"
                  "92071a93-de8f-4923-85b6-f853a765c9b9.pdf")
INDHOTEL = Path("D:/RealityEngine/raw/pilot60_history/INDHOTEL/quarterly_results/"
                "bf8004d9-f1e4-48a8-bf05-5309ea25fd2a.pdf")
ADANI_BALANCE = Path("D:/RealityEngine/raw/pilot60_history/ADANIPORTS/quarterly_results/"
                     "446f8fb4-dd8f-46d7-a1a5-d52c9af21d8b.pdf")
ADANI_DECK = Path("D:/RealityEngine/raw/pilot60_history/ADANIPORTS/investor_presentation/"
                  "1fc2a481-3e16-4c98-abe4-6970bbbf80c1.pdf")
CRORE = 1e7


def _right(anchor: float, y: float, text: str, size: float = 9) -> tuple:
    width = pymupdf.get_text_length(text, fontname="helv", fontsize=size)
    return (anchor - width, y, text, size)


def _center(centre: float, y: float, text: str, size: float = 16) -> tuple:
    width = pymupdf.get_text_length(text, fontname="helv", fontsize=size)
    return (centre - width / 2, y, text, size)


def _save(path: Path, lines: list[tuple]) -> str:
    document = pymupdf.open()
    page = document.new_page(width=842, height=595)
    for x, y, text, size in lines:
        page.insert_text((x, y), text, fontsize=size, fontname="helv")
    document.save(str(path))
    document.close()
    return str(path)


@pytest.fixture()
def pdf_path():
    handle, name = tempfile.mkstemp(prefix="t132-", suffix=".pdf", dir=".tmp")
    os.close(handle)
    path = Path(name)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _pid(start: str | None, end: str) -> str:
    return str(period_row(start, end)["period_id"])


def _by_label(cells: list[dict], text: str) -> list[dict]:
    return [cell for cell in cells if cell["row_label"] and text in cell["row_label"]]


def _pl_page(pdf_path: Path) -> list[dict]:
    """A results P&L: quarter/half/year header stack, numbered rows, Expenses section."""
    anchors = [320, 400, 480, 620, 760]
    values = {
        1: ["1,500", "1,400", "1,200", "2,900", "5,500"],
        2: ["100", "(1,234.5)", "-", "190", "350"],
        3: ["2,028", "1,490", "1,280", "3,090", "5,850"],
        5: ["700", "650", "600", "1,350", "2,600"],
        6: ["200", "190", "180", "390", "750"],
        7: ["300", "280", "250", "580", "1,100"],
        8: ["400", "370", "250", "770", "1,400"],
    }
    lines = [(60, 50, "Consolidated Statement of Profit and Loss (Rs. in crore)", 9),
             _center(383, 110, "Quarter ended"), _center(603, 110, "Half year ended"),
             _center(743, 110, "Year ended")]
    lines += [_right(anchor, 130, date, 8) for anchor, date in zip(
        anchors, ("30.09.2026", "30.06.2026", "30.09.2025", "30.09.2026", "31.03.2026"))]
    labels = {1: "Revenue from operations", 2: "Other income", 3: "Total income"}
    y = 180
    for number in (1, 2, 3):
        lines.append((40, y, str(number), 9))
        lines.append((60, y, labels[number], 9))
        for anchor, text in zip(anchors, values[number]):
            if number == 3 and text == "2,028":          # split by the text layer
                lines.append((295, y, "2,", 9))
                lines.append((295 + pymupdf.get_text_length("2,", fontname="helv", fontsize=9) + 3.5,
                              y, "028", 9))
            else:
                lines.append(_right(anchor, y, text))
        y += 18
    lines += [(40, y, "4", 9), (60, y, "Expenses", 9)]
    y += 18
    sub_rows = (("(a)", "Cost of materials", values[5]), ("(b)", "Employee benefits", values[6]),
                ("(c)", "Other expenses", values[7]))
    for number, (sub, label, row_values) in zip((5, 6, 7), sub_rows):
        lines.append((40, y, sub, 9))
        lines.append((60, y, label, 9))
        lines += [_right(anchor, y, text) for anchor, text in zip(anchors, row_values)]
        y += 18
    lines.append((40, y, "5", 9))
    lines.append((60, y, "Profit before tax", 9))
    lines += [_right(anchor, y, text) for anchor, text in zip(anchors, values[8])]
    return extract(_save(pdf_path, lines))


def test_results_table_labels_headers_periods_and_values(pdf_path):
    cells = _pl_page(pdf_path)
    assert len(cells) == 35                              # 7 rows x 5 date columns
    assert {cell["basis"] for cell in cells} == {"consolidated"}
    assert {cell["method"] for cell in cells} == {"text_layer"}
    assert all(cell["bbox"] for cell in cells)

    materials = _by_label(cells, "Cost of materials")
    assert len(materials) == 5
    assert {cell["row_label"] for cell in materials} == {"Expenses > (a) Cost of materials"}
    by_column = {cell["col_no"]: cell for cell in materials}
    assert "Quarter ended" in by_column[0]["col_header"]
    assert "30.09.2026" in by_column[0]["col_header"]
    assert by_column[0]["period_id"] == _pid("2026-07-01", "2026-09-30")      # Q2FY27
    assert by_column[1]["period_id"] == _pid("2026-04-01", "2026-06-30")      # Q1FY27
    assert by_column[2]["period_id"] == _pid("2025-07-01", "2025-09-30")      # Q2FY26
    assert by_column[3]["period_id"] == _pid("2026-04-01", "2026-09-30")      # H1FY27
    assert by_column[4]["period_id"] == _pid("2025-04-01", "2026-03-31")      # FY26
    assert by_column[0]["value"] == 700 * CRORE
    assert by_column[0]["unit_text"] == "Rs crore" and by_column[0]["scale"] == CRORE

    profit = _by_label(cells, "Profit before tax")
    assert profit and all(cell["row_label"] == "Profit before tax" for cell in profit)


def test_split_numbers_negatives_and_placeholders(pdf_path):
    cells = _pl_page(pdf_path)
    total = {cell["col_no"]: cell for cell in _by_label(cells, "Total income")}
    assert total[0]["value_text"] == "2,028"
    assert total[0]["value"] == 2_028 * CRORE
    other = {cell["col_no"]: cell for cell in _by_label(cells, "Other income")}
    assert other[1]["value_text"] == "(1,234.5)"
    assert other[1]["value"] == -1_234.5 * CRORE
    assert other[2]["value_text"] == "-"
    assert other[2]["value"] is None


def test_percent_column_stays_in_percent_points(pdf_path):
    anchors = [320, 480]
    lines = [(60, 50, "Standalone Results (Rs. in crore)", 9),
             _right(anchors[0], 110, "30.09.2026", 8),
             _right(anchors[1], 110, "YoY (%)", 8)]
    for y, (revenue, growth) in zip((150, 168), (("1,500", "12.3%"), ("1,400", "10.0%"))):
        lines.append((60, y, "Revenue", 9))
        lines.append(_right(anchors[0], y, revenue))
        lines.append(_right(anchors[1], y, growth))
    cells = extract(_save(pdf_path, lines))
    percent = [cell for cell in cells if cell["col_no"] == 1]
    assert percent and all(cell["unit_text"] == "%" for cell in percent)
    assert {cell["scale"] for cell in percent} == {1.0}
    assert percent[0]["value"] == 12.3
    assert {cell["period_id"] for cell in percent} == {None}


def test_no_unit_means_no_value(pdf_path):
    anchors = [320, 480]
    lines = [_center(400, 95, "Quarter ended"),
             _right(anchors[0], 110, "30.09.2026", 8),
             _right(anchors[1], 110, "30.06.2026", 8)]
    for y, (left, right) in zip((150, 168), (("1,234.5", "1,100.0"), ("900.0", "800.0"))):
        lines.append((60, y, "Revenue", 9))
        lines.append(_right(anchors[0], y, left))
        lines.append(_right(anchors[1], y, right))
    cells = extract(_save(pdf_path, lines))
    assert cells
    assert all(cell["value"] is None and cell["scale"] is None for cell in cells)
    assert cells[0]["value_text"] == "1,234.5"
    assert {cell["period_id"] for cell in cells} == {
        _pid("2026-07-01", "2026-09-30"), _pid("2026-04-01", "2026-06-30")}


def test_infographic_page_gives_no_cells(pdf_path):
    lines = [(120, 120, "78%", 22), (420, 200, "1,234", 18), (690, 310, "56", 16),
             (200, 420, "Growth", 14), (600, 470, "Market share", 12),
             (90, 520, "9,999", 20)]
    cells = extract(_save(pdf_path, lines))
    assert cells == []


def test_header_periods_survive_a_wrapped_date_row():
    from reality_engine.v2.table_cells import period_from_header

    assert period_from_header("Quarter ended > June > 30,2025") == _pid("2025-04-01", "2025-06-30")
    assert period_from_header("Quarter ended > June 30, 2025") == _pid("2025-04-01", "2025-06-30")
    assert period_from_header("Quarter ended > Jun-25") == _pid("2025-04-01", "2025-06-30")
    assert period_from_header("Quarter ended > June") is None


def test_bad_digit_grouping_keeps_value_text_without_value(pdf_path):
    """Defect 1: '860,19' / '44,86' are print breaks, not numbers; a date fragment is no cell."""
    anchors = [320, 480]
    lines = [(60, 50, "Results (Rs. in crore)", 9), (400, 70, "Year Ended", 8),
             _right(anchors[0], 90, "31.03.2025", 8), _right(anchors[1], 90, "31.03.2024", 8)]
    rows = (("Revenue", "1,16,388.11", "2,028"), ("Cost", "860,19", "44,86"),
            ("Other income", "31,2026", "1,234"))
    for y, (label, left, right) in zip((140, 160, 180), rows):
        lines.append((60, y, label, 9))
        lines += [_right(anchor, y, text) for anchor, text in zip(anchors, (left, right))]
    cells = extract(_save(pdf_path, lines))
    by_text = {cell["value_text"]: cell for cell in cells}
    assert by_text["1,16,388.11"]["value"] == 116_388.11 * CRORE
    assert by_text["860,19"]["value"] is None and by_text["860,19"]["value_text"] == "860,19"
    assert by_text["44,86"]["value"] is None
    assert "31,2026" not in by_text                      # a date fragment is not a table cell
    assert {cell["period_id"] for cell in cells} == {
        _pid("2024-04-01", "2025-03-31"), _pid("2023-04-01", "2024-03-31")}


def test_wrapped_balance_sheet_header_resolves_the_point_period(pdf_path):
    """Defect 2: 'As at > March 31, > 2026' used to read 'March 31' as the year 2031."""
    anchors = [400, 540]
    lines = [(180, 50, "Balance Sheet", 9),
             _right(anchors[0], 70, "As at", 8), _right(anchors[1], 70, "As at", 8),
             _right(anchors[0], 80, "March 31,", 8), _right(anchors[1], 80, "March 31,", 8),
             _right(anchors[0], 90, "2026", 8), _right(anchors[1], 90, "2025*", 8),
             _right(anchors[0], 100, "(Audited)", 8), _right(anchors[1], 100, "(Audited)", 8)]
    for y, (left, right) in zip((140, 160), (("10,570.25", "11,014.60"), ("44,86", "46.00"))):
        lines.append((60, y, "Property, Plant and Equipment", 9))
        lines += [_right(anchor, y, text) for anchor, text in zip(anchors, (left, right))]
    cells = extract(_save(pdf_path, lines))
    by_col = {cell["col_no"]: cell for cell in cells
              if cell["row_label"] == "Property, Plant and Equipment"}
    assert by_col[0]["period_id"] == _pid(None, "2026-03-31")
    assert by_col[1]["period_id"] == _pid(None, "2025-03-31")

    from reality_engine.v2.table_cells import period_from_header
    assert period_from_header("As at > March 31, > 2026 > (Audited)") == _pid(None, "2026-03-31")
    assert period_from_header("As at > March 31, > 2025* > (Audited)") == _pid(None, "2025-03-31")
    assert period_from_header("Quarter Ended > Q1 25-26") == _pid("2025-04-01", "2025-06-30")
    assert period_from_header("Quarter Ended > Q2 26-27") == _pid("2026-07-01", "2026-09-30")
    assert period_from_header("As at > Dec-24") == _pid(None, "2024-12-31")
    assert period_from_header("As at > Jun-26") == _pid(None, "2026-06-30")
    assert period_from_header("As at > Mar'24") == _pid(None, "2024-03-31")
    assert period_from_header("Year Ended > FY25-26") == _pid("2025-04-01", "2026-03-31")
    assert period_from_header("Nine Months Ended > 9M FY27") == _pid("2026-04-01", "2026-12-31")
    assert period_from_header("Half Year Ended > H1 26-27") == _pid("2026-04-01", "2026-09-30")
    assert period_from_header("Quarter Ended > YTD FY26", date(2026, 1, 20)) == \
        _pid("2025-04-01", "2025-12-31")
    assert period_from_header("Quarter Ended > YTD FY26") == _pid("2025-04-01", "2026-03-31")


def test_unit_from_split_header_line_and_from_a_row_label(pdf_path):
    """Defect 3: 'f Lakhs' (text-layer split of '(₹ in Lakhs)') and 'EBIT ( ₹ crores)'."""
    anchors = [320, 480, 640]
    lines = [(60, 30, "Segment revenue", 9), (500, 45, "f Lakhs", 8),
             (330, 60, "Year Ended", 8), (500, 60, "Year Ended", 8)]
    lines += [_right(anchor, 80, "31.03.2025", 8) for anchor in anchors]
    for y, label in zip((130, 150), ("Hotel Services", "Air and Institutional catering")):
        lines.append((60, y, label, 9))
        lines += [_right(anchor, y, text) for anchor, text in zip(anchors, ("762324", "71641", "833965"))]
    cells = extract(_save(pdf_path, lines))
    assert cells and all(cell["scale"] == 1e5 for cell in cells)
    assert cells[0]["unit_text"] == "Rs lakh" and cells[0]["value"] == 762324 * 1e5

    lines = [(60, 50, "Year Ended", 9), (300, 50, "31.03.2025", 8),
             (60, 120, "EBIT ( \u20b9 crores)", 9), _right(320, 120, "100"),
             _right(480, 120, "200"), (60, 140, "Other income", 9),
             _right(320, 140, "300"), _right(480, 140, "400")]
    cells = extract(_save(pdf_path, lines))
    ebit = [cell for cell in cells if cell["row_label"] and "EBIT" in cell["row_label"]]
    other = [cell for cell in cells if cell["row_label"] == "Other income"]
    assert ebit and all(cell["scale"] == CRORE for cell in ebit)
    assert other and all(cell["scale"] is None and cell["value"] is None for cell in other)


def test_callout_rows_are_not_column_headers(pdf_path):
    """Defect 4: slide call-outs above the table ('Rs 353 crores', 'PAT') must not be headers."""
    anchors = [333, 401, 468, 536]
    lines = [(270, 128, "Q2 FY27", 9),
             (191, 147, "(Quarter Ended September 30,2026)", 8),
             (205, 188, "Rs 576 crores", 8),
             (86, 193, "34.6% YoY Rs 353 crores Rs 1,190 crores", 8),
             (208, 204, "30.5% Growth YoY", 8),
             (78, 209, "Net Revenue Growth", 8), (358, 209, "PAT", 8),
             (447, 209, "Cash & Cash Equivalent", 8),
             (226, 215, "EBITDA", 8),
             (54, 249, "1. P&L Summary - Quarterly", 8),
             (59, 266, "(In Rs crores)", 8)]
    lines += [(270, 266, "Q2 FY27", 8), (368, 266, "Q2 FY26", 8),
              (420, 266, "YoY (%)", 8), (500, 266, "Q1 FY27", 8)]
    for y, (label, values) in zip((284, 299), (
            ("Net Revenue (NR)", ("6,417", "4,767", "34.6%", "6,510")),
            ("Contribution", ("1,166", "958", "21.7%", "1,194")))):
        lines.append((59, y, label, 9))
        lines += [_right(anchor, y, text) for anchor, text in zip(anchors, values)]
    cells = extract(_save(pdf_path, lines))
    assert len(cells) == 8
    assert {cell["col_header"] for cell in cells} == {"Q2 FY27", "Q2 FY26", "YoY (%)", "Q1 FY27"}
    assert not any("353" in (cell["col_header"] or "") or "PAT" in (cell["col_header"] or "")
                   for cell in cells)
    assert cells[0]["period_id"] == _pid("2026-07-01", "2026-09-30")
    assert cells[0]["value"] == 6417 * CRORE


def test_prose_with_numbers_is_not_a_table(pdf_path):
    """Defect 5: footnote prose with scattered numbers used to become row labels and cells."""
    lines = [
        (31, 200, "aligned with market growth. Growth of the company from 113 MMT to 408 MMT "
                  "between 2014 and 2024, outpacing the industry", 8),
        (31, 210, "(5%). The capacity expanded from 0.3 GW to 10.9 GW (57%) between 2016 and 2024, "
                  "surpassing the industry", 8),
        (31, 220, "and 2024, surpassing the industry from 3,41,551 ckm to 4,85,544 ckm (4%). "
                  "ATGL expanded its areas", 8),
    ]
    assert extract(_save(pdf_path, lines)) == []


def test_a_continued_statement_inherits_the_previous_page_headers(pdf_path):
    """A statement continued on the next page keeps the header printed on the first page."""
    document = pymupdf.open()
    first = document.new_page(width=842, height=595)
    anchors = [320, 480]
    first.insert_text((60, 50), "Consolidated P&L (Rs. in crore)", fontsize=9, fontname="helv")
    for x, text in ((260, "Q2 FY27"), (420, "Q2 FY26")):
        first.insert_text((x, 80), text, fontsize=9, fontname="helv")
    for y, texts in ((140, ("1,500", "1,400")), (160, ("1,600", "1,500"))):
        first.insert_text((60, y), "Revenue", fontsize=9, fontname="helv")
        for anchor, text in zip(anchors, texts):
            x0, y0, text, size = _right(anchor, y, text)
            first.insert_text((x0, y0), text, fontsize=size, fontname="helv")
    second = document.new_page(width=842, height=595)
    for y, texts in ((120, ("1,700", "1,600")), (140, ("1,800", "1,700"))):
        second.insert_text((60, y), "Revenue", fontsize=9, fontname="helv")
        for anchor, text in zip(anchors, texts):
            x0, y0, text, size = _right(anchor, y, text)
            second.insert_text((x0, y0), text, fontsize=size, fontname="helv")
    document.save(str(pdf_path))
    document.close()
    cells = extract(str(pdf_path))
    page2 = [cell for cell in cells if cell["page"] == 2]
    assert page2 and {cell["col_header"] for cell in page2} == {"Q2 FY27", "Q2 FY26"}
    assert {cell["period_id"] for cell in page2} == {
        _pid("2026-07-01", "2026-09-30"), _pid("2025-07-01", "2025-09-30")}


@pytest.mark.skipif(not HAVELLS.exists(), reason="Havells information update is not on disk")
def test_smoke_havells_segment_table():
    cells = extract(str(HAVELLS))
    page5 = [cell for cell in cells if cell["page"] == 5 and cell["table_no"] == 0]
    assert len(page5) == 36                              # 9 segment rows x 4 columns
    assert all(cell["row_label"] for cell in page5)
    assert all(cell["col_header"] for cell in page5)
    first = page5[0]
    assert first["period_id"] == _pid("2026-07-01", "2026-09-30") and first["value"] == 782 * CRORE

    page4 = [cell for cell in cells if cell["page"] == 4]
    assert page4 and {cell["col_header"] for cell in page4} == {
        "Q2 FY27", "Q2 FY26", "YoY (%)", "Q1 FY27"}
    assert not any("PAT" in (cell["col_header"] or "") or "353" in (cell["col_header"] or "")
                   for cell in page4)


@pytest.mark.skipif(not ASIANPAINT.exists(), reason="Asian Paints results are not on disk")
def test_smoke_asian_paints_revenue_row():
    cells = extract(str(ASIANPAINT))
    revenue = [cell for cell in cells if cell["page"] == 5 and cell["row_label"]
               and "Revenue from operations" in cell["row_label"]]
    q2 = [cell for cell in revenue if cell["period_id"] == _pid("2026-07-01", "2026-09-30")]
    assert q2, [(cell["col_header"], cell["period_id"]) for cell in revenue]
    assert q2[0]["unit_text"] == "Rs crore" and q2[0]["scale"] == CRORE


@pytest.mark.skipif(not INDHOTEL.exists(), reason="Indian Hotels results are not on disk")
def test_smoke_indian_hotels_split_lakh_header():
    with pymupdf.open(str(INDHOTEL)) as document:
        cells = extract_page(document[11], 12)
    first = cells[0]
    assert first["row_label"].split(" > ")[-1] == "Hotel Services"
    assert "Segment Revenue" in first["row_label"]      # its printed section parent
    assert first["unit_text"] == "Rs lakh" and first["scale"] == 1e5
    assert first["period_id"] == _pid("2025-04-01", "2025-06-30")


@pytest.mark.skipif(not ADANI_BALANCE.exists(), reason="Adani Ports results are not on disk")
def test_smoke_adani_wrapped_balance_sheet_and_bad_grouping():
    with pymupdf.open(str(ADANI_BALANCE)) as document:
        cells = extract_page(document[25], 26)
    goodwill = [cell for cell in cells if cell["row_label"] == "Goodwill"]
    assert len(goodwill) == 2
    assert {cell["period_id"] for cell in goodwill} == {_pid(None, "2026-03-31"),
                                                        _pid(None, "2025-03-31")}
    assert all(cell["value"] is None for cell in goodwill)       # '44,86' is not a number
    ppe = [cell for cell in cells if cell["row_label"] == "Property, Plant and Equipment"]
    assert ppe[0]["value"] == 10_570.25 * CRORE


@pytest.mark.skipif(not ADANI_DECK.exists(), reason="Adani Ports deck is not on disk")
def test_smoke_adani_deck_prose_page_has_no_cells():
    with pymupdf.open(str(ADANI_DECK)) as document:
        assert extract_page(document[5], 6) == []


TITAN_RESULTS = Path("D:/RealityEngine/raw/pilot60_history/TITAN/quarterly_results/"
                     "6d34f7e0-d10e-4dd0-8b27-6ebb6a4a8ad9.pdf")
COALINDIA_DECK = Path("D:/RealityEngine/raw/pilot60_history/COALINDIA/investor_presentation/"
                      "c8559664-a5ad-4fbe-8427-8c1155d16277.pdf")


def test_bare_date_header_is_a_quarter_in_results_and_a_point_on_a_balance_sheet(pdf_path):
    """Round 3, class 1: '31-12-2024 > (Unaudited)' names a period, never nothing."""
    anchors = [480, 640]
    header = [(60, 50, "Statement of Unaudited Financial Results (Rs. in crore)", 9)]
    for anchors_col, date_text in ((anchors[0], "31-12-2024"), (anchors[1], "30-09-2024")):
        header += [_right(anchors_col, 70, date_text, 8), _right(anchors_col, 80, "(Unaudited)", 8)]
    rows = (("Revenue from operations", "1,500", "1,400"), ("Profit before tax", "200", "190"))
    lines = header + [(60, y, label, 9) for y, (label, _, _) in zip((140, 160), rows)]
    for y, (_, left, right) in zip((140, 160), rows):
        lines += [_right(anchors[0], y, left), _right(anchors[1], y, right)]
    cells = extract(_save(pdf_path, lines), doc_type="results")
    assert {cell["period_id"] for cell in cells} == {
        _pid("2024-10-01", "2024-12-31"), _pid("2024-07-01", "2024-09-30")}

    lines[0] = (60, 50, "Balance Sheet (Rs. in crore)", 9)          # an as-at page
    cells = extract(_save(pdf_path, lines), doc_type="results")
    assert {cell["period_id"] for cell in cells} == {
        _pid(None, "2024-12-31"), _pid(None, "2024-09-30")}

    lines = [(60, 50, "Shareholding pattern", 9),
             _right(anchors[0], 70, "Mar-26", 8), _right(anchors[1], 70, "Mar-25", 8),
             (60, 140, "Promoter", 9), (60, 160, "Public", 9)]
    lines += [_right(anchors[0], y, text) for y, text in zip((140, 160), ("50.2", "49.8"))]
    lines += [_right(anchors[1], y, text) for y, text in zip((140, 160), ("49.8", "50.2"))]
    cells = extract(_save(pdf_path, lines), doc_type="deck")
    assert {cell["period_id"] for cell in cells} == {
        _pid(None, "2026-03-31"), _pid(None, "2025-03-31")}


def test_bare_nine_month_and_fiscal_year_headers_resolve(pdf_path):
    """Round 3, class 1: a bare '9M' or 'FY' uses the printed year range or the filing date."""
    from reality_engine.v2.table_cells import period_from_header

    assert period_from_header("9M 25-26") == _pid("2025-04-01", "2025-12-31")
    assert period_from_header("9M 24-25") == _pid("2024-04-01", "2024-12-31")
    assert period_from_header("Nine Months Ended > 9M", date(2026, 1, 20)) == \
        _pid("2025-04-01", "2025-12-31")
    assert period_from_header("Year Ended > FY", date(2026, 5, 1)) == \
        _pid("2025-04-01", "2026-03-31")
    assert period_from_header("Quarter Ended > Q3 25-26") == _pid("2025-10-01", "2025-12-31")
    assert period_from_header("Quarter Ended > Y-o-Y Growth") is None


def test_cells_without_a_row_label_or_a_column_header_are_not_stored(pdf_path):
    """Round 3, class 2: an unlabelled row or a headerless column is not a stored cell."""
    anchors = [480, 640]
    lines = [(60, 50, "Results (Rs. in crore)", 9), _right(anchors[0], 70, "31.03.2025", 8)]
    for y, (label, left, right) in zip((140, 160), (("Revenue from operations", "1,500", "1,400"),
                                                    ("", "45,016.75", "2,000"))):
        if label:
            lines.append((60, y, label, 9))
        lines += [_right(anchors[0], y, left), _right(anchors[1], y, right)]
    cells = extract(_save(pdf_path, lines))
    assert cells
    assert {cell["row_label"] for cell in cells} == {"Revenue from operations"}
    assert {cell["col_header"] for cell in cells} == {"31.03.2025"}
    assert all(cell["row_label"] and cell["col_header"] for cell in cells)


def test_per_share_count_and_ratio_rows_keep_their_label_unit(pdf_path):
    """Round 3, class 3: 'per share' / a count / a ratio never takes the page's crore scale."""
    anchors = [480, 640]
    lines = [(60, 50, "Results (Rs. in crore)", 9),
             _right(anchors[0], 70, "31.03.2026", 8), _right(anchors[1], 70, "31.03.2025", 8)]
    rows = (("Basic Earnings Per Share (EPS) (*not annualised)", "10.5", "9.6"),
            ("Paid-up equity share capital (Face value of ₹ 1 per share)", "89", "89"),
            ("No. of employees", "4,012", "4,100"),
            ("Debt Equity Ratio (in times)", "0.14", "0.22"),
            ("Revenue from operations", "1,500", "1,400"),
            ("Total Comprehensive Income", "1,000", "900"))
    for y, (label, left, right) in zip((140, 160, 180, 200, 220, 240), rows):
        lines.append((60, y, label, 9))
        lines += [_right(anchor, y, text) for anchor, text in zip(anchors, (left, right))]
    cells = extract(_save(pdf_path, lines), doc_type="results")
    eps = [cell for cell in cells if "Earnings Per Share" in (cell["row_label"] or "")]
    assert eps and all(cell["unit_text"] == "inr_per_share" and cell["scale"] == 1.0
                       for cell in eps)
    assert eps[0]["value"] == 10.5
    capital = [cell for cell in cells if "equity share capital" in (cell["row_label"] or "")]
    assert capital and all(cell["scale"] == CRORE for cell in capital)   # money, not per share
    employees = [cell for cell in cells if "employees" in (cell["row_label"] or "")]
    assert employees and all(cell["unit_text"] == "count" and cell["scale"] == 1.0
                             for cell in employees)
    ratio = [cell for cell in cells if "Debt Equity Ratio" in (cell["row_label"] or "")]
    assert ratio and all(cell["unit_text"] == "ratio" and cell["scale"] == 1.0 for cell in ratio)
    revenue = [cell for cell in cells if "Revenue from operations" in (cell["row_label"] or "")]
    assert revenue and all(cell["scale"] == CRORE for cell in revenue)


def test_a_garbled_header_date_is_dropped_never_guessed(pdf_path):
    """Round 3, class 4: '30.011.2028' is a broken text layer, not a period."""
    anchors = [480, 640]
    lines = [(60, 50, "Results (Rs. in crore)", 9),
             _right(anchors[0], 70, "30.011.2028", 8), _right(anchors[0], 80, "(Reviewed)", 8),
             _right(anchors[1], 70, "31.03.2026", 8), _right(anchors[1], 80, "(Audited)", 8)]
    for y, (label, left, right) in zip((140, 160), (("Revenue", "1,500", "1,400"),
                                                    ("Profit", "200", "190"))):
        lines.append((60, y, label, 9))
        lines += [_right(anchors[0], y, left), _right(anchors[1], y, right)]
    cells = extract(_save(pdf_path, lines), date(2026, 5, 1), doc_type="results")
    assert cells
    assert not any("2028" in (cell["col_header"] or "") for cell in cells)
    assert not any(cell["period_id"] and "2028" in cell["period_id"] for cell in cells)
    assert {cell["period_id"] for cell in cells} == {_pid("2026-01-01", "2026-03-31")}


def test_difference_columns_are_flagged_and_have_no_period(pdf_path):
    """Round 3, class 5: 'Inc/Dec%' / 'YoY (%)' are differences, not a period's value."""
    anchors = [480, 640]
    lines = [(60, 50, "Results (Rs. in crore)", 9),
             _right(anchors[0], 70, "31.03.2026", 8), _right(anchors[1], 70, "Inc/Dec%", 8)]
    for y, (label, value, change) in zip((140, 160), (("Revenue", "1,500", "12.3%"),
                                                      ("Profit", "200", "-4.5%"))):
        lines.append((60, y, label, 9))
        lines += [_right(anchors[0], y, value), _right(anchors[1], y, change)]
    cells = extract(_save(pdf_path, lines), doc_type="results")
    delta = [cell for cell in cells if cell["col_header"] == "Inc/Dec%"]
    period = [cell for cell in cells if cell["col_header"] == "31.03.2026"]
    assert delta and all(cell["period_id"] is None for cell in delta)
    assert all(cell["method"] == "text_layer;delta" for cell in delta)
    assert period and all(cell["period_id"] == _pid("2026-01-01", "2026-03-31")
                          for cell in period)
    assert all(cell["method"] == "text_layer" for cell in period)


def test_a_wrapped_label_line_belongs_to_the_row_it_finishes(pdf_path):
    """Round 3, class 6: the label's last line is part of its row, not the next row's section."""
    anchors = [420, 560]
    lines = [(60, 50, "Ratios (Rs. in crore)", 9),
             _right(anchors[0], 70, "30.09.26", 8), _right(anchors[1], 70, "31.03.26", 8),
             (60, 140, "Current Ratio", 9),
             _right(anchors[0], 140, "1.81"), _right(anchors[1], 140, "1.86"),
             (60, 176, "Quick Ratio", 9),
             _right(anchors[0], 176, "1.65"), _right(anchors[1], 176, "1.62"),
             (60, 228, "Debtor Turnover Ratio", 9),
             _right(anchors[0], 246, "0.76"), _right(anchors[1], 246, "0.81"),
             (60, 264, "(no. of months of Gross Sales)", 9),
             (60, 298, "EBITDA Margin on Revenue", 9),
             _right(anchors[0], 298, "29%"), _right(anchors[1], 298, "32%")]
    cells = extract(_save(pdf_path, lines), doc_type="deck")
    labels = {cell["row_label"] for cell in cells}
    assert "Debtor Turnover Ratio (no. of months of Gross Sales)" in labels
    assert "EBITDA Margin on Revenue" in labels
    assert not any("no. of months" in label and label.startswith("EBITDA") for label in labels)


@pytest.mark.skipif(not TITAN_RESULTS.exists(), reason="Titan results are not on disk")
def test_smoke_titan_bare_date_balance_sheet_and_joined_labels():
    """Round 3, class 1 and 6: 'Asat > 31-03-2025' is a point; '(v) ...' is its own row."""
    with pymupdf.open(str(TITAN_RESULTS)) as document:
        cells = extract_page(document[6], 7, "2026-11-01", "results")
    investments = [cell for cell in cells if cell["row_label"] == "(g) Financial assets > (i) Investments"]
    assert investments and {cell["period_id"] for cell in investments} == {
        _pid(None, "2025-09-30"), _pid(None, "2025-03-31")}
    other = [cell for cell in cells if cell["row_label"] == "(v) Other financial liabilities"]
    assert other and {cell["value"] for cell in other} == {1528 * CRORE, 1134 * CRORE}
    assert not any("Trade payables" in (cell["row_label"] or "") for cell in other)


@pytest.mark.skipif(not COALINDIA_DECK.exists(), reason="Coal India deck is not on disk")
def test_smoke_coal_india_nine_month_headers_and_difference_columns():
    """Round 3, class 1 and 5: '9M 25-26' resolves and 'Inc/Dec' is flagged."""
    with pymupdf.open(str(COALINDIA_DECK)) as document:
        cells = extract_page(document[18], 19, "2026-11-01", "deck")
    nine_month = [cell for cell in cells if cell["col_header"] == "9M 25-26"]
    assert nine_month and all(cell["period_id"] == _pid("2025-04-01", "2025-12-31")
                              for cell in nine_month)
    delta = [cell for cell in cells if cell["col_header"] == "Inc/Dec%"]
    assert delta and all(cell["period_id"] is None and cell["method"] == "text_layer;delta"
                         for cell in delta)


def test_a_header_date_split_onto_its_own_line_keeps_its_column(pdf_path):
    """Round 4, class 1: the first date printed six points lower must not take a neighbour's column.

    A results page prints 'Quarter ended | Year ended' over five date columns.  The text layer
    puts the first date on the line of the left 'Sr. No.' cell, so the date line arrives as four
    phrases plus one; each phrase owns the column it is printed over, never a block assigned in
    order (which put '31.12.2024' over the 31.03.2025 column on the Asian Paints results).
    """
    anchors = (330, 390, 450, 510, 570)
    dates = ("31.03.2025", "31.12.2024", "31.03.2024", "31.03.2025", "31.03.2024")
    lines = [(60, 60, "Consolidated Statement of Profit and Loss", 9),
             (60, 70, "Rs. in crore", 9),
             _center(370, 105, "Quarter ended"), _center(520, 105, "Year ended"),
             (40, 133, "Sr.", 8), (40, 141, "No.", 8),
             _right(anchors[0], 133, dates[0], 8)]
    lines += [_right(anchor, 127, text, 8) for anchor, text in zip(anchors[1:], dates[1:])]
    lines += [_right(anchor, 147, "Audited", 8) for anchor in anchors]
    y = 180
    for label, values in (("Revenue from operations",
                           ("7,157", "7,384", "7,538", "29,421", "31,094")),
                          ("Total expenses", ("6,000", "6,200", "6,300", "24,000", "25,000"))):
        lines.append((60, y, label, 9))
        lines += [_right(anchor, y, text) for anchor, text in zip(anchors, values)]
        y += 18
    cells = extract(_save(pdf_path, lines), "2025-05-08", None, "results")
    revenue = _by_label(cells, "Revenue from operations")
    assert {cell["col_no"]: cell["col_header"] for cell in revenue} == {
        0: "Quarter ended > 31.03.2025 > Audited",
        1: "Quarter ended > 31.12.2024 > Audited",
        2: "Quarter ended > 31.03.2024 > Audited",
        3: "Year ended > 31.03.2025 > Audited",
        4: "Year ended > 31.03.2024 > Audited"}
    assert {cell["col_no"]: cell["period_id"] for cell in revenue} == {
        0: _pid("2025-01-01", "2025-03-31"), 1: _pid("2024-10-01", "2024-12-31"),
        2: _pid("2024-01-01", "2024-03-31"), 3: _pid("2024-04-01", "2025-03-31"),
        4: _pid("2023-04-01", "2024-03-31")}


def test_a_year_ended_span_wins_over_the_bare_date(pdf_path):
    """Round 4, class 2: 'Year ended' (and its 'Vear' garble, 'twelve months') is FY, never a quarter.

    Only a bare date with no span text keeps the quarter rule.  HDFC AMC prints 'Vear Ended >
    March 31, 2025' (the text layer lost the Y) and was read as the March quarter.
    """
    anchors = (330, 480, 630)
    lines = [(60, 60, "Statement of Profit and Loss", 9), (60, 70, "Rs. in crore", 9),
             _center(310, 105, "Year Ended"), _center(460, 105, "Vear Ended"),
             _center(610, 105, "For the twelve months ended")]
    lines += [_right(anchor, 127, text, 8) for anchor, text in zip(
        anchors, ("31.03.2025", "31.03.2024", "31.03.2025"))]
    y = 180
    for label in ("Revenue from operations", "Total expenses"):
        lines.append((60, y, label, 9))
        lines += [_right(anchor, y, text) for anchor, text in zip(anchors, ("7,157", "7,384", "7,538"))]
        y += 18
    cells = extract(_save(pdf_path, lines), "2025-05-08", None, "results")
    revenue = _by_label(cells, "Revenue from operations")
    assert {cell["col_no"]: cell["period_id"] for cell in revenue} == {
        0: _pid("2024-04-01", "2025-03-31"), 1: _pid("2023-04-01", "2024-03-31"),
        2: _pid("2024-04-01", "2025-03-31")}


def test_segment_assets_and_liabilities_are_points_on_the_column_date(pdf_path):
    """Round 4, class 3: a balance item under 'Quarter ended' is a POINT at the column date.

    The Indian Hotels and Havells segment tables print 'Segment Assets' / 'Segment Liabilities'
    under a quarter heading; those rows are balances on the date, not the quarter's flow.
    """
    anchors = (320, 420, 520)
    lines = [(60, 60, "Statement of Profit and Loss", 9), (60, 70, "Rs. in crore", 9),
             _center(400, 105, "Quarter ended")]
    lines += [_right(anchor, 127, text, 8) for anchor, text in zip(
        anchors, ("30.09.2025", "30.06.2025", "31.03.2025"))]
    y = 180
    rows = (("Revenue from operations", ("1,500", "1,400", "1,300")),
            ("Total expenses", ("1,000", "950", "900")),
            ("Segment Assets", None),
            ("a) Hotels", ("4,100", "4,000", "3,900")),
            ("b) Food & Beverage", ("210", "205", "200")),
            ("Total Segment Assets", ("4,310", "4,205", "4,100")),
            ("Segment Liabilities", None),
            ("a) Hotels", ("700", "690", "680")))
    for label, values in rows:
        lines.append((60, y, label, 9))
        if values:
            lines += [_right(anchor, y, text) for anchor, text in zip(anchors, values)]
        y += 18
    cells = extract(_save(pdf_path, lines), "2025-11-01", None, "results")
    revenue = _by_label(cells, "Revenue from operations")
    assert {cell["period_id"] for cell in revenue} == {_pid("2025-07-01", "2025-09-30"),
                                                       _pid("2025-04-01", "2025-06-30"),
                                                       _pid("2025-01-01", "2025-03-31")}
    assets = [cell for cell in cells if (cell["row_label"] or "").startswith("Segment Assets")]
    liabilities = [cell for cell in cells if (cell["row_label"] or "").startswith(
        "Segment Liabilities")]
    assert assets and liabilities
    points = {_pid(None, day) for day in ("2025-09-30", "2025-06-30", "2025-03-31")}
    assert {cell["period_id"] for cell in assets} == points
    assert {cell["period_id"] for cell in liabilities} == points


def test_a_balance_printed_under_a_quarter_label_is_a_point(pdf_path):
    """Round 4, class 3: 'Total Equity' under 'Quarter Q1FY27' is the balance on 30.06.2026.

    Havells prints its balance sheet over quarter labels; the balance row must carry the
    quarter's end date as a POINT, while the revenue row keeps the quarter span.
    """
    anchors = (320, 400)
    lines = [(60, 60, "Balance Sheet", 9), (60, 70, "(Rs. in crore)", 9),
             _center(270, 105, "Q1FY27"), _center(380, 105, "Q1FY26")]
    y = 180
    for label, values in (("Revenue from operations", ("1,500", "1,400")),
                          ("EQUITY AND LIABILITIES > Total equity", ("9,476", "9,200"))):
        lines.append((60, y, label, 9))
        lines += [_right(anchor, y, text) for anchor, text in zip(anchors, values)]
        y += 18
    cells = extract(_save(pdf_path, lines), "2026-07-30", None, "deck")
    equity = [cell for cell in cells if "Total equity" in (cell["row_label"] or "")]
    assert equity and {cell["period_id"] for cell in equity} == {_pid(None, "2026-06-30"),
                                                                 _pid(None, "2025-06-30")}
    revenue = _by_label(cells, "Revenue from operations")
    assert revenue and {cell["period_id"] for cell in revenue} == {_pid("2026-04-01", "2026-06-30"),
                                                                   _pid("2025-04-01", "2025-06-30")}


def test_rows_that_name_their_own_unit_keep_scale_one(pdf_path):
    """Round 4, class 4: a per-tonne / per-user row is not read at the page's crore scale.

    'Overall Average Realization' is Rs per tonne, 'RevPAR in Rs' is Rs per room night; both were
    tagged 'Rs crore' with a 1e7 scale.  The page's money rows keep the crore scale.
    """
    anchors = (320, 420)
    lines = [(60, 60, "Investor Presentation", 9), (60, 70, "Rs. in crore", 9),
             _center(370, 105, "Q2 FY27")]
    lines += [_right(anchor, 127, text, 8) for anchor, text in zip(anchors, ("Jun-25", "Sep-25"))]
    y = 180
    rows = (("Overall Average Realization", ("1,647.24", "1,600.00")),
            ("Price (In Rs./Te.)", ("1,549.63", "1,524.15")),
            ("EBITDA per tonne", ("450.00", "440.00")),
            ("Average Revenue Per User (ARPU)", ("259", "262")),
            ("Revenue from operations", ("7,157", "7,384")))
    for label, values in rows:
        lines.append((60, y, label, 9))
        lines += [_right(anchor, y, text) for anchor, text in zip(anchors, values)]
        y += 18
    cells = extract(_save(pdf_path, lines), "2025-11-01", None, "deck")
    for label in ("Overall Average Realization", "Price (In Rs./Te.)", "EBITDA per tonne",
                  "Average Revenue Per User (ARPU)"):
        found = _by_label(cells, label)
        assert found and all(cell["scale"] == 1.0 and cell["unit_text"] == "Rs" for cell in found), label
        assert found[0]["value"] == float(found[0]["value_text"].replace(",", ""))
    money = _by_label(cells, "Revenue from operations")
    assert money and all(cell["scale"] == CRORE and cell["unit_text"] == "Rs crore"
                         for cell in money)
    assert label_unit("RevPAR in ₹ ( LFL )") == ("Rs", 1.0)
    assert label_unit("ARR (Rs)") == ("Rs", 1.0)
    assert label_unit("Revenue per key") == ("Rs", 1.0)


def test_a_measure_group_header_is_carried_into_the_column_header(pdf_path):
    """Round 4, class 5: a 'REVENUE | EBITDA | EBITDA MARGIN' group row names the cell's measure.

    Indian Hotels' legal-entity deck prints the measure over its period sub-columns; without the
    group row 'UOH Inc. - USA 19' cannot be told from the same entity's 236 revenue.
    """
    anchors = (340, 400, 460, 520, 580, 640)
    periods = ("Q1FY27", "Q1FY26", "Q1FY27", "Q1FY26", "Q1FY27", "Q1FY26")
    lines = [(60, 60, "Key legal entities", 9), (60, 72, "(Rs. in crore)", 9),
             (60, 100, "Legal Entities", 10),
             _center(340, 100, "REVENUE"), _center(460, 100, "EBITDA"),
             _center(580, 100, "EBITDA MARGIN")]
    lines += [_center(anchor - 30, 115, text, 8) for anchor, text in zip(anchors, periods)]
    lines.append((60, 150, "UOH Inc. - USA", 9))
    lines += [_right(anchor, 150, text) for anchor, text in zip(
        anchors, ("204", "236", "10", "19", "4.8%", "7.8%"))]
    lines.append((60, 168, "IHG - UK", 9))
    lines += [_right(anchor, 168, text) for anchor, text in zip(
        anchors, ("1,500", "1,400", "420", "380", "28.0%", "27.1%"))]
    cells = extract(_save(pdf_path, lines), "2025-08-01", None, "deck")
    usa = _by_label(cells, "UOH Inc. - USA")
    assert {cell["col_no"]: cell["col_header"] for cell in usa} == {
        0: "measure=REVENUE > Q1FY27", 1: "measure=REVENUE > Q1FY26",
        2: "measure=EBITDA > Q1FY27", 3: "measure=EBITDA > Q1FY26",
        4: "measure=EBITDA MARGIN > Q1FY27", 5: "measure=EBITDA MARGIN > Q1FY26"}
    assert {cell["period_id"] for cell in usa} == {
        _pid("2026-04-01", "2026-06-30"), _pid("2025-04-01", "2025-06-30")}
    assert [cell["value"] for cell in usa if cell["col_no"] == 2] == [10.0 * CRORE]


def test_garbled_row_labels_are_not_stored(pdf_path):
    """Round 4, class 6: 'St', a punctuation-only label and a label holding a value are dropped.

    Coal India prints 'St' as a row label, Apollo Tyres prints '-------' above its rows and the
    Adani Ports text layer puts a printed figure ('CT2, Yes 529.40') in the label column.
    """
    anchors = (320, 420)
    lines = [(60, 60, "Statement of Profit and Loss", 9), (60, 70, "Rs. in crore", 9),
             _center(370, 105, "Quarter ended")]
    lines += [_right(anchor, 127, text, 8) for anchor, text in zip(anchors, ("30.09.2025", "30.06.2025"))]
    y = 180
    rows = (("Revenue from operations", ("7,157", "7,384")),
            ("St", ("195", "531")),
            ("-------", None),
            ("Depreciation", ("269", "224")),
            ("CT2, Yes 529.40", ("317.47", "846.87")),
            ("Total income", ("7,330", "7,644")))
    for label, values in rows:
        lines.append((60, y, label, 9))
        if values:
            lines += [_right(anchor, y, text) for anchor, text in zip(anchors, values)]
        y += 18
    cells = extract(_save(pdf_path, lines), "2025-11-01", None, "results")
    labels = {cell["row_label"] for cell in cells}
    assert "Depreciation" in labels and len(_by_label(cells, "Depreciation")) == 2
    assert not any(label in ("St", "-------") or "529.40" in label for label in labels)
    assert not any("St" == label.split(" > ")[-1] for label in labels)


def test_six_months_ended_is_h1_not_the_quarter(pdf_path):
    """Round 5, class 1: a '6 months ended' span over a date column is H1, like 'Half year'.

    Titan prints '6 months ended > 30-09-2025' (the text layer's numeral, not 'Six'); the span
    word must win over the bare-date quarter rule, exactly as 'Half year ended' does.
    """
    anchors = (330, 480)
    lines = [(60, 60, "Statement of Profit and Loss", 9), (60, 70, "Rs. in crore", 9),
             _center(285, 105, "6 months ended"), _center(410, 105, "Half year ended")]
    lines += [_right(anchor, 127, text, 8) for anchor, text in zip(
        anchors, ("30.09.2025", "30.09.2024"))]
    y = 180
    for label, values in (("Revenue from operations", ("7,157", "7,384")),
                          ("Total income", ("7,330", "7,644"))):
        lines.append((60, y, label, 9))
        lines += [_right(anchor, y, text) for anchor, text in zip(anchors, values)]
        y += 18
    cells = extract(_save(pdf_path, lines), "2025-11-01", None, "results")
    found = _by_label(cells, "Revenue from operations")
    assert {cell["period_id"] for cell in found} == {
        _pid("2025-04-01", "2025-09-30"), _pid("2024-04-01", "2024-09-30")}


def test_currency_in_the_label_beats_the_page_unit(pdf_path):
    """Round 5, class 2: a label's own currency wins over the page's crore scale.

    'Average Revenue Per User (ARPU) US$' is USD at scale 1, '(US$ Mn)' is USD millions, and a
    section prefix 'Revenue in ₹ Cr' names a crore scale ('Marine' was stored as bare 'Rs').
    """
    assert label_unit("Average Revenue Per User (ARPU) US$") == ("USD", 1.0)
    assert label_unit("(US$ Mn)") == ("USD million", 1e6)
    assert label_unit("Revenue in ₹ Cr") == ("Rs crore", CRORE)
    anchors = (330, 430)
    lines = [(60, 60, "Investor Presentation", 9), (60, 70, "Rs. in crore", 9),
             _center(380, 105, "Q2 FY27")]
    lines += [_right(anchor, 127, text, 8) for anchor, text in zip(anchors, ("Sep-25", "Jun-25"))]
    y = 180
    rows = (("Revenue from operations", ("6,417", "6,100")),
            ("Revenue in ₹ Cr", None),
            ("Marine", ("190", "180")),
            ("Average Revenue Per User (ARPU) US$", ("2.9", "2.8")))
    for label, values in rows:
        lines.append((60, y, label, 9))
        if values:
            lines += [_right(anchor, y, text) for anchor, text in zip(anchors, values)]
        y += 18
    cells = extract(_save(pdf_path, lines), "2025-11-01", None, "deck")
    marine = _by_label(cells, "Marine")
    assert marine and all(cell["unit_text"] == "Rs crore" and cell["scale"] == CRORE
                          for cell in marine)
    arpu = _by_label(cells, "ARPU")
    assert arpu and all(cell["unit_text"] == "USD" and cell["scale"] == 1.0 for cell in arpu)
    revenue = _by_label(cells, "Revenue from operations")
    assert revenue and all(cell["unit_text"] == "Rs crore" for cell in revenue)


def test_a_bare_ratio_label_takes_its_line_item_as_parent(pdf_path):
    """Round 5, class 3: 'as a % of NR' carries the line item printed above it.

    Havells prints each line item and, under it, a bare 'as a % of NR'; without the parent the
    percentage cannot be told from any other line's percentage (the printed 'Less:' is dropped).
    """
    anchors = (330, 430)
    lines = [(60, 60, "Investor Presentation", 9), (60, 70, "(In Rs crores)", 9),
             _center(380, 105, "Q4 FY25")]
    lines += [_right(anchor, 127, text, 8) for anchor, text in zip(anchors, ("Mar", "Dec"))]
    y = 180
    rows = (("Net Revenue (NR)", ("6,532", "5,434")),
            ("Contribution", ("1,311", "1,117")),
            ("as a % of NR", ("20.1%", "20.6%")),
            ("Less: Advertising & Sales Promotion", ("142", "132")),
            ("as a % of NR", ("2.2%", "2.4%")),
            ("EBITDA", ("761", "637")),
            ("as a % of NR", ("11.6%", "11.7%")))
    for label, values in rows:
        lines.append((77 if label.startswith("as a %") else 60, y, label, 9))
        lines += [_right(anchor, y, text) for anchor, text in zip(anchors, values)]
        y += 18
    cells = extract(_save(pdf_path, lines), "2025-05-08", None, "deck")
    ratios = [cell for cell in cells if (cell["row_label"] or "").endswith("as a % of NR")]
    assert {cell["row_label"] for cell in ratios} == {
        "Contribution > as a % of NR",
        "Advertising & Sales Promotion > as a % of NR",
        "EBITDA > as a % of NR"}


def test_a_label_shares_the_top_edge_of_its_numbers(pdf_path):
    """Round 5, class 4: a tall label joins the numbers printed on the same baseline.

    On the Coal India deck the label box is taller than its figures, so its y-centre sits nearer
    the row below; the row is the one whose numbers share its top edge, not the nearest centre.
    """
    words = [(300, 80, 340, 92, "1,000"), (400, 80, 440, 92, "2,000"),
             (50, 100, 120, 124, "CMPDIL"),
             (373, 100, 413, 110, "195"), (500, 100, 539, 110, "177"),
             (373, 120, 413, 132, "52"), (500, 120, 539, 132, "79")]
    rows = _rows_of([tuple(word) for word in words])
    labels = [" ".join(token[4] for token in row) for row in rows]
    assert labels == ["1,000 2,000", "CMPDIL 195 177", "52 79"]

    anchors = (330, 430)
    lines = [(60, 60, "Coal India Limited", 9), (60, 70, "(Rs. in crore)", 9),
             _center(380, 105, "H1 26-27")]
    lines += [_right(anchor, 127, text, 8) for anchor, text in zip(anchors, ("30.09.2025",
                                                                             "30.09.2024"))]
    y = 180
    for label, values in (("CIL St (Excl. Dividend)", ("205", "195")), ("MCL", ("4,881", "4,574"))):
        lines.append((60, y, label, 9))
        lines += [_right(anchor, y, text) for anchor, text in zip(anchors, values)]
        y += 18
    cells = extract(_save(pdf_path, lines), "2025-11-01", None, "deck")
    assert "CIL St (Excl. Dividend)" in {cell["row_label"] for cell in cells}


def test_garbled_labels_are_flagged_and_keep_their_value(pdf_path):
    """Round 5, class 5: >30% of a label's letters in non-words marks it 'text_layer;garbled'.

    A broken text layer prints 'l:Jnallocable / el' and 'Financial riabilities'; the cell is
    kept (the value is printed right) with the method flagged so a reader can skip the label.
    """
    anchors = (330, 430)
    lines = [(60, 60, "Statement of Profit and Loss", 9), (60, 70, "Rs. in crore", 9),
             _center(380, 105, "Q4 FY25")]
    lines += [_right(anchor, 127, text, 8) for anchor, text in zip(anchors, ("Mar", "Dec"))]
    y = 180
    rows = (("Revenue from operations", ("6,532", "5,434")),
            ("l:Jnallocable / el", ("12", "11")),
            ("Financial riabilities", ("300", "290")),
            ("Total", ("6,844", "5,735")))
    for label, values in rows:
        lines.append((60, y, label, 9))
        lines += [_right(anchor, y, text) for anchor, text in zip(anchors, values)]
        y += 18
    cells = extract(_save(pdf_path, lines), "2025-05-08", None, "results")
    broken = [cell for cell in cells
              if cell["row_label"] in ("l:Jnallocable / el", "Financial riabilities")]
    assert broken and all(";garbled" in cell["method"] for cell in broken)
    assert all(cell["value"] is not None for cell in broken)
    clean = _by_label(cells, "Revenue from operations")
    assert clean and all(cell["method"] == "text_layer" for cell in clean)


def test_a_decimal_tail_split_by_the_text_layer_merges(pdf_path):
    """The text layer cuts the decimal tail off a figure ('7,601.5' + '1', '2,016' + '32')."""
    anchors = (330, 430)
    lines = [(60, 60, "Statement of Profit and Loss", 9), (60, 70, "Rs. in crore", 9),
             _center(380, 105, "Q2 FY27")]
    lines += [_right(anchor, 127, text, 8) for anchor, text in zip(anchors, ("Jun-26", "Jun-25"))]
    rows = (("Revenue from operations", "7,601.5", "1", "6,532.00"),
            ("Finance costs", "2,016", "32", "1,900.00"))
    y = 180
    for label, left_text, tail, right in rows:
        lines.append((60, y, label, 9))
        left = _right(anchors[0], y, left_text)
        lines.append(left)
        lines.append((left[0] + pymupdf.get_text_length(left_text, fontname="helv", fontsize=9)
                      + 2.0, y, tail, 9))
        lines.append(_right(anchors[1], y, right))
        y += 18
    cells = extract(_save(pdf_path, lines), "2026-08-01", None, "results")
    assert {cell["value_text"] for cell in _by_label(cells, "Revenue")} == {"7,601.51", "6,532.00"}
    assert {cell["value_text"] for cell in _by_label(cells, "Finance costs")} == {"2,016.32",
                                                                                "1,900.00"}


def test_as_on_split_across_a_header_segment_is_a_point():
    """'As > on > 30.06.2025' is the balance-sheet as-at header, not a quarter."""
    assert period_from_header("As > on > 30.06.2025", "2025-08-01", "results") == "/2025-06-30"


def test_cell_sample_writes_a_seeded_csv():
    directory = Path(f".tmp/t132-store-{os.getpid()}-{os.urandom(4).hex()}")
    directory.mkdir()
    try:
        (directory / "company").mkdir()
        conn = sqlite3.connect(directory / "company" / "INE000000000.db")
        schema.create(conn)
        conn.execute("INSERT INTO doc (doc_key, sha256, doc_type, source_key) "
                     "VALUES ('d1', 'x', 'deck', '.tmp/missing.pdf')")
        conn.execute(
            "INSERT INTO table_cell (doc_key, page, table_no, row_no, col_no, row_label, "
            "col_header, value_text, value, unit_text, scale, method) "
            "VALUES ('d1', 3, 0, 0, 0, 'Revenue', 'Q2 FY27', '6,417', 64170000000.0, "
            "'Rs crore', 10000000.0, 'text_layer')")
        conn.execute(
            "INSERT INTO table_cell (doc_key, page, table_no, row_no, col_no, row_label, "
            "value_text, value, method) "
            "VALUES ('d1', 3, 0, 1, 0, 'Other', '-', NULL, 'text_layer')")
        conn.commit()
        conn.close()
        cells = cell_sample.load_cells(directory, "deck")
        assert len(cells) == 1                       # the NULL-value row is not sampled
        out = directory / "sample.csv"
        rows = cell_sample.write_sample(cells, out, n=100, seed=9)
        assert len(rows) == 1 and rows[0]["label"] == "Revenue"
        lines = out.read_text(encoding="utf-8").splitlines()
        assert lines[0] == ("doc,page,label,header,period_id,value_text,unit_text,scale,"
                            "value,method,snippet")
        assert lines[1].startswith("d1,3,Revenue,Q2 FY27,")
    finally:
        shutil.rmtree(directory, ignore_errors=True)


# ---------------------------------------------------------------- round 6 defect classes


def test_a_rows_own_unit_cell_sets_the_scale(pdf_path):
    """Round 6, class 1: the row's unit cell beats a bare currency in the label.

    Bharati Airtel prints 'EBIT | Rs Mn | 680,996' under 'Consolidated Financials (Rs Mn)';
    a bare 'Rs' label must never mean scale 1.  A row's own unit cell wins, then the title,
    and with no scale word printed anywhere the scale is NULL, never 1.
    """
    anchors = (330, 430)
    lines = [(60, 50, "Consolidated Financials (Rs Mn)", 9),
             _center(380, 70, "Full Year Ended"),
             _right(anchors[0], 85, "31.03.2026", 8), _right(anchors[1], 85, "31.03.2025", 8)]
    rows = (("EBIT", "Rs", "Mn", ("680,996", "569,567")),
            ("Total Assets", "₹", "Cr", ("99,686", "1,14,763")))
    y = 140
    for label, currency, scale, values in rows:
        lines += [(60, y, label, 9), (250, y, currency, 9), (262, y, scale, 9)]
        lines += [_right(anchor, y, text) for anchor, text in zip(anchors, values)]
        y += 18
    cells = extract(_save(pdf_path, lines), "2026-05-01", None, "results")
    ebit = _by_label(cells, "EBIT")
    assert ebit and all(cell["unit_text"] == "Rs million" and cell["scale"] == 1e6
                        for cell in ebit)
    assets = _by_label(cells, "Total Assets")
    assert assets and all(cell["unit_text"] == "Rs crore" and cell["scale"] == CRORE
                          for cell in assets)

    lines = [(60, 50, "Segment results", 9),
             _center(380, 70, "Quarter Ended"),
             _right(anchors[0], 85, "30.06.2026", 8), _right(anchors[1], 85, "31.03.2026", 8),
             (60, 140, "Other income US$", 9), _right(anchors[0], 140, "190", 8),
             _right(anchors[1], 140, "180", 8),
             (60, 158, "Revenue", 9), _right(anchors[0], 158, "1,900", 8),
             _right(anchors[1], 158, "1,800", 8)]
    cells = extract(_save(pdf_path, lines), "2026-08-01", None, "results")
    other = _by_label(cells, "Other income")
    assert other and all(cell["unit_text"] is None and cell["scale"] is None
                         and cell["value"] is None for cell in other)


def test_the_nearest_table_note_overrides_the_page_unit(pdf_path):
    """Round 6, class 2: 'Amount in US$ Mn, except ratios' over its table wins.

    The page default is Rs crore; the table note says US$ Mn, so Bharati Airtel's
    'Access charges' 61 is USD 61 million, not Rs 61 million.
    """
    anchors = (330, 430)
    lines = [(60, 50, "(Rs. in crore)", 9),
             (60, 70, "Africa: In USD Constant Currency", 9),
             (60, 82, "Amount in US$ Mn, except ratios", 8),
             _center(380, 100, "Quarter Ended"),
             _right(anchors[0], 115, "Mar-26", 8), _right(anchors[1], 115, "Jun-25", 8)]
    y = 150
    for label, values in (("Total revenues", ("1,610", "1,593")),
                          ("Access charges", ("61", "69"))):
        lines.append((60, y, label, 9))
        lines += [_right(anchor, y, text) for anchor, text in zip(anchors, values)]
        y += 18
    cells = extract(_save(pdf_path, lines), "2026-05-01", None, "results")
    access = _by_label(cells, "Access charges")
    assert access and all(cell["unit_text"] == "USD million" and cell["scale"] == 1e6
                          for cell in access)


def test_a_two_line_label_is_one_row(pdf_path):
    """Round 6, class 3: a wrapped label's tail belongs to its own row, never the next.

    'Cash profit from operations before Derivative &' + 'Exchange Fluctuations' is one
    label; '[Share capital + other equity]' printed under 'Net worth' finishes that row.
    """
    anchors = (480, 640)
    lines = [(60, 50, "Consolidated Financials (Rs Mn)", 9),
             _center(560, 70, "Quarter Ended"),
             _right(anchors[0], 85, "Jun-25", 8), _right(anchors[1], 85, "Mar-25", 8),
             (60, 140, "Cash profit from operations before Derivative &", 9),
             _right(anchors[0], 140, "227,871", 8), _right(anchors[1], 140, "221,795", 8),
             (60, 150, "Exchange Fluctuations", 9),
             (60, 175, "Profit before tax", 9),
             _right(anchors[0], 175, "105,044", 8), _right(anchors[1], 175, "97,240", 8)]
    cells = extract(_save(pdf_path, lines), "2026-08-01", None, "results")
    cash = [cell for cell in cells if cell["value_text"] == "227,871"]
    assert cash and cash[0]["row_label"].endswith(
        "before Derivative & Exchange Fluctuations")
    profit = [cell for cell in cells if cell["value_text"] == "105,044"]
    assert profit and "Exchange Fluctuations" not in profit[0]["row_label"]

    lines = [(60, 50, "Standalone Balance Sheet", 9),
             _center(380, 70, "As at"),
             _right(anchors[0], 85, "31.03.2026", 8), _right(anchors[1], 85, "31.03.2025", 8),
             (60, 140, "Net worth (~ Million)", 9),
             _right(anchors[0], 140, "118,965.60", 8), _right(anchors[1], 140, "106,720.53", 8),
             (60, 145, "[Share capital + other equity]", 9),
             (60, 165, "Total equity", 9),
             _right(anchors[0], 165, "1,00,000", 8), _right(anchors[1], 165, "90,000", 8)]
    cells = extract(_save(pdf_path, lines), "2026-05-01", None, "results")
    worth = _by_label(cells, "Net worth")
    assert worth and all("[Share capital + other equity]" in cell["row_label"]
                         for cell in worth)
    assert worth and all(cell["unit_text"] == "Rs million" for cell in worth)


def test_a_measure_group_names_only_the_columns_it_covers(pdf_path):
    """Round 6, class 4: 'Q-on-Q Growth' over one growth column never names a level column.

    Bharati Airtel prints the level columns Mar-25 / Jun-24 around a 'Q-on-Q Growth'
    column; the level cell 992,465 is the quarter's level, not a growth.
    """
    lines = [(60, 50, "Customers - Consolidated", 9),
             (400, 93, "Q-on-Q", 9), (494, 93, "Y-on-Y", 9),
             (133, 98, "Parameters", 8), (264, 98, "Unit", 8),
             (307, 98, "Jun-25", 8), (351, 98, "Mar-25", 8), (443, 98, "Jun-24", 8),
             (397, 103, "Growth", 9), (489, 103, "Growth", 9),
             (264, 115, "000's", 8),
             (60, 120, "Total Mobile Broadband Base stations", 9),
             _right(328, 120, "999,933", 8), _right(374, 120, "992,465", 8),
             _right(417, 120, "7,468", 8), _right(464, 120, "947,377", 8),
             _right(509, 120, "52,556", 8),
             (60, 140, "Network towers", 9),
             _right(328, 140, "377,439", 8), _right(374, 140, "375,146", 8),
             _right(417, 140, "1,831", 8), _right(464, 140, "324,498", 8),
             _right(509, 140, "15,362", 8)]
    cells = extract(_save(pdf_path, lines), "2026-08-01", None, "results")
    level = [cell for cell in cells if cell["value_text"] == "992,465"]
    assert level and "measure=" not in (level[0]["col_header"] or "")
    assert level and level[0]["period_id"] == _pid("2025-01-01", "2025-03-31")
    level = [cell for cell in cells if cell["value_text"] == "947,377"]
    assert level and "measure=" not in (level[0]["col_header"] or "")


def test_a_split_period_label_and_a_point_under_a_quarter(pdf_path):
    """Round 6, class 5: 'H1 > FY27' is the half year, not the full year.

    Pidilite prints 'H1' over 'FY27'; a segment liability under 'For the Quarter ended'
    is a POINT and keeps its 'Segment Liabilities' parent.
    """
    anchors = (330, 430)
    # 'H1' over 'FY27' is the half of FY27, never the full year.
    assert period_from_header("H1 > FY27") == _pid("2026-04-01", "2026-09-30")
    assert period_from_header("Q2 > FY27") == _pid("2026-07-01", "2026-09-30")
    assert period_from_header("9M > FY26") == _pid("2025-04-01", "2025-12-31")
    lines = [(60, 50, "Segment information", 9),
             _center(380, 70, "For the Quarter ended"),
             _right(anchors[0], 85, "30.09.2025", 8), _right(anchors[1], 85, "30.06.2025", 8),
             (60, 120, "Segment Assets", 9),
             _right(anchors[0], 120, "1,245.52", 8), _right(anchors[1], 120, "1,329.74", 8),
             (60, 140, "4 Segment Liabilities", 9),
             (75, 160, "a) Consumer & Bazaar", 9),
             _right(anchors[0], 160, "2690.32", 8), _right(anchors[1], 160, "2659.40", 8),
             (75, 180, "b) Business to Business", 9),
             _right(anchors[0], 180, "824.89", 8), _right(anchors[1], 180, "841.65", 8)]
    cells = extract(_save(pdf_path, lines), "2026-10-28", None, "results")
    consumer = [cell for cell in cells if cell["value_text"] == "2690.32"]
    assert consumer and "Segment Liabilities" in consumer[0]["row_label"]
    assert consumer and consumer[0]["period_id"] == _pid(None, "2025-09-30")


def test_spaced_digits_in_a_header_still_parse(pdf_path):
    """Round 6, class 6: '3 1.03 .2025' is 31.03.2025, not a lost column.

    Asian Paints prints the dates with the digits spaced by the text layer; each column
    keeps its own date, so 187.11 is the quarter ended 31.03.2024 (Q4 FY24).
    """
    lines = [(60, 50, "Statement of Consolidated Financial Results", 9),
             _center(545, 70, "Quarter Ended"), _center(720, 70, "Year Ended"),
             (520, 90, "3", 8), (530, 90, "1.03", 8), (552, 90, ".2025", 8),
             (615, 90, "3", 8), (625, 90, "1.03", 8), (647, 90, ".2", 8),
             (660, 90, "0", 8), (668, 90, "24", 8),
             (700, 90, "3", 8), (710, 90, "1.12.2024", 8)]
    y = 140
    for label, values in (("Other income", ("187.11", "572.61", "687.96")),
                          ("Revenue from operations", ("8,701.46", "33,797.36", "35,382.12"))):
        lines.append((60, y, label, 9))
        for anchor, text in zip((560, 660, 730), values):
            lines.append(_right(anchor, y, text))
        y += 18
    assert _squash_digits("3 1.03 .2025") == "31.03.2025"
    assert _squash_digits("3 1.03 .2 0 24") == "31.03.2024"
    assert _squash_digits("2024 2025 2026") == "2024 2025 2026"   # a year row is not a date
    merged = _merge_date_phrases([
        {"x0": 520.0, "x1": 528.0, "text": "3"},
        {"x0": 530.0, "x1": 556.0, "text": "1.03"},
        {"x0": 560.0, "x1": 585.0, "text": ".2025"},
        {"x0": 700.0, "x1": 708.0, "text": "3"},
        {"x0": 710.0, "x1": 748.0, "text": "1.12.2024"}])
    assert [phrase["text"] for phrase in merged] == ["31.03.2025", "31.12.2024"]
    assert period_from_header("Quarter Ended > 31.03.2024") == _pid("2024-01-01", "2024-03-31")
    cells = extract(_save(pdf_path, lines), "2026-05-01", None, "results")
    other = [cell for cell in cells if cell["row_label"] == "Other income"]
    assert len({cell["period_id"] for cell in other}) >= 2


def test_a_label_printed_below_its_figures_stays_with_its_own_row(pdf_path):
    """Round 6, class 7: columns of labels and figures pair by row, not by order.

    The Coal India deck prints 'Finance Costs' one line under its own figures and
    'Depreciation, Amortization and Impairment Expenses' over the next row's: the -290
    is Finance Costs' and the -670 is Depreciation's.
    """
    lines = [(60, 50, "Coal India Limited", 9),
             (60, 60, "Rs. in crore", 8),
             _center(380, 90, "H1 FY26"), _center(560, 90, "H1 FY25"),
             _right(646, 95, "Inc/Dec", 8), _right(762, 95, "Inc/Dec%", 8)]
    rows = ((120, "Employee Benefits Expense", 146, ("666", "552", "114", "21%")),
            (149, "Finance Costs", 175, ("4,682", "4,972", "-290", "-6%")),
            (179, "Depreciation, Amortization", 206, ("-2,935", "-2,266", "-670", "30%")))
    for label_y, label, numbers_y, values in rows:
        lines.append((60, label_y, label, 9))
        for anchor, text in zip((431, 547, 646, 762), values):
            lines.append(_right(anchor, numbers_y, text, 8))
    lines.append((60, 200, "and Impairment Expenses", 9))
    cells = extract(_save(pdf_path, lines), "2026-10-30", None, "deck")
    finance = [cell for cell in cells if cell["value_text"] == "-290"]
    assert finance and finance[0]["row_label"] == "Finance Costs"
    depreciation = [cell for cell in cells if cell["value_text"] == "-670"]
    assert depreciation and depreciation[0]["row_label"] == (
        "Depreciation, Amortization and Impairment Expenses")


def test_a_bullet_sentence_is_not_a_row_label(pdf_path):
    """Round 6, class 8: a slide bullet is prose, never a row name.

    Titan prints '• Growth was well- supported ...' beside a figure; it is not a row.
    """
    lines = [(60, 50, "EyeCare: Quarterly Business Performance", 9),
             _center(380, 70, "Q1FY27"), _center(500, 70, "Q1FY26"),
             (60, 120, "Total Income", 9),
             _right(380, 120, "289", 8), _right(500, 120, "238", 8),
             (60, 160, "• Growth was well- supported by calibrated marketing investments "
                       "driving multi-pair and multi-category consumer propositions", 9),
             (60, 180, "Domestic", 9),
             _right(380, 180, "285", 8), _right(500, 180, "234", 8)]
    cells = extract(_save(pdf_path, lines), "2026-08-07", None, "deck")
    assert cells
    assert not [cell for cell in cells if (cell["row_label"] or "").startswith("•")]
    assert [cell for cell in cells if (cell["row_label"] or "").endswith("Domestic")]


def test_a_bare_currency_unit_cell_keeps_its_own_currency(pdf_path):
    """Round 7, class 1: a bare 'US$' unit cell beside ARPU is USD at scale 1, never the page Rs.

    Bharati Airtel prints 'Average Revenue Per User (ARPU) | US$ | 2.5 | 2.5 | 2.4% | 2.2 |
    11.8%'; the page's unit is Rs, the row's own unit cell is US$.
    """
    lines = [(60, 40, "Human Resource Analysis", 9), (60, 50, "Rs. in crore", 9),
             _center(330, 80, "Dec-25", 8), _center(380, 80, "Sep-25", 8),
             _center(475, 80, "Dec-24", 8)]
    lines.append((54, 120, "Average Revenue Per User (ARPU)", 9))
    lines.append((280, 120, "US$", 9))
    for anchor, text in zip((330, 380, 475), ("2.50", "2.60", "2.20")):
        lines.append(_right(anchor, 120, text))
    lines.append((54, 150, "Total Revenue", 9))
    lines.append((280, 150, "US$", 9))
    lines.append(_right(330, 150, "500"))
    lines.append(_right(475, 150, "480"))
    cells = extract(_save(pdf_path, lines), "2026-02-05", None, "results")
    arpu = [cell for cell in cells if "ARPU" in (cell["row_label"] or "")]
    assert arpu and arpu[0]["unit_text"] == "USD" and arpu[0]["scale"] == 1.0
    assert arpu[0]["value"] == 2.5 and arpu[0]["period_id"] == _pid("2025-10-01", "2025-12-31")
    revenue = [cell for cell in cells if (cell["row_label"] or "").endswith("Total Revenue")]
    assert revenue and revenue[0]["unit_text"] == "USD" and revenue[0]["scale"] is None
    assert revenue[0]["value"] is None                # a bare currency is no scale


def test_a_period_header_spans_its_measure_columns(pdf_path):
    """Round 7, class 2: 'Q1 FY27' over Revenue | EBITDA | PAT carries both measure and period.

    Adani Ports' JV table prints the period once over three measure columns; every cell must
    say Revenue/EBITDA/PAT and its own quarter.
    """
    lines = [(60, 40, "JV financial performance (in Rs Cr)", 9)]
    lines += [_center(430, 90, "Q1 FY27", 8), _center(705, 90, "Q1 FY26", 8)]
    lines += [_center(380, 115, "Revenue", 8), _center(470, 115, "EBITDA", 8),
              _center(560, 115, "PAT", 8), _center(650, 115, "Revenue", 8),
              _center(740, 115, "EBITDA", 8), _center(800, 115, "PAT", 8)]
    lines += [(35, 140, "AECTPL, JV with MSC", 9)]
    for anchor, text in zip((330, 420, 510, 600, 690, 780),
                            ("72", "17", "(20)", "65", "18", "(11)")):
        lines.append(_right(anchor, 140, text))
    lines += [(35, 165, "APSEZ Consolidated", 9)]
    for anchor, text in zip((330, 420, 510, 600, 690, 780),
                            ("10,821", "6,541", "3,650", "9,126", "5,495", "3,311")):
        lines.append(_right(anchor, 165, text))
    cells = extract(_save(pdf_path, lines), "2026-07-29", None, "deck")
    aect = [cell for cell in cells if "AECTPL" in (cell["row_label"] or "")]
    assert {cell["col_no"]: cell["col_header"] for cell in aect} == {
        0: "measure=Revenue > Q1 FY27", 1: "measure=EBITDA > Q1 FY27",
        2: "measure=PAT > Q1 FY27", 3: "measure=Revenue > Q1 FY26",
        4: "measure=EBITDA > Q1 FY26", 5: "measure=PAT > Q1 FY26"}
    assert {cell["period_id"] for cell in aect} == {
        _pid("2026-04-01", "2026-06-30"), _pid("2025-04-01", "2025-06-30")}


def test_a_label_printed_inside_tall_figures_keeps_its_own_row(pdf_path):
    """Round 7, class 3: the Coal India deck prints the figures before the label in reading order.

    '2,752 2,289 463 20%' sits inside the tall 'Cost of Materials Consumed' box; the label must
    take its own figures, and Inc/Dec = later - earlier holds for each row.
    """
    lines = [(60, 40, "Rs. in crore", 9)]
    for centre, text in ((381, "Q2 26-27"), (489, "Q2 25-26"),
                         (596, "Inc/Dec"), (704, "Inc/Dec%")):
        lines.append(_center(centre, 90, text))
    lines.append((70, 181, "Cost of Materials Consumed", 9))
    for anchor, text in zip((431, 547, 646, 762), ("2,752", "2,289", "463", "20%")):
        lines.append(_right(anchor, 185, text, 14))
    lines.append((70, 210, "Changes in inventories", 9))
    for anchor, text in zip((431, 547, 646, 762), ("3,052", "1,331", "1,721", "129%")):
        lines.append(_right(anchor, 214, text, 14))
    cells = extract(_save(pdf_path, lines), "2026-10-30", None, "deck")
    materials = [cell for cell in cells if "Materials" in (cell["row_label"] or "")]
    changes = [cell for cell in cells if "inventories" in (cell["row_label"] or "")]
    assert materials and [cell["value_text"] for cell in materials] == ["2,752", "2,289", "463", "20%"]
    assert changes and [cell["value_text"] for cell in changes] == ["3,052", "1,331", "1,721", "129%"]
    assert materials[0]["value"] == 2752 * CRORE
    assert changes[0]["value"] == 3052 * CRORE


def test_a_header_merging_two_printed_dates_splits_by_position(pdf_path):
    """Round 7, class 4: 'YEAR ENDED > 31.03.2025 I 31.03.2024' is two column headers.

    Apollo Tyres prints the separator 'I' between its two year columns; 1,637.14 is FY25 and
    3,079.20 is FY24, never both FY24.
    """
    lines = [(60, 40, "Rs. Million", 9),
             _center(470, 80, "YEAR ENDED", 8),
             (439, 105, "31.03.2025 I 31.03.2024", 8)]
    lines.append((77, 160, "Tax expense a. Current tax", 9))
    lines.append(_right(451, 160, "1,637.14"))
    lines.append(_right(520, 160, "3,079.20"))
    lines.append((77, 180, "Deferred tax", 9))
    lines.append(_right(451, 180, "1,672.40"))
    lines.append(_right(520, 180, "3,746.72"))
    cells = extract(_save(pdf_path, lines), "2025-05-14", None, "results")
    years = [cell for cell in cells if "Current tax" in (cell["row_label"] or "")]
    assert {cell["period_id"] for cell in years} == {
        _pid("2024-04-01", "2025-03-31"), _pid("2023-04-01", "2024-03-31")}
    assert {cell["value_text"] for cell in years} == {"1,637.14", "3,079.20"}
    fy25 = [cell for cell in years if cell["period_id"] == _pid("2024-04-01", "2025-03-31")]
    assert fy25 and fy25[0]["value_text"] == "1,637.14"


def test_a_title_row_is_not_a_period_and_a_table_span_names_the_column(pdf_path):
    """Round 7, class 5: the slide title 'Q3 FY26 & 9M FY26 key financials' is not a header.

    Adani Ports p2 prints the title over 'Q3 FY26 | Q3 FY25 | YoY | 9M FY26 | 9M FY25 | YoY';
    27.2% is 9M FY25, not the title's Q3 FY26.
    """
    lines = [(60, 40, "Adani Ports results", 9),
             (90, 80, "Q3 FY26 & 9M FY26 key financials (consolidated)", 9),
             _center(160, 105, "Q3 FY26", 8), _center(240, 105, "Q3 FY25", 8),
             _center(320, 105, "YoY", 8), _center(400, 105, "9M FY26", 8),
             _center(480, 105, "9M FY25", 8), _center(560, 105, "YoY", 8)]
    lines.append((60, 140, "All-India market share", 9))
    for anchor, text in zip((200, 280, 360, 440, 520, 600),
                            ("26.4%", "27.0%", "-60", "27.4%", "27.2%", "-20")):
        lines.append(_right(anchor, 140, text))
    lines.append((60, 165, "Revenue", 9))
    for anchor, text in zip((200, 280, 360, 440, 520, 600),
                            ("9,705", "7,964", "22%", "27,998", "22,590", "24%")):
        lines.append(_right(anchor, 165, text))
    cells = extract(_save(pdf_path, lines), "2026-02-03", None, "deck")
    share = [cell for cell in cells if "market share" in (cell["row_label"] or "")]
    by_col = {cell["col_no"]: cell for cell in share}
    assert by_col[4]["value_text"] == "27.2%"
    assert by_col[4]["period_id"] == _pid("2024-04-01", "2024-12-31")
    assert {cell["col_header"] for cell in by_col.values()} == {
        "Q3 FY26", "Q3 FY25", "YoY", "9M FY26", "9M FY25", "YoY"}
    assert by_col[2]["period_id"] is None and by_col[2]["method"] == "text_layer;delta"


def test_cash_flow_columns_are_ordered_by_their_own_opening_cash(pdf_path):
    """Round 7, class 5: opening cash equal to the other column's closing cash is the later column.

    Havells prints Q1FY27 over FY26; when the header loses its span words both columns read the
    filing date's quarter, and the cash-flow cross-check must make the second column Q4FY26.
    """
    lines = [(60, 40, "Cash Flow (In Rs crores)", 9),
             _center(330, 80, "Quarter ended", 8), _center(470, 80, "Quarter ended", 8),
             (120, 105, "PBT", 9), _right(380, 105, "401"), _right(520, 105, "2,226"),
             (120, 125, "Depreciation", 9), _right(380, 125, "120"), _right(520, 125, "429"),
             (120, 165, "Cash & Cash Equivalent at beginning", 9),
             _right(380, 165, "2,351"), _right(520, 165, "3,353"),
             (120, 185, "Cash & Cash Equivalent at end", 9),
             _right(380, 185, "1,497"), _right(520, 185, "2,351")]
    cells = extract(_save(pdf_path, lines), "2026-07-17", None, "results")
    pbt = [cell for cell in cells if (cell["row_label"] or "").endswith("PBT")]
    assert {cell["col_no"]: cell["period_id"] for cell in pbt} == {
        0: _pid("2026-04-01", "2026-06-30"), 1: _pid("2026-01-01", "2026-03-31")}
    closing = [cell for cell in cells if "at end" in (cell["row_label"] or "")]
    assert closing and closing[0]["value_text"] == "1,497"


def test_bps_and_mmt_columns_keep_their_own_unit(pdf_path):
    """Round 7, class 6: a bps column is basis points and '(MMT)' is million tonnes, not money/count."""
    lines = [(60, 40, "Rs. in crore", 9),
             _center(300, 80, "Q1FY26", 8), _center(380, 80, "Q1FY27", 8),
             _center(470, 80, "YoY (bps)", 8)]
    lines += [(60, 120, "Domestic Businesses", 9), _right(320, 120, "12.2%"),
              _right(400, 120, "14.0%"), _right(490, 120, "189")]
    lines += [(60, 150, "GPWIS volume (MMT)", 9), _right(320, 150, "5.6"),
              _right(400, 150, "5.8"), _right(490, 150, "-5%")]
    cells = extract(_save(pdf_path, lines), "2026-08-07", None, "deck")
    bps = [cell for cell in cells if cell["value_text"] == "189"]
    assert bps and bps[0]["unit_text"] == "bps" and bps[0]["scale"] == 1.0
    assert bps[0]["method"] == "text_layer;delta" and bps[0]["period_id"] is None
    mmt = [cell for cell in cells if "GPWIS" in (cell["row_label"] or "")]
    assert mmt and mmt[0]["unit_text"] == "MMT" and mmt[0]["scale"] == 1.0


def test_a_roman_marker_starting_mid_label_splits_the_two_printed_rows(pdf_path):
    """Round 7, class 7: 'ii)' / 'ii,' starts its own printed row, never a wrap of the label above.

    Pidilite prints 'Less i) Finance Costs' then 'ii) Other Unallocable Expenditure net of' +
    'Unallocable Income'; Apollo prints 'hedging instruments in cash flow hedge' then
    'ii, Income tax effect'.
    """
    lines = [(60, 40, "Rs. in Crores", 9),
             _center(300, 70, "Q2FY27", 8), _center(470, 70, "Q2FY26", 8),
             (60, 95, "Segment Results", 9), (60, 120, "Less i) Finance Costs", 9),
             _right(380, 120, "7.24"), _right(520, 120, "8.10"),
             (60, 150, "ii) Otner Unallocable Expenditure net of", 9),
             (60, 170, "Unallocable Income", 9), _right(380, 170, "176.25"),
             _right(520, 170, "178.69")]
    cells = extract(_save(pdf_path, lines), "2026-10-28", None, "results")
    labels = {cell["row_label"] for cell in cells}
    assert any(label.endswith("Less i) Finance Costs") for label in labels)
    assert any("Unallocable Expenditure" in label and "Unallocable Income" in label
               for label in labels)
    assert not any("Finance Costs ii)" in label for label in labels)
    assert not _label_continues("instruments in cash flow hedge", "ii, Income tax effect")
    assert _label_continues("Cash profit from operations before Derivative &",
                            "Exchange Fluctuations")


def test_an_interleaved_sub_header_is_a_dimension(pdf_path):
    """Round 7, class 8: 'HDFC MF | Industry' under Mar-24 | Dec-24 | Mar-25 names the dimension.

    HDFC AMC p15 prints 15.9% under the Industry sub-column of Dec-24; the sub-header belongs
    to the cell or the HDFC MF value beside it cannot be told from the industry's.
    """
    lines = [(60, 40, "AUM by Segment - HDFC MF & Industry", 9),
             _center(319, 80, "Mar-24", 8), _center(488, 80, "Dec-24", 8),
             _center(658, 80, "Mar-25", 8)]
    for centre, text in ((300, "HDFC MF"), (380, "Industry"), (470, "HDFC MF"),
                         (550, "Industry"), (635, "HDFC MF"), (720, "Industry")):
        lines.append(_center(centre, 110, text))
    lines += [(176, 140, "Equity-oriented", 9)]
    for anchor, text in zip((319, 401, 490, 571, 660, 742),
                            ("63.0%", "54.3%", "64.9%", "57.0%", "63.8%", "55.9%")):
        lines.append(_right(anchor, 140, text))
    lines += [(176, 165, "Others", 9)]
    for anchor, text in zip((319, 401, 490, 571, 660, 742),
                            ("3.7%", "16.0%", "4.2%", "15.9%", "4.7%", "16.0%")):
        lines.append(_right(anchor, 165, text))
    cells = extract(_save(pdf_path, lines), "2025-04-17", None, "deck")
    others = [cell for cell in cells if (cell["row_label"] or "").endswith("Others")]
    by_col = {cell["col_no"]: cell for cell in others}
    assert len(by_col) == 6
    assert by_col[3]["value_text"] == "15.9%"
    assert by_col[3]["col_header"] == "dimension=Industry > Dec-24"
    assert by_col[2]["col_header"] == "dimension=HDFC MF > Dec-24"
    assert by_col[3]["period_id"] == _pid(None, "2024-12-31")

# ---------------------------------------------------------------- round 8 defect classes


def test_round8_step0a_ratios_header_right_of_the_figures_and_split_blocks(pdf_path):
    """Step 0a: the Coal India Key Financial Ratios table.

    The dates print left of the figure anchors and a 'Remarks' column prints past the right
    edge; the row lines split the block.  The header row must survive and every row keep its
    date (printed text: '30.09.25', '31.03.25', '30.09.24', 'Remarks').
    """
    lines = [(60, 40, "Key Financial Ratios", 12),
             (60, 60, "Ratios", 9),
             _right(330, 60, "30.09.25", 8), _right(480, 60, "31.03.25", 8),
             _right(630, 60, "30.09.24", 8), (800, 60, "Remarks", 8),
             (60, 100, "Debt Equity Ratio", 9),
             _right(320, 105, "0.13", 8), _right(470, 105, "0.09", 8),
             _right(620, 105, "0.07", 8),
             (60, 140, "Current Ratio", 9),
             _right(320, 145, "1.77", 8), _right(470, 145, "1.74", 8),
             _right(620, 145, "1.81", 8)]
    cells = extract(_save(pdf_path, lines), "2025-10-29", None, "results")
    debt = _by_label(cells, "Debt Equity Ratio")
    assert {cell["value_text"] for cell in debt} == {"0.13", "0.09", "0.07"}
    assert {cell["col_header"] for cell in debt} == {"30.09.25", "31.03.25", "30.09.24"}
    current = _by_label(cells, "Current Ratio")
    assert {cell["period_id"] for cell in current} == {
        _pid(None, "2025-09-30"), _pid(None, "2025-03-31"), _pid(None, "2024-09-30")}


def test_round8_step0b_a_growth_column_split_after_a_delta_word(pdf_path):
    """Step 0b: Indhotel p33 pairs its growth column with the row that owns it.

    Printed text: 'Less : Share of Non Controlling Interest' and the split tokens '(400' and
    'bps)' on Titan p43 / '-96%' in Indhotel's 'Var. vs FY24' column.
    """
    lines = [(60, 40, "CONSOLIDATED P&L Q4 & 12MFY25", 9),
             _center(383, 70, "Q4 FY24", 8), _center(461, 70, "Q4 FY25", 8),
             _center(535, 70, "Var. vs FY24", 8), _center(620, 70, "12M FY24", 8),
             _center(700, 70, "12M FY25", 8), _center(774, 70, "Var. vs FY24", 8),
             (60, 100, "Less : Share of Non Controlling Interest", 9),
             _right(403, 100, "(21)", 8), _right(500, 100, "(40)", 8),
             _right(589, 100, "-96%", 8), _right(672, 100, "(71)", 8),
             _right(753, 100, "(130)", 8), _right(833, 100, "-83%", 8),
             (60, 130, "Add: Share of Profit/(Loss) in Assoc. & JV's", 9),
             _right(403, 130, "45", 8), _right(500, 130, "23", 8),
             _right(589, 130, "-50%", 8), _right(672, 130, "129", 8),
             _right(753, 130, "77", 8), _right(833, 130, "-40%", 8)]
    cells = extract(_save(pdf_path, lines), "2025-05-05", None, "deck")
    deltas = [cell for cell in cells if cell["value_text"] in ("-96%", "-83%")]
    assert len(deltas) == 2
    assert {cell["method"] for cell in deltas} == {"text_layer;delta"}
    assert {cell["period_id"] for cell in deltas} == {None}
    assert all("Non Controlling Interest" in cell["row_label"] for cell in deltas)


def test_round8_step1_a_balance_is_a_point_and_a_flow_is_the_quarter(pdf_path):
    """Step 1: Bharti's 'Quarter ended / As of' columns hold both a flow and a balance.

    Printed text: 'Long term borrowings' 54,563 at Mar-26 is a POINT; 'Revenue from
    operations' under the same header is the quarter, never a point.
    """
    lines = [(60, 40, "Audited Consolidated Segment-wise Revenue, Results, Assets and "
                      "Liabilities as of and for the quarter ended June 30, 2026", 9),
             _center(380, 90, "Quarter ended / As of", 8),
             _right(380, 105, "March 31, 2026", 8), _right(520, 105, "June 30, 2026", 8),
             (60, 130, "Revenue from operations", 9),
             _right(380, 130, "9,167", 8), _right(520, 130, "9,126", 8),
             (60, 150, "Long term borrowings", 9),
             _right(380, 150, "54,563", 8), _right(520, 150, "54,744", 8)]
    cells = extract(_save(pdf_path, lines), "2026-08-04", None, "results")
    revenue = _by_label(cells, "Revenue from operations")
    assert {cell["period_id"] for cell in revenue} == {
        _pid("2026-01-01", "2026-03-31"), _pid("2026-04-01", "2026-06-30")}
    borrowings = _by_label(cells, "Long term borrowings")
    assert {cell["period_id"] for cell in borrowings} == {"/2026-03-31", "/2026-06-30"}
    assert {cell["value_text"] for cell in borrowings} == {"54,563", "54,744"}


def test_round8_step2_a_measure_section_is_the_row_label_never_the_column_measure(pdf_path):
    """Step 2 (round 9 correction): a measure printed as a row label stays a section parent.

    Printed text: '1. Segment Revenue' over the first group, '2. Segment Results' below it.
    Round 8 promoted either one to measure= on every column, which overwrote the second
    group's real measure; round 9 takes measure= only from header rows over the columns.
    """
    lines = [(60, 40, "Audited Consolidated Segment-wise Revenue and Results", 9),
             (60, 60, "(Rs in Millions)", 8),
             _right(380, 80, "Dec-25", 8), _right(520, 80, "Dec-24", 8),
             (60, 100, "1. Segment Revenue", 9),
             (60, 120, "- Mobile Services India", 9),
             _right(380, 120, "81,463", 8), _right(520, 120, "75,475", 8),
             (60, 150, "2. Segment Results", 9),
             (60, 170, "- Mobile Services India", 9),
             _right(380, 170, "46,097", 8), _right(520, 170, "70,811", 8)]
    cells = extract(_save(pdf_path, lines), "2026-02-05", None, "results")
    revenue = [cell for cell in cells if cell["value_text"] == "81,463"]
    results = [cell for cell in cells if cell["value_text"] == "46,097"]
    assert revenue and "measure=" not in revenue[0]["col_header"]
    assert results and "measure=" not in results[0]["col_header"]
    assert "Segment Revenue" in revenue[0]["row_label"]
    assert "Segment Results" in results[0]["row_label"]


def test_round8_step3_a_segment_title_is_the_parent_of_its_table(pdf_path):
    """Step 3: Bharti's 'Airtel Business' heading names every row of the table under it."""
    lines = [(60, 40, "Airtel Business", 11),
             (60, 60, "Amount in Rs Mn, except ratios", 8),
             (60, 80, "Quarter Ended", 8),
             _right(380, 95, "Dec-25", 8), _right(520, 95, "Sep-25", 8),
             (60, 120, "Total revenues", 9),
             _right(380, 120, "53,531", 8), _right(520, 120, "52,760", 8),
             (60, 140, "EBITDA", 9),
             _right(380, 140, "23,577", 8), _right(520, 140, "21,943", 8)]
    cells = extract(_save(pdf_path, lines), "2026-02-05", None, "results")
    assert {cell["row_label"] for cell in cells} == {
        "Airtel Business > Total revenues", "Airtel Business > EBITDA"}
    assert {cell["value_text"] for cell in cells
                    if cell["value_text"] in ("53,531", "52,760")} == {"53,531", "52,760"}


def test_round8_step4_a_short_row_is_aligned_by_the_printed_columns(pdf_path):
    """Step 4: Adani p12's exceptional-items row prints 3 values for 4 columns.

    Printed text: 'Exceptional items (refer note 8)' and '(24.41)'; the row arithmetic
    (3,556.34 - 24.41 = 3,531.93) puts (24.41) on the Q4FY25 column, not FY25.
    """
    lines = [(60, 40, "CONSOLIDATED FINANCIAL RESULTS FOR THE QUARTER ENDED JUNE 30, 2025", 8),
             (600, 40, "(₹ in crore)", 8),
             _center(384, 83, "Quarter Ended", 8), _center(524, 83, "Year Ended", 8),
             _center(340, 94, "June 30,", 8), _center(400, 94, "March 31,", 8),
             _center(480, 94, "June 30,", 8), _center(544, 94, "March 31,", 8),
             _center(340, 103, "2025", 8), _center(400, 103, "2025", 8),
             _center(480, 103, "2024", 8), _center(544, 103, "2025", 8),
             (40, 140, "Profit before exceptional items and tax", 9),
             _right(369, 140, "3,847.60", 8), _right(439, 140, "3,556.34", 8),
             _right(509, 140, "3,738.08", 8), _right(569, 140, "13,279.08", 8),
             (40, 165, "Exceptional items (refer note 8)", 9),
             _right(439, 165, "(24.41)", 8), _right(509, 165, "(145.43)", 8),
             _right(569, 165, "(249.46)", 8)]
    cells = extract(_save(pdf_path, lines), "2025-08-05", None, "results")
    exceptional = [cell for cell in cells if cell["value_text"] == "(24.41)"]
    assert len(exceptional) == 1
    assert round(exceptional[0]["value"] / 1e7, 2) == -24.41
    assert exceptional[0]["period_id"] == _pid("2025-01-01", "2025-03-31")


def test_round8_step5_units_scale_sign_and_junk(pdf_path):
    """Step 5: "in 000's" scales a count, a bare 'Bn' level is people, '(400 bps)' is -400.

    Printed text: "Volume* (in 000's)", 'Population Covered | Bn', '(400' + 'bps)'.
    """
    from reality_engine.v2.table_cells import _number
    assert _number("(400 bps)") == (-400.0, False)
    lines = [(60, 40, "4.1 Customers - Consolidated", 9),
             (60, 60, "Volume* (in 000's) RHS", 8),
             _right(380, 80, "Mar-26", 8), _right(520, 80, "Dec-25", 8),
             (60, 110, "Population Covered", 9), (280, 110, "Bn", 8),
             _right(380, 110, "2", 8), _right(520, 110, "2", 8),
             (60, 140, "Net additions", 9),
             _right(380, 140, "812", 8), _right(520, 140, "5,006", 8)]
    cells = extract(_save(pdf_path, lines), "2026-05-13", None, "results")
    population = _by_label(cells, "Population Covered")
    assert population and {cell["unit_text"] for cell in population} == {"count"}
    assert {cell["value"] for cell in population} == {2e9}
    additions = _by_label(cells, "Net additions")
    assert additions and {cell["scale"] for cell in additions} == {1000.0}


def test_round8_step5b_an_ocr_lost_decimal_is_junk_suspect(pdf_path):
    """Step 5b: Havells p15 prints 300.78 as '30078'; its column neighbours are '310.00'
    and '0.73', so the value is not stored and the cell is flagged.
    """
    lines = [(60, 40, "STATEMENT OF CONSOLIDATED FINANCIAL RESULTS", 9),
             (60, 50, "(Rs in Crore)", 8),
             _center(380, 80, "31-Mar-26", 8), _center(520, 80, "31-Dec-25", 8),
             (60, 110, "Total comprehensive income", 9),
             _right(380, 110, "724.03", 8), _right(520, 110, "310.00", 8),
             (60, 140, "Owners of the parent", 9),
             _right(380, 140, "723.06", 8), _right(520, 140, "30078", 8),
             (60, 170, "Non-controlling interest", 9),
             _right(380, 170, "0.33", 8), _right(520, 170, "(0.73)", 8)]
    cells = extract(_save(pdf_path, lines), "2026-04-22", None, "results")
    junk = [cell for cell in cells if cell["value_text"] == "30078"]
    assert len(junk) == 1
    assert junk[0]["value"] is None and "junk_suspect" in junk[0]["method"]
    assert round([cell for cell in cells
                  if cell["value_text"] == "724.03"][0]["value"] / 1e7, 2) == 724.03


def test_round8_step6_a_label_just_above_its_figures_keeps_its_own_row(pdf_path):
    """Step 6: Pidilite deck p28 prints values before labels, 3 points apart.

    Printed text: 'Staff Costs' 471, 'Other Expenses' 485, 'EBITDA' 2,071.
    """
    lines = [(60, 40, "EARNINGS SUMMARY - CONSOLIDATED", 9),
             (270, 60, "In Crs", 8),
             _right(359, 90, "FY26", 8), _right(418, 90, "FY27", 8),
             (60, 119, "Staff Costs", 9),
             _right(359, 122, "471", 8), _right(418, 122, "511", 8),
             (60, 139, "Other Expenses", 9),
             _right(359, 142, "485", 8), _right(418, 142, "566", 8),
             (60, 159, "EBITDA", 9),
             _right(359, 162, "851", 8), _right(418, 162, "878", 8)]
    cells = extract(_save(pdf_path, lines), "2026-10-28", None, "deck")
    by_value = {cell["value_text"]: cell for cell in cells}
    assert by_value["471"]["row_label"] == "Staff Costs"
    assert by_value["485"]["row_label"] == "Other Expenses"
    assert by_value["851"]["row_label"] == "EBITDA"


def test_round8_step7_a_merged_ratio_label_keeps_the_second_name(pdf_path):
    """Step 7: Coal India p16 prints 'Gross Profit Margin on Net Sales Net Profit Margin on
    Net Sales' as one label; the row's own name is the second ratio (33% is Net).
    """
    lines = [(60, 40, "Key Financial Ratios", 9),
             _right(380, 70, "30.06.24", 8), _right(520, 70, "31.03.24", 8),
             (60, 100, "Gross Profit Margin on Net Sales Net Profit Margin on Net Sales", 9),
             _right(380, 100, "43%", 8), _right(520, 100, "37%", 8),
             (60, 130, "Net Profit Margin on Net Sales", 9),
             _right(380, 130, "33%", 8), _right(520, 130, "28%", 8)]
    cells = extract(_save(pdf_path, lines), "2026-02-12", None, "results")
    merged = [cell for cell in cells if cell["value_text"] == "43%"]
    assert merged and merged[0]["row_label"].endswith("Net Profit Margin on Net Sales")
    assert [cell for cell in cells if cell["value_text"] == "33%"]


# ---------------------------------------------------------------- round 9 defect classes


def test_round9_step1_flow_words_beat_balance_words(pdf_path):
    """Step 1: the column's own period wins; a flow word beats an equity/inventory/cash word.

    Exact printed text: 'Return on Shareholder's Equity (Pre Tax) %', 'Inventory turnover
    ratio', 'Gain on investments at fair value through OCI', 'Loss on re-statement of foreign
    currency cash and cash equivalents', 'Net Loss on FVTOCI Equity Securities', 'Customer
    Base', 'Network Towers', 'Long term debt to working capital ratio'.
    """
    anchors = (340, 540)
    values = {
        "Return on Shareholder's Equity (Pre Tax) %": ("26.9%", "32.5%"),
        "Inventory turnover ratio (not annualised)": ("1.98", "2.01"),
        "Gain on investments at fair value through OCI": ("1,338", "1,500"),
        "Loss on re-statement of foreign currency cash and cash equivalents": ("31.14", "20"),
        "Net Loss on FVTOCI Equity Securities": ("(78.00)", "9"),
        "Customer Base": ("173,816", "175,000"),
        "Network Towers": ("35,961", "36,500"),
        "Co-locations": ("11,178", "11,500"),
        "Long term debt to working capital ratio": ("0.05", "0.06"),
    }
    lines = [(60, 40, "Consolidated Statement of Profit and Loss (Rs. in crore)", 9),
             _center(300, 70, "Quarter Ended"), _center(500, 70, "Year Ended")]
    lines += [_right(anchor, 95, text, 8) for anchor, text in zip(
        anchors, ("30.06.2025", "31.03.2026"))]
    y = 130
    for label, row_values in values.items():
        lines.append((60, y, label, 8))
        lines += [_right(anchor, y, text, 8) for anchor, text in zip(anchors, row_values)]
        y += 20
    cells = extract(_save(pdf_path, lines), "2025-08-01", None, "results")
    by_value = {}
    for cell in cells:
        by_value.setdefault(cell["value_text"], []).append(cell)
    quarter = by_value["26.9%"][0]
    assert quarter["period_id"] == _pid("2025-04-01", "2025-06-30")     # flow, quarter
    assert by_value["32.5%"][0]["period_id"] == _pid("2025-04-01", "2026-03-31")
    assert by_value["1.98"][0]["period_id"] == _pid("2025-04-01", "2025-06-30")
    assert by_value["1,338"][0]["period_id"] == _pid("2025-04-01", "2025-06-30")
    assert by_value["31.14"][0]["period_id"] == _pid("2025-04-01", "2025-06-30")
    assert by_value["(78.00)"][0]["period_id"] == _pid("2025-04-01", "2025-06-30")
    assert by_value["173,816"][0]["period_id"] == _pid(None, "2025-06-30")   # an operating count
    assert by_value["35,961"][0]["period_id"] == _pid(None, "2025-06-30")
    assert by_value["11,178"][0]["period_id"] == _pid(None, "2025-06-30")
    assert by_value["0.05"][0]["period_id"] == _pid(None, "2025-06-30")      # a balance ratio


def test_round9_step2_measure_only_from_header_rows(pdf_path):
    """Step 2: a measure comes from header rows over the columns, never from a row label.

    Printed text: 'I. INCOME' and '2. EXPENSES' in the label column; 'Quarter Ended' and
    'Year Ended' over the columns.
    """
    lines = [(60, 40, "Standalone Financial Results (Rs. in crore)", 9),
             _center(330, 70, "Quarter Ended"), _center(500, 70, "Year Ended")]
    lines += [_right(anchor, 95, text, 8) for anchor, text in zip(
        (370, 540), ("March 31, 2025", "March 31, 2025"))]
    lines += [(60, 130, "I. INCOME", 9),
              (60, 150, "Revenue from operations", 9),
              _right(370, 150, "901.22", 8), _right(540, 150, "3,498.03", 8),
              (60, 180, "2. EXPENSES", 9),
              (60, 200, "Employee benefits expense", 9),
              _right(370, 200, "96.83", 8), _right(540, 200, "388.25", 8)]
    cells = extract(_save(pdf_path, lines), "2025-05-01", None, "results")
    assert all("measure=" not in (cell["col_header"] or "") for cell in cells)
    revenue = [cell for cell in cells if cell["value_text"] == "901.22"][0]
    assert revenue["period_id"] == _pid("2025-01-01", "2025-03-31")
    assert "INCOME" in revenue["row_label"]
    expense = [cell for cell in cells if cell["value_text"] == "96.83"][0]
    assert "EXPENSES" in expense["row_label"]


HDFCAMC = Path("D:/RealityEngine/raw/pilot60_history/HDFCAMC/quarterly_results/"
               "b3a54a28-70e9-4df3-b531-5ae991f0d802.pdf")


@pytest.mark.skipif(not HDFCAMC.exists(), reason="HDFC AMC results are not on disk")
def test_round9_step2_hdfcamc_quarter_band_is_not_eaten():
    """Regression: HDFC AMC standalone results p6 keeps all five columns (91 cells, not 46).

    Round 8 dropped every quarter column when the 'I. INCOME' row was read as a measure; the
    values are 'Quarter Ended > March 31, > 2025' and 'Year Ended > March 31, > 2025'.
    """
    with pymupdf.open(str(HDFCAMC)) as document:
        cells = extract_page(document[5], 6, "2025-05-01", "results")
    assert len(cells) >= 85, f"quarter band lost: {len(cells)} cells"
    revenue = [cell for cell in cells if cell["value_text"] == "901.22"]
    assert revenue and revenue[0]["period_id"] == _pid("2025-01-01", "2025-03-31")
    assert "Quarter Ended" in revenue[0]["col_header"]
    assert not any((cell["col_header"] or "").startswith("measure=") for cell in cells)


def test_round9_step3_a_ratios_page_reads_halves_and_years(pdf_path):
    """Step 3: 'Key Financial Ratios' dated 30.09.25 / 31.03.25 / 30.09.24 in an H1 filing.

    Flow ratios are the half year / fiscal year, not a quarter; a balance ratio is a point.
    The remarks column is printed right of the figures.
    """
    lines = [(60, 40, "Key Financial Ratios", 12),
             (60, 60, "Ratios", 9), _right(330, 60, "30.09.25", 8),
             _right(480, 60, "31.03.25", 8), _right(630, 60, "30.09.24", 8),
             (800, 60, "Remarks wrt 31.03.25", 8),
             (60, 100, "Net Profit Margin on Net Sales", 9),
             _right(320, 105, "22%", 8), _right(470, 105, "28%", 8),
             _right(620, 105, "28%", 8),
             (800, 108, "Increase in Average Inventory", 8),
             (60, 140, "Debt Equity Ratio", 9),
             _right(320, 145, "0.13", 8), _right(470, 145, "0.09", 8),
             _right(620, 145, "0.07", 8),
             (800, 148, "Decrease in current Liabilities", 8)]
    cells = extract(_save(pdf_path, lines), "2025-10-29", None, "results")
    margin = {cell["col_header"]: cell for cell in cells if cell["value_text"] == "22%"}
    assert margin["30.09.25"]["period_id"] == _pid("2025-04-01", "2025-09-30")
    debt = {cell["value_text"]: cell for cell in cells if "Debt Equity Ratio" in
            (cell["row_label"] or "")}
    assert debt["0.13"]["period_id"] == _pid(None, "2025-09-30")
    assert all("Increase" not in (cell["row_label"] or "") for cell in cells)


def test_round9_step4_year_sequence_and_group_headers(pdf_path):
    """Step 4: FY22..FY26 + H1 FY27 map by position, and group headings own their columns.

    Adani's balance-sheet snapshot prints a year sequence; its port-volume tables print
    'Total | Dry (MMT) | Containers | Liquid (MMT)' over period pairs below.
    """
    # (a) a year sequence with a right-hand Insights column (a separate call-out row)
    sequence = [(60, 40, "Balance sheet snapshot", 9),
                (40, 70, "Particulars", 9), (150, 70, "Unit", 8)]
    for anchor, label in zip((320, 400, 480, 560, 640, 720),
                             ("FY22", "FY23", "FY24", "FY25", "FY26", "H1 FY27")):
        sequence.append(_right(anchor, 70, label, 8))
    sequence += [(40, 100, "Gross Fixed Assets (Excl. CWIP)", 9), (150, 100, "₹ Cr", 8),
                 _right(320, 100, "74,076", 8), _right(400, 100, "86,930", 8),
                 _right(480, 100, "93,006", 8), _right(560, 100, "1,11,163", 8),
                 _right(640, 100, "1,58,850", 8), _right(720, 100, "1,66,190", 8),
                 (40, 130, "Total Assets", 9), (150, 130, "₹ Cr", 8),
                 _right(320, 130, "99,686", 8), _right(400, 130, "1,14,763", 8),
                 _right(480, 130, "1,18,918", 8), _right(560, 130, "1,35,332", 8),
                 _right(640, 130, "1,85,315", 8), _right(720, 130, "1,96,921", 8),
                 (800, 130, "₹1,54,288", 8)]
    cells = extract(_save(pdf_path, sequence), "2026-11-01", None, "deck")
    periods = {cell["value_text"]: cell["period_id"] for cell in cells}
    assert periods["74,076"] == _pid(None, "2022-03-31")
    assert periods["1,66,190"] == _pid(None, "2026-09-30")
    assert periods["1,96,921"] == _pid(None, "2026-09-30")
    # (b) a port-volume table: 3 Total columns, then Coal/Other Dry/Containers/Liquid pairs
    anchors = [150 + 46 * index for index in range(13)]
    periods_row = ("Q1 FY27", "Q1 FY26", "YoY", "Q1 FY27", "Q1 FY26",
                   "Q1 FY27", "Q1 FY26", "Q1 FY27", "Q1 FY26", "Q1 FY27", "Q1 FY26",
                   "Q1 FY27", "Q1 FY26")
    volume = [(60, 40, "Volume", 9),
              _center(173, 80, "Total", 8), _center(334, 80, "Dry (MMT)", 8),
              _center(518, 80, "Containers", 8), _center(656, 80, "Liquid (MMT)", 8),
              (255, 100, "Of which", 8), (275, 100, "Coal", 8), (365, 100, "Other Dry", 8),
              (460, 100, "'000 TEUs", 8), (550, 100, "MMT", 8), (645, 100, "MMT", 8)]
    volume += [_right(anchor, 125, label, 8)
               for anchor, label in zip(anchors, periods_row)]
    rows = (("Mundra1", ("51.2", "48.0", "7%", "6.2", "7.1", "2.7", "1.9", "2,185.0",
                         "2,047.7", "32.8", "30.7", "9.5", "8.2")),
            ("Dahej", ("2.6", "2.4", "10%", "1.9", "1.8", "0.7", "0.6", "100.0",
                       "90.0", "1.0", "0.9", "0.1", "0.2")))
    y = 160
    for label, row_values in rows:
        volume.append((40, y, label, 9))
        volume += [_right(anchor, y, text, 8) for anchor, text in zip(anchors, row_values)]
        y += 25
    cells = extract(_save(pdf_path, volume), "2026-08-01", None, "deck")
    cell = {value: [c for c in cells if c["value_text"] == value]
            for value in ("51.2", "6.2", "2,185.0", "32.8", "9.5")}
    assert cell["51.2"] and cell["51.2"][0]["period_id"] == _pid("2026-04-01", "2026-06-30")
    assert "Total" in cell["51.2"][0]["col_header"]
    coal = cell["6.2"][0]
    assert "Dry (MMT)" in coal["col_header"] and "Coal" in coal["col_header"]
    assert coal["unit_text"] == "MMT"
    containers = cell["2,185.0"][0]
    assert "Containers" in containers["col_header"]
    assert containers["unit_text"] == "count" and containers["scale"] == 1000.0
    assert cell["32.8"][0]["unit_text"] == "MMT"
    assert "Liquid" in cell["9.5"][0]["col_header"]


def test_round9_step5_junk_parents_bullets_and_page_numbers(pdf_path):
    """Step 5: a bullet, a slide title, a remarks column and 'Page 13' name no row.

    A split restatement label keeps its 'Previously reported' / 'Regrouped' parent.
    """
    lines = [(60, 40, "Investor presentation", 9),
             (60, 60, "additions and European subsea expansion", 8),
             (60, 90, "30 / th September", 8),
             _center(330, 110, "Q2 FY27"), _center(480, 110, "Q2 FY26"),
             _right(370, 130, "30.09.2025", 8), _right(520, 130, "30.09.2024", 8)]
    lines += [(60, 170, "Revenue", 9), _right(370, 170, "10,821", 8),
              _right(520, 170, "9,500", 8),
              (60, 195, "Other income", 9), _right(370, 195, "100", 8),
              _right(520, 195, "90", 8),
              (60, 225, "Previously reported Employee", 9),
              (60, 250, "Benefits Expense", 9), _right(370, 250, "97.43", 8),
              _right(520, 250, "103.82", 8),
              (60, 280, "Regrouped Employee", 9),
              (60, 305, "Benefits Expense", 9), _right(370, 305, "93.75", 8),
              _right(520, 305, "99.61", 8),
              (60, 340, "Page 13 of 59", 8)]
    cells = extract(_save(pdf_path, lines), "2025-11-01", None, "results")
    revenue = [cell for cell in cells if cell["value_text"] == "10,821"]
    assert revenue and "additions" not in revenue[0]["row_label"]
    assert revenue and "th" not in revenue[0]["row_label"].split(" > ")
    assert not any(cell["value_text"] == "13" for cell in cells)
    reported = [cell for cell in cells if cell["value_text"] == "97.43"]
    assert reported and "Benefits Expense" in reported[0]["row_label"]
    regrouped = [cell for cell in cells if cell["value_text"] == "93.75"]
    assert regrouped and "Regrouped Employee Benefits Expense" in regrouped[0]["row_label"]
