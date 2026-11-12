"""DDL for the pilot3 core tables (T-049 part A).  Every fact row carries symbol, isin, period, basis,
value, unit, scale, ``known_at`` (from the filing record) and its source (doc + page, or source db +
table + rowid).  ``create(conn, tables)`` drops and recreates the named tables, so a part re-runs cleanly.

Schema version (T-202): every pilot3 store carries ``schema_meta.schema_version``.  ``MIGRATIONS`` is the ordered
list of additive changes since a store without the table (version 0), and ``migrate`` is the ONE function that
changes an existing store's schema: build parts call it before they write (``build.py`` once per run).  A
read-only lookup never migrates; it reads ``version`` and falls back to the older rule instead (lookups_pilot3).
CLI: ``python -m reality_engine.pilot3.schema --db <store> --status|--migrate``."""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from collections.abc import Callable

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
    # ``count_basis`` (T-192): how the count was got -- ``filed_exact`` (a filed shareholding pattern's own total)
    # or ``derived_from_capital`` (paid-up capital / face value, rounded, so never preferred over an exact filing).
    # ``ratio`` stays what it always was: the split/bonus ratio of an event row.
    "share_capital": """CREATE TABLE share_capital (
        symbol TEXT, isin TEXT, as_of_date TEXT, basis TEXT, event TEXT, ratio TEXT,
        shares_outstanding REAL, paid_up_capital REAL, face_value REAL, unit TEXT, scale REAL,
        known_at TEXT, known_at_source TEXT, source_db TEXT, source_table TEXT, source_rowid TEXT,
        isin_effective_from TEXT, isin_effective_to TEXT, count_basis TEXT)""",
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
    # T-194: one row per event an announcement names (regulatory inspection, buyback, dividend, acquisition,
    # merger), built by ``pilot3.events`` from the announcement title and its first pages.  ``event_date`` is the
    # event's own start date when the text prints one, else the filing date; ``announced`` is always the filing.
    # T-197: ``body_excerpt`` holds the sentences of the page that state the outcome, observations, classification,
    # impact or amount, and ``doc_type`` / ``title`` name the document the event came from.
    "event": """CREATE TABLE event (
        symbol TEXT, isin TEXT, kind TEXT, event_date TEXT, end_date TEXT, announced TEXT, unit TEXT,
        outcome TEXT, subject TEXT, doc_key TEXT, page INTEGER, quote TEXT, known_at TEXT,
        known_at_source TEXT, source TEXT, extractor_rule TEXT, doc_type TEXT, title TEXT, body_excerpt TEXT)""",
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
    # column is named ``doc_key`` like every other pilot3 table.  ``entity`` (T-192) is the subsidiary, associate,
    # joint venture or acquired company a target belongs to when the sentence or the question it answers names one:
    # such a row is never the group's guidance, and the guidance lookup serves only rows whose entity is empty.
    # ``entity_unsure`` marks a row whose text named a candidate entity the store cannot prove is a subsidiary: the
    # row stays the group's (never hidden) and says it was unsure.
    "guidance": """CREATE TABLE guidance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT, isin TEXT, metric TEXT, target_period TEXT, low REAL, high REAL, unit TEXT,
        direction TEXT, said_on TEXT, doc_key TEXT, page INTEGER, quote TEXT, speaker TEXT,
        known_at TEXT, known_at_source TEXT, revision_of INTEGER, extractor_rule TEXT,
        entity TEXT NOT NULL DEFAULT '', entity_unsure INTEGER NOT NULL DEFAULT 0)""",
    # T-093: one identity verdict per document (doc_identity.py).  A failure sets the document aside; nothing is deleted.
    "doc_identity": """CREATE TABLE doc_identity (
        doc_key TEXT, corporate_doc_id INTEGER, symbol TEXT, isin TEXT, doc_type TEXT, file_where TEXT, verdict TEXT,
        company TEXT, company_reason TEXT, fiscal_year TEXT, fiscal_year_reason TEXT, type TEXT, type_reason TEXT,
        date TEXT, date_reason TEXT, filing_date TEXT, linked_url TEXT, duplicate_of INTEGER, text_chars INTEGER,
        checked_at TEXT)""",
    # T-091: the annual-report note tables read by notes.py.  One row per agency/instrument/rating
    # (rating_event), per bucket or geography/product and year column (concentration), and per counterparty and
    # year column (related_party_txn); ``basis`` says which reporting statement the page belongs to.
    "rating_event": """CREATE TABLE rating_event (
        symbol TEXT, isin TEXT, fiscal_year TEXT, entity TEXT, basis TEXT, agency TEXT, instrument TEXT,
        rating TEXT, outlook TEXT, action TEXT, effective_date TEXT, trigger_text TEXT,
        doc_key TEXT, page INTEGER, quote TEXT, known_at TEXT, known_at_source TEXT, extractor_rule TEXT)""",
    "concentration": """CREATE TABLE concentration (
        symbol TEXT, isin TEXT, fiscal_year TEXT, entity TEXT, basis TEXT, dimension TEXT, bucket TEXT,
        measure TEXT, pct REAL, value REAL, unit TEXT, scale REAL, period_end TEXT,
        doc_key TEXT, page INTEGER, quote TEXT, known_at TEXT, known_at_source TEXT, extractor_rule TEXT)""",
    "related_party_txn": """CREATE TABLE related_party_txn (
        symbol TEXT, isin TEXT, fiscal_year TEXT, entity TEXT, basis TEXT, counterparty TEXT, relationship TEXT,
        txn_type TEXT, amount REAL, balance REAL, unit TEXT, scale REAL, period_end TEXT,
        doc_key TEXT, page INTEGER, quote TEXT, known_at TEXT, known_at_source TEXT, extractor_rule TEXT)""",
}

