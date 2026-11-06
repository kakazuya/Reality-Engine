"""DDL for the pilot3 core tables (T-049 part A).  Every fact row carries symbol, isin, period, basis,
value, unit, scale, ``known_at`` (from the filing record) and its source (doc + page, or source db +
table + rowid).  ``create(conn, tables)`` drops and recreates the named tables, so a part re-runs cleanly."""
from __future__ import annotations

import sqlite3

TABLES: dict[str, str] = {
    "company": """CREATE TABLE company (
        symbol TEXT, isin TEXT, isin_from TEXT, isin_to TEXT, isin_source TEXT, bse_code TEXT, name TEXT)""",
    "doc": """CREATE TABLE doc (
        doc_key TEXT PRIMARY KEY, symbol TEXT, isin TEXT, doc_type TEXT, doc_family TEXT, title TEXT,
        filing_date TEXT, known_at TEXT, pages INTEGER, sha256 TEXT, source TEXT, source_key TEXT)""",
    "doc_alias": """CREATE TABLE doc_alias (symbol TEXT, alias_key TEXT, doc_key TEXT, PRIMARY KEY (symbol, alias_key))""",
    "doc_page": """CREATE TABLE doc_page (
        doc_key TEXT, symbol TEXT, page INTEGER, text TEXT, method TEXT, chars INTEGER, known_at TEXT,
        ocr_conf REAL,
        PRIMARY KEY (doc_key, page))""",
    "share_capital": """CREATE TABLE share_capital (
        symbol TEXT, isin TEXT, as_of_date TEXT, basis TEXT, event TEXT, ratio TEXT,
        shares_outstanding REAL, paid_up_capital REAL, face_value REAL, unit TEXT, scale REAL,
        known_at TEXT, known_at_source TEXT, source_db TEXT, source_table TEXT, source_rowid TEXT,
        isin_effective_from TEXT, isin_effective_to TEXT)""",
    # ``preferred_from`` / ``preferred_to`` (T-090): the window in which this row is THE figure for its
    # (symbol, line_item, fiscal_period, basis).  ``preferred_to`` NULL means current.  The windows of one key tile
    # its timeline, so plain SQL elects the same row pilot3_fin returns at any day (preferred.py writes them).
    "fin_quarter_xbrl": """CREATE TABLE fin_quarter_xbrl (
        symbol TEXT, isin TEXT, period_start TEXT, period_end TEXT, fiscal_period TEXT, basis TEXT,
        audited TEXT, statement TEXT, line_item TEXT, xbrl_tag TEXT, value REAL, unit TEXT, scale REAL,
        source_file TEXT, source_db TEXT, source_table TEXT, source_rowid TEXT,
        known_at TEXT, known_at_source TEXT, is_reported INTEGER,
        preferred_from TEXT, preferred_to TEXT)""",
    "fin_annual_line": """CREATE TABLE fin_annual_line (
        symbol TEXT, isin TEXT, fiscal_year TEXT, period_end TEXT, basis TEXT, statement TEXT,
        line_item TEXT, caption TEXT, value REAL, unit TEXT, scale REAL, doc_key TEXT, page INTEGER,
        quote TEXT, source_db TEXT, source_table TEXT, source_rowid TEXT,
        known_at TEXT, known_at_source TEXT, is_reported INTEGER, is_derived INTEGER,
        definition TEXT, period_type TEXT)""",
    "dividend_event": """CREATE TABLE dividend_event (
        symbol TEXT, isin TEXT, ex_date TEXT, record_date TEXT, fiscal_year TEXT, kind TEXT, amount_per_share REAL,
        face_value REAL, subject TEXT, known_at TEXT, known_at_source TEXT, source_db TEXT, source_table TEXT,
        source_rowid TEXT)""",
    "price_delivery": """CREATE TABLE price_delivery (
        symbol TEXT, isin TEXT, exchange TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL,
        prev_close REAL, volume REAL, value_inr REAL, num_trades REAL, deliverable_qty REAL,
        delivery_pct REAL, adj_factor REAL, adj_close REAL, known_at TEXT, known_at_source TEXT,
        source_db TEXT, source_table TEXT, source_rowid TEXT)""",
    # ``pct_base_shares`` / ``pct_basis`` (T-088): the share count the filing's own percentage is on.  A
    # depository-receipt issuer prints it on the shares outside DR custody, everyone else on the total (the build
    # picks whichever base reproduces the printed percentages and labels it).
    "shp_category": """CREATE TABLE shp_category (
        symbol TEXT, isin TEXT, quarter_end TEXT, category TEXT, category_raw TEXT, shares REAL,
        pct REAL, holders REAL, unit TEXT, source_kind TEXT, source_file TEXT, source_db TEXT,
        source_table TEXT, source_rowid TEXT, revised TEXT, known_at TEXT, known_at_source TEXT,
        is_reported INTEGER, pct_base_shares REAL, pct_basis TEXT)""",
    # one row per named holder per quarter (T-088), from the SHP XBRL detail axes.  ``category`` is the shp_category
    # name of the holder's category; a PAC disclosure is its own ``pac_*`` category (never a MEMBERS name) so a sum
    # over a category can never count the same holder twice: ``pac_name`` is the concert party and ``pac_pct`` the
    # filing's PAC percentage.  ``pledged_shares`` is the holder's own encumbered-under-pledge count when printed.
    "shp_holder": """CREATE TABLE shp_holder (
        symbol TEXT, isin TEXT, quarter_end TEXT, category TEXT, holder_name TEXT, shares REAL, pct REAL,
        holders REAL, pac_name TEXT, pac_pct REAL, pledged_shares REAL, source_file TEXT, source_db TEXT,
        source_table TEXT, known_at TEXT, known_at_source TEXT)""",
    # the promoter encumbrance block of one SHP file per quarter (T-088).  The three flags are the file's own
    # booleans (NULL where the taxonomy of that year does not print the flag).  ``pledged_pct`` is the filing's
    # printed percentage, which the corpus confirms is of the promoter group's own shares (not of all shares).
    "shp_pledge": """CREATE TABLE shp_pledge (
        symbol TEXT, isin TEXT, quarter_end TEXT, pledge_flag INTEGER, ndu_flag INTEGER, other_flag INTEGER,
        promoter_shares REAL, pledged_shares REAL, pledged_pct REAL, other_shares REAL, encumbered_shares REAL,
        source_file TEXT, known_at TEXT, known_at_source TEXT)""",
    "formula": """CREATE TABLE formula (
        formula_id TEXT PRIMARY KEY, metric TEXT, expression TEXT, inputs TEXT, unit TEXT, version INTEGER,
        note TEXT)""",
    "ratio_panel": """CREATE TABLE ratio_panel (
        symbol TEXT, isin TEXT, fiscal_period TEXT, period_type TEXT, period_start TEXT, period_end TEXT,
        basis TEXT, metric TEXT, value REAL, unit TEXT, scale REAL, formula_id TEXT, input_refs TEXT,
        known_at TEXT, known_at_source TEXT, is_derived INTEGER)""",
    "valuation_daily": """CREATE TABLE valuation_daily (
        symbol TEXT, isin TEXT, date TEXT, basis TEXT, close REAL, shares_outstanding REAL,
        market_cap REAL, trailing_eps REAL, trailing_pat REAL, net_worth REAL, net_debt REAL,
        trailing_ebitda REAL, pe REAL, pb REAL, ev_ebitda REAL, dividend_yield_pct REAL,
        known_at TEXT, known_at_source TEXT, input_refs TEXT)""",
    # T-056 loop 2: deals, insider trades and the relative price against an index (stores.py).  A company with
    # none has no rows: "no deals" is the true answer.
    "bulk_block_deal": """CREATE TABLE bulk_block_deal (
        symbol TEXT, isin TEXT, deal_date TEXT, client_name TEXT, deal_type TEXT, buy_sell TEXT, quantity REAL,
        trade_price REAL, exchange TEXT, is_marquee_institution INTEGER,
        known_at TEXT, known_at_source TEXT, source_db TEXT, source_table TEXT, source_rowid TEXT)""",
    "insider_trade": """CREATE TABLE insider_trade (
        symbol TEXT, isin TEXT, source TEXT, source_key TEXT, person_name TEXT, person_category TEXT,
        transaction_type TEXT, mode TEXT, security_type TEXT, qty REAL, value_inr REAL, before_pct REAL,
        after_pct REAL, trade_from TEXT, trade_to TEXT, intimation_date TEXT,
        known_at TEXT, known_at_source TEXT, source_db TEXT, source_table TEXT, source_rowid TEXT)""",
    "index_price": """CREATE TABLE index_price (
        symbol TEXT, isin TEXT, index_name TEXT, date TEXT, index_close REAL, stock_close REAL, stock_adj_close REAL,
        stock_return_1m REAL, stock_return_3m REAL, stock_return_6m REAL, stock_return_12m REAL,
        index_return_1m REAL, index_return_3m REAL, index_return_6m REAL, index_return_12m REAL,
        relative_return_1m REAL, relative_return_3m REAL, relative_return_6m REAL, relative_return_12m REAL,
        known_at TEXT, known_at_source TEXT, source_db TEXT, source_table TEXT, source_rowid TEXT)""",
    # T-057 loop 3: the comparative columns a quarterly results PDF prints (current, preceding, year-ago, ytd,
    # prior ytd, last full year) rebuilt from the page's word boxes.  One row per printed cell; ``value`` is in
    # rupees (``scale`` 1.0) and ``check_status`` says whether XBRL or the table's own arithmetic confirmed it.
    "fin_quarter_printed": """CREATE TABLE fin_quarter_printed (
        symbol TEXT, isin TEXT, period_start TEXT, period_end TEXT, fiscal_period TEXT, period_type TEXT,
        column_role TEXT, basis TEXT, statement TEXT, line_item TEXT, caption TEXT, value REAL, unit TEXT,
        scale REAL, raw_token TEXT, quote TEXT, doc_key TEXT, page INTEGER, known_at TEXT, known_at_source TEXT,
        check_status TEXT, check_detail TEXT, is_reported INTEGER,
        preferred_from TEXT, preferred_to TEXT)""",
    # one row per forward-looking numeric target (guidance.py).  ``doc_key`` is the ticket's ``doc_id``; the
    # column is named ``doc_key`` like every other pilot3 table.
    "guidance": """CREATE TABLE guidance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT, isin TEXT, metric TEXT, target_period TEXT, low REAL, high REAL, unit TEXT,
        direction TEXT, said_on TEXT, doc_key TEXT, page INTEGER, quote TEXT, speaker TEXT,
        known_at TEXT, known_at_source TEXT, revision_of INTEGER, extractor_rule TEXT)""",
}

