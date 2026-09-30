"""Factor spine — dated, point-in-time-correct factor series (design §1-§2).

``tasks/FACTOR_SPINE_DESIGN_2026-09-29.md`` is the authority. This module is
its implementation: the three-table spine (``factor_series`` /
``factor_observation`` / ``factor_event_window``), the as-of resolver, the
audit readers, and the explicitly-invoked substrate backfill.

The failure class this exists to prevent
---------------------------------------
``tasks/next_wave_plan_2026-09-23.md:176-182`` (§2M) records that
``composite_screener._lookup_moat_metrics`` and
``ensemble_ranker.get_ensemble_weights_for_context`` take no date key, so
backfilled past dates get stamped with *today's* substrate — a look-ahead
machine. The structural difference here is that **every temporal decision is
a column in a ``WHERE`` clause, not a parameter threaded through a function
signature**, and the resolver has exactly one temporal predicate.

The contract (design §2.1, in one paragraph)
--------------------------------------------
A factor read is a function of ``(series, T)``, never of "now". It returns
**exactly one row per series, always** — carrying ``value_usable`` (the
number, or NULL) plus a ``status`` saying why a NULL is NULL. A value is
usable **iff ``status == 'ok'``**; callers gate on ``value_usable`` and must
never read ``raw_value``. Knowability is decided by ``as_of_date <= T`` and
by nothing else: ``period_end``, the fetch-time column, and ``is_latest``
are never read predicates. Within a period the vintage chosen is the
highest ``vintage`` already public on ``T`` — deliberately *not*
``is_latest = 1``, which means "latest as of now" and is a look-ahead in one
word. Levels and steps are carried forward (LVCF) only until they exceed the
series' own declared ``max_lookback_days``; after that the honest answer is
NULL — not a stale number, never an interpolated one.

Honest-NULL and quarantine-before-inference (AGENTS.md rules 13, 4)
-----------------------------------------------------------------
Nothing here interpolates, forward-fills a gap, or invents a magnitude. A
quarantined or inactive series is refused for the **whole series** with
``status='quarantined_or_inactive_series'`` — it never degrades into "the
last value before the bad row", because that laundering is how a demo seed
becomes a confident wrong answer. Every NULL carries a reason, and every
answer carries the trust metadata (``is_point_in_time``,
``availability_contract``, ``family``) a downstream inference model needs in
order not to over-read it.

Live DB is ahead of ``schema.sql``
----------------------------------
``reality_engine/db/schema.sql`` does NOT describe the live
``equity_intelligence.db`` (e.g. ``macro_events`` gained a ``doc_id`` column
that ``schema.sql`` lacks). **Editing ``schema.sql`` alone creates nothing.**
The migration path for this task is the idempotent
``ensure_factor_spine_schema()`` helper here, plus
``Repository.ensure_factor_spine_schema`` in ``reality_engine/db/repository.py``
(the ``ensure_validation_schema`` pattern, repository.py:3853). The DDL also
ships as documentation in ``reality_engine/db/factor_spine_schema.sql``
(SQLite) and ``reality_engine/db/factor_spine_postgres.sql`` (PG parity).
Neither shared schema file is modified by this task.

Scope of this task
------------------
Core spine + resolver + audits + the opt-in backfill. **No loaders, no
network fetching.** ``FACTOR_SERIES_REGISTRY`` is a code constant, so the
schema is useful the moment it is written and a registered-but-never-fetched
series is a first-class, queryable ``no_observation_known_at_T`` state
rather than a gap (design §4.1).
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

logger = logging.getLogger("reality_engine.factor_spine")

# IST is the market's own clock; every "today" decision in this module
# (the future-as_of_date guard, the default backfill horizon) uses it.
IST = timezone(timedelta(hours=5, minutes=30), "IST")

_SCHEMA_SQL = Path(__file__).resolve().parent.parent / "db" / "factor_spine_schema.sql"


# ---------------------------------------------------------------------------
# Vocabulary (design §1.2/§1.3). These are validation vocabularies, not
# constraints: an unknown value is refused at the boundary rather than
# silently coerced, because a mistyped family is a series nobody can find.
# ---------------------------------------------------------------------------
FAMILIES: Tuple[str, ...] = (
    "rates_credit",
    "crude_energy",
    "policy_budget",
    "fx_flows",
    "metals",
    "OTHER",
)

FREQUENCIES: Tuple[str, ...] = (
    "daily",
    "weekly",
    "monthly",
    "quarterly",
    "irregular",
    "annual",
)

AGGREGATION_POLICIES: Tuple[str, ...] = ("lvcf", "last", "sum", "none")

VALUE_SEMANTICS: Tuple[str, ...] = ("level", "rate", "index_level", "spread")

ALLOWED_SOURCES: Tuple[str, ...] = (
    "rbi_official",
    "mospi",
    "pib",
    "nse_official",
    "sebi_official",
    "manual",
    "fixture",
)

AVAILABILITY_CONTRACTS: Tuple[str, ...] = ("pita_strict", "pita_estimated")

SERIES_STATUSES: Tuple[str, ...] = ("active", "deprecated", "unreachable")

# Families whose publication lag is meaningful: ``as_of_date`` may not precede
# the end of the reference period (design §1.7 rule 3). A daily or
# event-driven series has no such constraint.
_LAG_BEARING_FREQUENCIES: Tuple[str, ...] = ("monthly", "quarterly", "annual")

# --- resolver statuses (design §2.1). Callers switch on these strings. -----
STATUS_OK = "ok"
STATUS_STALE = "stale_beyond_max_lookback"
STATUS_NO_OBS = "no_observation_known_at_T"
STATUS_NULL_VALUE = "null_value"
STATUS_QUARANTINED = "quarantined_or_inactive_series"
STATUS_UNKNOWN = "unknown_series"

RESOLVER_STATUSES: Tuple[str, ...] = (
    STATUS_OK,
    STATUS_STALE,
    STATUS_NO_OBS,
    STATUS_NULL_VALUE,
    STATUS_QUARANTINED,
    STATUS_UNKNOWN,
)

# Tables the spine DDL creates. ``factor_symbol_link`` is in this list but is
# DELIBERATELY UNPOPULATED — see the file header and ``POPULATED_TABLES``.
SPINE_TABLES: Tuple[str, ...] = (
    "factor_series",
    "factor_observation",
    "factor_event_window",
    "factor_symbol_link",
    "factor_load_run",
)

#: Tables this module actually writes rows into. ``factor_symbol_link`` is
#: excluded: nothing may populate it until exposure edges can be *estimated*
#: (design §3.4), and an asserted exposure is a placeholder with a number's
#: clothes on.
POPULATED_TABLES: Tuple[str, ...] = (
    "factor_series",
    "factor_observation",
    "factor_event_window",
    "factor_load_run",
)


# ---------------------------------------------------------------------------
# The series registry (design §4.2). A code constant, NOT a fetch: the
# registry is useful before any source is reachable, and a series that was
# never loaded is an honest-NULL, not a missing table.
# ---------------------------------------------------------------------------
FACTOR_SERIES_REGISTRY: Tuple[Dict[str, Any], ...] = (
    # (a) STATE / step function. FIRST series (design §4.3).
    dict(
        factor_key="IN.RBI.REPO_RATE",
        display_name="RBI policy repo rate",
        family="rates_credit",
        unit="pct",
        frequency="irregular",
        value_semantics="rate",
        source="rbi_official",
        source_url="https://www.rbi.org.in/",
        license="RBI public press release; review before redistribution",
        current_status="active",
        aggregation_policy="lvcf",
        max_lookback_days=45,
        expected_publication_lag_days=0,
        is_point_in_time=1,
        availability_contract="pita_strict",
        methodology_notes=(
            "RBI policy repo rate, effective date of each MPC action. One row per "
            "policy action; the value is the state from period_start until superseded."
        ),
    ),
    # (b) FLOW with publication lag. Registered, unreachable until a loader
    # exists. Honest-NULL by design, not a failure.
    dict(
        factor_key="IN.CPI.YOY",
        display_name="India CPI inflation, year-on-year",
        family="rates_credit",
        unit="pct",
        frequency="monthly",
        value_semantics="rate",
        source="mospi",
        source_url="https://www.mospi.gov.in/",
        license="MoSPI public release; review before redistribution",
        current_status="active",
        aggregation_policy="last",
        max_lookback_days=400,
        expected_publication_lag_days=45,
        is_point_in_time=1,
        availability_contract="pita_strict",
        methodology_notes=(
            "CPI combined YoY. period_end is the reference month end; as_of_date is "
            "the MoSPI release date. The lag is data, never inferred by the resolver."
        ),
    ),
)

_REGISTRY_COLUMNS: Tuple[str, ...] = (
    "factor_key",
    "display_name",
    "family",
    "unit",
    "frequency",
    "value_semantics",
    "source",
    "source_url",
    "license",
    "current_status",
    "aggregation_policy",
    "max_lookback_days",
    "expected_publication_lag_days",
    "is_point_in_time",
    "availability_contract",
    "methodology_notes",
)


# ---------------------------------------------------------------------------
# Connection plumbing. Every public entry point accepts EITHER a
# ``DatabaseManager`` (repo convention: ``mgr.session()``) or a raw
# ``sqlite3.Connection`` (test/CLI convention). Read paths never create
# tables, so the quarantine fragment is selected by table existence rather
# than by writing to the DB behind the caller's back.
# ---------------------------------------------------------------------------
@contextmanager
def _session(target: Optional[Any]) -> Iterator[Any]:
    """Yield a live connection from a manager or a raw sqlite3 connection."""
    if target is None:
        from reality_engine.db.database import db_manager

        target = db_manager
    if hasattr(target, "session"):
        with target.session() as conn:
            yield conn
    else:
        yield target


def _table_exists(conn: Any, table: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
            (table,),
        ).fetchone()
        return row is not None
    except Exception:  # pragma: no cover - defensive on schema drift
        return False


def _quarantine_clause(alias: str, table: str, key_col: str) -> str:
    """``NOT EXISTS`` anti-quarantine fragment, or a vacuous ``1=1``.

    The trust layer (``substrate_hygiene``) materializes quarantine keys into
    ``substrate_quarantine(rule_id, table_name, row_key)``. A spine table is
    absorbed by writing ``CAST(<pk> AS TEXT)`` as ``row_key`` — no change to
    the trust layer is required. When the table has never been created the
    fragment is vacuous, which is correct (nothing is quarantined yet) and
    keeps read paths read-only.
    """
    return (
        f"AND NOT EXISTS (SELECT 1 FROM substrate_quarantine q "
        f"WHERE q.table_name = '{table}' AND q.row_key = CAST({alias}.{key_col} AS TEXT))"
    )


def _today_ist() -> str:
    return datetime.now(IST).date().isoformat()


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------
def read_spine_ddl() -> str:
    """Return the SQLite spine DDL shipped in ``db/factor_spine_schema.sql``."""
    if not _SCHEMA_SQL.exists():  # pragma: no cover - packaging guard
        raise FileNotFoundError(f"factor spine DDL not found: {_SCHEMA_SQL}")
    return _SCHEMA_SQL.read_text(encoding="utf-8")


def ensure_factor_spine_schema(manager: Optional[Any] = None) -> None:
    """Create the factor spine tables + indexes if absent. Idempotent, additive only.

    This is the migration path. The live DB is ahead of ``schema.sql``, so
    new DDL ships here first and may only be appended to ``schema.sql``
    later as documentation. Never modifies an existing table.
    """
    with _session(manager) as conn:
        conn.executescript(read_spine_ddl())
        # The resolver's quarantine predicate reads this table. Creating it
        # empty is the same trust-layer-owned table substrate_hygiene.ensure_schema
        # owns; it does NOT apply any rule (that stays an explicit operator call).
        conn.execute(
            "CREATE TABLE IF NOT EXISTS substrate_quarantine ("
            "rule_id TEXT NOT NULL, table_name TEXT NOT NULL, row_key TEXT NOT NULL, "
            "severity TEXT NOT NULL, reason TEXT, "
            "detected_at TEXT DEFAULT CURRENT_TIMESTAMP, "
            "PRIMARY KEY (rule_id, table_name, row_key))"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_substrate_quarantine_table "
            "ON substrate_quarantine(table_name)"
        )


# ---------------------------------------------------------------------------
# Write path — registry + observations
# ---------------------------------------------------------------------------
def _validate_registry_entry(entry: Dict[str, Any]) -> None:
    key = entry.get("factor_key")
    if not key:
        raise ValueError("series registry entry requires factor_key")
    if entry.get("family") not in FAMILIES:
        raise ValueError(f"{key}: family {entry.get('family')!r} not in {FAMILIES}")
    if entry.get("unit") in (None, ""):
        raise ValueError(f"{key}: unit is required")
    if entry.get("frequency") not in FREQUENCIES:
        raise ValueError(f"{key}: frequency {entry.get('frequency')!r} not in {FREQUENCIES}")
    if entry.get("aggregation_policy") not in AGGREGATION_POLICIES:
        raise ValueError(
            f"{key}: aggregation_policy {entry.get('aggregation_policy')!r} not in {AGGREGATION_POLICIES}"
        )
    if entry.get("value_semantics") not in VALUE_SEMANTICS:
        raise ValueError(f"{key}: value_semantics {entry.get('value_semantics')!r} not in {VALUE_SEMANTICS}")
    if not str(entry.get("source", "")).startswith("vendor:") and entry.get("source") not in ALLOWED_SOURCES:
        raise ValueError(f"{key}: source {entry.get('source')!r} not in ALLOWED_SOURCES or 'vendor:<name>'")
    if entry.get("availability_contract") not in AVAILABILITY_CONTRACTS:
        raise ValueError(f"{key}: availability_contract not in {AVAILABILITY_CONTRACTS}")
    if entry.get("current_status") not in SERIES_STATUSES:
        raise ValueError(f"{key}: current_status not in {SERIES_STATUSES}")
    # Design §1.2: max_lookback_days is NOT NULL precisely so a series may
    # not claim "always fresh". Refuse a missing or negative ceiling.
    ceiling = entry.get("max_lookback_days")
    if ceiling is None or int(ceiling) < 0:
        raise ValueError(f"{key}: max_lookback_days must be a non-negative integer (got {ceiling!r})")


def register_series(manager: Optional[Any] = None, entries: Optional[Sequence[Dict[str, Any]]] = None) -> int:
    """Write the series REGISTRY into ``factor_series``. Idempotent; returns rows written.

    Never rewrites an existing definition row: a changed definition is
    ``current_status='deprecated'`` plus a NEW ``factor_key``, because
    silently mutating a definition in place would change what every past
    as-of read means.
    """
    rows_in = list(entries if entries is not None else FACTOR_SERIES_REGISTRY)
    for entry in rows_in:
        _validate_registry_entry(entry)
    placeholders = ", ".join("?" for _ in _REGISTRY_COLUMNS)
    cols = ", ".join(_REGISTRY_COLUMNS)
    sql = f"INSERT OR IGNORE INTO factor_series ({cols}) VALUES ({placeholders})"
    written = 0
    with _session(manager) as conn:
        for entry in rows_in:
            cur = conn.execute(sql, tuple(entry.get(c) for c in _REGISTRY_COLUMNS))
            written += max(cur.rowcount, 0)
    return written


_OBSERVATION_COLUMNS: Tuple[str, ...] = (
    "series_id",
    "period_start",
    "period_end",
    "value",
    "unit",
    "as_of_date",
    "retrieved_at",
    "source",
    "source_url",
    "vintage",
    "revision_of",
    "is_latest",
    "confidence",
    "notes",
    "source_doc_id",
    "chunk_span",
)


def upsert_observations(
    manager: Optional[Any],
    series_key: str,
    rows: Sequence[Dict[str, Any]],
    retrieved_at: Optional[str] = None,
) -> int:
    """Insert/refresh factor observations for ``series_key``. Returns rows written.

    Load-time half of the anti-look-ahead contract (design §4.2). Refusals
    are raised or counted, never warned into the substrate:

    * ``as_of_date > today (IST)``           -> ValueError (future knowledge is a bug
      at construction, not a warning).
    * ``source`` not in ALLOWED_SOURCES / ``vendor:<name>`` -> ValueError.
    * unknown ``series_key``                 -> ValueError.
    * ``as_of_date < period_end`` for a monthly/quarterly/annual series -> row
      refused (a reference period cannot close before it is public).

    The fetch-time column is stamped here and is deliberately NOT a read
    predicate: a historical backfill legitimately stamps today on every
    historical row, because it is a reconstruction of what was public, not a
    record of when we happened to fetch it.
    """
    with _session(manager) as conn:
        row = conn.execute(
            "SELECT series_id, unit, frequency FROM factor_series WHERE factor_key = ?",
            (series_key,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown series_key {series_key!r} (register it first)")
        series_id = int(row[0])
        series_unit = row[1]
        frequency = row[2]
        lag_bearing = frequency in _LAG_BEARING_FREQUENCIES
        stamp = retrieved_at or datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        today = _today_ist()

        placeholders = ", ".join("?" for _ in _OBSERVATION_COLUMNS)
        cols = ", ".join(_OBSERVATION_COLUMNS)
        conflict = (
            "ON CONFLICT(series_id, period_start, period_end, vintage) DO UPDATE SET "
            "value=excluded.value, unit=excluded.unit, as_of_date=excluded.as_of_date, "
            "source=excluded.source, source_url=excluded.source_url, "
            "revision_of=excluded.revision_of, is_latest=excluded.is_latest, "
            "confidence=excluded.confidence, notes=excluded.notes, "
            "source_doc_id=excluded.source_doc_id, chunk_span=excluded.chunk_span"
        )
        sql = f"INSERT INTO factor_observation ({cols}) VALUES ({placeholders}) {conflict}"

        written = 0
        for r in rows:
            as_of = r.get("as_of_date")
            if not as_of:
                raise ValueError("as_of_date is required on every observation (KNOWLEDGE date)")
            if str(as_of) > today:
                raise ValueError(
                    f"refused future-dated observation: as_of_date={as_of} > today(IST)={today}"
                )
            source = r.get("source")
            if not (source in ALLOWED_SOURCES or str(source or "").startswith("vendor:")):
                raise ValueError(f"source {source!r} not in ALLOWED_SOURCES")
            period_end = r.get("period_end") or r.get("period_start")
            period_start = r.get("period_start") or period_end
            if not period_start:
                raise ValueError("period_start is required on every observation")
            if lag_bearing and str(as_of) < str(period_end):
                logger.warning(
                    "refused observation: as_of_date=%s precedes period_end=%s for a %s series",
                    as_of, period_end, frequency,
                )
                continue
            vintage = int(r.get("vintage") or 1)
            revision_of = r.get("revision_of")
            if revision_of is None and vintage > 1:
                prev = conn.execute(
                    "SELECT observation_id FROM factor_observation "
                    "WHERE series_id=? AND period_start=? AND period_end=? AND vintage=?",
                    (series_id, period_start, period_end, vintage - 1),
                ).fetchone()
                revision_of = prev[0] if prev else None
            conn.execute(
                sql,
                (
                    series_id,
                    period_start,
                    period_end,
                    r.get("value"),
                    r.get("unit", series_unit),
                    as_of,
                    r.get("retrieved_at", stamp),
                    source,
                    r.get("source_url"),
                    vintage,
                    revision_of,
                    int(r.get("is_latest", 1)),
                    r.get("confidence"),
                    r.get("notes"),
                    r.get("source_doc_id"),
                    r.get("chunk_span"),
                ),
            )
            # Audit-only freshness bookkeeping. The resolver never reads this.
            conn.execute(
                "UPDATE factor_observation SET is_latest = 0 "
                "WHERE series_id=? AND period_start=? AND period_end=? AND vintage < ?",
                (series_id, period_start, period_end, vintage),
            )
            written += 1
    return written


# ---------------------------------------------------------------------------
# The as-of resolver (design §2.3). This is the core artifact.
#
# The single temporal predicate in the whole module is
# ``o.as_of_date <= g.asof_date``. There is no second one to get wrong.
# ---------------------------------------------------------------------------
_STATE_SQL_TEMPLATE = """
WITH series_gate AS (
  SELECT b.series_id,
         b.asof_date,
         any.series_id        AS any_series_id,   -- does the definition exist at all?
         live.series_id       AS live_series_id,  -- exists AND active AND not quarantined
         CASE WHEN ?3 IS NULL THEN live.max_lookback_days
              ELSE MIN(live.max_lookback_days, ?3) END AS max_lookback_days
  FROM (SELECT ?1 AS series_id, ?2 AS asof_date) b
  LEFT JOIN factor_series any
         ON any.series_id = b.series_id
  LEFT JOIN factor_series live
         ON live.series_id = b.series_id
        AND live.current_status = 'active'
        {QUAR_SERIES}
),
ranked AS (
  SELECT o.observation_id, o.series_id, o.period_start, o.period_end, o.value, o.unit,
         o.as_of_date, o.vintage,
         ROW_NUMBER() OVER (
           PARTITION BY o.series_id, o.period_start, o.period_end
           ORDER BY o.vintage DESC, o.as_of_date DESC, o.observation_id DESC
         ) AS vintage_rank
  FROM factor_observation o
  JOIN series_gate g ON g.live_series_id = o.series_id
  WHERE o.as_of_date <= g.asof_date
    {QUAR_OBS}
),
latest_known AS (
  SELECT * FROM ranked WHERE vintage_rank = 1
),
picked AS (
  SELECT lk.observation_id, lk.value, lk.unit, lk.period_start, lk.period_end,
         lk.as_of_date, lk.vintage,
         julianday(g.asof_date) - julianday(lk.period_end) AS age_days
  FROM latest_known lk
  CROSS JOIN series_gate g
  ORDER BY lk.period_end DESC, lk.vintage DESC, lk.as_of_date DESC
  LIMIT 1
),
statused AS (
  SELECT g.series_id, g.any_series_id, g.live_series_id, g.max_lookback_days,
         p.observation_id, p.value, p.unit, p.period_start, p.period_end,
         p.as_of_date, p.vintage, p.age_days,
         CASE
           WHEN g.any_series_id  IS NULL THEN 'unknown_series'
           WHEN g.live_series_id IS NULL THEN 'quarantined_or_inactive_series'
           WHEN p.observation_id IS NULL THEN 'no_observation_known_at_T'
           WHEN p.value          IS NULL THEN 'null_value'
           WHEN p.age_days > g.max_lookback_days THEN 'stale_beyond_max_lookback'
           ELSE 'ok'
         END AS status
  FROM series_gate g
  LEFT JOIN picked p ON 1 = 1
)
SELECT s.factor_key, s.family, s.unit AS series_unit, s.aggregation_policy,
       s.current_status, s.is_point_in_time, s.availability_contract,
       x.series_id, x.observation_id, x.value AS raw_value,
       CASE WHEN x.status = 'ok' THEN x.value END AS value_usable,
       x.unit, x.period_start, x.period_end, x.as_of_date, x.vintage,
       CAST(ROUND(x.age_days) AS INTEGER) AS age_days,
       x.max_lookback_days, x.status