GUIDANCE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_gd ON guidance(symbol, metric, target_period)",
    "CREATE INDEX IF NOT EXISTS ix_gd2 ON guidance(symbol, said_on)",
)

NOTES_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_re ON rating_event(symbol, agency, fiscal_year)",
    "CREATE INDEX IF NOT EXISTS ix_conc ON concentration(symbol, dimension, fiscal_year)",
    "CREATE INDEX IF NOT EXISTS ix_rpt ON related_party_txn(symbol, counterparty, fiscal_year)",
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
    "CREATE INDEX IF NOT EXISTS ix_ev ON event(symbol, kind, event_date)",
    "CREATE INDEX IF NOT EXISTS ix_bbd ON bulk_block_deal(symbol, deal_date)",
    "CREATE INDEX IF NOT EXISTS ix_ins ON insider_trade(symbol, intimation_date)",
    "CREATE INDEX IF NOT EXISTS ix_ip ON index_price(symbol, index_name, date)",
    *GUIDANCE_INDEXES,
    *NOTES_INDEXES,
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


ROW_CHECK_SCHEMA = """
CREATE TABLE IF NOT EXISTS row_check (tbl TEXT, row_id INTEGER, symbol TEXT, metric TEXT, canon TEXT, sector TEXT,
    doc_type TEXT, rule TEXT, status TEXT, corroborated INTEGER, checker TEXT, definition TEXT,
    PRIMARY KEY (tbl, row_id));
CREATE TABLE IF NOT EXISTS row_check_fail (tbl TEXT, row_id INTEGER, check_name TEXT, hard INTEGER, why TEXT);
"""


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
    gains them when the ``preferred`` migration runs, and until then the view is left alone rather than failing."""
    tables = ("fin_quarter_xbrl", "fin_quarter_printed")
    for table in tables:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
            return
        if not {"preferred_from", "preferred_to"} <= _columns(conn, table):
            return
    conn.execute("DROP VIEW IF EXISTS fin_quarter_current")
    conn.execute(FIN_QUARTER_CURRENT)


# --- T-202: the schema version and its numbered migrations -----------------------------------------------
# One row per numbered, ADDITIVE change: (version, name, fn(conn)).  A migration only creates a table / index
# (IF NOT EXISTS) or adds a column that is absent; it never drops, rewrites or reorders a row, so any older store
# migrates in place and running one twice is a no-op.  To add a change, append the next number here (never edit or
# renumber a released one), give it the ticket that needs it, make it idempotent, and extend
# reality_engine/tests/test_pilot3_schema_version.py.
V_SHARE_COUNT_BASIS = 1        # T-192: share_capital.count_basis
V_GUIDANCE_ENTITY = 2          # T-192: guidance.entity / entity_unsure
V_EVENT_TABLE = 3              # T-194: the event table
V_PREFERRED_WINDOWS = 4        # T-090: preferred_from / preferred_to + fin_quarter_current
V_TRANSCRIPT_TURNS = 5         # T-164: transcript tables, entities / answer_turn, analyst_question views
V_KPI_CONFIDENCE = 6           # T-049 E: kpi_series confidence / conf_rank / method / ocr_conf / source_type / entity
V_ROW_CHECK_DEFINITION = 7     # T-113: row_check.definition
V_INDEXES_AND_VIEWS = 8        # every index and view on the tables a store holds
V_EVENT_BODY = 9               # T-197: event.doc_type / title / body_excerpt

# additive columns for tables built before them (a migration adds, never drops)
SHARE_CAPITAL_ADDITIONS = (
    "ALTER TABLE share_capital ADD COLUMN count_basis TEXT",
)
GUIDANCE_ADDITIONS = (
    "ALTER TABLE guidance ADD COLUMN entity TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE guidance ADD COLUMN entity_unsure INTEGER NOT NULL DEFAULT 0",
)
# T-197: an event row names its document and carries the body sentences that answer the event question.
EVENT_ADDITIONS = (
    "ALTER TABLE event ADD COLUMN doc_type TEXT",
    "ALTER TABLE event ADD COLUMN title TEXT",
    "ALTER TABLE event ADD COLUMN body_excerpt TEXT",
)
PREFERRED_ADDITIONS = (
    "ALTER TABLE {table} ADD COLUMN preferred_from TEXT",
    "ALTER TABLE {table} ADD COLUMN preferred_to TEXT",
)
ROW_CHECK_ADDITIONS = (
    "ALTER TABLE row_check ADD COLUMN definition TEXT",
)
TRANSCRIPT_STATEMENT_ADDITIONS = (
    "ALTER TABLE transcript_statement ADD COLUMN entities TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE transcript_statement ADD COLUMN answer_turn INTEGER NOT NULL DEFAULT 0",
)
TRANSCRIPT_QUESTION_ADDITIONS = (
    "ALTER TABLE transcript_question ADD COLUMN entities TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE transcript_question ADD COLUMN answer_turn INTEGER NOT NULL DEFAULT 0",
)
TRANSCRIPT_VIEW_COLUMNS = {"symbol", "call_date", "analyst", "firm", "question", "topics", "entities",
                           "call_period", "doc_key", "answer_turn"}


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone())


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _script(conn: sqlite3.Connection, script: str) -> None:
    """Run a DDL script statement by statement: ``executescript`` commits a pending transaction first, which would
    break ``migrate``'s one transaction, and these scripts hold no semicolon inside a literal."""
    for statement in script.split(";"):
        if statement.strip():
            conn.execute(statement)


