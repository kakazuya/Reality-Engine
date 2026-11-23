"""T-177: reference cells are settled by a vote on (row label, value), not by exact text or reply order."""
from reality_engine.v2 import reference_vote as rv


def _rows(label, headers, values):
    return [{"table": "T", "row_label": label, "col_header": h, "value": v, "unit": ""}
            for h, v in zip(headers, values)]


def test_header_spelling_and_enumerators_do_not_split_cells():
    a = _rows("(a) Debt-Equity Ratio", ["Quarter ended 31st March, 2022", "Quarter ended 31st Dec, 2021"],
              ["0.33:1", "0.42:1"])
    b = _rows("Debt - Equity ratio", ["Quarter ended 31 March 2022 (Audited)", "Quarter ended 31 Dec 2021"],
              ["0.33:1", "0.42:1"])
    cells, disputes = rv.vote_page([a, b], "Debt-Equity Ratio 0.33:1 0.42:1")
    assert len(cells) == 2 and not disputes
    assert all(c["agree_n"] == 2 and c["settled_by"] == "script" for c in cells)


def test_row_major_and_column_major_replies_agree():
    heads = ["Sep-19", "Mar-19"]
    row_major = _rows("PPE", heads, ["171372.90", "171057.99"]) + _rows("CWIP", heads, ["38460.55", "37388.47"])
    col_major = [row_major[0], row_major[2], row_major[1], row_major[3]]
    cells, disputes = rv.vote_page([row_major, col_major], "PPE 171372.90 171057.99 CWIP 38460.55 37388.47")
    assert len(cells) == 4 and not disputes


def test_majority_of_three_with_a_dropped_column_and_a_misread():
    heads = ["Q1", "Q2", "Q3"]
    a = _rows("EBITDA", heads, ["100", "120", "(15)"])
    b = _rows("EBITDA", heads[:2], ["100", "120"])
    c = _rows("EBITDA", heads, ["100", "125", "-15"])
    cells, disputes = rv.vote_page([a, b, c], "EBITDA 100 120 (15)")
    settled = {x["value_text"] for x in cells if x["settled_by"]}
    assert settled == {"100", "120", "(15)"}
    assert [d["value_text"] for d in disputes] == ["125"]


def test_same_value_under_two_labels_is_a_label_dispute():
    a = _rows("Consumer lending", ["FY23"], ["39,699"])
    b = _rows("Vehicle finance", ["FY23"], ["39,699"])
    cells, disputes = rv.vote_page([a, b], "Vehicle finance 39,699")
    assert len(cells) == 2 and len(disputes) == 2
    assert all(c["label_dispute"] and not c["settled_by"] and c["verbatim"] for c in cells)


def test_unprinted_value_is_never_settled_and_unlocated_rows_are_dropped():
    a = _rows("PAT", ["Q1"], ["999"])
    a.append({"table": "", "row_label": "", "col_header": "", "value": "7", "unit": ""})
    cells, disputes = rv.vote_page([a, list(a)], "PAT 55")
    assert len(cells) == 1 and cells[0]["agree_n"] == 2 and not cells[0]["verbatim"] and len(disputes) == 1


def test_two_spellings_of_one_label_are_one_row_but_two_names_are_not():
    heads = ["FY24", "FY25"]
    a = _rows("Depreciation and amortisation expenses", heads, ["291,085", "325,111"]) + _rows("SBPL", heads, ["60", "70"])
    b = _rows("Oeprecintlon nnd nmortisation expenses", heads, ["291,085", "325,111"])         + _rows("SBPL - Secured Business & Personal Loan", heads, ["60", "70"])
    cells, disputes = rv.vote_page([a, b], "Oeprecintlon nnd nmortisation expenses 291,085 325,111 SBPL 60 70")
    assert len(cells) == 4 and not disputes and all(c["agree_n"] == 2 for c in cells)
    assert {c["label_aliases"] for c in cells if "mortisation" in c["row_label"]} != {""}
    c = _rows("CSEL", heads, ["48,348", "53,922"])
    d = _rows("VF", heads, ["48,348", "53,922"])
    cells, disputes = rv.vote_page([c, d], "CSEL VF 48,348 53,922")
    assert len(disputes) == 4 and all(x["label_dispute"] for x in cells)
