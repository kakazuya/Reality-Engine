"""Fixture tests for the macro_claim_target pilot (G10 / policy_target).

The fixture is a tiny data root written to a temp dir: four policy_events sources
(Union Budget, RBI, PIB, a customs notification), seven held companies with their
basic industries and a price window, plus one state budget.  The pilot DB is built
from that fixture only; no live database is read and nothing outside the temp dir
is written.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import unittest
import uuid
from pathlib import Path
from unittest import mock

from reality_engine.pilot import macro_claims
from reality_engine.query import load_planners, route
from reality_engine.query.ctx import Ctx
from reality_engine.query.planners import ripple

AS_OF = "2026-06-30"
QUOTA = {"budget": 6, "rbi": 1, "pib": 3, "tariff": 1}
CEMCO = "INE000A01001"
BANKA = "INE000A01002"
STEELX = "INE000A01003"
TEXCO = "INE000A01004"
POWCO = "INE000A01005"
ROADCO = "INE000A01006"
PHARMA = "INE000A01007"
AIRCLEAN = "INE000A01008"

COMPANIES = [
    (CEMCO, "CEMCO", "500001", "Cemco Cement Limited", "Construction Materials",
     "Construction Materials", "LARGE"),
    (BANKA, "BANKA", "500002", "Banka Bank Limited", "Financial Services",
     "Financial Services", "LARGE"),
    (STEELX, "STEELX", "500003", "Steelx Industries Limited", "Capital Goods",
     "Capital Goods", "MID"),
    (TEXCO, "TEXCO", "500004", "Texco Textiles Limited", "Textiles", "Textiles", "MID"),
    (POWCO, "POWCO", "500005", "Powco Power Limited", "Power", "Power", "LARGE"),
    (ROADCO, "ROADCO", "500006", "Roadco Infra Limited", "Construction",
     "Construction", "SMALL"),
    (PHARMA, "PHARMA", "500007", "Pharma Holdings Limited", "Healthcare",
     "Healthcare", "MID"),
    (AIRCLEAN, "AIRCLEAN", "500008", "Tenneco Clean Air India Limited", "Capital Goods",
     "Capital Goods", "SMALL"),
]
INDUSTRY = [
    (CEMCO, "CEMCO", "Construction Materials", "Construction Materials",
     "Cement & Cement Products"),
    (BANKA, "BANKA", "Financial Services", "Financial Services", "Private Sector Bank"),
    (STEELX, "STEELX", "Capital Goods", "Capital Goods", "Iron & Steel Products"),
    (TEXCO, "TEXCO", "Textiles", "Textiles", "Other Textile Products"),
    (POWCO, "POWCO", "Power", "Power", "Power Generation"),
    (ROADCO, "ROADCO", "Construction", "Construction", "Civil Construction"),
    (PHARMA, "PHARMA", "Healthcare", "Healthcare", "Pharmaceuticals"),
    (AIRCLEAN, "AIRCLEAN", "Capital Goods", "Capital Goods", "Auto Components & Equipments"),
]
DOCS = [
    (1, "Union Budget 2026-27 Speech", "Union_Budget", "Ministry of Finance (GoI)",
     "2026-02-01"),
    (2, "RBI Governor Statement 2026", "RBI_Monetary_Policy", "Reserve Bank of India",
     "2026-04-05"),
    (3, "PIB release: housing push", "PIB_Press_Release", "Ministry of Housing & Urban Affairs",
     "2026-03-01"),
    (4, "CBIC notification 12/2025", "CBIC_Notification", "Central Board of Indirect Taxes",
     "2025-06-01"),
    (5, "Tamil Nadu Budget 2024-25", "State_Budget_Tamil_Nadu", "Tamil Nadu Finance Dept",
     "2024-06-01"),
    (6, "Union Budget 2024-25 Speech", "Union_Budget", "Ministry of Finance (GoI)",
     "2024-07-23"),
    (7, "Union Budget 2025-26 Speech", "Union_Budget", "Ministry of Finance (GoI)",
     "2025-02-01"),
]

COLUMNS = ("id, source_kind, source_id, section, published_at, title, policy_name, "
           "instrument, direction_for_industry, sectors, companies, products, "
           "amount_inr_crore, unit, new_value, old_value, effective_date, end_date, quote, "
           "quote_ok")
CLAIMS = [
    # id, source_kind, source_id, section, published_at, title, policy_name, instrument,
    # direction, sectors, companies, products, amount, unit, new, old, eff, end, quote, ok
    (101, "doc", "1", 0, "2026-02-01", "Union_Budget: Union Budget 2026-27 Speech",
     "Cement and steel capex push", "capex_sanction", "positive",
     '["cement", "steel"]', "[]", "[]", 1200.0, "INR crore", None, None,
     "2026-04-01", None, "rs 1,200 crore for cement and steel capacity", 1),
    (102, "doc", "1", 1, "2026-05-02", "Union_Budget: Union Budget 2026-27 Speech",
     "Repo-linked lending package", "monetary", "positive",
     '["banking", "financial services"]', "[]", "[]", None, "%",
     "repo rate cut 25 bps", None, "2026-04-01", None,
     "repo rate cut of 25 bps to 5.50 per cent", 1),
    (103, "doc", "2", 0, "2026-04-05", "RBI_Monetary_Policy: RBI Statement",
     "Higher risk weights on unsecured credit", "monetary", "negative",
     '["banking"]', "[]", "[]", None, None, None, None, "2026-05-01", None,
     "higher risk weights for unsecured personal loans, applicable to all fresh loans", 1),
    (104, "pib", "9001", 0, "2026-03-01", "PIB release: housing push",
     "PMAY-U 2.0 additional houses", "scheme", "positive",
     '["construction", "cement"]', '["Cemco Cement"]', "[]", None, None, None, None,
     None, None, "1.93 lakh additional houses approved", 1),
    (105, "doc", "4", 0, "2025-06-01", "CBIC notification 12/2025",
     "Customs duty cut on mobile phone parts", "customs_duty", "positive",
     '["electronics"]', "[]", '["mobile phones", "cellular mobile components"]',
     None, None, "20 to 15 per cent", None, "2025-07-01", None,
     "bcd on cellular mobile phone and parts cut, HS 8517", 1),
    (106, "doc", "1", 2, "2026-05-03", "Union_Budget: Union Budget 2026-27 Speech",
     "General package", "scheme", "neutral", '["all sectors"]', "[]", "[]", None, None,
     None, None, None, None, "general package across the economy", 1),
    (107, "doc", "1", 3, "2026-07-01", "Union_Budget: Union Budget 2026-27 Speech",
     "Cement package announced later", "capex_sanction", "positive", '["cement"]',
     "[]", "[]", None, None, None, None, None, None,
     "cement package announced after the decision date", 1),
    (108, "doc", "6", 0, "2024-07-23", "Union_Budget: Union Budget 2024-25 Speech",
     "Roads capital outlay", "capex_sanction", "positive", '["roads"]', "[]", "[]",
     500.0, "INR crore", None, None, "2024 - 25", None,
     "rs 500 crore for roads and bridges", 1),
    (109, "doc", "7", 0, "2025-02-01", "Union_Budget: Union Budget 2025-26 Speech",
     "Power distribution reform", "subsidy", "positive", '["power"]', "[]", "[]",
     None, None, None, None, "2025-26", None, "power distribution reform allocation", 1),
    (110, "doc", "5", 0, "2024-06-01", "State_Budget_Tamil_Nadu: TN Budget 2024-25",
     "Textile park allocation", "capex_sanction", "positive", '["textiles"]', "[]",
     "[]", 250.0, "INR crore", None, None, "2024-25", None,
     "rs 250 crore for the textile park", 1),
    (111, "pib", "9002", 0, "2026-03-02", "PIB release: health mission",
     "Health mission allocation", "scheme", "positive", '["healthcare"]', "[]", "[]",
     4500.0, "INR crore", None, None, "2026-04-01", None,
     "rs 4,500 crore to the national health mission", 1),
    # A plain-text sectors value (no JSON brackets): the pre-pilot RIPPLE fallback splits
    # on [,;|], so this is the claim that proves the fallback still answers.
    (112, "pib", "9001", 1, "2026-05-20", "PIB release: housing push",
     "Lending push for financial services", "regulation", "positive",
     "financial services", "[]", "[]", None, None, None, None, "2026-06-01", None,
     "lending push across financial services", 1),
    # A flagged row: kept by the full run, excluded from the stratified pilot.
    (113, "doc", "1", 4, "2026-01-15", "Union_Budget: Union Budget 2026-27 Speech",
     "Water supply package", "capex_sanction", "positive", '["water supply"]', "[]",
     "[]", None, None, None, None, None, None, "water supply package", 0),
]


def _make(path: Path, ddl: list[str], rows: list[tuple[str, tuple]] = ()) -> None:
    con = sqlite3.connect(path)
    for statement in ddl:
        con.execute(statement)
    for statement, params in rows:
        con.execute(statement, params)
    con.commit()
    con.close()


def build_root(root: Path) -> None:
    ei = root / "equity_intelligence.db"
    _make(ei, [
        "CREATE TABLE raw_documents(doc_id INTEGER, title TEXT, source_type TEXT, "
        "creator_or_ministry TEXT, published_date TEXT)",
        "CREATE TABLE pib_releases(prid INTEGER, ministry TEXT)",
        "CREATE TABLE policy_events(id INTEGER, source_kind TEXT, source_id TEXT, "
        "section INTEGER, published_at TEXT, title TEXT, policy_name TEXT, instrument TEXT, "
        "direction_for_industry TEXT, sectors TEXT, companies TEXT, products TEXT, "
        "amount_inr_crore REAL, unit TEXT, new_value TEXT, old_value TEXT, "
        "effective_date TEXT, end_date TEXT, quote TEXT, quote_ok INTEGER)",
        "CREATE TABLE master_companies(isin TEXT, nse_symbol TEXT, bse_code TEXT, "
        "company_name TEXT, industry TEXT, sector TEXT, market_cap_tier TEXT, "
        "is_active INTEGER, is_nifty500 INTEGER)",
        "CREATE TABLE company_industry(isin TEXT, symbol TEXT, series TEXT, macro TEXT, "
        "sector TEXT, industry TEXT, basic_industry TEXT, index_list TEXT, "
        "listing_date TEXT, fetched_at TEXT)",
        "CREATE TABLE daily_price_delivery(date TEXT, symbol TEXT, isin TEXT, open REAL, "
        "high REAL, low REAL, close REAL, prev_close REAL, change_pct REAL, "
        "total_volume INTEGER, turnover_lacs REAL, num_trades INTEGER, "
        "deliverable_volume INTEGER, delivery_pct REAL, rsi_14 REAL)",
    ], [(f"INSERT INTO raw_documents VALUES (?,?,?,?,?)", row) for row in DOCS] + [
        ("INSERT INTO pib_releases VALUES (?,?)",
         (9001, "Ministry of Housing & Urban Affairs")),
        ("INSERT INTO pib_releases VALUES (?,?)",
         (9002, "Ministry of Health and Family Welfare")),
    ] + [(f"INSERT INTO policy_events ({COLUMNS}) VALUES ({','.join('?' * 20)})", row)
         for row in CLAIMS])
    con = sqlite3.connect(ei)
    for row in COMPANIES:
        con.execute("INSERT INTO master_companies VALUES (?,?,?,?,?,?,?,1,1)", row)
    for isin, symbol, macro, sector, basic in INDUSTRY:
        con.execute("INSERT INTO company_industry VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (isin, symbol, "EQ", macro, sector, basic, basic, None, None, None))
    for day in ("2026-03-31", "2026-04-01", "2026-04-02", "2026-04-06", "2026-04-08",
                "2026-04-10", "2026-05-04", "2026-06-30"):
        for index, row in enumerate(COMPANIES):
            con.execute("INSERT INTO daily_price_delivery VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (day, row[1], row[0], 100, 101, 99, 100 + index, 99, 1.0, 1000,
                         1.0, 10, 500, 50.0, 55.0))
    con.commit()
    con.close()


def build_pilot(root: Path) -> dict:
    return macro_claims.build(root / "pilot", root / "equity_intelligence.db", QUOTA)


def case(**over) -> dict:
    base = {
        "mid": "T9001", "source_bank": "test", "family": [18], "entity_level": "industry",
        "answer_kind": "ranking", "archetype": None, "question": "steel policy targets",
        "entities": [], "period": None, "as_of": AS_OF, "template": None,
        "rubric": {"required_evidence": ["macro_claim_target"]},
        "case_status": "needs_new_table:macro_claim_target",
    }
    base.update(over)
    return base


def temp_root(prefix: str = "macro_pilot_") -> Path:
    """A writable scratch dir: mkdtemp's private DACL denies writes in this sandbox,
    while a plain mkdir under the worktree's .tmp inherits the workspace ACE."""
    base = Path(__file__).resolve().parents[2] / ".tmp"
    base.mkdir(parents=True, exist_ok=True)
    root = base / (prefix + uuid.uuid4().hex[:10])
    root.mkdir()
    return root


class PilotFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = temp_root()
        build_root(cls.tmp)
        cls.summary = build_pilot(cls.tmp)
        cls.db = cls.tmp / "pilot" / macro_claims.DB_NAME

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def rows(self, sql: str, params: tuple = ()) -> list[tuple]:
        con = sqlite3.connect(self.db)
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()


class TestClaimFields(PilotFixture):
    def test_paraphrase_is_at_most_30_words(self):
        for (paraphrase,) in self.rows("SELECT paraphrase FROM macro_claim"):
            self.assertTrue(paraphrase)
            self.assertLessEqual(len(str(paraphrase).split()), 30, paraphrase)

    def test_direction_magnitude_and_effective_date(self):
        magnitude_value, magnitude_unit, direction, effective = self.rows(
            "SELECT magnitude_value, magnitude_unit, direction, effective_date "
            "FROM macro_claim WHERE claim_id=101")[0]
        self.assertEqual(magnitude_unit, "INR_CRORE")
        self.assertAlmostEqual(magnitude_value, 1200.0)
        self.assertEqual(direction, "positive")
        self.assertEqual(effective, "2026-04-01")
        # bps in the quote become PERCENT; fiscal-year text becomes the FY start.
        self.assertEqual(self.rows("SELECT magnitude_unit FROM macro_claim WHERE "
                                   "claim_id=102")[0][0], "PERCENT")
        self.assertEqual(self.rows("SELECT magnitude_value FROM macro_claim WHERE "
                                   "claim_id=102")[0][0], 0.25)
        self.assertEqual(self.rows("SELECT effective_date FROM macro_claim WHERE "
                                   "claim_id=108")[0][0], "2024-04-01")
        self.assertEqual(self.rows("SELECT direction FROM macro_claim WHERE "
                                   "claim_id=103")[0][0], "negative")

    def test_known_at_comes_from_publication(self):
        known = self.rows("SELECT known_at FROM macro_claim WHERE claim_id=101")[0][0]
        self.assertEqual(known[:10], "2026-02-01")

    def test_conditions_extracted_from_the_quote(self):
        stored = self.rows("SELECT conditions FROM macro_claim WHERE claim_id=103")[0][0]
        self.assertIn("applicable to all fresh loans", stored)
        self.assertIsNone(self.rows("SELECT conditions FROM macro_claim WHERE "
                                    "claim_id=101")[0][0])
        self.assertIsNone(macro_claims.conditions({"quote": "rs 1,200 crore for capacity"}))
        found = macro_claims.conditions(
            {"quote": "the cut applies to all loans. it is subject to review."})
        self.assertIn("subject to review", found)

    def test_policy_type_map(self):
        self.assertEqual(macro_claims.policy_type({"instrument": "customs_duty"}), "tariff")
        self.assertEqual(macro_claims.policy_type({"instrument": "pli_incentive"}), "pli")
        self.assertEqual(macro_claims.policy_type({"instrument": "monetary"}), "rate")
        self.assertEqual(macro_claims.policy_type({"instrument": "scheme"}), "other")

    def test_iso_effective(self):
        self.assertEqual(macro_claims.iso_effective("2024-07-23"), "2024-07-23")
        self.assertEqual(macro_claims.iso_effective("2024 - 25"), "2024-04-01")
        self.assertEqual(macro_claims.iso_effective("not a date"), None)


