"""T-133 label dictionary v6: table totals, flow/stock context, suffixes, over-rejection, common lines, replay.

    python -m pytest -q reality_engine/tests/test_v2_label_map.py

Every line of the T-133 v2/v3 evidence lists, the v4 review list and the v5 ticket steps 1-7 has its own case
below, so a regression in any rule is a failing test, not a new review round.
"""
from __future__ import annotations

import csv
import shutil
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from reality_engine.pilot3.make_profile import main_store
from reality_engine.v2 import label_map

FAMILY_ENTRIES, COMMON = label_map.load_lexicons()
STORES = (Path("D:/RealityEngine/pilot10/pilot10.db"), Path("D:/RealityEngine/p20/p20new.db"),
          Path("D:/RealityEngine/u8/u8.db"), Path("D:/RealityEngine/q12/q12.db"))


def decide(raw, family="telecom", seeds=None, *, has_measure=False, has_metric_row=False, peers=0,
           previous="", trusted=False):
    return label_map.decide_label(raw, family, seeds or {}, FAMILY_ENTRIES, COMMON,
                                  has_measure=has_measure, has_metric_row=has_metric_row, peers=peers,
                                  previous=previous, trusted=trusted)


def metric(raw, family="telecom", *, has_measure=False, has_metric_row=False, peers=0, trusted=False):
    return decide(raw, family, None, has_measure=has_measure, has_metric_row=has_metric_row, peers=peers,
                  trusted=trusted)[1]


def need(raw, family="telecom", **context) -> label_map.Proposal:
    proposal = metric(raw, family, **context)
    assert proposal is not None, raw
    return proposal


@pytest.fixture
def member_corpus():
    """v8: the build's corpus vocabulary knows the member names a single test table cannot teach it."""
    label_map.set_corpus_vocabulary(("bccl", "mcl", "hazira", "mundra", "ginger", "damas"))
    try:
        yield
    finally:
        label_map.set_corpus_vocabulary(())


def test_normalisation_drops_unit_tails_and_numbering():
    assert label_map.normalise_label("1. Revenue from operations") == "revenue from operations"
    assert label_map.normalise_label("Revenue from Operations (Rs crore)") == "revenue from operations"
    assert label_map.normalise_label("EBITDA margin (%)") == "ebitda margin"
    assert label_map.normalise_label("(a) Finance costs") == "finance costs"
    assert label_map.normalise_label("i) Other income") == "other income"
    assert label_map.normalise_label("iv. Exceptional items") == "exceptional items"
    assert label_map.normalise_label("Net debt (excluding acceptances)") == "net debt excluding acceptances"
    assert label_map.normalise_label("Constant Currency Revenue") == "constant currency revenue"
    assert label_map.normalise_label("Others") == "others"
    assert label_map.normalise_label("Others", "Segment Revenue") == "segment revenue > others"
    assert label_map.parse_label("Others", "Segment Revenue").label_norm == "segment revenue > others"
    assert label_map.parse_label("Employee benefits expense", "Expenses").label_norm == "employee benefits expense"
    for raw in ("Net Debt US$ mn", "net debt us mn", "Net Debt 2 US$", "Net Debt (US$ Mn)"):
        assert label_map.normalise_label(raw) == "net debt", raw
    assert label_map.normalise_label("Capex 1 US$") == "capex"
    assert label_map.normalise_label("Total revenue 1 US$") == "total revenue"
    assert label_map.normalise_label("customer base 000 s") == "customer base"
    assert label_map.normalise_label("Interest Coverage ratio (times)") == "interest coverage ratio"


def test_rule_1_a_phrase_inside_a_longer_label_is_not_that_metric():
    ebit = label_map.Entry("ebit", phrases=("ebit",))
    assert label_map._match_entry(ebit, "ebit") == 4
    assert label_map._match_entry(ebit, "ebit margin") == 0
    assert label_map.propose_metric("ebit margin", "fmcg", {}, {}, [ebit]) is None
    assert label_map.propose_metric("sales and marketing expenses", "fmcg", {}, {},
                                    [label_map.Entry("revenue", phrases=("sales",))]) is None


def test_rule_1_bracket_unit_and_definition_handling():
    parsed = label_map.parse_label("Operating Free Cash Flow (EBITDA - Capex) Rs")
    assert parsed.label_norm == "operating free cash flow ebitda capex"
    assert ("operating free cash flow", "basis=ebitda") in parsed.candidates
    assert label_map.parse_label("Order book (excluding L1)").label_norm == "order book excluding l1"


def test_seed_rule_1_valid_seed_wins_a_conflicting_seed_loses_to_the_lexicon():
    seeded = label_map.propose_metric("casa ratio", "bank", {("casa ratio", "bank"): "casa_ratio"},
                                      FAMILY_ENTRIES, COMMON)
    assert seeded is not None and seeded.metric == "casa_ratio" and seeded.rule == "2-seed"
    conflict = label_map.propose_metric("casa ratio", "bank", {("casa ratio", "bank"): "wrong_metric"},
                                        FAMILY_ENTRIES, COMMON)
    assert conflict is not None and conflict.metric == "casa_ratio"     # the lexicon is the reviewed contract


def test_a_label_never_maps_across_families_except_common():
    seeds = {("casa ratio", "bank"): "casa_ratio"}
    assert label_map.propose_metric("casa ratio", "fmcg", seeds, FAMILY_ENTRIES, COMMON) is None
    shared = label_map.propose_metric("net debt", "fmcg", seeds, FAMILY_ENTRIES, COMMON)
    assert shared is not None and shared.metric == "net_debt" and shared.family == "*"


def test_rule_3_qualifiers_become_the_dimension():
    for label, dimension in (("Return on Shareholder's Equity (Pre Tax) %", "pre_tax"),
                             ("Return on Shareholder's Equity (Post Tax) %", "post_tax"),
                             ("Net debt excluding lease obligations", "excl_lease"),
                             ("Net debt including lease obligations", "incl_lease"),
                             ("Net debt excluding acceptances", "excl_acceptances")):
        proposal = metric(label)
        assert proposal is not None and proposal.metric in {"roe_pct", "net_debt"}, label
        assert dimension in proposal.dimension, (label, proposal.dimension)
        assert proposal.confidence == "synonym"
    assert need("Return on Shareholder's Equity (Pre Tax) %").metric == \
        need("Return on Shareholder's Equity (Post Tax) %").metric
    plain = metric("Net Debt")
    assert plain is not None and plain.metric == "net_debt" and plain.dimension == ""


def test_rule_3_a_definition_bracket_sets_the_basis():
    ebitda = metric("Operating Free Cash Flow (EBITDA - Capex)")
    ebitdaal = metric("Operating Free Cash Flow (EBITDAaL - Capex)")
    assert ebitda is not None and ebitdaal is not None
    assert ebitda.metric == ebitdaal.metric == "operating_free_cash_flow"
    assert ebitda.dimension == "basis=ebitda" and ebitdaal.dimension == "basis=ebitdaal"


