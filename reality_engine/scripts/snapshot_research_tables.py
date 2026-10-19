"""Research tables for the nightly DuckDB analysis snapshot (PIPELINE_TODO Q2, 2026-10-19).

build_truth_snapshot.py builds the price layer (identity, adjusted / total-return prices); this module adds every other
store to the same file, read-only from SQLite:

  reference   security_master, symbol_isin_history
  results     results_filings (+ trading_isin from filings_isin), results_facts (long), results_key (current quarter
              pivot of common concepts; consolidated and standalone kept apart)
  AR          ar_docs, ar_facts
  decks       deck_sources, deck_pages, deck_facts (facts + isin / known_at of their page), deck_chart_trends
  concalls    cc_docs (no raw JSON), cc_items, cc_item_checks
  telegram    tg_orders, tg_order_schedule, tg_pead_signals, tg_company_mentions
  events      bse_ann (market-wide BSE announcements), corporate_actions
  ownership   nse_insider, nse_sast, nse_pit_filings, bse_insider, nse_deals, bse_deals, nse_short
  flows       fii_dii_cash, nsdl_fpi_daily
  policy      policy_events, pib_releases (metadata only)

Point in time: every table with a time it became public gets
  known_at_src        the original string, unchanged
  known_at_utc        TIMESTAMP in UTC
  known_at_precision  'second' / 'minute' / 'day' / 'unknown'
Source conventions (checked 2026-10-19): exchange / PIB / AR / deck / concall / results times are naive IST;
tg_orders.known_at and tg_*.post_ts_utc are UTC. A date-only value is taken as known at the END of that day IST
(23:59:59 IST = 18:29:59 UTC), so it can never leak into the same day's trading. NSDL FPI daily is published the next
business day: its known_at is date + 1 day end (an upper bound, conservative).

pit_report: per table, rows, source rows just before / after the copy (count_ok: snapshot within them), rows with
a source time, and rows whose source time did not parse (must be 0).
"""
import time
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
ROOT = DATA.parents[1]
SOURCES = {
    "ei": DATA / "equity_intelligence.db",
    "rx": DATA / "results_xbrl.db",
    "ar": DATA / "ar_facts.db",
    "dk": DATA / "deck_figures.db",
    "cc": DATA / "concall_facts.db",
    "an": ROOT / "analysis" / "bse_announcements.db",
}
# Concepts pivoted into results_key (raw XBRL names; the metric ontology is Phase C).
KEY_CONCEPTS = ["RevenueFromOperations", "Income", "OtherIncome", "Expenses", "CostOfMaterialsConsumed",
                "EmployeeBenefitExpense", "FinanceCosts", "DepreciationDepletionAndAmortisationExpense",
                "ProfitBeforeExceptionalItemsAndTax", "ExceptionalItemsBeforeTax", "ProfitBeforeTax", "TaxExpense",
                "ProfitLossForPeriod", "ProfitOrLossAttributableToOwnersOfParent",
                "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                "PaidUpValueOfEquityShareCapital", "FaceValueOfEquityShareCapital",
                "InterestEarned", "InterestExpended", "OperatingProfitBeforeProvisionAndContingencies",
                "ProvisionsOtherThanTaxAndContingencies", "GrossNonPerformingAssets", "NetNonPerformingAssets",
                "PercentageOfGrossNpa", "PercentageOfNpa"]

ANN_COLS = ["NEWSID", "SCRIP_CD", "ATTACHMENTNAME", "NEWSSUB", "HEADLINE", "CATEGORYNAME", "SUBCATNAME", "NEWS_DT",
            "DT_TM", "News_submission_dt", "DissemDT", "QUARTER_ID", "Fld_Attachsize", "ANNOUNCEMENT_TYPE", "symbol"]

