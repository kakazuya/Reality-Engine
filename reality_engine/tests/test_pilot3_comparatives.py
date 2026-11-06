"""Tests for the printed comparative columns of the results tables (T-057, ``pilot3.comparatives``).

Every page here is built from inline word boxes (no PDF, no file on D:): the extractor reads
``page.get_text("words")``-shaped tuples, so a test can state exactly what a page prints.  The database is
``:memory:``."""
from __future__ import annotations

import sqlite3

import pytest

from reality_engine.pilot3 import comparatives as cmp
from reality_engine.pilot3 import schema

COLS = (200.0, 260.0, 320.0, 380.0, 440.0, 500.0)
DATES = ("30.09.2026", "30.06.2026", "30.09.2025", "30.09.2026", "30.09.2025", "31.03.2026")


def _w(x1: float, text: str, y: float) -> tuple:
    """One word box right-aligned at ``x1`` (the column anchor) on row ``y``."""
    return (x1 - 7.0 * len(text), y - 3.0, x1, y + 3.0, text, 0, 0, 0)


def _row(y: float, label: str, values, middle: bool = False) -> list[tuple]:
    """A printed row: label left of the numbers, or in the middle (HINDUNILVR style)."""
    cells = list(values)
    words, x = [], 20.0
    for word in label.split():
        width = 7.0 * len(word)
        words.append((x, y - 3.0, x + width, y + 3.0, word, 0, 0, 0))
        x += width + 3.0
    if middle:
        words = [(word[0] + 310.0, word[1], word[2] + 310.0, word[3], word[4], 0, 0, 0) for word in words]
    words += [_w(anchor, text, y) for anchor, text in zip(COLS, cells)]
    return words


def _page(rows, unit="Rs. inCrore", title="Statement of Consolidated Unaudited Financial Results", dates=DATES):
    words = [(40.0, 5.0, 120.0, 13.0, title, 0, 0, 0), (40.0, 15.0, 110.0, 23.0, unit, 0, 0, 0)]
    words += [_w(COLS[i], text, 30.0) for i, text in enumerate(dates)]
    for i, (label, values) in enumerate(rows):
        words += _row(50.0 + 10.0 * i, label, values)
    return cmp.rows_from_words(words)


