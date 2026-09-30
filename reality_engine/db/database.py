"""
Database Engine Module
Manages SQLite connection lifecycle, PRAGMA optimization, WAL mode, and schema migrations.
"""

import hashlib
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, Optional, Generator
from contextlib import contextmanager

from reality_engine.config import DB_PATH, SQLITE_PRAGMAS

logger = logging.getLogger("reality_engine.database")


# Single read contract for "when did the market know about this document". Precedence:
# BSE exchange dissemination timestamp (IST, second resolution) > date parsed from the
# filing body > NULL. Never falls back to doc_date/event_date (crawl stamps on legacy rows).
_V_DOCUMENT_PIT_SQL = """
CREATE VIEW v_document_pit AS
SELECT id, isin, symbol, doc_type, title, source_url,
       COALESCE(bse_dissem_ts, publication_date) AS pit_ts,
       substr(COALESCE(bse_dissem_ts, publication_date), 1, 10) AS pit_date,
       CASE WHEN bse_dissem_ts IS NOT NULL THEN 'bse_feed'
            WHEN publication_date IS NOT NULL THEN COALESCE(pit_source, 'body_publication_date')
            ELSE 'unknown' END AS pit_basis,
       call_date, fiscal_period_end, doc_date AS crawl_doc_date
FROM corporate_documents
"""


