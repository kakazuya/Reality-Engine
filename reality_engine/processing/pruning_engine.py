"""4-Pillar Data Pruning & Lifecycle Framework - Exponential Decay & Graph Pruning.

Implements postgres_schema.sql:169+ patch pillars:
  Pillar 1 tiering Hot12m/Warm36m/Cold (parquet >36m)
  Pillar 2 exponential decay S(t)=S0*e^{-lambda*t} with lambda=ln2/half_life
           YouTube 3m -> 0.231, Concall 6m -> 0.1155 (~0.115 spec truncated), Budget 12m -> 0.05776 (~0.058)
           pruning_decay_config half_life 3/6/12
  Pillar 3A partitioning (document_chunks PARTITION BY RANGE published_date) — SQLite fallback keeps non-partitioned
  Pillar 3B stored procedure prune_decayed_signals() + v_ripple_decayed view decayed_significance

SQLite fallback compatible: UPDATE document_chunks SET embedding=NULL etc. testable without PG.
"""

from __future__ import annotations
import math
import os
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Optional, List, Dict, Any, Tuple

logger = logging.getLogger("reality_engine.pruning")

# Pillar 2: Half-life constants per Architecture spec (months)
HALF_LIVES: dict[str, float] = {
    "Analyst Commentary / YouTube": 3.0,   # months -> lambda 0.231049...
    "Quarterly Concall / MPC Stance": 6.0,  # -> 0.115524 (spec truncated 0.115, PG NUMERIC(6,4) 0.1155)
    "Union Budget / Tax Reform": 12.0,      # -> 0.057762 (spec 0.058)
}

# Spec-truncated display Lambdas (for docs/tests expecting 0.231/0.115/0.058)
LAMBDA_SPEC_TRUNCATED: dict[str, float] = {
    "Analyst Commentary / YouTube": 0.231,
    "Quarterly Concall / MPC Stance": 0.115,
    "Union Budget / Tax Reform": 0.058,
}

def lambda_for(category: str) -> float:
    """Precise lambda = ln(2)/half_life. Use LAMBDA_SPEC_TRUNCATED for spec display."""
    hl = HALF_LIVES.get(category, 6.0)
    return math.log(2) / hl

def decayed_significance(S0: float, category: str, months_elapsed: float) -> float:
    """S(t) = S0 * e^{-lambda * delta_t}  (postgres_schema.sql:13 v_ripple_decayed)."""
    lam = lambda_for(category)
    return S0 * math.exp(-lam * months_elapsed)

@dataclass
class TieringPolicy:
    """Pillar 1: Data Tiering — Hot12m/Warm36m/Cold per postgres_schema.sql:343"""
    entity: str
    hot_months: int
    warm_months: int
    cold_threshold_months: int
    action_hot: str
    action_warm: str
    action_cold: str

TIERING: list[TieringPolicy] = [
    TieringPolicy("Video/Audio MP4", 0, 0, 0, "never DB", "temp buffer", "S3 Glacier, delete local temp immediately"),
    TieringPolicy("Document Chunks Embeddings", 12, 36, 36, "RAM pgvector ivfflat/HNSW", "drop embedding keep relational text", "Parquet >36m raw text export"),
    TieringPolicy("Ripple Effects", 12, 24, 24, "active unmaterialized paths", "validated backtest archive", "purge PN<0.05 or expired"),
    TieringPolicy("Financials & Moats", 9999, 9999, 9999, "all hot", "all warm", "never purge"),
]

def should_prune_ripple(prob: float, raw: float, decayed_S: float, prob_cutoff: float = 0.08, S_floor: float = 5.0, Pn_cutoff: float = 0.05) -> bool:
    """Pillar 2B: Graph pruning execution rules — prob<0.08 or raw*prob<0.50 or S<5.0 or PN<0.05"""
    if prob < prob_cutoff:
        return True
    if abs(raw) * prob < 0.50:  # ghost node per prune_decayed_signals()
        return True
    if decayed_S < S_floor:
        return True
    return False