ROWS = [
    ("1 Revenue from operations", ("1,000", "900", "800", "1,900", "1,700", "3,500")),
    ("2 Other income", ("100", "90", "80", "190", "170", "350")),
    ("3 Total income", ("1,100", "990", "880", "2,090", "1,870", "3,850")),
    ("4 Total expenses", ("800", "720", "640", "1,520", "1,360", "2,800")),
    ("5 Profit before exceptional items and tax", ("300", "270", "240", "570", "510", "1,050")),
    ("6 Total tax expense", ("75", "67", "60", "142", "127", "262")),
    ("7 Profit for the period", ("225", "203", "180", "428", "383", "788")),
    ("8 Basic EPS", ("10.5", "9.5", "8.4", "20.0", "17.9", "36.8")),
]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE company (symbol TEXT, isin TEXT, isin_from TEXT, isin_to TEXT, isin_source TEXT, bse_code TEXT, name TEXT);
        CREATE TABLE fin_quarter_xbrl (symbol TEXT, isin TEXT, period_start TEXT, period_end TEXT, fiscal_period TEXT,
            basis TEXT, audited TEXT, statement TEXT, line_item TEXT, xbrl_tag TEXT, value REAL, unit TEXT, scale REAL,
            source_file TEXT, source_db TEXT, source_table TEXT, source_rowid TEXT, known_at TEXT, known_at_source TEXT,
            is_reported INTEGER);
        CREATE TABLE share_capital (symbol TEXT, isin TEXT, as_of_date TEXT, basis TEXT, event TEXT, ratio TEXT,
            shares_outstanding REAL, paid_up_capital REAL, face_value REAL, unit TEXT, scale REAL, known_at TEXT,
            known_at_source TEXT, source_db TEXT, source_table TEXT, source_rowid TEXT, isin_effective_from TEXT,
            isin_effective_to TEXT);
        CREATE TABLE doc (doc_key TEXT PRIMARY KEY, symbol TEXT, isin TEXT, doc_type TEXT, doc_family TEXT, title TEXT,
            filing_date TEXT, known_at TEXT, pages INTEGER, sha256 TEXT, source TEXT, source_key TEXT);
    """)
    conn.execute("INSERT INTO company (symbol, isin, isin_from) VALUES ('AAAA', 'INE000A01001', '2019-01-01')")
    schema.ensure(conn, (cmp.TABLE,))
    return conn


def _xbrl(conn, end: str, item: str, value: float, basis: str = "consolidated") -> None:
    conn.execute("INSERT INTO fin_quarter_xbrl (symbol, basis, period_start, period_end, fiscal_period, line_item, value, "
                 "known_at) VALUES ('AAAA', ?, '2026-07-01', ?, 'Q2FY27', ?, ?, '2026-10-19T10:00:00')",
                 (basis, end, item, value))


def _store(conn, known_at="2026-10-20T12:00:00", unit="Rs. inCrore", rows=ROWS, dates=DATES):
    table = cmp.read_page(_page(rows, unit=unit, dates=dates))
    assert table is not None
    return cmp._table_rows(conn, "AAAA", "INE000A01001", "doc1", 6, known_at, table,
                           cmp.xbrl_index(conn, "AAAA"), [])


def _cells(rows, item, role):
    return [r for r in rows if r[9] == item and r[6] == role]


# ---------------------------------------------------------------- word boxes -------------------------------------------------------
def test_word_box_rows_group_by_y_and_order_by_x():
    words = [(300.0, 10.0, 330.0, 16.0, "second", 0, 0, 0),
             (50.0, 10.0, 90.0, 16.0, "first", 0, 0, 0),
             (50.0, 30.0, 90.0, 36.0, "third", 0, 0, 0)]
    rows = cmp.rows_from_words(words)
    assert [[w[4] for w in row] for row in rows] == [["first", "second"], ["third"]]


def test_middle_label_layout_reads_six_columns():
    rows = [("1 Revenue from operations", ROWS[0][1]), ("2 Other income", ROWS[1][1]),
            ("3 Total income", ROWS[2][1]), ("4 Total expenses", ROWS[3][1]),
            ("5 Profit before exceptional items and tax", ROWS[4][1]),
            ("6 Total tax expense", ROWS[5][1]), ("7 Profit for the period", ROWS[6][1]),
            ("8 Basic EPS", ROWS[7][1])]
    words = []
    for i, (label, values) in enumerate(rows):
        words += _row(50.0 + 10.0 * i, label, values, middle=(label.startswith("3 ")))
    page = cmp.rows_from_words(words + [(40.0, 5.0, 120.0, 13.0, "Results", 0, 0, 0),
                                        (40.0, 15.0, 110.0, 23.0, "Rs. inCrore", 0, 0, 0)]
                                 + [_w(COLS[i], text, 30.0) for i, text in enumerate(DATES)])
    table = cmp.read_page(page)
    assert table is not None
    assert len(table["anchors"]) == 6
    assert [round(a) for a in table["anchors"]] == [200, 260, 320, 380, 440, 500]
    stored = _store(_conn())
    total = _cells(stored, "total_income", "current")[0]
    assert total[11] == 1100 * 1e7          # value in rupees, scale 1.0
    assert total[12] == "inr"
    assert total[15].startswith("3 Total income") or total[15].startswith("1,100")   # quote is the printed row
    assert "1,100" in total[15]


def test_hindunilvr_column_order_year_ago_second():
    """The year-ago column printed second and the preceding third: the header's month decides the role."""
    dates = ("30.09.2026", "30.09.2025", "30.06.2026", "30.09.2026", "30.09.2025", "31.03.2026")
    rows = [("1 Revenue from operations", ("1,000", "800", "900", "1,900", "1,700", "3,500")),
            ("2 Other income", ("100", "80", "90", "190", "170", "350")),
            ("3 Total income", ("1,100", "880", "990", "2,090", "1,870", "3,850")),
            ("4 Total expenses", ("800", "640", "720", "1,520", "1,360", "2,800")),
            ("5 Profit before exceptional items and tax", ("300", "240", "270", "570", "510", "1,050")),
            ("6 Total tax expense", ("75", "60", "67", "142", "127", "262")),
            ("7 Profit for the period", ("225", "180", "203", "428", "383", "788")),
            ("8 Basic EPS", ("10.5", "8.4", "9.5", "20.0", "17.9", "36.8"))]
    stored = _store(_conn(), rows=rows, dates=dates)
    assert _cells(stored, "revenue_from_operations", "year_ago")[0][3] == "2025-09-30"
    assert _cells(stored, "revenue_from_operations", "preceding")[0][3] == "2026-06-30"
    assert _cells(stored, "revenue_from_operations", "year_ago")[0][11] == 800 * 1e7


