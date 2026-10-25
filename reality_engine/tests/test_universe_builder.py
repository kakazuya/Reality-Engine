"""Fixture test for the point-in-time theme-universe builder.

The fixture is the shape production actually has: an ``ar_facts`` revenue-mix table
(``Revenue from Operations`` plus ``Revenue from Operations (Gold Jewellery)`` for the
same document, fiscal period, basis and unit) and a deck percentage row.  It checks the
weight, the prior-year column being ignored, the materiality floor, the pivot flag, the
expiry of a stale weight, and that an acquisition announcement is a candidate, not a
member.

Run from the repo root:
    python -m unittest reality_engine.tests.test_universe_builder
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import sys
import unittest
import uuid
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reality_engine.scripts import build_universe_membership as builder  # noqa: E402

# The harness TMP dir (and any ``tmp*`` directory) is ACL-denied; ``.tmp/`` is ignored.
_TMP_ROOT = ROOT / ".tmp" / "universe-tests"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)

ACME = "INE00ACME001"    # 90% of revenue is jewellery -> a weighted member
BETA = "INE00BETA001"    # 20% of revenue is jewellery -> below the floor, no membership
GAMMA = "INE00GAMMA01"   # NSE industry 'Gems Jewellery And Watches' -> unweighted member
DELTA = "INE00DELTA01"   # deck says jewellery is 60% of revenue
FILED_AT = "2019-07-30T11:27:07"


def _case_dir() -> Path:
    path = _TMP_ROOT / f"case_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    path.mkdir()
    return path


def _fixture(root: Path) -> None:
    eq = sqlite3.connect(root / "equity_intelligence.db")
    eq.executescript(
        "CREATE TABLE master_companies(isin TEXT, nse_symbol TEXT, bse_code TEXT, company_name TEXT);"
        "CREATE TABLE company_industry(isin TEXT, symbol TEXT, sector TEXT, industry TEXT,"
        " basic_industry TEXT, fetched_at TEXT, listing_date TEXT);"
        "CREATE TABLE substrate_quarantine(rule_id TEXT, table_name TEXT, row_key TEXT, severity TEXT);"
    )
    eq.executemany("INSERT INTO master_companies VALUES (?,?,?,?)", [
        (ACME, "ACME", "500001", "Acme Jewellery Limited"),
        (BETA, "BETA", "500002", "Beta Packaging Limited"),
        (GAMMA, "GAMMA", "500003", "Gamma Jewellers Limited"),
        (DELTA, "DELTA", "500004", "Delta Retail Limited"),
    ])
    eq.executemany("INSERT INTO company_industry VALUES (?,?,?,?,?,?,?)", [
        (ACME, "ACME", "Consumer Durables", "Consumer Durables", "Packaging", "2026-01-01", "10-May-1995"),
        (BETA, "BETA", "Consumer Durables", "Consumer Durables", "Packaging", "2026-01-01", "10-May-1995"),
        (GAMMA, "GAMMA", "Consumer Durables", "Consumer Durables", "Gems Jewellery And Watches",
         "2026-01-01", "15-Mar-2016"),
        (DELTA, "DELTA", "Consumer Durables", "Consumer Durables", "Packaging", "2026-01-01", "10-May-1995"),
    ])
    eq.commit()
    eq.close()

    # ar_facts + its external-content FTS index, the production query path.
    ar = sqlite3.connect(root / "ar_facts.db")
    ar.executescript(
        "CREATE TABLE ar_facts(doc_id INTEGER, piece INTEGER, isin TEXT, symbol TEXT,"
        " fiscal_year TEXT, filed_at TEXT, page INTEGER, category TEXT, item TEXT,"
        " value_raw TEXT, value REAL, unit TEXT, period TEXT, basis TEXT, quote TEXT,"
        " model TEXT, value_check TEXT, prompt_version TEXT);"
        "CREATE VIRTUAL TABLE ar_facts_fts USING fts5(item, category,"
        " content='ar_facts', content_rowid='rowid');"
    )
    rows = [
        # (doc, piece, isin, symbol, fy, filed, category, item, value, unit, period, basis)
        (1, 11, ACME, "ACME", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations", 1000.0, "Rs crore", "FY19", "standalone"),
        (1, 11, ACME, "ACME", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations (Gold Jewellery)", 900.0, "Rs crore", "FY19", "standalone"),
        (1, 11, ACME, "ACME", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations (Others)", 100.0, "Rs crore", "FY19", "standalone"),
        # The prior-year comparative column: 400/500 = 0.8, and wrong for FY19.
        (1, 11, ACME, "ACME", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations (Gold Jewellery)", 400.0, "Rs crore", "FY18", "standalone"),
        (1, 11, ACME, "ACME", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations", 500.0, "Rs crore", "FY18", "standalone"),
        # A market statistic, not a company revenue mix: must never become a weight.
        (1, 12, ACME, "ACME", "2019-03-31", FILED_AT, "market_share",
         "Gold jewellery market share of revenue", 64.0, "%", "FY19", "standalone"),
        # Below the materiality floor.
        (2, 11, BETA, "BETA", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations", 1000.0, "Rs crore", "FY19", "standalone"),
        (2, 11, BETA, "BETA", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations (Gold Jewellery)", 200.0, "Rs crore", "FY19", "standalone"),
    ]
    ar.executemany(
        "INSERT INTO ar_facts(doc_id, piece, isin, symbol, fiscal_year, filed_at, category, item,"
        " value, unit, period, basis) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    ar.execute("INSERT INTO ar_facts_fts(ar_facts_fts) VALUES('rebuild')")
    ar.commit()
    ar.close()

    dk = sqlite3.connect(root / "deck_figures.db")
    dk.executescript(
        "CREATE TABLE facts(sha256 TEXT, page_no INTEGER, prompt_version TEXT, model TEXT,"
        " line_no INTEGER, metric TEXT, period TEXT, raw_number TEXT, value REAL, unit TEXT,"
        " is_final INTEGER);"
        "CREATE VIRTUAL TABLE facts_metric_fts USING fts5(metric, content='facts',"
        " content_rowid='rowid');"
        "CREATE TABLE deck_sources(source TEXT, source_id TEXT, symbol TEXT, isin TEXT,"
        " exch_code TEXT, known_at TEXT, title TEXT, url TEXT, local_path TEXT, sha256 TEXT,"
        " size_bytes INTEGER, status TEXT, error TEXT, fetched_at TEXT);"
    )
    dk.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               ("sha-delta", 12, "v1", "m", 3, "Gold jewellery revenue mix", "FY25",
                "60", 60.0, "%", 1))
    dk.execute("INSERT INTO facts_metric_fts(facts_metric_fts) VALUES('rebuild')")
    dk.execute("INSERT INTO deck_sources(source, symbol, isin, known_at, sha256) VALUES (?,?,?,?,?)",
               ("bse", "DELTA", DELTA, "2025-05-20T18:00:00", "sha-delta"))
    dk.commit()
    dk.close()

    ann = sqlite3.connect(root / "bse_announcements.db")
    ann.executescript(
        "CREATE TABLE ann(NEWSID TEXT, SCRIP_CD TEXT, symbol TEXT, HEADLINE TEXT, NEWSSUB TEXT,"
        " NEWS_DT TEXT);")
    ann.execute("INSERT INTO ann VALUES (?,?,?,?,?,?)",
                ("n1", "500001", "ACME",
                 "Acme sets up a subsidiary for gold jewellery retailing", "", "2020-02-02"))
    ann.commit()
    ann.close()


class UniverseBuilderTests(unittest.TestCase):
    def setUp(self):
        self.root = _case_dir()
        _fixture(self.root)
        self.out = self.root / "out.db"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _run(self) -> dict:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = builder.main(["--db", str(self.out), "--data-root", str(self.root),
                                 "--themes", str(builder.DEFAULT_THEMES)])
        self.assertEqual(code, 0)
        return json.loads(buf.getvalue().splitlines()[0])

    def _rows(self, isin: str):
        con = sqlite3.connect(self.out)
        try:
            return con.execute(
                "SELECT theme, isin, valid_from, valid_to, weight, weight_source, method,"
                " pivot, evidence_id, evidence_quote FROM universe_membership WHERE isin = ?",
                (isin,)).fetchall()
        finally:
            con.close()

    def test_ar_revenue_mix_weight_and_pivot(self):
        self._run()
        rows = self._rows(ACME)
        self.assertEqual(len(rows), 1)
        theme, _isin, valid_from, valid_to, weight, source, method, pivot, evidence, quote = rows[0]
        self.assertEqual(theme, "gold_jewellery_finance")
        self.assertEqual(valid_from, "2019-07-30")     # the AR's filing date
        self.assertEqual(valid_to, "2021-03-31")       # two fiscal years later: stale
        self.assertAlmostEqual(weight, 0.9, places=4)  # not 0.8 (FY18) and not 0.64 (market)
        self.assertEqual(source, "segment")
        self.assertEqual(method, "segment")
        self.assertEqual(pivot, 1)                     # the largest of two segments
        self.assertIn("ar_facts", evidence)
        self.assertIn("Gold Jewellery", quote)

    def test_floor_and_industry_are_unweighted(self):
        self._run()
        self.assertEqual(self._rows(BETA), [])         # 20% is below min_segment_weight
        gamma = self._rows(GAMMA)
        self.assertEqual(len(gamma), 1)
        _theme, _isin, since, _until, weight, source, method, _pivot, _ev, _quote = gamma[0]
        self.assertIsNone(weight)                      # never 0
        self.assertEqual((source, method), ("industry", "industry"))
        self.assertEqual(since, "2016-03-15")          # the listing date, not the crawl

    def test_deck_revenue_mix_and_prior_year(self):
        self._run()
        delta = self._rows(DELTA)
        self.assertEqual(len(delta), 1)
        self.assertAlmostEqual(delta[0][4], 0.6, places=4)
        self.assertEqual(delta[0][2], "2025-05-20")
        self.assertEqual(delta[0][3], "2027-03-31")

    def test_subsidiary_is_a_candidate_not_a_member(self):
        self._run()
        con = sqlite3.connect(self.out)
        try:
            methods = {r[0] for r in con.execute("SELECT DISTINCT method FROM universe_membership")}
            candidates = con.execute(
                "SELECT theme, isin, method, evidence_quote FROM universe_candidates").fetchall()
            columns = {str(r[1]) for r in con.execute("PRAGMA table_info(universe_candidates)")}
        finally:
            con.close()
        self.assertNotIn("subsidiary", methods)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][:3], ("gold_jewellery_finance", ACME, "subsidiary"))
        self.assertIn("subsidiary", candidates[0][3])
        self.assertNotIn("weight", columns)  # candidates never carry a weight

    def test_rebuild_is_idempotent(self):
        first = self._run()
        second = self._run()
        self.assertEqual(first["members"], second["members"])
        self.assertEqual(self._rows(ACME)[0][2], "2019-07-30")
        con = sqlite3.connect(self.out)
        try:
            joins, exits = con.execute(
                "SELECT joins, exits FROM universe_membership_runs"
                " ORDER BY built_at DESC, run_id DESC").fetchone()
        finally:
            con.close()
        self.assertFalse(json.loads(joins))
        self.assertFalse(json.loads(exits))


class SegmentLabelTests(unittest.TestCase):
    """The row shapes that decide numerator vs total have to stay distinguishable."""

    def test_split_item_shapes(self):
        for item in ("Revenue from Operations (Petroleum)", "Revenue from Operations: Petroleum",
                     "Revenue from Operations - Petroleum segment"):
            base, suffix = builder._split_item(item)
            self.assertEqual(base, "revenue from operations", item)
            self.assertIn("petroleum", suffix, item)

    def test_unit_and_year_suffixes_are_totals(self):
        for item in ("Revenue from Operations (Rs crore)", "Revenue from Operations (FY19)",
                     "Total External Revenue"):
            base, suffix = builder._split_item(item)
            self.assertIn(base, builder.TOTAL_ITEMS, item)
            self.assertTrue(builder._is_unit_suffix(suffix), item)

    def test_percent_rows_need_a_revenue_mix_phrase(self):
        self.assertAlmostEqual(
            builder._pct_weight("Milk Product Mix: 63%", "revenue_mix", "%", 63.0), 0.63)
        for item, category in (
            ("Mortgage share of total loan portfolio", "loan_mix"),
            ("Affordable housing segment share in project portfolio", "project_mix"),
            ("Revenue from sales to oil marketing companies percentage", "customer_concentration"),
            ("Mid income housing contribution", "revenue_mix"),
        ):
            self.assertEqual(builder._pct_weight(item, category, "%", 64.0), 0.0, item)


if __name__ == "__main__":
    unittest.main()
