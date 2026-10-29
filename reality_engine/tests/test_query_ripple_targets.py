"""RIPPLE stage 2/3: the sector store, the non-company targets and trigger matching.

The fixture is a tiny data root in a temp dir: a policy store with four claims, a
``sector_pit`` store (the new alias), a pilot (b) store with index membership, the
extraction store with a plant row, and a price window.  No live database is read and
nothing outside the temp dir is written.
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
from reality_engine.query import route
from reality_engine.query.ctx import Ctx
from reality_engine.query.planners import ripple

AS_OF = "2026-06-30"
STEELCO = "INE000A01001"     # basic_industry Iron & Steel Products, adopted 2019
NEWCO = "INE000A01002"       # the same industry, adopted 2026-07-01 (after AS_OF)
GEMSCO = "INE000A01003"      # basic_industry Gems Jewellery And Watches
PLANTCO = "INE000A01004"     # a West Bengal plant in the extraction store
COALCO = "INE000A01005"      # coking coal in its cost structure
DEFCO = "INE000A01006"       # a NIFTY INDIA DEFENCE member

COLUMNS = ("id, source_kind, source_id, section, published_at, title, policy_name, "
           "instrument, direction_for_industry, sectors, companies, products, "
           "amount_inr_crore, unit, new_value, old_value, effective_date, end_date, quote, "
           "quote_ok")
CLAIMS = [
    # id, kind, source, section, published, title, policy_name, instrument, direction,
    # sectors, companies, products, amount, unit, new, old, eff, end, quote, ok
    (201, "doc", "1", 0, "2026-06-05", "Union_Budget: Union Budget 2026-27 Speech",
     "Gold jewellery duty rationalisation", "customs_duty", "positive",
     '["gold jewellery"]', "[]", "[]", None, None, None, None, "2026-06-05", None,
     "duty on gold jewellery rationalised", 1),
    (202, "doc", "2", 0, "2025-02-01", "Union_Budget: Union Budget 2025-26 Speech",
     "Tariff simplification on industrial inputs", "customs_duty", "positive",
     '["steel"]', "[]", "[]", None, None, None, None, "2025-02-01", None,
     "rates codified", 1),
    (203, "doc", "3", 0, "2026-05-20", "PIB release: coastal steel plant",
     "Steel plant investment approved", "scheme", "positive",
     '["steel"]', "[]", "[]", None, None, None, None, None, None,
     "a steel plant in West Bengal", 1),
    (204, "doc", "4", 0, "2026-02-10", "RBI_Monetary_Policy: RBI Statement",
     "Repo rate cut 25 bps", "monetary", "positive", '["banking"]', "[]", "[]",
     None, "%", "repo rate cut", None, "2026-03-01", None, "25 bps to 5.50 per cent", 1),
    (205, "doc", "5", 0, "2026-05-20", "PIB release: defence production",
     "Defence production incentive extended", "scheme", "positive", '["defence"]', "[]",
     "[]", None, None, None, None, None, None, "incentive for defence production", 1),
]


def _make(path: Path, ddl: list[str], rows: list[tuple[str, tuple]] = ()) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    for statement in ddl:
        con.execute(statement)
    for statement, params in rows:
        con.execute(statement, params)
    con.commit()
    con.close()


def temp_root(prefix: str = "ripple_targets_") -> Path:
    """A writable scratch dir: mkdtemp's private DACL denies writes in this sandbox."""
    base = Path(__file__).resolve().parents[2] / ".tmp"
    base.mkdir(parents=True, exist_ok=True)
    root = base / (prefix + uuid.uuid4().hex[:10])
    root.mkdir()
    return root


