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


def test_unit_is_read_only_where_the_page_declares_it():
    """Repair note R-006: a unit word after a figure is a note sentence, not the table's unit."""
    from reality_engine.pilot3.comparatives import _unit

    for text, scale in (("Rs. inCrore", 1e7), ("(tin crore)", 1e7), ("(f in Million)", 1e6), ("llNR crore", 1e7),
                        ("(Rs. In Lakhs)", 1e5), ("(Rin lakhs ) PARTICULARS", 1e5), ("Rs on Lakhs Year Ended", 1e5),
                        ("Rs. rnlakhs Year Ended", 1e5), ("quarter ended march cin lakhs", 1e5)):
        assert _unit(text) == scale, text
    assert _unit("has already made a provision of Rs. 20 crore during the year") is None
    assert _unit("exceptional item includes Rs 17.82 crore towards arbitration") is None


# ---------------------------------------------------------------- R-020: June-end layouts never write FYFY ytd rows ----------------
def test_june_role_sets_and_quarter_guard():
    assert cmp._role_set("2026-06-30", 4) == ["current", "preceding", "year_ago", "last_fy"]
    assert cmp._role_set("2026-06-30", 5) == ["current", "preceding", "year_ago", None, "last_fy"]
    assert cmp._role_set("2026-06-30", 6) == ["current", "preceding", "year_ago", None, None, "last_fy"]
    assert cmp._role_set("2026-06-30", 8) == ["current", "preceding", "year_ago", "last_fy"]
    assert cmp._quarter("2026-06-30", "ytd") is None
    assert cmp._quarter("2026-03-31", "ytd") is None
    assert cmp._quarter("2026-09-30", "ytd") == ("H1FY27", "2026-04-01", "ytd")


def _june_rows(vals_per_row):
    return [
        ("1 Revenue from operations", vals_per_row[0]),
        ("2 Other income", vals_per_row[1]),
        ("3 Total income", vals_per_row[2]),
        ("4 Total expenses", vals_per_row[3]),
        ("5 Profit before exceptional items and tax", vals_per_row[4]),
        ("6 Total tax expense", vals_per_row[5]),
        ("7 Profit for the period", vals_per_row[6]),
        ("8 Basic EPS", vals_per_row[7]),
    ]


def _page_n(rows, dates, title="Statement of Standalone Unaudited Financial Results",
            subhead="", unit="Rs. inCrore"):
    cols = tuple(200.0 + 70.0 * i for i in range(len(dates)))
    words = [(40.0, 5.0, 120.0, 13.0, title, 0, 0, 0), (40.0, 15.0, 110.0, 23.0, unit, 0, 0, 0)]
    if subhead:
        words.append((200.0, 20.0, 480.0, 28.0, subhead, 0, 0, 0))
    words += [(cols[i] - 7.0 * len(text), 27.0, cols[i], 33.0, text, 0, 0, 0) for i, text in enumerate(dates)]
    for idx, (label, values) in enumerate(rows):
        y = 50.0 + 10.0 * idx
        x = 20.0
        for word in label.split():
            w = 7.0 * len(word)
            words.append((x, y - 3.0, x + w, y + 3.0, word, 0, 0, 0))
            x += w + 3.0
        words += [(cols[i] - 7.0 * len(v), y - 3.0, cols[i], y + 3.0, v, 0, 0, 0) for i, v in enumerate(values)]
    return cmp.rows_from_words(words)


def test_june_five_col_two_fy_layout_takes_last_fy_and_drops_prior_fy():
    """MENONBE layout: Q1, Q4, Q1-1, FY25, FY24 -> col 3 is last_fy, col 4 writes nothing, 0 FYFY."""
    dates = ("30.06.2025", "31.03.2025", "30.06.2024", "31.03.2025", "31.03.2024")
    rows = _june_rows([
        ("500", "450", "400", "1,700", "2,000"),
        ("10", "10", "10", "40", "50"),
        ("510", "460", "410", "1,740", "2,050"),
        ("400", "360", "320", "1,400", "1,650"),
        ("110", "100", "90", "340", "400"),
        ("28", "25", "22", "85", "100"),
        ("82", "75", "68", "255", "300"),
        ("1.5", "1.4", "1.2", "4.5", "5.3"),
    ])
    table = cmp.read_page(_page_n(rows, dates))
    stored = cmp._table_rows(_conn(), "AAAA", "INE000A01001", "doc1", 5, "2025-07-25T12:00:00", table, {}, [])
    assert not any(r[4].startswith("FYFY") or r[5] == "ytd" for r in stored)
    rev_last = _cells(stored, "revenue_from_operations", "last_fy")
    assert len(rev_last) == 1 and rev_last[0][3] == "2025-03-31" and rev_last[0][4] == "FY25"
    assert rev_last[0][11] == 1700 * 1e7


def test_june_five_col_ytd_plus_fy_layout_takes_col4_as_last_fy():
    """HYPERSOFT layout: Q1, Q4, Q1-1, Q1-YTD (30.06), FY25 (31.03) -> col 3 writes nothing, col 4 is last_fy."""
    dates = ("30.06.2025", "31.03.2025", "30.06.2024", "30.06.2025", "31.03.2025")
    rows = _june_rows([
        ("992.00", "777.00", "14.00", "992.00", "805.00"),
        ("3.00", "5.00", "3.00", "3.00", "6.00"),
        ("995.00", "782.00", "17.00", "995.00", "811.00"),
        ("882.00", "654.00", "18.00", "882.00", "763.00"),
        ("113.00", "128.00", "(1.00)", "113.00", "48.00"),
        ("29.00", "13.00", "0.00", "29.00", "13.00"),
        ("84.00", "115.00", "(1.00)", "84.00", "35.00"),
        ("2.00", "2.70", "0.00", "2.00", "0.80"),
    ])
    table = cmp.read_page(_page_n(rows, dates))
    stored = cmp._table_rows(_conn(), "AAAA", "INE000A01001", "doc1", 4, "2025-08-13T12:00:00", table, {}, [])
    assert not any(r[4].startswith("FYFY") or r[5] == "ytd" for r in stored)
    rev_last = _cells(stored, "revenue_from_operations", "last_fy")
    assert len(rev_last) == 1 and rev_last[0][3] == "2025-03-31" and rev_last[0][4] == "FY25"
    assert rev_last[0][11] == 805 * 1e7


def test_june_six_col_december_year_skips_six_month_columns():
    """RSYSTEMS layout: 3M cols + 6M June-end cols + Dec-year FY -> 6M cols write nothing, no FYFY."""
    dates = ("30.06.2026", "31.03.2026", "30.06.2025", "30.06.2026", "30.06.2025", "31.12.2025")
    rows = _june_rows([
        ("600", "575", "462", "1,175", "904", "1,958"),
        ("1", "17", "47", "18", "49", "54"),
        ("601", "592", "509", "1,193", "953", "2,012"),
        ("522", "502", "410", "1,024", "798", "1,732"),
        ("79", "90", "99", "169", "155", "280"),
        ("25", "24", "23", "49", "41", "69"),
        ("54", "66", "76", "120", "114", "211"),
        ("4.5", "5.5", "6.3", "10.0", "9.5", "17.6"),
    ])
    table = cmp.read_page(_page_n(rows, dates, subhead="Three months ended Six months ended Year ended"))
    store_fy = {("unchecked", "2026-03-31"): {"revenue_from_operations": [1958 * 1e7]}}
    stored = cmp._table_rows(_conn(), "AAAA", "INE000A01001", "doc1", 3, "2026-08-04T12:00:00",
                             table, {}, [], store_fy=store_fy)
    assert not any(r[4].startswith("FYFY") or r[5] == "ytd" for r in stored)
    assert {r[6] for r in stored} == {"current", "preceding", "year_ago", "last_fy"}
    assert _cells(stored, "revenue_from_operations", "last_fy")[0][11] == 1958 * 1e7


def test_june_eight_col_side_by_side_reads_standalone_last_fy_only():
    """8-col side-by-side Q1 (BLKASHYAP/SESHAPAPER): col 3 is standalone last_fy, cols 4-7 write nothing."""
    dates = ("30.06.2026", "31.03.2026", "30.06.2025", "31.03.2026",
             "30.06.2026", "31.03.2026", "30.06.2025", "31.03.2026")
    rows = _june_rows([
        ("492.00", "591.00", "385.00", "1,710.00", "493.00", "592.00", "386.00", "1,711.00"),
        ("13.00", "12.00", "14.00", "49.00", "12.00", "12.00", "14.00", "49.00"),
        ("505.00", "603.00", "399.00", "1,759.00", "505.00", "604.00", "400.00", "1,760.00"),
        ("460.00", "570.00", "360.00", "1,650.00", "461.00", "571.00", "361.00", "1,651.00"),
        ("45.00", "33.00", "39.00", "109.00", "44.00", "33.00", "39.00", "109.00"),
        ("11.00", "6.00", "13.00", "24.00", "12.00", "6.00", "13.00", "24.00"),
        ("34.00", "27.00", "26.00", "85.00", "32.00", "27.00", "26.00", "85.00"),
        ("5.60", "4.50", "4.30", "14.10", "5.30", "4.50", "4.30", "14.10"),
    ])
    table = cmp.read_page(_page_n(rows, dates, title="Statement of Standalone and Consolidated Financial Results"))
    stored = cmp._table_rows(_conn(), "AAAA", "INE000A01001", "doc1", 2, "2026-08-05T12:00:00", table, {}, [])
    assert not any(r[4].startswith("FYFY") or r[5] == "ytd" for r in stored)
    assert {r[6] for r in stored} == {"current", "preceding", "year_ago", "last_fy"}
    assert _cells(stored, "revenue_from_operations", "last_fy")[0][11] == 1710 * 1e7


def test_date_match_requires_year_when_requested():
    assert cmp._date_match((3, 2024), (3, 2024), require_year=True)
    assert cmp._date_match((None, 2024), (3, 2024), require_year=True)
    assert not cmp._date_match((3, None), (3, 2024), require_year=True)
    assert not cmp._date_match((3, 2023), (3, 2024), require_year=True)


def test_june_five_col_incomplete_year_row_and_store_fy_resolution():
    """HYPERSOFT b4e661b1 layout: 5 date cells with 4 years on next line resolves FY24 over FY23;
    without any year match or FY reference, neither annual column is guessed."""
    rows = _june_rows([
        ("13.93", "18.85", "24.60", "82.60", "86.95"),
        ("3.37", "3.96", "1.57", "10.40", "9.05"),
        ("17.30", "22.81", "26.17", "93.07", "96.00"),
        ("18.49", "36.65", "28.52", "118.09", "104.37"),
        ("(1.19)", "(13.84)", "(2.35)", "(25.02)", "(8.37)"),
        ("0.00", "0.00", "0.00", "0.00", "0.00"),
        ("(1.19)", "(13.84)", "(2.35)", "(25.02)", "(8.37)"),
        ("(0.03)", "(0.33)", "(0.06)", "(0.59)", "(0.20)"),
    ])
    # 1) Split header: col 0 has June 30, 2024; cols 1..4 put years 2024, 2023, 2024, 2023 on the row below.
    cols = tuple(200.0 + 70.0 * i for i in range(5))
    top_dates = ("June, 30, 2024", "March, 31,", "June, 30,", "March 31,", "March 31,")
    sub_years = ("2024", "2023", "2024", "2023")
    words = [
        (40.0, 5.0, 180.0, 13.0, "Statement of Audited Financial Results for the quarter ended 30-06-2024", 0, 0, 0),
        (40.0, 15.0, 110.0, 23.0, "Rs. in Lakhs", 0, 0, 0),
    ]
    for i, t in enumerate(top_dates):
        cx = cols[i] - 48.0
        for part in t.split():
            pw = 6.0 * len(part)
            words.append((cx, 24.0, cx + pw, 30.0, part, 0, 0, 0))
            cx += pw + 2.0
    words += [(cols[i + 1] - 28.0, 32.0, cols[i + 1], 38.0, y, 0, 0, 0) for i, y in enumerate(sub_years)]
    for idx, (label, values) in enumerate(rows):
        y = 50.0 + 10.0 * idx
        x = 20.0
        for word in label.split():
            w = 7.0 * len(word)
            words.append((x, y - 3.0, x + w, y + 3.0, word, 0, 0, 0))
            x += w + 3.0
        words += [(cols[i] - 7.0 * len(v), y - 3.0, cols[i], y + 3.0, v, 0, 0, 0) for i, v in enumerate(values)]
    table = cmp.read_page(cmp.rows_from_words(words))
    assert table["dates"] == [(6, 2024), (3, 2024), (6, 2023), (3, 2024), (3, 2023)]
    stored = cmp._table_rows(_conn(), "HYP", "INE000A01001", "doc1", 6, "2024-08-05T12:00:00", table, {}, [])
    rev_last = _cells(stored, "revenue_from_operations", "last_fy")
    assert len(rev_last) == 1 and rev_last[0][11] == pytest.approx(82.60 * 1e5)

    # 2) Strip header years completely: without store_fy/XBRL, writes nothing for last_fy;
    #    with store_fy holding FY24, resolves col 3 (FY24) rather than defaulting to col 4 (FY23).
    table_no_yr = dict(table, dates=[(6, 2024), (3, None), (6, None), (3, None), (3, None)])
    stored_none = cmp._table_rows(_conn(), "HYP", "INE000A01001", "doc1", 6, "2024-08-05T12:00:00", table_no_yr, {}, [])
    assert _cells(stored_none, "revenue_from_operations", "last_fy") == []

    store_fy = {("unchecked", "2024-03-31"): {"total_income": [93.07 * 1e5], "other_income": [10.40 * 1e5]}}
    stored_fy = cmp._table_rows(_conn(), "HYP", "INE000A01001", "doc1", 6, "2024-08-05T12:00:00",
                                table_no_yr, {}, [], store_fy=store_fy)
    rev_last_fy = _cells(stored_fy, "revenue_from_operations", "last_fy")
    assert len(rev_last_fy) == 1 and rev_last_fy[0][11] == pytest.approx(82.60 * 1e5)


def test_june_eight_col_halves_must_match():
    """Wide June pages whose halves differ (or single-basis mixed tables) are never read as Sx4+Cx4."""
    dates = ("30.06.2026", "31.03.2026", "30.06.2025", "31.03.2026",
             "30.06.2026", "30.09.2025", "30.06.2025", "31.03.2026")
    rows = _june_rows([("100",) * 8, ("10",) * 8, ("110",) * 8, ("90",) * 8,
                       ("20",) * 8, ("5",) * 8, ("15",) * 8, ("1.0",) * 8])
    t_mismatch = cmp.read_page(_page_n(rows, dates, title="Statement of Standalone and Consolidated Financial Results"))
    assert cmp._table_rows(_conn(), "AAAA", "INE000A01001", "doc1", 2, "2026-08-05T12:00:00", t_mismatch, {}, []) == []

    dates_ok = ("30.06.2026", "31.03.2026", "30.06.2025", "31.03.2026") * 2
    t_single = cmp.read_page(_page_n(rows, dates_ok, title="Statement of Standalone Financial Results"))
    assert cmp._table_rows(_conn(), "AAAA", "INE000A01001", "doc1", 8, "2026-08-05T12:00:00", t_single, {}, []) == []


def test_header_dates_merges_split_column_across_adjacent_rows():
    """KITEX a8bc224d p8: March31 shifted one row up and 2024 one row down still resolves all 4 cols."""
    rows = _june_rows([
        ("500.00", "450.00", "400.00", "1,700.00"),
        ("10.00", "10.00", "10.00", "40.00"),
        ("510.00", "460.00", "410.00", "1,740.00"),
        ("400.00", "360.00", "320.00", "1,400.00"),
        ("110.00", "100.00", "90.00", "340.00"),
        ("28.00", "25.00", "22.00", "85.00"),
        ("82.00", "75.00", "68.00", "255.00"),
        ("1.50", "1.40", "1.20", "4.50"),
    ])
    cols = (200.0, 270.0, 340.0, 410.0)
    words = [
        (40.0, 5.0, 220.0, 13.0, "Statement of Consolidated Financial Results for the quarter ended June 30, 2024", 0, 0, 0),
        (40.0, 15.0, 110.0, 23.0, "Rupees in lakhs", 0, 0, 0),
        (cols[1] - 42.0, 22.0, cols[1], 28.0, "March31", 0, 0, 0),
        (cols[0] - 48.0, 30.0, cols[0] - 28.0, 36.0, "June", 0, 0, 0),
        (cols[0] - 26.0, 30.0, cols[0] - 14.0, 36.0, "30,", 0, 0, 0),
        (cols[0] - 12.0, 30.0, cols[0], 36.0, "2024", 0, 0, 0),
        (cols[2] - 48.0, 30.0, cols[2] - 28.0, 36.0, "June", 0, 0, 0),
        (cols[2] - 26.0, 30.0, cols[2] - 14.0, 36.0, "30,", 0, 0, 0),
        (cols[2] - 12.0, 30.0, cols[2], 36.0, "2023", 0, 0, 0),
        (cols[3] - 48.0, 30.0, cols[3] - 28.0, 36.0, "March", 0, 0, 0),
        (cols[3] - 26.0, 30.0, cols[3] - 14.0, 36.0, "31,", 0, 0, 0),
        (cols[3] - 12.0, 30.0, cols[3], 36.0, "2024", 0, 0, 0),
        (cols[1] - 24.0, 38.0, cols[1], 44.0, "2024", 0, 0, 0),
    ]
    for idx, (label, values) in enumerate(rows):
        y = 55.0 + 10.0 * idx
        x = 20.0
        for word in label.split():
            w = 7.0 * len(word)
            words.append((x, y - 3.0, x + w, y + 3.0, word, 0, 0, 0))
            x += w + 3.0
        words += [(cols[i] - 7.0 * len(v), y - 3.0, cols[i], y + 3.0, v, 0, 0, 0) for i, v in enumerate(values)]
    table = cmp.read_page(cmp.rows_from_words(words))
    assert table["dates"] == [(6, 2024), (3, 2024), (6, 2023), (3, 2024)]
    stored = cmp._table_rows(_conn(), "KITEX", "INE000A01001", "doc1", 8, "2024-08-12T12:00:00", table, {}, [])
    rev_last = _cells(stored, "revenue_from_operations", "last_fy")
    assert len(rev_last) == 1 and rev_last[0][3] == "2024-03-31" and rev_last[0][11] == 1700 * 1e5


