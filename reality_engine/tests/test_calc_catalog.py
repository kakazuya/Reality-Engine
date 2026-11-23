"""T-135: the calc catalog reproduces every compute-class failure of the 8-9 Nov re-asks with one call.

Run from the repo root:
    python -m pytest reality_engine/tests/test_calc_catalog.py -q

No fixtures and no database: ``calc_catalog`` is pure arithmetic over parsed inputs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "plugins" / "reality-data" / "server"))

import calc_catalog  # noqa: E402


def cat(name: str, **inputs):
    return calc_catalog.run({"name": name, "inputs": inputs})


# --- 1. GROWTH: BAJFINANCE-005, TTM PAT 22,067 vs FY26 19,332 crore ------------------------------------


def test_growth_bajfinance_005_is_14_15_pct():
    out = cat("GROWTH", now="22,067 crore", before="19,332 crore")
    assert out["value"] == pytest.approx(100 * (22067 / 19332 - 1), abs=1e-6)
    assert round(out["value"], 2) == 14.15
    assert "14.15%" in out["formula"]
    assert out["unit"] == "percent"


def test_growth_refuses_a_zero_base():
    out = cat("GROWTH", now="10 crore", before="0 crore")
    assert "error" in out and "base" in out["error"]


# --- 2. TTM_SUM: four labelled quarters ---------------------------------------------------------------


def test_ttm_sum_adds_four_consecutive_quarters():
    out = cat("TTM_SUM", q1="1,000 crore", q2="1,100 crore", q3="1,000 crore", q4="1,200 crore",
              periods=["Q1FY26", "Q2FY26", "Q3FY26", "Q4FY26"])
    assert out["crore"] == 4300
    assert out["periods"] == ["Q1FY26", "Q2FY26", "Q3FY26", "Q4FY26"]


def test_ttm_sum_refuses_labels_that_are_not_consecutive():
    out = cat("TTM_SUM", q1=1, q2=2, q3=3, q4=4, periods=["Q1FY26", "Q2FY26", "Q4FY26", "Q1FY27"])
    assert "error" in out and "consecutive" in out["error"]


# --- 3. TTM_GROWTH: KEC-081 compared a TTM with a fiscal year it overlaps -----------------------------


def test_ttm_growth_clean_ttm_against_ttm_a_year_earlier():
    out = cat("TTM_GROWTH", ttm_now="22,067 crore", ttm_year_ago="19,332 crore",
              period_now="TTM Q2FY27", period_before="TTM Q2FY26")
    assert round(out["value"], 2) == 14.15


def test_ttm_growth_kec_081_refuses_an_overlapping_fiscal_year():
    out = cat("TTM_GROWTH", ttm_now="22,067 crore", ttm_year_ago="19,332 crore",
              period_now="TTM Q2FY27", period_before="FY26")
    assert "error" in out
    assert "Q3FY26" in out["error"] and "Q4FY26" in out["error"]
    assert "overlap" in out["error"]


# --- 4. Q_FROM_CUMULATIVE: SBILIFE-081 Q3/Q4 from 9M and FY ------------------------------------------


def test_q_from_cumulative_fy_minus_9m_is_q4():
    out = cat("Q_FROM_CUMULATIVE", longer=100, shorter=72,
              longer_label="FY26", shorter_label="9MFY26")
    assert out["value"] == 28
    assert out["period"] == "Q4FY26"
    assert "Q4FY26" in out["formula"]


def test_q_from_cumulative_9m_minus_h1_is_q3_and_h1_minus_q1_is_q2():
    assert cat("Q_FROM_CUMULATIVE", longer=90, shorter=60,
               longer_label="9MFY26", shorter_label="H1FY26")["period"] == "Q3FY26"
    assert cat("Q_FROM_CUMULATIVE", longer=60, shorter=20,
               longer_label="H1FY26", shorter_label="Q1FY26")["period"] == "Q2FY26"


def test_q_from_cumulative_refuses_a_pair_that_is_not_one_quarter():
    out = cat("Q_FROM_CUMULATIVE", longer=100, shorter=40, longer_label="FY26", shorter_label="H1FY26")
    assert "error" in out


# --- 5. SHARE -----------------------------------------------------------------------------------------


def test_share_is_a_percent_of_the_whole():
    out = cat("SHARE", part="366 crore", total="1,208 crore")
    assert out["value"] == pytest.approx(366 / 1208 * 100, abs=1e-6)


# --- 6. CONTRIBUTION_TO_INCREASE ----------------------------------------------------------------------


def test_contribution_to_increase_explains_half_the_total_change():
    out = cat("CONTRIBUTION_TO_INCREASE", part_now=80, part_before=60, total_now=240, total_before=200)
    assert out["value"] == 50


# --- 7. CASH_CONVERSION: ETERNAL-020 ----------------------------------------------------------------


def test_cash_conversion_eternal_020_is_1_727x_and_0_523x():
    out = cat("CASH_CONVERSION", ocf="632 crore", pat="366 crore", ebitda="1,208 crore")
    assert round(out["values"]["ocf_to_pat"], 3) == 1.727
    assert round(out["values"]["ocf_to_ebitda"], 3) == 0.523
    assert out["unit"] == "x"


def test_cash_conversion_refuses_mixed_units():
    out = cat("CASH_CONVERSION", ocf="632 crore", pat="366 lakh units", ebitda="1,208 crore")
    assert "error" in out and "unit" in out["error"].lower()


# --- 8. INCREMENTAL_ROCE: HINDUNILVR-031 -------------------------------------------------------------


def test_incremental_roce_is_the_change_in_ebit_over_the_change_in_capital():
    out = cat("INCREMENTAL_ROCE", ebit_now=1200, ebit_before=1000,
              capital_employed_now=5000, capital_employed_before=4000)
    assert out["value"] == 20  # the level ROCE (1200/5000 = 24%) is the wrong answer
    assert "24" not in out["formula"]


def test_incremental_roce_refuses_a_shrinking_capital_base():
    out = cat("INCREMENTAL_ROCE", ebit_now=1200, ebit_before=1000,
              capital_employed_now=4000, capital_employed_before=5000)
    assert "error" in out


# --- 9. RANGE_POSITION: BAJFINANCE-123 ---------------------------------------------------------------


def test_range_position_bajfinance_123_is_40_68_pct_middle_third():
    out = cat("RANGE_POSITION", x=30.9, low=26.1, high=37.9)
    assert round(out["value"], 2) == 40.68
    assert out["third"] == "middle third"
    assert "middle third" in " ".join(out["notes"])


# --- 10. FAIR_PB and IMPLIED_ROE: HDFCBANK-120 -------------------------------------------------------


def test_fair_pb_hdfcbank_120_is_1_5():
    out = cat("FAIR_PB", roe="14.5%", cost_of_equity="12%", growth="7%")
    assert out["value"] == 1.5
    assert out["unit"] == "x"


def test_implied_roe_hdfcbank_120_is_16_25_pct():
    out = cat("IMPLIED_ROE", pb=1.85, cost_of_equity="12%", growth="7%")
    assert out["value"] == pytest.approx(16.25, abs=1e-9)


def test_fair_pb_refuses_growth_at_or_above_the_cost_of_equity():
    assert "error" in cat("FAIR_PB", roe="14.5%", cost_of_equity="7%", growth="7%")


# --- 11. IMPLIED_GROWTH_PE ----------------------------------------------------------------------------


def test_implied_growth_from_pe_payout_and_cost_of_equity():
    out = cat("IMPLIED_GROWTH_PE", pe=20, payout="40%", cost_of_equity="12%")
    assert out["value"] == pytest.approx((20 * 0.12 - 0.4) / (20 + 0.4) * 100, abs=1e-6)
    assert round(out["value"], 2) == 9.80


# --- 12. ANNUALISE: SBILIFE-105 -----------------------------------------------------------------------


def test_annualise_sbilife_105_six_months_is_18_8_pct_annualised():
    out = cat("ANNUALISE", rate="9.4%", months=6, method="simple")
    assert out["value"] == pytest.approx(18.8, abs=1e-9)
    assert out["label"] == "annualised"
    assert "annualised" in json.dumps(out)


def test_annualise_compound_is_the_compounded_rate():
    out = cat("ANNUALISE", rate="9.4%", months=6, method="compound")
    assert out["value"] == pytest.approx((1.094 ** 2 - 1) * 100, rel=1e-9)


def test_annualise_refuses_an_unknown_method():
    assert "error" in cat("ANNUALISE", rate="9.4%", months=6, method="weekly")


# --- 13. SAME_SPAN_GROWTH: MARUTI-023 ----------------------------------------------------------------


def test_same_span_growth_maruti_023_refuses_six_months_against_a_year():
    out = cat("SAME_SPAN_GROWTH", balance_now="1,000 crore", balance_before="900 crore",
              flow_now="1,200 crore", flow_before="1,000 crore",
              balance_now_label="2026-03-31", balance_before_label="2025-09-30",
              flow_now_label="FY26", flow_before_label="FY25")
    assert "error" in out
    assert "6 months" in out["error"] and "12 months" in out["error"]


def test_same_span_growth_returns_both_growths_over_one_span():
    out = cat("SAME_SPAN_GROWTH", balance_now="1,000 crore", balance_before="900 crore",
              flow_now="1,200 crore", flow_before="1,000 crore",
              balance_now_label="2026-03-31", balance_before_label="2025-03-31",
              flow_now_label="FY26", flow_before_label="FY25")
    assert round(out["values"]["balance_growth_pct"], 2) == 11.11
    assert round(out["values"]["flow_growth_pct"], 2) == 20.00
    assert out["span_months"] == 12


# --- 14. PROFIT_BRIDGE_MARGIN: ETERNAL-113 ------------------------------------------------------------


def test_profit_bridge_eternal_113_margin_needed_for_a_pat_target():
    out = cat("PROFIT_BRIDGE_MARGIN", target_pat="366 crore", revenue="1,208 crore", tax_rate="25%",
              depreciation="120 crore", finance_cost="40 crore", other_income="10 crore")
    assert out["ebitda_crore"] == 638
    assert out["value"] == pytest.approx(638 / 1208 * 100, abs=1e-6)


# --- the catalog itself and the p3ask wiring ----------------------------------------------------------


def test_list_prints_every_formula_and_the_tech_kinds():
    listing = calc_catalog.run({"name": "list"})
    assert listing["count"] == 15 == len(listing["ids"])
    for formula_id in ("GROWTH", "TTM_SUM", "TTM_GROWTH", "Q_FROM_CUMULATIVE", "SHARE",
                       "CONTRIBUTION_TO_INCREASE", "CASH_CONVERSION", "INCREMENTAL_ROCE", "RANGE_POSITION",
                       "FAIR_PB", "IMPLIED_ROE", "IMPLIED_GROWTH_PE", "ANNUALISE", "SAME_SPAN_GROWTH",
                       "PROFIT_BRIDGE_MARGIN"):
        assert formula_id in listing["ids"]
    assert "see tech kind=reaction" in listing["tech"]
    assert "see tech kind=rsi" in listing["tech"]


def test_every_reply_carries_the_documented_shape():
    calls = {
        "GROWTH": dict(now=121, before=100),
        "TTM_SUM": dict(q1=1, q2=2, q3=3, q4=4, periods=["Q1FY26", "Q2FY26", "Q3FY26", "Q4FY26"]),
        "TTM_GROWTH": dict(ttm_now=121, ttm_year_ago=100),
        "Q_FROM_CUMULATIVE": dict(longer=100, shorter=72, longer_label="FY26", shorter_label="9MFY26"),
        "SHARE": dict(part=1, total=4),
        "CONTRIBUTION_TO_INCREASE": dict(part_now=4, part_before=2, total_now=10, total_before=6),
        "CASH_CONVERSION": dict(ocf=120, pat=100, ebitda=200),
        "INCREMENTAL_ROCE": dict(ebit_now=120, ebit_before=100, capital_employed_now=200,
                                 capital_employed_before=100),
        "RANGE_POSITION": dict(x=5, low=0, high=10),
        "FAIR_PB": dict(roe="15%", cost_of_equity="12%", growth="7%"),
        "IMPLIED_ROE": dict(pb=1.5, cost_of_equity="12%", growth="7%"),
        "IMPLIED_GROWTH_PE": dict(pe=20, payout="40%", cost_of_equity="12%"),
        "ANNUALISE": dict(rate="9.4%", months=6, method="simple"),
        "SAME_SPAN_GROWTH": dict(balance_now=110, balance_before=100, flow_now=120, flow_before=100,
                                 balance_now_label="2026-03-31", balance_before_label="2025-03-31",
                                 flow_now_label="FY26", flow_before_label="FY25"),
        "PROFIT_BRIDGE_MARGIN": dict(target_pat=75, revenue=1000, tax_rate="25%", depreciation=20,
                                     finance_cost=10, other_income=5),
    }
    for formula_id, inputs in calls.items():
        out = calc_catalog.run({"name": formula_id, "inputs": inputs})
        assert "error" not in out, (formula_id, out)
        assert set(("formula_id", "value", "unit", "formula", "inputs", "notes")) <= set(out), formula_id
        assert set(inputs) <= set(out["inputs"]), f"{formula_id}: the inputs are echoed back"


def test_unknown_formula_is_an_error_that_lists_the_ids():
    out = calc_catalog.run({"name": "NOPE"})
    assert "error" in out and "GROWTH" in out["error"]


def test_p3ask_runs_the_catalog():
    from reality_engine.scripts import p3ask

    out = p3ask.run("nonexistent.db", "catalog",
                    {"name": "GROWTH", "inputs": {"now": "22,067 crore", "before": "19,332 crore"}})
    assert round(out["value"], 2) == 14.15
    assert p3ask.run("nonexistent.db", "catalog", {"name": "list"})["count"] == 15