def test_misread_header_year_keeps_the_layout():
    """HDFCBANK's year-ago column reads 39.09.2026: count and quarter decide, not the printed year."""
    dates = ("30.09.2026", "30.06.2026", "39.09.2026", "30.09.2026", "30.09.2025", "31.03.2026")
    stored = _store(_conn(), dates=dates)
    roles = [r[6] for r in stored if r[9] == "total_income"]
    assert roles[:6] == ["current", "preceding", "year_ago", "ytd", "prior_ytd", "last_fy"]
    assert _cells(stored, "total_income", "year_ago")[0][3] == "2025-09-30"


# ---------------------------------------------------------------- numbers ----------------------------------------------------------
def test_separators_are_reread_under_the_tables_decimals():
    assert cmp.read_number("17.369.35", 2) == (17369.35, False)
    assert cmp.read_number("79362,78", 2) == (79362.78, False)
    assert cmp.read_number("533-402", 0) == (533402, False)
    assert cmp.read_number("506.155", 0) == (506155, False)
    assert cmp.read_number("(1,67)", 2) == (-1.67, False)
    assert cmp.read_number("-", 0) == (0.0, False)
    assert cmp.read_number("5,467.71", 2) == (5467.71, False)
    assert cmp._decimals(["5,467.71", "1,005,746", "79362,78"]) == 2


def test_a_repaired_token_enters_only_behind_a_confirming_check():
    conn = _conn()
    rows = ROWS + [("9 Other expenses", ("800", "700", "6O0", "1,500", "1,300", "2,700"))]
    unconfirmed = _store(conn, rows=rows)
    assert not _cells(unconfirmed, "other_expenses", "year_ago")     # "6O0" read as 600, no check confirms it
    _xbrl(conn, "2025-09-30", "other_expenses", 600 * 1e7)
    confirmed = _store(conn, rows=rows)
    cell = _cells(confirmed, "other_expenses", "year_ago")[0]
    assert cell[11] == 600 * 1e7
    assert cell[20] == "xbrl_ok"
    assert cell[21] and "repaired" in cell[21]


def test_unit_from_the_text_or_from_xbrl():
    assert cmp._unit("Rs. inCrore") == 1e7
    assert cmp._unit("(Rs in crores)") == 1e7
    assert cmp._unit("(₹ in Lakhs)") == 1e5
    assert cmp._unit("(f in Million)") == 1e6
    assert cmp._unit("('I: in Crore") == 1e7
    assert cmp._unit("llNR crore") == 1e7
    assert cmp._unit("Particulars") is None
    # no unit word on the page: the power of ten that makes the current column equal XBRL
    conn = _conn()
    _xbrl(conn, "2026-09-30", "revenue_from_operations", 1000 * 1e6)
    _xbrl(conn, "2026-09-30", "pat", 225 * 1e6)
    stored = _store(conn, unit="Statement of Consolidated Unaudited Financial Results")
    cell = _cells(stored, "revenue_from_operations", "current")[0]
    assert cell[11] == 1000 * 1e6
    assert cell[21] and "scale from XBRL" in cell[21]