def ensure_columns(conn: sqlite3.Connection, table: str, additions) -> None:
    """Add the given columns to ``table`` when it exists without them (additive, never dropped).

    A thin helper for the migrations below only: a build part moves a store forward with ``migrate``, never with a
    column call of its own (T-202)."""
    if not _has_table(conn, table):
        return
    have = _columns(conn, table)
    for sql in additions:
        column = sql.split(" ADD COLUMN ")[1].split()[0]
        if column not in have:
            conn.execute(sql)


def _create(conn: sqlite3.Connection, names) -> None:
    for name in names:
        conn.execute(TABLES[name].replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1))


def _add_share_count_basis(conn: sqlite3.Connection) -> None:
    ensure_columns(conn, "share_capital", SHARE_CAPITAL_ADDITIONS)


def _add_guidance_entity(conn: sqlite3.Connection) -> None:
    _create(conn, ("guidance",))                      # a build that never ran the guidance part still gains the table
    ensure_columns(conn, "guidance", GUIDANCE_ADDITIONS)
    for sql in GUIDANCE_INDEXES:
        conn.execute(sql)


def _add_event_table(conn: sqlite3.Connection) -> None:
    _create(conn, ("event",))
    conn.execute("CREATE INDEX IF NOT EXISTS ix_ev ON event(symbol, kind, event_date)")


