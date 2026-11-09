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
from reality_engine.v2.table_cells import extract, extract_page

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
                            "value,snippet")
        assert lines[1].startswith("d1,3,Revenue,Q2 FY27,")
    finally:
        shutil.rmtree(directory, ignore_errors=True)
