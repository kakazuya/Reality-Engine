"""T-222 / R-015: the annual-report cash-flow reader (``pilot3.ar_statements``), on synthetic word boxes."""
from __future__ import annotations

import sqlite3

import pytest

from reality_engine.pilot3 import ar_statements as A


def _line(y: float, *cells: tuple[float, str]) -> list[tuple[float, float, float, float, str]]:
    """Word boxes for one printed line: (x, text) pairs, each word 6 points per character wide."""
    out = []
    for x, text in cells:
        for word in text.split(" "):
            out.append((x, y, x + 6 * len(word), y + 8, word))
            x += 6 * len(word) + 4
    return out


CUR, PRI = 400.0, 480.0


def statement_words(title="Standalone Statement of Cash Flows for the year ended 31st March 2024",
                    unit="(All amounts in Rs. Lakhs)", cfi="(1,146.47)", net="791.51", left_block=""):
    rows = [
        (20, [(30, title)] if not left_block else [(30, left_block), (300, title)]),
        (32, [(300 if left_block else 380, unit)]),
        (44, [(30 if not left_block else 300, "Particulars"), (CUR, "31st March 2024"), (PRI, "31st March 2023")]),
        (60, [(30, "Cash flows from operating activities")]),
        (72, [(30, "Profit before tax"), (CUR + 10, "575.94"), (PRI + 10, "390.47")]),
        (84, [(30, "Depreciation and amortisation"), (CUR + 10, "71.45"), (PRI + 10, "46.57")]),
        (96, [(30, "Less : Tax paid"), (CUR + 10, "(99.01)"), (PRI + 10, "(18.56)")]),
        (108, [(30, "Net cash from operating activities"), (CUR + 10, "22.71"), (PRI + 10, "717.80")]),
        (120, [(30, "Cash flows from investing activities")]),
        (132, [(30, "Purchase of property, plant and equipment"), (CUR + 10, "(123.06)"), (PRI + 10, "(36.32)")]),
        (144, [(30, "Net cash used in investing activities"), (CUR + 10, cfi), (PRI + 10, "(320.08)")]),
        (156, [(30, "Cash flows from financing activities")]),
        (168, [(30, "Dividend paid"), (CUR + 10, "(20.00)"), (PRI + 10, "-")]),
        (180, [(30, "Net cash from financing activities"), (CUR + 10, "1,915.27"), (PRI + 10, "(308.90)")]),
        (192, [(30, "Net increase in cash and cash equivalents"), (CUR + 10, net), (PRI + 10, "88.81")]),
        (204, [(30, "Cash and cash equivalents at the beginning of the year"), (CUR + 10, "93.71"), (PRI + 10, "4.90")]),
        (216, [(30, "Cash and cash equivalents at the end of the year"), (CUR + 10, "885.22"), (PRI + 10, "93.71")]),
        (240, [(30, "Annual Report 2023-24"), (CUR + 10, "105")]),
        (252, [(30, "As per our report of even date")]),
    ]
    words = []
    for y, cells in rows:
        if left_block and y > 32:
            cells = [(x + (0 if x >= 300 else 0), t) for x, t in cells]
        words += _line(y, *cells)
    return words


def test_number_reads_brackets_dashes_and_damaged_brackets():
    assert A.number("(1,146.47)") == (-1146.47, 2)
    assert A.number("1,915.27") == (1915.27, 2)
    assert A.number("-") == (0.0, 0)
    assert A.number("22.69)") == (-22.69, 2)
    assert A.number("(12.02") == (-12.02, 2)
    assert A.number("Note") is None


def test_dates_and_fiscal_label():
    assert [d for _, _, d in A._date_of("31st March, 2024   March 31, 2023  31.03.2022")] == \
        ["2024-03-31", "2023-03-31", "2022-03-31"]
    assert A.fiscal_label("2024-03-31") == "FY24"
    assert A.fiscal_label("2023-12-31") == "FY23"


