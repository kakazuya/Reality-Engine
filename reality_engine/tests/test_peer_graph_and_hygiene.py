"""Isolation tests for the substrate trust layer and the analog peer graph.

Mirrors the repo convention (see tests/test_derived_substrate.py): temp-file
SQLite DB, never the live equity_intelligence.db, deterministic fixture, and
assertions on the contract each module promises to its consumers.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing import peer_graph as pg
from reality_engine.processing import substrate_hygiene as hygiene


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
# Four substrate tables are created at runtime by repository methods rather than
# by schema.sql, so a fresh temp DB lacks them.  Mirrored here (repo convention:
# see tests/test_document_industry_tag.py) with the columns the feature
# extractors read.
_ENSURE_DDL = (
    "CREATE TABLE IF NOT EXISTS business_model_profiles ("
    " company_id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT UNIQUE, archetype TEXT,"
    " revenue_recurrence_pct REAL, pricing_power_score REAL, capital_intensity_score REAL,"
    " operating_leverage_score REAL, qualitative_notes TEXT, updated_at TEXT)",
    "CREATE TABLE IF NOT EXISTS moat_evaluations ("
    " company_id INTEGER PRIMARY KEY, ticker TEXT UNIQUE, eval_date TEXT, switching_costs REAL,"
    " network_effects REAL, cost_advantage REAL, intangible_assets REAL, efficient_scale REAL,"
    " total_moat_score REAL, moat_width TEXT, moat_trajectory TEXT, isin TEXT)",
    "CREATE TABLE IF NOT EXISTS geographic_exposure ("
    " company_id INTEGER NOT NULL, country_id TEXT NOT NULL, revenue_share_pct REAL,"
    " asset_exposure_pct REAL, created_at TEXT)",
    "CREATE TABLE IF NOT EXISTS ripple_effects ("
    " ripple_id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT, parent_ripple_id INTEGER,"
    " order_level INTEGER, target_type TEXT, target_sector_id TEXT, target_industry_id TEXT,"
    " target_company_id TEXT, transmission_channel TEXT, transmission_elasticity REAL,"
    " raw_magnitude REAL, probability REAL, lag_time_months INTEGER, significance_rank REAL,"
    " created_at TEXT, revision_count INTEGER, last_revised_at TEXT)",
)


def _seed_substrate(mgr, n_companies: int = 12) -> None:
    """Twelve companies with deliberate variance, plus deliberate degeneracy.

    Constant on purpose (must be gated out):
      * ``stage_conviction`` 0.6 for everyone      -> near_constant
      * ``is_cyclical`` false for everyone         -> near_constant
      * ``altman_z`` 3.0 for everyone              -> constant
      * geographic exposure always 100% India      -> near_constant

    Varied on purpose (must survive):
      * four business-model scores, four moat components, debt/equity,
        market cap, latest-quarter growth and EBITDA margin.
    """
    with mgr.session() as conn:
        # company_distilled_parameters has an FK on parameter_key
        # -> dynamic_parameter_definitions, which is empty in a fresh DB.
        for key, name, category in (
            ("cyclicality_profile", "Cyclicality Profile", "CYCLICALITY"),
            ("business_sensitivities", "Business Sensitivities", "BUSINESS_MODEL"),
        ):
            conn.execute(
                "INSERT OR IGNORE INTO dynamic_parameter_definitions "
                "(parameter_key, display_name, data_type, category) VALUES (?,?,?,?)",
                (key, name, "JSON", category),
            )
        for i in range(n_companies):
            sym = f"CO{i:02d}"
            isin = f"INE{i:04d}B01{i:03d}"
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, company_name, industry, sector, "
                "is_active, is_nifty200) VALUES (?,?,?,?,?,1,1)",
                (isin, sym, f"Company {i}", "Industrials", "Industrials"),
            )
            rowid = conn.execute(
                "SELECT rowid FROM master_companies WHERE nse_symbol = ?", (sym,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO business_model_profiles (company_id, isin, symbol, archetype, "
                "revenue_recurrence_pct, pricing_power_score, capital_intensity_score, "
                "operating_leverage_score) VALUES (?,?,?,?,?,?,?,?)",
                (rowid, isin, sym, "Asset-Heavy OEM", 30.0 + i * 5, 2 + (i % 4), 2 + ((i + 1) % 4),
                 2 + ((i + 2) % 4)),
            )
            conn.execute(
                "INSERT INTO moat_evaluations (company_id, ticker, isin, switching_costs, "
                "network_effects, cost_advantage, intangible_assets, efficient_scale, "
                "total_moat_score, moat_width, moat_trajectory) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (rowid, sym, isin, 1 + (i % 5), 1 + ((i + 1) % 5), 1 + ((i + 2) % 5),
                 2 + (i % 4), 1 + ((i + 3) % 5), 1.0 + 0.3 * (i % 10), "Narrow", "Stable"),
            )
            conn.execute(
                "INSERT INTO company_distilled_parameters (isin, symbol, parameter_key, "
                "value_json, confidence_score, last_updated_date) VALUES (?,?,?,?,?,?)",
                (isin, sym, "cyclicality_profile",
                 json.dumps({"is_cyclical": False, "cycle_duration_years": 7.0,
                             "stage_conviction": 0.6}), 0.5, "2026-09-20"),
            )
            conn.execute(
                "INSERT INTO company_distilled_parameters (isin, symbol, parameter_key, "
                "value_json, confidence_score, last_updated_date) VALUES (?,?,?,?,?,?)",
                (isin, sym, "business_sensitivities",
                 json.dumps({"moat_rating": 4.0, "key_revenue_drivers": ["a"],
                             "raw_material_sensitivities": {"steel": 0.3}}), 0.5, "2026-09-20"),
            )
            conn.execute(
                "INSERT INTO regulatory_political_risks (company_id, ticker, isin, symbol, "
                "policy_name, risk_type, factor_type, severity_score, probability, "
                "net_impact_score, coverage_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (rowid, sym, isin, sym, "TEMPLATE", "Policy", "Macro", 1.0 + (i % 3), 0.5,
                 1.0, "mapped" if i % 3 == 0 else "no_template"),
            )
            conn.execute(
                "INSERT INTO geographic_exposure (company_id, country_id, revenue_share_pct, "
                "asset_exposure_pct) VALUES (?,?,?,?)",
                (rowid, "IND", 100.0, 100.0),
            )
            conn.execute(
                "INSERT INTO company_forensic_health (isin, symbol, fiscal_year, "
                "debt_to_equity_ratio, interest_coverage_ratio, altman_z_score, "
                "market_cap_inr_cr, last_evaluated_date, is_solvency_approved) "
                "VALUES (?,?,?,?,?,?,?,?,1)",
                (isin, sym, "FY26", 0.1 + 0.15 * i, 3.0, 3.0, 1000.0 * (i + 1) ** 2, "2026-09-20"),
            )
            conn.execute(
                "INSERT INTO quarterly_financials (isin, symbol, financial_year, "
                "quarter_end_date, revenue_inr_cr, ebitda_inr_cr, net_profit_inr_cr, "
                "ebitda_margin_pct, yoy_revenue_growth_pct) VALUES (?,?,?,?,?,?,?,?,?)",
                (isin, sym, "FY26", f"2026-{3 + (i % 9):02d}-30", 100.0 + i, 20.0, 10.0,
                 5.0 + i * 2.0, -10.0 + i * 4.0),
            )
            # One contaminated quarter: a 599,921% margin must be rejected, not clipped.
            if i == 0:
                conn.execute(
                    "INSERT INTO quarterly_financials (isin, symbol, financial_year, "
                    "quarter_end_date, revenue_inr_cr, ebitda_margin_pct) VALUES (?,?,?,?,?,?)",
                    (isin, sym, "FY27", "2027-03-31", 100.0, 599921.43),
                )
        # Two deliberate fixture rows that the trust layer must quarantine.
        conn.execute(
            "INSERT INTO graph_nodes (node_id, node_type, name, metadata_json) "
            "VALUES ('TEST_SHOCK_abc','TEST','t','{}')"
        )
        conn.execute(
            "INSERT INTO graph_nodes (node_id, node_type, name, metadata_json) "
            "VALUES ('NODE_REAL_1','COMPANY','real','{}')"
        )
        conn.execute(
            "INSERT INTO graph_causal_edges (edge_id, source_node_id, target_node_id, "
            "relationship_type, impact_direction, transmission_mechanism, confidence_score) "
            "VALUES ('E1','TEST_SHOCK_abc','NODE_REAL_1','CAUSAL','POSITIVE','test',1.0)"
        )
        conn.execute(
            "INSERT INTO macro_events (event_id, event_name, category, event_date, summary) "
            "VALUES ('PHASE5_EVT_RECENT_001','PHASE5_DEMO_RECENT_EVENT','Fiscal','2026-08-01','demo')"
        )
        conn.execute(
            "INSERT INTO ripple_effects (event_id, parent_ripple_id, order_level, target_type, "
            "transmission_channel) VALUES ('PHASE5_EVT_RECENT_001', NULL, 1, NULL, 'demo')"
        )
        # A synthetic-ISIN company that must not enter the peer graph.  It is
        # given real substrate rows so the test proves exclusion rather than
        # passing trivially because it had nothing to contribute.
        conn.execute(
            "INSERT INTO master_companies (isin, nse_symbol, company_name, industry, sector, "
            "is_active) VALUES ('INE_AUTO0001','PHANTOM','Phantom Co','Industrials','Industrials',1)"
        )
        phantom_rowid = conn.execute(
            "SELECT rowid FROM master_companies WHERE nse_symbol = 'PHANTOM'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO business_model_profiles (company_id, isin, symbol, archetype, "
            "revenue_recurrence_pct, pricing_power_score, capital_intensity_score, "
            "operating_leverage_score) VALUES (?,?,?,?,?,?,?,?)",
            (phantom_rowid, "INE_AUTO0001", "PHANTOM", "Asset-Heavy OEM", 55.0, 3, 3, 3),
        )
        conn.execute(
            "INSERT INTO moat_evaluations (company_id, ticker, isin, switching_costs, "
            "network_effects, cost_advantage, intangible_assets, efficient_scale, "
            "total_moat_score, moat_width, moat_trajectory) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (phantom_rowid, "PHANTOM", "INE_AUTO0001", 3, 3, 3, 3, 3, 2.5, "Narrow", "Stable"),
        )
        conn.execute(
            "INSERT INTO company_forensic_health (isin, symbol, fiscal_year, "
            "debt_to_equity_ratio, interest_coverage_ratio, altman_z_score, "
            "market_cap_inr_cr, last_evaluated_date, is_solvency_approved) "
            "VALUES (?,?,?,?,?,?,?,?,1)",
            ("INE_AUTO0001", "PHANTOM", "FY26", 0.5, 3.0, 3.0, 4000.0, "2026-09-20"),
        )


class _BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="peer_graph_"))
        self.mgr = DatabaseManager(db_path=self.tmp / "peer_graph.db")
        self.repo = Repository(manager=self.mgr)
        with self.mgr.session() as conn:
            for ddl in _ENSURE_DDL:
                conn.execute(ddl)
        _seed_substrate(self.mgr)
        with self.mgr.session() as conn:
            hygiene.apply(conn)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Trust layer
# ---------------------------------------------------------------------------
class TestSubstrateHygiene(_BaseCase):
    def test_quarantines_fixtures_and_demo_rows_only(self):
        with self.mgr.session() as conn:
            snap = hygiene.audit(conn)
        self.assertEqual(snap["quarantined"]["graph_fixture_nodes"], 1)
        self.assertEqual(snap["quarantined"]["graph_fixture_edges"], 1)
        self.assertEqual(snap["quarantined"]["demo_macro_events"], 1)
        self.assertEqual(snap["quarantined"]["demo_ripples"], 1)
        self.assertEqual(snap["quarantined"]["unresolvable_ripples"], 1)
        self.assertEqual(snap["quarantined"]["synthetic_isin_companies"], 1)
        # Real, hand-authored rows must never be quarantined.
        with self.mgr.session() as conn:
            self.assertEqual(hygiene.quarantined_keys(conn, "master_companies"),
                             {"INE_AUTO0001"})
            self.assertEqual(hygiene.quarantined_keys(conn, "graph_nodes"), {"TEST_SHOCK_abc"})
            # The real node sharing the graph is untouched.
            self.assertTrue(conn.execute(
                "SELECT 1 FROM graph_nodes WHERE node_id = 'NODE_REAL_1'").fetchone())

    def test_apply_is_idempotent(self):
        with self.mgr.session() as conn:
            hygiene.apply(conn)
            first = hygiene.quarantine_summary(conn)
            hygiene.apply(conn)
            second = hygiene.quarantine_summary(conn)
        self.assertEqual(first, second)


# ---------------------------------------------------------------------------
# Peer graph
# ---------------------------------------------------------------------------
class TestPeerGraph(_BaseCase):
    def _build(self, **kwargs):
        return pg.main(db=self.mgr, apply=True, **kwargs)

    def test_degenerate_features_are_dropped_not_weighted(self):
        res = self._build(top_k=5)
        self.assertEqual(res["status"], "ok", res)
        dropped = set(res["dropped_features"])
        for name in ("distilled.stage_conviction", "distilled.is_cyclical",
                     "solvency.altman_z", "geo.non_india_revenue_pct"):
            self.assertIn(name, dropped, f"{name} should be gated out")
        reasons = res["diagnostics"]["dropped_by_reason"]
        floored = reasons.get("constant", []) + reasons.get("near_constant", [])
        self.assertIn("distilled.stage_conviction", floored)
        self.assertIn("distilled.is_cyclical", floored)
        self.assertIn("solvency.altman_z", reasons.get("constant", []))
        self.assertIn("geo.non_india_revenue_pct", floored)
        # The varied features survive.
        self.assertIn("moat.switching_costs", res["active_features"])
        self.assertIn("solvency.debt_to_equity", res["active_features"])

    def test_identical_profiles_rank_first(self):
        """Two companies given identical substrate values must be each other's rank-1."""
        with self.mgr.session() as conn:
            # Mirror every column that feeds an active feature, so the pair is
            # genuinely identical rather than identical on a hand-picked subset.
            for col in ("revenue_recurrence_pct", "pricing_power_score",
                        "capital_intensity_score", "operating_leverage_score"):
                conn.execute(
                    f"UPDATE business_model_profiles SET {col} = "
                    f"(SELECT {col} FROM business_model_profiles WHERE symbol='CO07') "
                    "WHERE symbol='CO03'"
                )
            for col in ("switching_costs", "network_effects", "cost_advantage",
                        "intangible_assets", "efficient_scale"):
                conn.execute(
                    f"UPDATE moat_evaluations SET {col} = "
                    f"(SELECT {col} FROM moat_evaluations WHERE ticker='CO07') "
                    "WHERE ticker='CO03'"
                )
            for col in ("debt_to_equity_ratio", "market_cap_inr_cr"):
                conn.execute(
                    f"UPDATE company_forensic_health SET {col} = "
                    f"(SELECT {col} FROM company_forensic_health WHERE symbol='CO07') "
                    "WHERE symbol='CO03'"
                )
            for col in ("ebitda_margin_pct", "yoy_revenue_growth_pct"):
                conn.execute(
                    f"UPDATE quarterly_financials SET {col} = "
                    f"(SELECT {col} FROM quarterly_financials WHERE symbol='CO07') "
                    "WHERE symbol='CO03'"
                )
            for col in ("severity_score", "probability"):
                conn.execute(
                    f"UPDATE regulatory_political_risks SET {col} = "
                    f"(SELECT {col} FROM regulatory_political_risks WHERE symbol='CO07') "
                    "WHERE symbol='CO03'"
                )
        self._build(top_k=5)
        with self.mgr.session() as conn:
            top = pg.neighbours(conn, "CO03", top_k=1)
        self.assertTrue(top, "expected at least one neighbour for CO03")
        self.assertEqual(top[0]["peer"], "CO07")
        self.assertAlmostEqual(top[0]["similarity"], 1.0, places=4)

    def test_lift_is_reported_against_anchor_baseline(self):
        self._build(top_k=5)
        with self.mgr.session() as conn:
            rows = pg.neighbours(conn, "CO00", top_k=5)
        self.assertTrue(rows)
        for row in rows:
            self.assertIsNotNone(row["baseline_similarity"])
            self.assertAlmostEqual(
                row["lift"], round(row["similarity"] - row["baseline_similarity"], 4), places=4
            )

    def test_pairs_below_the_coverage_floor_are_never_emitted(self):
        self._build(top_k=5)
        with self.mgr.session() as conn:
            worst = conn.execute(
                "SELECT MIN(coverage), MIN(shared_families) FROM company_peer_graph"
            ).fetchone()
        self.assertGreaterEqual(worst[0], pg.MIN_PAIR_COVERAGE)
        self.assertGreaterEqual(worst[1], pg.MIN_PAIR_FAMILIES)

    def test_quarantined_symbol_never_appears_as_anchor_or_peer(self):
        res = self._build(top_k=5)
        self.assertEqual(res["quarantined_excluded"], 1, res)
        with self.mgr.session() as conn:
            leaked = conn.execute(
                "SELECT COUNT(*) FROM company_peer_graph WHERE anchor_symbol = 'PHANTOM' "
                "OR peer_symbol = 'PHANTOM'"
            ).fetchone()[0]
        self.assertEqual(leaked, 0)

    def test_contaminated_margin_is_treated_as_missing(self):
        """A 599,921% margin must be rejected, not clipped, and must not poison the row.

        CO00's newest quarter carries the contaminated value; the extractor falls
        back to the previous *valid* quarter rather than mixing fields across
        periods or clipping the garbage into range.
        """
        res = self._build(top_k=5)
        self.assertGreaterEqual(res["contaminated_earnings_values"], 1)
        with self.mgr.session() as conn:
            stored = json.loads(conn.execute(
                "SELECT features_json FROM company_peer_features WHERE symbol = 'CO00'"
            ).fetchone()[0])
        self.assertIn("earnings.ebitda_margin_pct", stored)
        low, high = pg.SANITY_BANDS["margin_pct"]
        self.assertTrue(low <= stored["earnings.ebitda_margin_pct"] <= high)

    def test_refuses_to_rank_when_signal_is_absent(self):
        """An empty substrate must produce an explicit refusal, not confident noise."""
        empty_dir = Path(tempfile.mkdtemp(prefix="peer_empty_"))
        self.addCleanup(shutil.rmtree, empty_dir, True)
        empty = DatabaseManager(db_path=empty_dir / "empty.db")
        res = pg.main(db=empty, apply=True, top_k=5)
        self.assertEqual(res["status"], "insufficient_signal")
        self.assertEqual(res["written"], 0)
        with empty.session() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM company_peer_graph").fetchone()[0], 0
            )
            run = pg.latest_run(conn)
        self.assertEqual(run["status"], "insufficient_signal")

    def test_rebuild_is_idempotent(self):
        first = self._build(top_k=5)
        second = self._build(top_k=5)
        self.assertEqual(first["pairs"], second["pairs"])
        with self.mgr.session() as conn:
            total = conn.execute("SELECT COUNT(*) FROM company_peer_graph").fetchone()[0]
        self.assertEqual(total, second["pairs"])


if __name__ == "__main__":
    unittest.main()