GUIDANCE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_gd ON guidance(symbol, metric, target_period)",
    "CREATE INDEX IF NOT EXISTS ix_gd2 ON guidance(symbol, said_on)",
)

INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_page_sym ON doc_page(symbol, doc_key)",
    "CREATE INDEX IF NOT EXISTS ix_fq ON fin_quarter_xbrl(symbol, basis, line_item, period_end)",
    "CREATE INDEX IF NOT EXISTS ix_fqp ON fin_quarter_printed(symbol, basis, line_item, period_end)",
    "CREATE INDEX IF NOT EXISTS ix_fa ON fin_annual_line(symbol, basis, line_item, fiscal_year)",
    "CREATE INDEX IF NOT EXISTS ix_px ON price_delivery(symbol, exchange, date)",
    "CREATE INDEX IF NOT EXISTS ix_shp ON shp_category(symbol, quarter_end, category)",
    "CREATE INDEX IF NOT EXISTS ix_shph ON shp_holder(symbol, quarter_end)",
    "CREATE INDEX IF NOT EXISTS ix_shpp ON shp_pledge(symbol, quarter_end)",
    "CREATE INDEX IF NOT EXISTS ix_rp ON ratio_panel(symbol, metric, fiscal_period)",
    "CREATE INDEX IF NOT EXISTS ix_vd ON valuation_daily(symbol, date)",
    "CREATE INDEX IF NOT EXISTS ix_sc ON share_capital(symbol, as_of_date)",
    "CREATE INDEX IF NOT EXISTS ix_div ON dividend_event(symbol, ex_date)",
    "CREATE INDEX IF NOT EXISTS ix_bbd ON bulk_block_deal(symbol, deal_date)",
    "CREATE INDEX IF NOT EXISTS ix_ins ON insider_trade(symbol, intimation_date)",
    "CREATE INDEX IF NOT EXISTS ix_ip ON index_price(symbol, index_name, date)",
    *GUIDANCE_INDEXES,
)

