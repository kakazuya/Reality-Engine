"""Fixture test for the point-in-time theme-universe builder.

The fixture is the shape production actually has: an ``ar_facts`` revenue-mix table
(``Revenue from Operations`` plus ``Revenue from Operations (Gold Jewellery)`` for the
same document, fiscal period, basis and unit) and deck rows.  It checks the weight, the
prior-year column being ignored, the materiality floor, the pivot flag, the expiry of a
stale weight, that a deck weight beats an AR weight and expires after four quarters,
that a deck slide's own segment revenue over its stated total is a weight, that deck
guidance / market-share rows are rejected, and that an acquisition announcement is a
candidate, not a member.

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

# The harness TMP dir (and any ``tmp*`` directory) is ACL-denied, and
# ``.tmp/universe-tests`` was left ACL-locked by an earlier run; ``.tmp/`` is ignored,
# so each run gets its own fresh directory name.
_TMP_ROOT = ROOT / ".tmp" / f"g3r2-{os.getpid()}"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)

ACME = "INE00ACME001"    # 90% of revenue is jewellery -> a weighted member
BETA = "INE00BETA001"    # 20% of revenue is jewellery -> below the floor, no membership
GAMMA = "INE00GAMMA01"   # NSE industry 'Gems Jewellery And Watches' -> unweighted member
DELTA = "INE00DELTA01"   # deck says jewellery is 60% of revenue
ZETA = "INE00ZETA001"    # segment table, no stated total -> segment_sum must reconcile
ETA = "INE00ETA0001"     # parent segment listed with its children -> must be rejected
THETA = "INE00THETA01"   # the PDF is someone else's AR -> the document does not name it
IOTA = "INE00IOTA001"    # a revenue row with no filing date -> no interval
KAPPA = "INE00KAPPA01"   # two weights with a hole between them -> the industry row fills it
MU = "INE00MU00001"      # a deck share beats an older AR weight
NU = "INE00NU00001"      # a deck share that expired; the AR weight applies again
XI = "INE00XI00001"      # deck guidance / market-share rows are never weights
OMICRON = "INE00OMICR1"  # a deck pivot: jewellery becomes the largest revenue line
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
        (ZETA, "ZETA", "500005", "Zeta Ornaments Limited"),
        (ETA, "ETA", "500006", "Eta Traders Limited"),
        (THETA, "THETA", "500007", "Theta Retail Limited"),
        (IOTA, "IOTA", "500008", "Iota Jewels Limited"),
        (KAPPA, "KAPPA", "500009", "Kappa Jewellers Limited"),
        (MU, "MU", "500010", "Mu Jewellers Limited"),
        (NU, "NU", "500011", "Nu Jewellers Limited"),
        (XI, "XI", "500012", "Xi Jewellers Limited"),
        (OMICRON, "OMICRON", "500013", "Omicron Jewellers Limited"),
    ])
    eq.executemany("INSERT INTO company_industry VALUES (?,?,?,?,?,?,?)", [
        (ACME, "ACME", "Consumer Durables", "Consumer Durables", "Packaging", "2026-01-01", "10-May-1995"),
        (BETA, "BETA", "Consumer Durables", "Consumer Durables", "Packaging", "2026-01-01", "10-May-1995"),
        (GAMMA, "GAMMA", "Consumer Durables", "Consumer Durables", "Gems Jewellery And Watches",
         "2026-01-01", "15-Mar-2016"),
        (DELTA, "DELTA", "Consumer Durables", "Consumer Durables", "Packaging", "2026-01-01", "10-May-1995"),
        (ZETA, "ZETA", "Consumer Durables", "Consumer Durables", "Packaging", "2026-01-01", "10-May-1995"),
        (ETA, "ETA", "Consumer Durables", "Consumer Durables", "Packaging", "2026-01-01", "10-May-1995"),
        (THETA, "THETA", "Consumer Durables", "Consumer Durables", "Packaging", "2026-01-01", "10-May-1995"),
        (IOTA, "IOTA", "Consumer Durables", "Consumer Durables", "Packaging", "2026-01-01", "10-May-1995"),
        (KAPPA, "KAPPA", "Consumer Durables", "Consumer Durables", "Gems Jewellery And Watches",
         "2026-01-01", "01-Jan-2015"),
        (MU, "MU", "Consumer Durables", "Consumer Durables", "Gems Jewellery And Watches",
         "2026-01-01", "15-Mar-2016"),
        (NU, "NU", "Consumer Durables", "Consumer Durables", "Gems Jewellery And Watches",
         "2026-01-01", "15-Mar-2016"),
        (OMICRON, "OMICRON", "Consumer Durables", "Consumer Durables", "Packaging",
         "2026-01-01", "10-May-1995"),
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
    n1 = "Acme Jewellery Limited: Revenue from Operations"
    rows = [
        # (doc, piece, isin, symbol, fy, filed, category, item, value, unit, period, basis, quote)
        (1, 11, ACME, "ACME", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations", 1000.0, "Rs crore", "FY19", "standalone", n1),
        (1, 11, ACME, "ACME", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations (Gold Jewellery)", 900.0, "Rs crore", "FY19", "standalone", n1),
        (1, 11, ACME, "ACME", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations (Silver)", 50.0, "Rs crore", "FY19", "standalone", n1),
        (1, 11, ACME, "ACME", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations (Others)", 50.0, "Rs crore", "FY19", "standalone", n1),
        # The prior-year comparative column: 400/500 = 0.8, and wrong for FY19.
        (1, 11, ACME, "ACME", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations (Gold Jewellery)", 400.0, "Rs crore", "FY18", "standalone", n1),
        (1, 11, ACME, "ACME", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations", 500.0, "Rs crore", "FY18", "standalone", n1),
        # A market statistic, not a company revenue mix: must never become a weight.
        (1, 12, ACME, "ACME", "2019-03-31", FILED_AT, "market_share",
         "Gold jewellery market share of revenue", 64.0, "%", "FY19", "standalone", n1),
        # Below the materiality floor.
        (2, 11, BETA, "BETA", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations", 1000.0, "Rs crore", "FY19", "standalone",
         "Beta Packaging Limited: Revenue from Operations"),
        (2, 11, BETA, "BETA", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations (Gold Jewellery)", 200.0, "Rs crore", "FY19", "standalone",
         "Beta Packaging Limited: Revenue from Operations"),
        # No stated total: the segment sum (600 + 300 + 100) reconciles to the revenue note.
        (4, 5, ZETA, "ZETA", "2019-03-31", FILED_AT, "segment",
         "Revenue from Operations - Gold Jewellery", 600.0, "Rs crore", "FY19", "standalone",
         "Zeta Ornaments Limited: segment information"),
        (4, 5, ZETA, "ZETA", "2019-03-31", FILED_AT, "segment",
         "Revenue from Operations - Silver", 300.0, "Rs crore", "FY19", "standalone",
         "Zeta Ornaments Limited: segment information"),
        (4, 5, ZETA, "ZETA", "2019-03-31", FILED_AT, "segment",
         "Revenue from Operations - Others", 100.0, "Rs crore", "FY19", "standalone",
         "Zeta Ornaments Limited: segment information"),
        (4, 5, ZETA, "ZETA", "2019-03-31", FILED_AT, "financial",
         "Revenue from contract with customers", 1000.0, "Rs crore", "FY19", "standalone",
         "Zeta Ornaments Limited: revenue note"),
        # A parent segment listed alongside its children sums to twice the stated revenue.
        (5, 6, ETA, "ETA", "2019-03-31", FILED_AT, "segment",
         "Revenue from Operations - Gold Jewellery", 100.0, "Rs crore", "FY19", "standalone",
         "Eta Traders Limited: segment information"),
        (5, 6, ETA, "ETA", "2019-03-31", FILED_AT, "segment",
         "Revenue from Operations - Gold Jewellery Retail", 60.0, "Rs crore", "FY19", "standalone",
         "Eta Traders Limited: segment information"),
        (5, 6, ETA, "ETA", "2019-03-31", FILED_AT, "segment",
         "Revenue from Operations - Gold Jewellery Wholesale", 40.0, "Rs crore", "FY19", "standalone",
         "Eta Traders Limited: segment information"),
        (5, 6, ETA, "ETA", "2019-03-31", FILED_AT, "financial",
         "Revenue from contract with customers", 100.0, "Rs crore", "FY19", "standalone",
         "Eta Traders Limited: revenue note"),
        # The wrong-file AR: filed as Theta's, but nothing inside it names Theta.
        (6, 7, THETA, "THETA", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations", 1000.0, "Rs crore", "FY19", "standalone",
         "Inadvertently the incorrect file of Annual Report was uploaded."),
        (6, 7, THETA, "THETA", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations (Gold Jewellery)", 900.0, "Rs crore", "FY19", "standalone",
         "Manufacturing of Gold Jewellery revenue contribution: 100.0 %"),
        # Iota's row has no filing date: it must never be dated from the fiscal-year end.
        (7, 8, IOTA, "IOTA", "2019-03-31", "", "financial",
         "Revenue from Operations", 1000.0, "Rs crore", "FY19", "standalone",
         "Iota Jewels Limited: Revenue from Operations"),
        (7, 8, IOTA, "IOTA", "2019-03-31", "", "financial",
         "Revenue from Operations (Gold Jewellery)", 900.0, "Rs crore", "FY19", "standalone",
         "Iota Jewels Limited: Revenue from Operations"),
        # Two disclosures with a hole between them; the industry row has to fill it.
        (8, 9, KAPPA, "KAPPA", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations", 1000.0, "Rs crore", "FY19", "standalone",
         "Kappa Jewellers Limited: Revenue from Operations"),
        (8, 9, KAPPA, "KAPPA", "2019-03-31", FILED_AT, "financial",
         "Revenue from Operations (Gold Jewellery)", 900.0, "Rs crore", "FY19", "standalone",
         "Kappa Jewellers Limited: Revenue from Operations"),
        (9, 9, KAPPA, "KAPPA", "2024-03-31", "2024-07-30T10:00:00", "financial",
         "Revenue from Operations", 1000.0, "Rs crore", "FY24", "standalone",
         "Kappa Jewellers Limited: Revenue from Operations"),
        (9, 9, KAPPA, "KAPPA", "2024-03-31", "2024-07-30T10:00:00", "financial",
         "Revenue from Operations (Gold Jewellery)", 950.0, "Rs crore", "FY24", "standalone",
         "Kappa Jewellers Limited: Revenue from Operations"),
        # A 55% AR weight, beaten later by a 60% deck share.
        (10, 20, MU, "MU", "2024-03-31", "2024-07-30T10:00:00", "financial",
         "Revenue from Operations", 1000.0, "Rs crore", "FY24", "standalone",
         "Mu Jewellers Limited: Revenue from Operations"),
        (10, 20, MU, "MU", "2024-03-31", "2024-07-30T10:00:00", "financial",
         "Revenue from Operations (Gold Jewellery)", 550.0, "Rs crore", "FY24", "standalone",
         "Mu Jewellers Limited: Revenue from Operations"),
        # A deck share from 2020, long expired by the 2022 AR: the AR weight must apply.
        (11, 21, NU, "NU", "2022-03-31", "2022-07-30T10:00:00", "financial",
         "Revenue from Operations", 1000.0, "Rs crore", "FY22", "standalone",
         "Nu Jewellers Limited: Revenue from Operations"),
        (11, 21, NU, "NU", "2022-03-31", "2022-07-30T10:00:00", "financial",
         "Revenue from Operations (Gold Jewellery)", 800.0, "Rs crore", "FY22", "standalone",
         "Nu Jewellers Limited: Revenue from Operations"),
    ]
    ar.executemany(
        "INSERT INTO ar_facts(doc_id, piece, isin, symbol, fiscal_year, filed_at, category, item,"
        " value, unit, period, basis, quote) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    ar.execute("INSERT INTO ar_facts_fts(ar_facts_fts) VALUES('rebuild')")
    ar.commit()
    ar.close()

    dk = sqlite3.connect(root / "deck_figures.db")
    dk.executescript(
        "CREATE TABLE facts(sha256 TEXT, page_no INTEGER, prompt_version TEXT, model TEXT,"
        " line_no INTEGER, metric TEXT, period TEXT, raw_number TEXT, value REAL, unit TEXT,"
        " is_final INTEGER);"
        "CREATE INDEX ix_facts_page ON facts(sha256, page_no);"
        "CREATE VIRTUAL TABLE facts_metric_fts USING fts5(metric, content='facts',"
        " content_rowid='rowid');"
        "CREATE TABLE deck_sources(source TEXT, source_id TEXT, symbol TEXT, isin TEXT,"
        " exch_code TEXT, known_at TEXT, title TEXT, url TEXT, local_path TEXT, sha256 TEXT,"
        " size_bytes INTEGER, status TEXT, error TEXT, fetched_at TEXT);"
    )
    # (sha, page, line, metric, period, raw_number, value, unit)
    deck_facts = [
        ("sha-delta", 12, 3, "Gold jewellery revenue mix", "FY25", "60", 60.0, "%"),
        ("sha-mu", 5, 3, "Gold jewellery revenue mix", "FY25", "60", 60.0, "%"),
        ("sha-nu", 4, 2, "Gold jewellery revenue mix", "FY20", "65", 65.0, "%"),
        # Not weights: one is guidance and one is a market share, not company revenue.
        ("sha-xi", 3, 3, "Gold jewellery revenue mix guidance", "FY25", "70", 70.0, "%"),
        ("sha-xi", 3, 4, "Gold jewellery market share of revenue", "FY25", "64", 64.0, "%"),
        # Two decks of segment revenue over the deck's own total revenue.
        ("sha-omicron-1", 5, 1, "Jewellery Revenue", "FY25", "500", 500.0, "Rs crore"),
        ("sha-omicron-1", 5, 2, "Packaging Revenue", "FY25", "850", 850.0, "Rs crore"),
        ("sha-omicron-1", 5, 3, "Other Revenue", "FY25", "50", 50.0, "Rs crore"),
        ("sha-omicron-1", 5, 4, "Total Revenue", "FY25", "1,400", 1400.0, "Rs crore"),
        ("sha-omicron-2", 6, 1, "Jewellery Revenue", "FY25", "1,500", 1500.0, "Rs crore"),
        ("sha-omicron-2", 6, 2, "Packaging Revenue", "FY25", "400", 400.0, "Rs crore"),
        ("sha-omicron-2", 6, 3, "Other Revenue", "FY25", "100", 100.0, "Rs crore"),
        ("sha-omicron-2", 6, 4, "Total Revenue", "FY25", "2,000", 2000.0, "Rs crore"),
    ]
    dk.executemany(
        "INSERT INTO facts(sha256, page_no, prompt_version, model, line_no, metric, period,"
        " raw_number, value, unit, is_final) VALUES (?,?,'v1','m',?,?,?,?,?,?,1)",
        [(sha, page, line, metric, period, raw, value, unit)
         for sha, page, line, metric, period, raw, value, unit in deck_facts])
    dk.execute("INSERT INTO facts_metric_fts(facts_metric_fts) VALUES('rebuild')")
    dk.executemany(
        "INSERT INTO deck_sources(source, symbol, isin, known_at, sha256) VALUES (?,?,?,?,?)", [
            ("bse", "DELTA", DELTA, "2025-05-20T18:00:00", "sha-delta"),
            ("bse", "MU", MU, "2025-02-10T18:00:00", "sha-mu"),
            ("bse", "NU", NU, "2020-05-20T18:00:00", "sha-nu"),
            ("bse", "XI", XI, "2025-03-01T18:00:00", "sha-xi"),
            ("bse", "OMICRON", OMICRON, "2025-02-10T18:00:00", "sha-omicron-1"),
            ("bse", "OMICRON", OMICRON, "2025-05-15T18:00:00", "sha-omicron-2"),
        ])
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
        self.assertEqual(delta[0][5], "deck")
        self.assertEqual(delta[0][2], "2025-05-20")
        self.assertEqual(delta[0][3], "2026-05-20")   # four quarters, not two fiscal years

    def test_deck_weight_beats_an_older_ar_weight(self):
        self._run()
        rows = sorted(self._rows(MU), key=lambda row: row[2])
        deck = [row for row in rows if row[5] == "deck"]
        self.assertEqual(len(deck), 1)
        self.assertEqual((deck[0][2], deck[0][3]), ("2025-02-10", "2026-02-10"))
        self.assertAlmostEqual(deck[0][4], 0.6, places=4)
        segment = [row for row in rows if row[5] == "segment"]
        # The AR weight is clipped where the deck takes over and resumes after it expires.
        self.assertEqual(segment[0][3], "2025-02-10")
        self.assertEqual((segment[-1][2], segment[-1][3]), ("2026-02-10", "2026-03-31"))
        self.assertAlmostEqual(segment[-1][4], 0.55, places=4)

    def test_expired_deck_falls_back_to_the_ar_weight(self):
        self._run()
        rows = sorted(self._rows(NU), key=lambda row: row[2])
        deck = next(row for row in rows if row[5] == "deck")
        self.assertEqual((deck[2], deck[3]), ("2020-05-20", "2021-05-20"))
        self.assertAlmostEqual(deck[4], 0.65, places=4)
        # Four quarters later the deck is gone and the 2022 AR weight applies.
        segment = next(row for row in rows if row[5] == "segment")
        self.assertEqual(segment[2], "2022-07-30")
        self.assertAlmostEqual(segment[4], 0.8, places=4)
        self.assertFalse([row for row in rows
                          if row[5] == "deck" and row[2] <= "2022-07-30" < row[3]])

    def test_deck_guidance_and_market_share_are_rejected(self):
        self._run()
        self.assertEqual(self._rows(XI), [])

    def test_deck_pivot_fires_on_the_transition(self):
        self._run()
        rows = [row for row in self._rows(OMICRON) if row[5] == "deck"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0][2], rows[0][3]), ("2025-05-15", "2026-05-15"))
        self.assertAlmostEqual(rows[0][4], 0.75, places=4)   # 1,500 / 2,000 of the deck
        self.assertEqual(rows[0][7], 1)   # it became the largest line; deck 1 was not

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

    def test_segment_sum_reconciles_without_a_stated_total(self):
        self._run()
        rows = self._rows(ZETA)
        self.assertEqual(len(rows), 1)
        _theme, _isin, since, until, weight, source, method, pivot, _ev, quote = rows[0]
        self.assertAlmostEqual(weight, 0.6, places=4)   # 600 / (600 + 300 + 100)
        self.assertEqual(source, "segment_sum")
        self.assertEqual(method, "segment")
        self.assertEqual(pivot, 1)                      # 3 siblings, sum == stated revenue
        self.assertEqual((since, until), ("2019-07-30", "2021-03-31"))
        self.assertIn("reconciles to", quote)           # the figure is in the evidence
        self.assertIn("1,000.00", quote)

    def test_parent_and_child_double_count_is_rejected(self):
        self._run()
        # 100 + 60 + 40 = 200 against a stated 100: the sum does not reconcile, so no weight.
        self.assertEqual(self._rows(ETA), [])

    def test_document_must_name_the_company(self):
        self._run()
        # Right company field, wrong file inside: the weight must not exist (LAKESHORE).
        self.assertEqual(self._rows(THETA), [])

    def test_weight_without_a_disclosure_date_is_dropped(self):
        self._run()
        self.assertEqual(self._rows(IOTA), [])

    def test_gaps_between_weights_are_filled(self):
        self._run()
        rows = sorted(self._rows(KAPPA), key=lambda row: row[2])
        self.assertEqual([row[2] for row in rows],
                         ["2015-01-01", "2019-07-30", "2021-03-31", "2024-07-30", "2026-03-31"])
        self.assertEqual([row[4] is not None for row in rows], [False, True, False, True, False])
        self.assertEqual([row[5] for row in rows],
                         ["industry", "segment", "industry", "segment", "industry"])
        for previous, following in zip(rows, rows[1:]):
            # Half-open intervals: every chain hands over exactly, no hole and no overlap.
            self.assertEqual(previous[3], following[2])

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
        # The SEBI "Principal Business Activity" disclosure is a revenue mix (HATSUN 93.59%).
        self.assertAlmostEqual(
            builder._pct_weight("Principal Business Activity: Milk and Milk Products",
                                "business_activity", "%", 93.59), 0.9359)
        # "<product> turnover %" is a revenue mix (HERITGFOOD "Milk turnover %" 65.47).
        self.assertAlmostEqual(
            builder._pct_weight("Milk turnover", "revenue_mix", "%", 65.47), 0.6547)
        # Portfolio words are allowed in the company's own revenue mix.
        self.assertAlmostEqual(
            builder._pct_weight("Interest income from housing loans % of revenue",
                                "revenue_mix", "%", 90.0), 0.90)
        for item, category in (
            ("Mortgage contribution to loan portfolio", "loan_composition"),
            ("Affordable housing segment share in project portfolio", "project_mix"),
            ("Revenue from sales to oil marketing companies percentage", "customer_concentration"),
            ("Market share of South in Indian Jewellery Market", "industry"),
            ("Mid income housing contribution", "revenue_mix"),
        ):
            self.assertEqual(builder._pct_weight(item, category, "%", 64.0), 0.0, item)

    def test_pivot_needs_one_reconciling_segment_table(self):
        self.assertTrue(builder._pivot({"petroleum": 60.0, "gas": 30.0, "other": 10.0}, 60.0, 100.0))
        # Two siblings is not a segment table.
        self.assertFalse(builder._pivot({"petroleum": 60.0, "gas": 40.0}, 60.0, 100.0))
        # The siblings must add up to the stated total (parent + children = 140 of 200).
        self.assertFalse(builder._pivot({"petroleum": 60.0, "gas": 40.0, "other": 40.0}, 60.0, 200.0))
        # Totals, inter-segment and unallocated rows never join the sibling set.
        self.assertEqual(
            builder._siblings([("total", 100.0), ("petroleum", 60.0),
                               ("less inter segment", 5.0), ("gas", 40.0)]),
            {"petroleum": 60.0, "gas": 40.0})


if __name__ == "__main__":
    unittest.main()