def test_page_basis_matches_space_split_standalone_before_consolidated():
    """NILKAMAL 442ae482 p5: 'Standa lone' on left and 'Consolidated' on right stores both halves with right bases."""
    assert cmp._page_basis("UNAUDITED FINANCIAL RESULTS Standa lone Consolidated") == "standalone"
    dates = ("30.06.2025", "31.03.2025", "30.06.2024", "31.03.2025") * 2
    rows = _june_rows([
        ("500.00", "450.00", "400.00", "1,700.00", "900.00", "850.00", "800.00", "3,200.00"),
        ("10.00", "10.00", "10.00", "40.00", "20.00", "20.00", "20.00", "80.00"),
        ("510.00", "460.00", "410.00", "1,740.00", "920.00", "870.00", "820.00", "3,280.00"),
        ("400.00", "360.00", "320.00", "1,400.00", "700.00", "650.00", "600.00", "2,600.00"),
        ("110.00", "100.00", "90.00", "340.00", "220.00", "220.00", "220.00", "680.00"),
        ("28.00", "25.00", "22.00", "85.00", "55.00", "55.00", "55.00", "170.00"),
        ("82.00", "75.00", "68.00", "255.00", "165.00", "165.00", "165.00", "510.00"),
        ("1.50", "1.40", "1.20", "4.50", "3.00", "3.00", "3.00", "9.50"),
    ])
    table = cmp.read_page(_page_n(rows, dates, title="Financial Results Standa lone Consolidated"))
    stored = cmp._table_rows(_conn(), "NIL", "INE000A01001", "doc1", 5, "2025-08-01T12:00:00", table, {}, [])
    assert stored and {r[7] for r in stored} == {"standalone", "consolidated"}
    sa_rev = [r for r in stored if r[7] == "standalone" and r[9] == "revenue_from_operations" and r[6] == "last_fy"]
    co_rev = [r for r in stored if r[7] == "consolidated" and r[9] == "revenue_from_operations" and r[6] == "last_fy"]
    assert sa_rev[0][11] == 1700 * 1e7 and co_rev[0][11] == 3200 * 1e7


def test_june_last_fy_drops_unchecked_cell_when_text_and_ocr_disagree():
    """BLKASHYAP abba81be p2: unconfirmed last_fy text-layer 5,191.84 vs OCR 8,191.84 writes nothing."""
    dates = ("30.06.2024", "31.03.2024", "30.06.2023", "31.03.2024")
    base_rows = _june_rows([
        ("500.00", "450.00", "400.00", "1,700.00"),
        ("10.00", "10.00", "10.00", "40.00"),
        ("510.00", "460.00", "410.00", "1,740.00"),
        ("400.00", "360.00", "320.00", "1,400.00"),
        ("110.00", "100.00", "90.00", "340.00"),
        ("28.00", "25.00", "22.00", "85.00"),
        ("82.00", "75.00", "68.00", "255.00"),
        ("1.50", "1.40", "1.20", "4.50"),
    ])
    text_rows = base_rows + [("Other expenses", ("100.00", "90.00", "80.00", "519.18"))]
    ocr_rows = base_rows + [("Other expenses", ("100.00", "90.00", "80.00", "819.18"))]
    t_text = cmp.read_page(_page_n(text_rows, dates))
    t_ocr = cmp.read_page(_page_n(ocr_rows, dates), ocr=True)
    review: list[dict] = []
    stored = cmp._table_rows(_conn(), "BLK", "INE000A01001", "doc1", 2, "2024-08-14T12:00:00",
                             t_text, {}, review, fill_table=t_ocr)
    assert _cells(stored, "other_expenses", "last_fy") == []
    assert any(r["check"] == "ocr_text_disagree" and r["line_item"] == "other_expenses" for r in review)
    assert _cells(stored, "total_income", "last_fy")[0][11] == 1740 * 1e7


def test_side_by_side_non_june_10col_stores_both_bases():
    """MICEL a8f6ea20 p2: 10-column STAND-ALONE | CONSOLIDATED table stores all columns for both bases."""
    dates = ("31.03.2026", "31.12.2025", "31.03.2025", "31.03.2026", "31.03.2025") * 2
    rows = _june_rows([
        ("500.00", "450.00", "400.00", "1,700.00", "1,500.00", "900.00", "850.00", "800.00", "3,200.00", "2,800.00"),
        ("10.00", "10.00", "10.00", "40.00", "30.00", "20.00", "20.00", "20.00", "80.00", "60.00"),
        ("510.00", "460.00", "410.00", "1,740.00", "1,530.00", "920.00", "870.00", "820.00", "3,280.00", "2,860.00"),
        ("400.00", "360.00", "320.00", "1,400.00", "1,200.00", "700.00", "650.00", "600.00", "2,600.00", "2,200.00"),
        ("110.00", "100.00", "90.00", "340.00", "330.00", "220.00", "220.00", "220.00", "680.00", "660.00"),
        ("28.00", "25.00", "22.00", "85.00", "80.00", "55.00", "55.00", "55.00", "170.00", "160.00"),
        ("82.00", "75.00", "68.00", "255.00", "250.00", "165.00", "165.00", "165.00", "510.00", "500.00"),
        ("1.50", "1.40", "1.20", "4.50", "4.00", "3.00", "3.00", "3.00", "9.50", "9.00"),
    ])
    table = cmp.read_page(_page_n(rows, dates, title="Financial Results STAND-ALONE CONSOLIDATED"))
    stored = cmp._table_rows(_conn(), "MICEL", "INE000A01001", "doc1", 2, "2026-05-15T12:00:00", table, {}, [])
    sa = [r for r in stored if r[7] == "standalone" and r[9] == "revenue_from_operations"]
    co = [r for r in stored if r[7] == "consolidated" and r[9] == "revenue_from_operations"]
    assert {r[6]: r[11] for r in sa}["current"] == 500 * 1e7
    assert {r[6]: r[11] for r in co}["current"] == 900 * 1e7
    assert {r[6]: r[11] for r in sa}["ytd"] == 1700 * 1e7
    assert {r[6]: r[11] for r in co}["ytd"] == 3200 * 1e7



def test_side_by_side_half_with_empty_column_does_not_crash():
    """c91 drift run 18 Nov: a split half whose current column holds no figure raised KeyError in _choose_rows."""
    dates = ("31.03.2026", "31.12.2025", "31.03.2025", "31.03.2026", "31.03.2025") * 2
    rows = _june_rows([
        ("500.00", "450.00", "400.00", "1,700.00", "1,500.00", "900.00", "850.00", "800.00", "3,200.00", "2,800.00"),
        ("10.00", "10.00", "10.00", "40.00", "30.00", "20.00", "20.00", "20.00", "80.00", "60.00"),
        ("510.00", "460.00", "410.00", "1,740.00", "1,530.00", "920.00", "870.00", "820.00", "3,280.00", "2,860.00"),
        ("400.00", "360.00", "320.00", "1,400.00", "1,200.00", "700.00", "650.00", "600.00", "2,600.00", "2,200.00"),
        ("110.00", "100.00", "90.00", "340.00", "330.00", "220.00", "220.00", "220.00", "680.00", "660.00"),
        ("28.00", "25.00", "22.00", "85.00", "80.00", "55.00", "55.00", "55.00", "170.00", "160.00"),
        ("82.00", "75.00", "68.00", "255.00", "250.00", "165.00", "165.00", "165.00", "510.00", "500.00"),
        ("1.50", "1.40", "1.20", "4.50", "4.00", "3.00", "3.00", "3.00", "9.50", "9.00"),
    ]) + [("9 Basic EPS", ("1.50", "1.40", "1.20", "4.50", "4.00", "3.00", "3.00", "3.00", "9.50", "9.00"))]
    table = cmp.read_page(_page_n(rows, dates, title="Financial Results STAND-ALONE CONSOLIDATED"))
    table["values"].pop(5, None)
    halves = cmp._split_side_by_side(table)
    assert halves is not None and halves[1]["values"][0] == {}
    cmp._table_rows(_conn(), "MICEL", "INE000A01001", "doc1", 2, "2026-05-15T12:00:00", table, {}, [])


def test_side_by_side_eps_decimals_come_from_whole_table():
    """c91 03fcddb7 p3: standalone half prints EPS '213 181' (points lost), consolidated '1.90 3.04': 2.13, not 213."""
    dates = ("30.06.2025", "31.03.2025", "30.06.2024", "31.03.2025") * 2
    rows = _june_rows([
        ("500.00", "450.00", "400.00", "1,700.00", "900.00", "850.00", "800.00", "3,200.00"),
        ("10.00", "10.00", "10.00", "40.00", "20.00", "20.00", "20.00", "80.00"),
        ("510.00", "460.00", "410.00", "1,740.00", "920.00", "870.00", "820.00", "3,280.00"),
        ("400.00", "360.00", "320.00", "1,400.00", "700.00", "650.00", "600.00", "2,600.00"),
        ("110.00", "100.00", "90.00", "340.00", "220.00", "220.00", "220.00", "680.00"),
        ("28.00", "25.00", "22.00", "85.00", "55.00", "55.00", "55.00", "170.00"),
        ("82.00", "75.00", "68.00", "255.00", "165.00", "165.00", "165.00", "510.00"),
        ("213", "181", "050", "294", "2.15", "1.90", "0.50", "3.04"),
    ])
    table = cmp.read_page(_page_n(rows, dates, title="Financial Results STANDALONE CONSOLIDATED"))
    halves = cmp._split_side_by_side(table)
    assert halves is not None and all(h["eps_decimals"] == 2 for h in halves)
    stored = cmp._table_rows(_conn(), "C91", "INE000A01001", "doc1", 3, "2025-08-01T12:00:00", table, {}, [])
    sa = {r[6]: r[11] for r in stored if r[7] == "standalone" and r[9] == "eps_basic"}
    assert sa and all(v < 10 for v in sa.values()), sa
    # review ac3eb3e4: every call site on a half (fill path, role scoring, June last_fy) sees the same count
    assert all(cmp._eps_decimals(h["values"]) == 2 for h in halves)
    fill_halves = cmp._split_side_by_side(cmp.read_page(_page_n(rows, dates,
                                                             title="Financial Results STANDALONE CONSOLIDATED"),
                                                     ocr=True))
    assert fill_halves is not None and all(cmp._eps_decimals(h["values"]) == 2 for h in fill_halves)

def test_fill_negative_cost_does_not_abort_text_layer_table():
    """GREENPOWER c1e7c4d2 p27: OCR fill reading '(228)' on a missing cost cell never rejects the clean table."""
    dates = ("30.06.2025", "31.03.2025", "30.06.2024", "31.03.2025")
    base_rows = _june_rows([
        ("500.00", "450.00", "400.00", "1,700.00"),
        ("10.00", "10.00", "10.00", "40.00"),
        ("510.00", "460.00", "410.00", "1,740.00"),
        ("400.00", "360.00", "320.00", "1,400.00"),
        ("110.00", "100.00", "90.00", "340.00"),
        ("28.00", "25.00", "22.00", "85.00"),
        ("82.00", "75.00", "68.00", "255.00"),
        ("1.50", "1.40", "1.20", "4.50"),
    ])
    t_text = cmp.read_page(_page_n(base_rows, dates))
    t_ocr = cmp.read_page(_page_n(base_rows + [("Finance costs", ("5.00", "4.00", "(228)", "20.00"))], dates), ocr=True)
    review: list[dict] = []
    stored = cmp._table_rows(_conn(), "GRN", "INE000A01001", "doc1", 27, "2025-08-01T12:00:00",
                             t_text, {}, review, fill_table=t_ocr)
    assert stored and not any(r["check"] == "not_pl_costs" for r in review)
    assert [r for r in stored if r[9] == "finance_cost" and r[6] == "year_ago"] == []


def test_continuation_recovers_bottom_of_pl_above_notes():
    """MENONBE 0e806637 p8: continuation stops before 'Notes:-' summary table and recovers OCI/TCI/EPS."""
    dates = ("30.06.2025", "31.03.2025", "30.06.2024", "31.03.2025")
    prev_rows = _june_rows([
        ("500.00", "450.00", "400.00", "1,700.00"),
        ("10.00", "10.00", "10.00", "40.00"),
        ("510.00", "460.00", "410.00", "1,740.00"),
        ("400.00", "360.00", "320.00", "1,400.00"),
        ("110.00", "100.00", "90.00", "340.00"),
        ("28.00", "25.00", "22.00", "85.00"),
        ("82.00", "75.00", "68.00", "255.00"),
        ("1.50", "1.40", "1.20", "4.50"),
    ])[:-1] + [("Cost of materials consumed", ("200.00", "180.00", "160.00", "700.00"))]  # 8 rows ending without EPS
    previous = cmp.read_page(_page_n(prev_rows, dates))
    cols = previous["anchors"]
    words = []
    cont_items = [
        ("Total Other Comprehensive Income", ("3.36", "15.77", "0.54", "(19.21)")),
        ("Total Comprehensive Income", ("846.30", "676.40", "616.23", "2,474.25")),
        ("Basic EPS", ("1.50", "1.18", "1.10", "4.45")),
        ("Diluted EPS", ("1.50", "1.18", "1.10", "4.45")),
    ]
    for idx, (lbl, vals) in enumerate(cont_items):
        y = 40.0 + 10.0 * idx
        words.append((20.0, y - 3.0, 140.0, y + 3.0, lbl, 0, 0, 0))
        words += [(cols[i] - 7.0 * len(v), y - 3.0, cols[i], y + 3.0, v, 0, 0, 0) for i, v in enumerate(vals)]
    # Notes:- 3-column summary below continuation
    words.append((20.0, 100.0, 70.0, 106.0, "Notes:-", 0, 0, 0))
    for r_i, (lbl, v1, v2, v3) in enumerate([("Total Income", "6880.64", "5838.99", "17.84"),
                                            ("PAT", "842.95", "615.69", "36.91"),
                                            ("PBT", "1106.08", "822.83", "34.42")]):
        y = 120.0 + 10.0 * r_i
        words.append((20.0, y - 3.0, 100.0, y + 3.0, lbl, 0, 0, 0))
        words += [(260.0 + 80.0 * k, y - 3.0, 310.0 + 80.0 * k, y + 3.0, val, 0, 0, 0)
                  for k, val in enumerate((v1, v2, v3))]
    cont = cmp._continuation(cmp.rows_from_words(words), previous)
    assert cont is not None and len(cont["anchors"]) == 4
    stored = cmp._table_rows(_conn(), "MEN", "INE000A01001", "doc1", 8, "2025-07-26T12:00:00", cont, {}, [])
    cur = {r[9]: r[11] for r in stored if r[6] == "current"}
    assert cur["other_comprehensive_income"] == 3.36 * 1e7
    assert cur["total_comprehensive_income"] == 846.30 * 1e7
    assert cur["eps_basic"] == 1.50


def test_leading_comma_ocr_token_does_not_veto_clean_text():
    """ESTER 125d3c0e p7: OCR ',036.28' returns None so it never triggers ocr_text_disagree on clean 7,036.28."""
    assert cmp.read_number(",036.28", 2) is None
    dates = ("30.06.2024", "31.03.2024", "30.06.2023", "31.03.2024")
    base_rows = _june_rows([
        ("500.00", "450.00", "400.00", "1,700.00"),
        ("10.00", "10.00", "10.00", "40.00"),
        ("510.00", "460.00", "410.00", "1,740.00"),
        ("400.00", "360.00", "320.00", "1,400.00"),
        ("110.00", "100.00", "90.00", "340.00"),
        ("28.00", "25.00", "22.00", "85.00"),
        ("82.00", "75.00", "68.00", "255.00"),
        ("1.50", "1.40", "1.20", "4.50"),
    ])
    t_text = cmp.read_page(_page_n(base_rows + [("Finance costs", ("16.76", "17.98", "16.76", "7,036.28"))], dates))
    t_ocr = cmp.read_page(_page_n(base_rows + [("Finance costs", ("16.76", "17.98", "16.76", ",036.28"))], dates), ocr=True)
    review: list[dict] = []
    stored = cmp._table_rows(_conn(), "EST", "INE000A01001", "doc1", 7, "2024-08-12T12:00:00",
                             t_text, {}, review, fill_table=t_ocr)
    fc = _cells(stored, "finance_cost", "last_fy")
    assert len(fc) == 1 and fc[0][11] == 7036.28 * 1e7
    assert not any(r["check"] == "ocr_text_disagree" for r in review)


