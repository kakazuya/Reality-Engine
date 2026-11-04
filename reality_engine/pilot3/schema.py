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
    "fin_quarter_xbrl": """CREATE TABLE fin_quarter_xbrl (
        symbol TEXT, isin TEXT, period_start TEXT, period_end TEXT, fiscal_period TEXT, basis TEXT,
        audited TEXT, statement TEXT, line_item TEXT, xbrl_tag TEXT, value REAL, unit TEXT, scale REAL,
        source_file TEXT, source_db TEXT, source_table TEXT, source_rowid TEXT,
        known_at TEXT, known_at_source TEXT, is_reported INTEGER)""",
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
    "shp_category": """CREATE TABLE shp_category (
        symbol TEXT, isin TEXT, quarter_end TEXT, category TEXT, category_raw TEXT, shares REAL,
        pct REAL, holders REAL, unit TEXT, source_kind TEXT, source_file TEXT, source_db TEXT,
        source_table TEXT, source_rowid TEXT, revised TEXT, known_at TEXT, known_at_source TEXT,
        is_reported INTEGER)""",
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
    "CREATE INDEX IF NOT EXISTS ix_fa ON fin_annual_line(symbol, basis, line_item, fiscal_year)",
    "CREATE INDEX IF NOT EXISTS ix_px ON price_delivery(symbol, exchange, date)",
    "CREATE INDEX IF NOT EXISTS ix_shp ON shp_category(symbol, quarter_end, category)",
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

PARTS = {
    "registry": ("company", "doc", "doc_alias"),
    "pages": ("doc_page",),
    "stores": ("share_capital", "fin_quarter_xbrl", "fin_annual_line", "dividend_event", "price_delivery", "shp_category",
               "bulk_block_deal", "insider_trade", "index_price"),
    "ratios": ("formula", "ratio_panel", "valuation_daily"),
}


def create(conn: sqlite3.Connection, names) -> None:
    for name in names:
        if name == "doc_page":
            conn.execute("DROP TABLE IF EXISTS doc_page_fts")
        conn.execute(f'DROP TABLE IF EXISTS "{name}"')
        conn.execute(TABLES[name])
    for sql in INDEXES:
        table = sql.split(" ON ")[1].split("(")[0]
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
            conn.execute(sql)
    conn.commit()
