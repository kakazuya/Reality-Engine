"""
Unit & Integration Tests for Deterministic Bootstrap & Test-Data Workflows.
Verifies fixture integrity, clean database bootstrapping, schema creation,
time-series calculations, fundamental seeding, causal graph ontologies,
FTS concall indexing, CLI execution, and idempotency.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from reality_engine.config import FIXTURES_DIR, DATA_DIR
from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.db.fixtures import create_isolated_test_db, isolated_test_context
from reality_engine.pipeline.bootstrap import BootstrapManager, bootstrap_database


class TestBootstrapWorkflow(unittest.TestCase):
    """Test suite for Reality Engine deterministic bootstrap engine and fixtures."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="reality_bootstrap_test_suite_"))
        cls.test_db_path = cls.temp_dir / "bootstrapped_test.db"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_01_fixture_file_integrity(self):
        """Verifies that the fixtures.json file exists and contains all required data contracts."""
        fixture_path = FIXTURES_DIR / "fixtures.json"
        self.assertTrue(fixture_path.exists(), f"Fixtures file missing at {fixture_path}")
        self.assertGreater(fixture_path.stat().st_size, 100000, "Fixtures file is unexpectedly small")

        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        required_keys = [
            "master_companies",
            "quarterly_financials",
            "annual_financials",
            "company_forensic_health",
            "corporate_documents",
            "insider_trades",
            "bulk_block_deals",
        ]
        for key in required_keys:
            self.assertIn(key, data, f"Required fixture key '{key}' missing from fixtures.json")
            self.assertIsInstance(data[key], list, f"Fixture key '{key}' must be a list")
            self.assertGreater(len(data[key]), 0, f"Fixture list for '{key}' is empty")

        # Verify Nifty 200 constituents count
        n200_count = sum(1 for c in data["master_companies"] if c.get("is_nifty200") == 1)
        self.assertGreaterEqual(n200_count, 200, "Fixtures must include at least 200 Nifty 200 members")

        # Verify key test stock coverage
        symbols = {c.get("nse_symbol") for c in data["master_companies"] if c.get("nse_symbol")}
        for required_sym in ["HAL", "TITAGARH", "KAYNES", "PIDILITIND", "RELIANCE", "ASIANPAINT", "SCI", "HAVELLS", "TCS", "HDFCBANK"]:
            self.assertIn(required_sym, symbols, f"Core symbol {required_sym} missing from master company fixtures")

    def test_02_bootstrap_manager_clean_database(self):
        """Tests complete deterministic bootstrapping from a fresh/empty database."""
        db = DatabaseManager(db_path=self.test_db_path)
        repo = Repository(manager=db)
        mgr = BootstrapManager(
            db_path=self.test_db_path,
            db_manager_inst=db,
            repository_inst=repo,
        )

        res = mgr.bootstrap(days=25, top=200, force=True, verify=True)

        self.assertEqual(res["status"], "SUCCESS")
        self.assertGreater(res["master_companies_count"], 200)
        self.assertGreater(res["bhavcopy_rows_count"], 1000)
        self.assertGreater(res["fundamentals"]["quarterly_financials"], 0)
        self.assertGreater(res["fundamentals"]["annual_financials"], 0)
        self.assertGreater(res["fundamentals"]["forensic_health"], 0)
        self.assertGreater(res["ontologies"]["company_parameters"], 0)
        self.assertGreater(res["causal_graph"]["graph_nodes"], 0)

        # Check checkpoint validation
        checkpoint = res.get("checkpoint")
        self.assertIsNotNone(checkpoint)
        self.assertTrue(checkpoint.get("checkpoint_passed"), "Phase 1 checkpoint should pass on bootstrapped database")
        self.assertGreaterEqual(checkpoint.get("technical_data_complete_count", 0), 190)
        self.assertGreaterEqual(checkpoint.get("fundamental_data_complete_count", 0), 180)

        # Verify tables and records in SQLite
        with db.session() as conn:
            journal = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            self.assertEqual(journal.upper(), "WAL")

            n200_in_db = conn.execute("SELECT COUNT(*) FROM master_companies WHERE is_nifty200 = 1").fetchone()[0]
            self.assertGreaterEqual(n200_in_db, 200)

            # Check rolling indicators computed
            hal_rows = conn.execute("SELECT * FROM daily_price_delivery WHERE symbol = 'HAL' ORDER BY date DESC").fetchall()
            self.assertGreater(len(hal_rows), 0)
            latest_hal = dict(hal_rows[0])
            self.assertIsNotNone(latest_hal.get("delivery_spike_ratio"))
            self.assertIsNotNone(latest_hal.get("rsi_14"))
            self.assertIsNotNone(latest_hal.get("sma_20"))

            # Check concalls in FTS5
            fts_count = conn.execute("SELECT COUNT(*) FROM intelligence_fts").fetchone()[0]
            self.assertGreater(fts_count, 0)

    def test_03_bootstrap_cli_execution(self):
        """Verifies CLI command `python reality_engine/cli.py bootstrap --target-db ...` executes cleanly."""
        cli_db_path = self.temp_dir / "cli_bootstrap_test.db"
        cmd = [
            sys.executable,
            "reality_engine/cli.py",
            "bootstrap",
            "--target-db",
            str(cli_db_path),
            "--days",
            "25",
            "--top",
            "200",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"Bootstrap CLI command failed: {proc.stderr}")
        self.assertIn("BOOTSTRAP EXECUTION SUMMARY", proc.stdout)
        self.assertIn("Status                  : SUCCESS", proc.stdout)
        self.assertIn("Checkpoint Validation   : PASSED", proc.stdout)
        self.assertTrue(cli_db_path.exists())

    def test_04_bootstrap_idempotency(self):
        """Verifies running bootstrap twice on the same database is safe and idempotent."""
        idempotent_db_path = self.temp_dir / "idempotent_test.db"
        mgr = BootstrapManager(db_path=idempotent_db_path)

        # Run 1
        res1 = mgr.bootstrap(days=25, top=200, verify=False)
        self.assertEqual(res1["status"], "SUCCESS")

        # Run 2 on same database
        res2 = mgr.bootstrap(days=25, top=200, verify=False)
        self.assertEqual(res2["status"], "SUCCESS")

        # Verify no duplicate master companies
        with mgr.db.session() as conn:
            total_m = conn.execute("SELECT COUNT(*) FROM master_companies").fetchone()[0]
            distinct_m = conn.execute("SELECT COUNT(DISTINCT isin) FROM master_companies").fetchone()[0]
            self.assertEqual(total_m, distinct_m, "Master companies table should not contain duplicate ISINs")

    def test_05_sample_only_fast_bootstrap(self):
        """Verifies sample-only mode bootstraps key symbols quickly."""
        sample_db_path = self.temp_dir / "sample_only_test.db"
        mgr = BootstrapManager(db_path=sample_db_path)

        res = mgr.bootstrap(days=25, sample_only=True, verify=False)
        self.assertEqual(res["status"], "SUCCESS")
        self.assertLessEqual(res["master_companies_count"], 20)

        # Verify key stocks present
        with mgr.db.session() as conn:
            hal = conn.execute("SELECT isin, company_name FROM master_companies WHERE nse_symbol = 'HAL'").fetchone()
            self.assertIsNotNone(hal)
            titagarh = conn.execute("SELECT isin, company_name FROM master_companies WHERE nse_symbol = 'TITAGARH'").fetchone()
            self.assertIsNotNone(titagarh)

    def test_06_isolated_test_context_fixture(self):
        """Verifies isolated_test_context creates an independent temporary DB and cleans up on exit."""
        created_path = None
        with isolated_test_context(bootstrap_full=False) as (db, repo, target_dir):
            created_path = target_dir
            self.assertTrue(target_dir.exists())
            self.assertIsNotNone(db)
            self.assertIsNotNone(repo)

            # Insert a record
            repo.upsert_master_companies([{
                "isin": "INE_TEST_999",
                "nse_symbol": "TESTSTOCK",
                "company_name": "Test Company",
                "is_active": 1
            }])
            comp = repo.get_company_by_symbol("TESTSTOCK")
            self.assertIsNotNone(comp)
            self.assertEqual(comp["company_name"], "Test Company")

        # Verify directory cleaned up
        self.assertFalse(created_path.exists(), "isolated_test_context should clean up temp directory on exit")


if __name__ == "__main__":
    unittest.main()