# ---------------------------------------------------------------- R-013: jumbled layer + OCR lead rule -------------------------------
def _build_pdf_and_ocr(tmp_dir, layer_rows, ocr_rows, *, title="Statement of Consolidated Unaudited Financial Results",
                       unit="Rs. inCrore", dates=DATES, jumbled: bool = True, cols=COLS,
                       xbrl_rows=(), extra_docs=()):
    import csv
    import json
    import pymupdf

    tmp_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = tmp_dir / "res.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=800, height=600)
    page.insert_text((40, 20), title, fontsize=8)
    page.insert_text((40, 35), unit, fontsize=8)
    for anchor, dtext in zip(cols, dates):
        w = pymupdf.get_text_length(dtext, fontsize=7)
        page.insert_text((anchor - w, 50), dtext, fontsize=7)
    for idx, (label, values) in enumerate(layer_rows):
        y = 70.0 + 14.0 * idx
        page.insert_text((20, y), label, fontsize=7)
        for anchor, val in zip(cols, values):
            w = pymupdf.get_text_length(val, fontsize=7)
            page.insert_text((anchor - w, y), val, fontsize=7)
    if jumbled:
        # 45 vowel-carrying non-words push page_words.dictionary_score below 0.75 while keeping the table readable
        for i in range(15):
            page.insert_text((20, 320 + 12 * i), f"Zxv{i}omer Qlarton{i} Vroptex{i}", fontsize=7)
    doc.save(str(pdf_path))
    doc.close()

    ocr_db = tmp_dir / "store_ocr.db"
    ocr_db.unlink(missing_ok=True)
    if ocr_rows is not None:
        ocon = sqlite3.connect(str(ocr_db))
        ocon.execute("CREATE TABLE ocr_page (symbol TEXT, doc_key TEXT, page INTEGER, doc_type TEXT, "
                     "known_at TEXT, text TEXT, words_json TEXT, ocr_conf REAL, n_boxes INTEGER, dpi INTEGER, "
                     "seconds REAL, method TEXT)")
        ocr_words = [[40.0, 5.0, 180.0, 13.0, title, 0.95], [40.0, 15.0, 110.0, 23.0, unit, 0.95]]
        for anchor, dtext in zip(cols, dates):
            ocr_words.append([anchor - 7.0 * len(dtext), 27.0, anchor, 33.0, dtext, 0.95])
        for idx, (label, values) in enumerate(ocr_rows):
            y = 50.0 + 10.0 * idx
            x = 20.0
            for word in label.split():
                width = 7.0 * len(word)
                ocr_words.append([x, y - 3.0, x + width, y + 3.0, word, 0.95])
                x += width + 3.0
            for anchor, val in zip(cols, values):
                ocr_words.append([anchor - 7.0 * len(val), y - 3.0, anchor, y + 3.0, val, 0.95])
        ocon.execute("INSERT INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("AAAA", "res.pdf", 1, "results", "2026-10-20T12:00:00", "ocr", json.dumps(ocr_words),
                      0.95, len(ocr_words), 300, 1.0, "ocr_textrec"))
        ocon.commit()
        ocon.close()

    store_db = tmp_dir / "store.db"
    store_db.unlink(missing_ok=True)
    conn = sqlite3.connect(str(store_db))
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
    for basis, end, item, val in xbrl_rows:
        conn.execute("INSERT INTO fin_quarter_xbrl (symbol, basis, period_start, period_end, fiscal_period, "
                     "line_item, value, known_at) VALUES ('AAAA', ?, '2026-04-01', ?, 'Q1FY27', ?, ?, "
                     "'2026-10-19T10:00:00')", (basis, end, item, val))
    conn.execute("INSERT INTO doc VALUES ('res.pdf','AAAA','INE000A01001','results','results','Results',"
                 "'2026-10-20','2026-10-20T12:00:00',1,'sha1','bse',?)", (str(pdf_path),))
    for dk, fdate, k_at, e_rows, e_dates, e_cols in extra_docs:
        epath = tmp_dir / f"{dk}.pdf"
        edoc = pymupdf.open()
        epage = edoc.new_page(width=800, height=600)
        epage.insert_text((40, 20), title, fontsize=8)
        epage.insert_text((40, 35), unit, fontsize=8)
        for anchor, dtext in zip(e_cols, e_dates):
            w = pymupdf.get_text_length(dtext, fontsize=7)
            epage.insert_text((anchor - w, 50), dtext, fontsize=7)
        for idx, (label, values) in enumerate(e_rows):
            y = 70.0 + 14.0 * idx
            epage.insert_text((20, y), label, fontsize=7)
            for anchor, val in zip(e_cols, values):
                w = pymupdf.get_text_length(val, fontsize=7)
                epage.insert_text((anchor - w, y), val, fontsize=7)
        edoc.save(str(epath))
        edoc.close()
        conn.execute("INSERT INTO doc VALUES (?,'AAAA','INE000A01001','results','results','Results',"
                     "?,?,1,?,'bse',?)", (dk, fdate, k_at, f"sha_{dk}", str(epath)))
    conn.commit()
    review_csv = tmp_dir / "review.csv"
    cmp.run(conn, ["AAAA"], review_path=review_csv, store_db=store_db,
            ocr_dbs=[ocr_db] if ocr_rows is not None else ())
    rows = conn.execute(
        f"SELECT symbol, isin, period_start, period_end, fiscal_period, period_type, column_role, basis, statement, "
        f"line_item, caption, value, unit, scale, raw_token, quote, doc_key, page, known_at, known_at_source, "
        f"check_status, check_detail, is_reported FROM {cmp.TABLE}"
    ).fetchall()
    conn.close()
    with review_csv.open(newline="", encoding="utf-8") as fh:
        review = list(csv.DictReader(fh))
    return rows, review


def test_r013_jumbled_page_ocr_leads_when_layer_disagrees():
    import uuid
    from pathlib import Path

    layer = [(lbl, ("9,999",) + vals[1:] if lbl.startswith("3 ") else vals) for lbl, vals in ROWS]
    rows, review = _build_pdf_and_ocr(Path(".tmp/pytest") / uuid.uuid4().hex[:8], layer, ROWS)
    ti = _cells(rows, "total_income", "current")
    assert len(ti) == 1 and ti[0][11] == 1100 * 1e7 and ti[0][20] == "sum_ok"
    assert any(r["check"] == "ocr_text_disagree" and r["line_item"] == "total_income" and r["column_role"] == "current"
               for r in review)


def test_r013_layer_only_figure_completing_arithmetic_is_stored_sum_ok():
    import uuid
    from pathlib import Path

    # Use June 4-column layout (no cross-column ytd mark) so only total_income - total_expenses can confirm PBT.
    # Layer has garbled total_income (9,999) and right PBT (300); OCR has right total_income (1,100) and expenses (800)
    # but garbled PBT label so OCR misses PBT.
    dates = ("30.06.2026", "31.03.2026", "30.06.2025", "31.03.2026")
    cols = (200.0, 260.0, 320.0, 380.0)
    base_rows = [(lbl, vals[:4]) for lbl, vals in ROWS]
    layer = [(lbl, ("9,999",) + vals[1:] if lbl.startswith("3 ") else vals) for lbl, vals in base_rows]
    ocr = [("Xyz before Qrs", vals) if lbl.startswith("5 ") else (lbl, vals) for lbl, vals in base_rows]
    rows, _review = _build_pdf_and_ocr(Path(".tmp/pytest") / uuid.uuid4().hex[:8], layer, ocr, dates=dates, cols=cols)
    pbt = _cells(rows, "pbt_before_exceptional", "current")
    assert len(pbt) == 1 and pbt[0][11] == 300 * 1e7 and pbt[0][20] == "sum_ok"


def test_r013_layer_only_unconfirmed_figure_dropped_and_logged():
    import uuid
    from pathlib import Path

    # current + preceding != ytd (408 + 360 != 758), so nothing confirms other_expenses
    layer = ROWS + [("9 Other expenses", ("408", "360", "300", "758", "650", "1,400"))]
    ocr = ROWS + [("9 Oth3r xyz", ("408", "360", "300", "758", "650", "1,400"))]
    rows, review = _build_pdf_and_ocr(Path(".tmp/pytest") / uuid.uuid4().hex[:8], layer, ocr)
    assert _cells(rows, "other_expenses", "current") == []
    assert any(r["check"] == "layer_unconfirmed" and r["line_item"] == "other_expenses"
               and r["column_role"] == "current" and r["raw_token"] == "408" for r in review)


def test_r013_clean_page_without_ocr_keeps_unchecked_layer_rows():
    import uuid
    from pathlib import Path

    clean = ROWS + [("9 Other expenses", ("408", "360", "300", "758", "650", "1,400"))]
    rows, review = _build_pdf_and_ocr(Path(".tmp/pytest") / uuid.uuid4().hex[:8], clean, None, jumbled=False)
    oe = _cells(rows, "other_expenses", "current")
    assert len(oe) == 1 and oe[0][11] == 408 * 1e7 and oe[0][20] == "unchecked"
    assert not any(r["check"] == "layer_unconfirmed" for r in review)


def test_r013_side_by_side_jumbled_page_yields_both_bases():
    import uuid
    from pathlib import Path

    dates = ("31.03.2026", "31.12.2025", "31.03.2025", "31.03.2026", "31.03.2025") * 2
    cols = tuple(160.0 + 60.0 * i for i in range(10))
    ocr_rows = _june_rows([
        ("500.00", "450.00", "400.00", "1,700.00", "1,500.00", "900.00", "850.00", "800.00", "3,200.00", "2,800.00"),
        ("10.00", "10.00", "10.00", "40.00", "30.00", "20.00", "20.00", "20.00", "80.00", "60.00"),
        ("510.00", "460.00", "410.00", "1,740.00", "1,530.00", "920.00", "870.00", "820.00", "3,280.00", "2,860.00"),
        ("400.00", "360.00", "320.00", "1,400.00", "1,200.00", "700.00", "650.00", "600.00", "2,600.00", "2,200.00"),
        ("110.00", "100.00", "90.00", "340.00", "330.00", "220.00", "220.00", "220.00", "680.00", "660.00"),
        ("28.00", "25.00", "22.00", "85.00", "80.00", "55.00", "55.00", "55.00", "170.00", "160.00"),
        ("82.00", "75.00", "68.00", "255.00", "250.00", "165.00", "165.00", "165.00", "510.00", "500.00"),
        ("1.50", "1.40", "1.20", "4.50", "4.00", "3.00", "3.00", "3.00", "9.50", "9.00"),
    ])
    # Text layer garbles total_income on both halves (9999.00); OCR has the right figures and both basis headers.
    layer_rows = [(lbl, ("9999.00",) * 10 if lbl.startswith("3 ") else vals) for lbl, vals in ocr_rows]
    rows, review = _build_pdf_and_ocr(
        Path(".tmp/pytest") / uuid.uuid4().hex[:8],
        layer_rows, ocr_rows,
        title="Financial Results STANDALONE CONSOLIDATED",
        dates=dates, cols=cols,
    )
    sa_ti = [r for r in rows if r[7] == "standalone" and r[9] == "total_income" and r[6] == "current"]
    co_ti = [r for r in rows if r[7] == "consolidated" and r[9] == "total_income" and r[6] == "current"]
    assert len(sa_ti) == 1 and sa_ti[0][11] == 510 * 1e7 and sa_ti[0][20] == "sum_ok"
    assert len(co_ti) == 1 and co_ti[0][11] == 920 * 1e7 and co_ti[0][20] == "sum_ok"
    assert any(r["check"] == "ocr_text_disagree" and r["line_item"] == "total_income" for r in review)


def test_r013_unreadable_ocr_table_falls_back_to_layer_with_rule3():
    import uuid
    from pathlib import Path

    # OCR has only 1 row (read_page returns None), while layer has the full P&L table + unconfirmed other_expenses.
    layer = ROWS + [("9 Other expenses", ("408", "360", "300", "758", "650", "1,400"))]
    ocr = [("1 Revenue from operations", ("1,000", "900", "800", "1,900", "1,700", "3,500"))]
    rows, review = _build_pdf_and_ocr(Path(".tmp/pytest") / uuid.uuid4().hex[:8], layer, ocr)
    assert len(_cells(rows, "total_income", "current")) == 1
    assert _cells(rows, "other_expenses", "current") == []
    assert any(r["check"] == "layer_unconfirmed" and r["line_item"] == "other_expenses" for r in review)


def test_r013_ladder_confirmed_layer_beats_ocr_leading_digit_drop():
    import uuid
    from pathlib import Path

    # Q2 cross-column identity (current + preceding = ytd) confirms layer's 363,278 as sum_ok,
    # while OCR dropped the leading digit (63,278) and fails cross-column check -> confirmed layer wins.
    layer = ROWS + [("6a Current tax", ("363,278", "200,000", "150,000", "563,278", "400,000", "900,000"))]
    ocr = ROWS + [("6a Current tax", ("63,278", "200,000", "150,000", "563,278", "400,000", "900,000"))]
    rows, review = _build_pdf_and_ocr(Path(".tmp/pytest") / uuid.uuid4().hex[:8], layer, ocr,
                                      unit="Rs. in Thousands")
    ct = _cells(rows, "current_tax", "current")
    assert len(ct) == 1 and ct[0][11] == 363278 * 1e3 and ct[0][20] == "sum_ok"
    assert any(r["check"] == "ocr_text_disagree" and r["line_item"] == "current_tax" for r in review)


def test_r013_ladder_layer_xbrl_ok_eps_kept_when_ocr_differs():
    import uuid
    from pathlib import Path

    dates = ("30.06.2026", "31.03.2026", "30.06.2025", "31.03.2026")
    cols = (200.0, 260.0, 320.0, 380.0)
    base = [(lbl, vals[:4]) for lbl, vals in ROWS[:-1]]
    layer = base + [
        ("8 Basic EPS", ("0.38", "0.30", "0.25", "1.20")),
        ("9 Diluted EPS", ("2.85", "2.10", "1.90", "8.50")),
    ]
    ocr = base + [
        ("8 Basic EPS", ("9.38", "0.30", "0.25", "1.20")),
        ("9 Diluted EPS", ("8.85", "2.10", "1.90", "8.50")),
    ]
    rows, review = _build_pdf_and_ocr(
        Path(".tmp/pytest") / uuid.uuid4().hex[:8], layer, ocr, dates=dates, cols=cols,
        xbrl_rows=[("consolidated", "2026-06-30", "eps_basic", 0.38),
                   ("consolidated", "2026-06-30", "eps_diluted", 2.85)],
    )
    eb = _cells(rows, "eps_basic", "current")
    ed = _cells(rows, "eps_diluted", "current")
    assert len(eb) == 1 and eb[0][11] == 0.38 and eb[0][20] == "xbrl_ok"
    assert len(ed) == 1 and ed[0][11] == 2.85 and ed[0][20] == "xbrl_ok"
    assert any(r["check"] == "ocr_text_disagree" and r["line_item"] == "eps_basic" for r in review)


def test_r013_ladder_layer_xbrl_ok_exceptional_zero_beats_ocr_mislabelled():
    import uuid
    from pathlib import Path

    dates = ("30.06.2026", "31.03.2026", "30.06.2025", "31.03.2026")
    cols = (200.0, 260.0, 320.0, 380.0)
    layer = [
        ("1 Revenue from operations", ("1,000", "900", "800", "3,500")),
        ("2 Other income", ("100", "90", "80", "350")),
        ("3 Total income", ("1,100", "990", "880", "3,850")),
        ("4 Total expenses", ("800", "720", "640", "2,800")),
        ("5 Profit before exceptional items and tax", ("300", "270", "240", "1,050")),
        ("6 Exceptional items", ("0.00", "0.00", "0.00", "0.00")),
        ("7 Profit before tax", ("300", "270", "240", "1,050")),
        ("8 Total tax expense", ("75", "67", "60", "262")),
        ("9 Profit for the period", ("225", "203", "180", "788")),
    ]
    ocr = [
        ("6 Exceptional items", ("1,266.17", "0.00", "0.00", "0.00")) if lbl.startswith("6 ") else (lbl, vals)
        for lbl, vals in layer
    ]
    rows, review = _build_pdf_and_ocr(
        Path(".tmp/pytest") / uuid.uuid4().hex[:8], layer, ocr, dates=dates, cols=cols,
        xbrl_rows=[("consolidated", "2026-06-30", "exceptional_items", 0.0)],
    )
    exc = _cells(rows, "exceptional_items", "current")
    assert len(exc) == 1 and exc[0][11] == 0.0 and exc[0][20] == "xbrl_ok"
    assert any(r["check"] == "ocr_text_disagree" and r["line_item"] == "exceptional_items" for r in review)


def test_r013_ladder_xbrl_ok_beats_losing_sum_ok():
    import uuid
    from pathlib import Path

    dates = ("30.06.2026", "31.03.2026", "30.06.2025", "31.03.2026")
    cols = (200.0, 260.0, 320.0, 380.0)
    layer = [
        ("1 Revenue from operations", ("1,000", "900", "800", "3,500")),
        ("2 Other income", ("100", "90", "80", "350")),
        ("3 Total income", ("1,100", "990", "880", "3,850")),
        ("4 Total expenses", ("800", "720", "640", "2,800")),
        ("5 Profit before tax", ("300", "270", "240", "1,050")),
        ("6 Total tax expense", ("1", "67", "60", "262")),
        ("7 Profit for the period", ("299", "203", "180", "788")),
        ("8 Basic EPS", ("10.5", "9.5", "8.4", "36.8")),
    ]
    # OCR has wrong tax=-25 and wrong pat=325 so OCR's own arithmetic (300 - (-25) = 325) marks tax=-25 as sum_ok.
    ocr = [
        ("6 Total tax expense", ("-25", "67", "60", "262")) if lbl.startswith("6 ")
        else ("7 Profit for the period", ("325", "203", "180", "788")) if lbl.startswith("7 ")
        else (lbl, vals)
        for lbl, vals in layer
    ]
    rows, _review = _build_pdf_and_ocr(
        Path(".tmp/pytest") / uuid.uuid4().hex[:8], layer, ocr, dates=dates, cols=cols,
        xbrl_rows=[("consolidated", "2026-06-30", "tax", 1 * 1e7)],
    )
    tax = _cells(rows, "tax", "current")
    assert len(tax) == 1 and tax[0][11] == 1 * 1e7 and tax[0][20] == "xbrl_ok"