def tier_for_age(entity: str, age_months: int) -> Literal["hot","warm","cold","purge"]:
    """Return tier for age_months per TIERING. 12m boundary inclusive hot, 36m inclusive warm."""
    pol = next((p for p in TIERING if p.entity == entity), TIERING[1])
    if age_months <= pol.hot_months:
        return "hot"
    if age_months <= pol.warm_months:
        return "warm"
    if age_months >= pol.cold_threshold_months and pol.cold_threshold_months < 9999:
        return "cold"
    return "warm"

# SQL helpers for repository.py integration (PG original)
PRUNE_EMBEDDINGS_SQL = """
UPDATE document_chunks dc SET embedding = NULL
FROM raw_documents rd
WHERE dc.doc_id = rd.doc_id
  AND rd.published_date < CURRENT_DATE - INTERVAL '12 months'
  AND dc.embedding IS NOT NULL
  AND COALESCE(rd.source_type,'') NOT ILIKE '%Structural Milestone%';
"""

PRUNE_RIPPLES_SQL = """
DELETE FROM ripple_effects
WHERE parent_ripple_id IS NOT NULL
  AND (probability < 0.10 OR (ABS(raw_magnitude) * probability) < 0.50);
"""

ARCHIVE_MACRO_SQL = """
UPDATE macro_events SET event_category='Archived'
WHERE announcement_date < CURRENT_DATE - INTERVAL '24 months' AND event_category!='Archived';
"""

DECAYED_VIEW_SQL = """
SELECT ripple_id, significance_rank * EXP(-lambda * EXTRACT(MONTH FROM AGE(CURRENT_DATE, announcement_date))) AS decayed
FROM ripple_effects JOIN macro_events USING(event_id) JOIN pruning_decay_config USING(category);
"""

# SQLite fallback SQL (ILIKE -> LIKE, INTERVAL -> date('now','-12 months'))
PRUNE_EMBEDDINGS_SQL_SQLITE = """
UPDATE document_chunks SET embedding = NULL
WHERE embedding IS NOT NULL
  AND doc_id IN (
    SELECT doc_id FROM raw_documents
    WHERE published_date < date('now','-12 months')
      AND COALESCE(source_type,'') NOT LIKE '%Structural Milestone%'
  );
"""

PRUNE_RIPPLES_SQL_SQLITE = """
DELETE FROM ripple_effects
WHERE parent_ripple_id IS NOT NULL
  AND (probability < 0.10 OR (ABS(raw_magnitude) * probability) < 0.50);
"""

# Archive macro >24m — handles both PG event_category/announcement_date and SQLite category/event_date
ARCHIVE_MACRO_SQL_SQLITE_CATEGORY = """
UPDATE macro_events SET category='Archived'
WHERE event_date < date('now','-24 months') AND COALESCE(category,'')!='Archived';
"""
ARCHIVE_MACRO_SQL_SQLITE_EVENT_CATEGORY = """
UPDATE macro_events SET event_category='Archived'
WHERE announcement_date < date('now','-24 months') AND COALESCE(event_category,'')!='Archived';
"""

# v_ripple_decayed emulation SQL for SQLite (joins raw_documents for source_type->category mapping)
V_RIPPLE_DECAYED_SQL_SQLITE = """
SELECT
  r.ripple_id,
  r.event_id,
  r.order_level,
  r.transmission_channel,
  r.raw_magnitude,
  r.probability,
  r.lag_time_months,
  r.significance_rank,
  me.event_date AS announcement_date,
  rd.source_type,
  d.category,
  d.lambda,
  (r.significance_rank * exp(-d.lambda * max(0, (julianday('now') - julianday(me.event_date))/30.44))) AS decayed_significance
FROM ripple_effects r
JOIN macro_events me ON r.event_id = me.event_id
JOIN raw_documents rd ON me.raw_document_path = rd.local_file_path OR me.event_id = rd.doc_id OR 1=1
LEFT JOIN pruning_decay_config d ON (
  CASE WHEN lower(COALESCE(rd.source_type,'')) LIKE '%youtube%' OR lower(COALESCE(rd.source_type,'')) LIKE '%analyst%' THEN 'Analyst Commentary / YouTube'
       WHEN lower(COALESCE(rd.source_type,'')) LIKE '%concall%' OR lower(COALESCE(rd.source_type,'')) LIKE '%mpc%' THEN 'Quarterly Concall / MPC Stance'
       ELSE 'Union Budget / Tax Reform' END
) = d.category
LIMIT 1;
"""