# ---------------------------------------------------------------- checks -----------------------------------------------------------
def test_xbrl_ok_and_sum_ok():
    conn = _conn()
    _xbrl(conn, "2026-09-30", "revenue_from_operations", 1000 * 1e7)
    _xbrl(conn, "2026-06-30", "revenue_from_operations", 900 * 1e7)
    stored = _store(conn)
    assert _cells(stored, "revenue_from_operations", "current")[0][20] == "xbrl_ok"
    assert _cells(stored, "revenue_from_operations", "preceding")[0][20] == "xbrl_ok"
    # total_income = revenue + other_income, pbt_before = total_income - total_expenses, pat = pbt - tax
    for item, role in (("total_income", "current"), ("other_income", "current"), ("total_expenses", "current"),
                       ("pbt_before_exceptional", "current"), ("pat", "current")):
        assert _cells(stored, item, role)[0][20] == "sum_ok", item
    # a Q2 table also carries current + preceding = ytd
    assert _cells(stored, "total_income", "ytd")[0][20] == "sum_ok"


def test_a_failed_check_stores_nothing():
    conn = _conn()
    rows = [("1 Revenue from operations", ("1,000", "900", "800", "1,900", "1,700", "3,500")),
            ("2 Other income", ("100", "90", "80", "190", "170", "350")),
            ("3 Total income", ("9,999", "990", "880", "2,090", "1,870", "3,850")),
            ("4 Total expenses", ("800", "720", "640", "1,520", "1,360", "2,800")),
            ("5 Profit before exceptional items and tax", ("300", "270", "240", "570", "510", "1,050")),
            ("6 Total tax expense", ("75", "67", "60", "142", "127", "262")),
            ("7 Profit for the period", ("0", "203", "180", "428", "383", "788")),
            ("8 Basic EPS", ("10.5", "9.5", "8.4", "20.0", "17.9", "36.8"))]
    stored = _store(conn, rows=rows)
    assert not _cells(stored, "total_income", "current")     # 9,999 not 1,000 + 100
    assert _cells(stored, "revenue_from_operations", "current")


def test_known_at_is_the_filings_date():
    stored = _store(_conn(), known_at="2026-10-20T12:00:00")
    assert {r[18] for r in stored} == {"2026-10-20T12:00:00"}
    assert {r[19] for r in stored} == {"doc.known_at"}


def test_every_raw_token_is_in_its_quote():
    stored = _store(_conn())
    for row in stored:
        if row[22]:                                          # a derived row joins two quotes
            assert row[14] in row[15], row


# ---------------------------------------------------------------- scope ------------------------------------------------------------
def test_per_symbol_rerun_leaves_other_symbols_rows():
    conn = _conn()
    conn.execute("INSERT INTO doc (doc_key, symbol, doc_type, known_at) VALUES ('doc1', 'AAAA', 'results', "
                 "'2026-10-20T12:00:00')")
    rows = _store(conn)                                      # AAAA's own rows
    conn.executemany(
        f"INSERT INTO {cmp.TABLE} (symbol, isin, period_start, period_end, fiscal_period, period_type, column_role, "
        "basis, statement, line_item, caption, value, unit, scale, raw_token, quote, doc_key, page, known_at, "
        "known_at_source, check_status, check_detail, is_reported) VALUES ("
        + ",".join("?" * 23) + ")", rows)
    conn.execute(f"INSERT INTO {cmp.TABLE} (symbol, line_item, value) VALUES ('BBBB', 'pat', 1.0)")
    conn.commit()
    before = {r[0] for r in conn.execute(f"SELECT symbol FROM {cmp.TABLE}")}
    assert before == {"AAAA", "BBBB"}
    stats = cmp.run(conn, ["AAAA"])
    assert stats["AAAA"]["rows"] >= 0
    left = {r[0] for r in conn.execute(f"SELECT symbol FROM {cmp.TABLE}")}
    assert left == {"BBBB"}          # AAAA was rewritten from its documents (none readable here); BBBB untouched
    assert conn.execute(f"SELECT COUNT(*) FROM {cmp.TABLE} WHERE symbol='BBBB'").fetchone()[0] == 1


