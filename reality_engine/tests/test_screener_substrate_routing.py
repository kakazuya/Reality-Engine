"""Screener substrate routing — canonical moat/ROIC provenance.

Regression cover for two defects fixed 2026-09-20:

* ``_lookup_moat_metrics`` tier 1 joins ``companies``, a PostgreSQL-only table. On SQLite
  that query always raised and every lookup silently fell through to an archetype
  heuristic, so 76% of the nifty200 disagreed with the stored ``moat_evaluations`` and 67
  crossed the ``TOPDOWN_MIN_MOAT_SCORE`` gate. The canonical row must now win.
* The ROIC-WACC spread is a constant for most names, and the thesis template rendered it as
  "value-creative". The spread now carries a provenance status so the claim is gated.

Isolation convention (see tests/test_derived_substrate.py): temp-file SQLite, never the
live equity_intelligence.db.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing.composite_screener import (
    CompositeScreener,
    TOPDOWN_MIN_MOAT_SCORE,
)


# business_model_profiles is created at runtime by repository methods, not schema.sql.
_ENSURE_DDL = (
    "CREATE TABLE IF NOT EXISTS business_model_profiles ("
    " company_id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT UNIQUE, archetype TEXT,"
    " revenue_recurrence_pct REAL, pricing_power_score REAL, capital_intensity_score REAL,"
    " operating_leverage_score REAL, qualitative_notes TEXT, updated_at TEXT)",
    "CREATE TABLE IF NOT EXISTS moat_evaluations ("
    " company_id INTEGER PRIMARY KEY, ticker TEXT UNIQUE, eval_date TEXT, switching_costs REAL,"
    " network_effects REAL, cost_advantage REAL, intangible_assets REAL, efficient_scale REAL,"
    " total_moat_score REAL, moat_width TEXT, moat_trajectory TEXT, isin TEXT)",
    "CREATE TABLE IF NOT EXISTS business_model_profiles_demo ("
    " symbol TEXT PRIMARY KEY, archetype TEXT, revenue_recurrence_pct REAL,"
    " pricing_power_score REAL, capital_intensity_score REAL, operating_leverage_score REAL,"
    " notes TEXT)",
)


def _seed(mgr) -> None:
    with mgr.session() as conn:
        for ddl in _ENSURE_DDL:
            conn.execute(ddl)
        # Two companies: one WITH a canonical moat row, one WITHOUT (heuristic fallback).
        for i, sym in enumerate(("CANON", "FALLBACK")):
            isin = f"INE{i:04d}B01{i:03d}"
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, company_name, industry, sector, "
                "is_active, is_nifty200) VALUES (?,?,?,?,?,1,1)",
                (isin, sym, f"{sym} Ltd", "Industrials", "Industrials"),
            )
            conn.execute(
                "INSERT INTO business_model_profiles (company_id, isin, symbol, archetype, "
                "revenue_recurrence_pct, pricing_power_score, capital_intensity_score, "
                "operating_leverage_score) VALUES (?,?,?,?,?,?,?,?)",
                (i + 1, isin, sym, "Asset-Heavy OEM", 50.0, 3, 3, 3),
            )
            # NOTE: no business_model_profiles_demo row is seeded. That table is a 1:1 mirror
            # of the canonical one and the screener no longer reads it (see tier 3), so a
            # fixture that seeded it would hide a regression back to the mirror.
        conn.execute(
            "INSERT INTO moat_evaluations (company_id, ticker, isin, switching_costs, "
            "network_effects, cost_advantage, intangible_assets, efficient_scale, "
            "total_moat_score, moat_width, moat_trajectory) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (1, "CANON", "INE0000B01000", 4, 4, 4, 4, 4, 4.25, "Wide", "Expanding"),
        )
        # RoCE for the proxy path only; CANON has no annual_financials row.
        conn.execute(
            "INSERT INTO annual_financials (isin, symbol, fiscal_year, roce_pct) VALUES (?,?,?,?)",
            ("INE0001B01001", "FALLBACK", "FY26", 16.5),
        )


class TestScreenerSubstrateRouting(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="screener_routing_"))
        self.mgr = DatabaseManager(db_path=self.tmp / "routing.db")
        self.repo = Repository(manager=self.mgr)
        _seed(self.mgr)
        # CompositeScreener.__init__ takes no arguments and binds the module-level `repo`
        # singleton, so the repository has to be injected after construction for the
        # fixture to be the database under test.
        self.screener = CompositeScreener()
        self.screener.repo = self.repo

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # moat routing
    # ------------------------------------------------------------------
    def test_canonical_moat_wins_over_archetype_heuristic(self):
        """The stored substrate must answer when a moat_evaluations row exists."""
        got = self.screener._lookup_moat_metrics("CANON", "INE0000B01000")
        self.assertAlmostEqual(got["total_moat_score"], 4.25, places=2)
        self.assertEqual(got["moat_source"], "moat_evaluations")
        self.assertEqual(got["moat_width"], "Wide")
        self.assertEqual(got["moat_trajectory"], "Expanding")
        # And it must differ from what the heuristic would have produced (2.7 + adj).
        self.assertNotAlmostEqual(got["total_moat_score"], 2.7, places=2)

    def test_heuristic_fires_from_the_canonical_table_without_the_demo_mirror(self):
        """Tier 2 must not depend on `business_model_profiles_demo` any more.

        The fixture deliberately seeds no demo rows: if the heuristic still read the mirror
        this would fall through to the default 2.5 and the assertion below would fail.
        """
        with self.mgr.session() as conn:
            demo_rows = conn.execute(
                "SELECT COUNT(*) FROM business_model_profiles_demo"
            ).fetchone()[0]
        self.assertEqual(demo_rows, 0, "fixture must not seed the retired mirror")
        got = self.screener._lookup_moat_metrics("FALLBACK", "INE0001B01001")
        self.assertEqual(got["moat_source"], "archetype_heuristic")
        self.assertAlmostEqual(got["total_moat_score"], 2.7, places=2)

    def test_moat_gate_uses_the_canonical_score(self):
        """The TOPDOWN gate reads the routed score, so routing controls funnel membership."""
        canonical = self.screener._lookup_moat_metrics("CANON", "")["total_moat_score"]
        heuristic = self.screener._lookup_moat_metrics("FALLBACK", "")["total_moat_score"]
        # CANON clears the 3.5 hurdle on stored data; the heuristic score would not.
        self.assertGreaterEqual(canonical, TOPDOWN_MIN_MOAT_SCORE)
        self.assertLess(heuristic, TOPDOWN_MIN_MOAT_SCORE)

    # ------------------------------------------------------------------
    # ROIC provenance
    # ------------------------------------------------------------------
    def test_roic_value_is_unchanged_but_status_reports_provenance(self):
        """Numeric contract preserved (guardrail G2); provenance is what gates the claim."""
        # No PG tier, no RoCE row -> the terminal constant, reported as unknown.
        self.assertAlmostEqual(self.screener._lookup_roic_wacc_spread("CANON", ""), 0.06, places=4)
        self.assertEqual(self.screener.roic_wacc_status("CANON"), "unknown")

    def test_roic_proxy_status_when_roce_is_available(self):
        # annual_financials roce 16.5% -> 0.165 - 0.10 WACC = 0.065, status proxy
        self.assertAlmostEqual(self.screener._lookup_roic_wacc_spread("FALLBACK", ""), 0.065, places=4)
        self.assertEqual(self.screener.roic_wacc_status("FALLBACK"), "proxy")

    def test_enrichment_carries_the_status_column(self):
        import pandas as pd
        df = pd.DataFrame([{"symbol": "CANON", "isin": "", "industry": "Industrials",
                            "sector": "Industrials"}])
        out = self.screener._enrich_with_topdown_metrics(df)
        self.assertIn("roic_wacc_status", out.columns)
        self.assertEqual(out.iloc[0]["roic_wacc_status"], "unknown")

    # ------------------------------------------------------------------
    # the user-visible claim
    # ------------------------------------------------------------------
    def test_monetisation_claim_is_absent_from_thesis_text_without_a_source(self):
        """The template must not assert value-creation from the constant."""
        from reality_engine.agent.orchestrator import AgentOrchestrator

        orch = AgentOrchestrator(repository=self.repo, screener=self.screener)
        rationale = orch._synthesize_topdown_rationale(
            symbol="CANON", sector="Industrials", industry="Industrials",
            distilled={}, candidate_row={},
        )
        self.assertNotIn("value-creative", rationale)
        self.assertIn("monetisation", rationale.lower())


if __name__ == "__main__":
    unittest.main()