class TestTargetMap(PilotFixture):
    def test_sector_alias_resolves_to_basic_industry(self):
        rows = self.rows("SELECT target_kind, target_id FROM macro_claim_target "
                         "WHERE claim_id=101 ORDER BY target_kind, target_id")
        self.assertIn(("basic_industry", "Cement & Cement Products"), rows)
        self.assertIn(("basic_industry", "Iron & Steel Products"), rows)

    def test_state_budget_emits_state_and_sector(self):
        rows = self.rows("SELECT target_kind, target_id FROM macro_claim_target "
                         "WHERE claim_id=110 ORDER BY target_kind, target_id")
        self.assertIn(("sector", "Textiles"), rows)
        self.assertIn(("state", "Tamil Nadu"), rows)

    def test_named_company_resolves_to_isin(self):
        rows = self.rows("SELECT target_kind, target_id FROM macro_claim_target "
                         "WHERE claim_id=104")
        self.assertIn(("isin", CEMCO), rows)

    def test_hs_chapter_and_product_maps(self):
        firms = macro_claims.CompanyIndex([])
        hs = macro_claims.claim_targets(
            {"instrument": "customs_duty", "products": "[]", "quote": "",
             "policy_name": "duty on HS 7208 flat rolled products",
             "sectors": "[]", "companies": "[]",
             "direction_for_industry": "positive"}, firms)
        self.assertIn(("basic_industry", "Iron & Steel Products",
                       "positive", "HS chapter 72"), hs)
        chapter = macro_claims.claim_targets(
            {"instrument": "customs_duty", "products": "chapter 30 imports",
             "quote": "", "policy_name": "", "sectors": "[]", "companies": "[]",
             "direction_for_industry": "positive"}, firms)
        kinds = {(kind, ident) for kind, ident, _, _ in chapter}
        self.assertIn(("basic_industry", "Pharmaceuticals"), kinds)

    def test_sector_product_terms_do_not_fire_on_a_plain_allocation(self):
        targets = macro_claims.claim_targets(
            {"instrument": "scheme", "products": '["mobile phones"]', "quote": "",
             "policy_name": "housing allocation", "sectors": '["housing"]',
             "companies": "[]", "direction_for_industry": "positive"},
            macro_claims.CompanyIndex([]))
        kinds = {(kind, ident) for kind, ident, _, _ in targets}
        self.assertNotIn(("basic_industry", "Consumer Electronics"), kinds)
        self.assertIn(("sector", "Realty"), kinds)

    def test_company_resolver_refuses_substring_and_short_names(self):
        index = macro_claims.CompanyIndex([
            {"isin": AIRCLEAN, "nse_symbol": "AIRCLEAN",
             "company_name": "Tenneco Clean Air India Limited"},
            {"isin": CEMCO, "nse_symbol": "CEMCO", "company_name": "Cemco Cement Limited"},
        ])
        self.assertIsNone(index.resolve("Air India"))
        self.assertIsNone(index.resolve("LIC"))
        self.assertEqual(index.resolve("Cemco Cement"), CEMCO)
        self.assertEqual(index.resolve("CEMCO"), CEMCO)