MACROS = [
    # naive IST string -> UTC; date-only -> end of that day IST
    """CREATE OR REPLACE MACRO ist_utc(s) AS CASE
         WHEN s IS NULL OR trim(CAST(s AS VARCHAR)) = '' THEN NULL
         WHEN length(trim(CAST(s AS VARCHAR))) <= 10 THEN CAST(try_cast(trim(CAST(s AS VARCHAR)) AS DATE) AS TIMESTAMP)
              + INTERVAL '18 hours 29 minutes 59 seconds'
         ELSE try_cast(replace(substr(trim(CAST(s AS VARCHAR)), 1, 23), 'T', ' ') AS TIMESTAMP) - INTERVAL 330 MINUTE END""",
    # UTC string (naive or +00:00) -> UTC
    """CREATE OR REPLACE MACRO utc_utc(s) AS CASE
         WHEN s IS NULL OR trim(CAST(s AS VARCHAR)) = '' THEN NULL
         ELSE try_cast(replace(substr(trim(CAST(s AS VARCHAR)), 1, 19), 'T', ' ') AS TIMESTAMP) END""",
    """CREATE OR REPLACE MACRO pit_prec(s) AS CASE
         WHEN s IS NULL OR trim(CAST(s AS VARCHAR)) = '' THEN 'unknown'
         WHEN length(trim(CAST(s AS VARCHAR))) <= 10 THEN 'day'
         WHEN length(trim(CAST(s AS VARCHAR))) <= 16 THEN 'minute' ELSE 'second' END""",
]


def pit(expr, tz="ist"):
    f = "ist_utc" if tz == "ist" else "utc_utc"
    return (f"CAST({expr} AS VARCHAR) AS known_at_src, {f}({expr}) AS known_at_utc, "
            f"pit_prec({expr}) AS known_at_precision")