def test_r013_ladder_ocr_xbrl_ok_beats_layer_sum_ok():
    import uuid
    from pathlib import Path

    dates = ("30.06.2026", "31.03.2026", "30.06.2025", "31.03.2026")
    cols = (200.0, 260.0, 320.0, 380.0)
    ocr = [(lbl, vals[:4]) for lbl, vals in ROWS]
    # Layer misreads both tax=85 and pat=215 so layer satisfies 300 - 85 = 215 (sum_ok), while OCR tax=75 is xbrl_ok.
    layer = [
        ("6 Total tax expense", ("85", "67", "60", "262")) if lbl.startswith("6 ")
        else ("7 Profit for the period", ("215", "203", "180", "788")) if lbl.startswith("7 ")
        else (lbl, vals)
        for lbl, vals in ocr
    ]
    rows, _review = _build_pdf_and_ocr(
        Path(".tmp/pytest") / uuid.uuid4().hex[:8], layer, ocr, dates=dates, cols=cols,
        xbrl_rows=[("consolidated", "2026-06-30", "tax", 75 * 1e7)],
    )
    tax = _cells(rows, "tax", "current")
    assert len(tax) == 1 and tax[0][11] == 75 * 1e7 and tax[0][20] == "xbrl_ok"


def test_r013_ladder_repeat_ok_promotes_layer_disagreed_value():
    import uuid
    from pathlib import Path

    dates = ("30.06.2026", "31.03.2026", "30.06.2025", "31.03.2026")
    cols = (200.0, 260.0, 320.0, 380.0)
    base = [(lbl, vals[:4]) for lbl, vals in ROWS]
    layer = base + [("6a Current tax", ("120", "100", "90", "380"))]
    ocr = base + [("6a Current tax", ("150", "100", "90", "380"))]
    rows, _review = _build_pdf_and_ocr(
        Path(".tmp/pytest") / uuid.uuid4().hex[:8], layer, ocr, dates=dates, cols=cols,
        extra_docs=[("prior.pdf", "2026-07-25", "2026-07-25T12:00:00", layer, dates, cols)],
    )
    ct = [r for r in _cells(rows, "current_tax", "current") if r[16] == "res.pdf"]
    assert len(ct) == 1 and ct[0][11] == 120 * 1e7 and ct[0][20] == "repeat_ok"


def _run_june_annual_facts_case(tmp_path, annual_rows):
    import pymupdf

    dates = ("30.06.2026", "31.03.", "30.06.2025", "31.03.")
    cols = (200.0, 270.0, 340.0, 410.0)
    rows = _june_rows([
        ("12,000.00", "13,000.00", "11,000.00", "50,167.28"),
        ("100.00", "110.00", "90.00", "417.05"),
        ("12,100.00", "13,110.00", "11,090.00", "50,584.33"),
        ("10,500.00", "11,400.00", "9,700.00", "44,051.93"),
        ("1,600.00", "1,710.00", "1,390.00", "6,532.40"),
        ("400.00", "420.00", "350.00", "1,513.86"),
        ("1,200.00", "1,290.00", "1,040.00", "5,018.54"),
        ("11.90", "12.80", "10.30", "49.80"),
    ])
    pdf_path = tmp_path / "june_q1.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=800, height=600)
    page.insert_text((40, 20), "Statement of Standalone Unaudited Financial Results for the Quarter Ended 30.06.2026", fontsize=8)
    page.insert_text((40, 35), "Rs. in Lakhs", fontsize=8)
    for anchor, dtext in zip(cols, dates):
        w = pymupdf.get_text_length(dtext, fontsize=7)
        page.insert_text((anchor - w, 50), dtext, fontsize=7)
    for idx, (label, values) in enumerate(rows):
        y = 70.0 + 14.0 * idx
        page.insert_text((20, y), label, fontsize=7)
        for anchor, val in zip(cols, values):
            w = pymupdf.get_text_length(val, fontsize=7)
            page.insert_text((anchor - w, y), val, fontsize=7)
    for i in range(15):
        page.insert_text((20, 320 + 12 * i), f"Zxv{i}omer Qlarton{i} Vroptex{i}", fontsize=7)
    doc.save(str(pdf_path))
    doc.close()

    conn = _conn()
    conn.execute("""
        CREATE TABLE fin_annual_line (symbol TEXT, isin TEXT, fiscal_year TEXT, period_end TEXT, basis TEXT,
            statement TEXT, line_item TEXT, caption TEXT, value REAL, unit TEXT, scale REAL, doc_key TEXT,
            page INTEGER, quote TEXT, source_db TEXT, source_table TEXT, source_rowid TEXT, known_at TEXT,
            known_at_source TEXT, is_reported INTEGER, is_derived INTEGER, definition TEXT, period_type TEXT)
    """)
    for basis, period_end, item, value, source_table in annual_rows:
        conn.execute(
            "INSERT INTO fin_annual_line (symbol, isin, fiscal_year, period_end, basis, statement, line_item, "
            "value, unit, scale, source_table, period_type) VALUES "
            "('AAAA', 'INE000A01001', 'FY26', ?, ?, 'P&L', ?, ?, 'inr', 1.0, ?, 'FY')",
            (period_end, basis, item, value, source_table),
        )
    conn.execute(
        "INSERT INTO doc VALUES ('june_q1.pdf','AAAA','INE000A01001','results','results','Results',"
        "'2026-08-14','2026-08-14T12:00:00',1,'sha_q1','nse',?)", (str(pdf_path),)
    )
    conn.commit()
    cmp.run(conn, ["AAAA"])
    out = conn.execute(
        f"SELECT line_item, column_role, period_end, basis, value, check_status FROM {cmp.TABLE}"
    ).fetchall()
    conn.close()
    return out


def test_june_last_fy_confirmed_by_annual_facts_when_header_lacks_year(tmp_path):
    """R-020 follow-up: annual XBRL facts (fin_annual_line source_table='facts') confirm June last_fy."""
    stored = _run_june_annual_facts_case(
        tmp_path,
        [("standalone", "2026-03-31", "total_income", 50584.33 * 1e5, "facts")],
    )
    last_fy = [r for r in stored if r[1] == "last_fy"]
    assert {r[0] for r in last_fy} >= {
        "revenue_from_operations", "total_income", "total_expenses", "pbt_before_exceptional", "eps_basic",
    }
    ti = [r for r in last_fy if r[0] == "total_income"]
    assert len(ti) == 1 and ti[0][2] == "2026-03-31" and ti[0][3] == "standalone"
    assert ti[0][4] == pytest.approx(50584.33 * 1e5) and ti[0][5] == "xbrl_ok"


def test_june_last_fy_not_stored_when_annual_facts_mismatches_or_wrong_source(tmp_path):
    """R-020 follow-up: non-matching annual facts (or non-facts/non-vocab rows) do not confirm June last_fy."""
    stored_mismatch = _run_june_annual_facts_case(
        tmp_path,
        [("standalone", "2026-03-31", "total_income", 99999.00 * 1e5, "facts")],
    )
    assert [r for r in stored_mismatch if r[1] == "last_fy"] == []
    assert {r[1] for r in stored_mismatch} == {"current", "preceding", "year_ago"}

    # Non-vocab item and non-facts source_table do not confirm last_fy either.
    stored_other = _run_june_annual_facts_case(
        tmp_path,
        [
            ("standalone", "2026-03-31", "ebitda", 50584.33 * 1e5, "facts"),
            ("standalone", "2026-03-31", "total_income", 50584.33 * 1e5, "ar_facts"),
        ],
    )
    assert [r for r in stored_other if r[1] == "last_fy"] == []


def test_june_last_fy_eps_tolerance_uses_printed_decimals(tmp_path):
    """EPS confirmation against annual facts uses EPS's own printed decimals, never table rupee scale."""
    stored_ok = _run_june_annual_facts_case(
        tmp_path,
        [("standalone", "2026-03-31", "eps_basic", 49.81, "facts")],
    )
    assert any(r[1] == "last_fy" and r[0] == "eps_basic" for r in stored_ok)

    stored_far = _run_june_annual_facts_case(
        tmp_path,
        [("standalone", "2026-03-31", "eps_basic", 50.10, "facts")],
    )
    assert [r for r in stored_far if r[1] == "last_fy"] == []


# ---------------------------------------------------------------- T-223: R-013 9 held-store causes ----------------------------------
def test_fy_column_confirmed_by_annual_facts_not_q4_xbrl(tmp_path):
    """FY columns (Q4 ytd or last_fy) confirm against fin_annual_line facts, never Q4 fin_quarter_xbrl;
    and H1/9M ytd columns never match Q2/Q3 quarter XBRL."""
    import pymupdf

    dates = ("31.03.2025", "31.12.2024", "31.03.2024", "31.03.2025", "31.03.2024")
    cols = (200.0, 260.0, 320.0, 380.0, 440.0)
    rows = [
        ("1 Revenue from operations", ("1,000", "900", "800", "3,600", "3,200")),
        ("2 Other income", ("100", "90", "80", "400", "300")),
        ("3 Total income", ("1,100", "990", "880", "4,000", "3,500")),
        ("4 Total expenses", ("800", "720", "640", "3,000", "2,600")),
        ("5 Profit before exceptional items and tax", ("300", "270", "240", "1,000", "900")),
        ("6 Total tax expense", ("75", "67", "60", "250", "225")),
        ("7 Profit for the period", ("225", "203", "180", "750", "675")),
        ("8 Diluted EPS", ("(0.32)", "(0.06)", "(2.83)", "(0.57)", "(3.47)")),
    ]
    rows_out, _rev = _build_pdf_and_ocr(
        tmp_path / "fy_case",
        [(lbl, ("9,999",) * 5 if lbl.startswith("8 ") else vals) for lbl, vals in rows],
        rows,
        dates=dates,
        cols=cols,
        xbrl_rows=[
            ("consolidated", "2025-03-31", "eps_diluted", -0.32),
            ("consolidated", "2024-12-31", "eps_diluted", -0.06),
        ],
    )
    # Also test with fin_annual_line (source_table='facts') populated
    pdf_path = tmp_path / "fy_facts.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=800, height=600)
    page.insert_text((40, 20), "Statement of Consolidated Unaudited Financial Results", fontsize=8)
    page.insert_text((40, 35), "Rs. in Crore", fontsize=8)
    for anchor, dtext in zip(cols, dates):
        w = pymupdf.get_text_length(dtext, fontsize=7)
        page.insert_text((anchor - w, 50), dtext, fontsize=7)
    for idx, (label, values) in enumerate(rows):
        y = 70.0 + 14.0 * idx
        page.insert_text((20, y), label, fontsize=7)
        for anchor, val in zip(cols, values):
            w = pymupdf.get_text_length(val, fontsize=7)
            page.insert_text((anchor - w, y), val, fontsize=7)
    for i in range(15):
        page.insert_text((20, 320 + 12 * i), f"Zxv{i}omer Qlarton{i} Vroptex{i}", fontsize=7)
    doc.save(str(pdf_path))
    doc.close()
    conn = _conn()
    conn.execute("""
        CREATE TABLE fin_annual_line (symbol TEXT, isin TEXT, fiscal_year TEXT, period_end TEXT, basis TEXT,
            statement TEXT, line_item TEXT, caption TEXT, value REAL, unit TEXT, scale REAL, doc_key TEXT,
            page INTEGER, quote TEXT, source_db TEXT, source_table TEXT, source_rowid TEXT, known_at TEXT,
            known_at_source TEXT, is_reported INTEGER, is_derived INTEGER, definition TEXT, period_type TEXT)
    """)
    conn.execute("INSERT INTO fin_annual_line (symbol, basis, period_end, line_item, value, source_table, period_type) "
                 "VALUES ('AAAA', 'consolidated', '2025-03-31', 'eps_diluted', -0.57, 'facts', 'FY')")
    conn.execute("INSERT INTO doc VALUES ('fy.pdf','AAAA','INE000A01001','results','results','Results',"
                 "'2025-05-20','2025-05-20T12:00:00',1,'sha_fy','bse',?)", (str(pdf_path),))
    _xbrl(conn, "2025-03-31", "eps_diluted", -0.32)
    ocr_db = tmp_path / "fy_ocr.db"
    ocr_con = sqlite3.connect(ocr_db)
    ocr_con.execute("CREATE TABLE ocr_page (doc_key TEXT, page INTEGER, method TEXT, words_json TEXT)")
    words = [(40.0, 15.0, 220.0, 23.0, "Statement of Consolidated Unaudited Financial Results"),
             (40.0, 28.0, 120.0, 36.0, "Rs. in Crore")]
    for anchor, dtext in zip(cols, dates):
        words.append((anchor - 40.0, 44.0, anchor, 52.0, dtext))
    for idx, (label, values) in enumerate(rows):
        y = 65.0 + 14.0 * idx
        x = 20.0
        for tok in label.split():
            words.append((x, y - 3.0, x + 6.0 * len(tok), y + 3.0, tok))
            x += 6.0 * len(tok) + 3.0
        for anchor, val in zip(cols, values):
            words.append((anchor - 6.0 * len(val), y - 3.0, anchor, y + 3.0, val))
    import json
    ocr_con.execute("INSERT INTO ocr_page VALUES ('fy.pdf', 1, 'ocr_rapid', ?)", (json.dumps(words),))
    ocr_con.commit()
    ocr_con.close()
    conn.commit()
    store_db = tmp_path / "fy_store.db"
    dst = sqlite3.connect(store_db)
    conn.backup(dst)
    dst.close()
    cmp.run(conn, ["AAAA"], store_db=store_db, ocr_dbs=[ocr_db])
    stored = conn.execute(
        f"SELECT column_role, period_type, line_item, value, check_status FROM {cmp.TABLE}"
    ).fetchall()
    conn.close()
    # On d39a4411, ytd (-0.57) is checked against Q4 (-0.32), fails _xbrl_ok, and is dropped as ocr_unreconciled.
    fy_eps = [r for r in stored if r[0] == "ytd" and r[2] == "eps_diluted"]
    assert len(fy_eps) == 1 and fy_eps[0][3] == pytest.approx(-0.57) and fy_eps[0][4] == "xbrl_ok"
    # On a 9M/H1 table, ytd must never be marked xbrl_ok against quarter XBRL (without annual_facts),
    # whereas point-in-time paid_up_capital at period_end does match quarter XBRL
    assert [r for r in rows_out if r[6] == "ytd" and r[9] == "eps_diluted" and r[20] == "xbrl_ok"] == []
    assert cmp._xbrl_ok({("consolidated", "2024-12-31"): {"paid_up_capital": 1e9, "exceptional_items": 0.0}},
                        "consolidated", "2024-12-31", "paid_up_capital", 1e9, 1e5, ptype="ytd") is True
    assert cmp._xbrl_ok({("consolidated", "2024-12-31"): {"paid_up_capital": 1e9, "exceptional_items": 0.0}},
                        "consolidated", "2024-12-31", "exceptional_items", 0.0, 1e5, ptype="ytd") is False


def test_debit_costs_keeps_confirmed_pl_with_negative_component_cost():
    """A genuine P&L with one negative expense reversal (e.g. Finance Costs (1147.25) or Other Expenses (49))
    and positive total_expenses + confirmed arithmetic/XBRL must NOT be rejected as not_pl_costs."""
    conn = _conn()
    _xbrl(conn, "2026-09-30", "total_expenses", 800 * 1e7)
    _xbrl(conn, "2026-09-30", "finance_cost", -50 * 1e7)
    rows = [
        ("1 Revenue from operations", ("1,000", "900", "800", "1,900", "1,700", "3,500")),
        ("2 Other income", ("100", "90", "80", "190", "170", "350")),
        ("3 Total income", ("1,100", "990", "880", "2,090", "1,870", "3,850")),
        ("4a Finance costs", ("(50)", "20", "15", "(30)", "30", "60")),
        ("4b Other expenses", ("850", "700", "625", "1,550", "1,330", "2,740")),
        ("4 Total expenses", ("800", "720", "640", "1,520", "1,360", "2,800")),
        ("5 Profit before exceptional items and tax", ("300", "270", "240", "570", "510", "1,050")),
        ("6 Total tax expense", ("75", "67", "60", "142", "127", "262")),
        ("7 Profit for the period", ("225", "203", "180", "428", "383", "788")),
    ]
    review: list[dict] = []
    table = cmp.read_page(_page(rows))
    stored = cmp._table_rows(conn, "AAAA", "INE000A01001", "doc1", 8, "2026-10-20T12:00:00",
                             table, cmp.xbrl_index(conn, "AAAA"), review)
    assert stored and not any(r["check"] == "not_pl_costs" for r in review)
    te = _cells(stored, "total_expenses", "current")
    assert len(te) == 1 and te[0][11] == 800 * 1e7 and te[0][20] == "xbrl_ok"
    fc = _cells(stored, "finance_cost", "current")
    assert len(fc) == 1 and fc[0][11] == -50 * 1e7 and fc[0][20] == "xbrl_ok"


def test_choose_rows_picks_closest_xbrl_eps_and_rejects_discontinued_tax(tmp_path):
    """(a) Multiple EPS rows within tol: closest to XBRL wins (19.00 beats 19.02 when XBRL=19.00);
    (b) OCR '0,0' vs layer '0.01' with XBRL 0.01 keeps 0.01, not 0.0;
    (c) 'Tax Expense of discounting operations' does not hijack tax from current_tax + deferred_tax."""
    # (a) Closest EPS row
    conn = _conn()
    _xbrl(conn, "2026-09-30", "eps_basic", 19.00)
    rows_eps = ROWS[:-1] + [
        ("9a Basic", ("19.02", "16.29", "10.66", "35.31", "30.00", "60.44")),
        ("9b Basic", ("19.00", "16.32", "10.67", "35.32", "30.00", "60.49")),
    ]
    stored = _store(conn, rows=rows_eps)
    eb = _cells(stored, "eps_basic", "current")
    assert len(eb) == 1 and eb[0][11] == pytest.approx(19.00)

    # (b) OCR '0,0' vs layer '0.01'
    layer_eps = ROWS[:-1] + [("9 Diluted EPS", ("0.01", "(0.20)", "(0.20)", "(0.19)", "(0.55)", "(3.47)"))]
    ocr_eps = ROWS[:-1] + [("9 Diluted EPS", ("0,0", "(0.20)", "(0.20)", "(0.19)", "(0.55)", "(3.47)"))]
    rows_b, _rev = _build_pdf_and_ocr(
        tmp_path / "eps_zero", layer_eps, ocr_eps, dates=DATES,
        xbrl_rows=[("consolidated", "2026-09-30", "eps_diluted", 0.01)],
    )
    ed = _cells(rows_b, "eps_diluted", "current")
    assert len(ed) == 1 and ed[0][11] == pytest.approx(0.01)

    # (c) Discontinued operations tax does not hijack tax
    assert cmp.match_line("Tax Expense of discounting operations", anchor=2, prefix_ok=True) is None
    assert cmp.match_line("11 Tax expenses/(income) of discontinued operations", anchor=2) is None