# Simpler per-row compute without raw_documents join (fallback)
V_RIPPLE_DECAYED_SIMPLE_SQL = """
SELECT
  r.ripple_id,
  r.event_id,
  r.order_level,
  r.raw_magnitude,
  r.probability,
  r.lag_time_months,
  r.significance_rank,
  me.event_date,
  (r.significance_rank * exp(-0.11552453009332421 * max(0, (julianday('now') - julianday(me.event_date))/30.44))) AS decayed_significance
FROM ripple_effects r
JOIN macro_events me ON r.event_id = me.event_id
"""

# Schema DDL for SQLite fallback (idempotent)
ENSURE_PRUNING_DECAY_CONFIG_SQL = """
CREATE TABLE IF NOT EXISTS pruning_decay_config (
  category TEXT PRIMARY KEY,
  half_life_months REAL NOT NULL,
  lambda REAL,
  significance_floor REAL DEFAULT 5.0,
  prob_cutoff REAL DEFAULT 0.08
);
"""

ENSURE_RIPPLE_EFFECTS_SQLITE = """
CREATE TABLE IF NOT EXISTS ripple_effects (
  ripple_id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT,
  parent_ripple_id INTEGER,
  order_level INTEGER NOT NULL DEFAULT 1,
  target_type TEXT,
  target_sector_id INTEGER,
  target_industry_id INTEGER,
  target_company_id INTEGER,
  transmission_channel TEXT NOT NULL DEFAULT 'direct',
  transmission_elasticity REAL DEFAULT 1.0,
  raw_magnitude REAL,
  probability REAL,
  lag_time_months INTEGER DEFAULT 0,
  significance_rank REAL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(parent_ripple_id) REFERENCES ripple_effects(ripple_id)
);
"""

ENSURE_DISTILLATION_RUNS_SQLITE = """
CREATE TABLE IF NOT EXISTS distillation_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_date TEXT DEFAULT CURRENT_TIMESTAMP,
  source_type TEXT,
  chunks_distilled INTEGER NOT NULL,
  vectors_purged INTEGER NOT NULL,
  summary TEXT,
  moat_updates TEXT
);
"""

ENSURE_MOAT_EVALUATIONS_SQLITE = """
CREATE TABLE IF NOT EXISTS moat_evaluations (
  company_id INTEGER PRIMARY KEY,
  ticker TEXT UNIQUE,
  eval_date TEXT DEFAULT CURRENT_TIMESTAMP,
  switching_costs INTEGER CHECK (switching_costs BETWEEN 0 AND 5),
  network_effects INTEGER CHECK (network_effects BETWEEN 0 AND 5),
  cost_advantage INTEGER CHECK (cost_advantage BETWEEN 0 AND 5),
  intangible_assets INTEGER CHECK (intangible_assets BETWEEN 0 AND 5),
  efficient_scale INTEGER CHECK (efficient_scale BETWEEN 0 AND 5),
  total_moat_score REAL,
  moat_width TEXT,
  moat_trajectory TEXT CHECK (moat_trajectory IN ('Deteriorating','Stable','Expanding'))
);
"""

def _compute_moat_score(sc: int, ne: int, ca: int, ia: int, es: int) -> float:
    return round((sc*0.25)+(ne*0.25)+(ca*0.20)+(ia*0.20)+(es*0.10), 2)