def _add_event_columns(conn: sqlite3.Connection) -> None:
    ensure_columns(conn, "event", EVENT_ADDITIONS)     # a store at v3..v8 has the table, not its T-197 columns


def _add_preferred_windows(conn: sqlite3.Connection) -> None:
    for table in ("fin_quarter_xbrl", "fin_quarter_printed"):
        ensure_columns(conn, table, tuple(sql.format(table=table) for sql in PREFERRED_ADDITIONS))
    ensure_views(conn)


def _add_transcript_turns(conn: sqlite3.Connection) -> None:
    from reality_engine.pilot3 import transcripts      # late: transcripts imports kpi, never this module

    if not _has_table(conn, "transcript_statement"):
        _script(conn, transcripts.SCHEMA)              # a build that never ran the extractor still gains the tables
    else:                                              # older store: add the T-164 columns BEFORE the index naming them
        ensure_columns(conn, "transcript_statement", TRANSCRIPT_STATEMENT_ADDITIONS)
        ensure_columns(conn, "transcript_question", TRANSCRIPT_QUESTION_ADDITIONS)
        if {"symbol", "call_date"} <= _columns(conn, "transcript_statement"):
            conn.execute("CREATE INDEX IF NOT EXISTS ix_ts_sym_call ON transcript_statement(symbol, call_date)")
        if {"symbol", "doc_key", "answer_turn"} <= _columns(conn, "transcript_statement"):
            conn.execute("CREATE INDEX IF NOT EXISTS ix_ts_turn ON transcript_statement(symbol, doc_key, answer_turn)")
    ensure_transcript_views(conn)


def _add_kpi_confidence(conn: sqlite3.Connection) -> None:
    from reality_engine.pilot3 import kpi              # late: kpi is heavy and is not needed to read a version

    if not _has_table(conn, "kpi_series"):
        _script(conn, kpi.SCHEMA)                      # a build that never ran a KPI part still gains the table
        return
    ensure_columns(conn, "kpi_series",
                   tuple(f"ALTER TABLE kpi_series ADD COLUMN {name} {ddl}" for name, ddl in kpi.NEW_COLS))
    if {"symbol", "metric", "fiscal_period"} <= _columns(conn, "kpi_series"):    # a partial store keeps its shape
        conn.execute("CREATE INDEX IF NOT EXISTS ix_kpi_sym_metric ON kpi_series(symbol, metric, fiscal_period)")


def _add_row_check_definition(conn: sqlite3.Connection) -> None:
    _script(conn, ROW_CHECK_SCHEMA)                    # the verdict tables build --part checks copies in (T-113)
    ensure_columns(conn, "row_check", ROW_CHECK_ADDITIONS)


def _add_indexes_and_views(conn: sqlite3.Connection) -> None:
    _indexes(conn)
    ensure_views(conn)
    ensure_transcript_views(conn)


MIGRATIONS: tuple[tuple[int, str, Callable[[sqlite3.Connection], None]], ...] = (
    (V_SHARE_COUNT_BASIS, "share_capital.count_basis (T-192)", _add_share_count_basis),
    (V_GUIDANCE_ENTITY, "guidance.entity / entity_unsure (T-192)", _add_guidance_entity),
    (V_EVENT_TABLE, "event table (T-194)", _add_event_table),
    (V_PREFERRED_WINDOWS, "fin_quarter preferred windows + fin_quarter_current (T-090)", _add_preferred_windows),
    (V_TRANSCRIPT_TURNS, "transcript tables, entities / answer_turn, analyst_question views (T-164)",
     _add_transcript_turns),
    (V_KPI_CONFIDENCE, "kpi_series confidence columns (T-049 E)", _add_kpi_confidence),
    (V_ROW_CHECK_DEFINITION, "row_check.definition (T-113)", _add_row_check_definition),
    (V_INDEXES_AND_VIEWS, "every index and view on the tables a store holds", _add_indexes_and_views),
    (V_EVENT_BODY, "event.doc_type / title / body_excerpt (T-197)", _add_event_columns),
)
LATEST = MIGRATIONS[-1][0]