def test_r013_preserves_layer_on_continuation_side_by_side_none_roles_and_probe(tmp_path):
    """(a) Continuation page keeps fill_table from text layer so EPS 14.40 (xbrl_ok) beats OCR 4.40;
    (b) Side-by-side split falls back to OCR halves' bases when layer header is garbled;
    (c) None role in fill_choice does not discard fill_table;
    (d) probe tests disagreed layer candidate to confirm sum_ok."""
    import uuid

    # (a) Continuation page with fill_table
    dates = ("31.12.2024", "30.09.2024", "31.12.2023", "31.12.2024", "31.12.2023", "31.03.2024")
    p1_rows = ROWS[:-1] + [("5a Exceptional items", ("0", "0", "0", "0", "0", "0"))]
    p2_layer = [
        ("8 Total other comprehensive income", ("10", "10", "10", "20", "20", "40")),
        ("9 Total comprehensive income", ("235", "213", "190", "448", "403", "828")),
        ("10 Paid-up equity share capital", ("100", "100", "100", "100", "100", "100")),
        ("11 Basic EPS", ("14.40", "12.00", "11.00", "26.40", "24.00", "50.00")),
    ]
    p2_ocr = [
        ("8 Total other comprehensive income", ("10", "10", "10", "20", "20", "40")),
        ("9 Total comprehensive income", ("235", "213", "190", "448", "403", "828")),
        ("10 Paid-up equity share capital", ("100", "100", "100", "100", "100", "100")),
        ("11 Basic EPS", ("4.40", "12.00", "11.00", "26.40", "24.00", "50.00")),
    ]
    import pymupdf, json
    d = tmp_path / uuid.uuid4().hex[:8]
    d.mkdir(parents=True)
    pdf_path = d / "cont.pdf"
    doc = pymupdf.open()
    for p_rows, has_hdr in ((p1_rows, True), (p2_layer, False)):
        pg = doc.new_page(width=800, height=600)
        if has_hdr:
            pg.insert_text((40, 20), "Statement of Consolidated Unaudited Financial Results", fontsize=8)
            pg.insert_text((40, 35), "Rs. in Lakhs", fontsize=8)
            for a, dt in zip(COLS, dates):
                pg.insert_text((a - pymupdf.get_text_length(dt, fontsize=7), 50), dt, fontsize=7)
        else:
            pg.insert_text((40, 20), "Notes continued", fontsize=8)
        for idx, (lbl, vals) in enumerate(p_rows):
            y = 70.0 + 14.0 * idx
            pg.insert_text((20, y), lbl, fontsize=7)
            for a, v in zip(COLS, vals):
                pg.insert_text((a - pymupdf.get_text_length(v, fontsize=7), y), v, fontsize=7)
        for i in range(15):
            pg.insert_text((20, 320 + 12 * i), f"Zxv{i}omer Qlarton{i} Vroptex{i}", fontsize=7)
    doc.save(str(pdf_path))
    doc.close()

    def _box_list(p_rows, has_hdr):
        w = []
        if has_hdr:
            w += [(40.0, 15.0, 220.0, 23.0, "Statement of Consolidated Unaudited Financial Results"),
                  (40.0, 28.0, 120.0, 36.0, "Rs. in Lakhs")]
            for a, dt in zip(COLS, dates):
                w.append((a - 40.0, 44.0, a, 52.0, dt))
        else:
            w.append((40.0, 15.0, 120.0, 23.0, "Notes continued"))
        for idx, (lbl, vals) in enumerate(p_rows):
            y = 65.0 + 14.0 * idx
            x = 20.0
            for tok in lbl.split():
                w.append((x, y - 3.0, x + 6.0 * len(tok), y + 3.0, tok))
                x += 6.0 * len(tok) + 3.0
            for a, v in zip(COLS, vals):
                w.append((a - 6.0 * len(v), y - 3.0, a, y + 3.0, v))
        return w

    ocr_db = d / "ocr.db"
    ocon = sqlite3.connect(ocr_db)
    ocon.execute("CREATE TABLE ocr_page (doc_key TEXT, page INTEGER, method TEXT, words_json TEXT)")
    ocon.execute("INSERT INTO ocr_page VALUES ('cont.pdf', 1, 'ocr_rapid', ?)", (json.dumps(_box_list(p1_rows, True)),))
    ocon.execute("INSERT INTO ocr_page VALUES ('cont.pdf', 2, 'ocr_rapid', ?)", (json.dumps(_box_list(p2_ocr, False)),))
    ocon.commit()
    ocon.close()
    conn = _conn()
    conn.execute("INSERT INTO doc VALUES ('cont.pdf','AAAA','INE000A01001','results','results','Results',"
                 "'2025-02-10','2025-02-10T12:00:00',2,'sha_c','bse',?)", (str(pdf_path),))
    _xbrl(conn, "2024-12-31", "eps_basic", 14.40)
    conn.commit()
    sdb = d / "store.db"
    dst = sqlite3.connect(sdb)
    conn.backup(dst)
    dst.close()
    cmp.run(conn, ["AAAA"], store_db=sdb, ocr_dbs=[ocr_db])
    stored = conn.execute(f"SELECT column_role, line_item, value, check_status FROM {cmp.TABLE} WHERE page=2").fetchall()
    conn.close()
    eb2 = [r for r in stored if r[0] == "current" and r[1] == "eps_basic"]
    assert len(eb2) == 1 and eb2[0][2] == pytest.approx(14.40) and eb2[0][3] == "xbrl_ok"

    # (b) Side-by-side split when layer header lacks readable basis words
    sbs_dates = ("30.09.2026", "30.06.2026", "30.09.2025", "30.09.2026", "30.09.2025", "31.03.2026") * 2
    sbs_ocr_rows = _june_rows([
        ("500.00", "450.00", "400.00", "950.00", "800.00", "1,700.00", "900.00", "850.00", "800.00", "1,750.00", "1,600.00", "3,200.00"),
        ("10.00", "814.3", "685.9", "824.3", "20.00", "40.00", "20.00", "20.00", "20.00", "40.00", "40.00", "80.00"),
        ("510.00", "1,264.31", "1,085.93", "1,774.31", "820.00", "1,740.00", "920.00", "870.00", "820.00", "1,790.00", "1,640.00", "3,280.00"),
        ("400.00", "360.00", "320.00", "760.00", "640.00", "1,400.00", "700.00", "650.00", "600.00", "1,350.00", "1,200.00", "2,600.00"),
        ("110.00", "904.31", "765.93", "1,014.31", "180.00", "340.00", "220.00", "220.00", "220.00", "440.00", "440.00", "680.00"),
        ("28.00", "25.00", "22.00", "53.00", "44.00", "85.00", "55.00", "55.00", "55.00", "110.00", "110.00", "170.00"),
        ("82.00", "879.31", "743.93", "961.31", "136.00", "255.00", "165.00", "165.00", "165.00", "330.00", "330.00", "510.00"),
        ("1.50", "1.40", "1.20", "2.90", "2.40", "4.50", "3.00", "3.00", "3.00", "6.00", "6.00", "9.50"),
    ])
    sbs_layer_rows = [
        (lbl, ("10.00", "814.31", "685.93", "824.31", "20.00", "40.00", "20.00", "20.00", "20.00", "40.00", "40.00", "80.00")
         if lbl.startswith("2 ") else vals)
        for lbl, vals in sbs_ocr_rows
    ]
    t_sbs_ocr = cmp.read_page(_page_n(sbs_ocr_rows, sbs_dates, title="Financial Results STANDALONE CONSOLIDATED"), ocr=True)
    t_sbs_layer = cmp.read_page(_page_n(sbs_layer_rows, sbs_dates, title="Financial Results Stndln Cnsldtd"))
    assert cmp._split_side_by_side(t_sbs_layer) is None
    conn = _conn()
    _xbrl(conn, "2026-06-30", "other_income", 814.31 * 1e7, basis="standalone")
    sbs_stored = cmp._table_rows(conn, "AAAA", "INE000A01001", "doc1", 5, "2026-10-20T12:00:00",
                                 t_sbs_ocr, cmp.xbrl_index(conn, "AAAA"), [], ocr=True, fill_table=t_sbs_layer)
    oi_sa = [r for r in sbs_stored if r[7] == "standalone" and r[9] == "other_income" and r[6] == "preceding"]
    assert len(oi_sa) == 1 and oi_sa[0][11] == pytest.approx(814.31 * 1e7) and oi_sa[0][20] == "xbrl_ok"

    # (c) None-padded fill_choice["roles"] still uses fill_table
    q_dates = ("30.06.2024", "31.03.2024", "30.06.2023", "31.03.2024")
    base_4 = [(lbl, vals[:4]) for lbl, vals in ROWS[:-1]]
    t_ocr4 = cmp.read_page(_page_n(base_4 + [("9 Diluted EPS", ("0.00", "(0.01)", "(0.03)", "(0.06)"))], q_dates,
                                   title="Statement of Consolidated Financial Results"), ocr=True)
    t_lay4 = cmp.read_page(_page_n(base_4 + [("9 Diluted EPS", ("(0.31)", "(0.01)", "(0.03)", "(0.06)"))], q_dates,
                                   title="Statement of Consolidated Financial Results"))
    t_lay4["anchors"] = t_lay4["anchors"][:3] + [t_lay4["anchors"][3] - 5.0] + t_lay4["anchors"][3:]
    t_lay4["values"] = { (at + 1 if at >= 3 else at): col for at, col in t_lay4["values"].items() }
    t_lay4["dates"] = t_lay4["dates"][:3] + [None] + t_lay4["dates"][3:]
    conn = _conn()
    _xbrl(conn, "2024-06-30", "eps_diluted", -0.31)
    stored_c = cmp._table_rows(conn, "AAAA", "INE000A01001", "doc1", 17, "2024-08-14T12:00:00",
                               t_ocr4, cmp.xbrl_index(conn, "AAAA"), [], ocr=True, fill_table=t_lay4)
    ed_c = _cells(stored_c, "eps_diluted", "current")
    assert len(ed_c) == 1 and ed_c[0][11] == pytest.approx(-0.31) and ed_c[0][20] == "xbrl_ok"

    # (d) probe tests disagreed layer candidate when OCR failed sum_failed and layer missed total_income
    ocr_d = [
        ("1 Revenue from operations", ("1,000", "900", "800", "1,900", "20,39", "3,500")),
        ("2 Other income", ("100", "90", "80", "190", "125", "350")),
        ("3 Total income", ("1,100", "990", "880", "2,090", "20,522", "3,850")),
        ("4 Total expenses", ("800", "720", "640", "1,520", "15,000", "2,800")),
        ("5 Profit before exceptional items and tax", ("300", "270", "240", "570", "5,522", "1,050")),
        ("6 Total tax expense", ("75", "67", "60", "142", "1,380", "262")),
        ("7 Profit for the period", ("225", "203", "180", "428", "4,142", "788")),
        ("8 Paid-up equity share capital", ("100", "100", "100", "100", "100", "100")),
    ]
    layer_d = [
        ("1 Revenue from operations", ("1,000", "900", "800", "1,900", "20,397", "3,500")) if lbl.startswith("1 ")
        else ("Xyz garbled", vals) if lbl.startswith("3 ")
        else (lbl, vals)
        for lbl, vals in ocr_d
    ]
    rows_d, _rev_d = _build_pdf_and_ocr(tmp_path / "probe_disagree", layer_d, ocr_d)
    rev_py = _cells(rows_d, "revenue_from_operations", "prior_ytd")
    assert len(rev_py) == 1 and rev_py[0][11] == 20397 * 1e7 and rev_py[0][20] == "sum_ok"


def test_r013_derived_tax_cross_source_and_ocr_repeat_ok_across_filings(tmp_path):
    """(a) current_tax (OCR-only) + deferred_tax (layer-only) derive tax confirmed by annual_facts;
    (b) OCR-only derived tax repeating across two different filings becomes repeat_ok."""
    # (a) cross-source derived tax confirmed by fin_annual_line
    dates6 = ("30.09.2026", "30.06.2026", "30.09.2025", "30.09.2026", "30.09.2025", "31.03.2026")
    base = [
        ("1 Revenue from operations", ("1,000.00", "900.00", "800.00", "1,900.00", "1,700.00", "2,269.44")),
        ("2 Other income", ("100.00", "90.00", "80.00", "190.00", "170.00", "709.31")),
        ("3 Total income", ("1,100.00", "990.00", "880.00", "2,090.00", "1,870.00", "2,978.75")),
        ("4 Total expenses", ("800.00", "720.00", "640.00", "1,520.00", "1,360.00", "4,278.47")),
        ("5 Profit before exceptional items and tax", ("300.00", "270.00", "240.00", "570.00", "510.00", "(1,299.72)")),
        ("7 Profit for the period", ("225.00", "203.00", "180.00", "428.00", "383.00", "(973.69)")),
    ]
    ocr_a = base + [
        ("6a Current tax", ("0.00", "0.00", "0.00", "0.00", "0.00", "0.09")),
        ("6b Deferred tax", ("75.00", "67.00", "60.00", "142.00", "127.00", "326.12)")),
    ]
    layer_a = base + [
        ("6a Current tax", ("0.00", "0.00", "0.00", "0.00", "0.00", "0.09]")),
        ("6b Deferred tax", ("75.00", "67.00", "60.00", "142.00", "127.00", "(326.12)")),
    ]
    t_ocr = cmp.read_page(_page_n(ocr_a, dates6), ocr=True)
    t_lay = cmp.read_page(_page_n(layer_a, dates6))
    conn = _conn()
    annual = {("standalone", "2026-03-31"): {"tax": [-326.03 * 1e7]}}
    stored_a = cmp._table_rows(conn, "AAAA", "INE000A01001", "doc1", 4, "2026-10-20T12:00:00",
                               t_ocr, {}, [], ocr=True, fill_table=t_lay, annual_facts=annual)
    tx = _cells(stored_a, "tax", "last_fy")
    assert len(tx) == 1 and tx[0][11] == pytest.approx(-326.03 * 1e7) and tx[0][20] == "xbrl_ok"

    # (b) OCR-only derived tax repeating across two filings becomes repeat_ok
    dates_q = ("30.09.2025", "30.06.2025", "30.09.2024", "30.09.2025", "30.09.2024", "31.03.2025")
    rows_q1 = [
        ("1 Revenue from operations", ("1,000.00", "900.00", "800.00", "1,900.00", "1,700.00", "4,000.00")),
        ("2 Other income", ("100.00", "90.00", "80.00", "190.00", "170.00", "400.00")),
        ("3 Total income", ("1,100.00", "990.00", "880.00", "2,090.00", "1,870.00", "4,400.00")),
        ("4 Total expenses", ("800.00", "720.00", "640.00", "1,520.00", "1,360.00", "3,200.00")),
        ("5 Profit before exceptional items and tax", ("300.00", "270.00", "240.00", "570.00", "510.00", "1,200.00")),
        ("6a Current tax", ("65.00", "58.00", "52.00", "123.00", "110.00", "255.52")),
        ("6b Deferred tax", ("10.00", "9.00", "8.00", "19.00", "17.00", "21.90")),
        ("8 Paid-up equity share capital", ("100.00", "100.00", "100.00", "100.00", "100.00", "100.00")),
        # PAT missing/unreadable so pbt - tax = pat cannot mark FY25 tax sum_ok
    ]
    rows_q2 = [
        ("1 Revenue from operations", ("1,100.00", "1,000.00", "900.00", "3,000.00", "2,600.00", "4,000.00")),
        ("2 Other income", ("110.00", "100.00", "90.00", "300.00", "260.00", "400.00")),
        ("3 Total income", ("1,210.00", "1,100.00", "990.00", "3,300.00", "2,860.00", "4,400.00")),
        ("4 Total expenses", ("880.00", "800.00", "720.00", "2,400.00", "2,080.00", "3,200.00")),
        ("5 Profit before exceptional items and tax", ("330.00", "300.00", "270.00", "900.00", "780.00", "1,200.00")),
        ("6a Current tax", ("70.00", "65.00", "58.00", "193.00", "168.00", "255.52")),
        ("6b Deferred tax", ("12.00", "10.00", "9.00", "31.00", "26.00", "21.90")),
        ("8 Paid-up equity share capital", ("100.00", "100.00", "100.00", "100.00", "100.00", "100.00")),
    ]
    import pymupdf, json
    d2 = tmp_path / "ocr_repeat"
    d2.mkdir(parents=True)
    conn = _conn()
    ocr_db = d2 / "ocr.db"
    ocon = sqlite3.connect(ocr_db)
    ocon.execute("CREATE TABLE ocr_page (doc_key TEXT, page INTEGER, method TEXT, words_json TEXT)")
    for dk, fdate, k_at, r_set, d_set in (
        ("q2.pdf", "2025-11-10", "2025-11-10T12:00:00", rows_q1, dates_q),
        ("q3.pdf", "2026-02-10", "2026-02-10T12:00:00", rows_q2,
         ("31.12.2025", "30.09.2025", "31.12.2024", "31.12.2025", "31.12.2024", "31.03.2025")),
    ):
        ppath = d2 / dk
        doc = pymupdf.open()
        pg = doc.new_page(width=800, height=600)
        pg.insert_text((40, 20), "Garbled xxx yyy zzz", fontsize=8)
        doc.save(str(ppath))
        doc.close()
        conn.execute("INSERT INTO doc VALUES (?,'AAAA','INE000A01001','results','results','Results',"
                     "?,?,1,?,'bse',?)", (dk, fdate, k_at, f"sha_{dk}", str(ppath)))
        words = [(40.0, 15.0, 220.0, 23.0, "Statement of Consolidated Unaudited Financial Results"),
                 (40.0, 28.0, 120.0, 36.0, "Rs. in Crore")]
        for a, dt in zip(COLS, d_set):
            words.append((a - 40.0, 44.0, a, 52.0, dt))
        for idx, (lbl, vals) in enumerate(r_set):
            y = 65.0 + 14.0 * idx
            x = 20.0
            for tok in lbl.split():
                words.append((x, y - 3.0, x + 6.0 * len(tok), y + 3.0, tok))
                x += 6.0 * len(tok) + 3.0
            for a, v in zip(COLS, vals):
                words.append((a - 6.0 * len(v), y - 3.0, a, y + 3.0, v))
        ocon.execute("INSERT INTO ocr_page VALUES (?, 1, 'ocr_rapid', ?)", (dk, json.dumps(words)))
    ocon.commit()
    ocon.close()
    conn.commit()
    sdb = d2 / "store.db"
    dst = sqlite3.connect(sdb)
    conn.backup(dst)
    dst.close()
    cmp.run(conn, ["AAAA"], store_db=sdb, ocr_dbs=[ocr_db])
    fy_tax = conn.execute(f"SELECT doc_key, value, check_status FROM {cmp.TABLE} "
                          "WHERE line_item='tax' AND column_role='last_fy'").fetchall()
    conn.close()
    assert len(fy_tax) == 2
    assert all(r[1] == pytest.approx(277.42 * 1e7) and r[2] == "repeat_ok" for r in fy_tax)