def test_ttm_from_one_filings_columns():
    """TTM = last_fy + ytd - prior_ytd from the checked printed columns (Q2 table)."""
    conn = _conn()
    values = {("current", "2026-09-30"): 225.0, ("preceding", "2026-06-30"): 203.0,
              ("year_ago", "2025-09-30"): 180.0, ("ytd", "2026-09-30"): 428.0,
              ("prior_ytd", "2025-09-30"): 383.0, ("last_fy", "2026-03-31"): 788.0}
    for (role, end), value in values.items():
        ptype = "fy" if role == "last_fy" else ("ytd" if role in ("ytd", "prior_ytd") else "quarter")
        conn.execute(
            f"INSERT INTO {cmp.TABLE} (symbol, isin, period_start, period_end, fiscal_period, period_type, column_role, "
            "basis, statement, line_item, caption, value, unit, scale, raw_token, quote, doc_key, page, known_at, "
            "known_at_source, check_status, check_detail, is_reported) VALUES "
            "('AAAA','INE000A01001','2026-04-01',?,'FY26',?,?,'consolidated','P&L','pat','x',?,'inr',1.0,'1','q',"
            "'doc1',6,'2026-10-20','doc.known_at','sum_ok',NULL,1)", (end, ptype, role, value))
    sets = cmp.ttm_filings(conn, "AAAA", "consolidated")
    assert sets and sets[0]["items"]["pat"] == pytest.approx(788 + 428 - 383)


def _ttm_cells(ll, cur, ago, ytd, prior, ytd_ptype="ytd"):
    cells = {("last_fy", "eps_basic"): (ll, "2026-03-31", "fy")}
    if cur is not None:
        cells[("current", "eps_basic")] = (cur, "2026-09-30", "quarter")
    if ago is not None:
        cells[("year_ago", "eps_basic")] = (ago, "2025-09-30", "quarter")
    if ytd is not None:
        cells[("ytd", "eps_basic")] = (ytd, "2026-09-30", ytd_ptype)
    if prior is not None:
        cells[("prior_ytd", "eps_basic")] = (prior, "2025-09-30", ytd_ptype)
    return cells


def test_ttm_uses_the_tables_own_quarter_layout():
    """A Q2/Q3 table prints a ytd column and must use last_fy + ytd - prior_ytd; the Q1 formula is only for a
    table with no ytd at all.  The four measured rows of the audit (the old code used the Q1 formula)."""
    assert cmp._ttm_one(_ttm_cells(72.05, 21.35, 17.59, 39.38, 31.43), "eps_basic") == pytest.approx(80.00)  # HINDALCO
    assert cmp._ttm_one(_ttm_cells(45.36, 9.03, 12.86, 32.49, 34.77), "eps_basic") == pytest.approx(43.08)   # HINDUNILVR
    assert cmp._ttm_one(_ttm_cells(26.89, 7.85, 6.47, 15.41, 12.79), "eps_basic") == pytest.approx(29.51)    # BAJFINANCE
    assert cmp._ttm_one(_ttm_cells(45.6, 13.0, 12.7, 22.5, 24.5), "eps_basic") == pytest.approx(43.60)       # SUNPHARMA
    # a Q1 table has no ytd column at all
    q1 = {("last_fy", "eps_basic"): (36.8, "2026-03-31", "fy"), ("current", "eps_basic"): (10.5, "2026-06-30", "quarter"),
          ("year_ago", "eps_basic"): (8.4, "2025-06-30", "quarter")}
    assert cmp._ttm_one(q1, "eps_basic") == pytest.approx(38.9)
    # never fall through when the ytd formula lacks a cell
    missing = _ttm_cells(72.05, 21.35, 17.59, 39.38, None)
    assert cmp._ttm_one(missing, "eps_basic") is None
    # a Q4 table prints the year itself
    q4 = {("ytd", "pat"): (788.0, "2026-03-31", "fy"), ("current", "pat"): (225.0, "2026-03-31", "quarter")}
    assert cmp._ttm_one(q4, "pat") == pytest.approx(788.0)


