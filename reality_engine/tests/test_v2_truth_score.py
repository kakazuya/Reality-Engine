"""Hand-read truth scoring: right/wrong per reader cell, checker 2x2, wrong-cell kinds."""
from pathlib import Path

from reality_engine.v2 import truth_score as ts

TMP = Path(".tmp/test_truth_score")


def _w(x0, y0, text, cw=5.0, h=8.0):
    return (x0, y0, x0 + cw * len(text), y0 + h, text)


WORDS = [_w(200, 10, "FY26"), _w(260, 10, "FY25"),
         _w(10, 30, "Revenue"), _w(200, 30, "100"), _w(260, 30, "90"),
         _w(10, 45, "Profit"), _w(200, 45, "40"), _w(260, 45, "30"),
         _w(10, 60, "Tax"), _w(200, 60, "12"), _w(260, 60, "9")]
TRUTH = "TABLE: P&L\nUNIT: Rs cr\nCOLUMNS: FY26 | FY25\nRevenue | 100 | 90\nProfit | 40 | 30\nTax | 12 | 9\n"


def _cell(label, col, value):
    return {"table": "P&L", "row_label": label, "col_header": col, "value": value, "unit": ""}


def test_right_wrong_and_checker_table():
    TMP.mkdir(parents=True, exist_ok=True)
    (TMP / "p.truth.txt").write_text(TRUTH, encoding="utf-8")
    truth = ts.truth_cells(TMP / "p.truth.txt")
    assert len(truth) == 6
    rows = [_cell("Revenue", "FY26", "100"), _cell("Profit", "FY26", "30"),       # right; wrong column
            _cell("Tax", "FY25", "8"), _cell("", "Sl No", "1"),                      # misread; not a figure
            _cell("FY25", "Revenue", "90")]                                           # transposed: right
    c = ts.score_page(rows, truth, WORDS)
    assert c["cells"] == 5 and c["right"] == 2 and c["truth"] == 6
    assert c["wrong_wrong_row_or_column"] == 1 and c["wrong_value_misread"] == 1 and c["wrong_not_a_figure"] == 1
    assert c["confirmed_wrong"] == 0                       # the position check never passes the wrong-column cell
    assert c["confirmed_right"] + c["unconfirmed_right"] == 2


def test_page_without_figures_scores_every_cell_wrong():
    (TMP / "q.truth.txt").write_text("# notice page: no figures\n", encoding="utf-8")
    c = ts.score_page([_cell("", "Sr. No.", "1"), _cell("", "Sr. No.", "2")], ts.truth_cells(TMP / "q.truth.txt"), WORDS)
    assert c["truth"] == 0 and c["right"] == 0 and c["wrong_not_a_figure"] == 2