class DatabaseManager:
    """Manages high-performance SQLite connections with WAL mode and memory PRAGMAs."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Create an optimized SQLite connection with configured PRAGMAs."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row

        # busy_timeout MUST be in force before any lock-taking statement
        # (journal_mode switch, DDL): SQLite can return SQLITE_BUSY for those
        # without invoking the busy handler at all when another connection holds
        # a snapshot, in which case the timeout in the PRAGMA list below would
        # never apply and a concurrent writer would fail instantly.
        _busy = next((p for p in SQLITE_PRAGMAS if p.strip().lower().startswith("pragma busy_timeout")), None)
        if _busy:
            conn.execute(_busy)

        # Apply performance PRAGMAs
        with conn:
            for pragma in SQLITE_PRAGMAS:
                conn.execute(pragma)
                
        return conn

    @contextmanager
    def session(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager providing an auto-committing or rolling back SQLite connection."""
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        """Initializes tables, indices, and views from schema.sql."""
        schema_file = Path(__file__).parent / "schema.sql"
        if not schema_file.exists():
            raise FileNotFoundError(f"Schema file not found at {schema_file}")

        with open(schema_file, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        with self.session() as conn:
            # Schema DDL needs exclusive access; with other writers active SQLite
            # may refuse without waiting, so retry with backoff rather than
            # failing the whole process (this killed a scheduled run mid-ingest).
            # Fast path: schema DDL needs an exclusive lock, so running the whole
            # idempotent script on every process start costs ~60s of contention
            # while ingest writers are active (measured). Skip it when the schema
            # file is unchanged AND every required table still exists — the
            # existence check is what keeps this correct for callers that drop
            # tables (e.g. rebuilding the FTS index) while sharing the DB.
            _required = (
                "master_companies", "raw_documents", "document_chunks", "intelligence_fts",
                "moat_evaluations", "business_model_profiles", "company_distilled_parameters",
                "daily_price_delivery", "regulatory_political_risks",
            )
            _skip_schema = False
            if not os.environ.get("REALITY_ENGINE_FORCE_SCHEMA"):
                try:
                    _digest = hashlib.sha256(schema_sql.encode("utf-8")).hexdigest()
                    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)")
                    _row = conn.execute("SELECT value FROM schema_meta WHERE key='schema_sha256'").fetchone()
                    _present = {r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
                    _skip_schema = bool(_row) and _row[0] == _digest and all(t in _present for t in _required)
                except Exception:
                    _skip_schema = False

            last_exc = None
            for _attempt in range(5 if not _skip_schema else 0):
                try:
                    conn.executescript(schema_sql)
                    last_exc = None
                    break
                except sqlite3.OperationalError as exc:
                    last_exc = exc
                    if "locked" in str(exc).lower() and _attempt < 4:
                        time.sleep(1.5 * (_attempt + 1))
                        continue
                    break
            if last_exc is not None:
                # Production DB may predate the latest schema.sql additions
                # (e.g. regulatory_political_risks.coverage_status,
                # document_chunks.fiscal_* + idx_chunks_fiscal). The fresh
                # temp DB path always succeeds, but a stale production file
                # would fail on CREATE INDEX referencing a missing column
                # (CREATE TABLE IF NOT EXISTS is a no-op on the old table).
                # Repair in-place and continue; do not crash import or tests.
                msg = str(last_exc)
                if "fiscal_period" in msg or "fiscal_confidence" in msg or "fiscal_source" in msg:
                    try:
                        _dcols = {r[1] for r in conn.execute("PRAGMA table_info(document_chunks)").fetchall()}
                        if _dcols:
                            for _col, _ddl in (
                                ("fiscal_period", "TEXT"),
                                ("fiscal_confidence", "REAL"),
                                ("fiscal_source", "TEXT"),
                            ):
                                if _col not in _dcols:
                                    conn.execute(f"ALTER TABLE document_chunks ADD COLUMN {_col} {_ddl}")
                            conn.execute(
                                "CREATE INDEX IF NOT EXISTS idx_chunks_fiscal "
                                "ON document_chunks(fiscal_period, fiscal_confidence)"
                            )
                    except Exception:
                        pass
                    try:
                        conn.executescript(schema_sql)
                        last_exc = None
                    except Exception:
                        pass
                if last_exc is not None:
                    if "coverage_status" in str(last_exc):
                        try:
                            cols = {r[1] for r in conn.execute("PRAGMA table_info(regulatory_political_risks)").fetchall()}
                            if cols and "coverage_status" not in cols:
                                conn.execute(
                                    "ALTER TABLE regulatory_political_risks ADD COLUMN coverage_status TEXT CHECK (coverage_status IN ('mapped','no_template','unknown')) DEFAULT 'mapped'"
                                )
                            for stmt in (
                                "CREATE INDEX IF NOT EXISTS idx_regpol_coverage ON regulatory_political_risks(coverage_status)",
                                "CREATE INDEX IF NOT EXISTS idx_regpol_symbol ON regulatory_political_risks(symbol)",
                                "CREATE INDEX IF NOT EXISTS idx_regpol_isin ON regulatory_political_risks(isin)",
                                "CREATE INDEX IF NOT EXISTS idx_regpol_net ON regulatory_political_risks(net_impact_score)",
                            ):
                                try:
                                    conn.execute(stmt)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        try:
                            conn.executescript(schema_sql)
                        except Exception:
                            pass
                    else:
                        raise last_exc
            if not _skip_schema and last_exc is None:
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_sha256', ?)",
                        (hashlib.sha256(schema_sql.encode("utf-8")).hexdigest(),),
                    )
                except Exception:
                    pass
            self._apply_runtime_migrations(conn)

    def _apply_runtime_migrations(self, conn: sqlite3.Connection) -> None:
        """Idempotent ALTER TABLE migrations for pre-existing databases."""
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(telegram_posts)").fetchall()}
            if cols and "button_links_json" not in cols:
                conn.execute("ALTER TABLE telegram_posts ADD COLUMN button_links_json TEXT")
        except Exception as exc:
            # Table may not exist yet (fresh DB handled by schema.sql); ignore.
            pass
        # Provenance columns for the corporate_documents registry (raw official
        # exchange filings discovered via Screener). Idempotent across runs.
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(corporate_documents)").fetchall()}
            for new_col in ("source", "discovery_source"):
                if new_col not in cols:
                    conn.execute(f"ALTER TABLE corporate_documents ADD COLUMN {new_col} TEXT")
            # Point-in-time columns. doc_date/event_date can be crawl stamps; readers that need
            # "when did the market know" must use v_document_pit, never those two.
            for new_col, ddl in (
                ("call_date", "TEXT"), ("publication_date", "TEXT"),
                ("pit_source", "TEXT"), ("pit_tier", "INTEGER"), ("pit_applied_at", "TEXT"),
                ("bse_newsid", "TEXT"), ("bse_dissem_ts", "TEXT"),
                ("bse_news_dt", "TEXT"), ("bse_subcat", "TEXT"), ("bse_joined_at", "TEXT"),
                ("fiscal_period_end", "TEXT"),
            ):
                if new_col not in cols:
                    conn.execute(f"ALTER TABLE corporate_documents ADD COLUMN {new_col} {ddl}")
            conn.execute("DROP VIEW IF EXISTS v_document_pit")
            conn.execute(_V_DOCUMENT_PIT_SQL)
        except Exception:
            # Fresh DB: schema.sql already creates these columns; ignore.
            pass
        # Idempotent UNIQUE index on corporate_documents.source_url so that
        # repository.upsert_corporate_documents ON CONFLICT(source_url) works on
        # pre-existing databases built before the UNIQUE constraint landed in schema.sql.
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_corp_docs_source_url "
                "ON corporate_documents(source_url)"
            )
        except Exception:
            # Pre-existing rows may carry duplicate or NULL source_url; never crash init_db.
            pass
        # Symbol/ISIN-scoped chunk lookup indexes.
        #
        # document_chunks was indexed only by (doc_id, chunk_index), which is the original
        # doc-scoped access pattern. Symbol-scoped reads (pdf_ingestor's industry backfill,
        # tests, and any new consumer) therefore scanned the whole table including the wide
        # embedding/content columns: measured 5,045 ms per symbol lookup and 623 ms per ISIN
        # lookup on the live DB, versus ~0.03 ms with an index.
        #
        # These live here rather than in schema.sql so one code path covers both fresh and
        # pre-existing databases (init_db runs schema.sql and then these migrations).
        for idx_name, col in (("idx_docchunks_symbol", "symbol"), ("idx_docchunks_isin", "isin")):
            try:
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON document_chunks({col})"
                )
            except Exception:
                # Table absent on a minimal bootstrap; never crash init_db.
                pass
        # Fiscal-period labels on document_chunks (findings §11) — ADDITIVE ONLY.
        # Body-genuine labels stamped at insert by pdf_ingestor via
        # processing/document_parser.extract_fiscal_period on the header-stripped
        # body (content after first newline). content/embedding are NEVER
        # rewritten. Canonical DDL: schema.sql section 22. Idempotent: ALTER
        # TABLE ADD COLUMN skips present columns; index is IF NOT EXISTS.
        try:
            _fcols = {r[1] for r in conn.execute("PRAGMA table_info(document_chunks)").fetchall()}
            if _fcols:
                for _col, _ddl in (
                    ("fiscal_period", "TEXT"),
                    ("fiscal_confidence", "REAL"),
                    ("fiscal_source", "TEXT"),
                ):
                    if _col not in _fcols:
                        conn.execute(f"ALTER TABLE document_chunks ADD COLUMN {_col} {_ddl}")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_chunks_fiscal "
                    "ON document_chunks(fiscal_period, fiscal_confidence)"
                )
        except Exception:
            # Table absent on a minimal bootstrap; never crash init_db.
            pass
        # Defensive idempotent creation of corporate_status_flags for very old DB files.
        # Fresh installs already get this table (CREATE TABLE IF NOT EXISTS) from schema.sql.
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS corporate_status_flags ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, isin TEXT, symbol TEXT NOT NULL, "
                "status_type TEXT NOT NULL, source TEXT NOT NULL, detail TEXT, "
                "detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                "UNIQUE(symbol, status_type, source))"
            )
        except Exception:
            pass
        # Provenance columns on financials tables (where each number came from).
        for tbl in ("quarterly_financials", "annual_financials"):
            try:
                tcols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
                if "source" not in tcols:
                    conn.execute(f"ALTER TABLE {tbl} ADD COLUMN source TEXT DEFAULT 'yfinance'")
            except Exception:
                pass

        # Raw document registry (macro PDF audit trail). Ensure table + columns +
        # UNIQUE source_url index so repository.upsert_raw_document dedups cleanly.
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS raw_documents (
                    doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    published_date TEXT NOT NULL,
                    fiscal_period TEXT,
                    source_url TEXT,
                    creator_or_ministry TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    sha256_hash TEXT,
                    local_file_path TEXT,
                    file_size_bytes INTEGER
                )
                """
            )
            rcols = {r[1] for r in conn.execute("PRAGMA table_info(raw_documents)").fetchall()}
            for col, ddl in (
                ("source_url", "TEXT"),
                ("creator_or_ministry", "TEXT"),
                ("sha256_hash", "TEXT"),
                ("local_file_path", "TEXT"),
                ("file_size_bytes", "INTEGER"),
            ):
                if col not in rcols:
                    try:
                        conn.execute(f"ALTER TABLE raw_documents ADD COLUMN {col} {ddl}")
                    except Exception:
                        pass
            # Idempotent UNIQUE constraints (created once; harmless if they exist).
            try:
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_rawdoc_url ON raw_documents(source_url)")
            except Exception:
                pass
            try:
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_rawdoc_hash ON raw_documents(sha256_hash)")
            except Exception:
                pass
        except Exception:
            pass

        # Regulatory policy coverage_status (added in latest schema.sql) — backfill for stale production DBs
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(regulatory_political_risks)").fetchall()}
            if cols and "coverage_status" not in cols:
                conn.execute(
                    "ALTER TABLE regulatory_political_risks ADD COLUMN coverage_status TEXT CHECK (coverage_status IN ('mapped','no_template','unknown')) DEFAULT 'mapped'"
                )
            # Ensure indexes exist even if the initial executescript failed partway
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_regpol_coverage ON regulatory_political_risks(coverage_status)")
            except Exception:
                pass
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_regpol_symbol ON regulatory_political_risks(symbol)")
            except Exception:
                pass
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_regpol_isin ON regulatory_political_risks(isin)")
            except Exception:
                pass
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_regpol_net ON regulatory_political_risks(net_impact_score)")
            except Exception:
                pass
        except Exception:
            pass

        # Decay config: ensure table + seed macro/policy categories with computed lambda.
        try:
            import math

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pruning_decay_config (
                    category TEXT PRIMARY KEY,
                    half_life_months REAL NOT NULL,
                    lambda REAL,
                    significance_floor REAL DEFAULT 5.0,
                    prob_cutoff REAL DEFAULT 0.08
                )
                """
            )
            _decay_seed = [
                ("State Budget", 12),
                ("PIB Circular", 3),
                ("RBI Report / Economic Survey", 6),
                ("Economic Survey", 12),
                ("Union Budget / Tax Reform", 12),
                ("Analyst Commentary / YouTube", 3),
                ("Quarterly Concall / MPC Stance", 6),
            ]
            for cat, hl in _decay_seed:
                conn.execute(
                    "INSERT OR IGNORE INTO pruning_decay_config (category, half_life_months) VALUES (?, ?)",
                    (cat, hl),
                )
                lam = math.log(2) / hl
                conn.execute(
                    "UPDATE pruning_decay_config SET lambda=? WHERE category=? AND (lambda IS NULL OR abs(lambda-?)>0.0001)",
                    (lam, cat, lam),
                )
        except Exception:
            pass
        # Substrate versioning (P0b peers-speak) — ADDITIVE ONLY (canonical DDL: schema.sql section 21).
        # History tables sit beside the live level tables, which are NEVER altered here.
        # Created here as well as in schema.sql so pre-existing DBs (schema digest skipped)
        # still gain them. Backfill is INSERT OR IGNORE (idempotent): one row per live level
        # row with asof = earliest EOD date (per-row created_at date part for ripples/edges),
        # so delta predictors have a day-one baseline. Best-effort: never crash init.
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS moat_history (
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    asof_date TEXT NOT NULL,
                    moat_score REAL,
                    moat_width TEXT,
                    trajectory TEXT,
                    source TEXT DEFAULT 'backfill',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, asof_date)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_moat_hist_sym_date ON moat_history(symbol, asof_date DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_moat_hist_date ON moat_history(asof_date DESC)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS policy_eni_history (
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    policy_name TEXT NOT NULL,
                    asof_date TEXT NOT NULL,
                    net_impact_score REAL,
                    severity REAL,
                    source TEXT DEFAULT 'backfill',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, policy_name, asof_date)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_policy_hist_sym_date ON policy_eni_history(symbol, asof_date DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_policy_hist_sym_pol_date ON policy_eni_history(symbol, policy_name, asof_date DESC)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ripple_history (
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    edge_key TEXT NOT NULL,
                    symbol TEXT,
                    event_id TEXT,
                    source_node_id TEXT,
                    target_node_id TEXT,
                    asof_date TEXT NOT NULL,
                    significance REAL,
                    beta REAL,
                    revision_count INTEGER DEFAULT 0,
                    source TEXT DEFAULT 'revision',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(edge_key, asof_date)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ripple_hist_sym_date ON ripple_history(symbol, asof_date DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ripple_hist_edge_date ON ripple_history(edge_key, asof_date DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ripple_hist_event ON ripple_history(event_id)")
        except Exception:
            pass
        try:
            from datetime import date as _date
            try:
                _erow = conn.execute("SELECT MIN(date) AS d FROM daily_price_delivery").fetchone()
                _asof = str(_erow["d"])[:10] if _erow and _erow["d"] else _date.today().isoformat()
            except Exception:
                _asof = _date.today().isoformat()
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO moat_history (symbol, asof_date, moat_score, moat_width, trajectory, source) "
                    "SELECT UPPER(ticker), ?, total_moat_score, moat_width, moat_trajectory, 'backfill' "
                    "FROM moat_evaluations WHERE ticker IS NOT NULL",
                    (_asof,),
                )
            except Exception:
                pass
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO policy_eni_history (symbol, policy_name, asof_date, net_impact_score, severity, source) "
                    "SELECT UPPER(symbol), policy_name, ?, net_impact_score, severity_score, 'backfill' "
                    "FROM regulatory_political_risks WHERE symbol IS NOT NULL AND policy_name IS NOT NULL",
                    (_asof,),
                )
            except Exception:
                pass
            try:
                _rcols = {r[1] for r in conn.execute("PRAGMA table_info('ripple_effects')").fetchall()}
            except Exception:
                _rcols = set()
            if _rcols:
                try:
                    _rrows = conn.execute("SELECT * FROM ripple_effects").fetchall()
                except Exception:
                    _rrows = []
                for _r in _rrows:
                    try:
                        _rd = dict(_r)
                        _cid = _rd.get("target_company_id")
                        _sym = None
                        if _cid is not None:
                            try:
                                _b = conn.execute("SELECT symbol FROM financial_metrics WHERE company_id = ? LIMIT 1", (_cid,)).fetchone()
                                if _b and _b[0]:
                                    _sym = str(_b[0]).strip().upper()
                                else:
                                    _b2 = conn.execute("SELECT ticker FROM moat_evaluations WHERE company_id = ? LIMIT 1", (_cid,)).fetchone()
                                    if _b2 and _b2[0]:
                                        _sym = str(_b2[0]).strip().upper()
                            except Exception:
                                _sym = None
                        _created = _rd.get("created_at")
                        _ad = str(_created)[:10] if _created else _asof
                        _ekey = "ripple:{}:L{}:C{}:S{}:I{}:{}".format(
                            _rd.get("event_id") if _rd.get("event_id") is not None else "?",
                            _rd.get("order_level") if _rd.get("order_level") is not None else 1,
                            _cid if _cid is not None else "-",
                            _rd.get("target_sector_id") if _rd.get("target_sector_id") is not None else "-",
                            _rd.get("target_industry_id") if _rd.get("target_industry_id") is not None else "-",
                            _rd.get("transmission_channel") or "direct",
                        )
                        conn.execute(
                            "INSERT OR IGNORE INTO ripple_history (edge_key, symbol, event_id, asof_date, significance, beta, revision_count, source) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, 'backfill')",
                            (_ekey, _sym, _rd.get("event_id"), _ad,
                             _rd.get("significance_rank"), _rd.get("transmission_elasticity", 1.0),
                             int(_rd.get("revision_count") or 0)),
                        )
                    except Exception:
                        continue
            try:
                _ecols = {r[1] for r in conn.execute("PRAGMA table_info('graph_causal_edges')").fetchall()}
            except Exception:
                _ecols = set()
            if _ecols and "edge_id" in _ecols:
                try:
                    _erows = conn.execute("SELECT * FROM graph_causal_edges").fetchall()
                except Exception:
                    _erows = []
                for _e in _erows:
                    try:
                        _ed = dict(_e)
                        if not _ed.get("edge_id"):
                            continue
                        _ecreated = _ed.get("created_at")
                        _ead = str(_ecreated)[:10] if _ecreated else _asof
                        conn.execute(
                            "INSERT OR IGNORE INTO ripple_history (edge_key, source_node_id, target_node_id, asof_date, significance, beta, revision_count, source) "
                            "VALUES (?, ?, ?, ?, ?, ?, 0, 'backfill')",
                            (str(_ed.get("edge_id")), _ed.get("source_node_id"), _ed.get("target_node_id"),
                             _ead, _ed.get("elasticity_score"), _ed.get("elasticity_score")),
                        )
                    except Exception:
                        continue
        except Exception:
            pass

    # Tables whose statistics are never worth re-analysing (FTS5 shadow tables, internal).
    _SKIP_ANALYZE_PREFIXES = ("sqlite_", "intelligence_fts", "inbox_fts")
    _ANALYZE_DRIFT_THRESHOLD = 0.25
    _ANALYZE_MIN_ROWS = 1000

    def optimize(self, force: bool = False) -> Dict[str, str]:
        """Refresh SQLite planner statistics for tables whose estimates have drifted.

        ``PRAGMA optimize`` alone is not sufficient here. Measured 2026-09-20 on the
        production DB: ``PRAGMA optimize`` (0.00s) and ``PRAGMA optimize=0x10002`` (2.11s)
        both left ``sqlite_stat1`` reporting 3,474 rows for ``master_companies`` against an
        actual 6,438, and 2,715,255 against 3,121,803 for ``daily_price_delivery`` -- its
        heuristics key off changes made by the *current* connection, not drift already on
        disk. Only a real ``ANALYZE`` refreshed them, at 32.8s for the whole DB, which is
        too expensive to run unconditionally after every ingest.

        So: run the cheap optimisation first (it covers tables that have never been analyzed
        at all), then compare each table's stored row estimate to its actual count and
        ``ANALYZE`` only what has drifted beyond the threshold (or, with ``force``,
        everything that is big enough to matter).

        Returns ``{table: action}`` for observability; empty when nothing needed work.
        """
        actions: Dict[str, str] = {}
        with self.session() as conn:
            try:
                conn.execute("PRAGMA optimize;")
            except Exception:
                pass
            try:
                tables = [
                    r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                ]
                # sqlite_stat1 holds one row per *index*, and the first number in each
                # row's ``stat`` is that index's row count -- which for a non-partial index
                # equals the table's. Prefer an explicit table-level row (idx IS NULL) when
                # present; otherwise take the largest first-token across the table's index
                # rows. Keying only on idx IS NULL silently reported "no stats" for tables
                # whose indexes are all explicitly named (e.g. corporate_documents), so
                # they were re-analyzed on every call and never converged.
                estimates: Dict[str, int] = {}
                for tbl, idx, stat in conn.execute(
                    "SELECT tbl, idx, stat FROM sqlite_stat1"
                ).fetchall():
                    try:
                        first = int(str(stat).split()[0])
                    except (ValueError, IndexError):
                        continue
                    if idx is None or tbl not in estimates:
                        estimates[tbl] = first
                    else:
                        estimates[tbl] = max(estimates[tbl], first)
            except Exception as exc:  # pragma: no cover - never fail an ingest run
                logger.debug("optimize(): table scan failed: %s", exc)
                return actions

            for table in tables:
                if any(table.startswith(p) for p in self._SKIP_ANALYZE_PREFIXES):
                    continue
                try:
                    actual = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                except Exception:
                    continue
                stat = estimates.get(table)
                estimated = stat if stat is not None else None
                if actual < self._ANALYZE_MIN_ROWS and estimated is not None:
                    continue
                if force:
                    needs = actual >= self._ANALYZE_MIN_ROWS
                    action = "analyzed (forced)"
                elif estimated is None:
                    needs = actual >= self._ANALYZE_MIN_ROWS
                    action = "analyzed (no stats)"
                else:
                    drift = abs(estimated - actual) / max(actual, 1)
                    needs = drift > self._ANALYZE_DRIFT_THRESHOLD
                    action = f"analyzed (drift {drift:.0%})"
                if not needs:
                    continue
                try:
                    conn.execute(f'ANALYZE "{table}"')
                    actions[table] = action
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("ANALYZE %s failed: %s", table, exc)
        if actions:
            logger.info("Refreshed planner statistics for %d table(s): %s", len(actions), actions)
        return actions

    def vacuum(self) -> None:
        """Optimizes and re-indexes the SQLite database."""
        with self.session() as conn:
            conn.execute("PRAGMA optimize;")


# Global singleton instance
db_manager = DatabaseManager()
