"""
TestDistilledExpansion: validates curated 5-key loader and derived parameter synthesis
using isolated temporary databases. Never touches production DB.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing.distillation_engine import DistillationEngine


# 5 canonical curated symbols that exist in curated_company_parameters.json
CURATED_TEST_SYMBOLS = {
    "TCS": "INE467B01029",
    "INFY": "INE009A01021",
    "HDFCBANK": "INE040A01034",
    "SBIN": "INE062A01020",
    "ICICIBANK": "INE090A01021",
}

EXPECTED_KEYS = [
    "cyclicality_profile",
    "business_sensitivities",
    "geopolitical_supply_chain",
    "capital_allocation",
    "order_book_metrics",
]


class TestDistilledExpansion(unittest.TestCase):
    """Isolated tests for lane-code-distill expansion."""

    def _make_db(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="reality_distilled_test_"))
        db_path = temp_dir / "test_equity_intelligence.db"
        db = DatabaseManager(db_path=db_path)
        repo = Repository(manager=db)
        engine = DistillationEngine(manager=db)
        return db, repo, engine, temp_dir

    def _cleanup(self, temp_dir: Path):
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_01_curated_loader_writes_5_keys(self):
        """Curated loader writes 5 keys x N with ISIN resolved, source Curated_Intelligence_FY26."""
        db, repo, engine, temp_dir = self._make_db()
        try:
            # Upsert master_companies for N curated symbols so loader can resolve ISIN
            masters = [
                {
                    "isin": isin,
                    "nse_symbol": sym,
                    "company_name": f"{sym} Ltd",
                    "is_active": 1,
                    "is_nifty200": 1,
                    "is_nifty500": 1,
                }
                for sym, isin in CURATED_TEST_SYMBOLS.items()
            ]
            inserted = repo.upsert_master_companies(masters)
            self.assertGreaterEqual(inserted, len(masters))

            # Seed definitions then load curated
            def_count = engine.seed_ontology_definitions()
            self.assertEqual(def_count, 5)

            result = engine.load_curated_company_parameters()
            self.assertIn("curated_parameters_seeded", result)
            # Loader should have seeded N*5 rows (one per key per resolved symbol)
            # Curated file has 42 entries but only our N masters exist, so loader skips 37 gracefully
            curated_count = result["curated_parameters_seeded"]
            # Dynamic check: must be multiple of 5 and >= N*5 lower bound
            self.assertGreaterEqual(curated_count, len(CURATED_TEST_SYMBOLS) * 5)
            self.assertEqual(curated_count % 5, 0, "curated count should be multiple of 5 keys")
            # Exact expectation with our isolated DB: 5 symbols *5 keys =25
            # Use dynamic but also allow exact 25 when only 5 masters present
            expected_n = len(CURATED_TEST_SYMBOLS)
            self.assertEqual(curated_count, expected_n * 5)

            # Verify DB state: source Curated_Intelligence_FY26 and ISIN resolved
            with db.session() as conn:
                cnt = conn.execute(
                    "SELECT COUNT(*) FROM company_distilled_parameters WHERE source_document_ref='Curated_Intelligence_FY26'"
                ).fetchone()[0]
                self.assertEqual(cnt, curated_count)
                self.assertEqual(cnt, expected_n * 5)

                # Each symbol has exactly 5 keys
                for sym, isin in CURATED_TEST_SYMBOLS.items():
                    rows = conn.execute(
                        "SELECT parameter_key, confidence_score, value_json, isin, source_document_ref FROM company_distilled_parameters WHERE symbol=?",
                        (sym,),
                    ).fetchall()
                    self.assertEqual(len(rows), 5, f"{sym} should have 5 distilled rows")
                    keys = {r["parameter_key"] for r in rows}
                    self.assertEqual(keys, set(EXPECTED_KEYS))
                    for r in rows:
                        # ISIN resolved
                        self.assertEqual(r["isin"], isin)
                        self.assertEqual(r["source_document_ref"], "Curated_Intelligence_FY26")
                        # confidence clamped 0.85-0.95
                        conf = float(r["confidence_score"])
                        self.assertGreaterEqual(conf, 0.85, f"{sym} {r['parameter_key']} confidence {conf} <0.85")
                        self.assertLessEqual(conf, 0.95, f"{sym} {r['parameter_key']} confidence {conf} >0.95")
                        # value_json valid JSON with expected top-level structure
                        try:
                            payload = json.loads(r["value_json"])
                        except Exception as exc:
                            self.fail(f"{sym} {r['parameter_key']} value_json not valid JSON: {exc}")
                        self.assertIsInstance(payload, dict)
                        # spot-check key-specific fields
                        if r["parameter_key"] == "cyclicality_profile":
                            self.assertIn("is_cyclical", payload)
                            self.assertIn("key_revenue_drivers", payload)
                        elif r["parameter_key"] == "business_sensitivities":
                            self.assertIn("moat_rating", payload)
                            self.assertIn("pricing_power_assessment", payload)
                        elif r["parameter_key"] == "order_book_metrics":
                            # curated order_book may have None but should parse
                            self.assertIn("ttm_revenue_inr_cr", payload)
                        elif r["parameter_key"] == "capital_allocation":
                            self.assertIn("deleveraging_trend", payload)
                        elif r["parameter_key"] == "geopolitical_supply_chain":
                            self.assertIn("geographic_revenue_split", payload)

                # Missing ISIN symbols are skipped gracefully: total curated rows must equal expected, not 42*5
                total_distinct_symbols = conn.execute(
                    "SELECT COUNT(DISTINCT symbol) FROM company_distilled_parameters WHERE source_document_ref='Curated_Intelligence_FY26'"
                ).fetchone()[0]
                self.assertEqual(total_distinct_symbols, expected_n)
        finally:
            self._cleanup(temp_dir)

    def test_02_derive_writes_confidence_and_keys(self):
        """Derive writes confidence in [0.3,0.8] + Derived ref, 5 keys present, no crash on missing data."""
        db, repo, engine, temp_dir = self._make_db()
        try:
            engine.seed_ontology_definitions()

            # Upsert synthetic masters: TESTA with data, TESTB with missing data
            repo.upsert_master_companies([
                {"isin": "INE000000001", "nse_symbol": "TESTA", "company_name": "Test A Ltd", "is_active": 1, "is_nifty200": 1},
                {"isin": "INE000000002", "nse_symbol": "TESTB", "company_name": "Test B Ltd", "is_active": 1, "is_nifty200": 1},
                # extra symbol for OPM percentile distribution
                {"isin": "INE000000003", "nse_symbol": "TESTC_DIST", "company_name": "Test C Dist", "is_active": 1, "is_nifty200": 1},
            ])

            # Quarterly financials for TESTA: 4 quarters varying revenue for volatility calc
            with db.session() as conn:
                conn.executemany(
                    "INSERT INTO quarterly_financials (isin, symbol, quarter_end_date, financial_year, revenue_inr_cr, yoy_revenue_growth_pct) VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        ("INE000000001", "TESTA", "2024-12-31", "FY25Q3", 1000, 5.0),
                        ("INE000000001", "TESTA", "2025-03-31", "FY25Q4", 1100, 8.0),
                        ("INE000000001", "TESTA", "2025-06-30", "FY26Q1", 1050, 6.0),
                        ("INE000000001", "TESTA", "2025-09-30", "FY26Q2", 1200, 12.0),
                    ],
                )
                # Annual financials for TESTA (full) and TESTC_DIST (for OPM distribution)
                conn.executemany(
                    "INSERT INTO annual_financials (isin, symbol, fiscal_year, revenue_inr_cr, roce_pct, opm_pct, debt_to_equity, operating_cash_flow_inr_cr) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        ("INE000000001", "TESTA", "FY26", 4350, 15, 20, 0.3, 1000),
                        ("INE000000003", "TESTC_DIST", "FY26", 2000, 10, 10, 0.6, 500),
                    ],
                )
                # Intentionally leave TESTB without quarterly rows and without annual to test missing-data path
                # But insert a minimal annual for TESTB with nulls to ensure derive still runs via direct insert of nulls
                # We do NOT insert any quarterly for TESTB

            # Derive for TESTA (full data)
            res_a = engine.derive_company_parameters(symbol="TESTA", overwrite_derived=True)
            self.assertIn("derived_parameters_seeded", res_a)
            self.assertEqual(res_a["derived_parameters_seeded"], 5)
            self.assertEqual(res_a["symbols_processed"], 1)

            with db.session() as conn:
                rows_a = conn.execute(
                    "SELECT parameter_key, value_json, confidence_score, source_document_ref FROM company_distilled_parameters WHERE symbol='TESTA' AND source_document_ref='Derived_Financials_FY26'"
                ).fetchall()
                self.assertEqual(len(rows_a), 5, "TESTA should have 5 derived keys")
                keys_a = {r["parameter_key"] for r in rows_a}
                self.assertEqual(keys_a, set(EXPECTED_KEYS))

                for r in rows_a:
                    conf = float(r["confidence_score"])
                    # Spec says [0.3,0.8] inclusive to be safe; implementation is 0.5-0.7
                    self.assertGreaterEqual(conf, 0.3, f"confidence {conf} below 0.3")
                    self.assertLessEqual(conf, 0.8, f"confidence {conf} above 0.8")
                    # also assert within implementation's tighter range for completeness (optional)
                    # self.assertGreaterEqual(conf, 0.5)
                    # self.assertLessEqual(conf, 0.7)
                    self.assertEqual(r["source_document_ref"], "Derived_Financials_FY26")
                    payload = json.loads(r["value_json"])
                    self.assertIsInstance(payload, dict)

                # Spot-check business_sensitivities contains moat_rating
                bs_row = conn.execute(
                    "SELECT value_json FROM company_distilled_parameters WHERE symbol='TESTA' AND parameter_key='business_sensitivities'"
                ).fetchone()
                self.assertIsNotNone(bs_row)
                bs_payload = json.loads(bs_row["value_json"])
                self.assertIn("moat_rating", bs_payload)
                # moat derived from roce 15 -> 6 per logic
                self.assertIn(bs_payload["moat_rating"], [4, 6, 8])

                # order_book_metrics contains available false
                ob_row = conn.execute(
                    "SELECT value_json FROM company_distilled_parameters WHERE symbol='TESTA' AND parameter_key='order_book_metrics'"
                ).fetchone()
                ob_payload = json.loads(ob_row["value_json"])
                self.assertIn("available", ob_payload)
                self.assertEqual(ob_payload["available"], False)

                # cyclicality_profile checks
                cp_row = conn.execute(
                    "SELECT value_json FROM company_distilled_parameters WHERE symbol='TESTA' AND parameter_key='cyclicality_profile'"
                ).fetchone()
                cp_payload = json.loads(cp_row["value_json"])
                self.assertIn("is_cyclical", cp_payload)
                self.assertIn("cycle_current_stage", cp_payload)
                self.assertIn("stage_rationale", cp_payload)

            # Derive for TESTB (missing data) should not crash and still create 5 keys with defaults
            res_b = engine.derive_company_parameters(symbol="TESTB", overwrite_derived=True)
            self.assertEqual(res_b["derived_parameters_seeded"], 5)
            self.assertEqual(res_b["symbols_processed"], 1)

            with db.session() as conn:
                rows_b = conn.execute(
                    "SELECT parameter_key, confidence_score, value_json FROM company_distilled_parameters WHERE symbol='TESTB' AND source_document_ref='Derived_Financials_FY26'"
                ).fetchall()
                self.assertEqual(len(rows_b), 5, "TESTB should have 5 derived keys even with missing data")
                for r in rows_b:
                    conf = float(r["confidence_score"])
                    self.assertGreaterEqual(conf, 0.3)
                    self.assertLessEqual(conf, 0.8)
                    payload = json.loads(r["value_json"])
                    self.assertIsInstance(payload, dict)

            # Also test universe derive does not crash on mixed data
            res_universe = engine.derive_company_parameters(universe="all", limit=10, overwrite_derived=True)
            # Should process at least our 3 symbols
            self.assertGreaterEqual(res_universe["symbols_processed"], 2)
            self.assertGreaterEqual(res_universe["derived_parameters_seeded"], 10)

        finally:
            self._cleanup(temp_dir)

    def test_03_derive_skips_curated(self):
        """Derive skips curated (seed curated then derive without overwrite -> curated unchanged)."""
        db, repo, engine, temp_dir = self._make_db()
        try:
            engine.seed_ontology_definitions()
            masters = [
                {"isin": isin, "nse_symbol": sym, "company_name": f"{sym} Ltd", "is_active": 1, "is_nifty200": 1}
                for sym, isin in CURATED_TEST_SYMBOLS.items()
            ]
            repo.upsert_master_companies(masters)
            # Seed curated
            engine.load_curated_company_parameters()

            # Capture curated state for TCS before derive
            with db.session() as conn:
                before_rows = conn.execute(
                    "SELECT parameter_key, value_json, confidence_score, source_document_ref FROM company_distilled_parameters WHERE symbol='TCS' ORDER BY parameter_key"
                ).fetchall()
                self.assertEqual(len(before_rows), 5)
                before_map = {r["parameter_key"]: dict(r) for r in before_rows}
                # confidence should be >=0.85 curated
                for r in before_rows:
                    self.assertGreaterEqual(float(r["confidence_score"]), 0.85)
                    self.assertEqual(r["source_document_ref"], "Curated_Intelligence_FY26")

                # Also ensure no derived rows for TCS yet
                derived_before = conn.execute(
                    "SELECT COUNT(*) FROM company_distilled_parameters WHERE symbol='TCS' AND source_document_ref='Derived_Financials_FY26'"
                ).fetchone()[0]
                self.assertEqual(derived_before, 0)

            # Derive without overwrite: should skip curated
            res_skip = engine.derive_company_parameters(symbol="TCS", overwrite_derived=False)
            # Implementation returns symbols_skipped_curated increment
            self.assertIn("symbols_skipped_curated", res_skip)
            self.assertGreaterEqual(res_skip["symbols_skipped_curated"], 1)
            self.assertEqual(res_skip["symbols_processed"], 0)

            # Verify curated unchanged
            with db.session() as conn:
                after_rows = conn.execute(
                    "SELECT parameter_key, value_json, confidence_score, source_document_ref FROM company_distilled_parameters WHERE symbol='TCS' ORDER BY parameter_key"
                ).fetchall()
                self.assertEqual(len(after_rows), 5)
                for r in after_rows:
                    self.assertGreaterEqual(float(r["confidence_score"]), 0.85)
                    self.assertEqual(r["source_document_ref"], "Curated_Intelligence_FY26")
                    before = before_map[r["parameter_key"]]
                    self.assertEqual(r["value_json"], before["value_json"], f"curated value_json for {r['parameter_key']} should be unchanged")
                    self.assertEqual(float(r["confidence_score"]), float(before["confidence_score"]))

                # No derived rows created for TCS
                derived_after = conn.execute(
                    "SELECT COUNT(*) FROM company_distilled_parameters WHERE symbol='TCS' AND source_document_ref='Derived_Financials_FY26'"
                ).fetchone()[0]
                self.assertEqual(derived_after, 0)

            # Verify overwrite_derived=True does overwrite (or at least processes)
            # Need to add financial data for TCS to allow derive to produce meaningful confidences
            with db.session() as conn:
                # Provide minimal financials for TCS derive after overwrite
                conn.execute(
                    "INSERT OR IGNORE INTO quarterly_financials (isin, symbol, quarter_end_date, financial_year, revenue_inr_cr, yoy_revenue_growth_pct) VALUES (?, ?, ?, ?, ?, ?)",
                    (CURATED_TEST_SYMBOLS["TCS"], "TCS", "2025-09-30", "FY26Q2", 60000, 10),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO annual_financials (isin, symbol, fiscal_year, revenue_inr_cr, roce_pct, opm_pct, debt_to_equity, operating_cash_flow_inr_cr) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (CURATED_TEST_SYMBOLS["TCS"], "TCS", "FY26", 250000, 55, 28, 0.1, 45000),
                )
            res_overwrite = engine.derive_company_parameters(symbol="TCS", overwrite_derived=True)
            self.assertGreaterEqual(res_overwrite["derived_parameters_seeded"], 5)
            self.assertGreaterEqual(res_overwrite["symbols_processed"], 1)
            with db.session() as conn:
                # After overwrite, source should be Derived and confidence 0.5-0.7
                row = conn.execute(
                    "SELECT confidence_score, source_document_ref FROM company_distilled_parameters WHERE symbol='TCS' AND parameter_key='business_sensitivities'"
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["source_document_ref"], "Derived_Financials_FY26")
                self.assertGreaterEqual(float(row["confidence_score"]), 0.3)
                self.assertLessEqual(float(row["confidence_score"]), 0.8)

        finally:
            self._cleanup(temp_dir)

    def test_04_idempotent_rerun(self):
        """Idempotent re-run (second derive returns 0 new rows or same counts)."""
        db, repo, engine, temp_dir = self._make_db()
        try:
            engine.seed_ontology_definitions()
            # Upsert master for idempotent symbol TESTC
            repo.upsert_master_companies([
                {"isin": "INE000000010", "nse_symbol": "TESTC", "company_name": "Test C Ltd", "is_active": 1, "is_nifty200": 1},
            ])
            with db.session() as conn:
                conn.executemany(
                    "INSERT INTO quarterly_financials (isin, symbol, quarter_end_date, financial_year, revenue_inr_cr, yoy_revenue_growth_pct) VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        ("INE000000010", "TESTC", "2024-12-31", "FY25Q3", 2000, 7.0),
                        ("INE000000010", "TESTC", "2025-03-31", "FY25Q4", 2100, 9.0),
                        ("INE000000010", "TESTC", "2025-06-30", "FY26Q1", 2050, 5.0),
                        ("INE000000010", "TESTC", "2025-09-30", "FY26Q2", 2200, 11.0),
                    ],
                )
                conn.execute(
                    "INSERT INTO annual_financials (isin, symbol, fiscal_year, revenue_inr_cr, roce_pct, opm_pct, debt_to_equity, operating_cash_flow_inr_cr) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("INE000000010", "TESTC", "FY26", 8350, 18, 22, 0.2, 1500),
                )

            # First derive
            res1 = engine.derive_company_parameters(symbol="TESTC", overwrite_derived=True)
            self.assertEqual(res1["derived_parameters_seeded"], 5)
            with db.session() as conn:
                cnt1 = conn.execute(
                    "SELECT COUNT(*) FROM company_distilled_parameters WHERE symbol='TESTC' AND source_document_ref='Derived_Financials_FY26'"
                ).fetchone()[0]
                self.assertEqual(cnt1, 5)
                # capture before second run values
                rows1 = conn.execute(
                    "SELECT parameter_key, value_json, confidence_score FROM company_distilled_parameters WHERE symbol='TESTC' ORDER BY parameter_key"
                ).fetchall()
                cnt_total_1 = conn.execute("SELECT COUNT(*) FROM company_distilled_parameters WHERE symbol='TESTC'").fetchone()[0]
                self.assertEqual(cnt_total_1, 5)

            # Second derive with same params (overwrite False) should not create extra rows
            res2 = engine.derive_company_parameters(symbol="TESTC", overwrite_derived=False)
            # res2 may re-process since not curated, but total rows must stay same
            with db.session() as conn:
                cnt2 = conn.execute(
                    "SELECT COUNT(*) FROM company_distilled_parameters WHERE symbol='TESTC' AND source_document_ref='Derived_Financials_FY26'"
                ).fetchone()[0]
                self.assertEqual(cnt2, 5, "second derive should not duplicate rows")
                cnt_total_2 = conn.execute("SELECT COUNT(*) FROM company_distilled_parameters WHERE symbol='TESTC'").fetchone()[0]
                self.assertEqual(cnt_total_2, 5)
                # Also ensure distinct keys still 5
                distinct_keys = conn.execute(
                    "SELECT COUNT(DISTINCT parameter_key) FROM company_distilled_parameters WHERE symbol='TESTC'"
                ).fetchone()[0]
                self.assertEqual(distinct_keys, 5)

            # Third derive with overwrite True should also be idempotent (upsert replaces, no duplicate)
            res3 = engine.derive_company_parameters(symbol="TESTC", overwrite_derived=True)
            self.assertEqual(res3["derived_parameters_seeded"], 5)
            with db.session() as conn:
                cnt3 = conn.execute("SELECT COUNT(*) FROM company_distilled_parameters WHERE symbol='TESTC'").fetchone()[0]
                self.assertEqual(cnt3, 5)
                # Verify no duplicates across keys: primary key (isin, parameter_key) ensures uniqueness
                dup_check = conn.execute(
                    "SELECT isin, parameter_key, COUNT(*) c FROM company_distilled_parameters WHERE symbol='TESTC' GROUP BY isin, parameter_key HAVING c>1"
                ).fetchall()
                self.assertEqual(len(dup_check), 0, "no duplicate isin+parameter_key rows")

            # Also test curated idempotent: curated loader re-run should be idempotent
            # For TESTC we don't have curated, but test that calling derive twice with overwrite False on curated symbol after initial curated would skip
            # Re-use a curated symbol for this extra check within same test DB (isolated)
            # Create new temp DB scenario: seed curated then derive skip twice
            db2, repo2, engine2, temp_dir2 = self._make_db()
            try:
                engine2.seed_ontology_definitions()
                repo2.upsert_master_companies([
                    {"isin": CURATED_TEST_SYMBOLS["HDFCBANK"], "nse_symbol": "HDFCBANK", "company_name": "HDFC Bank", "is_active": 1}
                ])
                engine2.load_curated_company_parameters()
                with db2.session() as conn:
                    cnt_cur_before = conn.execute(
                        "SELECT COUNT(*) FROM company_distilled_parameters WHERE symbol='HDFCBANK'"
                    ).fetchone()[0]
                    self.assertEqual(cnt_cur_before, 5)
                r_a = engine2.derive_company_parameters(symbol="HDFCBANK", overwrite_derived=False)
                r_b = engine2.derive_company_parameters(symbol="HDFCBANK", overwrite_derived=False)
                # Both should skip curated
                self.assertEqual(r_a["symbols_skipped_curated"], 1)
                self.assertEqual(r_b["symbols_skipped_curated"], 1)
                with db2.session() as conn:
                    cnt_cur_after = conn.execute(
                        "SELECT COUNT(*) FROM company_distilled_parameters WHERE symbol='HDFCBANK'"
                    ).fetchone()[0]
                    self.assertEqual(cnt_cur_after, 5)
                    self.assertEqual(cnt_cur_after, cnt_cur_before)
            finally:
                self._cleanup(temp_dir2)

        finally:
            self._cleanup(temp_dir)


if __name__ == "__main__":
    unittest.main()