# (table, select-from SQL, sort key or None). Sorted tables make per-company / per-time scans skip row groups.
def table_specs():
    key_cols = ", ".join(f"max(CASE WHEN x.concept = '{c}' THEN x.value END) AS \"{c}\"" for c in KEY_CONCEPTS)
    key_in = ", ".join(f"'{c}'" for c in KEY_CONCEPTS)
    return [
        ("security_master", "SELECT * FROM ei.security_master", None),
        ("symbol_isin_history", "SELECT * FROM ei.symbol_isin_history", None),
        ("results_filings",
         f"SELECT f.*, i.isin AS trading_isin, i.method AS trading_isin_method, i.same_issuer, "
         f"{pit('coalesce(f.dissem_ts, f.broadcast_ts, f.filing_ts)')} "
         "FROM rx.filings f LEFT JOIN rx.filings_isin i ON i.file = f.file", "trading_isin, period_end"),
        # XBRL contexts: OneD = the quarter, FourD = year to date, OneI / FourI = balance at period end, PY_I = prior
        # year end. facts.period_start / period_end are blank before 2022 and, for FourD, wrongly carry the quarter's
        # dates (parse_nse_results_xbrl, seen 2026-10-19: TITAGARH Dec-2024 FourD revenue = 9 months under Oct-Dec),
        # so the context decides the period, never the stored dates.
        ("results_facts",
         "SELECT *, CASE context WHEN 'OneD' THEN 'quarter' WHEN 'FourD' THEN 'year_to_date' WHEN 'OneI' THEN "
         "'instant' WHEN 'FourI' THEN 'instant' WHEN 'PY_I' THEN 'prior_year_instant' ELSE 'other' END AS period_kind "
         "FROM rx.facts", "file, concept"),
        ("results_key",
         f"SELECT f.file, i.isin AS trading_isin, f.symbol, f.taxonomy, f.consolidated, f.audited, f.period_start, "
         f"f.period_end, f.fy_start, {pit('coalesce(f.dissem_ts, f.broadcast_ts, f.filing_ts)')}, {key_cols}, "
         "max(CASE WHEN y.concept = 'RevenueFromOperations' THEN y.value END) AS ytd_RevenueFromOperations, "
         "max(CASE WHEN y.concept = 'ProfitLossForPeriod' THEN y.value END) AS ytd_ProfitLossForPeriod "
         "FROM rx.filings f LEFT JOIN rx.filings_isin i ON i.file = f.file "
         f"LEFT JOIN rx.facts x ON x.file = f.file AND x.context IN ('OneD', 'OneI') AND x.concept IN ({key_in}) "
         "LEFT JOIN rx.facts y ON y.file = f.file AND y.context = 'FourD' "
         "AND y.concept IN ('RevenueFromOperations', 'ProfitLossForPeriod') "
         "GROUP BY ALL", "trading_isin, period_end"),
        ("ar_docs", f"SELECT * EXCLUDE (path), {pit('filed_at')} FROM ar.ar_docs", None),
        ("ar_facts", f"SELECT *, {pit('filed_at')} FROM ar.ar_facts", "isin, fiscal_year"),
        ("deck_sources", f"SELECT * EXCLUDE (local_path), {pit('known_at')} FROM dk.deck_sources", "isin"),
        ("deck_pages", f"SELECT sha256, CAST(page_no AS INTEGER) AS page_no, prompt_version, doc_id, isin, symbol, doc_type, route, CAST(n_facts AS INTEGER) AS n_facts, status, "
                       f"{pit('known_at')} FROM dk.pages", "isin, sha256, page_no"),
        ("deck_facts",
         f"SELECT p.isin, p.symbol, p.doc_type, f.*, {pit('p.known_at')} FROM dk.facts f "
         "LEFT JOIN dk.pages p ON p.sha256 = f.sha256 AND p.page_no = f.page_no AND p.prompt_version = f.prompt_version",
         "isin, known_at_utc"),
        ("deck_chart_trends", f"SELECT *, {pit('known_at')} FROM dk.chart_trends", "isin"),
        ("cc_docs", f"SELECT * EXCLUDE (raw_json, checks_json), {pit('filed_at')} FROM cc.cc_docs", None),
        ("cc_items", f"SELECT * EXCLUDE (item_json), {pit('filed_at')} FROM cc.cc_items", "isin, filed_at"),
        ("cc_item_checks", "SELECT * FROM cc.cc_item_checks", None),
        ("tg_orders", f"SELECT *, {pit('known_at', 'utc')} FROM ei.tg_orders", None),
        ("tg_order_schedule", "SELECT * FROM ei.tg_order_schedule", None),
        ("tg_pead_signals", f"SELECT *, {pit('post_ts_utc', 'utc')} FROM ei.tg_pead_signals", None),
        ("tg_company_mentions", f"SELECT *, {pit('post_ts_utc', 'utc')} FROM ei.tg_company_mentions", None),
        # ann columns have no declared type in SQLite (DuckDB would read BLOB): cast each to text
        ("bse_ann", "SELECT " + ", ".join(f"CAST({c} AS VARCHAR) AS {c}" for c in ANN_COLS)
         + f", {pit('CAST(DissemDT AS VARCHAR)')} FROM an.ann", "SCRIP_CD, DissemDT"),
        ("corporate_actions", f"SELECT *, {pit('broadcast_date')} FROM ei.corporate_actions", None),
        ("board_meetings", f"SELECT *, {pit('intimated_at')} FROM ei.board_meetings", "isin, meeting_date"),
        ("index_tri", "SELECT * FROM ei.index_tri", "index_name, date"),
        ("tax_rules", "SELECT * FROM ei.tax_rules", None),
        ("etf_px", "SELECT * FROM ei.etf_px", "isin, date"),
        ("fund_nav", f"SELECT *, {pit('date')} FROM ei.fund_nav", "isin, date"),
        ("company_industry", "SELECT * FROM ei.company_industry", None),
        ("shp_index", f"SELECT *, {pit('broadcast_at')} FROM ei.shp_index", "isin, quarter_end"),
        ("nse_insider", f"SELECT *, {pit('disseminated_at')} FROM ei.mkt_nse_insider", "symbol"),
        ("nse_sast", f"SELECT * EXCLUDE (raw_json), {pit('disseminated_at')} FROM ei.mkt_nse_sast", None),
        ("nse_pit_filings", f"SELECT *, {pit('disseminated_at')} FROM ei.mkt_nse_pit_filings", None),
        ("nse_pit_xbrl_facts", "SELECT * FROM ei.mkt_nse_pit_xbrl_facts", "xml_file"),   # insider after May 2026
        ("bse_insider", "SELECT *, NULL::VARCHAR AS known_at_src, NULL::TIMESTAMP AS known_at_utc, "
                        "'unknown' AS known_at_precision FROM ei.mkt_bse_insider", None),
        ("nse_deals", f"SELECT *, {pit('date')} FROM ei.mkt_nse_deals", "date"),
        ("bse_deals", f"SELECT *, {pit('date')} FROM ei.mkt_bse_deals", "date"),
        ("nse_short", f"SELECT *, {pit('date')} FROM ei.mkt_nse_short", "date"),
        ("fii_dii_cash", f"SELECT *, {pit('date')} FROM ei.mkt_fii_dii_cash", "date"),
        ("nsdl_fpi_daily",
         "SELECT *, CAST(date AS VARCHAR) AS known_at_src, ist_utc(date) + INTERVAL 1 DAY AS known_at_utc, "
         "'day' AS known_at_precision FROM ei.mkt_nsdl_fpi_daily", "date"),
        ("policy_events", f"SELECT *, {pit('published_at')} FROM ei.policy_events", "published_at"),
        ("pib_releases", f"SELECT * EXCLUDE (body), {pit('coalesce(posted_at, release_date)')} FROM ei.pib_releases",
         "release_date"),
    ]