class TestBuild(PilotFixture):
    def test_schema_is_the_design_ddl_plus_two_pilot_columns(self):
        columns = {row[1] for row in self.rows("PRAGMA table_info(macro_claim)")}
        self.assertTrue({"claim_id", "doc_id", "policy_type", "direction", "quote",
                         "paraphrase", "known_at", "stratum"} <= columns)
        targets = {row[1] for row in self.rows("PRAGMA table_info(macro_claim_target)")}
        self.assertEqual(targets, {"claim_id", "target_kind", "target_id", "direction",
                                   "weight", "evidence"})
        view = self.rows("SELECT COUNT(*) FROM policy_target")
        self.assertEqual(view[0][0], self.rows("SELECT COUNT(*) FROM macro_claim_target")[0][0])

    def test_stratified_counts(self):
        self.assertEqual(self.summary["claims"], 11)
        self.assertEqual(self.summary["by_stratum"]["budget"], 5)
        self.assertEqual(self.summary["by_stratum"]["rbi"], 1)
        self.assertEqual(self.summary["by_stratum"]["pib"], 3)
        self.assertEqual(self.summary["by_stratum"]["tariff"], 1)
        self.assertEqual(self.summary["by_stratum"]["state_budget"], 1)
        years = [row[0] for row in self.rows(
            "SELECT DISTINCT substr(d.known_at, 1, 4) FROM macro_claim c "
            "JOIN macro_doc d ON d.doc_id = c.doc_id WHERE d.doc_type='union_budget' "
            "ORDER BY 1")]
        self.assertEqual(years, ["2024", "2025", "2026"])

    def test_every_claim_has_a_doc_and_every_target_a_claim(self):
        orphans = self.rows(
            "SELECT COUNT(*) FROM macro_claim c LEFT JOIN macro_doc d "
            "ON d.doc_id = c.doc_id WHERE d.doc_id IS NULL")[0][0]
        self.assertEqual(orphans, 0)
        orphan_targets = self.rows(
            "SELECT COUNT(*) FROM macro_claim_target t LEFT JOIN macro_claim c "
            "ON c.claim_id = t.claim_id WHERE c.claim_id IS NULL")[0][0]
        self.assertEqual(orphan_targets, 0)

    def test_build_is_deterministic(self):
        second = self.tmp / "pilot2"
        macro_claims.build(second, self.tmp / "equity_intelligence.db", QUOTA)
        con = sqlite3.connect(self.db)
        other = sqlite3.connect(second / macro_claims.DB_NAME)
        try:
            for table in ("macro_doc", "macro_claim", "macro_claim_target"):
                one = con.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
                two = other.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
                self.assertEqual(one, two, table)
        finally:
            con.close()
            other.close()
            shutil.rmtree(second, ignore_errors=True)

    def test_meta_file_is_written(self):
        meta = json.loads((self.tmp / "pilot" / "macro_pilot_meta.json").read_text())
        self.assertEqual(meta["claims"], 11)
        self.assertGreater(meta["targets"], 0)