def test_rule_3_member_labels_are_from_header(member_corpus):
    for label, context in (("BCCL", {"peers": 7}), ("MCL", {"peers": 7}), ("Dahej", {"peers": 4}),
                           ("Hazira", {"peers": 4}), ("Mundra", {"peers": 4}),
                           ("Airtel Business", {"has_metric_row": True}),
                           ("Homes Services", {"has_metric_row": True}),
                           ("EyeCare", {"has_measure": True}), ("Watches", {"has_measure": True}),
                           ("CaratLane", {"has_measure": True}),
                           ("Business to Business", {"peers": 3})):
        proposal = label_map.decide_label(label, "telecom", {}, FAMILY_ENTRIES, COMMON,
                                          has_measure=bool(context.get("has_measure")),
                                          has_metric_row=bool(context.get("has_metric_row")),
                                          peers=int(context.get("peers", 0)))[1]
        assert proposal is not None and proposal.metric == label_map.FROM_HEADER, (label, proposal)
        assert proposal.dimension == label_map.normalise_label(label)
    jv = decide("JVs > AICTPL (CT-3), JV with MSC", "ports_logistics")
    assert jv[1] is not None and jv[1].metric == label_map.FROM_HEADER
    assert jv[1].dimension == "aictpl ct 3 jv with msc"
    assert jv[0] == "jvs > aictpl ct 3 jv with msc"


def test_rule_4_unit_kind_is_money_and_currency_comes_from_the_cell():
    proposal = metric("Capex 1 US$")
    assert proposal is not None and proposal.metric == "capex"
    defs = {row["metric"]: row for row in label_map._metric_defs([proposal], {})}
    assert defs["capex"]["unit_kind"] == "money"
    # A seed unit never makes the map inr/usd: a money figure's currency belongs to the cell (rule 4).
    assert label_map.resolve_unit_kind("capex", label_map.MetricMeta(units=Counter({"inr_cr": 9}))) == "money"
    assert label_map.resolve_unit_kind("interest_coverage", label_map.MetricMeta(entry_unit="x")) == "x"
    assert label_map.resolve_unit_kind("roe_pct", label_map.MetricMeta(entry_unit="pct")) == "pct"
    assert label_map.resolve_unit_kind("working_capital_days", label_map.MetricMeta(entry_unit="days")) == "days"
    assert label_map.resolve_unit_kind("capex", None) == ""      # v3: unknown is NULL, never money
    for raw, wanted in (("EBITDA 1 US$", "ebitda"), ("Net debt 2 US$", "net_debt"),
                        ("Total revenue 1 US$", "total_revenue")):
        assert need(raw).metric == wanted


def test_rule_5_statement_context():
    cash_flow = metric("Cash flows from investing activities > Interest received")
    pnl = metric("Statement of profit and loss > Interest received")
    assert cash_flow is not None and cash_flow.metric == "interest_received"
    assert cash_flow.dimension == "statement=cash_flow"
    assert pnl is not None and pnl.metric == "interest_income" and pnl.dimension == "statement=pnl"
    owners = metric("Owners of the Parent")
    assert owners is not None and owners.metric == "profit_attributable"      # the P&L attribution line
    assert owners.dimension == "attribution=owners_of_parent" and owners.rule == "5-context"
    equity = metric("Equity > Owners of the parent")
    assert equity is not None and equity.metric == "owners_equity"
    attributable = metric("Profit for the period attributable to: > Owners of the parent")
    assert attributable is not None and attributable.metric == "profit_attributable"
    assert attributable.dimension == "attribution=owners_of_parent"


def test_rule_5_deferred_tax_and_balance_sheet_lines_keep_their_own_metric():
    assert need("Deferred tax liabilities (net)").metric == "deferred_tax_liabilities"
    assert need("Deferred tax expense").metric == "deferred_tax"
    assert need("Total equity and liabilities").metric == "total_equity_and_liabilities"
    assert need("Total equity").metric == "total_equity"


def test_rule_6_junk_is_rejected_not_proposed():
    for raw, why in (("45,000 160% EBITDA", "a value token in the label"),
                     ("FY23 - 9MFY23", "period tokens only")):
        key, proposal, rejection = decide(raw, "mining")
        assert proposal is None and rejection == why, raw
    # v6: a footnote digit glued to a word ("ebitdaal1", "mundra1") is a footnote, not junk.
    assert need("ebitdaal1 US$", "mining").metric == "ebitdaal"
    assert label_map.normalise_label("mundra1") == "mundra"
    assert metric("Assets i Revenue from operations") is None      # rule 1: not revenue
    assert metric("Financial Assets") is None and decide("Financial Assets")[2] == "heading"


def test_every_evidence_line():
    """The T-133 v2 evidence list, one row each: (raw label, family, metric, dimension)."""
    evidence = (
        ("Operating Free Cash Flow (EBITDA - Capex)", "telecom", "operating_free_cash_flow", "basis=ebitda"),
        ("Operating Free Cash Flow (EBITDAaL - Capex)", "telecom", "operating_free_cash_flow", "basis=ebitdaal"),
        ("Sales and marketing expenses", "telecom", "sales_and_marketing_expense", ""),
        ("Revenue per tower per month", "telecom", "revenue_per_tower_per_month", ""),
        ("Revenue per tow ers per month", "telecom", "revenue_per_tower_per_month", ""),
        ("Adjusted free cash flow before capex", "metals_nonferrous", "free_cash_flow_before_capex", ""),
        ("Net debt excluding lease obligations", "telecom", "net_debt", "excl_lease"),
        ("Return on Shareholder's Equity (Pre Tax) %", "telecom", "roe_pct", "pre_tax"),
        ("Return on Shareholder's Equity (Post Tax) %", "telecom", "roe_pct", "post_tax"),
        ("Capex 1 US$", "telecom", "capex", ""),
        ("EBITDA 1 US$", "telecom", "ebitda", ""),
        ("Net Debt 2 US$", "telecom", "net_debt", ""),
        ("Total revenue 1 US$", "telecom", "total_revenue", ""),
        ("Net Debt US$ mn", "telecom", "net_debt", ""),
        ("Total equity and liabilities", "hotels", "total_equity_and_liabilities", ""),
        ("Interest Coverage ratio (times)", "telecom", "interest_coverage", ""),
        ("Unallocable Income", "consumer_durables", "unallocable_income", ""),
        ("Interest Received", "telecom", "interest_received", ""),
        ("Deferred Tax Liabilities (net)", "hotels", "deferred_tax_liabilities", ""),
        ("Owners of the Parent", "telecom", "profit_attributable", "attribution=owners_of_parent"),
        ("JVs > AICTPL (CT-3), JV with MSC", "ports_logistics", "from_header", "aictpl ct 3 jv with msc"),
    )
    for raw, family, wanted, dimension in evidence:
        proposal = metric(raw, family)
        assert proposal is not None, raw
        assert proposal.metric == wanted, (raw, proposal.metric)
        assert proposal.dimension == dimension, (raw, proposal.dimension)
    for raw, reason in (("45,000 160% EBITDA", "a value token in the label"),
                        ("FY23 - 9MFY23", "period tokens only")):
        assert decide(raw, "mining")[2] == reason
    assert metric("Assets i Revenue from operations", "mining") is None


