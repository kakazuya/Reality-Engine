"""T-228 stage 1a-fix: driver-tree claims from management text.  Synthetic only: no store, no network.

The contract under test: the script mapping, the number normaliser, the three-way quote/number check, the
unit/period/sign script checks, the independent judge's verdict applied to a claim, context attachment,
dedupe, known_at copied from the source row, resume skip, and the adaptive limiter raising and halving.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import pytest

from reality_engine.research import driver_claims as dc


@pytest.fixture()
def db_path():
    """A private DB path under ``.tmp``.

    ``tmp_path`` is unusable on this machine: TMP points at ``.tmp`` and ``.tmp/pytest-of-SYSTEM``
    denies listing, so pytest cannot create its basetemp.  The test owns this directory and removes it.
    """
    folder = Path(".tmp/t228/test") / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=True)
    try:
        yield folder / "claims.db"
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _guidance_row(**kw):
    row = {
        "id": 11, "symbol": "BHAGERIA", "metric": "revenue_growth", "target_period": "FY26",
        "low": 20.0, "high": 22.0, "unit": "pct", "direction": "up",
        "quote": "But going forward, it would be maybe about 20%-22% in the revenue.",
        "doc_key": "D:/raw/BHAGERIA.pdf", "page": 15, "known_at": "2025-10-30T13:19:49", "said_on": "2025-10-28",
    }
    row.update(kw)
    return row


def _item(**kw):
    item = {
        "key": "c17|transcript_statement|250", "id": 1, "store": "c17", "source_table": "transcript_statement",
        "source_id": 250, "symbol": "BHAGERIA", "doc_key": "D:/raw/BHAGERIA.pdf", "page": 4,
        "known_at": "2025-10-30T13:19:49", "event_date": "2025-10-28",
        "text": "It will increase by approximately Rs. 55 crores annually, starting from Q4.",
        "context": "S1: Good afternoon. | S2: Thank you for joining.",
    }
    item.update(kw)
    return item


def _claim(**kw):
    base = {"node": "capex.amount", "unit": "inr_cr", "value_low": 55.0, "value_high": None,
            "sign": "+", "effective_period": None, "segment": "total",
            "quote_span": "approximately Rs. 55 crores annually",
            "statement": "It will increase by approximately Rs. 55 crores annually, starting from Q4.",
            "store": "c17", "symbol": "BHAGERIA", "source_table": "transcript_statement", "source_id": 250,
            "doc_key": "D:/raw/BHAGERIA.pdf", "page": 4, "known_at": "2025-10-30T13:19:49",
            "event_date": "2025-10-28", "base": None, "conditional": 0, "context": "",
            "method": "model", "extractor": "test"}
    base.update(kw)
    return base


def _row(**kw):
    row = {"_store": "c17", "id": 1, "symbol": "BHAGERIA", "doc_key": "D:/raw/BHAGERIA.pdf", "page": 4,
           "call_date": "2025-10-28", "known_at": "2025-10-30T13:19:49", "is_fragment": 0, "seq": 1,
           "answer_turn": -1, "text": "Good afternoon.", "numbers_json": "[]"}
    row.update(kw)
    return row


# ------------------------------------------------------------------ script mapping
def test_guidance_maps_a_node_named_metric():
    claim, reason = dc.guidance_claim("c17", _guidance_row())
    assert reason == "mapped" and claim is not None
    assert claim["node"] == "revenue.total"
    assert claim["sign"] == "+"
    assert (claim["value_low"], claim["value_high"]) == (20.0, 22.0)
    assert claim["unit"] == "pct"
    assert claim["effective_period"] == "FY26"
    assert claim["method"] == "script"
    assert claim["status"] == "verified"
    assert claim["judge_ok"] is None


def test_guidance_special_metrics_map_to_their_nodes():
    cases = {
        "capex": "capex.amount",
        "ebitda_margin": "margin.ebitda",
        "order_intake": "revenue.order_book",
        "interest_cost": "debt.cost",
        "credit_cost": "cost.other",
        "aum_growth": "revenue.volume",
        "nim": "margin.ebitda",
    }
    for metric, node in cases.items():
        claim, _ = dc.guidance_claim("c17", _guidance_row(metric=metric, quote="Rs. 50 crores next year",
                                                          low=50.0, high=50.0, unit="inr_cr"))
        assert claim is not None, metric
        assert claim["node"] == node, metric


def test_guidance_unmapped_and_valueless_are_not_claims():
    claim, reason = dc.guidance_claim("c17", _guidance_row(metric="other"))
    assert claim is None and reason == "unmapped"
    claim, reason = dc.guidance_claim("c17", _guidance_row(metric="revenue_growth", low=None, high=None))
    assert claim is None and reason == "no_value"


def test_guidance_sign_follows_direction():
    signs = []
    for direction in ("up", "down", "flat"):
        claim, _ = dc.guidance_claim("c17", _guidance_row(direction=direction))
        assert claim is not None
        signs.append(claim["sign"])
    assert signs == ["+", "-", "0"]


def test_guidance_known_at_is_copied_from_the_source_row():
    row = _guidance_row(known_at="2025-01-02T03:04:05")
    claim, _ = dc.guidance_claim("c17", row)
    assert claim is not None
    assert claim["known_at"] == "2025-01-02T03:04:05"
    assert claim["event_date"] == "2025-10-28"
    assert (claim["doc_key"], claim["page"]) == ("D:/raw/BHAGERIA.pdf", 15)


# ------------------------------------------------------------------ number normaliser
def test_find_numbers_reads_indian_grouping_and_units():
    assert dc.find_numbers("Rs. 1,748.95 crore") == [1748.95]
    assert dc.find_numbers("Rs. 50-Rs. 75 crores") == [50.0, 75.0]
    assert dc.find_numbers("20%-22% of revenue") == [20.0, 22.0]
    assert dc.find_numbers("₹2.8 Cr") == [2.8]
    assert dc.find_numbers("1,23,456 tonnes") == [123456.0]
    assert dc.find_numbers("INR40 crore") == [40.0]          # a digit glued to its currency prefix
    assert dc.find_numbers("1x to 1.25x") == [1.0, 1.25]     # a multiple keeps its trailing x


def test_find_numbers_does_not_read_period_labels():
    assert dc.find_numbers("FY26 and Q2FY26 and H1FY26 and 9MFY26") == []


def test_matches_value_accepts_pct_as_a_fraction():
    assert dc.matches_value(0.2, [20.0], "pct")
    assert dc.matches_value(20.0, [20.0], "pct")
    assert not dc.matches_value(25.0, [20.0], "pct")


def test_canon_unit_folds_printed_variants():
    assert dc.canon_unit("Rs. crore") == "inr_cr"
    assert dc.canon_unit("percent") == "pct"
    assert dc.canon_unit("basis points") == "bp"
    assert dc.canon_unit("inr_cr") == "inr_cr"


# ------------------------------------------------------------------ the quote/number check
def test_verified_when_numbers_are_in_the_quote():
    assert dc.verify_claim(_claim()) == ("verified", "")


def test_unverified_when_a_value_is_not_printed():
    # 25 is a sum the model computed; it is nowhere in the quote.
    statement = "Segment A will add Rs. 10 crore and segment B will add Rs. 15 crore."
    claim = _claim(value_low=25.0, quote_span="Rs. 10 crore and segment B will add Rs. 15 crore",
                   statement=statement)
    assert dc.verify_claim(claim) == ("unverified", "value_low_not_in_quote")


def test_quarantined_when_the_span_is_a_paraphrase():
    claim = _claim(quote_span="will increase by about 55 crore")
    assert dc.verify_claim(claim) == ("quarantined", "quote_span_not_in_statement")


def test_quarantined_without_a_span():
    assert dc.verify_claim(_claim(quote_span="")) == ("quarantined", "no_quote_span")


def test_span_may_span_a_line_wrap():
    statement = "The expansion\nwill add Rs. 55 crores annually."
    claim = _claim(quote_span="will add Rs. 55 crores annually", statement=statement)
    assert dc.verify_claim(claim) == ("verified", "")


# ------------------------------------------------------------------ unit / sign / period checks
def test_unit_word_must_agree_with_the_unit():
    d = _claim(node="working_capital.days", unit="days", value_low=30.0, value_high=None,
               quote_span="less than 30 days", statement="Our receivables will be less than 30 days.",
               effective_period="FY26")
    assert dc.verify_claim(d) == ("verified", "")
    months = _claim(node="working_capital.days", unit="months", value_low=30.0, value_high=None,
                    quote_span="less than 30 days", statement="Our receivables will be less than 30 days.",
                    effective_period="FY26")
    assert dc.verify_claim(months) == ("unverified", "unit_mismatch")
    crore = _claim(unit="inr_cr", value_low=0.75, quote_span="Rs. 0.75 crore annually",
                   statement="It will be Rs. 0.75 crore annually.")
    assert dc.verify_claim(crore) == ("verified", "")
    million = _claim(unit="inr_cr", value_low=0.75, quote_span="Rs. 0.75 million annually",
                     statement="It will be Rs. 0.75 million annually.")
    assert dc.verify_claim(million) == ("unverified", "unit_mismatch")
    pct = _claim(unit="pct", value_low=50.0, quote_span="50 basis points", statement="It will be 50 basis points next year.")
    assert dc.verify_claim(pct) == ("unverified", "unit_mismatch")
    bp = _claim(node="margin.ebitda", unit="bp", value_low=50.0, quote_span="50 basis points",
                statement="It will be 50 basis points next year.", effective_period="FY26")
    assert dc.verify_claim(bp) == ("verified", "")


def test_ambiguous_range_forces_sign_zero():
    for marker in ("plus or minus", "+/-", "±"):
        claim = _claim(node="revenue.total", sign="+", unit="pct", value_low=10.0, value_high=15.0,
                       quote_span=f"10%-15% {marker} next year",
                       statement=f"There could be a 10%-15% {marker} next year.")
        status, _ = dc.verify_claim(claim)
        assert status == "verified", marker
        assert claim["sign"] == "0", marker


def test_a_claim_needs_a_period_or_a_forward_horizon():
    no_period = _claim(quote_span="approximately Rs. 55 crores", statement="It will be approximately Rs. 55 crores.",
                       effective_period=None)
    assert dc.verify_claim(no_period) == ("unverified", "no_period")
    horizon = _claim(quote_span="approximately Rs. 55 crores annually",
                     statement="It will be approximately Rs. 55 crores annually.", effective_period=None)
    assert dc.verify_claim(horizon) == ("verified", "")
    explicit = _claim(quote_span="approximately Rs. 55 crores", statement="It will be approximately Rs. 55 crores.",
                      effective_period="FY26")
    assert dc.verify_claim(explicit) == ("verified", "")


# ------------------------------------------------------------------ the model claim + judge verdict
def test_model_claim_carries_the_source_ids_and_the_check():
    claim, reason = dc.claim_from_reply(
        {"node": "capex.amount", "sign": "+", "value_low": "55", "value_high": None, "unit": "Rs. crore",
         "quote_span": "approximately Rs. 55 crores annually", "effective_period": "Q4", "conditional": False},
        _item())
    assert reason == "claim" and claim is not None
    assert claim["known_at"] == "2025-10-30T13:19:49"          # copied from the row, never from the model
    assert claim["source_id"] == 250 and claim["store"] == "c17"
    assert claim["context"] == "S1: Good afternoon. | S2: Thank you for joining."   # judge input, not a source
    assert claim["unit"] == "inr_cr"
    assert claim["status"] == "verified"
    assert claim["judge_ok"] is None


def test_model_claim_with_an_unknown_node_is_dropped():
    claim, reason = dc.claim_from_reply({"node": "margin", "value_low": 10, "quote_span": "x"}, _item())
    assert claim is None and reason == "bad_node"


def test_reply_parser_tolerates_fences_and_rejects_garbage():
    items = dc.parse_reply('```json\n{"items":[{"id":1,"drop":null,"claims":[]}]}\n```')
    assert items == [{"id": 1, "drop": None, "claims": []}]
    try:
        dc.parse_reply("no json here")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("garbage must not parse")


def test_node_unit_compatibility():
    cases = [
        (_claim(node="capacity.add", unit="months", value_low=3.0, quote_span="next 3 months",
                statement="It will be ready in next 3 months.", effective_period="FY26"), "unverified"),
        (_claim(node="capacity.add", unit="mw", value_low=40.0, quote_span="40 MW",
                statement="We will add 40 MW.", effective_period="FY26"), "verified"),
        (_claim(node="working_capital.days", unit="months", value_low=3.0, quote_span="3 months",
                statement="Receivables will be 3 months.", effective_period="FY26"), "unverified"),
        (_claim(node="margin.ebitda", unit="inr_cr", value_low=35.0, quote_span="Rs. 35 crores",
                statement="EBITDA will be Rs. 35 crores.", effective_period="FY26"), "unverified"),
        (_claim(node="margin.ebitda", unit="pct", value_low=35.0, quote_span="35%",
                statement="EBITDA margin will be 35%.", effective_period="FY26"), "verified"),
        (_claim(node="capex.amount", unit="pct", value_low=5.0, quote_span="5% higher",
                statement="Capex will be 5% higher.", effective_period="FY26"), "unverified"),
        (_claim(node="revenue.price", unit="pct", value_low=5.0, quote_span="5% higher",
                statement="Realisation will be 5% higher.", effective_period="FY26"), "verified"),
        (_claim(node="revenue.volume", unit="inr_cr", value_low=50.0, quote_span="Rs. 50 crores",
                statement="Volume will be Rs. 50 crores.", effective_period="FY26"), "unverified"),
        (_claim(node="debt.cost", unit="pct", value_low=9.0, quote_span="9%",
                statement="Interest rate will be 9%.", effective_period="FY26"), "verified"),
    ]
    for claim, expected in cases:
        assert dc.verify_claim(claim)[0] == expected, (claim["node"], claim["unit"])


def test_company_brief_names_products_and_raw_materials():
    corpus = ("Cotton prices have moved up. We buy cotton and polyester fibre. "
              "Our cotton yarn and fabric sales will grow. Cotton is our main raw material. " * 3)
    brief = dc.brief_from_text("Sportking India Limited", corpus)
    assert "Sportking India Limited" in brief
    assert "It buys or uses:" in brief and "cotton" in brief
    assert "textiles" in brief
    assert "cost.raw_material" in brief and "revenue.price" in brief


def test_company_brief_is_empty_safe():
    brief = dc.brief_from_text("Empty Limited", "we had a call")
    assert "Empty Limited" in brief
    assert "It sells:" not in brief and "It buys or uses:" not in brief


def test_from_to_is_a_target_not_a_range():
    statement = ("The short-term debt is expected to come down from INR450 crores to INR100 crores "
                 "in next three to four months.")
    claim = _claim(node="debt.level", unit="inr_cr", value_low=100.0, value_high=450.0,
                   quote_span="from INR450 crores to INR100 crores", statement=statement,
                   effective_period="next three to four months")
    status, _ = dc.verify_claim(claim)
    assert status == "verified"
    assert (claim["value_low"], claim["value_high"]) == (100.0, 100.0)
    assert claim["base"] == "INR450 crores"
    assert claim["sign"] == "-"
    up = _claim(node="debt.level", unit="inr_cr", value_low=100.0, value_high=450.0,
                quote_span="from INR100 crores to INR450 crores",
                statement="Debt will rise from INR100 crores to INR450 crores next year.",
                effective_period="FY26")
    assert dc.verify_claim(up)[0] == "verified"
    assert up["sign"] == "+" and up["value_low"] == 450.0


def test_a_to_b_needs_a_change_verb_to_become_a_target():
    change = _claim(node="debt.level", unit="inr_cr", value_low=450.0, value_high=100.0,
                    quote_span="reduce debt from INR450 crores to INR100 crores",
                    statement="We will reduce debt from INR450 crores to INR100 crores next year.",
                    effective_period="FY26")
    assert dc.verify_claim(change)[0] == "verified"
    assert (change["value_low"], change["value_high"]) == (100.0, 100.0)
    assert change["sign"] == "-"
    plain = _claim(node="revenue.total", unit="inr_cr", value_low=2700.0, value_high=2800.0,
                   quote_span="INR 2,700 to 2,800 crores",
                   statement="We expect revenue of INR 2,700 to 2,800 crores next year.",
                   effective_period="FY26")
    assert dc.verify_claim(plain)[0] == "verified"
    assert (plain["value_low"], plain["value_high"]) == (2700.0, 2800.0)


def test_mix_share_moves_to_revenue_mix_with_its_segment():
    claim = _claim(node="revenue.total", unit="pct", value_low=20.0, value_high=25.0, sign="+",
                   quote_span="20% to 25%",
                   statement="Exports contributed around 17% of total income; the medium-term target is 20% to 25%.",
                   effective_period="medium term")
    status, _ = dc.verify_claim(claim)
    assert status == "verified"
    assert claim["node"] == "revenue.mix"
    assert claim["segment"] == "exports"


def test_mix_rule_needs_a_pct_and_a_share_pattern():
    money = _claim(node="revenue.total", unit="inr_cr", value_low=20.0, quote_span="Rs. 20 crores",
                   statement="Exports contributed Rs. 20 crores of total income.", effective_period="FY26")
    assert dc.verify_claim(money)[0] == "verified"
    assert money["node"] == "revenue.total"
    growth = _claim(node="revenue.total", unit="pct", value_low=20.0, quote_span="20%",
                    statement="Revenue will grow 20% next year.", effective_period="FY26")
    assert dc.verify_claim(growth)[0] == "verified"
    assert growth["node"] == "revenue.total"


def test_list_of_values_must_span_the_numbers():
    trunc = _claim(node="revenue.total", unit="pct", value_low=8.0, value_high=8.0, sign="+",
                   quote_span="8%, 10%", statement="We expect an 8%, 10% increase in the top line.",
                   effective_period="FY26")
    assert dc.verify_claim(trunc) == ("unverified", "range_truncated")
    spans = _claim(node="revenue.total", unit="pct", value_low=8.0, value_high=10.0, sign="+",
                   quote_span="8%, 10%", statement="We expect an 8%, 10% increase in the top line.",
                   effective_period="FY26")
    assert dc.verify_claim(spans) == ("verified", "")
    rng = _claim(node="revenue.total", unit="pct", value_low=20.0, value_high=22.0, sign="+",
                 quote_span="20% to 22%", statement="We expect 20% to 22% growth next year.",
                 effective_period="FY26")
    assert dc.verify_claim(rng) == ("verified", "")


def test_from_to_with_a_percent_is_a_target():
    claim = _claim(node="margin.ebitda", unit="pct", value_low=20.0, value_high=None, sign="+",
                   quote_span="from 18% to 20%",
                   statement="We expect margins to move from 18% to 20% next year.",
                   effective_period="FY26")
    assert dc.verify_claim(claim) == ("verified", "")
    assert (claim["value_low"], claim["value_high"]) == (20.0, 20.0)
    assert claim["base"] == "18%" and claim["sign"] == "+"


def test_retag_mix_and_truncated_in_an_existing_db(db_path: Path):
    writer = dc.Writer(db_path)

    def legacy(source_id: int, **kw):
        row = _claim(source_id=source_id, **kw)
        row.update({"status": "verified", "status_reason": "", "created_at": "x", "judge_ok": 1,
                    "judge_fail": "", "judge_suggest": None})
        return row

    mix_agreed = legacy(2, node="revenue.total", unit="pct", value_low=20.0, value_high=25.0,
                        quote_span="20% to 25%",
                        statement="Exports contributed 20% to 25% of total income.")
    mix_agreed["judge_suggest"] = "revenue.mix"
    writer.insert_claims("run1", [
        legacy(1, node="revenue.total", unit="pct", value_low=20.0, value_high=25.0,
               quote_span="20% to 25%", statement="Exports contributed 20% to 25% of total income."),
        mix_agreed,
        legacy(3, node="revenue.total", unit="pct", value_low=8.0, value_high=8.0,
               quote_span="8%, 10%", statement="We expect an 8%, 10% increase in the top line.",
               effective_period="FY26"),
    ])
    writer.close()
    dc.retag_existing(db_path)
    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT source_id, node, segment, status, status_reason FROM claim "
                       "ORDER BY source_id").fetchall()
    con.close()
    assert rows == [(1, "revenue.mix", "exports", "unverified", "mix_retag"),
                     (2, "revenue.mix", "exports", "verified", ""),
                     (3, "revenue.total", "total", "unverified", "range_truncated")]


def test_mix_does_not_fire_on_a_margin_or_change_clause():
    # Wolf, round 6, from the three re-tagged sentences.
    margin = _claim(node="margin.ebitda", unit="pct", value_low=30.0, value_high=35.0, sign="0",
                    quote_span="30% to 35%",
                    statement="Quarter ended June 2025 is more aligned to usual product mix and EBIT margin "
                              "of 30% to 35%.", effective_period="Q1FY26")
    assert margin["node"] == "margin.ebitda"
    assert dc.verify_claim(margin)[0] == "verified"
    ebitda = _claim(node="margin.ebitda", unit="pct", value_low=25.0, sign="+",
                    quote_span="upwards of 25%",
                    statement="So Kavach as a product is a high margin because it's a safety technology "
                              "and we foresee that it should contribute anywhere upwards of 25% in terms "
                              "of EBITDA margins.", effective_period="FY26")
    assert dc.verify_claim(ebitda)[0] == "verified"
    assert ebitda["node"] == "margin.ebitda"
    better = _claim(node="revenue.total", unit="pct", value_low=25.0, sign="+",
                    quote_span="at least 25% better",
                    statement="We will have new product lines also, that is the tipping jacks is going to "
                              "contribute, Sumeet just mentioned about Rs. 8 crores to Rs. 10 crores for this "
                              "H2 time, H2 is going to be at least 25% better.", effective_period="H2FY26")
    assert dc.verify_claim(better)[0] == "verified"
    assert better["node"] == "revenue.total"


def test_mix_does_not_fire_on_a_change_clause_inside_a_long_span():
    claim = _claim(node="revenue.total", unit="pct", value_low=25.0, sign="+",
                   quote_span="that is the tipping jacks is going to contribute, Sumeet just mentioned about "
                              "Rs. 8 crores to Rs. 10 crores for this H2 time, H2 is going to be at least 25% better",
                   statement="We will have new product lines also, that is the tipping jacks is going to "
                             "contribute, Sumeet just mentioned about Rs. 8 crores to Rs. 10 crores for this "
                             "H2 time, H2 is going to be at least 25% better.", effective_period="H2FY26")
    dc.verify_claim(claim)
    assert claim["node"] == "revenue.total"


def test_retag_restores_a_wrongly_moved_mix_claim(db_path: Path):
    writer = dc.Writer(db_path)

    def moved(source_id: int, low: float, high, span: str, statement: str):
        row = _claim(source_id=source_id, node="revenue.mix", unit="pct", value_low=low,
                     value_high=high, quote_span=span, statement=statement, effective_period="FY26")
        row.update({"status": "unverified", "status_reason": "mix_retag", "created_at": "x",
                    "judge_ok": 1, "judge_fail": "", "judge_suggest": None})
        return row

    writer.insert_claims("run1", [
        moved(1, 30.0, 35.0, "30% to 35%",
              "Quarter ended June 2025 is more aligned to usual product mix and EBIT margin of 30% to 35%."),
        moved(2, 25.0, None, "upwards of 25%",
              "So Kavach should contribute anywhere upwards of 25% in terms of EBITDA margins."),
        moved(3, 25.0, None, "at least 25% better",
              "We will have new product lines also; H2 is going to be at least 25% better."),
    ])
    writer.close()
    dc.retag_existing(db_path)
    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT source_id, node, status, status_reason FROM claim ORDER BY source_id").fetchall()
    con.close()
    assert rows == [(1, "margin.ebitda", "verified", ""),
                    (2, "margin.ebitda", "verified", ""),
                    (3, "revenue.total", "verified", "")]


def test_prompts_carry_the_measure_and_renode_rules():
    prompt = dc.build_prompt([_item()], "Company: Test Ltd. It sells yarn.")
    assert "gross margin -> margin.gross" in prompt and "utilisation -> revenue.volume" in prompt
    assert "Company: Test Ltd." in prompt
    judge = dc.judge_prompt([{**dc._finish(_claim()), "id": 1}], "Company: Test Ltd.")
    assert "node_suggest" in judge and "gross margin -> margin.gross" in judge


def test_judge_node_suggest_renodes_instead_of_losing_the_claim(db_path: Path):
    writer = dc.Writer(db_path)
    writer.insert_claims("run1", [dc._finish(_claim(node="margin.ebitda", unit="pct", value_low=60.0,
                                                    quote_span="60% to 65% utilisation",
                                                    statement="We are targeting 60% to 65% utilisation.",
                                                    effective_period="FY26"))])
    cid = writer.con.execute("SELECT id FROM claim").fetchone()[0]
    verdict: dict[str, Any] = {f: True for f in dc.JUDGE_FIELDS}
    verdict.update({"node_ok": False, "node_suggest": "revenue.volume"})
    writer.apply_judge(int(cid), verdict)
    row = writer.con.execute(
        "SELECT node, status, status_reason, judge_suggest, judge_ok FROM claim").fetchone()
    writer.close()
    assert tuple(row) == ("revenue.volume", "unverified", "judge_renode", "revenue.volume", 0)


def test_judge_node_suggest_outside_the_tree_is_ignored(db_path: Path):
    writer = dc.Writer(db_path)
    writer.insert_claims("run1", [dc._finish(_claim())])
    cid = writer.con.execute("SELECT id FROM claim").fetchone()[0]
    verdict: dict[str, Any] = {f: True for f in dc.JUDGE_FIELDS}
    verdict.update({"node_ok": False, "node_suggest": "margin"})
    writer.apply_judge(int(cid), verdict)
    row = writer.con.execute("SELECT node, status, status_reason FROM claim").fetchone()
    writer.close()
    assert tuple(row) == ("capex.amount", "unverified", "judge:node_ok")


def test_judge_reply_parses_all_six_fields():
    verdicts = dc.parse_judge_reply(
        '{"items":[{"id":3,"node_ok":true,"sign_ok":false,"unit_ok":true,"period_ok":true,'
        '"forward_ok":true,"company_ok":false,"node_suggest":"margin.ebitda","why":"sign wrong"}]}')
    assert verdicts == [{"id": 3, "node_ok": True, "sign_ok": False, "unit_ok": True,
                         "period_ok": True, "forward_ok": True, "company_ok": False,
                         "node_suggest": "margin.ebitda", "why": "sign wrong"}]


def test_tolerant_judge_parser_reads_broken_json():
    broken = ('{"items":[{"id":11,"node_ok":true,"sign_ok":true,"unit_ok":true,'
              '"period_ok":true,"forward_ok":true,"company_ok":true,"node_suggest":"revenue.volume"},'
              '{"id":12,"node_ok":true,"sign_ok":false,')   # truncated second item
    verdicts = dc.parse_judge_reply(broken)
    assert verdicts == [{"id": 11, "node_ok": True, "sign_ok": True, "unit_ok": True,
                         "period_ok": True, "forward_ok": True, "company_ok": True,
                         "node_suggest": "revenue.volume", "why": ""}]


def test_judge_downgrades_a_claim_and_stores_the_failing_field(db_path: Path):
    writer = dc.Writer(db_path)
    claim = dc._finish(_claim())
    writer.insert_claims("run1", [claim])
    assert writer.claims_to_judge()                      # a script-verified claim is queued for judging
    cid = writer.con.execute("SELECT id FROM claim").fetchone()[0]
    writer.apply_judge(int(cid), {"node_ok": False, "sign_ok": True, "unit_ok": True, "period_ok": True,
                                  "forward_ok": True, "company_ok": True, "why": "receivables is not volume"})
    row = writer.con.execute("SELECT status, status_reason, judge_ok, judge_fail FROM claim").fetchone()
    writer.close()
    assert tuple(row) == ("unverified", "judge:node_ok", 0, "node_ok")


def test_judge_keeps_a_claim_verified_when_all_five_pass(db_path: Path):
    writer = dc.Writer(db_path)
    writer.insert_claims("run1", [dc._finish(_claim())])
    cid = writer.con.execute("SELECT id FROM claim").fetchone()[0]
    writer.apply_judge(int(cid), {f: True for f in dc.JUDGE_FIELDS} | {"why": "ok"})
    row = writer.con.execute("SELECT status, judge_ok, judge_fail FROM claim").fetchone()
    writer.close()
    assert tuple(row) == ("verified", 1, "")


def test_dedupe_keeps_one_row_per_symbol_span_and_node(db_path: Path):
    writer = dc.Writer(db_path)
    script = dc._finish(_claim(method="script", source_table="guidance", source_id=11, status="verified"))
    model = dc._finish(_claim(method="model"))
    writer.insert_claims("run1", [model])
    writer.insert_claims("run1", [script])
    removed = writer.dedupe()
    rows = writer.con.execute("SELECT method, source_table FROM claim").fetchall()
    writer.close()
    assert removed == 1
    assert [tuple(r) for r in rows] == [("script", "guidance")]


# ------------------------------------------------------------------ context
def test_context_is_the_two_statements_before_and_the_question():
    rows = [
        _row(id=1, seq=1, text="Good afternoon, everyone."),
        _row(id=2, seq=2, text="Thank you for joining the call."),
        _row(id=3, seq=3, text="We will add Rs. 55 crores annually from Q4.", numbers_json='[{"value":55}]',
             answer_turn=1),
        _row(id=4, seq=4, text="The plant is on track."),
        _row(id=5, seq=5, text="It will add Rs. 20 crores next year.", numbers_json='[{"value":20}]'),
    ]
    questions = {("D:/raw/BHAGERIA.pdf", 1): "What will the new line add to revenue?"}
    items, counters = dc.attach_context(rows, questions)
    assert counters["statements_with_numbers"] == 2
    assert counters["statements_sent"] == 2
    first, second = items
    assert first["source_id"] == 3
    assert first["context"] == ("S1: Good afternoon, everyone.\nS2: Thank you for joining the call.\n"
                                "Q: What will the new line add to revenue?")
    assert second["context"] == "S1: We will add Rs. 55 crores annually from Q4.\nS2: The plant is on track."
    assert first["text"].startswith("We will add")


def test_a_number_in_the_context_does_not_satisfy_the_quote():
    # The quote may only come from the target statement: a span lifted from the context is quarantined.
    claim = _claim(value_low=20.0, quote_span="Rs. 20 crores",
                   statement="It will add revenue next year.",
                   context="S1: It will add Rs. 20 crores next year.")
    assert dc.verify_claim(claim) == ("quarantined", "quote_span_not_in_statement")


def test_pick_stores_is_seeded_and_reproducible():
    candidates = ["c03", "c05", "c07", "c12", "c13", "c22"]
    picked = dc.pick_stores(candidates, 2, seed=7)
    assert picked == dc.pick_stores(list(reversed(candidates)), 2, seed=7)
    assert len(picked) == 2 and set(picked) <= set(candidates)


def test_pick_stores_returns_all_when_pool_is_small():
    assert dc.pick_stores(["c03"], 2, seed=7) == ["c03"]


# ------------------------------------------------------------------ resume + DB
def test_resume_skips_items_already_in_the_read_log(db_path: Path):
    writer = dc.Writer(db_path)
    done = ["c17|transcript_statement|250"]
    writer.read_log("run1", "c17", 1, "a", "b", 1.5, 200, 10, 5, 1, 1, {"claims": 1}, done, 1)
    assert writer.done_keys() == set(done)
    items = [{"key": "c17|transcript_statement|250"}, {"key": "c17|transcript_statement|251"}]
    assert [it["key"] for it in dc.pending_items(items, writer.done_keys())] == ["c17|transcript_statement|251"]
    writer.close()


def test_quota_event_records_utc_and_ist(db_path: Path):
    writer = dc.Writer(db_path)
    writer.quota_event("run1", "c17", 429, 12, "rate limit: " + "x" * 400)
    row = writer.con.execute("SELECT at_utc, at_ist, http_status, in_flight, body FROM quota_event").fetchone()
    writer.close()
    assert row[2:4] == (429, 12)
    assert row[0] and row[1] and row[0] != row[1]
    assert len(row[4]) == 300


def test_batch_writes_claims_and_marks_items_done(db_path: Path):
    writer = dc.Writer(db_path)
    reply = ('{"items":[{"id":1,"drop":null,"claims":[{"node":"capex.amount","sign":"+","value_low":55,'
             '"value_high":null,"unit":"inr_cr","effective_period":"Q4","conditional":false,'
             '"quote_span":"approximately Rs. 55 crores annually"}]}]}')

    class FakeClient:
        def chat(self, prompt):
            return 200, reply, (100, 50)

    limiter = dc.Adaptive(start=2)
    stats = dc.process_batch([_item()], FakeClient(), writer, limiter, "run1")
    assert stats.claims == 1 and stats.requests == 1 and stats.errors == 0
    claim = writer.con.execute("SELECT node, status, known_at, method, context FROM claim").fetchone()
    log = writer.con.execute("SELECT role, http_status, in_tok, out_tok, items_done FROM read_log").fetchone()
    writer.close()
    assert tuple(claim)[:4] == ("capex.amount", "verified", "2025-10-30T13:19:49", "model")
    assert claim[4].startswith("S1: Good afternoon.")
    assert log[0] == "extract" and log[1] == 200 and log[2:4] == (100, 50)
    assert log[4] == '["c17|transcript_statement|250"]'


def test_batch_retries_a_bad_json_reply_once_then_logs_an_error(db_path: Path):
    writer = dc.Writer(db_path)

    class BadClient:
        def __init__(self):
            self.calls = 0

        def chat(self, prompt):
            self.calls += 1
            return 200, "not json", (10, 1)

    bad = BadClient()
    stats = dc.process_batch([_item()], bad, writer, dc.Adaptive(start=2), "run1")
    rows = writer.con.execute("SELECT COUNT(*), SUM(error<>'') FROM read_log").fetchone()
    writer.close()
    assert bad.calls == 2                      # the brief: retry once, then log
    assert stats.errors == 1 and stats.claims == 0
    assert tuple(rows) == (2, 2)


def test_judge_batch_applies_verdicts_and_logs_a_judge_row(db_path: Path):
    writer = dc.Writer(db_path)
    writer.insert_claims("run1", [dc._finish(_claim(source_id=1)), dc._finish(_claim(source_id=2))])
    claims = writer.claims_to_judge()
    assert len(claims) == 2
    reply = json.dumps({"items": [
        {"id": claims[0]["id"], "node_ok": True, "sign_ok": True, "unit_ok": True, "period_ok": True,
         "forward_ok": True, "company_ok": True, "why": "ok"},
        {"id": claims[1]["id"], "node_ok": True, "sign_ok": False, "unit_ok": True, "period_ok": True,
         "forward_ok": True, "company_ok": True, "why": "sign"},
    ]})

    class JudgeClient:
        def chat(self, prompt):
            return 200, reply, (200, 40)

    stats = dc.judge_batch(claims, JudgeClient(), writer, dc.Adaptive(start=2), "run1")
    statuses = writer.con.execute("SELECT status, status_reason FROM claim ORDER BY id").fetchall()
    log = writer.con.execute("SELECT role, items FROM read_log WHERE role='judge'").fetchone()
    writer.close()
    assert stats.judged == 2 and stats.judged_ok == 1 and stats.by_field["sign_ok"] == 1
    assert [tuple(r) for r in statuses] == [("verified", ""), ("unverified", "judge:sign_ok")]
    assert log[0] == "judge" and log[1] == 2


def test_judge_batch_falls_back_to_block_position_when_ids_are_1_to_n(db_path: Path):
    writer = dc.Writer(db_path)
    writer.insert_claims("run1", [dc._finish(_claim(source_id=1)), dc._finish(_claim(source_id=2))])
    claims = writer.claims_to_judge()
    # beam-free sometimes numbers its answers 1..n instead of echoing CLAIM <id>
    reply = json.dumps({"items": [
        {"id": 1, "node_ok": True, "sign_ok": True, "unit_ok": True, "period_ok": True, "forward_ok": True,
         "company_ok": True},
        {"id": 2, "node_ok": True, "sign_ok": False, "unit_ok": True, "period_ok": True, "forward_ok": True,
         "company_ok": True},
    ]})

    class JudgeClient:
        def chat(self, prompt):
            return 200, reply, (200, 40)

    stats = dc.judge_batch(claims, JudgeClient(), writer, dc.Adaptive(start=2), "run1")
    statuses = writer.con.execute("SELECT status FROM claim ORDER BY id").fetchall()
    writer.close()
    assert stats.judged == 2 and stats.judged_ok == 1
    assert [tuple(r) for r in statuses] == [("verified",), ("unverified",)]


def test_judge_rejects_an_industry_claim(db_path: Path):
    writer = dc.Writer(db_path)
    writer.insert_claims("run1", [dc._finish(_claim())])
    cid = writer.con.execute("SELECT id FROM claim").fetchone()[0]
    writer.apply_judge(int(cid), {"node_ok": True, "sign_ok": True, "unit_ok": True, "period_ok": True,
                                  "forward_ok": True, "company_ok": False})
    row = writer.con.execute("SELECT status, judge_fail, judge_company FROM claim").fetchone()
    writer.close()
    assert tuple(row) == ("unverified", "company_ok", 0)


def test_reset_judge_errors_requeues_them(db_path: Path):
    writer = dc.Writer(db_path)
    writer.insert_claims("run1", [dc._finish(_claim())])
    cid = writer.con.execute("SELECT id FROM claim").fetchone()[0]
    writer.mark_judge_failed([int(cid)])
    assert writer.reset_judge_errors() == 1
    row = writer.con.execute("SELECT status, judge_ok, judge_fail FROM claim").fetchone()
    writer.close()
    assert tuple(row) == ("verified", None, None)


def test_judge_retries_twice_then_accepts(db_path: Path, monkeypatch):
    monkeypatch.setattr(dc, "JUDGE_BACKOFF_S", (0.0, 0.0))
    writer = dc.Writer(db_path)
    writer.insert_claims("run1", [dc._finish(_claim())])
    claims = writer.claims_to_judge()
    good = json.dumps({"items": [{**{f: True for f in dc.JUDGE_FIELDS}, "id": claims[0]["id"]}]})

    class FlakyJudge:
        calls = 0

        def chat(self, prompt):
            self.calls += 1
            if self.calls < 3:
                return 200, "garbage with no verdicts", (10, 1)
            return 200, good, (10, 1)

    judge = FlakyJudge()
    stats = dc.judge_batch(claims, judge, writer, dc.Adaptive(start=2), "run1")
    row = writer.con.execute("SELECT status, judge_ok FROM claim").fetchone()
    writer.close()
    assert judge.calls == 3                      # first attempt + two retries
    assert stats.judge_http_codes["200"] == 3
    assert stats.judged_ok == 1 and tuple(row) == ("verified", 1)


def test_judge_batch_marks_claims_unverified_when_the_judge_fails(db_path: Path, monkeypatch):
    monkeypatch.setattr(dc, "JUDGE_BACKOFF_S", (0.0, 0.0))
    writer = dc.Writer(db_path)
    writer.insert_claims("run1", [dc._finish(_claim())])
    claims = writer.claims_to_judge()

    class DeadJudge:
        calls = 0

        def chat(self, prompt):
            self.calls += 1
            return 500, "upstream error", (0, 0)

    judge = DeadJudge()
    stats = dc.judge_batch(claims, judge, writer, dc.Adaptive(start=2), "run1")
    row = writer.con.execute("SELECT status, status_reason, judge_fail FROM claim").fetchone()
    quota = writer.con.execute("SELECT COUNT(*) FROM quota_event").fetchone()[0]
    writer.close()
    assert judge.calls == 3 and stats.judge_errors == 1
    assert tuple(row) == ("unverified", "judge_error", "judge_error")
    assert quota >= 1 and stats.judge_http_codes["500"] == 3


# ------------------------------------------------------------------ limiter
def test_limiter_raises_after_five_minutes_under_the_error_rate():
    now = [1000.0]
    lim = dc.Adaptive(start=10, unleashed=True, clock=lambda: now[0])
    for _ in range(10):
        lim.saw(True)
    now[0] += 301.0
    for _ in range(10):
        lim.saw(True)
    lim.tick()                                  # 301 s since construction, 10 clean requests in the window
    assert lim.limit == 20
    lim.tick()                                  # less than 300 s since the last raise: no second raise
    assert lim.limit == 20


def test_limiter_does_not_raise_when_the_error_rate_is_high():
    now = [0.0]
    lim = dc.Adaptive(start=10, unleashed=True, clock=lambda: now[0])
    now[0] = 301.0
    for ok in [False, False, True, True, True]:
        lim.saw(ok)
    lim.tick()
    assert lim.limit == 10


def test_limiter_halves_on_a_429_with_a_floor_of_one():
    lim = dc.Adaptive(start=30)
    assert lim.halve() == 15
    assert lim.halve() == 7
    lim = dc.Adaptive(start=1)
    assert lim.halve() == 1


def test_limiter_stops_after_thirty_minutes_of_failures():
    now = [0.0]
    lim = dc.Adaptive(start=10, unleashed=True, clock=lambda: now[0])
    lim.saw(False)
    now[0] = 1799.0
    lim.tick()
    assert not lim.stopped.is_set()
    now[0] = 1801.0
    lim.tick()
    assert lim.stopped.is_set()


def test_limiter_gate_never_exceeds_the_limit():
    lim = dc.Adaptive(start=2)
    lim.acquire()
    lim.acquire()
    assert lim.active == 2
    lim.stopped.set()
    with pytest.raises(dc.Stopped):
        lim.acquire()