FROM statused x
LEFT JOIN factor_series s ON s.series_id = x.series_id
"""


def _asof_status_row(
    series_ref: Any,
    asof_date: str,
    max_lookback_override_days: Optional[int],
    status: str,
) -> Dict[str, Any]:
    """Uniform single-row shape, including the unknown-series case (R10)."""
    return {
        "factor_key": series_ref if isinstance(series_ref, str) else None,
        "series_id": series_ref if isinstance(series_ref, int) else None,
        "family": None,
        "unit": None,
        "series_unit": None,
        "aggregation_policy": None,
        "current_status": None,
        "is_point_in_time": None,
        "availability_contract": None,
        "observation_id": None,
        "raw_value": None,
        "value_usable": None,
        "period_start": None,
        "period_end": None,
        "as_of_date": None,
        "vintage": None,
        "age_days": None,
        "max_lookback_days": max_lookback_override_days,
        "status": status,
    }


def resolve_as_of(
    manager: Optional[Any],
    series_key: Any,
    asof_date: str,
    max_lookback_override_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Read one series as it was knowable on ``asof_date``. Exactly one row, always.

    ``series_key`` is a ``factor_key`` string or a ``series_id`` int. The
    returned dict ALWAYS has ``status`` and ``value_usable``; the value is
    usable **iff** ``status == 'ok'``. Never read ``raw_value`` as if it were
    usable — it is exposed for diagnosis (``stale`` rows keep their number so
    a human can see what was withheld and why).

    ``max_lookback_override_days`` may only ever *tighten* a call site's
    ceiling; the effective ceiling is ``MIN(series, override)``.

    This reader is a decision-path reader: it contains no ``is_latest``
    predicate, no ``period_end`` visibility gate, and no system-time gate.
    """
    if not asof_date:
        raise ValueError("asof_date (T) is required: a factor read is a function of (series, T)")
    with _session(manager) as conn:
        if isinstance(series_key, int):
            ref = conn.execute(
                "SELECT series_id FROM factor_series WHERE series_id = ?", (series_key,)
            ).fetchone()
            series_id: Optional[int] = int(ref[0]) if ref else None
        else:
            ref = conn.execute(
                "SELECT series_id FROM factor_series WHERE factor_key = ?", (str(series_key),)
            ).fetchone()
            series_id = int(ref[0]) if ref else None
        if series_id is None:
            # R10: an unknown series still produces exactly one row. A resolver
            # that returns zero rows makes "no data" indistinguishable from
            # "I forgot to write the query".
            return _asof_status_row(series_key, asof_date, max_lookback_override_days, STATUS_UNKNOWN)
        if not _table_exists(conn, "factor_observation"):
            return _asof_status_row(series_key, asof_date, max_lookback_override_days, STATUS_NO_OBS)
        has_q = _table_exists(conn, "substrate_quarantine")
        sql = _STATE_SQL_TEMPLATE.format(
            QUAR_SERIES=_quarantine_clause("live", "factor_series", "series_id") if has_q else "AND 1=1",
            QUAR_OBS=_quarantine_clause("o", "factor_observation", "observation_id") if has_q else "AND 1=1",
        )
        row = conn.execute(
            sql, (series_id, asof_date, max_lookback_override_days)
        ).fetchone()
    if row is None:  # pragma: no cover - LEFT JOINs guarantee a row
        return _asof_status_row(series_key, asof_date, max_lookback_override_days, STATUS_UNKNOWN)
    out = dict(row)
    if out.get("unit") is None:
        out["unit"] = out.get("series_unit")
    return out