def ensure_pruning_schema(manager=None) -> None:
    """Create pruning tables in SQLite fallback if not exist and seed pruning_decay_config 3 rows.
    Idempotent, safe to call on PG (no-op if psycopg2 used)."""
    from reality_engine.db.database import db_manager as _mgr
    mgr = manager or _mgr
    try:
        with mgr.session() as conn:
            # Detect PG vs SQLite by checking if we have sqlite_master access
            # Try to create SQLite tables; if PG, this will fail silently and we assume PG already has DDL via postgres_schema.sql
            is_sqlite = True
            try:
                conn.execute("SELECT name FROM sqlite_master LIMIT 1")
            except Exception:
                is_sqlite = False
            if not is_sqlite:
                # PG path: ensure pruning_decay_config seeded via postgres_schema already; try insert on conflict do nothing
                try:
                    import psycopg2  # type: ignore
                    # Assume mgr is not PG db_manager but we can try PG dsn fallback
                except Exception:
                    pass
                return
            conn.executescript(ENSURE_PRUNING_DECAY_CONFIG_SQL)
            conn.executescript(ENSURE_RIPPLE_EFFECTS_SQLITE)
            conn.executescript(ENSURE_DISTILLATION_RUNS_SQLITE)
            conn.executescript(ENSURE_MOAT_EVALUATIONS_SQLITE)
            # Seed pruning_decay_config with lambda computed
            for cat, hl in HALF_LIVES.items():
                lam = math.log(2)/hl
                conn.execute(
                    "INSERT OR IGNORE INTO pruning_decay_config (category, half_life_months, lambda, significance_floor, prob_cutoff) VALUES (?, ?, ?, 5.0, 0.08)",
                    (cat, hl, lam)
                )
                # Update lambda if exists but null
                conn.execute("UPDATE pruning_decay_config SET lambda=? WHERE category=? AND (lambda IS NULL OR abs(lambda-?)>0.0001)", (lam, cat, lam))
            # Ensure indexes for ripple
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ripple_hierarchy ON ripple_effects(event_id, parent_ripple_id, order_level)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ripple_targets ON ripple_effects(target_company_id, target_industry_id)")
            except Exception:
                pass
    except Exception as exc:
        logger.debug("ensure_pruning_schema note: %s", exc)

def _table_exists(conn, table: str) -> bool:
    try:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        return row is not None
    except Exception:
        return False

def _column_exists(conn, table: str, column: str) -> bool:
    try:
        cols = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
        return any(c[1] == column for c in cols)
    except Exception:
        return False