def build_root(root: Path) -> Path:
    """The data root: policy store, sector store, index membership, extraction store."""
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
        "CREATE TABLE master_companies(isin TEXT, nse_symbol TEXT, company_name TEXT, "
        "sector TEXT, industry TEXT, is_active INTEGER)",
        "CREATE TABLE daily_price_delivery(date TEXT, symbol TEXT, isin TEXT, close REAL)",
    ], [
        ("INSERT INTO raw_documents VALUES (?,?,?,?,?)",
         (1, "Union Budget 2026-27", "Union_Budget", "Ministry of Finance", "2026-02-01")),
        ("INSERT INTO raw_documents VALUES (?,?,?,?,?)",
         (2, "Union Budget 2025-26", "Union_Budget", "Ministry of Finance", "2025-02-01")),
        ("INSERT INTO raw_documents VALUES (?,?,?,?,?)",
         (3, "PIB steel plant", "PIB_Press_Release", "Ministry of Steel", "2026-05-20")),
        ("INSERT INTO raw_documents VALUES (?,?,?,?,?)",
         (4, "RBI statement", "RBI_Monetary_Policy", "Reserve Bank of India", "2026-02-10")),
        ("INSERT INTO raw_documents VALUES (?,?,?,?,?)",
         (5, "PIB data centres", "PIB_Press_Release", "Ministry of Finance", "2026-05-20")),
    ] + [(f"INSERT INTO policy_events ({COLUMNS}) VALUES ({','.join('?' * 20)})", row)
         for row in CLAIMS])
    con = sqlite3.connect(ei)
    for row in ((STEELCO, "STEELCO", "Steelco Limited"), (NEWCO, "NEWCO", "Newco Limited"),
                (GEMSCO, "GEMSCO", "Gemsco Limited"), (PLANTCO, "PLANTCO", "Plantco Ltd"),
                (COALCO, "COALCO", "Coalco Limited"), (DEFCO, "DEFCO", "Defco Limited")):
        con.execute("INSERT INTO master_companies VALUES (?,?,?,?,?,1)",
                    (row[0], row[1], row[2], "Capital Goods", "Capital Goods"))
    for day in ("2026-05-15", "2026-05-20", "2026-05-29", "2026-06-01", "2026-06-05",
                "2026-06-30"):
        for isin in (STEELCO, GEMSCO, PLANTCO, DEFCO, COALCO):
            con.execute("INSERT INTO daily_price_delivery VALUES (?,?,?,?)",
                        (day, isin[:6], isin, 100.0))
    con.commit()
    con.close()

    # The new alias: company_sector_pit alone, in its own file, in the data root.
    pit = root / "pilot" / "pilot60" / "sector_pit.db"
    _make(pit, [
        "CREATE TABLE company_sector_pit(isin TEXT NOT NULL, macro TEXT, sector TEXT, "
        "industry TEXT, basic_industry TEXT, valid_from TEXT NOT NULL, valid_to TEXT, "
        "source TEXT NOT NULL, PRIMARY KEY (isin, valid_from))",
        "CREATE INDEX ix_csp_basic ON company_sector_pit(basic_industry, valid_from)",
    ], [
        ("INSERT INTO company_sector_pit VALUES (?,?,?,?,?,?,?,?)",
         (STEELCO, "Capital Goods", "Capital Goods", "Ferrous Metals",
          "Iron & Steel Products", "2019-01-01", None, "nse_classification")),
        ("INSERT INTO company_sector_pit VALUES (?,?,?,?,?,?,?,?)",
         (NEWCO, "Capital Goods", "Capital Goods", "Ferrous Metals",
          "Iron & Steel Products", "2026-07-01", None, "nse_classification")),
        ("INSERT INTO company_sector_pit VALUES (?,?,?,?,?,?,?,?)",
         (GEMSCO, "Consumer Durables", "Consumer Durables", "Gems", 
          "Gems Jewellery And Watches", "2019-01-01", None, "nse_classification")),
        ("INSERT INTO company_sector_pit VALUES (?,?,?,?,?,?,?,?)",
         (COALCO, "Metals & Mining", "Metals & Mining", "Ferrous Metals",
          "Iron & Steel Products", "2019-01-01", None, "nse_classification")),
    ])

    # The pilot (b) store: thematic index membership.
    _make(root / "pilot" / "pilot60" / "market_state_b.db", [
        "CREATE TABLE company_membership_pit(isin TEXT NOT NULL, index_code TEXT NOT NULL, "
        "added_on TEXT NOT NULL, removed_on TEXT, source TEXT NOT NULL, "
        "pit_conf REAL NOT NULL DEFAULT 1.0)",
    ], [
        ("INSERT INTO company_membership_pit VALUES (?,?,?,?,?,?)",
         (DEFCO, "niftyindiadefence", "2020-01-01", None, "nse_notice", 1.0)),
        ("INSERT INTO company_membership_pit VALUES (?,?,?,?,?,?)",
         ("INE000A01999", "niftyindiadefence", "2026-07-01", None, "nse_notice", 0.6)),
    ])

    # The extraction store: one project that names a state, one input share.
    extract = root / "pilot" / "pilot60" / "extract_pilot60.db"
    _make(extract, [
        "CREATE TABLE capex_project(isin TEXT, project TEXT, announced_on TEXT, "
        "capex_cr REAL, status TEXT, source_doc_id TEXT, page INTEGER, known_at TEXT, "
        "quote TEXT)",
        "CREATE TABLE company_capacity_utilisation(isin TEXT, product TEXT, period_end TEXT, "
        "capacity REAL, capacity_unit TEXT, utilisation_pct REAL, production REAL, "
        "source_doc_id TEXT, page INTEGER, known_at TEXT, quote TEXT)",
        "CREATE TABLE company_cost_structure(isin TEXT, period_end TEXT, basis TEXT, "
        "input_key TEXT, amount_cr REAL, share_of_cogs_pct REAL, source_doc_id TEXT, "
        "known_at TEXT, quote TEXT, page INTEGER)",
    ], [
        ("INSERT INTO capex_project VALUES (?,?,?,?,?,?,?,?,?)",
         (PLANTCO, "West Bengal steel plant", "2026-05-01", 1200.0, "approved", "d1", 4,
          "2026-05-20", "a steel plant in West Bengal")),
        ("INSERT INTO company_cost_structure VALUES (?,?,?,?,?,?,?,?,?,?)",
         (COALCO, "2026-03-31", "consolidated", "coking coal", 900.0, 22.0, "d2",
          "2026-06-01", "coking coal is 22 per cent of cogs", 2)),
    ])
    return ei


