"""
Factor spine tests (temp DBs only — the live equity_intelligence.db is never opened).

Why these tests exist
---------------------
``tasks/next_wave_plan_2026-09-23.md:176-182`` (§2M) records the failure this
module exists to prevent: backfilled past dates get stamped with *today's*
substrate, so a backtest is really a look-ahead machine wearing a date
header. A resolver that is wrong here does not crash — it returns a
confident, dated, plausible number. So the assertions below are mostly about
what the resolver REFUSES to return:

  * value usable IFF status == 'ok' (never read raw_value as usable)
  * as_of_date <= T is the only knowability predicate
  * is_latest=1 is never a knowability predicate (regression)
  * beyond max_lookback_days the answer is honest NULL, not a stale number
  * a hole in the observations is not bridged
  * exactly one row out, ALWAYS — unknown / quarantined / never-fetched
    series are reported with a status, never dropped and never zero-rowed

Temp-DB discipline
------------------
``reality_engine/data/equity_intelligence.db`` is never opened. Every test
gets a ``NamedTemporaryFile`` DB, and ``setUpModule`` replaces the global
``db_manager`` singleton with a raising stub so that any code path which
falls back to the default manager fails loudly instead of quietly writing
to the live database.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

# Singleton isolation (repo convention: test_onnx_embedder.py:21-24,
# test_offer_backfill.py:21-24, test_filing_ingestion.py:30-33, ...).
# reality_engine/db/database.py:639 runs `db_manager = DatabaseManager()` at
# IMPORT time, and DatabaseManager.__init__ -> init_db() applies PRAGMAs and
# CREATE TABLE IF NOT EXISTS (database.py:94, :635) to config.DB_PATH. Without
# this redirect, merely importing reality_engine.db.database below writes to the
# live reality_engine/data/equity_intelligence.db -- setUpModule's stub is too
# late, it runs after the import-time write has already happened.
_TEMP_DB_DIR = tempfile.mkdtemp(prefix="reality_factor_spine_test_db_")
os.environ.setdefault(
    "REALITY_ENGINE_DB_PATH", str(Path(_TEMP_DB_DIR) / "singleton_isolated.db")
)

from reality_engine.db import database as _database_module
from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing import factor_spine
from reality_engine.processing.factor_spine import (
    STATUS_NO_OBS,
    STATUS_OK,
    STATUS_QUARANTINED,
    STATUS_STALE,
    STATUS_UNKNOWN,
    SPINE_TABLES,
    backfill_substrate_from_spine,
    ensure_factor_spine_schema,
    factor_releases,
    gap_audit,
    lookahead_audit,
    register_series,
    resolve_as_of,
    resolve_panel,
    upsert_observations,
)


# --------------------------------------------------------------------------
# Module-level live-DB guard
# --------------------------------------------------------------------------
class _ForbiddenLiveDB:
    """Stands in for the global db_manager. Any use is a test bug."""

    def session(self):  # pragma: no cover - only runs if a path regresses
        raise AssertionError(
            "factor spine test touched the default db_manager — the live "
            "reality_engine/data/equity_intelligence.db must never be opened"
        )


_REAL_DB_MANAGER = None


def setUpModule():
    global _REAL_DB_MANAGER
    _REAL_DB_MANAGER = _database_module.db_manager
    _database_module.db_manager = _ForbiddenLiveDB()


def tearDownModule():
    if _REAL_DB_MANAGER is not None:
        _database_module.db_manager = _REAL_DB_MANAGER


# --------------------------------------------------------------------------
# Fixture helpers
# --------------------------------------------------------------------------
def _mk_mgr():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    mgr = DatabaseManager(Path(tmp.name))
    return mgr, tmp.name


def _entry(
    key: str,
    *,
    display: str = "test series",
    family: str = "rates_credit",
    frequency: str = "irregular",
    policy: str = "lvcf",
    lookback: int = 45,
    status: str = "active",
    unit: str = "pct",
) -> dict:
    return dict(
        factor_key=key,
        display_name=display,
        family=family,
        unit=unit,
        frequency=frequency,
        value_semantics="level",
        source="fixture",
        source_url="https://example.invalid/fixture",
        license="test fixture; not redistributable",
        current_status=status,
        aggregation_policy=policy,
        max_lookback_days=lookback,
        expected_publication_lag_days=0,
        is_point_in_time=1,
        availability_contract="pita_strict",
        methodology_notes="synthetic fixture series for test_factor_spine",
    )


def _obs(period: str, value, as_of: str, vintage: int = 1) -> dict:
    return {
        "period_start": period,
        "period_end": period,
        "value": value,
        "as_of_date": as_of,
        "vintage": vintage,
        "source": "fixture",
    }


# The design-doc seed (tasks/FACTOR_SPINE_DESIGN_2026-09-29.md:466-477):
# a step-function repo rate plus a v2 restatement that was not public until
# 2026-08-01. max_lookback_days = 45.
REPO = "IN.RBI.REPO_RATE"
GAPPY = "IN.TEST.GAPPY"
REVISED = "IN.TEST.REVISED"
QUARANTINED = "IN.TEST.QUARANTINED"
RETIRED = "IN.TEST.RETIRED"
NEVER_FETCHED = "IN.TEST.NEVER_FETCHED"
SHOCK = "IN.TEST.SHOCK"
FUTURE_ONLY = "IN.TEST.FUTURE_ONLY"


class _Base(unittest.TestCase):
    """Fresh temp DB, spine DDL applied, the design seed written."""

    seed = True

    def setUp(self):
        self.mgr, self._path = _mk_mgr()
        self.addCleanup(self._drop_db)
        ensure_factor_spine_schema(self.mgr)
        register_series(self.mgr, [
            _entry(REPO, display="RBI policy repo rate"),
            _entry(GAPPY, display="series with a hole in its observations",
                   policy="lvcf", lookback=5),
            _entry(REVISED, display="restated series", lookback=400),
            _entry(QUARANTINED, display="quarantined series"),
            _entry(RETIRED, display="deprecated series", status="deprecated"),
            _entry(NEVER_FETCHED, display="registered but never fetched",
                   frequency="monthly", policy="last", lookback=400),
            _entry(SHOCK, display="shock series", family="policy_budget"),
            _entry(FUTURE_ONLY, display="only row is future-dated", lookback=400),
        ])
        if self.seed:
            # v1 6.25 @ 2023-01-06; 6.50 @ 2023-12-06; 6.50 @ 2024-04-10;
            # restated to 6.75 @ 2024-04-10 but only public from 2026-08-01.
            upsert_observations(self.mgr, REPO, [
                _obs("2023-01-06", 6.25, "2023-01-06"),
                _obs("2023-12-06", 6.50, "2023-12-06"),
                _obs("2024-04-10", 6.50, "2024-04-10", vintage=1),
                _obs("2024-04-10", 6.75, "2026-08-01", vintage=2),
            ])
            # A genuine hole: nothing between 2025-01-01 and 2025-06-01.
            upsert_observations(self.mgr, GAPPY, [
                _obs("2025-01-01", 10.0, "2025-01-01"),
                _obs("2025-06-01", 20.0, "2025-06-01"),
            ])

    def _drop_db(self):
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def _series_id(self, key: str) -> int:
        with self.mgr.session() as conn:
            row = conn.execute(
                "SELECT series_id FROM factor_series WHERE factor_key = ?", (key,)
            ).fetchone()
        self.assertIsNotNone(row, f"{key} not registered")
        return int(row[0])

    def _quarantine_series(self, key: str) -> None:
        sid = self._series_id(key)
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO substrate_quarantine "
                "(rule_id, table_name, row_key, severity, reason) VALUES (?,?,?,?,?)",
                ("test_fixture_series", "factor_series", str(sid), "high",
                 "quarantined by test_factor_spine"),
            )


# --------------------------------------------------------------------------
# 1, 2, 3, 4, 7 — the as-of resolver on the design seed
# --------------------------------------------------------------------------
class TestResolveAsOf(_Base):
    def test_1_known_at_T_returns_value(self):
        row = resolve_as_of(self.mgr, REPO, "2023-01-10")
        self.assertEqual(row["status"], STATUS_OK)
        self.assertTrue(row["value_usable"])
        self.assertAlmostEqual(row["value_usable"], 6.25)
        self.assertEqual(row["period_end"], "2023-01-06")
        self.assertEqual(row["vintage"], 1)
        self.assertEqual(row["age_days"], 4)
        self.assertEqual(row["max_lookback_days"], 45)

    def test_2_before_as_of_date_is_no_observation_never_the_value(self):
        # T precedes the FIRST observation's as_of_date, so nothing at all is
        # knowable: the answer is "no observation known at T", not a number.
        row = resolve_as_of(self.mgr, REPO, "2022-12-01")
        self.assertEqual(row["status"], STATUS_NO_OBS)
        self.assertFalse(row["value_usable"])
        self.assertIsNone(row["value_usable"])
        self.assertIsNone(row["observation_id"])
        self.assertIsNone(row["period_end"])
        # None of the four known values leaked in.
        for leaked in (6.25, 6.50, 6.75):
            self.assertNotEqual(row["raw_value"], leaked)

    def test_2b_a_later_period_is_not_visible_before_its_as_of_date(self):
        # At T=2023-06-01 the 2023-12-06 value is NOT yet public. What IS
        # knowable (6.25 @ 2023-01-06) is 116 days stale, so it is withheld —
        # the not-yet-public 6.50 must not be substituted for the stale one.
        row = resolve_as_of(self.mgr, REPO, "2023-06-01")
        self.assertEqual(row["status"], STATUS_STALE)
        self.assertIsNone(row["value_usable"])
        # raw_value is diagnostic only; it stays the STALE value, never the future.
        self.assertEqual(row["raw_value"], 6.25)
        self.assertNotEqual(row["raw_value"], 6.50)
        # Tighten the ceiling to zero and the answer must go unusable, not
        # the not-yet-public 6.50. R8: an override only *tightens* the
        # ceiling, MIN(45, 0) = 0. An observation that IS known at T stays
        # STALE under that ceiling -- NO_OBS is reserved for a series with
        # no known observation at all (design 2.3 CASE order, R6/R10).
        no_fresh = resolve_as_of(self.mgr, REPO, "2023-06-01",
                                max_lookback_override_days=0)
        self.assertEqual(no_fresh["status"], STATUS_STALE)
        self.assertIsNone(no_fresh["value_usable"])
        # The guard that actually matters: the not-yet-public 6.50 must not
        # surface, as the usable value or as the diagnostic raw_value.
        self.assertNotEqual(no_fresh["raw_value"], 6.50)
        self.assertEqual(no_fresh["raw_value"], 6.25)
        self.assertEqual(no_fresh["max_lookback_days"], 0)

    def test_3_lvcf_carries_the_step_function_forward(self):
        early = resolve_as_of(self.mgr, REPO, "2023-01-10")
        later = resolve_as_of(self.mgr, REPO, "2023-01-20")
        # Same observation, carried: only age_days moves.
        self.assertEqual(later["observation_id"], early["observation_id"])
        self.assertEqual(later["status"], STATUS_OK)
        self.assertAlmostEqual(later["value_usable"], 6.25)
        self.assertEqual(later["period_end"], "2023-01-06")
        self.assertEqual(later["age_days"], 14)

    def test_4_stale_beyond_max_lookback_is_honest_null(self):
        row = resolve_as_of(self.mgr, REPO, "2023-03-01")
        self.assertEqual(row["status"], STATUS_STALE)
        self.assertEqual(row["age_days"], 54)
        self.assertGreater(row["age_days"], row["max_lookback_days"])
        # Honest NULL, not a stale number and not an interpolated one.
        self.assertIsNone(row["value_usable"])
        self.assertFalse(row["value_usable"])
        # raw_value is exposed for diagnosis only; it is not usable.
        self.assertEqual(row["raw_value"], 6.25)

    def test_4b_tightening_override_can_only_shorten_the_ceiling(self):
        # MIN(series 45, override 5): inside 5 days is ok, 6 days is stale.
        self.assertEqual(
            resolve_as_of(self.mgr, REPO, "2023-01-10",
                          max_lookback_override_days=5)["status"], STATUS_OK)
        stale = resolve_as_of(self.mgr, REPO, "2023-01-12",
                              max_lookback_override_days=5)
        self.assertEqual(stale["status"], STATUS_STALE)
        self.assertIsNone(stale["value_usable"])
        # A loosening override must NOT rescue it: effective ceiling is MIN(...).
        loose = resolve_as_of(self.mgr, REPO, "2023-03-01",
                              max_lookback_override_days=9999)
        self.assertEqual(loose["status"], STATUS_STALE)
        self.assertEqual(loose["max_lookback_days"], 45)

    def test_7_regression_is_latest_is_never_a_knowability_predicate(self):
        # The loader stamps is_latest=1 on the newest vintage, whose as_of_date
        # is 2026-08-01. A resolver that filtered on is_latest would return the
        # RESTATED value at a T long before the restatement was public.
        with self.mgr.session() as conn:
            flags = {
                int(r[0]): int(r[1])
                for r in conn.execute(
                    "SELECT observation_id, is_latest FROM factor_observation "
                    "WHERE series_id = ?", (self._series_id(REPO),)
                ).fetchall()
            }
        self.assertIn(1, flags.values(), "seed should carry an is_latest=1 row")
        self.assertIn(0, flags.values(), "seed should carry an is_latest=0 row")

        row = resolve_as_of(self.mgr, REPO, "2024-04-10")
        self.assertEqual(row["status"], STATUS_OK)
        self.assertAlmostEqual(row["value_usable"], 6.50)
        self.assertEqual(row["vintage"], 1, "the not-yet-public v2 leaked into the read")
        self.assertIsNone(
            next((v for v in (row["raw_value"], row["value_usable"]) if v == 6.75), None),
            "6.75 was not public on 2024-04-10",
        )

    def test_7b_is_latest_1_on_a_future_row_yields_no_observation(self):
        # Sharpest form: the series' ONLY row is is_latest=1 with a future
        # as_of_date. At an earlier T the honest answer is "nothing known",
        # not the number is_latest=1 promises.
        sid = self._series_id(FUTURE_ONLY)
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO factor_observation (series_id, period_start, period_end,"
                " value, unit, as_of_date, retrieved_at, source, vintage, is_latest)"
                " VALUES (?,?,?,?,?,?,?,?,1,1)",
                (sid, "2026-01-01", "2026-01-01", 99.0, "pct", "2026-09-01",
                 "2026-09-01 10:00:00", "fixture"),
            )
        row = resolve_as_of(self.mgr, FUTURE_ONLY, "2026-03-01")
        self.assertEqual(row["status"], STATUS_NO_OBS)
        self.assertIsNone(row["value_usable"])
        # The same row IS visible once its as_of_date has passed.
        later = resolve_as_of(self.mgr, FUTURE_ONLY, "2026-09-15")
        self.assertEqual(later["status"], STATUS_OK)
        self.assertAlmostEqual(later["value_usable"], 99.0)


# --------------------------------------------------------------------------
# 5 — a genuine hole is not bridged
# --------------------------------------------------------------------------
class TestGapIsNotBridged(_Base):
    seed = False

    def setUp(self):
        super().setUp()
        upsert_observations(self.mgr, GAPPY, [
            _obs("2025-01-01", 10.0, "2025-01-01"),
            _obs("2025-06-01", 20.0, "2025-06-01"),
        ])

    def test_5_value_before_the_hole_is_fresh(self):
        row = resolve_as_of(self.mgr, GAPPY, "2025-01-03")
        self.assertEqual(row["status"], STATUS_OK)
        self.assertAlmostEqual(row["value_usable"], 10.0)

    def test_5_the_hole_is_not_forward_filled(self):
        # 2025-03-01 sits inside a 151-day hole, 59 days past the last
        # observation. max_lookback_days = 5, so the carry stops well before
        # the hole is even half-covered.
        row = resolve_as_of(self.mgr, GAPPY, "2025-03-01")
        self.assertEqual(row["status"], STATUS_STALE)
        self.assertIsNone(row["value_usable"])
        self.assertEqual(row["period_end"], "2025-01-01")
        self.assertEqual(row["age_days"], 59)

    def test_5_gap_audit_shows_the_hole(self):
        rows = gap_audit(self.mgr, GAPPY, "2025-07-01")
        self.assertEqual([r["period_end"] for r in rows],
                         ["2025-01-01", "2025-06-01"])
        self.assertIsNone(rows[0]["gap_days"])
        self.assertEqual(rows[1]["gap_days"], 151)
        self.assertEqual(rows[1]["prev_period_end"], "2025-01-01")


# --------------------------------------------------------------------------
# 6 — the revision chain
# --------------------------------------------------------------------------
class TestRevisionChain(_Base):
    seed = False

    def setUp(self):
        super().setUp()
        upsert_observations(self.mgr, REVISED, [
            _obs("2024-04-10", 6.50, "2024-04-10", vintage=1),
            _obs("2024-04-10", 6.75, "2024-04-20", vintage=2),
        ])

    def test_6_only_the_public_vintage_is_visible_at_each_T(self):
        before = resolve_as_of(self.mgr, REVISED, "2024-04-10")
        self.assertEqual(before["vintage"], 1)
        self.assertEqual(before["status"], STATUS_OK)
        self.assertAlmostEqual(before["value_usable"], 6.50)

        after = resolve_as_of(self.mgr, REVISED, "2024-04-20")
        self.assertEqual(after["vintage"], 2)
        self.assertEqual(after["status"], STATUS_OK)
        self.assertAlmostEqual(after["value_usable"], 6.75)
        # Same period, different vintage: the revision replaced the value in
        # place rather than appending a competing period.
        self.assertEqual(after["period_end"], before["period_end"])
        self.assertNotEqual(after["observation_id"], before["observation_id"])

    def test_6b_midway_between_release_and_public_date_is_still_v1(self):
        mid = resolve_as_of(self.mgr, REVISED, "2024-04-19")
        self.assertEqual(mid["vintage"], 1)
        self.assertAlmostEqual(mid["value_usable"], 6.50)

    def test_6c_v2_links_back_to_v1(self):
        with self.mgr.session() as conn:
            rows = conn.execute(
                "SELECT observation_id, revision_of FROM factor_observation "
                "WHERE series_id = ? ORDER BY vintage", (self._series_id(REVISED),)
            ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0]["revision_of"])
        self.assertEqual(int(rows[1]["revision_of"]), int(rows[0]["observation_id"]))


# --------------------------------------------------------------------------
# 8, 9 — refusals. Exactly one row, always.
# --------------------------------------------------------------------------
class TestRefusals(_Base):
    def test_8_quarantined_series_returns_one_row_with_a_status(self):
        self._quarantine_series(QUARANTINED)
        row = resolve_as_of(self.mgr, QUARANTINED, "2023-02-01")
        self.assertEqual(row["status"], STATUS_QUARANTINED)
        self.assertNotEqual(row["status"], STATUS_OK)
        self.assertIsNone(row["value_usable"])

    def test_8b_quarantine_refuses_the_whole_series_not_just_the_bad_row(self):
        # Even at a T where a perfectly good observation exists, the SERIES is
        # refused. Degrading to "the last value before the bad row" is exactly
        # how a quarantined row becomes a confident wrong answer.
        upsert_observations(self.mgr, QUARANTINED, [_obs("2023-01-06", 4.0, "2023-01-06")])
        self.assertEqual(resolve_as_of(self.mgr, QUARANTINED, "2023-01-07")["status"],
                         STATUS_OK)
        self._quarantine_series(QUARANTINED)
        row = resolve_as_of(self.mgr, QUARANTINED, "2023-01-07")
        self.assertEqual(row["status"], STATUS_QUARANTINED)
        self.assertIsNone(row["value_usable"])

    def test_8c_inactive_series_is_refused_the_same_way(self):
        row = resolve_as_of(self.mgr, RETIRED, "2023-02-01")
        self.assertEqual(row["status"], STATUS_QUARANTINED)
        self.assertIsNone(row["value_usable"])

    def test_8d_never_fetched_series_is_no_observation_not_a_dropped_row(self):
        row = resolve_as_of(self.mgr, NEVER_FETCHED, "2023-01-01")
        self.assertEqual(row["status"], STATUS_NO_OBS)
        self.assertIsNone(row["value_usable"])

    def test_9_unknown_series_key_returns_exactly_one_row(self):
        row = resolve_as_of(self.mgr, "IN.NOPE.MISSING", "2023-01-01")
        self.assertEqual(row["status"], STATUS_UNKNOWN)
        self.assertIsNone(row["value_usable"])
        self.assertEqual(row["factor_key"], "IN.NOPE.MISSING")

    def test_9b_unknown_series_id_int_also_returns_one_row(self):
        row = resolve_as_of(self.mgr, 999999, "2023-01-01")
        self.assertEqual(row["status"], STATUS_UNKNOWN)
        self.assertIsNone(row["value_usable"])

    def test_as_of_date_is_required(self):
        with self.assertRaises(ValueError):
            resolve_as_of(self.mgr, REPO, "")


# --------------------------------------------------------------------------
# 10 — the panel reader
# --------------------------------------------------------------------------
class TestResolvePanel(_Base):
    def test_10_one_row_per_requested_key_including_unknown(self):
        requested = [REPO, GAPPY, NEVER_FETCHED, "IN.NOPE.MISSING", "IN.NOPE.OTHER"]
        rows = resolve_panel(self.mgr, "2023-03-01", requested)
        self.assertEqual(len(rows), len(requested))
        self.assertEqual([r["factor_key"] for r in rows], requested)
        self.assertEqual(len({r["factor_key"] for r in rows}), len(requested))

    def test_10b_panel_applies_the_staleness_gate(self):
        # REPO's 54-day-stale value must be withheld, not returned.
        rows = resolve_panel(self.mgr, "2023-03-01", [REPO, NEVER_FETCHED])
        by_key = {r["factor_key"]: r for r in rows}
        repo_row = by_key[REPO]
        self.assertEqual(repo_row["status"], STATUS_STALE)
        self.assertEqual(repo_row["age_days"], 54)
        self.assertIsNone(repo_row["value_usable"])
        self.assertFalse(repo_row["value_usable"])
        self.assertEqual(by_key[NEVER_FETCHED]["status"], STATUS_NO_OBS)
        self.assertIsNone(by_key[NEVER_FETCHED]["value_usable"])

    def test_10c_panel_reports_quarantined_and_unknown_rather_than_dropping(self):
        self._quarantine_series(QUARANTINED)
        requested = [QUARANTINED, RETIRED, "IN.NOPE.MISSING"]
        rows = resolve_panel(self.mgr, "2023-03-01", requested)
        self.assertEqual([r["factor_key"] for r in rows], requested)
        self.assertEqual(rows[0]["status"], STATUS_QUARANTINED)
        self.assertEqual(rows[1]["status"], STATUS_QUARANTINED)
        self.assertEqual(rows[2]["status"], STATUS_UNKNOWN)
        for r in rows:
            self.assertIsNone(r["value_usable"])

    def test_10d_panel_matches_single_series_reads(self):
        requested = [REPO, GAPPY, QUARANTINED, "IN.NOPE.MISSING"]
        for t in ("2023-01-10", "2023-03-01", "2024-04-10", "2026-08-02"):
            panel = {r["factor_key"]: r for r in
                     resolve_panel(self.mgr, t, requested)}
            self.assertEqual(set(panel), set(requested), t)
            for key in requested:
                single = resolve_as_of(self.mgr, key, t)
                self.assertEqual(panel[key]["status"], single["status"],
                                 f"{key}@{t}: panel and single read disagree")
                self.assertEqual(panel[key]["value_usable"], single["value_usable"],
                                 f"{key}@{t}: panel and single read disagree")
                self.assertEqual(panel[key]["vintage"], single["vintage"],
                                 f"{key}@{t}: panel and single read disagree")

    def test_10e_panel_default_covers_every_registered_series(self):
        rows = resolve_panel(self.mgr, "2023-03-01")
        with self.mgr.session() as conn:
            registered = [r[0] for r in conn.execute(
                "SELECT factor_key FROM factor_series ORDER BY family, factor_key").fetchall()]
        self.assertEqual(len(rows), len(registered))
        self.assertEqual(sorted(r["factor_key"] for r in rows), sorted(registered))
        self.assertTrue(all(r["status"] in factor_spine.RESOLVER_STATUSES for r in rows))

    def test_10f_empty_key_list_returns_empty_not_everything(self):
        self.assertEqual(resolve_panel(self.mgr, "2023-03-01", []), [])


# --------------------------------------------------------------------------
# 11 — the release view
# --------------------------------------------------------------------------
class TestFactorReleases(_Base):
    def test_11a_past_T_hides_a_later_restatement(self):
        rows = factor_releases(self.mgr, "2024-04-10", [REPO])
        self.assertEqual([(r["period_end"], r["vintage"]) for r in rows],
                         [("2023-01-06", 1), ("2023-12-06", 1), ("2024-04-10", 1)])
        self.assertNotIn(6.75, [r["value"] for r in rows])
        self.assertTrue(all(r["is_revision"] == 0 for r in rows))

    def test_11b_later_T_reveals_both_vintles(self):
        rows = factor_releases(self.mgr, "2026-08-02", [REPO])
        v2 = [r for r in rows if r["vintage"] == 2]
        self.assertEqual(len(v2), 1)
        self.assertAlmostEqual(v2[0]["value"], 6.75)
        self.assertEqual(v2[0]["as_of_date"], "2026-08-01")
        self.assertEqual(v2[0]["is_revision"], 1)
        # The superseded release is still visible — releases are history, not state.
        self.assertIn(1, [r["vintage"] for r in rows])

    def test_11c_releases_report_is_latest_without_filtering_on_it(self):
        rows = factor_releases(self.mgr, "2024-04-10", [REPO])
        self.assertTrue(any(r["is_latest"] == 0 for r in rows),
                        "is_latest=0 rows must be REPORTED, not hidden")
        # Releases are deliberately un-gated on staleness: the 2023-01-06 value
        # is long stale but it is what existed on T.
        self.assertEqual(rows[0]["period_end"], "2023-01-06")


# --------------------------------------------------------------------------
# 12 — the audits
# --------------------------------------------------------------------------
class TestAudits(_Base):
    def test_12a_lookahead_audit_is_zero_and_non_vacuous(self):
        rep = lookahead_audit(self.mgr, REPO, "2024-04-10")
        self.assertEqual(rep["lookahead_violations"], 0)
        # Non-vacuous: the table DOES contain a future-dated row the gate
        # excluded (the 2026-08-01 restatement), so the 0 is a real assertion.
        self.assertEqual(rep["future_dated_rows_in_table"], 1)
        self.assertFalse(rep["is_vacuous"])
        self.assertGreater(rep["future_dated_rows_in_table"], 0)

    def test_12b_lookahead_audit_declares_vacuity_when_nothing_is_at_risk(self):
        rep = lookahead_audit(self.mgr, GAPPY, "2025-07-01")
        self.assertEqual(rep["lookahead_violations"], 0)
        self.assertEqual(rep["future_dated_rows_in_table"], 0)
        self.assertTrue(rep["is_vacuous"],
                        "a 0 with nothing to exclude proves nothing and must say so")

    def test_12c_lookahead_audit_on_unknown_series_is_explicitly_vacuous(self):
        rep = lookahead_audit(self.mgr, "IN.NOPE.MISSING", "2024-04-10")
        self.assertEqual(rep["lookahead_violations"], 0)
        self.assertTrue(rep["is_vacuous"])
        self.assertIn("unknown series", rep["note"])

    def test_12d_the_resolver_never_returns_a_row_newer_than_T(self):
        # The real assertion the guard stands in for: sweep every date in the
        # seed and assert the resolver's own answer never carries an
        # as_of_date later than the T it was asked about.
        series = [REPO, GAPPY, REVISED, NEVER_FETCHED, QUARANTINED, "IN.NOPE.MISSING"]
        for t in ("2022-12-01", "2023-01-06", "2023-01-07", "2023-06-01",
                  "2024-04-09", "2024-04-10", "2024-04-19", "2024-04-20",
                  "2025-03-01", "2026-08-01", "2026-08-02"):
            for row in resolve_panel(self.mgr, t, series):
                if row["as_of_date"] is not None:
                    self.assertLessEqual(row["as_of_date"], t,
                                         f"{row['factor_key']}@{t} leaked a future row")
                if row["period_end"] is not None:
                    # period_end may legitimately exceed T only when the whole
                    # period was announced in advance; it is never a gate.
                    self.assertIsNotNone(row["status"])

    def test_12e_lookahead_audit_matches_the_design_seed(self):
        # tasks/FACTOR_SPINE_DESIGN_2026-09-29.md:593 — "On the verified seed
        # at T=2024-04-10, the guard returns 0 while the table holds 1
        # observation with as_of_date > T."
        rep = lookahead_audit(self.mgr, REPO, "2024-04-10")
        self.assertEqual(rep["lookahead_violations"], 0)
        self.assertEqual(rep["future_dated_rows_in_table"], 1)
        self.assertFalse(rep["is_vacuous"])

    def test_12f_gap_audit_reports_gap_days_and_dedupes_the_version_chain(self):
        rows = gap_audit(self.mgr, REPO, "2026-08-02")
        # 3 periods, not 4: the v1/v2 pair is deduplicated to the latest known
        # vintage, so the version chain does not appear as a bogus gap_days = 0.
        self.assertEqual([r["period_end"] for r in rows],
                         ["2023-01-06", "2023-12-06", "2024-04-10"])
        self.assertIsNone(rows[0]["gap_days"])
        self.assertEqual(rows[1]["gap_days"], 334)
        self.assertEqual(rows[2]["gap_days"], 126)
        self.assertEqual(rows[2]["vintage"], 2)
        self.assertNotIn(0, [r["gap_days"] for r in rows])

    def test_12g_gap_audit_is_point_in_time(self):
        before = gap_audit(self.mgr, REPO, "2024-04-09")
        self.assertEqual([r["period_end"] for r in before],
                         ["2023-01-06", "2023-12-06"])
        after = gap_audit(self.mgr, REPO, "2024-04-10")
        self.assertEqual(len(after), 3)


# --------------------------------------------------------------------------
# 13 — the substrate backfill: opt-in, dry-run by default, no invented numbers
# --------------------------------------------------------------------------
class TestBackfillSubstrate(_Base):
    def setUp(self):
        super().setUp()
        from reality_engine.processing.pruning_engine import ensure_pruning_schema

        ensure_pruning_schema(self.mgr)  # ripple_effects is not in schema.sql
        sid = self._series_id(SHOCK)
        with self.mgr.session() as conn:
            # w1: announced, effect window opened, magnitude NOT quantified.
            conn.execute(
                "INSERT INTO factor_event_window (series_id, event_label, announced_date,"
                " window_start, magnitude, direction, lag_time_months, probability,"
                " as_of_date, vintage, is_latest, source)"
                " VALUES (?,?,?,?,NULL,NULL,NULL,NULL,?,1,1,'fixture')",
                (sid, "FY26 Rail Capex provision", "2026-02-01", "2026-04-01", "2026-02-01"),
            )
            # w2: quantified.
            conn.execute(
                "INSERT INTO factor_event_window (series_id, event_label, announced_date,"
                " window_start, magnitude, direction, lag_time_months, probability,"
                " as_of_date, vintage, is_latest, source)"
                " VALUES (?,?,?,?,?,?,?,?,?,1,1,'fixture')",
                (sid, "Reserve Bank liquidity squeeze", "2026-03-01", "2026-03-15",
                 2.5, -1, 2, 0.7, "2026-03-01"),
            )

    def _counts(self):
        with self.mgr.session() as conn:
            ev = conn.execute("SELECT COUNT(*) FROM macro_events").fetchone()[0]
            rp = conn.execute("SELECT COUNT(*) FROM ripple_effects").fetchone()[0]
        return int(ev), int(rp)

    def test_13a_dry_run_by_default_writes_nothing(self):
        before = self._counts()
        rep = backfill_substrate_from_spine(self.mgr, asof_date="2026-05-01")
        self.assertTrue(rep["dry_run"])
        self.assertEqual(rep["candidates"], 2)
        self.assertEqual(rep["would_write_events"], 2)
        self.assertEqual(rep["would_write_ripples"], 2)
        self.assertEqual(rep["wrote_events"], 0)
        self.assertEqual(rep["wrote_ripples"], 0)
        self.assertEqual(rep["errors"], [])
        self.assertEqual(self._counts(), before, "a default (dry-run) call wrote to the substrate")

    def test_13b_explicit_write_creates_rows_with_provenance(self):
        rep = backfill_substrate_from_spine(self.mgr, asof_date="2026-05-01", dry_run=False)
        self.assertEqual(rep["wrote_events"], 2)
        self.assertEqual(rep["wrote_ripples"], 2)
        with self.mgr.session() as conn:
            row = conn.execute(
                "SELECT transmission_channel FROM ripple_effects WHERE event_id = ?",
                ("FEW_1",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertIn("source_series_id=", row[0])
        self.assertIn("source_observation_id=1", row[0])
        self.assertIn(SHOCK, row[0])

    def test_13c_unquantified_shock_stays_null_never_a_default(self):
        backfill_substrate_from_spine(self.mgr, asof_date="2026-05-01", dry_run=False)
        with self.mgr.session() as conn:
            row = conn.execute(
                "SELECT raw_magnitude, transmission_elasticity, probability "
                "FROM ripple_effects WHERE event_id = ?", ("FEW_1",)
            ).fetchone()
        # ripple_effects.transmission_elasticity has DEFAULT 1.0. The spine
        # must not inherit that constant (design D1), and an unquantified
        # shock must not become 0.0.
        self.assertIsNone(row["raw_magnitude"])
        self.assertIsNone(row["transmission_elasticity"])
        self.assertIsNone(row["probability"])
        # The quantified window, by contrast, is carried through verbatim.
        with self.mgr.session() as conn:
            q = conn.execute(
                "SELECT raw_magnitude, transmission_elasticity, probability "
                "FROM ripple_effects WHERE event_id = ?", ("FEW_2",)
            ).fetchone()
        self.assertAlmostEqual(q["raw_magnitude"], 2.5)
        self.assertAlmostEqual(q["probability"], 0.7)
        self.assertIsNone(q["transmission_elasticity"])

    def test_13d_backfill_is_idempotent_and_never_modifies_existing_rows(self):
        backfill_substrate_from_spine(self.mgr, asof_date="2026-05-01", dry_run=False)
        counts = self._counts()
        with self.mgr.session() as conn:
            before = [dict(r) for r in conn.execute(
                "SELECT * FROM macro_events ORDER BY event_id").fetchall()]
        again = backfill_substrate_from_spine(self.mgr, asof_date="2026-05-01", dry_run=False)
        self.assertEqual(again["wrote_events"], 0)
        self.assertEqual(again["wrote_ripples"], 0)
        self.assertEqual(again["skipped_existing"], 2)
        self.assertEqual(self._counts(), counts)
        with self.mgr.session() as conn:
            after = [dict(r) for r in conn.execute(
                "SELECT * FROM macro_events ORDER BY event_id").fetchall()]
        self.assertEqual(before, after)

    def test_13e_horizon_is_respected(self):
        rep = backfill_substrate_from_spine(self.mgr, asof_date="2026-02-15")
        self.assertEqual(rep["candidates"], 1)  # only the 2026-02-01 window is public

    def test_13f_missing_target_tables_is_an_error_not_a_crash(self):
        with self.mgr.session() as conn:
            conn.execute("DROP TABLE ripple_effects")
        rep = backfill_substrate_from_spine(self.mgr, asof_date="2026-05-01", dry_run=False)
        self.assertTrue(any("ripple_effects" in e for e in rep["errors"]))
        self.assertEqual(rep["wrote_events"], 0)


# --------------------------------------------------------------------------
# 14 — schema idempotency and the NOT NULL ceiling
# --------------------------------------------------------------------------
class TestSchemaContract(unittest.TestCase):
    def setUp(self):
        self.mgr, self._path = _mk_mgr()
        self.addCleanup(self._drop_db)
        # The spine DDL must exist before any test here touches factor_series:
        # test_14d/test_14e call register_series() directly, and the repo
        # accessor is idempotent over it. Mirrors _Base.setUp.
        ensure_factor_spine_schema(self.mgr)

    def _drop_db(self):
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def test_14a_ensure_is_idempotent(self):
        for _ in range(3):
            ensure_factor_spine_schema(self.mgr)  # raises nothing
        with self.mgr.session() as conn:
            names = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for t in SPINE_TABLES:
            self.assertIn(t, names)
        # The quarantine table the resolver's predicate reads must exist too.
        self.assertIn("substrate_quarantine", names)

    def test_14b_repository_accessor_is_idempotent(self):
        repo = Repository(self.mgr)
        repo.ensure_factor_spine_schema()
        repo.ensure_factor_spine_schema()
        repo.register_factor_series()
        self.assertEqual(repo.register_factor_series(), 0)  # already registered
        self.assertEqual(repo.resolve_factor_as_of(REPO, "2023-01-01")["status"],
                         STATUS_NO_OBS)

    def test_14c_max_lookback_days_is_not_null_at_the_sqlite_level(self):
        ensure_factor_spine_schema(self.mgr)
        with self.mgr.session() as conn:
            cols = {r[1]: r for r in conn.execute(
                "PRAGMA table_info(factor_series)").fetchall()}
        self.assertIn("max_lookback_days", cols)
        # notnull flag is column index 3 in PRAGMA table_info.
        self.assertEqual(cols["max_lookback_days"][3], 1,
                         "max_lookback_days must be NOT NULL: a series may not "
                         "claim 'always fresh'")
        self.assertEqual(cols["max_lookback_days"][2].upper(), "INTEGER")

    def test_14d_a_series_cannot_be_registered_without_a_lookback_ceiling(self):
        register_series(self.mgr, [_entry(REPO)])
        entry = _entry("IN.TEST.NO_CEILING")
        entry["max_lookback_days"] = None
        with self.assertRaises(ValueError):
            register_series(self.mgr, [entry])
        # And the DDL refuses it too, not just the Python validator.
        with self.assertRaises(sqlite3.IntegrityError):
            with self.mgr.session() as conn:
                conn.execute(
                    "INSERT INTO factor_series (factor_key, family, unit, frequency,"
                    " value_semantics, source, max_lookback_days) "
                    "VALUES ('IN.TEST.NULL_CEILING','rates_credit','pct','irregular',"
                    "'level','fixture',NULL)")

    def test_14e_future_dated_observation_is_refused_at_load_time(self):
        register_series(self.mgr, [_entry(REPO)])
        with self.assertRaises(ValueError):
            upsert_observations(self.mgr, REPO,
                                [_obs("2099-01-01", 1.0, "2099-01-01")])

    def test_14f_ddl_file_is_shipped_and_re_read_not_hardcoded(self):
        ddl = factor_spine.read_spine_ddl()
        self.assertIn("CREATE TABLE IF NOT EXISTS factor_observation", ddl)
        self.assertIn("CREATE TABLE IF NOT EXISTS factor_series", ddl)
        # factor_symbol_link is specified but deliberately unpopulated.
        self.assertIn("factor_symbol_link", factor_spine.SPINE_TABLES)
        self.assertNotIn("factor_symbol_link", factor_spine.POPULATED_TABLES)


# --------------------------------------------------------------------------
# Source-level guard on the decision readers (design §2.8)
# --------------------------------------------------------------------------
class TestDecisionReaderShape(unittest.TestCase):
    """The failure guarded is a SHAPE of the query, not a value, so the guard
    is source-level: the decision readers' SQL must contain the as_of_date gate
    and none of the other look-ahead handles."""

    #: Decision-path SQL, as written. Both templates are the only temporal
    #: predicate surface a decision reader has.
    _TEMPLATES = ("_STATE_SQL_TEMPLATE", "_PANEL_SQL_TEMPLATE")

    def test_decision_readers_are_the_documented_pair(self):
        self.assertEqual(set(factor_spine.FACTOR_DECISION_READERS),
                         {resolve_as_of, resolve_panel})

    def test_decision_sql_has_exactly_one_temporal_gate(self):
        for name in self._TEMPLATES:
            sql = getattr(factor_spine, name)
            self.assertIn("o.as_of_date <=", sql,
                          f"{name}: the as_of_date gate is missing entirely")
            for forbidden in (
                "o.is_latest",          # R5: display/audit only
                "o.retrieved_at <=",    # R3: fetch time is never a read predicate
                "o.period_end <=",      # R2: period_end is never a visibility gate
                "CURRENT_DATE",
                "date('now')",
                "datetime('now')",
                "daily_price_delivery",
            ):
                self.assertNotIn(forbidden, sql,
                                 f"{name} reads a forbidden predicate: {forbidden}")

    def test_status_and_value_usable_share_one_expression(self):
        # value_usable is nulled by `status`, never recomputed: two copies of
        # the gate is two chances for them to disagree.
        for name in self._TEMPLATES:
            sql = getattr(factor_spine, name)
            self.assertIn("CASE WHEN x.status = 'ok' THEN x.value END AS value_usable", sql)
            self.assertEqual(sql.count("AS status"), 1,
                             f"{name}: the status CASE is written more than once")


if __name__ == "__main__":
    unittest.main()