def test_xbrl_conflict_blocks_repeat_ok_and_sum_ok_and_drops_ocr_only(tmp_path):
    """A cell whose (basis, line_item, period_start, period_end) has a conflicting XBRL value never gets
    sum_ok or repeat_ok: clean/agreed cells stay 'unchecked' with check_detail 'xbrl_conflict <xbrl value>',
    OCR-only cells under R-013 are dropped instead of gaining repeat_ok, while ytd (6M/9M) has no XBRL
    and still gets sum_ok/repeat_ok."""
    import json, pymupdf

    # (a) Clean two-filing PDFs repeating a quarter other_expenses (300.00 vs XBRL 500.00) and a FY row
    # (800.00 vs annual facts 1,200.00) that satisfies Q2 current+preceding=ytd arithmetic: stays unchecked
    # with xbrl_conflict, while ytd (6M, no XBRL) still gets sum_ok.
    d1 = tmp_path / "clean_conflict"
    d1.mkdir()
    conn = _conn()
    conn.execute("""
        CREATE TABLE fin_annual_line (symbol TEXT, isin TEXT, fiscal_year TEXT, period_end TEXT, basis TEXT,
            statement TEXT, line_item TEXT, caption TEXT, value REAL, unit TEXT, scale REAL, doc_key TEXT,
            page INTEGER, quote TEXT, source_db TEXT, source_table TEXT, source_rowid TEXT, known_at TEXT,
            known_at_source TEXT, is_reported INTEGER, is_derived INTEGER, definition TEXT, period_type TEXT)
    """)
    _xbrl(conn, "2024-06-30", "other_expenses", 500.00 * 1e7)
    conn.execute("INSERT INTO fin_annual_line (symbol, basis, period_end, line_item, value, source_table, period_type) "
                 "VALUES ('AAAA', 'consolidated', '2024-03-31', 'other_expenses', ?, 'facts', 'FY')", (1200.00 * 1e7,))

    def _rows_oe(c, p, y, yt, py, lfy):
        return [
            ("1 Revenue from operations", ("1,000", "900", "800", "1,900", "1,700", "4,000")),
            ("2 Other income", ("100", "90", "80", "190", "170", "400")),
            ("3 Total income", ("1,100", "990", "880", "2,090", "1,870", "4,400")),
            ("4a Other expenses", (c, p, y, yt, py, lfy)),
            ("4 Total expenses", ("800", "720", "640", "1,520", "1,360", "3,200")),
            ("5 Profit before tax", ("300", "270", "240", "570", "510", "1,200")),
            ("6 Total tax expense", ("75", "67", "60", "142", "127", "300")),
            ("7 Profit for the period", ("225", "203", "180", "428", "383", "900")),
        ]

    for dk, fdate, k_at, dates, oe_vals in (
        ("q2_a.pdf", "2024-11-10", "2024-11-10T12:00:00",
         ("30.09.2024", "30.06.2024", "30.09.2023", "30.09.2024", "30.09.2023", "31.03.2024"),
         ("320.00", "300.00", "280.00", "620.00", "540.00", "800.00")),
        ("q3_b.pdf", "2025-02-10", "2025-02-10T12:00:00",
         ("31.12.2024", "30.09.2024", "31.12.2023", "31.12.2024", "31.12.2023", "31.03.2024"),
         ("340.00", "320.00", "290.00", "960.00", "830.00", "800.00")),
    ):
        ppath = d1 / dk
        doc = pymupdf.open()
        pg = doc.new_page(width=800, height=600)
        pg.insert_text((40, 20), "Statement of Consolidated Unaudited Financial Results", fontsize=8)
        pg.insert_text((40, 35), "Rs. in Crore", fontsize=8)
        for a, dt in zip(COLS, dates):
            pg.insert_text((a - pymupdf.get_text_length(dt, fontsize=7), 50), dt, fontsize=7)
        for idx, (lbl, vals) in enumerate(_rows_oe(*oe_vals)):
            y = 70.0 + 14.0 * idx
            pg.insert_text((20, y), lbl, fontsize=7)
            for a, v in zip(COLS, vals):
                pg.insert_text((a - pymupdf.get_text_length(v, fontsize=7), y), v, fontsize=7)
        doc.save(str(ppath))
        doc.close()
        conn.execute("INSERT INTO doc VALUES (?,'AAAA','INE000A01001','results','results','Results',"
                     "?,?,1,?,'bse',?)", (dk, fdate, k_at, f"sha_{dk}", str(ppath)))
    conn.commit()
    cmp.run(conn, ["AAAA"])
    rows_clean = conn.execute(
        f"SELECT doc_key, column_role, period_end, period_type, value, check_status, check_detail "
        f"FROM {cmp.TABLE} WHERE line_item='other_expenses'"
    ).fetchall()
    conn.close()
    q_jun = [r for r in rows_clean if r[2] == "2024-06-30" and r[3] == "quarter"]
    assert len(q_jun) == 1
    assert q_jun[0][5] == "unchecked" and q_jun[0][6] == f"xbrl_conflict {500.0 * 1e7}"
    fy_oe = [r for r in rows_clean if r[2] == "2024-03-31" and r[3] == "fy"]
    assert len(fy_oe) == 2
    assert all(r[5] == "unchecked" and r[6] == f"xbrl_conflict {1200.0 * 1e7}" for r in fy_oe)
    ytd_oe = [r for r in rows_clean if r[0] == "q2_a.pdf" and r[1] == "ytd"]
    assert len(ytd_oe) == 1 and ytd_oe[0][5] == "sum_ok"

    # (b) Both OCR-only and layer-only (recheck_layer) cells contradicting XBRL across two filings are dropped
    # instead of gaining repeat_ok
    d2 = tmp_path / "ocr_conflict"
    d2.mkdir()
    conn = _conn()
    _xbrl(conn, "2024-09-30", "other_expenses", 24157.0 * 1e5)
    _xbrl(conn, "2024-09-30", "pbt", -290.10 * 1e5)
    ocr_db = d2 / "ocr.db"
    ocon = sqlite3.connect(ocr_db)
    ocon.execute("CREATE TABLE ocr_page (doc_key TEXT, page INTEGER, method TEXT, words_json TEXT)")
    for dk, fdate, k_at, dates in (
        ("ocr1.pdf", "2024-11-10", "2024-11-10T12:00:00",
         ("30.09.2024", "30.06.2024", "30.09.2023", "30.09.2024", "30.09.2023", "31.03.2024")),
        ("ocr2.pdf", "2025-02-10", "2025-02-10T12:00:00",
         ("31.12.2024", "30.09.2024", "31.12.2023", "31.12.2024", "31.12.2023", "31.03.2024")),
    ):
        ppath = d2 / dk
        doc = pymupdf.open()
        pg = doc.new_page(width=800, height=600)
        pg.insert_text((40, 20), "Statement of Consolidated Unaudited Financial Results", fontsize=8)
        pg.insert_text((40, 35), "Rs. in Lakhs", fontsize=8)
        for a, dt in zip(COLS, dates):
            pg.insert_text((a - pymupdf.get_text_length(dt, fontsize=7), 50), dt, fontsize=7)
        r_layer = [
            ("1 Revenue from operations", ("1,000.00", "900.00", "800.00", "1,900.00", "1,700.00", "4,000.00")),
            ("2 Other income", ("100.00", "90.00", "80.00", "190.00", "170.00", "400.00")),
            ("3 Total income", ("1,100.00", "990.00", "880.00", "2,090.00", "1,870.00", "4,400.00")),
            ("4 Total expenses", ("800.00", "720.00", "640.00", "1,520.00", "1,360.00", "3,200.00")),
            ("5 Profit before tax", ("(284.50)", "(284.50)", "(168.80)", "(504.30)", "(403.90)", "(282.90)")),
            ("6 Total tax expense", ("75.00", "67.00", "60.00", "142.00", "127.00", "300.00")),
            ("7 Profit for the period", ("225.00", "203.00", "180.00", "428.00", "383.00", "900.00")),
            ("8 Paid-up equity share capital", ("100.00", "100.00", "100.00", "100.00", "100.00", "100.00")),
        ]
        for idx, (lbl, vals) in enumerate(r_layer):
            y = 70.0 + 14.0 * idx
            pg.insert_text((20, y), lbl, fontsize=7)
            for a, v in zip(COLS, vals):
                pg.insert_text((a - pymupdf.get_text_length(v, fontsize=7), y), v, fontsize=7)
        for i in range(15):
            pg.insert_text((20, 320 + 12 * i), f"Zxv{i}omer Qlarton{i} Vroptex{i}", fontsize=7)
        doc.save(str(ppath))
        doc.close()
        conn.execute("INSERT INTO doc VALUES (?,'AAAA','INE000A01001','results','results','Results',"
                     "?,?,1,?,'bse',?)", (dk, fdate, k_at, f"sha_{dk}", str(ppath)))
        r_set = [
            ("1 Revenue from operations", ("1,000.00", "900.00", "800.00", "1,900.00", "1,700.00", "4,000.00")),
            ("2 Other income", ("100.00", "90.00", "80.00", "190.00", "170.00", "400.00")),
            ("3 Total income", ("1,100.00", "990.00", "880.00", "2,090.00", "1,870.00", "4,400.00")),
            ("4a Other expenses", ("118.44", "118.44", "118.44", "236.88", "236.88", "444.88")),
            ("4 Total expenses", ("800.00", "720.00", "640.00", "1,520.00", "1,360.00", "3,200.00")),
            ("6 Total tax expense", ("75.00", "67.00", "60.00", "142.00", "127.00", "300.00")),
            ("7 Profit for the period", ("225.00", "203.00", "180.00", "428.00", "383.00", "900.00")),
            ("8 Paid-up equity share capital", ("100.00", "100.00", "100.00", "100.00", "100.00", "100.00")),
        ]
        words = [(40.0, 15.0, 220.0, 23.0, "Statement of Consolidated Unaudited Financial Results"),
                 (40.0, 28.0, 120.0, 36.0, "Rs. in Lakhs")]
        for a, dt in zip(COLS, dates):
            words.append((a - 40.0, 44.0, a, 52.0, dt))
        for idx, (lbl, vals) in enumerate(r_set):
            y = 65.0 + 14.0 * idx
            x = 20.0
            for tok in lbl.split():
                words.append((x, y - 3.0, x + 6.0 * len(tok), y + 3.0, tok))
                x += 6.0 * len(tok) + 3.0
            for a, v in zip(COLS, vals):
                words.append((a - 6.0 * len(v), y - 3.0, a, y + 3.0, v))
        ocon.execute("INSERT INTO ocr_page VALUES (?, 1, 'ocr_rapid', ?)", (dk, json.dumps(words)))
    ocon.commit()
    ocon.close()
    conn.commit()
    sdb = d2 / "store.db"
    dst = sqlite3.connect(sdb)
    conn.backup(dst)
    dst.close()
    cmp.run(conn, ["AAAA"], store_db=sdb, ocr_dbs=[ocr_db])
    sep_conflicts = conn.execute(
        f"SELECT line_item, check_status FROM {cmp.TABLE} "
        f"WHERE line_item IN ('other_expenses', 'pbt') AND period_end='2024-09-30' AND period_type='quarter'"
    ).fetchall()
    conn.close()
    assert sep_conflicts == []


def test_prewindow_xbrl_input_preserves_sum_ok_but_blocks_unconfirmed_repeat(tmp_path):
    """T-223 Cause 1: unserved pre-window fin_quarter_xbrl_input still yields xbrl_ok on matches and blocks
    unconfirmed component lines, but never strips self-consistent sum_ok cells when fin_quarter_xbrl is empty."""
    import json, pymupdf

    d = tmp_path / "xbrl_input"
    d.mkdir()
    conn = _conn()
    conn.execute("CREATE TABLE fin_quarter_xbrl_input (symbol TEXT, basis TEXT, period_end TEXT, line_item TEXT, value REAL)")
    for item, val in (
        ("total_income", 810000000.0),
        ("total_expenses", 690000000.0),
        ("pbt_before_exceptional", 120000000.0),
        ("other_expenses", 300000000.0),
    ):
        conn.execute("INSERT INTO fin_quarter_xbrl_input VALUES ('AAAA','standalone','2023-09-30',?,?)", (item, val))
    dates = ("30.09.2024", "30.06.2024", "30.09.2023", "30.09.2024", "30.09.2023", "31.03.2024")
    dates2 = ("31.12.2024", "30.09.2024", "31.12.2023", "31.12.2024", "31.12.2023", "31.03.2024")
    ocr_db = d / "ocr.db"
    ocon = sqlite3.connect(ocr_db)
    ocon.execute("CREATE TABLE ocr_page (doc_key TEXT, page INTEGER, method TEXT, words_json TEXT)")
    ppath = d / "q2.pdf"
    doc = pymupdf.open()
    pg = doc.new_page(width=800, height=600)
    pg.insert_text((40, 20), "Garbled xxx yyy zzz", fontsize=8)
    for i in range(15):
        pg.insert_text((20, 320 + 12 * i), f"Zxv{i}omer Qlarton{i} Vroptex{i}", fontsize=7)
    doc.save(str(ppath))
    doc.close()
    conn.execute("INSERT INTO doc VALUES ('q2.pdf','AAAA','INE000A01001','results','results','Results',"
                 "'2024-11-10','2024-11-10T12:00:00',1,'sha_q2','bse',?)", (str(ppath),))
    rows_ocr = [
        ("1 Revenue from operations", ("9,000.35", "8,200.92", "8,000.0", "17,201.27", "16,000.00", "32,000.00")),
        ("2 Other income", ("100.00", "90.00", "39.0", "190.00", "80.00", "200.00")),
        ("3 Total income", ("9,100.35", "8,290.92", "8,039.0", "17,391.27", "16,080.00", "32,200.00")),
        ("4a Other expenses", ("2,000.00", "1,800.00", "1,500.0", "3,800.00", "3,100.00", "6,000.00")),
        ("4 Total expenses", ("7,500.00", "7,000.00", "6,870.3", "14,500.00", "13,800.00", "28,000.00")),
        ("5. Profit before exceptional and extraordinary items and tax", ("1,600.35", "1,290.92", "1,168.7", "2,891.27", "2,280.00", "4,200.00")),
        ("6 Total tax expense", ("400.00", "320.00", "290.0", "720.00", "570.00", "1,050.00")),
        ("7 Profit for the period", ("1,200.35", "970.92", "878.7", "2,171.27", "1,710.00", "3,150.00")),
    ]
    c_wide = (340.0, 420.0, 500.0, 580.0, 660.0, 740.0)
    words = [(40.0, 15.0, 220.0, 23.0, "Statement of Standalone Unaudited Financial Results"),
             (40.0, 28.0, 120.0, 36.0, "Rs. in Lakhs")]
    for a, dt in zip(c_wide, dates):
        words.append((a - 45.0, 44.0, a, 52.0, dt))
    for idx, (lbl, vals) in enumerate(rows_ocr):
        y = 65.0 + 14.0 * idx
        x = 20.0
        for tok in lbl.split():
            words.append((x, y - 3.0, x + 4.5 * len(tok), y + 3.0, tok))
            x += 4.5 * len(tok) + 2.5
        for a, v in zip(c_wide, vals):
            words.append((a - 4.5 * len(v), y - 3.0, a, y + 3.0, v))
    ocon.execute("INSERT INTO ocr_page VALUES ('q2.pdf', 1, 'ocr_rapid', ?)", (json.dumps(words),))

    # Second clean PDF repeating the unconfirmed 2023-09-30 other_expenses (1,500.0 lakh = 150M vs xbrl_input 300M)
    ppath2 = d / "q3_clean.pdf"
    doc2 = pymupdf.open()
    pg2 = doc2.new_page(width=800, height=600)
    pg2.insert_text((40, 20), "Statement of Standalone Unaudited Financial Results", fontsize=8)
    pg2.insert_text((40, 35), "Rs. in Lakhs", fontsize=8)
    for a, dt in zip(c_wide, dates2):
        pg2.insert_text((a - pymupdf.get_text_length(dt, fontsize=7), 50), dt, fontsize=7)
    rows_clean = [
        ("1 Revenue from operations", ("9,100.00", "9,000.35", "8,000.00", "26,300.00", "16,000.00", "32,000.00")),
        ("2 Other income", ("100.00", "100.00", "39.00", "290.00", "80.00", "200.00")),
        ("3 Total income", ("9,200.00", "9,100.35", "8,039.00", "26,590.00", "16,080.00", "32,200.00")),
        ("4a Other expenses", ("2,100.00", "2,000.00", "1,500.00", "5,900.00", "3,100.00", "6,000.00")),
        ("4 Total expenses", ("7,600.00", "7,500.00", "6,870.30", "22,100.00", "13,800.00", "28,000.00")),
        ("5. Profit before exceptional and extraordinary items and tax", ("1,600.00", "1,600.35", "1,168.70", "4,490.00", "2,280.00", "4,200.00")),
        ("6 Total tax expense", ("400.00", "400.00", "290.00", "1,120.00", "570.00", "1,050.00")),
        ("7 Profit for the period", ("1,200.00", "1,200.35", "878.70", "3,370.00", "1,710.00", "3,150.00")),
    ]
    for idx, (lbl, vals) in enumerate(rows_clean):
        y = 70.0 + 14.0 * idx
        pg2.insert_text((20, y), lbl, fontsize=7)
        for a, v in zip(c_wide, vals):
            pg2.insert_text((a - pymupdf.get_text_length(v, fontsize=7), y), v, fontsize=7)
    doc2.save(str(ppath2))
    doc2.close()
    conn.execute("INSERT INTO doc VALUES ('q3_clean.pdf','AAAA','INE000A01001','results','results','Results',"
                 "'2025-02-10','2025-02-10T12:00:00',1,'sha_q3','bse',?)", (str(ppath2),))
    ocon.commit()
    ocon.close()
    conn.commit()
    sdb = d / "store.db"
    dst = sqlite3.connect(sdb)
    conn.backup(dst)
    dst.close()
    cmp.run(conn, ["AAAA"], store_db=sdb, ocr_dbs=[ocr_db])
    kept = {
        (r[9], r[20], r[21])
        for r in conn.execute(
            f"SELECT * FROM {cmp.TABLE} WHERE doc_key='q2.pdf' AND column_role='year_ago'"
        )
    }
    conn.close()
    assert ("total_income", "sum_ok", None) in kept
    assert ("total_expenses", "sum_ok", None) in kept
    assert ("pbt_before_exceptional", "sum_ok", None) in kept
    assert all(r[0] != "other_expenses" for r in kept)