def test_reads_both_columns_and_checks_the_identity(monkeypatch):
    words = statement_words()
    monkeypatch.setattr(A, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    st = A.read_statement("x.db", "doc", 1, "", None)
    assert st.ends == ["2024-03-31", "2023-03-31"] and st.unit == "inr_lakh" and st.basis == "standalone"
    c = A.canonical(st.lines)
    assert c["cash_flow_from_investing"].values == [-1146.47, -320.08]
    assert c["purchase_of_ppe"].values == [-123.06, -36.32]
    assert A.check_column(c, 0)[0] and A.check_column(c, 1)[0]
    log: list = []
    rows = A.rows_of(st, "2024-08-24", log)
    by = {(r.fiscal_year, r.line_item): r.value for r in rows}
    assert by[("FY24", "cash_flow_from_operations")] == 22.71
    assert by[("FY23", "cash_flow_from_financing")] == -308.90
    assert by[("FY24", "purchase_of_ppe")] == 123.06          # payment stored positive
    assert by[("FY24", "capex")] == -123.06                   # derived, outflow negative
    assert by[("FY24", "income_tax_paid")] == 99.01
    assert by[("FY23", "dividends_paid")] == 0.0
    # page furniture and the signature block never become rows
    assert not any("Annual Report" in r.caption for r in rows)


def test_a_column_that_does_not_add_up_writes_nothing(monkeypatch):
    words = statement_words(cfi="1,146.47")                   # sign lost: CFO+CFI+CFF no longer equals net change
    monkeypatch.setattr(A, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    st = A.read_statement("x.db", "doc", 1, "", None)
    log: list = []
    rows = A.rows_of(st, "2024-08-24", log)
    assert not any(r.fiscal_year == "FY24" for r in rows)
    assert any(r.fiscal_year == "FY23" for r in rows)
    assert [c["ok"] for c in log] == [False, True]


def test_no_unit_means_no_rows(monkeypatch):
    words = statement_words(unit="")
    monkeypatch.setattr(A, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    st = A.read_statement("x.db", "doc", 1, "", None)
    assert st.problems == ["no unit printed"]


def test_side_by_side_statement_is_cropped():
    words = _line(20, (30, "STATEMENT OF CHANGES IN EQUITY"), (300, "STATEMENT OF CASH FLOWS")) + \
        _line(40, (30, "Balance as at April 1, 2022"), (200, "2,182.21"), (300, "Net Profit Before Tax"))
    kept = A._crop(words)
    assert min(w[0] for w in kept) >= 290
    # a title alone on its line, centred, crops nothing
    centred = _line(20, (250, "STATEMENT OF CASH FLOWS")) + _line(40, (30, "Profit before tax"))
    assert A._crop(centred) == centred


def test_fiscal_year_headers_and_body_columns():
    words = _line(10, (30, "Cash Flow Statement for the year ended March 31, 2025")) + \
        _line(20, (30, "Particulars"), (CUR, "2024-25"), (PRI, "2023-24"))
    cols = A._columns(words, A.lines_of(words))
    assert cols and cols[1] == ["2025-03-31", "2024-03-31"]
    body = _line(10, (30, "CASH FLOW STATEMENT FOR THE PERIOD 01st APRIL, 2024 TO 31st MARCH, 2025")) + \
        _line(20, (30, "Particulars"), (CUR, "Current Year"), (PRI, "Previous Year"))
    for n in range(12):
        body += _line(40 + 12 * n, (30, f"Line {n}"), (CUR + 10, f"{n + 1},234.50"), (PRI + 10, f"({n + 1}.25)"))
    cols = A._columns_from_body(body, A.lines_of(body))
    assert cols and cols[1] == ["2025-03-31", "2024-03-31"] and cols[0][0] < cols[0][1]


SCHEMA = """
CREATE TABLE company(symbol TEXT, isin TEXT);
CREATE TABLE doc(doc_key TEXT, symbol TEXT, isin TEXT, doc_type TEXT, doc_family TEXT, title TEXT, filing_date TEXT,
  known_at TEXT, pages INT, sha256 TEXT, source TEXT, source_key TEXT);
CREATE TABLE doc_page(doc_key TEXT, symbol TEXT, page INT, text TEXT, method TEXT, chars INT, known_at TEXT, ocr_conf REAL);
CREATE TABLE fin_annual_line (symbol TEXT, isin TEXT, fiscal_year TEXT, period_end TEXT, basis TEXT, statement TEXT,
  line_item TEXT, caption TEXT, value REAL, unit TEXT, scale REAL, doc_key TEXT, page INTEGER, quote TEXT,
  source_db TEXT, source_table TEXT, source_rowid TEXT, known_at TEXT, known_at_source TEXT, is_reported INTEGER,
  is_derived INTEGER, definition TEXT, period_type TEXT);
"""


def test_run_store_writes_non_xbrl_years_and_compares_xbrl(tmp_path, monkeypatch):
    db = tmp_path / "c99.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO company VALUES ('TESTCO','INE000TEST01')")
    conn.execute("INSERT INTO doc (doc_key, doc_type, filing_date, known_at) VALUES ('ar24','annual_report',"
                 "'2024-08-24','2024-08-24T10:00:00')")
    text = ("Standalone Statement of Cash Flows for the year ended 31st March 2024\n"
            "Cash flows from operating activities\nCash flows from investing activities\n")
    conn.execute("INSERT INTO doc_page (doc_key, page, text) VALUES ('ar24', 5, ?)", (text,))
    # XBRL holds FY24: the printed FY24 totals are compared, only FY23 is written
    conn.execute("INSERT INTO fin_annual_line (symbol, fiscal_year, basis, statement, line_item, value, scale, "
                 "source_table, period_type) VALUES ('TESTCO','FY24','standalone','CF','cash_flow_from_operations',"
                 "2271000, 1, 'facts', 'FY')")
    conn.commit()
    conn.close()
    words = statement_words()
    monkeypatch.setattr(A, "words_for", lambda *a, **k: type("P", (), {"words": words})())
    res = A.run_store(db, "c99")
    assert res["xbrl_compared"] == 1 and res["xbrl_agree"] == 1
    conn = sqlite3.connect(db)
    got = conn.execute("SELECT DISTINCT fiscal_year FROM fin_annual_line WHERE source_table='ar_statement'").fetchall()
    assert got == [("FY23",)]
    unit, scale, known = conn.execute("SELECT unit, scale, known_at FROM fin_annual_line WHERE "
                                      "source_table='ar_statement' LIMIT 1").fetchone()
    assert (unit, scale, known) == ("inr_lakh", 1e5, "2024-08-24T10:00:00")
    # a re-run replaces its own rows, never adds duplicates
    n = conn.execute("SELECT COUNT(*) FROM fin_annual_line WHERE source_table='ar_statement'").fetchone()[0]
    conn.close()
    A.run_store(db, "c99")
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM fin_annual_line WHERE source_table='ar_statement'").fetchone()[0] == n
    conn.close()


@pytest.mark.parametrize("label,expected", [
    ("Add:- Opening Cash & Cash Equivalents", "cash_at_beginning"),
    ("Total Cash Flow", "net_change_in_cash"),
    ("Effect of exchange rate changes on cash and cash equivalents", "fx_effect_on_cash"),
])
def test_line_names(label, expected):
    assert next(n for n, rx, _ in A.LINES if rx.search(label.lower())) == expected


# --- review round 1 (headless reviewer, 17 Nov): one test per defect ---------------------------------------------

def _ln(label, cur, pri=None):
    return A.Line(label, [cur, pri], 2, label, 1)


def test_fx_adjustment_in_operating_is_not_the_effect_on_cash():
    lines = [_ln("Cash flows from operating activities", None), _ln("Net (gain)/loss on foreign currency translation", -7.26),
             _ln("Net cash from operating activities", 10.0), _ln("Net cash used in financing activities", -2.0),
             _ln("Exchange rate fluctuation arising on consolidation (D)", -5.11)]
    c = A.canonical(lines)
    assert c["fx_effect_on_cash"].values[0] == -5.11


def test_net_ppe_line_is_not_a_gross_purchase():
    lines = [_ln("Cash flows from investing activities", None),
             _ln("Sale / (Acquisition) of Property, plant and equipment", 674.15),
             _ln("Purchase of intangible assets", -3.0), _ln("Purchase of investment property", -9.0)]
    c = A.canonical(lines)
    assert c["ppe_purchase_net_of_sale"].values[0] == 674.15
    assert "purchase_of_ppe" not in c


def test_lease_interest_is_not_interest_paid():
    lines = [_ln("Cash flows from financing activities", None), _ln("Interest paid on lease liabilities", -4.0),
             _ln("Interest paid", -20.0)]
    assert A.canonical(lines)["interest_paid"].values[0] == -20.0


def test_footnote_is_furniture():
    assert A._FURNITURE.search("Statement of Cash Flow has been prepared under the Indirect Method as set out in IND AS 7")


def test_side_by_side_header_takes_the_left_pair():
    words = _line(20, (30, "Particulars"), (CUR, "31st March 2025"), (PRI, "31st March 2024"),
                  (700, "31st March 2025"), (780, "31st March 2024"))
    cols = A._columns(words, A.lines_of(words))
    assert cols and cols[0][0] < 500


def test_one_statement_per_year_never_mixed():
    mk = lambda cap, own, src, known: A.Row("FY24", "2024-03-31", "standalone", "cf_printed_line", cap, 1.0, "inr_lakh",
                                             1e5, "d", 1, "", known, "", 0, own, src)
    cands = [mk("Unrealised exchange (gain)/losses", True, "ar24#p5#current", "2024-08-01"),
             mk("Realised exchange (gain)/losses", False, "ar25#p6#prior", "2025-08-01")]
    assert [r.caption for r in A.pick_statements(cands)] == ["Unrealised exchange (gain)/losses"]


# --- review round 2 -------------------------------------------------------------------------------------------------

def test_from_to_header_takes_the_to_date():
    words = _line(20, (30, "Particulars"), (CUR, "31 March 2026"), (PRI - 30, "11 February 2024 to 31 March 2025"))
    cols = A._columns(words, A.lines_of(words))
    assert cols and cols[1] == ["2026-03-31", "2025-03-31"]


def test_interest_paid_skips_nci_and_accrued_and_prefers_paid():
    lines = [_ln("Cash flows from financing activities", None),
             _ln("Proceeds from issue of equity shares to Non Controlling Interest", -1300.0),
             _ln("Interest accrued", 5.38), _ln("Interest paid", -450.10)]
    assert A.canonical(lines)["interest_paid"].values[0] == -450.10


def test_nothing_is_named_after_the_closing_cash():
    lines = [_ln("Net cash used in financing activities", -2.0), _ln("Cash and cash equivalents at the end of the year", 900.0),
             _ln("- foreign currency accounts", 655.65)]
    c = A.canonical(lines)
    assert "fx_effect_on_cash" not in c and c["cash_at_end"].values[0] == 900.0


def test_contd_half_of_the_same_statement_is_not_cropped():
    words = _line(20, (30, "Statement of Cash Flows for the year ended 31 March 2024"),
                  (330, "Statement of Cash Flows (Contd.)")) + _line(40, (30, "Profit before tax"), (330, "Net cash from financing"))
    assert A._crop(words) == words


def test_bank_balance_line_is_not_net_change_in_cash():
    assert not any(n == "net_change_in_cash" for n, rx, _ in A.LINES
                   if rx.search("net (increase)/decrease in bank balances other than cash and cash equivalents"))


def test_body_columns_oldest_first_header_is_reversed():
    body = _line(10, (30, "Cash Flow Statement for the year ended 31st March, 2024")) + \
        _line(20, (30, "Particulars"), (CUR, "31.03.2023"), (PRI, "31.03.2024 x"))
    for n in range(12):
        body += _line(40 + 12 * n, (30, f"Line {n}"), (CUR + 10, f"{n + 1},234.50"), (PRI + 10, f"({n + 1}.25)"))
    cols = A._columns(body, A.lines_of(body)) or A._columns_from_body(body, A.lines_of(body))
    assert cols[1][0] == "2023-03-31"   # the left column is the older year


def test_statement_in_two_titled_halves_is_read_left_then_right():
    L, R = 30, 560
    w = _line(20, (L, "Statement of Cash Flow for the year ended March 31, 2025"),
              (R, "Statement of Cash Flow for the year ended March 31, 2025"))
    w += _line(32, (L + 200, "(Rs in Lakh)"), (R + 200, "(Rs in Lakh)"))
    w += _line(44, (L, "Particulars"), (L + 250, "March 31, 2025"), (L + 340, "March 31, 2024"),
               (R, "Particulars"), (R + 250, "March 31, 2025"), (R + 340, "March 31, 2024"))
    left = [("Cash flows from operating activities", None, None), ("Net cash from operating activities", "100.00", "50.00"),
            ("Cash flows from investing activities", None, None), ("Net cash used in investing activities", "(30.00)", "(20.00)")]
    right = [("Cash flows from financing activities", None, None), ("Net cash used in financing activities", "(10.00)", "(5.00)"),
             ("Net increase in cash and cash equivalents", "60.00", "25.00")]
    for n, (lab, a, b) in enumerate(left):
        w += _line(60 + 12 * n, (L, lab), *([(L + 260, a), (L + 350, b)] if a else []))
    for n, (lab, a, b) in enumerate(right):
        w += _line(60 + 12 * n, (R, lab), *([(R + 260, a), (R + 350, b)] if a else []))
    halves = A._halves(w)
    assert len(halves) == 2
    import types
    A_words = A.words_for
    try:
        A.words_for = lambda *a, **k: types.SimpleNamespace(words=w)
        st = A.read_statement("x.db", "doc", 1, "", None)
    finally:
        A.words_for = A_words
    c = A.canonical(st.lines)
    assert c["cash_flow_from_financing"].values == [-10.0, -5.0] and A.check_column(c, 0)[0]


def test_wrapped_from_to_header_takes_the_to_date_below():
    words = _line(20, (30, "Particulars"), (CUR, "31 March 2026"), (PRI, "11 February 2024 to")) + \
        _line(30, (PRI, "31 March 2025"))
    cols = A._columns(words, A.lines_of(words))
    assert cols and cols[1] == ["2026-03-31", "2025-03-31"]


# --- review round 3 -------------------------------------------------------------------------------------------------

def test_full_year_from_to_title_is_not_part_year():
    assert not A._part_year("2024-04-01", "2025-03-31")
    assert A._part_year("2024-02-11", "2025-03-31")


def test_capitalised_wrapped_word_joins_its_line():
    words = _line(10, (30, "(Increase)/Decrease in Financial and Other"), (CUR + 10, "(5,818.86)"), (PRI + 10, "12.00")) + \
        _line(20, (30, "Assets")) + _line(30, (30, "Adjustments for:"))
    lines = A._read_lines(words, [CUR + 20, PRI + 20], 1)
    assert lines[0].label == "(Increase)/Decrease in Financial and Other Assets"
    assert lines[1].label == "Adjustments for:"