class TestEffectiveDateProse(unittest.TestCase):
    """Prose effective dates get a date and a pit_conf, so the market window can run."""

    def test_end_of_year(self):
        self.assertEqual(macro_claims.effective_date("end of 2026"), ("2026-12-31", 0.6))
        self.assertEqual(macro_claims.effective_date("by end-2027"), ("2027-12-31", 0.6))

    def test_month_without_a_year_uses_known_at(self):
        self.assertEqual(macro_claims.effective_date("from April", "2025-03-15"),
                         ("2025-04-01", 0.55))
        self.assertEqual(macro_claims.effective_date("April", "2025-06-01"),
                         ("2025-04-01", 0.55))
        self.assertEqual(macro_claims.effective_date("from April", None), (None, 0.0))

    def test_month_year_and_dotted_date(self):
        self.assertEqual(macro_claims.effective_date("June 2021"), ("2021-06-01", 0.85))
        self.assertEqual(macro_claims.effective_date("1. 10. 2024"), ("2024-10-01", 0.95))

    def test_fiscal_span_annotation_and_prefix(self):
        self.assertEqual(macro_claims.effective_date("2026-31"), ("2026-04-01", 0.9))
        self.assertEqual(macro_claims.effective_date("BE 2026-27"), ("2026-04-01", 0.9))
        self.assertEqual(macro_claims.effective_date("2022-23 (as written)"),
                         ("2022-04-01", 0.9))

    def test_next_financial_year_and_bare_year(self):
        self.assertEqual(macro_claims.effective_date("next financial year", "2025-02-01"),
                         ("2026-04-01", 0.55))
        self.assertEqual(macro_claims.effective_date("2021"), ("2021-04-01", 0.55))

    def test_iso_effective_keeps_its_string_contract(self):
        self.assertEqual(macro_claims.iso_effective("2024 - 25"), "2024-04-01")
        self.assertEqual(macro_claims.iso_effective("not a date"), None)


