"""T-133 label dictionary v3: OCR repair, whole-label matching, qualifiers, context, members, units, garbage.

    python -m pytest -q reality_engine/tests/test_v2_label_map.py

Every line of the T-133 v3 evidence list (the v2 wrong and keep lists) has its own case below, so a regression in
any rule is a failing test, not a new review round.
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


def decide(raw, family="telecom", seeds=None, *, has_measure=False, has_metric_row=False, peers=0):
    return label_map.decide_label(raw, family, seeds or {}, FAMILY_ENTRIES, COMMON,
                                  has_measure=has_measure, has_metric_row=has_metric_row, peers=peers)


def metric(raw, family="telecom", *, has_measure=False, has_metric_row=False, peers=0):
    return decide(raw, family, None, has_measure=has_measure, has_metric_row=has_metric_row, peers=peers)[1]


def need(raw, family="telecom", **context) -> label_map.Proposal:
    proposal = metric(raw, family, **context)
    assert proposal is not None, raw
    return proposal


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


def test_rule_3_member_labels_are_from_header():
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
                        ("Total revenue 1 US$", "revenue")):
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
                     ("FY23 - 9MFY23", "period tokens only"),
                     ("ebitdaal1 US$", "digit glued to a word")):
        key, proposal, rejection = decide(raw, "mining")
        assert proposal is None and rejection == why, raw
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
        ("Total revenue 1 US$", "telecom", "revenue", ""),
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


def test_review_queues_carry_rule_confidence_status_and_the_seed37_sample():
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
    assert rejected_row["status"] == "rejected" and rejected_row["rule"] == "6-reject"
    sample = out / "sample_seed37.csv"
    assert sample.is_file()
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
    ("financial liabifities > sorrowtngs", "a single lower-case OCR token"),
    ("mobife selfvices south asia > passive rnfrastrnctme servi ces", "OCR word soup"),
    ("kl int nsibleass ts", "OCR word soup"),
    ("finance cl sts", "OCR word soup"),
    ("iil 0ther lncome", "a digit/letter swap"),
    ("gpwis mmt", "OCR word soup"),
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


def test_v3_the_graded_keep_list_stays_from_header():
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
    assert kind("population_covered", units={"%": 48}) == "pct"
    assert kind("whatever", units={"Rs crore": 9, "%": 2}) == "money"
    assert kind("whatever", units={"Rs crore": 2, "%": 2}) == ""      # a tie is unknown
    assert kind("whatever") == ""                                     # never money by default
    proposal = need("Interest Coverage ratio (times)")
    defs = {row["metric"]: row for row in label_map._metric_defs([proposal], {})}
    assert defs["interest_coverage"]["unit_kind"] == "x"