# Snapshot table -> SQLite source for the 1:1 copies (count check); results_key has one row per filing.
DIRECT = {"security_master": "ei.security_master", "symbol_isin_history": "ei.symbol_isin_history",
          "results_filings": "rx.filings", "results_facts": "rx.facts", "results_key": "rx.filings", "ar_docs": "ar.ar_docs",
          "ar_facts": "ar.ar_facts", "deck_sources": "dk.deck_sources", "deck_pages": "dk.pages",
          "deck_facts": "dk.facts", "deck_chart_trends": "dk.chart_trends", "cc_docs": "cc.cc_docs",
          "cc_items": "cc.cc_items", "cc_item_checks": "cc.cc_item_checks", "tg_orders": "ei.tg_orders",
          "tg_order_schedule": "ei.tg_order_schedule", "tg_pead_signals": "ei.tg_pead_signals",
          "tg_company_mentions": "ei.tg_company_mentions", "bse_ann": "an.ann",
          "corporate_actions": "ei.corporate_actions",
          "board_meetings": "ei.board_meetings", "index_tri": "ei.index_tri", "tax_rules": "ei.tax_rules",
          "etf_px": "ei.etf_px", "fund_nav": "ei.fund_nav", "company_industry": "ei.company_industry",
          "shp_index": "ei.shp_index", "nse_insider": "ei.mkt_nse_insider",
          "nse_sast": "ei.mkt_nse_sast", "nse_pit_filings": "ei.mkt_nse_pit_filings",
          "nse_pit_xbrl_facts": "ei.mkt_nse_pit_xbrl_facts",
          "bse_insider": "ei.mkt_bse_insider", "nse_deals": "ei.mkt_nse_deals", "bse_deals": "ei.mkt_bse_deals",
          "nse_short": "ei.mkt_nse_short", "fii_dii_cash": "ei.mkt_fii_dii_cash",
          "nsdl_fpi_daily": "ei.mkt_nsdl_fpi_daily", "policy_events": "ei.policy_events",
          "pib_releases": "ei.pib_releases"}