def test_choose_rows_uses_all_columns_and_arithmetic_and_eps_ok_covers_diluted():
    """T-223 Cause 2: _choose_rows inspects non-current XBRL columns (unreadable current or current tie) and
    arithmetic ties; _eps_ok checks eps_diluted alongside eps_basic; _cross_column_marks uses 0.02 for eps_diluted."""
    conn = _conn()
    conn.execute("INSERT INTO share_capital (symbol, as_of_date, basis, shares_outstanding, known_at) "
                 "VALUES ('AAAA', '2024-03-31', 'standalone', 10000000.0, '2024-05-01T00:00:00')")
    _xbrl(conn, "2024-12-31", "eps_basic", -0.68, basis="standalone")
    _xbrl(conn, "2024-12-31", "eps_diluted", -0.68, basis="standalone")
    _xbrl(conn, "2025-12-31", "eps_basic", -1.25, basis="standalone")
    _xbrl(conn, "2025-12-31", "eps_diluted", -1.25, basis="standalone")
    _xbrl(conn, "2024-03-31", "eps_diluted", -2.17, basis="standalone")
    _xbrl(conn, "2025-03-31", "eps_basic", -2.18, basis="standalone")
    _xbrl(conn, "2025-03-31", "eps_diluted", -2.18, basis="standalone")
    xbrl = cmp.xbrl_index(conn, "AAAA")
    af = {("standalone", "2024-03-31"): {"eps_diluted": [-2.17]},
          ("standalone", "2025-03-31"): {"eps_basic": [-2.18], "eps_diluted": [-2.18]}}

    # Q3FY25 table: current eps_diluted has broken parens on both rows, last_fy settles row 2 (-2.17);
    # 9MFY25 pat = -2,410 lakh / 10 cr shares = -2.41 confirms eps_diluted via _eps_ok.
    d_q3_25 = ("31.12.2024", "30.09.2024", "31.12.2023", "31.12.2024", "31.12.2023", "31.03.2024")
    r_q3_25 = [
        ("1 Revenue from operations", ("1,000.00", "900.00", "800.00", "1,900.00", "1,700.00", "4,000.00")),
        ("2 Other income", ("100.00", "90.00", "80.00", "190.00", "170.00", "400.00")),
        ("3 Total income", ("1,100.00", "990.00", "880.00", "2,090.00", "1,870.00", "4,400.00")),
        ("4 Total expenses", ("1,168.00", "1,044.00", "900.00", "2,331.00", "2,000.00", "4,617.00")),
        ("5 Profit before tax", ("(68.00)", "(54.00)", "(20.00)", "(241.00)", "(130.00)", "(217.00)")),
        ("6 Total tax expense", ("0.00", "0.00", "0.00", "0.00", "0.00", "0.00")),
        ("7 Profit for the period", ("(68.00)", "(54.00)", "(20.00)", "(241.00)", "(130.00)", "(217.00)")),
        ("8a Basic EPS", ("(0.72)", "(0.56)", "(0.22)", "(2.48)", "(1.35)", "(1.03)")),
        ("8b Diluted EPS", ("(0.72", "(0.56)", "(0.22)", "2.48)", "(1.35)", "(1.03)")),
        ("9a Basic", ("(0.68)", "(0.54)", "(0.20)", "(2.41)", "(1.30)", "(2.17)")),
        ("9b Diluted", ("0.68)", "(0.54)", "(0.20)", "(2.41)", "(1.30)", "(2.17)")),
    ]
    def _wide_page(rows, unit="Rs. in Lakhs", title="Statement of Standalone Unaudited Financial Results", dates=d_q3_25):
        c_wide = (280.0, 360.0, 440.0, 520.0, 600.0, 680.0)
        words = [(40.0, 5.0, 220.0, 13.0, title, 0, 0, 0), (40.0, 15.0, 120.0, 23.0, unit, 0, 0, 0)]
        for anchor, text in zip(c_wide, dates):
            words.append((anchor - 4.0 * len(text), 27.0, anchor, 33.0, text, 0, 0, 0))
        for i, (lbl, vals) in enumerate(rows):
            y, x = 50.0 + 10.0 * i, 20.0
            for word in lbl.split():
                w = 4.0 * len(word)
                words.append((x, y - 3.0, x + w, y + 3.0, word, 0, 0, 0))
                x += w + 2.5
            for anchor, text in zip(c_wide, vals):
                words.append((anchor - 4.0 * len(text), y - 3.0, anchor, y + 3.0, text, 0, 0, 0))
        return cmp.rows_from_words(words)

    t1 = cmp.read_page(_wide_page(r_q3_25, unit="Rs. in Lakhs",
                                  title="Statement of Standalone Unaudited Financial Results", dates=d_q3_25), ocr=True)
    out1 = cmp._table_rows(conn, "AAAA", "INE000A01001", "doc25", 4, "2025-01-30T12:00:00", t1, xbrl, [], annual_facts=af)
    ed1 = _cells(out1, "eps_diluted", "ytd")
    assert len(ed1) == 1 and ed1[0][11] == pytest.approx(-2.41) and ed1[0][20] == "sum_ok"

    # Q3FY26 table: current ties (-1.25 == -1.25), year_ago (-0.68) and last_fy (-2.18) pick total EPS (-2.41)
    d_q3_26 = ("31.12.2025", "30.09.2025", "31.12.2024", "31.12.2025", "31.12.2024", "31.03.2025")
    r_q3_26 = [
        ("1 Revenue from operations", ("1,000.00", "900.00", "1,000.00", "1,900.00", "1,900.00", "4,000.00")),
        ("2 Other income", ("100.00", "90.00", "100.00", "190.00", "190.00", "400.00")),
        ("3 Total income", ("1,100.00", "990.00", "1,100.00", "2,090.00", "2,090.00", "4,400.00")),
        ("4 Total expenses", ("1,225.00", "1,065.00", "1,168.00", "2,370.00", "2,331.00", "4,618.00")),
        ("5 Profit before tax", ("(125.00)", "(75.00)", "(68.00)", "(280.00)", "(241.00)", "(218.00)")),
        ("6 Total tax expense", ("0.00", "0.00", "0.00", "0.00", "0.00", "0.00")),
        ("7 Profit for the period", ("(125.00)", "(75.00)", "(68.00)", "(280.00)", "(241.00)", "(218.00)")),
        ("8a Basic EPS", ("(1.25)", "(0.75)", "(0.72)", "(2.80)", "(2.48)", "(2.24)")),
        ("8b Diluted EPS", ("(1.25)", "(0.75)", "(0.72)", "(2.80)", "(2.48)", "(2.24)")),
        ("9a Basic", ("(1.25)", "(0.75)", "(0.68)", "(2.80)", "(2.41)", "(2.18)")),
        ("9b Diluted", ("(1.25)", "(0.75)", "(0.68)", "(2.80)", "(2.41)", "(2.18)")),
    ]
    t2 = cmp.read_page(_wide_page(r_q3_26, unit="Rs. in Lakhs",
                                  title="Statement of Standalone Unaudited Financial Results", dates=d_q3_26))
    out2 = cmp._table_rows(conn, "AAAA", "INE000A01001", "doc26", 4, "2026-02-04T12:00:00", t2, xbrl, [], annual_facts=af)
    repeated = cmp._apply_repeats(out1 + out2)
    py_eb = [r for r in repeated if r[16] == "doc26" and r[6] == "prior_ytd" and r[9] == "eps_basic"]
    py_ed = [r for r in repeated if r[16] == "doc26" and r[6] == "prior_ytd" and r[9] == "eps_diluted"]
    assert py_eb[0][11] == pytest.approx(-2.41) and py_eb[0][20] in cmp.CHECK_OK
    assert py_ed[0][11] == pytest.approx(-2.41) and py_ed[0][20] in cmp.CHECK_OK

    # Arithmetic tie-breaker on duplicate PAT rows & Q2 cross-column tolerance for eps_diluted (0.02, not rupee_tol)
    r_dup_pat = [
        ("1 Revenue from operations", ("1,000.00", "900.00", "800.00", "1,900.00", "3,100.17", "3,500.00")),
        ("2 Other income", ("100.00", "90.00", "80.00", "190.00", "208.56", "350.00")),
        ("3 Total income", ("1,100.00", "990.00", "880.00", "2,090.00", "3,308.73", "3,850.00")),
        ("4 Total expenses", ("800.00", "720.00", "640.00", "1,520.00", "3,099.91", "2,800.00")),
        ("5 Profit before tax", ("300.00", "270.00", "240.00", "570.00", "208.82", "1,050.00")),
        ("6 Total tax expense", ("75.00", "67.00", "60.00", "142.00", "40.06", "262.00")),
        ("7 Profit after tax", ("225.00", "203.00", "180.00", "428.00", "166.76", "788.00")),
        ("7b Profit for the period", ("225.00", "203.00", "180.00", "428.00", "168.76", "788.00")),
        ("8b Diluted EPS", ("1.00", "1.00", "0.80", "5.00", "0.75", "3.00")),
    ]
    t3 = cmp.read_page(_wide_page(r_dup_pat, unit="Rs. in Crore", dates=DATES))
    out3 = cmp._table_rows(conn, "AAAA", "INE000A01001", "doc3", 4, "2026-10-20T12:00:00", t3, {}, [])
    pat_py = _cells(out3, "pat", "prior_ytd")
    assert len(pat_py) == 1 and pat_py[0][11] == pytest.approx(168.76 * 1e7) and pat_py[0][20] == "sum_ok"
    ed_ytd = _cells(out3, "eps_diluted", "ytd")
    assert ed_ytd[0][20] == "unchecked"   # 1.00 + 1.00 != 5.00 (0.02 tolerance, never rupee_tol)
    conn.close()


def test_integer_eps_without_decimal_dots_uses_xbrl_two_decimals_for_repeat(tmp_path):
    """T-223 Cause 3: when every EPS token lost its dot ('070', '198', '197'), XBRL matching sets eps_decimals=2."""
    import json, pymupdf

    d = tmp_path / "eps_nodot"
    d.mkdir()
    conn = _conn()
    _xbrl(conn, "2024-12-31", "eps_basic", 0.70, basis="standalone")
    _xbrl(conn, "2024-12-31", "eps_diluted", 0.70, basis="standalone")
    _xbrl(conn, "2024-09-30", "eps_basic", 0.78, basis="standalone")
    dates1 = ("31.12.2024", "30.09.2024", "31.12.2023", "31.12.2024", "31.12.2023", "31.03.2024")
    rows1 = [
        ("1 Revenue from operations", ("1,000.00", "900.00", "800.00", "1,900.00", "1,700.00", "4,000.00")),
        ("2 Other income", ("100.00", "90.00", "80.00", "190.00", "170.00", "400.00")),
        ("3 Total income", ("1,100.00", "990.00", "880.00", "2,090.00", "1,870.00", "4,400.00")),
        ("4 Total expenses", ("800.00", "720.00", "640.00", "1,520.00", "1,360.00", "3,200.00")),
        ("5 Profit before tax", ("300.00", "270.00", "240.00", "570.00", "510.00", "1,200.00")),
        ("6 Total tax expense", ("75.00", "67.00", "60.00", "142.00", "127.00", "300.00")),
        ("7 Profit for the period", ("225.00", "203.00", "180.00", "428.00", "383.00", "900.00")),
        ("8a Basic EPS", ("070", "078", "040", "198", "120", "040")),
        ("8b Diluted EPS", ("070", "077", "040", "197", "120", "040")),
    ]
    p1 = d / "y1.pdf"
    doc1 = pymupdf.open()
    pg1 = doc1.new_page(width=800, height=600)
    pg1.insert_text((40, 20), "Statement of Standalone Unaudited Financial Results", fontsize=8)
    pg1.insert_text((40, 35), "Rs. in Lakhs", fontsize=8)
    for a, dt in zip(COLS, dates1):
        pg1.insert_text((a - pymupdf.get_text_length(dt, fontsize=7), 50), dt, fontsize=7)
    for idx, (lbl, vals) in enumerate(rows1):
        y = 70.0 + 14.0 * idx
        pg1.insert_text((20, y), lbl, fontsize=7)
        for a, v in zip(COLS, vals):
            pg1.insert_text((a - pymupdf.get_text_length(v, fontsize=7), y), v, fontsize=7)
    doc1.save(str(p1))
    doc1.close()
    conn.execute("INSERT INTO doc VALUES ('y1.pdf','AAAA','INE000A01001','results','results','Results',"
                 "'2025-02-06','2025-02-06T12:00:00',1,'sha_y1','bse',?)", (str(p1),))

    # Year 2: clean layer '197' vs bad OCR '107' on 9MFY25 eps_diluted must match 1.97 via _has_repeat_match
    dates2 = ("31.12.2025", "30.09.2025", "31.12.2024", "31.12.2025", "31.12.2024", "31.03.2025")
    layer2 = [
        ("1 Revenue from operations", ("1,100.00", "1,000.00", "1,000.00", "2,100.00", "1,900.00", "4,100.00")),
        ("2 Other income", ("110.00", "100.00", "100.00", "210.00", "190.00", "410.00")),
        ("3 Total income", ("1,210.00", "1,100.00", "1,100.00", "2,310.00", "2,090.00", "4,510.00")),
        ("4 Total expenses", ("880.00", "800.00", "800.00", "1,680.00", "1,520.00", "3,300.00")),
        ("5 Profit before tax", ("330.00", "300.00", "300.00", "630.00", "570.00", "1,210.00")),
        ("6 Total tax expense", ("82.00", "75.00", "75.00", "157.00", "142.00", "302.00")),
        ("7 Profit for the period", ("248.00", "225.00", "225.00", "473.00", "428.00", "908.00")),
        ("8a Basic EPS", ("090", "085", "070", "250", "198", "280")),
        ("8b Diluted EPS", ("090", "085", "070", "250", "197", "280")),
    ]
    ocr2 = layer2[:-2] + [
        ("8a Basic EPS", ("0.90", "0.85", "0.70", "2.50", "1.98", "2.80")),
        ("8b Diluted EPS", ("0.90", "0.85", "0.70", "2.50", "1.07", "2.80")),
    ]
    p2 = d / "y2.pdf"
    doc2 = pymupdf.open()
    pg2 = doc2.new_page(width=800, height=600)
    pg2.insert_text((40, 20), "Statement of Standalone Unaudited Financial Results", fontsize=8)
    pg2.insert_text((40, 35), "Rs. in Lakhs", fontsize=8)
    for a, dt in zip(COLS, dates2):
        pg2.insert_text((a - pymupdf.get_text_length(dt, fontsize=7), 50), dt, fontsize=7)
    for idx, (lbl, vals) in enumerate(layer2):
        y = 70.0 + 14.0 * idx
        pg2.insert_text((20, y), lbl, fontsize=7)
        for a, v in zip(COLS, vals):
            pg2.insert_text((a - pymupdf.get_text_length(v, fontsize=7), y), v, fontsize=7)
    for i in range(15):
        pg2.insert_text((20, 320 + 12 * i), f"Zxv{i}omer Qlarton{i} Vroptex{i}", fontsize=7)
    doc2.save(str(p2))
    doc2.close()
    conn.execute("INSERT INTO doc VALUES ('y2.pdf','AAAA','INE000A01001','results','results','Results',"
                 "'2026-02-13','2026-02-13T12:00:00',1,'sha_y2','bse',?)", (str(p2),))
    ocr_db = d / "ocr.db"
    ocon = sqlite3.connect(ocr_db)
    ocon.execute("CREATE TABLE ocr_page (doc_key TEXT, page INTEGER, method TEXT, words_json TEXT)")
    words = [(40.0, 15.0, 220.0, 23.0, "Statement of Standalone Unaudited Financial Results"),
             (40.0, 28.0, 120.0, 36.0, "Rs. in Lakhs")]
    for a, dt in zip(COLS, dates2):
        words.append((a - 40.0, 44.0, a, 52.0, dt))
    for idx, (lbl, vals) in enumerate(ocr2):
        y = 65.0 + 14.0 * idx
        x = 20.0
        for tok in lbl.split():
            words.append((x, y - 3.0, x + 6.0 * len(tok), y + 3.0, tok))
            x += 6.0 * len(tok) + 3.0
        for a, v in zip(COLS, vals):
            words.append((a - 6.0 * len(v), y - 3.0, a, y + 3.0, v))
    ocon.execute("INSERT INTO ocr_page VALUES ('y2.pdf', 1, 'ocr_rapid', ?)", (json.dumps(words),))
    ocon.commit()
    ocon.close()
    conn.commit()
    sdb = d / "store.db"
    dst = sqlite3.connect(sdb)
    conn.backup(dst)
    dst.close()
    cmp.run(conn, ["AAAA"], store_db=sdb, ocr_dbs=[ocr_db])
    y2_ed = conn.execute(
        f"SELECT value, check_status FROM {cmp.TABLE} "
        "WHERE doc_key='y2.pdf' AND column_role='prior_ytd' AND line_item='eps_diluted'"
    ).fetchall()
    conn.close()
    assert len(y2_ed) == 1 and y2_ed[0][0] == pytest.approx(1.97) and y2_ed[0][1] == "repeat_ok"