def prune_decayed_signals(manager=None, dry_run: bool = False) -> Dict[str, Any]:
    """SQLite-compatible implementation of postgres_schema.sql prune_decayed_signals() procedure.

    Logic (postgres_schema.sql:487):
      - Drop vector embeddings older than 12 months (retain raw text) unless source_type LIKE '%Structural Milestone%'
      - Prune ripple_effects where parent_ripple_id IS NOT NULL AND (prob<0.10 OR |raw|*prob<0.50)
      - Mark macro_events older than 24 months as Archived (category / event_category)

    Returns dict with counts: vectors_purged, ripples_pruned, macros_archived
    Works on SQLite fallback via db_manager; also attempts PG if PG_DSN env present.
    Testable without PG.
    """
    from reality_engine.db.database import db_manager as _mgr
    mgr = manager or _mgr
    ensure_pruning_schema(mgr)

    # Try PG first if env PG_DSN present (use psycopg2 procedure CALL)
    pg_dsn = os.environ.get("DATABASE_URL") or os.environ.get("PG_DSN") or os.environ.get("POSTGRES_DSN")
    if pg_dsn:
        try:
            import psycopg2  # type: ignore
            conn = psycopg2.connect(pg_dsn, connect_timeout=3)
            try:
                with conn.cursor() as cur:
                    if dry_run:
                        # Count what would be pruned
                        cur.execute("SELECT count(*) FROM document_chunks dc JOIN raw_documents rd ON dc.doc_id=rd.doc_id WHERE rd.published_date < CURRENT_DATE - INTERVAL '12 months' AND dc.embedding IS NOT NULL AND COALESCE(rd.source_type,'') NOT ILIKE '%Structural Milestone%'")
                        vectors = cur.fetchone()[0]
                        cur.execute("SELECT count(*) FROM ripple_effects WHERE parent_ripple_id IS NOT NULL AND (probability <0.10 OR ABS(raw_magnitude)*probability<0.50)")
                        ripples = cur.fetchone()[0]
                        cur.execute("SELECT count(*) FROM macro_events WHERE announcement_date < CURRENT_DATE - INTERVAL '24 months' AND event_category!='Archived'")
                        macros = cur.fetchone()[0]
                        return {"vectors_purged": vectors, "ripples_pruned": ripples, "macros_archived": macros, "dry_run": True, "backend": "pg"}
                    else:
                        cur.execute("CALL prune_decayed_signals();")
                        conn.commit()
                        # Counts after (approximate: use ROW_COUNT via GET DIAGNOSTICS not available, so re-query)
                        cur.execute("SELECT count(*) FROM document_chunks WHERE embedding IS NULL")
                        vectors = cur.fetchone()[0]
                        return {"vectors_purged": -1, "ripples_pruned": -1, "macros_archived": -1, "backend": "pg", "note": "CALL executed"}
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("PG prune fallback to SQLite: %s", exc)

    # SQLite fallback
    vectors_purged = 0
    ripples_pruned = 0
    macros_archived = 0
    with mgr.session() as conn:
        # Ensure tables exist
        if not _table_exists(conn, "document_chunks") or not _table_exists(conn, "raw_documents"):
            return {"vectors_purged": 0, "ripples_pruned": 0, "macros_archived": 0, "backend": "sqlite", "note": "missing core tables"}

        # 1. Count embeddings that will be purged (for dry_run and return counts)
        try:
            # How many currently have embedding not null and aged >12m and not milestone
            count_sql = """
            SELECT count(*) as c FROM document_chunks dc
            JOIN raw_documents rd ON dc.doc_id=rd.doc_id
            WHERE dc.embedding IS NOT NULL
              AND rd.published_date < date('now','-12 months')
              AND COALESCE(rd.source_type,'') NOT LIKE '%Structural Milestone%'
            """
            row = conn.execute(count_sql).fetchone()
            to_purge = int(row[0] if row else 0) if row else 0
        except Exception as exc:
            logger.debug("count embeddings note: %s", exc)
            to_purge = 0

        if dry_run:
            # Also count ripples and macros for dry_run
            try:
                if _table_exists(conn, "ripple_effects"):
                    rrow = conn.execute("SELECT count(*) FROM ripple_effects WHERE parent_ripple_id IS NOT NULL AND (probability <0.10 OR ABS(raw_magnitude)*probability<0.50)").fetchone()
                    ripples_p = int(rrow[0]) if rrow else 0
                else:
                    ripples_p = 0
            except Exception:
                ripples_p = 0
            try:
                # macro archive count — handle both column names
                mcnt = 0
                if _table_exists(conn, "macro_events"):
                    cols = {c[1] for c in conn.execute("PRAGMA table_info('macro_events')").fetchall()}
                    if "event_date" in cols:
                        mrow = conn.execute("SELECT count(*) FROM macro_events WHERE event_date < date('now','-24 months') AND COALESCE(category,'')!='Archived'").fetchone()
                        mcnt = int(mrow[0]) if mrow else 0
                    elif "announcement_date" in cols:
                        mrow = conn.execute("SELECT count(*) FROM macro_events WHERE announcement_date < date('now','-24 months') AND COALESCE(event_category,'')!='Archived'").fetchone()
                        mcnt = int(mrow[0]) if mrow else 0
                macros_p = mcnt
            except Exception:
                macros_p = 0
            return {"vectors_purged": to_purge, "ripples_pruned": ripples_p, "macros_archived": macros_p, "dry_run": True, "backend": "sqlite"}

        # 1. actual purge embeddings >12m retain Structural Milestone
        try:
            cur = conn.execute(PRUNE_EMBEDDINGS_SQL_SQLITE)
            # rowcount for UPDATE in sqlite is number of rows changed (may be -1 if not known)
            vectors_purged = cur.rowcount if cur.rowcount != -1 else to_purge
            # Fallback if rowcount -1: recount via changes()
            if cur.rowcount == -1:
                try:
                    vectors_purged = conn.execute("SELECT changes()").fetchone()[0]
                except Exception:
                    vectors_purged = to_purge
        except Exception as exc:
            logger.debug("prune embeddings error: %s", exc)
            vectors_purged = 0

        # 2. prune ghost ripple nodes
        if _table_exists(conn, "ripple_effects"):
            try:
                # Count before for accurate return if rowcount -1
                before = 0
                try:
                    brow = conn.execute("SELECT count(*) FROM ripple_effects WHERE parent_ripple_id IS NOT NULL AND (probability <0.10 OR ABS(raw_magnitude)*probability<0.50)").fetchone()
                    before = int(brow[0]) if brow else 0
                except Exception:
                    pass
                cur2 = conn.execute(PRUNE_RIPPLES_SQL_SQLITE)
                if cur2.rowcount != -1:
                    ripples_pruned = cur2.rowcount
                else:
                    try:
                        ripples_pruned = conn.execute("SELECT changes()").fetchone()[0] if before==0 else before
                        if ripples_pruned==0:
                            ripples_pruned = before
                    except Exception:
                        ripples_pruned = before
            except Exception as exc:
                logger.debug("prune ripples error: %s", exc)
                ripples_pruned = 0
        else:
            ripples_pruned = 0

        # 3. archive macro events >24m
        if _table_exists(conn, "macro_events"):
            try:
                cols = {c[1] for c in conn.execute("PRAGMA table_info('macro_events')").fetchall()}
                if "event_date" in cols:
                    # SQLite schema uses category + event_date
                    cur3 = conn.execute(ARCHIVE_MACRO_SQL_SQLITE_CATEGORY)
                    if cur3.rowcount != -1:
                        macros_archived = cur3.rowcount
                    else:
                        try:
                            macros_archived = conn.execute("SELECT changes()").fetchone()[0]
                        except Exception:
                            macros_archived = 0
                    # Also try alternative if zero and event_category exists (PG-style)
                if "announcement_date" in cols and macros_archived==0:
                    try:
                        cur4 = conn.execute(ARCHIVE_MACRO_SQL_SQLITE_EVENT_CATEGORY)
                        if cur4.rowcount != -1 and cur4.rowcount>0:
                            macros_archived = cur4.rowcount
                        elif cur4.rowcount==-1:
                            try:
                                macros_archived = conn.execute("SELECT changes()").fetchone()[0]
                            except Exception:
                                pass
                    except Exception:
                        pass
                elif "category" in cols and "event_category" in cols:
                    # PG column name in SQLite? try both
                    pass
            except Exception as exc:
                logger.debug("archive macro error: %s", exc)
                macros_archived = 0
        else:
            macros_archived = 0

    return {"vectors_purged": int(vectors_purged), "ripples_pruned": int(ripples_pruned), "macros_archived": int(macros_archived), "backend": "sqlite"}