FTS = """CREATE VIRTUAL TABLE doc_page_fts USING fts5(text, content='doc_page', content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2')"""

# T-090: the one figure that is preferred now (``preferred_to`` NULL) for every (symbol, fiscal_period, basis,
# line_item), across BOTH quarter tables, so plain SQL gets the same number ``pilot3_fin`` returns point in time.
FIN_QUARTER_CURRENT = """CREATE VIEW fin_quarter_current AS
    SELECT symbol, isin, period_start, period_end, fiscal_period, basis, statement, line_item, value, unit, scale,
           known_at, known_at_source, is_reported, preferred_from, preferred_to,
           'fin_quarter_xbrl' AS source_table, source_file AS source, NULL AS page, NULL AS column_role,
           NULL AS check_status, xbrl_tag
    FROM fin_quarter_xbrl
    WHERE preferred_from IS NOT NULL AND preferred_to IS NULL
    UNION ALL
    SELECT symbol, isin, period_start, period_end, fiscal_period, basis, statement, line_item, value, unit, scale,
           known_at, known_at_source, is_reported, preferred_from, preferred_to,
           'fin_quarter_printed', doc_key, page, column_role, check_status, NULL
    FROM fin_quarter_printed
    WHERE preferred_from IS NOT NULL AND preferred_to IS NULL"""

