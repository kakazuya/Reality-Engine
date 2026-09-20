"""
Database Engine Module
Manages SQLite connection lifecycle, PRAGMA optimization, WAL mode, and schema migrations.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Dict, Optional, Generator
from contextlib import contextmanager

from reality_engine.config import DB_PATH, SQLITE_PRAGMAS

logger = logging.getLogger("reality_engine.database")


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
            try:
                conn.executescript(schema_sql)
            except sqlite3.OperationalError as e:
                # Production DB may predate the latest schema.sql additions
                # (e.g. regulatory_political_risks.coverage_status). The fresh
                # temp DB path always succeeds, but a stale production file
                # would fail on CREATE INDEX referencing a missing column.
                # Repair in-place and continue; do not crash import or tests.
                msg = str(e)
                if "coverage_status" in msg:
                    try:
                        cols = {r[1] for r in conn.execute("PRAGMA table_info(regulatory_political_risks)").fetchall()}
                        if cols and "coverage_status" not in cols:
                            conn.execute(
                                "ALTER TABLE regulatory_political_risks ADD COLUMN coverage_status TEXT CHECK (coverage_status IN ('mapped','no_template','unknown')) DEFAULT 'mapped'"
                            )
                        # Create the covering indexes that previously failed
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
                    # Retry the remaining schema (IF NOT EXISTS makes it idempotent)
                    try:
                        conn.executescript(schema_sql)
                    except Exception:
                        pass
                else:
                    raise
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
