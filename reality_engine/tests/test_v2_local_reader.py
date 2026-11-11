"""T-188: the local reader's converter (model reply -> our grid rows). No GPU, no network."""
from __future__ import annotations

from reality_engine.v2.local_reader import convert

KEYS = {"table", "row_label", "col_header", "value", "unit"}


def _triples(rows):
    return [(r["row_label"], r["col_header"], r["value"]) for r in rows]


def test_markdown_table_with_blank_cell():
    raw = (
        "Some prose before the table.\n"
        "| Particulars | Q2FY27 | Q2FY26 |\n"
        "|:---|---:|---:|\n"
        "| Revenue from operations | 1,234 | 1,100 |\n"
        "| Exceptional items |  | 45 |\n"
    )
    rows = convert(raw)
    assert _triples(rows) == [
        ("Revenue from operations", "Q2FY27", "1,234"),
        ("Revenue from operations", "Q2FY26", "1,100"),
        ("Exceptional items", "Q2FY26", "45"),
    ]
    assert all(set(r) == KEYS for r in rows)
    assert rows[0]["unit"] == ""


def test_html_table_two_level_header_and_blank_cell():
    raw = (
        "```html\n<table>\n"
        "<tr><th></th><th>Q4FY26</th><th>Q4FY26</th></tr>\n"
        "<tr><th></th><th>Operating</th><th>Total</th></tr>\n"
        "<tr><td>Revenue</td><td>5,638</td><td></td></tr>\n"
        "<tr><td>EBITDA margin</td><td>21.3%</td><td>21.5%</td></tr>\n"
        "</table>\n```\n"
    )
    rows = convert(raw)
    assert _triples(rows) == [
        ("Revenue", "Q4FY26 > Operating", "5,638"),
        ("EBITDA margin", "Q4FY26 > Operating", "21.3%"),
        ("EBITDA margin", "Q4FY26 > Total", "21.5%"),
    ]


def test_unit_row_belongs_to_the_columns():
    raw = (
        "| Segment | FY26 | FY25 |\n|---|---|---|\n"
        "| Units | Rs crore | Rs crore |\n"
        "| Cement | 40,120 | 38,004 |\n"
    )
    rows = convert(raw)
    assert [(r["row_label"], r["col_header"], r["value"], r["unit"]) for r in rows] == [
        ("Cement", "FY26", "40,120", "Rs crore"),
        ("Cement", "FY25", "38,004", "Rs crore"),
    ]


def test_prose_and_labelless_cells_are_not_rows():
    assert convert("The page has no tables, only a chart title.") == []
    raw = "| Note | | |\n|---|---|---|\n| no figures here | n.a. | |\n"
    assert convert(raw) == []


def test_otsl_table_left_merge_and_two_level_header():
    """PaddleOCR-VL table recognition: OTSL, with the group header left-merged over its columns."""
    raw = (
        "<ecel><fcel>Total Income (\u20b9 crores)<lcel><lcel><fcel>EBIT (\u20b9 crores)<lcel><lcel><nl>"
        "<fcel>Particulars\\(^{{*}}\\)<fcel>Q1FY26<fcel>Q1FY27<fcel>YoY%<fcel>Q1FY26<fcel>Q1FY27<fcel>YoY%<nl>"
        "<fcel>Domestic<fcel>13,824<fcel>18,867<fcel>36%<fcel>1,680<fcel>2,649<fcel>58%<nl>"
    )
    rows = convert(raw)
    assert [(r["row_label"], r["col_header"], r["value"]) for r in rows] == [
        ("Domestic", "Total Income (\u20b9 crores) > Q1FY26", "13,824"),
        ("Domestic", "Total Income (\u20b9 crores) > Q1FY27", "18,867"),
        ("Domestic", "Total Income (\u20b9 crores) > YoY%", "36%"),
        ("Domestic", "EBIT (\u20b9 crores) > Q1FY26", "1,680"),
        ("Domestic", "EBIT (\u20b9 crores) > Q1FY27", "2,649"),
        ("Domestic", "EBIT (\u20b9 crores) > YoY%", "58%"),
    ]


def test_html_rowspan_header_keeps_the_column_alignment():
    raw = (
        "<table><thead>"
        '<tr><th rowspan="2">Particulars</th><th colspan="2">Revenue</th></tr>'
        "<tr><th>FY26</th><th>FY25</th></tr></thead>"
        "<tbody><tr><td>Cement</td><td>40,120</td><td></td></tr></tbody></table>"
    )
    rows = convert(raw)
    assert [(r["row_label"], r["col_header"], r["value"]) for r in rows] == [
        ("Cement", "Revenue > FY26", "40,120"),
    ]


def test_a_reply_cut_at_max_tokens_keeps_its_finished_rows():
    raw = ("<table><thead><tr><th>Particulars</th><th>FY26</th></tr></thead><tbody>"
           "<tr><td>Cement</td><td>40,120</td></tr><tr><td>Agg")
    assert [(r["row_label"], r["value"]) for r in convert(raw)] == [("Cement", "40,120")]