PARTS = {
    "registry": ("company", "doc", "doc_alias"),
    "pages": ("doc_page",),
    "stores": ("share_capital", "fin_quarter_xbrl", "fin_annual_line", "dividend_event", "price_delivery", "shp_category",
               "shp_holder", "shp_pledge", "bulk_block_deal", "insider_trade", "index_price"),
    "ratios": ("formula", "ratio_panel", "valuation_daily"),
}


def create(conn: sqlite3.Connection, names) -> None:
    for name in names:
        if name == "doc_page":
            conn.execute("DROP TABLE IF EXISTS doc_page_fts")
        conn.execute(f'DROP TABLE IF EXISTS "{name}"')
        conn.execute(TABLES[name])
    _indexes(conn)
    ensure_views(conn)
    conn.commit()


def ensure(conn: sqlite3.Connection, names) -> None:
    """``CREATE TABLE IF NOT EXISTS`` + indexes, never dropping: a part that rewrites one company's rows only
    (``comparatives``) must not delete another company's rows (``create`` drops every company -- HANDOFF 4 Nov)."""
    for name in names:
        conn.execute(TABLES[name].replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1))
    _indexes(conn)
    ensure_views(conn)
    conn.commit()


def ensure_views(conn: sqlite3.Connection) -> None:
    """Recreate ``fin_quarter_current`` when both quarter tables carry the preferred columns (T-090); an older build
    gains them when the ``preferred`` part runs, and until then the view is left alone rather than failing."""
    tables = ("fin_quarter_xbrl", "fin_quarter_printed")
    for table in tables:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
            return
        if not {"preferred_from", "preferred_to"} <= {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}:
            return
    conn.execute("DROP VIEW IF EXISTS fin_quarter_current")
    conn.execute(FIN_QUARTER_CURRENT)


def _indexes(conn: sqlite3.Connection) -> None:
    for sql in INDEXES:
        table = sql.split(" ON ")[1].split("(")[0]
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
            conn.execute(sql)