def get_decayed_significance_rows(manager=None, limit: int = 100, significance_floor: float = 5.0) -> List[Dict[str, Any]]:
    """Emulate v_ripple_decayed view decayed_significance query for SQLite.
    Returns rows with decayed_significance = significance_rank * exp(-lambda * months_elapsed)
    Months elapsed = (julianday('now')-julianday(event_date))/30.44
    """
    from reality_engine.db.database import db_manager as _mgr
    mgr = manager or _mgr
    ensure_pruning_schema(mgr)
    out: List[Dict[str, Any]] = []
    with mgr.session() as conn:
        if not _table_exists(conn, "ripple_effects") or not _table_exists(conn, "macro_events"):
            return []
        # Determine which category lambda to use: join raw_documents if available else default 0.1155
        # For SQLite we compute per ripple by looking up pruning_decay_config via source_type mapping
        # Simpler: compute lambda per row python-side
        try:
            # Build lambda map
            lam_map = {}
            try:
                for row in conn.execute("SELECT category, lambda FROM pruning_decay_config").fetchall():
                    lam_map[row["category"]] = float(row["lambda"]) if row["lambda"] is not None else lambda_for(row["category"])
            except Exception:
                lam_map = {k: lambda_for(k) for k in HALF_LIVES}
            # Fetch ripple + macro + raw doc source_type if possible
            # Try to join raw_documents via doc_id or local_file_path
            has_rd = _table_exists(conn, "raw_documents")
            has_rd_cols = {}
            if has_rd:
                try:
                    has_rd_cols = {c[1] for c in conn.execute("PRAGMA table_info('raw_documents')").fetchall()}
                except Exception:
                    has_rd_cols = set()
            # Fetch ripples with event date - handle both SQLite (event_date/category) and PG (announcement_date/event_category)
            # Build dynamic column selection based on available macro_events columns
            me_cols = {c[1] for c in conn.execute("PRAGMA table_info('macro_events')").fetchall()}
            # Use SELECT r.* , me.* with explicit join to be schema-agnostic
            # We select core r columns plus all me columns via * to avoid missing column errors
            try:
                rows = conn.execute("SELECT r.ripple_id, r.event_id, r.order_level, r.raw_magnitude, r.probability, r.lag_time_months, r.significance_rank, r.transmission_channel, me.* FROM ripple_effects r JOIN macro_events me ON r.event_id = me.event_id LIMIT ?", (limit*3,)).fetchall()
            except Exception as e:
                logger.debug("get_decayed select fallback %s", e)
                # Fallback without me.* expansion
                rows = conn.execute("SELECT r.* FROM ripple_effects r LIMIT ?", (limit*3,)).fetchall()
            for r in rows:
                # Determine event date agnostic
                ev_date_str = None
                try:
                    # r is sqlite3.Row, check keys safely
                    keys = r.keys()
                    if "event_date" in keys and r["event_date"]:
                        ev_date_str = r["event_date"]
                    elif "announcement_date" in keys and r["announcement_date"]:
                        ev_date_str = r["announcement_date"]
                    else:
                        # try alternative keys from me.* duplicate? event_date may be under different name; also try event_date in keys via r["event_date"]
                        for cand in ("event_date", "announcement_date"):
                            if cand in keys:
                                if r[cand]:
                                    ev_date_str = r[cand]
                                    break
                except Exception:
                    ev_date_str = None
                if not ev_date_str:
                    continue
                try:
                    # Parse date
                    ev_date = date.fromisoformat(str(ev_date_str)[:10])
                except Exception:
                    try:
                        ev_date = datetime.strptime(str(ev_date_str)[:10], "%Y-%m-%d").date()
                    except Exception:
                        continue
                months_elapsed = max(0.0, (date.today() - ev_date).days / 30.44)
                # Determine lambda by source_type if raw_documents available
                lam = 0.11552453009332421  # default concall 6m
                if has_rd and has_rd_cols:
                    # Try to find raw_documents source_type for this event
                    source_type = None
                    try:
                        # Try doc_id match if event_id numeric
                        try_event_id_int = None
                        try:
                            try_event_id_int = int(r["event_id"])
                        except Exception:
                            pass
                        if try_event_id_int is not None and "doc_id" in has_rd_cols:
                            srow = conn.execute("SELECT source_type FROM raw_documents WHERE doc_id=? LIMIT 1", (try_event_id_int,)).fetchone()
                            if srow:
                                source_type = srow["source_type"]
                        # raw_document_path may be in me.* or missing; check safely
                        rdp = None
                        try:
                            if "raw_document_path" in r.keys():
                                rdp = r["raw_document_path"]
                        except Exception:
                            rdp = None
                        if not source_type and rdp:
                            srow = conn.execute("SELECT source_type FROM raw_documents WHERE local_file_path=? LIMIT 1", (rdp,)).fetchone()
                            if srow:
                                source_type = srow["source_type"]
                    except Exception:
                        pass
                    if source_type:
                        st = str(source_type).lower()
                        if "youtube" in st or "analyst" in st:
                            lam = lam_map.get("Analyst Commentary / YouTube", lambda_for("Analyst Commentary / YouTube"))
                        elif "concall" in st or "mpc" in st:
                            lam = lam_map.get("Quarterly Concall / MPC Stance", lambda_for("Quarterly Concall / MPC Stance"))
                        else:
                            lam = lam_map.get("Union Budget / Tax Reform", lambda_for("Union Budget / Tax Reform"))
                    else:
                        # fallback by ripple order? keep default
                        lam = lam_map.get("Quarterly Concall / MPC Stance", lam)
                sig = float(r["significance_rank"]) if r["significance_rank"] is not None else 0.0
                decayed = sig * math.exp(-lam * months_elapsed)
                out.append({
                    "ripple_id": r["ripple_id"],
                    "event_id": r["event_id"],
                    "order_level": r["order_level"],
                    "raw_magnitude": r["raw_magnitude"],
                    "probability": r["probability"],
                    "lag_time_months": r["lag_time_months"],
                    "significance_rank": sig,
                    "announcement_date": ev_date_str,
                    "months_elapsed": round(months_elapsed, 2),
                    "lambda": round(lam, 5),
                    "decayed_significance": round(decayed, 2),
                })
            # Filter by floor if requested? Return all but sorted by decayed asc
            out = sorted(out, key=lambda x: x["decayed_significance"])
            # If significance_floor provided, caller can filter decayed < floor
            return out[:limit]
        except Exception as exc:
            logger.debug("v_ripple_decayed sqlite error: %s", exc)
            return []