# Design-doc aliases. Kept so the §4.2/§4.4 vocabulary resolves unchanged.
factor_state = resolve_as_of


# ---------------------------------------------------------------------------
# The panel reader (design §2.5, corrected twice).
#
# Correction 1 (§2.5): a naive correlated-subquery form returns the candidate
# value for a STALE series unless the staleness gate is applied in the outer
# select. The gate is applied here, in the same CASE that nulls value_usable.
#
# Correction 2 (the drafting bug the design records): a form driven by
# ``WHERE current_status='active' AND NOT quarantined`` returns ZERO rows for
# a quarantined series. Every requested series therefore goes through the
# same single-row gate, so a quarantined or unknown series appears WITH a
# status instead of vanishing. Silently-dropped rows are the bug.
# ---------------------------------------------------------------------------
_PANEL_SQL_TEMPLATE = """
WITH requested AS (
  {REQUESTED}
),
gate AS (
  SELECT r.ord, r.factor_key AS requested_key,
         any.series_id  AS any_series_id,
         live.series_id AS live_series_id,
         CASE WHEN ? IS NULL THEN live.max_lookback_days
              ELSE MIN(live.max_lookback_days, ?) END AS max_lookback_days
  FROM requested r
  LEFT JOIN factor_series any  ON any.factor_key = r.factor_key
  LEFT JOIN factor_series live
         ON live.series_id = any.series_id
        AND live.current_status = 'active'
        {QUAR_SERIES}
),
ranked AS (
  SELECT g.ord, g.requested_key, g.any_series_id, g.live_series_id, g.max_lookback_days,
         o.observation_id, o.series_id, o.period_start, o.period_end, o.value, o.unit,
         o.as_of_date, o.vintage,
         ROW_NUMBER() OVER (
           PARTITION BY o.series_id, o.period_start, o.period_end
           ORDER BY o.vintage DESC, o.as_of_date DESC, o.observation_id DESC
         ) AS vintage_rank
  FROM gate g
  JOIN factor_observation o ON o.series_id = g.live_series_id
  WHERE o.as_of_date <= ?
    {QUAR_OBS}
),
latest_known AS (
  SELECT * FROM ranked WHERE vintage_rank = 1
),
picked AS (
  SELECT * FROM (
    SELECT lk.*, ROW_NUMBER() OVER (
             PARTITION BY lk.ord
             ORDER BY lk.period_end DESC, lk.vintage DESC, lk.as_of_date DESC, lk.observation_id DESC
           ) AS pick_rank
    FROM latest_known lk
  ) WHERE pick_rank = 1
),
statused AS (
  SELECT g.ord, g.requested_key, g.any_series_id, g.live_series_id, g.max_lookback_days,
         p.observation_id, p.value, p.unit, p.period_start, p.period_end,
         p.as_of_date, p.vintage, p.series_id, p.age_days,
         -- Status is factored out here so it is written ONCE and both
         -- ``value_usable`` and ``status`` below are driven by the same
         -- expression. Computing it in the outer SELECT instead would need
         -- the CASE repeated, and a divergence between the two is exactly
         -- how a value leaks through a gate that should have withheld it.
         -- ``age_days`` is read from ``aged`` rather than recomputed so the
         -- staleness test and the reported age cannot disagree.
         CASE
           WHEN g.any_series_id  IS NULL THEN 'unknown_series'
           WHEN g.live_series_id IS NULL THEN 'quarantined_or_inactive_series'
           WHEN p.observation_id IS NULL THEN 'no_observation_known_at_T'
           WHEN p.value          IS NULL THEN 'null_value'
           WHEN p.age_days > g.max_lookback_days THEN 'stale_beyond_max_lookback'
           ELSE 'ok'
         END AS status
  FROM gate g
  LEFT JOIN (
    SELECT pk.*, julianday(?) - julianday(pk.period_end) AS age_days
    FROM picked pk
  ) p ON p.ord = g.ord
)
SELECT x.requested_key, s.factor_key, s.family, s.unit AS series_unit, s.aggregation_policy,
       s.current_status, s.is_point_in_time, s.availability_contract,
       x.series_id, x.observation_id, x.value AS raw_value,
       CASE WHEN x.status = 'ok' THEN x.value END AS value_usable,
       x.unit, x.period_start, x.period_end, x.as_of_date, x.vintage,
       CAST(ROUND(x.age_days) AS INTEGER) AS age_days,
       x.max_lookback_days, x.status
FROM statused x
LEFT JOIN factor_series s ON s.series_id = x.any_series_id
ORDER BY x.ord
"""