def test_probe_promotes_sum_ok_onto_agreed_partner_cells(tmp_path):
    """T-223 Cause 4: when probe confirms an identity via a layer-only partner cell (tci from layer + pat/oci agreed),
    the already-agreed partner cell (oci) also receives sum_ok instead of staying unchecked."""
    ocr = [
        ("1 Revenue from operations", ("1,000.00", "900.00", "800.00", "1,900.00", "1,451.86", "4,000.00")),
        ("2 Other income", ("100.00", "90.00", "80.00", "190.00", "446.98", "400.00")),
        ("3 Total income", ("1,100.00", "990.00", "880.00", "2,090.00", "1,898.84", "4,400.00")),
        ("4 Total expenses", ("800.00", "720.00", "640.00", "1,520.00", "2,310.79", "3,200.00")),
        ("5 Profit before tax", ("300.00", "270.00", "240.00", "570.00", "(411.95)", "1,200.00")),
        ("7 Profit for the period", ("225.00", "203.00", "180.00", "428.00", "(534.53)", "900.00")),
        ("8 Total other comprehensive income", ("10.00", "6.00", "5.00", "16.00", "14.63", "22.00")),
        ("9 Total comprehensive income", ("235.00", "209.00", "185.00", "444.00", "519.90)", "922.00")),
    ]
    layer = [
        ("Xyz garbled pat", vals) if lbl.startswith("7 ")
        else ("9 Total comprehensive income", ("235.00", "209.00", "185.00", "444.00", "(519.90)", "922.00"))
        if lbl.startswith("9 ") else (lbl, vals)
        for lbl, vals in ocr
    ]
    c_wide = (340.0, 420.0, 500.0, 580.0, 660.0, 740.0)
    rows, _rev = _build_pdf_and_ocr(tmp_path / "probe_agreed", layer, ocr, cols=c_wide)
    oci_py = _cells(rows, "other_comprehensive_income", "prior_ytd")
    tci_py = _cells(rows, "total_comprehensive_income", "prior_ytd")
    assert len(tci_py) == 1 and tci_py[0][20] == "sum_ok"
    assert len(oci_py) == 1 and oci_py[0][11] == pytest.approx(14.63 * 1e7) and oci_py[0][20] == "sum_ok"


def test_eps_blocks_skip_discontinued_and_keep_continuing():
    """R-023: read_page skips eps_basic/eps_diluted under a discontinued heading while keeping continuing/single EPS
    blocks, resetting section on any non-EPS matched row, and preserving first-block precedence without XBRL."""
    cols5 = (280.0, 360.0, 440.0, 520.0, 600.0)
    dates_q4 = ("31.03.2024", "31.12.2023", "31.03.2023", "31.03.2024", "31.03.2023")

    def _w5(x1: float, text: str, y: float) -> tuple:
        return (x1 - 4.0 * len(text), y - 3.0, x1, y + 3.0, text, 0, 0, 0)

    def _build_5col_page(body_rows):
        words = [
            (40.0, 5.0, 220.0, 13.0, "Statement of Standalone Audited Financial Results", 0, 0, 0),
            (40.0, 15.0, 120.0, 23.0, "Rs. in Lakhs", 0, 0, 0),
        ]
        words += [_w5(cols5[i], dt, 30.0) for i, dt in enumerate(dates_q4)]
        for idx, (lbl, vals, col_idxs) in enumerate(body_rows):
            y, x = 50.0 + 10.0 * idx, 20.0
            for word in lbl.split():
                w = 4.0 * len(word)
                words.append((x, y - 3.0, x + w, y + 3.0, word, 0, 0, 0))
                x += w + 2.5
            for col_i, val in zip(col_idxs, vals):
                anchor = cols5[col_i]
                parts = val.split()
                if len(parts) == 1:
                    words.append(_w5(anchor, parts[0], y))
                else:
                    rx = anchor
                    for p in reversed(parts):
                        pw = 4.0 * len(p)
                        words.append((rx - pw, y - 3.0, rx, y + 3.0, p, 0, 0, 0))
                        rx -= pw + 2.0
        return cmp.rows_from_words(words)

    pl_head = [
        ("1 Revenue from operations", ("11,792.36", "11,684.25", "10,354.56", "43,487.12", "44,152.02"), range(5)),
        ("2 Other income", ("55.43", "422.55", "285.97", "597.05", "815.56"), range(5)),
        ("3 Total income", ("11,847.79", "12,106.80", "10,640.53", "44,084.17", "44,967.58"), range(5)),
        ("4 Total expenses", ("11,645.80", "12,089.58", "9,644.28", "42,883.09", "40,051.49"), range(5)),
        ("5 Profit before exceptional items and tax", ("201.99", "17.22", "996.25", "1,201.08", "4,916.09"), range(5)),
        ("6 Total tax expense", ("(523.55)", "766.46", "331.58", "641.21", "(477.01)"), range(5)),
        ("Discontinued Operations", (), ()),
        ("7 Profit for the period", ("725.54", "(1,480.21)", "334.84", "(171.10)", "9,249.11"), range(5)),
    ]

    # (a) Mangled continuing Diluted ('(bl O1luted') + Discontinued block with 4 tokens at columns 2-5
    rows_a = pl_head + [
        ("Earnings Per Share (face value of Rs. 10 each)", (), ()),
        ("For Con tin ulna Operations", (), ()),
        ("(a) Basic", ("0 48", "(0 50)", "0 44", "0 37", "4 85"), range(5)),
        ("(bl O1luted", ("048", "(0.50)", "044", "037", "485"), range(5)),
        ("For Discontinued Operations", (), ()),
        ("cal BBSIC", ("(049)", "(022)", "(049)", "130"), (1, 2, 3, 4)),
        ("(b) Diluted", ("(049)", "(022)", "(049)", "130"), (1, 2, 3, 4)),
    ]
    conn = _conn()
    conn_a = _conn()
    _xbrl(conn_a, "2024-03-31", "eps_basic", 0.48, basis="standalone")
    table_a = cmp.read_page(_build_5col_page(rows_a))
    assert table_a is not None
    # Discontinued 4-token row is skipped; continuing Basic is intact and Diluted is absent.
    assert not any("eps_diluted" in col for col in table_a["values"].values())
    stored_a = cmp._table_rows(
        conn_a, "AAAA", "INE000A01001", "doc_a", 7, "2024-05-24T12:00:00", table_a,
        cmp.xbrl_index(conn_a, "AAAA"), [],
    )
    conn_a.close()
    assert _cells(stored_a, "eps_diluted", "current") == []
    assert _cells(stored_a, "eps_diluted", "preceding") == []
    assert [
        _cells(stored_a, "eps_basic", role)[0][11]
        for role in ("current", "preceding", "year_ago", "ytd", "prior_ytd")
    ] == pytest.approx([0.48, -0.50, 0.44, 0.37, 4.85])

    # (b) Clean continuing block + discontinued block -> both Basic and Diluted come from continuing block
    rows_b = pl_head + [
        ("For Continuing Operations", (), ()),
        ("(a) Basic", ("0.48", "(0.50)", "0.44", "0.37", "4.85"), range(5)),
        ("(b) Diluted", ("0.47", "(0.50)", "0.43", "0.36", "4.80"), range(5)),
        ("For Discontinued Operations", (), ()),
        ("(a) Basic", ("(0.49)", "(0.22)", "(0.49)", "1.30"), (1, 2, 3, 4)),
        ("(b) Diluted", ("(0.49)", "(0.22)", "(0.49)", "1.30"), (1, 2, 3, 4)),
    ]
    table_b = cmp.read_page(_build_5col_page(rows_b))
    stored_b = cmp._table_rows(conn, "AAAA", "INE000A01001", "doc_b", 7, "2024-05-24T12:00:00", table_b, {}, [])
    assert [
        _cells(stored_b, "eps_basic", role)[0][11]
        for role in ("current", "preceding", "year_ago", "ytd", "prior_ytd")
    ] == pytest.approx([0.48, -0.50, 0.44, 0.37, 4.85])
    assert [
        _cells(stored_b, "eps_diluted", role)[0][11]
        for role in ("current", "preceding", "year_ago", "ytd", "prior_ytd")
    ] == pytest.approx([0.47, -0.50, 0.43, 0.36, 4.80])

    # Second unheaded EPS block without XBRL never overwrites the first block
    rows_b2 = rows_b + [
        ("For Continuing and Discontinued Operations", (), ()),
        ("(a) Basic", ("(0.01)", "(0.72)", "0.22", "(0.12)", "6.15"), range(5)),
        ("(b) Diluted", ("(0.01)", "(0.72)", "0.22", "(0.12)", "6.10"), range(5)),
    ]
    table_b2 = cmp.read_page(_build_5col_page(rows_b2))
    stored_b2 = cmp._table_rows(conn, "AAAA", "INE000A01001", "doc_b2", 7, "2024-05-24T12:00:00", table_b2, {}, [])
    assert _cells(stored_b2, "eps_basic", "current")[0][11] == pytest.approx(0.48)
    assert _cells(stored_b2, "eps_diluted", "current")[0][11] == pytest.approx(0.47)

    # (c) Single EPS block (no EPS headings; earlier Discontinued Operations in P&L reset by pat) -> unchanged
    rows_c = pl_head + [
        ("8 Basic EPS", ("0.48", "(0.50)", "0.44", "0.37", "4.85"), range(5)),
        ("9 Diluted EPS", ("0.47", "(0.50)", "0.43", "0.36", "4.80"), range(5)),
    ]
    table_c = cmp.read_page(_build_5col_page(rows_c))
    stored_c = cmp._table_rows(conn, "AAAA", "INE000A01001", "doc_c", 7, "2024-05-24T12:00:00", table_c, {}, [])
    assert _cells(stored_c, "eps_basic", "current")[0][11] == pytest.approx(0.48)
    assert _cells(stored_c, "eps_diluted", "current")[0][11] == pytest.approx(0.47)
    conn.close()


def test_discontinued_pl_line_and_eps_heading_preserve_eps():
    """R-023 follow-up (T-223): blank discontinued P&L lines (e.g. SALSTEEL) never start a discontinued EPS
    section, and an 'Earnings per ...' heading resets any prior section before Basic/Diluted."""
    cols4 = (320.0, 400.0, 480.0, 560.0)
    dates_q1 = ("30.06.2024", "31.03.2024", "30.06.2023", "31.03.2024")

    def _w4(x1: float, text: str, y: float) -> tuple:
        return (x1 - 4.0 * len(text), y - 3.0, x1, y + 3.0, text, 0, 0, 0)

    def _build_4col_page(body_rows):
        words = [
            (40.0, 5.0, 220.0, 13.0, "Statement of Standalone Unaudited Financial Results", 0, 0, 0),
            (40.0, 15.0, 120.0, 23.0, "Rs. in Crores", 0, 0, 0),
        ]
        words += [_w4(cols4[i], dt, 30.0) for i, dt in enumerate(dates_q1)]
        for idx, (lbl, vals, col_idxs) in enumerate(body_rows):
            y, x = 50.0 + 10.0 * idx, 20.0
            for word in lbl.split():
                w = 4.0 * len(word)
                words.append((x, y - 3.0, x + w, y + 3.0, word, 0, 0, 0))
                x += w + 2.5
            for col_i, val in zip(col_idxs, vals):
                words.append(_w4(cols4[col_i], val, y))
        return cmp.rows_from_words(words)

    pl_head4 = [
        ("1 Revenue from operations", ("100.00", "120.00", "95.00", "410.00"), range(4)),
        ("2 Other income", ("1.00", "2.00", "1.50", "6.00"), range(4)),
        ("3 Total income", ("101.00", "122.00", "96.50", "416.00"), range(4)),
        ("4 Total expenses", ("100.80", "118.50", "96.35", "415.30"), range(4)),
        ("5 Profit before tax", ("0.20", "3.50", "0.15", "0.70"), range(4)),
        ("6 Tax expense", ("0.04", "0.80", "0.05", "0.23"), range(4)),
    ]

    conn = _conn()

    # (a) SALSTEEL Q1FY25 layout: blank discontinued P&L lines (OCR-noisy) + OCI + equity + Earnings per equity share
    rows_salsteel = pl_head4 + [
        ("Profit / (Loss) from discontinuing operatrons", (), ()),
        ("Tax expense of discontinuing operations", (), ()),
        ("Profw(Loss) from Discontinuing operatlons (after tax)", (), ()),
        ("Net Profit / (Loss) for the period (lx + Xll )", (), ()),
        ("Other Comprehensive income (Net of Tax)", ("0.01", "(0.08)", "0.04", "0.03"), range(4)),
        ("Total Comprehensive income/(Loss) (after tax)", ("0.17", "2.62", "0.14", "0.50"), range(4)),
        ("Paid-up Equity Share Capital (Face value Rs. 10/- each)", ("84.97", "84.97", "84.97", "84.97"), range(4)),
        ("Earnings per equity share :", (), ()),
        ("(1) Basic", ("0.02", "0.32", "0.01", "0.06"), range(4)),
        ("(2) Diluted", ("0.02", "0.32", "0.01", "0.06"), range(4)),
    ]
    table_sal = cmp.read_page(_build_4col_page(rows_salsteel))
    assert table_sal is not None
    stored_sal = cmp._table_rows(
        conn, "SALSTEEL", "INE000A01002", "doc_sal", 3, "2024-08-12T12:00:00", table_sal, {}, [],
    )
    assert [
        _cells(stored_sal, "eps_basic", role)[0][11]
        for role in ("current", "preceding", "year_ago", "last_fy")
    ] == pytest.approx([0.02, 0.32, 0.01, 0.06])
    assert [
        _cells(stored_sal, "eps_diluted", role)[0][11]
        for role in ("current", "preceding", "year_ago", "last_fy")
    ] == pytest.approx([0.02, 0.32, 0.01, 0.06])

    # (c) Blank discontinued P&L line followed directly (no EPS heading, no matched non-EPS row) by (a) Basic
    rows_direct = pl_head4 + [
        ("7 Profit for the period", ("0.16", "2.70", "0.10", "0.47"), range(4)),
        ("Profit / (Loss) from discontinued operations", (), ()),
        ("(a) Basic", ("1.00", "2.00", "3.00", "4.00"), range(4)),
    ]
    table_direct = cmp.read_page(_build_4col_page(rows_direct))
    assert table_direct is not None
    stored_direct = cmp._table_rows(
        conn, "SALSTEEL", "INE000A01002", "doc_dir", 3, "2024-08-12T12:00:00", table_direct, {}, [],
    )
    assert [
        _cells(stored_direct, "eps_basic", role)[0][11]
        for role in ("current", "preceding", "year_ago", "last_fy")
    ] == pytest.approx([1.00, 2.00, 3.00, 4.00])

    # (d) Short 'Discontinued Operations' heading followed by OCR-noisy 'Eamings per equity share :' resets section
    rows_eps_reset = pl_head4 + [
        ("7 Profit for the period", ("0.16", "2.70", "0.10", "0.47"), range(4)),
        ("Discontinued Operations", (), ()),
        ("Eamings per equity share :", (), ()),
        ("(1) Basic", ("1.50", "2.50", "3.50", "4.50"), range(4)),
    ]
    table_reset = cmp.read_page(_build_4col_page(rows_eps_reset))
    assert table_reset is not None
    stored_reset = cmp._table_rows(
        conn, "SALSTEEL", "INE000A01002", "doc_rst", 3, "2024-08-12T12:00:00", table_reset, {}, [],
    )
    assert [
        _cells(stored_reset, "eps_basic", role)[0][11]
        for role in ("current", "preceding", "year_ago", "last_fy")
    ] == pytest.approx([1.50, 2.50, 3.50, 4.50])
    conn.close()




