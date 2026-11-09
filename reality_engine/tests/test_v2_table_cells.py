"""T-132: printed table cells from the text layer (headers, labels, periods, units, signs)."""
import os
import tempfile
from pathlib import Path

import pymupdf
import pytest

from reality_engine.v2.periods import period_row
from reality_engine.v2.table_cells import extract

HAVELLS = Path("D:/RealityEngine/raw/pilot60_history/HAVELLS/investor_presentation/"
               "d8b03849-76b8-4a7b-9672-984693e5cfb6.pdf")
ASIANPAINT = Path("D:/RealityEngine/raw/pilot60_history/ASIANPAINT/quarterly_results/"
                  "92071a93-de8f-4923-85b6-f853a765c9b9.pdf")
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


@pytest.mark.skipif(not HAVELLS.exists(), reason="Havells information update is not on disk")
def test_smoke_havells_segment_table():
    cells = extract(str(HAVELLS))
    page5 = [cell for cell in cells if cell["page"] == 5 and cell["table_no"] == 0]
    assert len(page5) == 36                              # 9 segment rows x 4 columns
    assert all(cell["row_label"] for cell in page5)
    assert all(cell["col_header"] for cell in page5)
    first = page5[0]
    assert first["period_id"] == _pid("2026-07-01", "2026-09-30") and first["value"] == 782 * CRORE


@pytest.mark.skipif(not ASIANPAINT.exists(), reason="Asian Paints results are not on disk")
def test_smoke_asian_paints_revenue_row():
    cells = extract(str(ASIANPAINT))
    revenue = [cell for cell in cells if cell["page"] == 5 and cell["row_label"]
               and "Revenue from operations" in cell["row_label"]]
    q2 = [cell for cell in revenue if cell["period_id"] == _pid("2026-07-01", "2026-09-30")]
    assert q2, [(cell["col_header"], cell["period_id"]) for cell in revenue]
    assert q2[0]["unit_text"] == "Rs crore" and q2[0]["scale"] == CRORE