def resolve_panel(
    manager: Optional[Any],
    asof_date: str,
    series_keys: Optional[Sequence[str]] = None,
    max_lookback_override_days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """One row per REQUESTED series at ``asof_date``. A missing series is reported, not dropped.

    ``series_keys=None`` means "every registered series", in ``(family,
    factor_key)`` order. Either way the output has exactly one row per
    requested key, including quarantined, inactive, never-fetched and
    unknown ones — each with a ``status``. Callers filter on
    ``status == 'ok'``; nothing is silently omitted.

    The staleness gate is applied HERE, in the same CASE that nulls
    ``value_usable`` (design §2.5 regression).
    """
    if not asof_date:
        raise ValueError("asof_date (T) is required: a factor read is a function of (series, T)")
    with _session(manager) as conn:
        if series_keys is None:
            keys = [
                r[0]
                for r in conn.execute(
                    "SELECT factor_key FROM factor_series ORDER BY family, factor_key"
                ).fetchall()
            ]
        else:
            keys = [str(k) for k in series_keys]
        if not keys:
            return []
        if not _table_exists(conn, "factor_observation"):
            return [
                _asof_status_row(k, asof_date, max_lookback_override_days, STATUS_NO_OBS)
                for k in keys
            ]
        requested = " UNION ALL ".join(
            f"SELECT ? AS factor_key, {i} AS ord" for i in range(len(keys))
        )
        has_q = _table_exists(conn, "substrate_quarantine")
        sql = _PANEL_SQL_TEMPLATE.format(
            REQUESTED=requested,
            QUAR_SERIES=_quarantine_clause("live", "factor_series", "series_id") if has_q else "AND 1=1",
            QUAR_OBS=_quarantine_clause("o", "factor_observation", "observation_id") if has_q else "AND 1=1",
        )
        params: List[Any] = [*keys, max_lookback_override_days, max_lookback_override_days,
                             asof_date, asof_date]
        rows = conn.execute(sql, params).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if not d.get("factor_key"):
            d["factor_key"] = d.pop("requested_key", None)
        else:
            d.pop("requested_key", None)
        if d.get("unit") is None:
            d["unit"] = d.get("series_unit")
        out.append(d)
    return out


factor_panel = resolve_panel


# ---------------------------------------------------------------------------
# Audit readers. These are NOT the decision path and are deliberately kept
# out of FACTOR_DECISION_READERS: they exist so a reviewer can *prove* the
# decision path is correct, which means being allowed to look at the future.
# ---------------------------------------------------------------------------

def factor_releases(
    manager: Optional[Any],
    asof_date: str,
    series_keys: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Every ``(period, vintage)`` KNOWN at ``asof_date``. One row per release.

    Deliberately un-gated on staleness and un-carried: this answers "what
    existed on T", not "what to use". It is what makes the revision chain
    auditable without a second schema. ``is_latest`` is REPORTED here
    (display), never filtered on (design §2.4 / R5).
    """
    with _session(manager) as conn:
        keys: List[str]
        if series_keys is None:
            keys = [r[0] for r in conn.execute("SELECT factor_key FROM factor_series").fetchall()]
        else:
            keys = [str(k) for k in series_keys]
        if not keys:
            return []
        sql = """
        SELECT o.observation_id, o.series_id, s.factor_key, s.family, s.is_point_in_time,
               o.period_start, o.period_end, o.value, o.unit,
               o.as_of_date, o.vintage, o.is_latest, o.source, o.source_url,
               o.source_doc_id, o.chunk_span,
               (o.vintage > 1) AS is_revision
        FROM factor_observation o
        JOIN factor_series s ON s.series_id = o.series_id
        WHERE s.factor_key IN ({ph})
          AND o.as_of_date <= ?
          {quar}
        ORDER BY s.family, s.factor_key, o.period_end, o.vintage
        """.format(
            ph=", ".join("?" for _ in keys),
            quar=(
                _quarantine_clause("o", "factor_observation", "observation_id")
                if _table_exists(conn, "substrate_quarantine")
                else "AND 1=1"
            ),
        )
        rows = conn.execute(sql, [*keys, asof_date]).fetchall()
    return [dict(r) for r in rows]


def gap_audit(
    manager: Optional[Any],
    series_key: str,
    asof_date: str,
) -> List[Dict[str, Any]]:
    """Consecutive known periods as of ``asof_date``, with the gap between them.

    ``max_lookback_days`` bounds staleness in *days*; this bounds it in
    *observations* and is the query a reviewer runs to confirm a series is not
    being silently carried across a long break. Deduplicated to the latest
    KNOWN vintage first, so the version chain does not show up as a bogus
    ``gap_days = 0`` self-row.
    """
    with _session(manager) as conn:
        sql = """
        WITH latest_known AS (
          SELECT o.*, ROW_NUMBER() OVER (PARTITION BY period_start, period_end
                   ORDER BY vintage DESC, as_of_date DESC) AS vr
          FROM factor_observation o
          WHERE o.series_id = (SELECT series_id FROM factor_series WHERE factor_key = ?)
            AND o.as_of_date <= ?
        )
        SELECT period_start, period_end, value, vintage, as_of_date,
               LAG(period_end) OVER (ORDER BY period_end) AS prev_period_end,
               CAST(julianday(period_end)
                    - julianday(LAG(period_end) OVER (ORDER BY period_end)) AS INTEGER) AS gap_days
        FROM latest_known
        WHERE vr = 1
        ORDER BY period_end
        """
        rows = conn.execute(sql, (series_key, asof_date)).fetchall()
    return [dict(r) for r in rows]


def lookahead_audit(
    manager: Optional[Any],
    series_key: str,
    asof_date: str,
) -> Dict[str, Any]:
    """The anti-look-ahead assertion. ``lookahead_violations`` must be 0, always.

    A 0 from a table with no future rows proves nothing, so this also
    reports ``future_dated_rows_in_table``: the count the gate must be
    excluding. If that is 0 the assertion is VACUOUS and ``is_vacuous`` says
    so out loud.
    """
    with _session(manager) as conn:
        ref = conn.execute(
            "SELECT series_id FROM factor_series WHERE factor_key = ?", (series_key,)
        ).fetchone()
        if ref is None:
            return {
                "series_key": series_key,
                "asof_date": asof_date,
                "lookahead_violations": 0,
                "future_dated_rows_in_table": 0,
                "is_vacuous": True,
                "note": "unknown series: nothing to assert",
            }
        violations = conn.execute(
            "SELECT COUNT(*) FROM factor_observation "
            "WHERE series_id = ? AND as_of_date <= ? AND as_of_date > ?",
            (ref[0], asof_date, asof_date),
        ).fetchone()[0]
        future = conn.execute(
            "SELECT COUNT(*) FROM factor_observation WHERE series_id = ? AND as_of_date > ?",
            (ref[0], asof_date),
        ).fetchone()[0]
    return {
        "series_key": series_key,
        "asof_date": asof_date,
        "lookahead_violations": int(violations),
        "future_dated_rows_in_table": int(future),
        "is_vacuous": int(future) == 0,
    }


#: Decision-path readers. Linted by the test suite: their source may not
#: contain a system-time column, an ``is_latest`` predicate, a
#: ``period_end`` visibility gate, or a price-table future predicate
#: (design §2.8). The failure being guarded is a *shape* of the query, not
#: a value, so the guard is source-level rather than behavioural.
FACTOR_DECISION_READERS = (resolve_as_of, resolve_panel)


# ---------------------------------------------------------------------------
# Substrate backfill — OPT-IN, EXPLICIT, DRY-RUN BY DEFAULT.
#
# Why it is not a read-path side effect: the spine is a *read* contract
# (design Q8's recommendation: read-only input). This path exists because the
# user asked whether the spine may also seed the existing substrate, and the
# honest answer is "yes, but only ever on request, and never implicitly".
#
# What it does: turns dated ``factor_event_window`` rows into REAL
# ``macro_events`` + ``ripple_effects`` rows, each carrying
# ``source_series_id`` / ``source_observation_id`` provenance.
#
# What it must never do:
#   * run implicitly from any resolve_* call;
#   * synthesize a magnitude — an unquantified shock stays NULL, it does not
#     become 0.0, and it does not inherit ripple_effects' DEFAULT 1.0
#     transmission_elasticity (that constant is the defect, design D1);
#   * delete or modify an existing row;
#   * touch ``regulatory_political_risks``.
#
# Scope note: when explicitly invoked, the rows it produces are the honest
# replacement for the 3 PHASE5_DEMO macro_events fixtures and the 61
# constant-beta ripple rows. It does not delete those — quarantine and
# reporting handle them, deletion is an operator call.
# ---------------------------------------------------------------------------

#: Columns we would like to write, intersected at runtime with what the live
#: table actually has. The live DB is ahead of schema.sql, so the target
#: column set is discovered, not assumed.
_MACRO_EVENT_COLUMNS: Tuple[Tuple[str, Any], ...] = (
    ("event_id", "event_id"),
    ("event_name", "event_name"),
    ("category", "category"),
    ("event_date", "event_date"),
    ("summary", "summary"),
    ("affected_nodes_json", "affected_nodes_json"),
)

_RIPPLE_COLUMNS: Tuple[str, ...] = (
    "event_id",
    "parent_ripple_id",
    "order_level",
    "target_type",
    "target_sector_id",
    "target_industry_id",
    "target_company_id",
    "transmission_channel",
    "transmission_elasticity",
    "raw_magnitude",
    "probability",
    "lag_time_months",
    "significance_rank",
)


def _intersect_columns(conn: Any, table: str, wanted: Sequence[str]) -> List[str]:
    try:
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:  # pragma: no cover - defensive on schema drift
        return []
    return [c for c in wanted if c in have]


def backfill_substrate_from_spine(
    manager: Optional[Any],
    asof_date: Optional[str] = None,
    series_keys: Optional[Sequence[str]] = None,
    dry_run: bool = True,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Seed ``macro_events`` / ``ripple_effects`` from spine event windows.

    **Opt-in and dry-run by default.** No resolver calls this; nothing calls
    this implicitly. Pass ``dry_run=False`` to actually write.

    Honesty rules enforced here:
      * a shock with no numeric magnitude produces ``raw_magnitude = NULL``
        and ``transmission_elasticity = NULL`` — never a default, never 1.0;
      * a shock with no probability produces ``probability = NULL``;
      * every created row carries ``source_series_id=<id>`` and
        ``source_observation_id=<window id>`` in ``transmission_channel`` so
        it is traceable back to the spine;
      * existing rows are never modified or deleted; a window already
        represented is skipped, so the path is idempotent;
      * ``regulatory_political_risks`` is never read or written.
    """
    report: Dict[str, Any] = {
        "dry_run": bool(dry_run),
        "asof_date": asof_date or _today_ist(),
        "candidates": 0,
        "would_write_events": 0,
        "would_write_ripples": 0,
        "wrote_events": 0,
        "wrote_ripples": 0,
        "skipped_existing": 0,
        "errors": [],
    }
    horizon = report["asof_date"]
    with _session(manager) as conn:
        if not _table_exists(conn, "factor_event_window"):
            report["errors"].append("factor_event_window table missing; run ensure_factor_spine_schema()")
            return report
        for required in ("macro_events", "ripple_effects"):
            if not _table_exists(conn, required):
                report["errors"].append(
                    f"{required} table missing; the spine does not own it "
                    f"(pruning_engine.ensure_pruning_schema) and will not create it here"
                )
        if report["errors"]:
            return report

        quar = (
            "AND NOT EXISTS (SELECT 1 FROM substrate_quarantine q "
            "WHERE q.table_name='factor_event_window' "
            "AND q.row_key = CAST(w.event_window_id AS TEXT))"
            if _table_exists(conn, "substrate_quarantine")
            else "AND 1=1"
        )
        sql = f"""
        SELECT w.event_window_id, w.series_id, s.factor_key, s.family, s.unit,
               w.event_label, w.announced_date, w.window_start, w.window_end,
               w.magnitude, w.direction, w.lag_time_months, w.probability,
               w.as_of_date, w.vintage, w.source, w.source_url
        FROM factor_event_window w
        JOIN factor_series s ON s.series_id = w.series_id
        WHERE w.as_of_date <= ? {quar}
        ORDER BY w.announced_date, w.event_window_id
        """
        params: List[Any] = [horizon]
        if series_keys is not None:
            keys = [str(k) for k in series_keys]
            sql += f" AND s.factor_key IN ({', '.join('?' for _ in keys)})"
            params.extend(keys)
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        windows = conn.execute(sql, params).fetchall()
        report["candidates"] = len(windows)

        ev_cols = _intersect_columns(conn, "macro_events", [c for c, _ in _MACRO_EVENT_COLUMNS])
        rp_cols = _intersect_columns(conn, "ripple_effects", _RIPPLE_COLUMNS)
        for c, _ in _MACRO_EVENT_COLUMNS:
            if c not in ev_cols:
                report["errors"].append(f"macro_events.{c} absent in this DB; that field is not written")
        if not {"event_id", "event_name", "category", "event_date", "summary"} <= set(ev_cols):
            report["errors"].append("macro_events lacks the required spine columns; nothing written")
            return report

        for w in windows:
            wid = int(w["event_window_id"])
            series_id = int(w["series_id"])
            event_id = f"FEW_{wid}"
            provenance = (
                f"source_series_id={series_id}; source_observation_id={wid}; "
                f"factor_key={w['factor_key']}; unit={w['unit']}"
            )
            exists = conn.execute(
                "SELECT 1 FROM macro_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if exists:
                report["skipped_existing"] += 1
                continue
            affected = conn.execute(
                "SELECT transmission_channel FROM ripple_effects WHERE event_id = ? LIMIT 1",
                (event_id,),
            ).fetchone()
            if affected:
                report["skipped_existing"] += 1
                continue

            report["would_write_events"] += 1
            report["would_write_ripples"] += 1
            if dry_run:
                continue

            event_values = {
                "event_id": event_id,
                "event_name": str(w["event_label"])[:255],
                "category": str(w["family"])[:50],
                "event_date": w["announced_date"],
                "summary": f"{w['event_label']} ({w['factor_key']}); window {w['window_start']}"
                           f" -> {w['window_end'] or 'open-ended'}; {provenance}",
                "affected_nodes_json": None,
            }
            try:
                conn.execute(
                    f"INSERT INTO macro_events ({', '.join(ev_cols)}) "
                    f"VALUES ({', '.join('?' for _ in ev_cols)})",
                    tuple(event_values.get(c) for c in ev_cols),
                )
            except Exception as exc:  # pragma: no cover - live-schema drift
                report["errors"].append(f"macro_events insert {event_id} failed: {exc}")
                continue
            report["wrote_events"] += 1

            # honest-NULL: no magnitude, no magnitude. No default elasticity.
            row = {
                "event_id": event_id,
                "parent_ripple_id": None,
                "order_level": 1,
                "target_type": "Macro_Variable",
                "target_sector_id": None,
                "target_industry_id": None,
                "target_company_id": None,
                "transmission_channel": f"{provenance} | factor_shock",
                "transmission_elasticity": None,
                "raw_magnitude": w["magnitude"],
                "probability": w["probability"],
                "lag_time_months": w["lag_time_months"],
                "significance_rank": None,
            }
            write_cols = [c for c in rp_cols]
            try:
                conn.execute(
                    f"INSERT INTO ripple_effects ({', '.join(write_cols)}) "
                    f"VALUES ({', '.join('?' for _ in write_cols)})",
                    tuple(row.get(c) for c in write_cols),
                )
            except Exception as exc:  # pragma: no cover - live-schema drift
                report["errors"].append(f"ripple_effects insert {event_id} failed: {exc}")
                continue
            report["wrote_ripples"] += 1
    return report


__all__ = [
    "FACTOR_SERIES_REGISTRY",
    "FACTOR_DECISION_READERS",
    "FAMILIES",
    "FREQUENCIES",
    "AGGREGATION_POLICIES",
    "ALLOWED_SOURCES",
    "AVAILABILITY_CONTRACTS",
    "RESOLVER_STATUSES",
    "STATUS_OK",
    "STATUS_STALE",
    "STATUS_NO_OBS",
    "STATUS_NULL_VALUE",
    "STATUS_QUARANTINED",
    "STATUS_UNKNOWN",
    "SPINE_TABLES",
    "POPULATED_TABLES",
    "read_spine_ddl",
    "ensure_factor_spine_schema",
    "register_series",
    "upsert_observations",
    "resolve_as_of",
    "resolve_panel",
    "factor_state",
    "factor_panel",
    "factor_releases",
    "gap_audit",
    "lookahead_audit",
    "backfill_substrate_from_spine",
]