def build_pilot(root: Path) -> Path:
    """The macro claim pilot: five claims with their targets, built by the real builder."""
    macro_claims.build(root / "pilot", root / "equity_intelligence.db",
                       {"budget": 3, "rbi": 1, "pib": 1, "tariff": 1},
                       all_claims=True, db_name="macro_pilot.db")
    return root / "pilot" / "macro_pilot.db"


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = temp_root()
        build_root(cls.tmp)
        cls.pilot = build_pilot(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def ctx(self) -> Ctx:
        ctx = Ctx(root=self.tmp)
        self.addCleanup(ctx.close)
        return ctx

    def env(self) -> mock._patch:
        return mock.patch.dict(os.environ, {
            "REALITY_MACRO_PILOT_DB": str(self.pilot),
            "REALITY_EXTRACT_DB": str(self.tmp / "pilot" / "pilot60" /
                                       "extract_pilot60.db"),
        })


class TestSectorPitStore(Fixture):
    """The sector hop reads the new store first, as of the decision day."""

    def test_reads_the_sector_pit_alias(self):
        ctx = self.ctx()
        rows = ripple._sector_targets(ctx, "basic_industry", "Iron & Steel Products", AS_OF)
        self.assertEqual({row["isin"] for row in rows}, {STEELCO, COALCO})

    def test_an_isin_adopted_later_does_not_answer_earlier(self):
        ctx = self.ctx()
        early = {row["isin"] for row in ripple._sector_targets(
            ctx, "basic_industry", "Iron & Steel Products", "2026-06-30")}
        later = {row["isin"] for row in ripple._sector_targets(
            ctx, "basic_industry", "Iron & Steel Products", "2026-09-30")}
        self.assertNotIn(NEWCO, early)
        self.assertIn(NEWCO, later)

    def test_missing_store_degrades_to_the_live_classification(self):
        other = temp_root("no_sector_")
        self.addCleanup(shutil.rmtree, other, True)
        _make(other / "equity_intelligence.db", [
            "CREATE TABLE company_industry(isin TEXT, symbol TEXT, macro TEXT, sector TEXT, "
            "industry TEXT, basic_industry TEXT)"], [
            ("INSERT INTO company_industry VALUES (?,?,?,?,?,?)",
             (STEELCO, "STEELCO", "Capital Goods", "Capital Goods", "Ferrous Metals",
              "Iron & Steel Products"))])
        ctx = Ctx(root=other)
        self.addCleanup(ctx.close)
        rows = ripple._sector_targets(ctx, "basic_industry", "Iron & Steel Products", AS_OF)
        self.assertEqual([row["isin"] for row in rows], [STEELCO])


class TestNonCompanyTargets(Fixture):
    def test_theme_membership_from_the_index_table(self):
        ctx = self.ctx()
        rows = ripple._theme_targets(ctx, "defence", AS_OF)
        self.assertEqual([row["isin"] for row in rows], [DEFCO])
        self.assertEqual(ripple._theme_targets(ctx, "data_centres", AS_OF), [])

    def test_state_target_uses_the_held_plant_row(self):
        with self.env():
            targets, notes = ripple._targets_from_claims(
                self.ctx(), [{"target_kind": "state", "target_id": "West Bengal"}], AS_OF)
        self.assertEqual({target["isin"] for target in targets}, {PLANTCO})
        self.assertEqual(notes, [])

    def test_state_without_a_held_plant_says_which_store_is_missing(self):
        with self.env():
            targets, notes = ripple._targets_from_claims(
                self.ctx(), [{"target_kind": "state", "target_id": "Kerala"}], AS_OF)
        self.assertEqual(targets, [])
        self.assertTrue(notes)
        self.assertIn("Kerala", notes[0])
        self.assertIn("capex_project", notes[0])

    def test_state_row_after_as_of_is_not_used(self):
        with self.env():
            targets, _ = ripple._targets_from_claims(
                self.ctx(), [{"target_kind": "state", "target_id": "West Bengal"}],
                "2026-01-01")
        self.assertEqual(targets, [])

    def test_commodity_maps_through_the_industry_and_the_input_share(self):
        with self.env():
            ctx = self.ctx()
            gold, note = ripple._commodity_targets(ctx, "gold", AS_OF)
            coal, _ = ripple._commodity_targets(ctx, "coal", AS_OF)
            nothing, missing = ripple._commodity_targets(ctx, "uranium", AS_OF)
        self.assertIsNone(note)
        self.assertEqual({row["isin"] for row in gold}, {GEMSCO})
        self.assertEqual({row["isin"] for row in coal}, {COALCO})
        self.assertEqual(nothing, [])
        self.assertIn("uranium", missing)

    def test_theme_note_names_the_missing_membership_map(self):
        with self.env():
            targets, notes = ripple._targets_from_claims(
                self.ctx(), [{"target_kind": "theme", "target_id": "data_centres"}], AS_OF)
        self.assertEqual(targets, [])
        self.assertIn("company_membership_pit", notes[0])


class TestTriggerMatching(Fixture):
    """Issuer, date and topic gates stay; the ask's wording is normalised."""

    def slots(self, question: str, terms: list[str], basis: str = "none",
              date_from: str | None = None, date_to: str | None = None,
              template: str | None = None, symbol: str | None = None) -> dict:
        slots = {"question": question, "terms": terms, "period_basis": basis,
                 "date_from": date_from, "date_to": date_to, "template": template}
        if symbol:
            slots["symbol"] = symbol
        return slots

    def ids(self, slots: dict, as_of: str = AS_OF) -> list[int]:
        with self.env():
            return [row["id"] for row in ripple._policy(self.ctx(), slots, as_of)]

    def test_hinglish_filler_does_not_consume_the_term_window(self):
        slots = self.slots("gold jewellery mein kya hua aur kyun batao",
                           ["gold", "jewellery", "mein", "kya", "hua", "kyun", "batao"])
        self.assertEqual(self.ids(slots, "2026-06-30")[:1], [201])

    def test_the_asks_own_ticker_is_not_a_search_term(self):
        expanded = ripple._expand(["steelco", "customs", "duty"], "STEELCO")
        self.assertEqual(expanded, ["customs", "duty"])

    def test_spelling_variant_matches_the_corpus(self):
        # The claim prints "rationalisation", the ask prints "rationalization".
        slots = self.slots("gold jewellery duty rationalization", ["rationalization"])
        self.assertEqual(self.ids(slots, "2026-06-30")[:1], [201])

    def test_instrument_is_part_of_the_topic_match(self):
        # The claim's title never says "customs"; its instrument does.
        slots = self.slots("what did customs duty do to industrial inputs",
                           ["customs", "industrial", "inputs"])
        self.assertEqual(self.ids(slots, "2026-06-30")[:1], [202])

    def test_a_named_day_tolerates_a_few_days_of_filing_lag(self):
        # The ask names 2025-01-31; the claim is stamped 2025-02-01.
        slots = self.slots("tariff simplification on 31 January 2025",
                           ["tariff", "simplification"], basis="named date",
                           date_from="2025-01-31", date_to="2025-01-31")
        self.assertIn(202, self.ids(slots, "2026-06-30"))

    def test_grace_does_not_pull_a_much_later_claim(self):
        slots = self.slots("tariff simplification on 25 January 2025",
                           ["tariff", "simplification"], basis="named date",
                           date_from="2025-01-25", date_to="2025-01-25")
        self.assertNotIn(202, self.ids(slots, "2026-06-30"))

    def test_a_forward_window_searches_back_from_the_decision_day(self):
        # The ask is about FY27, which starts after as_of: the policy behind it was
        # published before the decision day, so the run-up is measured from as_of.
        slots = self.slots("defence production incentive effect by FY27",
                           ["defence", "production", "incentive"], basis="fiscal year end",
                           date_from="2027-03-31", date_to="2027-03-31")
        self.assertIn(205, self.ids(slots, "2026-10-19"))

    def test_a_generic_word_is_still_not_a_trigger(self):
        slots = self.slots("shares scheme budget order", ["shares", "scheme", "budget"])
        self.assertEqual(self.ids(slots, "2026-06-30"), [])


class TestRippleHopEndToEnd(Fixture):
    """The whole hop: trigger -> theme target -> held ISIN -> market window."""

    def test_theme_target_answers_with_market_rows(self):
        slots = {"question": "defence theme members moved after the defence production "
                             "incentive",
                 "terms": ["defence", "theme", "members", "production", "incentive"],
                 "period_basis": "none", "date_from": None, "date_to": None,
                 "template": None, "as_of": AS_OF, "needs": {"ripple": True}}
        ctx = self.ctx()
        with self.env():
            hop = ripple.plan(slots, AS_OF, ctx)
        self.assertTrue(hop["ok"], hop.get("detail"))
        self.assertIn("held target(s)", hop["detail"])
        self.assertIn(f"daily_price_delivery:{DEFCO}", {row["ref"] for row in hop["rows"]})


if __name__ == "__main__":
    unittest.main()
