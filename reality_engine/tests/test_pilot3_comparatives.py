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