def add_ar_item_index(con, log=print):
    """fact_id on ar_facts + DuckDB FTS over ar_facts.item, its term table sorted by termid.

    A market-wide ILIKE over 32M items takes ~3 s; reading the term table directly takes well under 1 s:
        SELECT f.* FROM ar_facts f SEMI JOIN (
            SELECT t.docid FROM fts_main_ar_facts.terms t JOIN fts_main_ar_facts.dict d USING (termid)
            WHERE d.term IN ('order', 'book') GROUP BY t.docid HAVING count(DISTINCT d.term) = 2) m
        ON m.docid = f.fact_id
    (terms are lower-case, no stemming, no stop words; match_bm25 also works but scores every row.)"""
    t0 = time.time()
    con.execute("INSTALL fts; LOAD fts;")
    con.execute("CREATE OR REPLACE TABLE ar_facts AS SELECT row_number() OVER () AS fact_id, * FROM ar_facts")
    con.execute("PRAGMA create_fts_index('ar_facts', 'fact_id', 'item', stemmer='none', stopwords='none', "
                "lower=1, overwrite=1)")
    con.execute("CREATE OR REPLACE TABLE fts_main_ar_facts.terms AS SELECT * FROM fts_main_ar_facts.terms ORDER BY termid")
    log(f"  ar_facts item index: {time.time() - t0:.0f}s")


def add_research_tables(con, log=print, only=None):
    con.execute("INSTALL sqlite; LOAD sqlite;")
    for alias, path in SOURCES.items():
        if alias in [r[0] for r in con.execute("SELECT database_name FROM duckdb_databases()").fetchall()]:
            continue
        con.execute(f"ATTACH '{path.as_posix()}' AS {alias} (TYPE sqlite, READ_ONLY)")
    for m in MACROS:
        con.execute(m)
    report = []
    for name, sql, order in table_specs():
        if only and name not in only:
            continue
        t0 = time.time()
        src = DIRECT.get(name)
        before = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0] if src else None
        q = f"CREATE OR REPLACE TABLE {name} AS {sql}" + (f" ORDER BY {order}" if order else "")
        try:
            con.execute("SET sqlite_all_varchar = false")
            con.execute(q)
            mode = "typed"
        except Exception as e:   # noqa: BLE001 - SQLite columns with mixed types: copy as text, report it
            log(f"  {name}: typed copy failed ({str(e)[:120]}); copying as text")
            con.execute("SET sqlite_all_varchar = true")
            con.execute(q)
            con.execute("SET sqlite_all_varchar = false")
            mode = "varchar"
        n = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        after = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0] if src else None
        count_ok = None if src is None else before <= n <= after
        cols = [r[0] for r in con.execute(f"DESCRIBE {name}").fetchall()]
        if "known_at_utc" in cols:
            with_src, bad, lo, hi = con.execute(
                f"SELECT count(known_at_src), count(*) FILTER (WHERE known_at_src IS NOT NULL AND trim(known_at_src) <> '' "
                f"AND known_at_utc IS NULL), min(known_at_utc), max(known_at_utc) FROM {name}").fetchone()
        else:
            with_src, bad, lo, hi = None, None, None, None
        report.append((name, n, before, after, count_ok, mode, with_src, bad, str(lo) if lo else None, str(hi) if hi else None,
                       round(time.time() - t0, 1)))
        log(f"  {name}: {n:,} rows (source {before}..{after} ok={count_ok}; {mode}, {time.time() - t0:.0f}s) pit src {with_src} unparsed {bad} {lo} .. {hi}")
    if not only or "ar_facts" in only:
        add_ar_item_index(con, log)
    con.execute("CREATE OR REPLACE TABLE pit_report (table_name VARCHAR, n_rows BIGINT, src_rows_before BIGINT, "
                "src_rows_after BIGINT, count_ok BOOLEAN, copy_mode VARCHAR, "
                "n_with_time BIGINT, n_time_unparsed BIGINT, min_known_at_utc VARCHAR, max_known_at_utc VARCHAR, "
                "seconds DOUBLE)")
    con.executemany("INSERT INTO pit_report VALUES (?,?,?,?,?,?,?,?,?,?,?)", report)
    return report