def test_eps_tolerance_is_never_scaled():
    """2 units of the item's own printed decimals: a crore table's scale must not turn an EPS check into a
    two-million-rupee tolerance (MARUTI stored 10,953 as 109.63)."""
    assert cmp._tol("eps_basic", 0, 1e6, "10953", 0) == 2.0
    assert cmp._tol("eps_basic", 0, 1e6, "10953", 1) == 0.2
    assert cmp._tol("eps_basic", 2, 1e7, "19.32", 2) == 0.02
    assert cmp._tol("revenue_from_operations", 0, 1e7) == 2e7

    conn = _conn()
    _xbrl(conn, "2026-09-30", "revenue_from_operations", 1000 * 1e6)
    _xbrl(conn, "2026-09-30", "eps_basic", 109.63)
    rows = [ROWS[0], ("2 Other income", ROWS[1][1]), ("3 Total income", ROWS[2][1]),
            ("4 Total expenses", ROWS[3][1]), ("5 Profit before exceptional items and tax", ROWS[4][1]),
            ("6 Total tax expense", ROWS[5][1]), ("7 Profit for the period", ROWS[6][1]),
            ("8 Basic EPS", ("10953", "9.5", "8.4", "20.0", "17.9", "36.8"))]
    stored = _store(conn, rows=rows, unit="Rs. in million")
    eps = _cells(stored, "eps_basic", "current")
    assert eps and eps[0][20] != "xbrl_ok"          # 10953 is not 109.63 within 2 units of the printed paise


def test_margin_and_percent_rows_never_map_to_a_rupee_line():
    assert cmp.match_line("Operating Margin excluding exceptional item (%)") is None
    assert cmp.match_line("Net Debt / Equity Ratio (times)") is None


def test_a_segment_page_is_not_read_and_bracketed_costs_refuse_the_table():
    words = [(40.0, 5.0, 120.0, 13.0, "Segmentwise Results", 0, 0, 0),
             (40.0, 15.0, 110.0, 23.0, "Rs. inCrore", 0, 0, 0)]
    words += [_w(COLS[i], text, 30.0) for i, text in enumerate(DATES)]
    for i, (label, values) in enumerate(ROWS):
        words += _row(50.0 + 10.0 * i, label, values)
    assert cmp.read_page(cmp.rows_from_words(words)) is None

    bracketed = [("1 Revenue from operations", ROWS[0][1]), ("2 Other income", ROWS[1][1]),
                 ("3 Total income", ROWS[2][1]), ("4 Total expenses", ("(800)", "(720)", "(640)", "(1,520)", "(1,360)", "(2,800)")),
                 ("5 Profit before exceptional items and tax", ROWS[4][1]), ("6 Total tax expense", ROWS[5][1]),
                 ("7 Profit for the period", ROWS[6][1]), ("8 Other expenses", ("800", "700", "600", "1,500", "1,300", "2,700"))]
    assert _store(_conn(), rows=bracketed) == []      # mixed: a cost in brackets is not the P&L


def _printed_row(item: str, value: float, known: str, raw: str = "1", status: str = "unchecked",
                 role: str = "current", end: str = "2026-09-30", ptype: str = "quarter") -> tuple:
    return ("AAAA", "INE000A01001", "2026-07-01", end, "Q2FY27", ptype, role, "consolidated", "P&L", item,
            "", value, "inr" if not item.startswith("eps_") else "inr_per_share", 1.0, raw, "q",
            f"doc-{known}", 1, known, "doc.known_at", status, None, 1)