class TestAliasRecallFixes(PilotFixture):
    """Sector terms the independent 80-claim check found unmapped."""

    def kinds(self, term: str) -> set[tuple[str, str]]:
        targets = macro_claims.claim_targets(
            {"instrument": "scheme", "sectors": json.dumps([term]), "companies": "[]",
             "products": "[]", "quote": "", "direction_for_industry": "positive"},
            macro_claims.CompanyIndex([]))
        return {(kind, ident) for kind, ident, _, _ in targets}

    def test_new_sector_aliases(self):
        self.assertIn(("basic_industry", "Seafood"), self.kinds("fisheries"))
        self.assertIn(("sector", "Automobile and Auto Components"), self.kinds("auto"))
        self.assertIn(("sector", "Information Technology"), self.kinds("IT / AI"))
        self.assertIn(("basic_industry", "Aerospace & Defense"), self.kinds("Drones"))
        self.assertIn(("basic_industry", "Gems Jewellery And Watches"),
                      self.kinds("jewellery"))
        self.assertIn(("basic_industry", "Logistics Solution Provider"),
                      self.kinds("Transportation"))
        self.assertIn(("basic_industry", "Other Bank"), self.kinds("Co-operative Banking"))

    def test_banking_and_financial_services_keeps_the_banking_half(self):
        kinds = self.kinds("Banking & Financial Services")
        self.assertIn(("sector", "Financial Services"), kinds)
        self.assertIn(("basic_industry", "Public Sector Bank"), kinds)
        self.assertIn(("basic_industry", "Other Bank"), kinds)