def test_metric_kinds_for_the_period_engine():
    assert label_map.metric_kind("revenue") == "flow"
    assert label_map.metric_kind("borrowings") == "stock"
    assert label_map.metric_kind("ebitda_margin_pct") == "ratio"
    assert label_map.metric_kind("eps_basic") == "per_share"
    assert label_map.metric_kind("aum") == "stock"
    assert label_map.metric_kind("arpu") == "price"
    assert label_map.metric_kind("total_expenses") == "flow"
    assert label_map.metric_kind("other_income") == "flow"
    assert label_map.metric_kind("total_equity_and_liabilities") == "stock"
    assert label_map.metric_kind("deferred_tax_liabilities") == "stock"
    assert label_map.metric_kind("interest_coverage") == "ratio"


def test_section_overrides_and_percentage_parents():
    assert label_map._section_metric("segment assets") == "segment_assets"
    assert label_map._section_metric("ii segment results") == "segment_results"
    assert label_map._pct_metric("access_charges") == "access_charges_pct"
    assert label_map._pct_metric("ebitda") == "ebitda_margin_pct"
    proposal = metric("Segment Assets > Unallocable assets")
    assert proposal is not None and proposal.metric == "segment_assets"
    assert proposal.dimension == "unallocable assets"


def test_review_queues_carry_rule_confidence_status_and_the_seed43_sample():
    out = Path(".tmp") / "test_label_map_out"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    proposal = metric("Capex 1 US$")
    assert proposal is not None
    proposals = {("capex", "telecom"): proposal}
    observations = {("capex", "telecom"): label_map.Observation(
        3, Counter({"Capex": 2, "Capex 1 US$": 1}), {"BHARTIARTL"}),
        ("financial assets", "telecom"): label_map.Observation(1, Counter({"Financial Assets": 1}),
                                                               {"BHARTIARTL"})}
    numeric = Counter({("capex", "telecom"): 3})
    label_map.write_outputs(out, proposals, observations, numeric, Counter(),
                            {"capex": label_map.MetricMeta()},
                            {("financial assets", "telecom"): "heading"})
    with (out / "review_telecom.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert tuple(rows[0].keys()) == label_map.REVIEW_COLUMNS
    assert rows[0]["label_norm"] == "capex" and rows[0]["rule"] == "1-match"
    assert rows[0]["confidence"] == "exact" and rows[0]["status"] == "queue"
    assert rows[0]["unit_kind"] == "money"
    rejected_row = next(row for row in rows if row["label_norm"] == "financial assets")
    assert rejected_row["status"] == "rejected" and rejected_row["rule"] == "heading"
    sample = out / label_map.SAMPLE_FILE
    assert sample.is_file() and sample.name == "sample_seed59.csv"
    rejected_sample = out / label_map.REJECTED_SAMPLE_FILE
    assert rejected_sample.is_file() and rejected_sample.name == "rejected_seed59.csv"
    with rejected_sample.open(encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == 1
    with sample.open(encoding="utf-8") as handle:
        sampled = list(csv.DictReader(handle))
    assert 0 < len(sampled) <= label_map.SAMPLE_SIZE and "family" in sampled[0]
    coverage = (out / "coverage.txt").read_text(encoding="utf-8")
    assert "mapped to a proposed metric: 3 (100.0%)" in coverage
    conn = sqlite3.connect(out / "label_map.db")
    try:
        assert conn.execute("SELECT dimension, unit_kind, status FROM label_map WHERE label_norm='capex'"
                            ).fetchone() == ("", "money", "queue")
        assert conn.execute("SELECT status FROM label_map WHERE label_norm='financial assets'"
                            ).fetchone() == ("rejected",)
    finally:
        conn.close()
    shutil.rmtree(out, ignore_errors=True)


def test_metric_def_table_and_kind_check():
    conn = sqlite3.connect(":memory:")
    label_map.schema.create(conn)
    conn.execute("INSERT INTO metric_def (metric, kind, unit_kind, description) VALUES ('revenue','flow','inr','x')")
    assert conn.execute("SELECT kind FROM metric_def WHERE metric='revenue'").fetchone()[0] == "flow"
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO metric_def (metric, kind) VALUES ('bad','maybe')")


def test_sector_map_gives_every_pilot_company_a_family():
    taxonomy = main_store()
    if not taxonomy.is_file() or not all(path.is_file() for path in STORES):
        pytest.skip("the pilot stores are not on this machine")
    rows = label_map.company_families(STORES, taxonomy)
    assert rows, "no company rows read from the four pilot stores"
    unknown = [row for row in rows if row["family"] == "unknown"]
    assert not unknown, f"{len(unknown)} company rows have no sector family: {unknown[:5]}"


def test_v3_ocr_spellings_are_repaired_before_matching():
    assert label_map.normalise_label("financial liabi6ties") == "financial liabilities"
    assert label_map.normalise_label("segment liabiities") == "segment liabilities"
    assert label_map.normalise_label("Other comprehensive lncome") == "other comprehensive income"
    assert label_map.normalise_label("less inter seoment eliminations") == "less inter segment eliminations"
    assert label_map.normalise_label("mobife selfvices south asia") == "mobile services south asia"
    assert label_map.normalise_label("Others", "segment liabiities") == "segment liabilities > others"


def test_v3_segment_misspelling_gets_the_section_metric():
    proposal = metric("segment liabiities > unallocated")
    assert proposal is not None and proposal.metric == "segment_liabilities"
    assert proposal.dimension == "unallocated"
    assert need("segment liabiities > others").metric == "segment_liabilities"


@pytest.mark.parametrize("raw, why", [
    ("gpwis mmt", "OCR word soup"),
    ("xqzt vbnm", "OCR word soup"),
])
def test_v3_garbled_labels_are_rejected(raw, why):
    _key, proposal, rejection = decide(raw, "telecom", has_metric_row=True, peers=6)
    assert proposal is None, (raw, why)
    assert rejection == "garbled", (raw, why, rejection)


@pytest.mark.parametrize("raw", [
    "adjustments for > bad debts written off",
    "current assets > inventories",
    "securities premium",
    "cogs",
    "exceptional item refer note",
    "nominal value of i 1 each not annualised > basic eps f",
    "attributable to > non controlling i iterest",
    "total outstanding dues of > micro small and medium",
    "government grant > rent waiver",
    "financial liabilities",
    "small enterprises",
])
def test_v3_a_statement_line_is_never_from_header(raw):
    proposal = metric(raw, has_metric_row=True, peers=6)
    assert proposal is None or proposal.metric != label_map.FROM_HEADER, raw


def test_v3_the_graded_keep_list_stays_from_header(member_corpus):
    for label, context in (("Dahej", {"has_measure": True}), ("Domestic Ports", {"has_measure": True}),
                           ("Ginger", {"has_measure": True}), ("Oriental Hotels Ltd", {"has_measure": True}),
                           ("India", {"has_measure": True}), ("Marine", {"has_measure": True}),
                           ("Airtel Business", {"has_metric_row": True}),
                           ("Digital TV Services", {"has_metric_row": True}),
                           ("Damas Core", {"has_metric_row": True}),
                           ("CaratLane", {"has_measure": True}),
                           ("Business to Business", {"has_metric_row": True}),
                           ("Cable", {"has_metric_row": True})):
        proposal = decide(label, "telecom", None,
                          has_measure=bool(context.get("has_measure")),
                          has_metric_row=bool(context.get("has_metric_row")))[1]
        assert proposal is not None and proposal.metric == label_map.FROM_HEADER, (label, proposal)
    jv = decide("JVs > AICTPL (CT-3), JV with MSC", "ports_logistics")
    assert jv[1] is not None and jv[1].metric == label_map.FROM_HEADER


def test_v3_profit_attribution_and_dividend_lines():
    nci = metric("profit attributable to > non controlling interest")
    assert nci is not None and nci.metric == "profit_attributable"
    assert nci.dimension == "attribution=non_controlling"
    assert need("dividend received").metric == "dividend_received"
    # v6: the OCR repair of "on controlling interest" must not damage "non controlling".
    assert label_map.normalise_label("on controlling interest") == "non controlling interest"
    assert need("Total comprehensive income for the period attributable to > on controlling interest",
                "jewellery_lifestyle").dimension == "attribution=non_controlling"


def test_v3_a_pct_metric_comes_from_the_base_metric_not_a_slug():
    for leaf in ("operating expenses excl access charges cost of sold and license fee and charity and donation",
                 "operating expenses excl access charges cost of sold license fee and charity and donation"):
        proposal = metric(f"As a % of Total revenues > {leaf}")
        assert proposal is not None and proposal.metric == "operating_expenses_pct", leaf
    assert need("As a % of Total revenues > cash profit from operations before derivative and").metric == \
        "cash_profit_from_operations_pct"
    assert need("As a % of Total revenues > access charges").metric == "access_charges_pct"


def test_v3_section_rule_does_not_replace_a_known_child_metric():
    proposal = metric("total comprehensive income for the period attributable to > "
                      "paid up equity share capital face value 1 per share")
    assert proposal is None or proposal.metric != "total_comprehensive_income_attributable"


def test_v3_unit_kind_from_metric_def_or_the_cells():
    def kind(name, entry_unit="", units=None):
        return label_map.resolve_unit_kind(name, label_map.MetricMeta(units=Counter(units or {}),
                                                                      entry_unit=entry_unit))
    assert kind("pcr_stage3", "pct") == "pct"
    assert kind("production_kt", "kt") == "tonnes"
    assert kind("volume", "kt") == "tonnes"
    assert kind("domestic_volumes", "count") == "count"
    assert kind("employees", "count") == "count"
    assert kind("population_covered") == "count"          # v5: the label's quantity word, not the cell unit
    assert kind("total_gbs_on_network") == "data"
    assert kind("debtors_turnover") == "x"
    assert kind("whatever", units={"Rs crore": 9, "%": 2}) == "money"
    assert kind("whatever", units={"Rs crore": 2, "%": 2}) == ""      # a tie is unknown
    assert kind("whatever") == ""                                     # never money by default
    proposal = need("Interest Coverage ratio (times)")
    defs = {row["metric"]: row for row in label_map._metric_defs([proposal], {})}
    assert defs["interest_coverage"]["unit_kind"] == "x"


def test_v4_exclusion_qualifier_stays_in_the_dimension():
    """Blocker (seed-31 row 31): the exclusion list is part of the meaning and is never dropped."""
    blocker = metric("As a % of Total revenues > operating expenses excluding access of goods sold and license fee")
    assert blocker is not None and blocker.metric == "operating_expenses_pct"
    assert blocker.dimension == "excl=access_charges,cogs,licence_fee"
    for raw in ("As a % of Total revenues > operating expenses excl access charges cost of sold and license fee "
                "and charity and donation",
                "As a % of Total revenues > operating expenses excl access charges cost of sold license fee and "
                "charity and donation"):
        proposal = metric(raw)
        assert proposal is not None and proposal.metric == "operating_expenses_pct", raw
        assert proposal.dimension.startswith("excl=access_charges,cogs,licence_fee"), (raw, proposal.dimension)
    plain = metric("Operating expenses")
    assert plain is not None and plain.metric == "operating_expenses" and plain.dimension == ""


def test_v4_a_measure_parent_owns_the_member_and_ocr_sections_are_repaired():
    cases = (
        ("revenue in > logistics", "ports_logistics", "segment_revenue", "logistics"),
        ("revenue in > marine", "ports_logistics", "segment_revenue", "marine"),
        ("segment sales > c and b", "paints_chemicals", "segment_revenue", "c and b"),
        ("profit loss from segments before finance costs exceptional item and > corporate unallocated",
         "telecom", "segment_results", "corporate unallocated"),
        ("segment results a switchgears", "consumer_durables", "segment_results", "switchgears"),
        ("segment liabilties > mobile services africa", "telecom", "segment_liabilities", "mobile services africa"),
        ("segment l iabifties > airtel business", "telecom", "segment_liabilities", "airtel business"),
    )
    for raw, family, wanted, dimension in cases:
        proposal = metric(raw, family, has_metric_row=True, peers=4)
        assert proposal is not None and proposal.metric == wanted, raw
        assert proposal.dimension == dimension, (raw, proposal.dimension)
    assert label_map.repair_section("segment l iabifties") == "segment liabilities"
    assert label_map.repair_section("asia") == "asia"


def test_v4_a_common_metric_leaf_wins_over_its_section_and_from_header():
    for raw, family, wanted in (
        ("cwip", "ports_logistics", "capital_work_in_progress"),
        ("cwip rs cr", "ports_logistics", "capital_work_in_progress"),
        ("share > diluted not annualised", "telecom", "eps_diluted"),
        ("earnings per equity share face value off 1 each not annualised > basic f", "telecom", "eps_basic"),
        ("total comprehensive income for the period attributable to > diluted not annualised",
         "telecom", "eps_diluted"),
    ):
        proposal = metric(raw, family, has_metric_row=True, peers=4)
        assert proposal is not None and proposal.metric == wanted, (raw, proposal)


def test_v4_from_header_has_no_unit_kind_and_a_currency_line_keeps_money():
    member = label_map.decide_label("Hazira", "ports_logistics", {}, FAMILY_ENTRIES, COMMON, has_measure=True)[1]
    assert member is not None and member.metric == label_map.FROM_HEADER
    row = label_map._queue_row("hazira", label_map.Observation(
        4, Counter({"Hazira": 4}), {"ADANIPORTS"}, Counter({"Rs crore": 3, "%": 1})), member,
        {"from_header": "money"})
    assert row["unit_kind"] == ""
    currency = need("Unallocable Expenses")
    assert currency.metric == "unallocable_expenses"
    assert label_map._queue_row("unallocable expenses", label_map.Observation(
        3, Counter({"Unallocable Expenses": 3}), {"HAVELLS"}, Counter({"Rs crore": 3})), currency,
        {"unallocable_expenses": "money"})["unit_kind"] == "money"


def test_v4_heading_fragments_are_rejected_not_members():
    for raw in ("particulars", "Less", "otal"):
        _key, proposal, rejection = decide(raw, "telecom", has_metric_row=True, peers=6)
        assert proposal is None and rejection == "heading", (raw, proposal, rejection)
    rejection_row = label_map._queue_row("particulars", label_map.Observation(
        2, Counter({"Particulars": 2}), {"X"}), None, {}, "heading")
    assert rejection_row["status"] == "rejected" and rejection_row["rule"] == "heading"


def test_v4_one_key_with_two_meanings_is_queued_with_no_metric():
    key, proposal, rejection = decide("items not to be reclasslfled to profit or loss > owners of the parent")
    assert proposal is None and not rejection
    assert key == "items not to be reclassified to profit or loss > owners of the parent"


def test_v4_a_ratio_of_the_previous_line_carries_its_base():
    for previous, base in (("Contribution", "contribution"), ("A&SP", "a_and_p_spend"),
                           ("Less: Other SG&A", "other_sga")):
        key, proposal, _rejection = decide("as a % of NR", "consumer_durables", previous=previous)
        assert proposal is not None and proposal.metric == "pct_of_net_revenue", previous
        assert proposal.dimension == f"base={base}", (previous, proposal.dimension)
        assert key.endswith(" > as a of nr") and key != "as a of nr"


def test_v4_wrong_metrics_are_one_canonical_id():
    assert need("net profit before tax").metric == "pbt"
    assert need("cash generated from operations").metric == "cash_generated_from_operations"
    for raw in ("net cash from operating activities", "net cash generated from operating activities"):
        assert need(raw).metric == "cash_flow_from_operations", raw
    assert need("total revenue from operations").metric == "revenue"
    assert need("revenue from operations").metric == "revenue"
    assert need("segment revenue").metric == "segment_revenue"
    total = need("segment results > total", "consumer_durables")
    assert total.metric == "segment_results" and total.dimension == ""
    asia = metric("Asia > Unallocated", "telecom", has_metric_row=True)
    assert asia is not None and asia.metric == label_map.FROM_HEADER
    assert asia.dimension == "asia > unallocated"


def test_v5_a_percent_label_is_a_margin_never_the_money_line():
    """Step 1: raw "PBT %"/"EBIT %" are margins with unit_kind pct, never the money ids."""
    for raw, wanted in (("PBT %", "pbt_margin"), ("PBT (%)", "pbt_margin"),
                        ("EBIT %", "ebit_margin"), ("EBIT (%)", "ebit_margin")):
        key, proposal, rejection = decide(raw, "jewellery_lifestyle")
        assert proposal is not None and proposal.metric == wanted, (raw, proposal)
        assert key.endswith(" %") and not rejection, (raw, key)
        defs = {row["metric"]: row for row in label_map._metric_defs([proposal], {})}
        assert defs[wanted]["unit_kind"] == "pct" and defs[wanted]["kind"] == "ratio", raw
    assert need("PBT", "jewellery_lifestyle").metric == "pbt"
    assert need("EBIT", "jewellery_lifestyle").metric == "ebit"
    margin = need("EBITDA margin (%)", "telecom")          # a margin label keeps its own metric
    assert margin.metric == "ebitda_margin_pct" and margin.dimension == ""


def test_v5_others_keeps_its_dimension_and_only_the_total_is_empty():
    """Step 2: a generic member stays in the dimension; the split-header leaf is the total."""
    for raw, family, wanted, dimension in (
            ("Segment Assets > c) Others", "paints_chemicals", "segment_assets", "others"),
            ("Segment Liabilities > Others", "jewellery_lifestyle", "segment_liabilities", "others"),
            ("Profit from segments before finance costs and taxes > Others", "jewellery_lifestyle",
             "segment_results", "others"),
            ("Segment Results > Total", "consumer_durables", "segment_results", ""),
            ("b) Profit from segments before finance costs and taxes", "jewellery_lifestyle",
             "segment_results", "")):
        proposal = metric(raw, family)
        assert proposal is not None and proposal.metric == wanted, raw
        assert proposal.dimension == dimension, (raw, proposal.dimension)


def test_v5_mis_parented_children_route_by_their_own_wording():
    """Step 3: child wording (OCR joined) beats the mis-parented section, and total revenue is total income."""
    for raw, family, wanted in (
            ("Segment Assets \"' > Total liabirlties", "telecom", "total_liabilities"),
            ("Profit for the pe riod attributable to: > Total Com pre hensive Income for the period attributable "
             "to: -Own ers of the Company", "paints_chemicals", "total_comprehensive_income_attributable"),
            ("Items not to be reclassified to profit or loss : > Total comprehensive income for the quarter / year",
             "telecom", "total_comprehensive_income"),
            ("Total Revenue", "hotels", "total_revenue"),
            ("total revenues", "telecom", "total_revenue"),
            ("Total revenue from operations", "telecom", "revenue")):
        proposal = need(raw, family)
        assert proposal.metric == wanted, (raw, proposal.metric)
    # v6 rule 9: a bare P&L "Attributable to:" parent is the flow, with the parent in the key; the OCI parent
    # above keeps its own key, so the two never share a row.
    key, proposal, rejection = decide("Attributable to: > Non Controlling Interest", "paints_chemicals")
    assert proposal is not None and proposal.metric == "profit_attributable" and not rejection
    assert proposal.dimension == "attribution=non_controlling"
    assert key == "attributable to > non controlling interest"
    oci_key = decide("OTHER COMPREHENSIVE CNCOME ATTRIBUTABLE TO: > Non-controlling interest",
                     "paints_chemicals")[0]
    assert oci_key == "other comprehensive income attributable to > non controlling interest"


def test_v5_sentence_fragments_and_heading_rows_are_rejected():
    """Step 4: a sentence fragment and an OCR heading are rejected; a dash-only heading is per table."""
    assert decide("The Parent Company has", "paints_chemicals")[2] == "sentence fragment"
    assert decide("Particulats", "jewellery_lifestyle")[2] == "heading"
    assert metric("The Parent Company has", "paints_chemicals") is None
    assert metric("Particulats", "jewellery_lifestyle") is None
    assert label_map.heading_like("particulats") and label_map.heading_like("particulars")
    assert not label_map.heading_like("net debt")
    assert label_map.empty_heading("current assets", [None, None])
    assert not label_map.empty_heading("current assets", [None, 12.0])
    assert not label_map.empty_heading("net debt", [None])


def test_v5_a_quantity_or_a_sub_line_member_queues_instead_of_from_header():
    """Step 5: a component of the parent line and a unit-bearing quantity are not members."""
    _key, proposal, rejection = decide("Cash and cash equivalents comprising of: > Balances with banks",
                                       "asset_management")
    assert proposal is None and not rejection
    assert label_map.decide_label("Cumulative", "mining", {}, FAMILY_ENTRIES, COMMON, peers=5,
                                  quantity_row=True)[1] is None
    assert label_map.decide_label("Tugs 10", "ports_logistics", {}, FAMILY_ENTRIES, COMMON, peers=5)[1] is None
    allow = label_map.decide_label("Corporate unallocated", "consumer_durables", {}, FAMILY_ENTRIES, COMMON,
                                   peers=5)[1]
    assert allow is not None and allow.metric == label_map.FROM_HEADER


def test_v5_unit_kind_comes_from_the_label_quantity_word():
    """Step 6: the metric's quantity word wins over a money-looking cell majority."""
    assert label_map.resolve_unit_kind("population_covered", None) == "count"
    assert label_map.resolve_unit_kind("total_gbs_on_network", None) == "data"
    assert label_map.resolve_unit_kind("debtors_turnover", None) == "x"
    assert label_map.resolve_unit_kind("roe_pct", label_map.MetricMeta(entry_unit="pct")) == "pct"
    assert label_map.resolve_unit_kind("capex", label_map.MetricMeta(units=Counter({"Rs crore": 4}))) == "money"
    assert label_map.unit_kind_of("MW") == "power" and label_map.unit_kind_of("GB") == "data"
    proposal = need("Population Covered Bn", "telecom")
    defs = {row["metric"]: row for row in label_map._metric_defs([proposal], {})}
    assert defs["population_covered"]["unit_kind"] == "count"


def test_v5_a_redundant_tax_qualifier_is_dropped():
    """Step 7: pre-tax on PBT and post-tax on PAT are not dimensions; ROE keeps them."""
    assert need("Profit before tax before exceptional items").dimension == ""
    assert need("Profit before tax").dimension == ""
    assert need("Profit after tax").dimension == ""
    assert need("Return on Shareholder's Equity (Pre Tax) %").dimension == "pre_tax"
    assert need("Return on Shareholder's Equity (Post Tax) %").dimension == "post_tax"


# ------------------------------------------------------------------------------------------------ v6 (T-133)
def _table_decisions(rows, family="hotels"):
    decisions, parsed = {}, {}
    for raw in dict.fromkeys(row[0] for row in rows):
        parsed[raw] = label_map.parse_label(*reversed(label_map._split_label(raw)))
        decisions[raw] = label_map.decide_label(raw, family, {}, FAMILY_ENTRIES, COMMON)
    label_map.resolve_total_revenue(rows, decisions)
    return decisions


def test_v6_total_revenue_is_decided_by_the_table_not_the_label():
    """Step 1: total_income only when this table's revenue + other income add up to the total."""
    ihcl = [("Revenue from operations", "Q4FY25", "Rs crore", 2425.0),
            ("Other Income", "Q4FY25", "Rs crore", 62.0),
            ("Total Revenue", "Q4FY25", "Rs crore", 2487.0)]
    decisions = _table_decisions(ihcl)
    assert decisions["Total Revenue"][1].metric == "total_income"
    assert decisions["Other Income"][1].metric == "other_income"

    bharti = [("Total revenues", "Q1FY26", "Rs million", 494626.0),
              ("Other income", "Q1FY26", "Rs million", 4858.0)]
    decisions = _table_decisions(bharti, "telecom")
    assert decisions["Total revenues"][1].metric == "revenue"

    # revenue + other income present but they do not make the total: still the revenue line.
    broken = [("Revenue from operations", "FY25", "Rs crore", 100.0),
              ("Other income", "FY25", "Rs crore", 5.0),
              ("Total revenue", "FY25", "Rs crore", 130.0)]
    assert _table_decisions(broken)[("Total revenue")][1].metric == "revenue"
    # the label alone carries the unresolved marker; the map defaults it to revenue.
    assert need("total revenues", "telecom").metric == "total_revenue"
    assert label_map.seed_agrees(label_map.TOTAL_REVENUE, "revenue")
    assert label_map.seed_agrees("revenue", "total_income") is False


def test_v6_flow_and_stock_never_share_a_key():
    """Step 2: cash-flow movements and attribution lines are flows; the balance-sheet ids stay stock."""
    receivable = label_map.decide_label(
        "Adjustments for (increase)/ decrease In operating assets: > Trade receivables", "hotels",
        {}, FAMILY_ENTRIES, COMMON)
    assert receivable[1] is not None and receivable[1].metric == "change_in_trade_receivables"
    assert " > " in receivable[0]
    payable = need("Adjustments for : > Decrease/(Increase) in trade payables", "consumer_durables")
    assert payable.metric == "change_in_trade_payables"
    assert need("increase decrease in inventories", "paints_chemicals").metric == "changes_in_inventories"

    pnl = label_map.decide_label("Profit for the pe riod attributable to: > -Non-controlling interest",
                                 "telecom", {}, FAMILY_ENTRIES, COMMON)
    assert pnl[1] is not None and pnl[1].metric == "profit_attributable"
    assert pnl[1].dimension == "attribution=non_controlling"
    oci = label_map.decide_label("B Items that may be reclassified to profit or loss > Non-controlling interest",
                                 "consumer_durables", {}, FAMILY_ENTRIES, COMMON)
    assert oci[1] is not None and oci[1].metric == "other_comprehensive_income"
    stock = label_map.decide_label("Equity > Non-controlling Interests", "telecom", {}, FAMILY_ENTRIES, COMMON)
    assert stock[1] is not None and stock[1].metric == "non_controlling_interest"
    assert len({pnl[0], oci[0], stock[0]}) == 3


def test_v6_a_suffix_naming_the_unit_is_never_stripped():
    """Step 3: EBITDA/ton stays ebitda_per_tonne; CASA % is casa_ratio; a seed survives a silent lexicon."""
    for raw in ("EBITDA/ton", "EBITDA/tonne $/tonne", "EBITDA per tonne"):
        assert need(raw, "metals_nonferrous").metric == "ebitda_per_tonne", raw
    casa = need("CASA %", "bank")
    assert casa.metric == "casa_ratio"
    defs = {row["metric"]: row for row in label_map._metric_defs([casa], {})}
    assert defs["casa_ratio"]["unit_kind"] == "pct" and defs["casa_ratio"]["kind"] == "ratio"
    seed = label_map.propose_metric("vonb margin", "insurance_life",
                                    {("vonb margin", "insurance_life"): "vnb_margin"}, FAMILY_ENTRIES, COMMON)
    assert seed is not None and seed.metric == "vnb_margin"
    assert label_map.seed_agrees(None, "vnb_margin")       # the lexicon is silent, the seed stands


def test_v6_garbled_rejects_only_character_level_junk():
    """Step 4: a real label seen in two documents is not garbled, even when the dictionary misses it."""
    assert label_map.garbled_reason("krishnapatnam") == "garbled"
    assert label_map.garbled_reason("krishnapatnam", trusted=True) == ""
    trusted = label_map.decide_label("krishnapatnam", "ports_logistics", {}, FAMILY_ENTRIES, COMMON,
                                     peers=4, trusted=True)
    assert trusted[1] is not None and trusted[1].metric == label_map.FROM_HEADER
    assert label_map.decide_label("krishnapatnam", "ports_logistics", {}, FAMILY_ENTRIES, COMMON,
                                  peers=4)[2] == "garbled"
    for clean in ("ebitdaal1", "mundra1"):
        assert label_map.junk_reason(label_map.normalise_label(clean)) == "", clean


def test_v6_the_missed_common_metrics_have_a_row():
    """Step 5: every metric the review named as unmapped maps again (no NULL for a common line)."""
    cases = (
        ("inventories", "paints_chemicals", "inventories"),
        ("current assets > inventories", "paints_chemicals", "inventories"),
        ("changes in inventories of finished goods stock in trade and work in progress", "paints_chemicals",
         "changes_in_inventories"),
        ("cogs", "tyres_auto_ancillary", "cost_of_goods_sold"),
        ("exceptional items refer note", "paints_chemicals", "exceptional_items"),
        ("securities premium", "paints_chemicals", "securities_premium"),
        ("profit for the period year", "paints_chemicals", "pat"),
        ("current tax liabilities net", "paints_chemicals", "current_tax_liabilities"),
        ("finance cost net", "paints_chemicals", "finance_cost"),
        ("revenue from sales", "paints_chemicals", "revenue"),
        ("tax expense current tax", "paints_chemicals", "current_tax"),
        ("profit loss before tax and exceptional items", "paints_chemicals", "pbt_before_exceptional"),
        ("equity holders of the parent", "paints_chemicals", "owners_equity"),
        ("operating ebitda margin", "paints_chemicals", "ebitda_margin_pct"),
        ("deferred tax assets net", "paints_chemicals", "deferred_tax_assets"),
        ("depreciation", "paints_chemicals", "depreciation"),
        ("borrowings", "paints_chemicals", "borrowings"),
        ("intangible assets", "paints_chemicals", "intangible_assets"),
        # the seed-31 OCR rows v5 dropped to NULL: repaired by the seen-spelling table, not lost.
        ("financial liabifities > sorrowtngs", "paints_chemicals", "borrowings"),
        ("finance cl sts", "paints_chemicals", "finance_cost"),
        ("kl int nsibleass ts", "paints_chemicals", "intangible_assets"),
        ("attributable to > non controlling i iterest", "paints_chemicals", "profit_attributable"),
        ("expenses > salesandmarlcetingexpenses", "paints_chemicals", "sales_and_marketing_expense"),
        ("profit attributable to > owners oflhe paunl company", "paints_chemicals", "profit_attributable"),
        ("expe1 ses > depreciation amortisation and lmpainnent", "paints_chemicals", "depreciation"),
        ("ftellls to be redassified to profit or loss > tlon contro ling interests", "paints_chemicals",
         "other_comprehensive_income"),
    )
    for raw, family, wanted in cases:
        assert need(raw, family).metric == wanted, raw


def test_v6_from_header_is_not_a_fallback_for_a_broken_row():
    """Step 6: a truncated label, an OCR number, a typo and two unwrapped lines get their own answer."""
    assert decide("(Excl.", "mining")[2] == "truncated label"
    assert decide("Revenue from OPerations > ?,39L.64", "mining")[2] == "digit glued to a word"
    owners = need("owners ofthe company", "mining")
    assert owners.metric == "profit_attributable" and owners.dimension == "attribution=owners_of_parent"
    assert need("PBDIT for the quarter", "paints_chemicals").metric == "ebitda"
    assert need("Provisiuns", "mining").metric == "provisions"
    for raw in ("(Excl.", "Revenue from OPerations > ?,39L.64", "owners ofthe company", "PBDIT for the quarter",
                "Provisiuns"):
        proposal = metric(raw, "mining", has_metric_row=True, peers=6)
        assert proposal is None or proposal.metric != label_map.FROM_HEADER, raw


def test_v6_the_smaller_rows_keep_their_context():
    """Step 7: dimensions, units and mix members the review named."""
    base = need("Data > As % of Customer Base", "telecom")
    assert base.metric == "pct_of_customer_base" and base.dimension == "data"
    assert need("Total comprehensive income for the period attributable to > on controlling interest",
                "jewellery_lifestyle").dimension == "attribution=non_controlling"
    assert label_map.resolve_unit_kind("eliminations", label_map.MetricMeta(units=Counter({"%": 9}))) == "money"
    assert label_map.resolve_unit_kind("current_liability_ratio",
                                       label_map.MetricMeta(units=Counter({"ratio": 9}))) == "x"
    retail = need("Retail", "it_services")
    assert retail.metric == "vertical_mix" and retail.dimension == "retail"
    liquid = need("Liquid", "asset_management")
    assert liquid.metric == "aum_mix" and liquid.dimension == "asset_class=liquid"
    # one OCR-merged line carries two metrics: it queues instead of picking one.
    assert metric("other equity excluding revaluation reserves as at march 31st earnings per share face value "
                  "off 2 each") is None
    # Qty.(In Mill. Te) takes the channel of the price row after it.
    rows = [("Qty.(In Mill. Te)", "31.03.26", "count", 645.99),
            ("FSA Price (In Rs./Te.)", "31.03.26", "Rs", 2082.66)]
    ordered = [row[0] for row in rows]
    parsed = {raw: label_map.parse_label(*reversed(label_map._split_label(raw))) for raw in ordered}
    decisions = {raw: label_map.decide_label(raw, "mining", {}, FAMILY_ENTRIES, COMMON) for raw in ordered}
    label_map.resolve_quantity_channels(ordered, parsed, decisions)
    qty = decisions["Qty.(In Mill. Te)"][1]
    assert qty is not None
    assert decisions["Qty.(In Mill. Te)"][0].startswith("fsa > qty in mill te")
    assert qty.dimension == "fsa"


def test_v6_replay_counts_a_right_row_lost_when_it_maps_to_nothing():
    """Step 8: a row graded right that now maps to NULL/rejected is LOST, never counted as fixed."""
    folder = Path(".tmp") / "test_label_map_replay"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "replay.csv"
    grade = folder / "grade.csv"
    grade.write_text("row,label_norm,proposed_metric,right,class,note\n"
                     "1,capex,capex,yes,,\n"
                     "2,financial assets,other_assets,yes,,\n"
                     "3,goodwill,goodwill,yes,,\n"
                     "4,old wrong,revenue,no,wrong_metric,\n", encoding="utf-8")
    metrics = {"capex": {"capex"}, "old wrong": {"pat"}}
    result = label_map.replay_grade(grade, metrics, out)
    # "financial assets" is a heading: no map row and the rule rejects it -> LOST.  "goodwill" has no map
    # row but the current rule maps it, so it is kept (the replay asks what the rule says now).
    assert result["graded_right"] == 3 and result["kept"] == 2 and result["lost"] == 1
    assert result["changed"] == 1
    with out.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["status"] for row in rows] == ["kept", "LOST", "kept", "changed"]
    shutil.rmtree(folder, ignore_errors=True)


def test_v7_rejects_only_character_level_junk():
    """Step 2: an OCR-damaged but readable line is queued; a label with clean cells in 2 periods is trusted."""
    for raw, family in (("0ther expenses", "paints_chemicals"), ("1c1 provisions", "telecom"),
                        ("iil 0ther lncome", "telecom"),
                        ("total rrabi6ties", "telecom"), ("lec1se liabilities", "telecom")):
        _key, proposal, rejection = decide(raw, family)
        assert rejection == "", (raw, rejection)
        assert proposal is None or proposal.metric != "from_header", raw
    assert decide("9b bb", "telecom")[2] == "digit glued to a word"
    assert decide("to1al", "telecom")[2] == "digit glued to a word"
    # v7 evidence: the same label in two periods of one document (or two documents) is real, not garbled.
    for raw in ("real estate", "non participating health", "order book 31 mar"):
        assert decide(raw, "realty", trusted=True)[2] == "", raw
    assert decide("real estate", "realty")[2] == "garbled"
    assert metric("Real Estate", "realty", trusted=True) in (None, "real_estate")
    assert need("Order Book - 31 Mar26", "epc_capital_goods", trusted=True).metric == "order_book"


def test_v7_the_ocr_fixer_never_rewrites_a_dictionary_word():
    """Step 3: "consumer" is a word, so the one-edit fixer must leave it alone (never "consumed")."""
    assert label_map._repair_token("consumer") == "consumer"
    assert label_map.normalise_label("Electrical Consumer Durables") == "electrical consumer durables"
    assert label_map.normalise_label("Lloyd consumer") == "lloyd consumer"
    assert label_map.normalise_label("Liabi6ties") == "liabilities"


def test_v7_from_header_only_when_the_header_names_the_measure():
    """Step 4: a row that names its own measure is not a from_header member."""
    proposal = need("ARR in Rs (LFL)", "hotels")
    assert proposal.metric == "arr" and "lfl" in proposal.dimension, proposal
    proposal = need("Occupancy % (LFL)", "hotels")
    assert proposal.metric == "occupancy_pct" and "lfl" in proposal.dimension, proposal
    proposal = need("Share of profit of: > Associate and joint venture", "jewellery_lifestyle")
    assert proposal.metric == "share_of_jv_profit", proposal
    assert proposal.dimension == "associate and joint venture"
    proposal = need("Changes in assets and liabilities > Provisions", "telecom")
    assert proposal.metric == "change_in_provisions", proposal
    assert decide("Cheques, draft on hand", "paints_chemicals")[1] is None


def test_v7_the_smaller_context_rows_keep_their_meaning():
    """Step 5: net cash keeps its sign, working capital is the balance, and the damaged/attribution rows route."""
    assert need("Net cash", "telecom").metric == "net_cash"
    assert need("Net Debt", "telecom").metric == "net_debt"
    assert need("Working capital", "airlines").metric == "working_capital"
    assert metric("Working capital loans and demand loan facilities", "airlines") is None
    proposal = need("Exceptional Items (net of tax & NCI)", "telecom")
    assert proposal.metric == "exceptional_items" and "nci" in proposal.dimension, proposal
    key, proposal, _rejection = decide("Segment Liabilities > Total raabinties", "telecom")
    assert proposal is not None and proposal.metric == "segment_liabilities"
    assert proposal.dimension == "" and key == "segment liabilities"
    assert decide("Segment Assets > A", "telecom")[1] is None
    key, proposal, _rejection = decide(
        "Total comprehensive income for the period attributable to: > ~ 8,. Co. I..", "hotels")
    assert proposal is not None and proposal.metric == "total_comprehensive_income", proposal
    assert proposal.dimension == ""
    key, proposal, _rejection = decide(
        "Other comprehensive income for the period attributable to: > Total comprehensive income for the period "
        "attributable to owners of the parent", "paints_chemicals")
    assert proposal is not None and proposal.metric == "total_comprehensive_income_attributable", proposal
    assert proposal.dimension == "attribution=owners_of_parent"


# ---------------------------------------------------------------- T-133 v8
# The seed-53 review's 21 over-rejected labels, with the ordinary financial words the corpus supplies.
_V8_CORPUS = ("crar treasury booked fibre linked standalone expense expenses share shares purchase consideration "
              "liabilities liability subsidiaries subsidiary benefits employee loan loans new revenue customers top "
              "ten food ordering delivery group life health optic network volume face value opening balance").split()
_V8_OVER_REJECTED = (
    "paid up eqwty share cap11al face value of", "purchase of treasury shares",
    "loan losses and provisions before accelerated ecl", "overall cil",
    "add reversal ol strip ping activity provision", "loan given to subsidiaries",
    "other ban lie ij a lances", "emplo ee benefits expense", "consideration paid for business combination",
    "crar standalone", "linked group life", "total liaj ulities and equity", "india food ordering and delivery",
    "treaty receivables", "new loans booked no in", "debt secunttc",
    "welspun global brands limited working capital", "revenue from top ten customers", "non participating health",
    "mundra volume mmt share", "optic fibre network r kms")


def test_v8_the_garbled_rule_spares_real_lines():
    """Step 3: at most 4 of the 21 seed-53 over-rejected labels may stay rejected; real OCR damage still is."""
    label_map.set_corpus_vocabulary(_V8_CORPUS)
    try:
        rejected = [label for label in _V8_OVER_REJECTED if decide(label, "mining")[2]]
        assert len(rejected) <= 4, rejected
        assert label_map.garbled_reason("iopening balance") == "garbled"
        assert label_map.garbled_reason("gpwis mmt") == "garbled"
        assert label_map.garbled_reason("xqzt vbnm") == "garbled"
        assert label_map.garbled_reason("crar standalone") == ""
    finally:
        label_map.set_corpus_vocabulary(())


def test_v8_the_ocr_garbled_rule_reads_the_corpus():
    """Step 3: a word the corpus prints in two documents is evidence, not damage."""
    label_map.set_corpus_vocabulary(("krishnapatnam", "mundra"))
    try:
        assert label_map.garbled_reason("krishnapatnam", trusted=True) == ""
        assert label_map.garbled_reason("mundra volume mmt share") == ""
    finally:
        label_map.set_corpus_vocabulary(())
    assert label_map.garbled_reason("krishnapatnam") == "garbled"


def test_v8_a_measure_parent_owns_the_child_and_an_ocr_leaf_queues():
    """Step 4: from_header_wrong rows 29, 83, 87, 104, 177 and the OCR-leaf rule."""
    key, proposal, _rejection = decide("TOTAL COMPREHENSIVE INCOME ATTRIBUTABLE TO: > Owners oftl1c Parent Company",
                                       "asset_management")
    assert proposal is not None and proposal.metric == "total_comprehensive_income_attributable"
    assert proposal.dimension == "attribution=owners_of_parent"
    assert decide("Receivables > Jnvesunents", "asset_management", has_metric_row=True)[1] is None
    proposal = need("b) Profit from gm,nt, b,f, fin,n, ,nd t,, > Jewellery", "jewellery_lifestyle")
    assert proposal.metric == "segment_results" and proposal.dimension == "jewellery"
    proposal = need("[b) Deferred Tax > Period/ Year (7'B)", "mining")
    assert proposal.metric == "deferred_tax"
    assert decide("Pmiit before lax", "paints_chemicals")[2] == "garbled"
    # a TCI total that names no owner is the total, not the owners' line.
    proposal = need("Items not to be reclassified to profit or loss : > Total comprehensive income for the quarter "
                    "/ year attrilutable to :", "telecom")
    assert proposal.metric == "total_comprehensive_income" and proposal.dimension == ""


def test_v8_units_and_members_from_the_label():
    """Step 4: the label's own unit word wins, a member stays a member and the vertical keeps its dimension."""
    proposal = need("Sales Million Tonne", "metals_ferrous")
    assert proposal.metric == "sales_volume" and proposal.unit_kind == "tonnes"
    volume = need("(Excl. Other Qty.(In Mill. Te)", "mining")
    defs = {row["metric"]: row for row in label_map._metric_defs([volume], {})}
    assert defs["volume"]["unit_kind"] == "tonnes"
    proposal = need("Total Minutes on Network Mn", "telecom")
    defs = {row["metric"]: row for row in label_map._metric_defs([proposal], {})}
    assert defs[proposal.metric]["unit_kind"] == "count"
    proposal = need("Current Ratio", "jewellery_lifestyle")
    defs = {row["metric"]: row for row in label_map._metric_defs([proposal], {})}
    assert defs[proposal.metric]["unit_kind"] == "x"
    proposal = need("communication", "it_services")
    assert proposal.metric == "vertical_mix" and proposal.dimension == "communication"
    member = decide("passive infrastructure services", "telecom", has_metric_row=True)[1]
    assert member is None or member.metric == label_map.FROM_HEADER