def test_repeat_ok_needs_a_second_filing_and_keeps_each_known_at():
    rows = [
        _printed_row("pat", 1000.0, "2026-02-12T10:00:00", raw="1,000", role="preceding", end="2025-09-30"),
        _printed_row("pat", 1000.0, "2026-10-28T10:00:00", raw="1,000", role="year_ago", end="2025-09-30"),
        _printed_row("pat", 2000.0, "2026-10-28T10:00:00", raw="2,000", role="current", end="2026-09-30"),
        _printed_row("eps_basic", 11.84, "2026-02-12T10:00:00", raw="11.84", role="preceding", end="2025-09-30"),
    ]
    out = cmp._apply_repeats(rows)
    assert out[0][20] == "repeat_ok" and out[1][20] == "repeat_ok"
    assert out[0][18] == "2026-02-12T10:00:00" and out[1][18] == "2026-10-28T10:00:00"
    assert out[2][20] == "unchecked"                   # printed once
    assert out[3][20] == "unchecked"                   # the same filing date does not corroborate itself


# ---------------------------------------------------------------- T-073: five columns, no column slide -----------------------------------
def test_a_five_column_q2_table_keeps_the_last_full_year():
    """A quarter pair + half-year pair + last full year table (INFY) must offer ``last_fy``: without it the TTM
    cannot be formed from that filing at all."""
    assert cmp._role_set("2026-09-30", 5) == ["current", "year_ago", "ytd", "prior_ytd", "last_fy"]
    assert cmp._role_set("2026-09-30", 4) == ["current", "year_ago", "ytd", "prior_ytd"]
    assert cmp._role_set("2026-03-31", 4) == ["current", "preceding", "ytd", "prior_ytd"]
    assert cmp._role_set("2026-06-30", 4) == ["current", "preceding", "year_ago", "last_fy"]
    header = [[(0.0, 0.0, 10.0, 10.0, w, 0, 0, 0)
               for w in "Three months ended Six months ended".split()]]
    assert cmp._layout_hint(header, [1.0, 2.0, 3.0, 4.0, 5.0]) == \
        ["current", "year_ago", "ytd", "prior_ytd", "last_fy"]


def test_a_missing_middle_cell_does_not_shift_the_row():
    """INFY's ``19.32 19.19 17.76 38.51 34.47 71.58`` row lost the Q1 cell to OCR; the remaining tokens must keep
    their own columns, never slide one left (T-073)."""
    row = [_w(200.0, "19.32", 10.0), _w(320.0, "17.76", 10.0),
           _w(380.0, "38.51", 10.0), _w(440.0, "34.47", 10.0)]
    got = cmp._assign_tokens(row, list(COLS))
    assert {at: token["text"] for at, token in got.items()} == \
        {0: "19.32", 2: "17.76", 3: "38.51", 4: "34.47"}


def test_xbrl_index_reads_the_compute_start_input_table():
    """A prior-year printed column is checked against the older quarter held as an input (T-073); the main
    table wins when both hold the quarter."""
    conn = _conn()
    conn.execute("CREATE TABLE fin_quarter_xbrl_input (symbol TEXT, basis TEXT, period_end TEXT, line_item TEXT, value REAL)")
    conn.execute("INSERT INTO fin_quarter_xbrl_input VALUES ('AAAA','consolidated','2024-12-31','eps_basic',9.0)")
    assert cmp.xbrl_index(conn, "AAAA")[("consolidated", "2024-12-31")]["eps_basic"] == 9.0
    _xbrl(conn, "2024-12-31", "eps_basic", 10.0)
    assert cmp.xbrl_index(conn, "AAAA")[("consolidated", "2024-12-31")]["eps_basic"] == 10.0