def version(conn: sqlite3.Connection) -> int:
    """The store's schema version; a store without ``schema_meta`` is version 0 (every build before T-202)."""
    try:
        row = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
    except sqlite3.OperationalError:
        return 0
    try:
        return int(row[0]) if row else 0
    except (TypeError, ValueError):
        return 0


def pending(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    """``[(version, name)]`` of the migrations this store has not had yet."""
    current = version(conn)
    return [(number, name) for number, name, _fn in MIGRATIONS if number > current]


def migrate(conn: sqlite3.Connection) -> tuple[int, int]:
    """Apply the missing migrations in order and record the version: ``(from_version, to_version)``.

    Additive and idempotent: a store already at ``LATEST`` is a no-op (one SELECT), and running it twice changes
    nothing.  A newer store (built by later code) is left alone, never downgraded."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)")
    from_version = version(conn)
    todo = [(number, name, fn) for number, name, fn in MIGRATIONS if number > from_version]
    if not todo:
        return from_version, from_version
    started = not conn.in_transaction
    if started:
        conn.execute("BEGIN")
    try:
        for _number, _name, fn in todo:
            fn(conn)
        to_version = todo[-1][0]
        conn.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)", (str(to_version),))
        conn.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('migrated_at', ?)",
                     (time.strftime("%Y-%m-%dT%H:%M:%S"),))
    except Exception:
        if started:
            conn.rollback()
        raise
    if started:
        conn.commit()
    return from_version, to_version


def ensure_transcript_views(conn: sqlite3.Connection) -> None:
    if not _has_table(conn, "transcript_question") or not TRANSCRIPT_VIEW_COLUMNS <= _columns(conn, "transcript_question"):
        return
    conn.execute("DROP VIEW IF EXISTS analyst_question")
    conn.execute("CREATE VIEW analyst_question AS SELECT symbol, call_date, analyst, firm, question, "
                 "topics, entities, call_period, doc_key, answer_turn FROM transcript_question")
    conn.execute("DROP VIEW IF EXISTS analyst_questions")
    conn.execute("CREATE VIEW analyst_questions AS SELECT * FROM analyst_question")
    conn.commit()


def _indexes(conn: sqlite3.Connection) -> None:
    for sql in INDEXES:
        table = sql.split(" ON ")[1].split("(")[0]
        if not _has_table(conn, table):
            continue
        wanted = {part.strip().split()[0] for part in sql.split("(", 1)[1].split(")")[0].split(",")}
        if wanted <= _columns(conn, table):            # a partial old table keeps its shape; the index waits
            conn.execute(sql)


def main(argv: list[str] | None = None) -> int:
    """``--status`` prints the store's version and pending migrations; ``--migrate`` applies them.  A copy only:
    the CLI writes the file it is given (the live stores are migrated by the build, never from here)."""
    ap = argparse.ArgumentParser(prog="python -m reality_engine.pilot3.schema", description=__doc__)
    ap.add_argument("--db", required=True, help="the pilot3 store (a copy, until the build migrates the live one)")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true", help="print the schema version and pending migrations")
    group.add_argument("--migrate", action="store_true", help="apply the pending migrations")
    args = ap.parse_args(argv)
    conn = sqlite3.connect(args.db)
    try:
        from_version = version(conn)
        todo = pending(conn)
        if args.migrate:
            from_version, to_version = migrate(conn)
            todo = pending(conn)
        else:
            to_version = from_version
        out = {"db": args.db, "version": to_version, "latest": LATEST, "from_version": from_version,
               "pending": [{"version": number, "name": name} for number, name in todo]}
        print(json.dumps(out, indent=1))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