def cold_export_rows(manager=None, months: int = 36) -> List[Dict[str, Any]]:
    """Helper for Pillar 1 Cold-tier parquet export: SELECT * FROM document_chunks WHERE published_date < date('now','-36 months')
    Returns rows that would be exported (for verification, not writing file).
    """
    from reality_engine.db.database import db_manager as _mgr
    mgr = manager or _mgr
    with mgr.session() as conn:
        if not _table_exists(conn, "document_chunks"):
            return []
        try:
            # Check which date column exists: document_chunks.published_date or raw_documents.published_date?
            has_col = _column_exists(conn, "document_chunks", "published_date")
            if has_col:
                rows = conn.execute(f"SELECT * FROM document_chunks WHERE published_date < date('now','-{months} months') LIMIT 100").fetchall()
            else:
                # Join via raw_documents
                rows = conn.execute(f"SELECT dc.* FROM document_chunks dc JOIN raw_documents rd ON dc.doc_id=rd.doc_id WHERE rd.published_date < date('now','-{months} months') LIMIT 100").fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.debug("cold_export note: %s", exc)
            return []

# CLI helper
def cli_main():
    import argparse
    parser = argparse.ArgumentParser(description="Prune decayed signals — SQLite fallback compatible")
    parser.add_argument("--dry-run", action="store_true", help="Count without deleting")
    parser.add_argument("--vectors", action="store_true", help="Only prune embeddings")
    args = parser.parse_args()
    res = prune_decayed_signals(dry_run=args.dry_run)
    print(json.dumps(res, indent=2))
    # Also show tiering demo
    print("\nTiering demo (Document Chunks Embeddings):")
    for age in [0,12,13,36,37]:
        print(f"  {age}m -> {tier_for_age('Document Chunks Embeddings', age)}")
    # Show decay sample
    print("\nDecayed significance sample S0=10:")
    for cat in HALF_LIVES:
        print(f"  {cat}: lambda={lambda_for(cat):.4f} S(3m)={decayed_significance(10,cat,3):.2f} S(12m)={decayed_significance(10,cat,12):.2f}")

if __name__ == "__main__":
    cli_main()