class TestAllClaimsBuild(PilotFixture):
    def test_all_mode_keeps_and_flags_quote_ok_zero(self):
        summary = macro_claims.build(self.tmp / "all", self.tmp / "equity_intelligence.db",
                                     QUOTA, all_claims=True, db_name="macro_all.db")
        self.assertEqual(summary["claims"], len(CLAIMS))
        self.assertEqual(summary["quote_ok"], {"1": len(CLAIMS) - 1, "0": 1})
        con = sqlite3.connect(self.tmp / "all" / "macro_all.db")
        try:
            flags = dict(con.execute("SELECT claim_id, quote_ok FROM macro_claim"))
            effective = con.execute(
                "SELECT effective_date, effective_pit_conf FROM macro_claim "
                "WHERE claim_id=101").fetchone()
        finally:
            con.close()
        self.assertEqual(flags[113], 0)
        self.assertEqual(flags[101], 1)
        self.assertEqual(effective, ("2026-04-01", 1.0))


class TestTriggerMatch(PilotFixture):
    """Issuer + date window + topic overlap are gates; one generic word is not a trigger."""

    def slots(self, question: str, terms: list[str], basis: str = "none",
              date_from: str | None = None, date_to: str | None = None,
              template: str | None = None) -> dict:
        return {"question": question, "terms": terms, "period_basis": basis,
                "date_from": date_from, "date_to": date_to, "template": template}

    def ctx(self) -> Ctx:
        ctx = Ctx(root=self.tmp)
        self.addCleanup(ctx.close)
        return ctx

    def test_issuer_gate_refuses_another_issuers_claim(self):
        # The only fixture claim whose policy_name carries "repo" is a Union Budget line:
        # an RBI ask must not take it.
        slots = self.slots("The RBI raised the repo rate", ["repo", "rate"])
        self.assertEqual(ripple._policy(self.ctx(), slots, "2026-06-30"), [])
        # A claim of the named issuer is kept.
        slots = self.slots("The RBI issued a circular on risk weights",
                           ["circular", "risk", "weights"])
        found = ripple._policy(self.ctx(), slots, "2026-06-30")
        self.assertEqual([row["id"] for row in found], [103])

    def test_topic_overlap_is_required(self):
        slots = self.slots("quantum computing partnership", ["quantum", "computing"])
        self.assertEqual(ripple._policy(self.ctx(), slots, "2026-06-30"), [])

    def test_one_generic_word_is_not_a_trigger(self):
        slots = self.slots("shares scheme budget order", ["shares", "scheme", "budget"])
        self.assertEqual(ripple._policy(self.ctx(), slots, "2026-06-30"), [])

    def test_date_window_excludes_an_old_policy(self):
        # Claim 110 (the only textiles claim) is 2024-06-01; a 2026-09 decision may not
        # use it as the trigger.
        slots = self.slots("textiles park allocation", ["textiles"], basis="as_of",
                           date_from="2026-09-30", date_to="2026-09-30")
        self.assertEqual(ripple._policy(self.ctx(), slots, "2026-09-30"), [])

    def test_declared_evidence_id_wins(self):
        slots = self.slots("anything at all", ["anything"], template="R02:policy_events.id=110")
        found = ripple._policy(self.ctx(), slots, "2026-09-30")
        self.assertEqual([row["id"] for row in found], [110])


