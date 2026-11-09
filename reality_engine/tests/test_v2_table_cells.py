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
from reality_engine.v2.table_cells import extract, extract_page, label_unit

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
    assert first["row_label"] == "Hotel Services"
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
