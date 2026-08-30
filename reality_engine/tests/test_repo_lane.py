"""Repo lane acceptance — ISIN resolver, industries seed, funnel fix.

Uses a fresh temp-file SQLite DB (never the live equity_intelligence.db) so the
suite never mutates production data. Verifies:
  (a) upsert_regulatory_political_risk with symbol+company_id, isin=None -> stored isin == master isin
  (b) same call but isin='INE999999999' provided -> stored isin stays 'INE999999999'
  (c) seed_industries_from_seed_file() idempotent 12 rows (real seed file)
  (d) FUNNEL_TABLES phantom removal
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository


class TestRepoLane(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="repo_lane_"))
        self.db_path = self.tmp / "repo_lane.db"
        self.mgr = DatabaseManager(db_path=self.db_path)
        self.repo = Repository(manager=self.mgr)
        # regulatory table needed for (a)/(b)
        self.repo.ensure_regulatory_political_risks_schema()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_regulatory_resolves_isin_via_company_id(self):
        # Seed master with known isin and capture rowid as company_id
        master_isin = "INE123A01001"
        symbol = "REPOLANE_A"
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, company_name, is_active) VALUES (?,?,?,1)",
                (master_isin, symbol, "Repo Lane Co A"),
            )
            row = conn.execute("SELECT rowid FROM master_companies WHERE isin = ?", (master_isin,)).fetchone()
            cid = int(row["rowid"])
        # isin=None -> should resolve to master_isin via _resolve_isin
        self.repo.upsert_regulatory_political_risk(
            symbol=symbol,
            policy_name="Lane Policy A",
            severity_score=2.0,
            probability=0.5,
            isin=None,
            company_id=cid,
        )
        with self.mgr.session() as conn:
            r = conn.execute(
                "SELECT isin FROM regulatory_political_risks WHERE symbol=? AND policy_name=?",
                (symbol, "Lane Policy A"),
            ).fetchone()
            self.assertIsNotNone(r, "regulatory row missing")
            self.assertEqual(r["isin"], master_isin)

    def test_b_regulatory_keeps_provided_isin(self):
        master_isin = "INE999A01001"
        symbol = "REPOLANE_B"
        provided = "INE999999999"
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, company_name, is_active) VALUES (?,?,?,1)",
                (master_isin, symbol, "Repo Lane Co B"),
            )
            row = conn.execute("SELECT rowid FROM master_companies WHERE isin = ?", (master_isin,)).fetchone()
            cid = int(row["rowid"])
        self.repo.upsert_regulatory_political_risk(
            symbol=symbol,
            policy_name="Lane Policy B",
            severity_score=1.5,
            probability=0.6,
            isin=provided,
            company_id=cid,
        )
        with self.mgr.session() as conn:
            r = conn.execute(
                "SELECT isin FROM regulatory_political_risks WHERE symbol=? AND policy_name=?",
                (symbol, "Lane Policy B"),
            ).fetchone()
            self.assertIsNotNone(r)
            self.assertEqual(r["isin"], provided)

    def test_c_seed_industries_idempotent(self):
        # Compute expected count from the real seed file (should be 12)
        seed_path = Path(__file__).resolve().parents[1] / "data" / "seed" / "fundamental_seed.json"
        data = json.loads(seed_path.read_text(encoding="utf-8"))
        rows = data["industries"] if isinstance(data, dict) else data
        expected = len(rows)
        n1 = self.repo.seed_industries_from_seed_file()
        self.assertEqual(n1, expected)
        with self.mgr.session() as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM industries").fetchone()[0]
            self.assertEqual(int(cnt), expected)
        n2 = self.repo.seed_industries_from_seed_file()
        self.assertEqual(n2, expected)
        with self.mgr.session() as conn:
            cnt2 = conn.execute("SELECT COUNT(*) FROM industries").fetchone()[0]
            self.assertEqual(int(cnt2), expected)

    def test_d_funnel_tables(self):
        from reality_engine.pipeline.data_audit import FUNNEL_TABLES
        self.assertNotIn("peer_financial_metrics", FUNNEL_TABLES)
        self.assertIn("financial_metrics", FUNNEL_TABLES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