class TestRipplePlanner(PilotFixture):
    def ctx(self) -> Ctx:
        return Ctx(root=self.tmp)

    def plan(self, question: str, **over):
        ctx = self.ctx()
        self.addCleanup(ctx.close)
        slots = route(case(question=question, **over))["slots"]
        return load_planners()["RIPPLE"](slots, AS_OF, ctx)

    def test_claim_target_is_pit_filtered(self):
        env = {"REALITY_MACRO_PILOT_DB":
               str(self.tmp / "pilot" / macro_claims.DB_NAME)}
        with mock.patch.dict(os.environ, env):
            ctx = self.ctx()
            self.addCleanup(ctx.close)
            self.assertEqual(ripple._claim_target_rows(ctx, 101, "2026-01-01"), ([], None))
            rows, db = ripple._claim_target_rows(ctx, 101, AS_OF)
        self.assertEqual(db, "macro_pilot")
        self.assertEqual({row["target_kind"] for row in rows},
                         {"basic_industry"})

    def test_without_pilot_the_target_hop_is_blocked(self):
        hop = self.plan("steel capacity expansion")
        self.assertFalse(hop["ok"])
        self.assertEqual(hop["why"], "schema")
        self.assertIn("macro_claim_target", hop["detail"])
        self.assertIn("do not map to held ISINs", hop["detail"])

    def test_with_pilot_the_hop_maps_held_isins(self):
        env = {"REALITY_MACRO_PILOT_DB":
               str(self.tmp / "pilot" / macro_claims.DB_NAME)}
        with mock.patch.dict(os.environ, env):
            hop = self.plan("steel capacity expansion")
        self.assertTrue(hop["ok"], hop["detail"])
        self.assertIn("macro_claim_target", hop["detail"])
        names = {row["ref"] for row in hop["rows"]}
        self.assertIn(f"daily_price_delivery:{CEMCO}", names, hop["rows"])

    def test_fallback_still_answers_without_the_pilot_table(self):
        hop = self.plan("financial services lending")
        self.assertTrue(hop["ok"], hop["detail"])
        self.assertIn("policy_events.sectors", hop["detail"])


if __name__ == "__main__":
    unittest.main()
