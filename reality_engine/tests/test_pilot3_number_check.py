"""Tests for reality_engine/pilot3/number_check.py and answer_record.py (T-072), from dev-set answer rows.

The rows are trimmed copies of real answers of the 600-answer run: a market cap, a share count, an interest
cover, a percentage change and a computed source, each in the shape the checker has to read.  Run:

    python -m pytest reality_engine/tests/test_pilot3_number_check.py -q
"""
from __future__ import annotations

import json
import shutil
from fractions import Fraction
from pathlib import Path

import pytest

from reality_engine.pilot3 import answer_record, number_check


def _tmp_dir() -> Path:
    """A clean writable directory: the sandbox denies pytest its own tmp_path."""
    path = Path(".tmp") / "test_number_check"
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def codes(report: dict, severity: str = "fail") -> set[str]:
    return {f["code"] for f in report["findings"] if f["severity"] == severity}


# --- reading an amount out of prose -------------------------------------------------------------------
def test_amount_unit_words() -> None:
    found = number_check.amounts("a consideration of Rs 2,711.9m (about Rs 2.71bn), 14.53 crore shares, 5.0%")
    values = {(a["family"], a["value"]) for a in found}
    assert ("money", Fraction("2711900000")) in values        # "Rs 2,711.9m" is 2.7119 billion rupees
    assert ("money", Fraction("2710000000")) in values        # Rs 2.71bn
    assert ("count", Fraction("145300000")) in values         # 14.53 crore shares is 145.3 million shares
    assert ("pct", Fraction("5.0")) in values


def test_unit_family_scale() -> None:
    assert number_check.unit_family("Rs lakh (i.e. Rs 3,417,946 crore)") == ("money", 10 ** 5)
    assert number_check.unit_family("INR cr GST") == ("money", 10 ** 7)
    assert number_check.unit_family("shares held by that bucket (14.53 crore)") == ("count", 1)
    assert number_check.unit_family("% of shares held by FPIs") == ("pct", 1)
    assert number_check.unit_family("INR per share") == ("money", 1)
    assert number_check.unit_family("trading days") == ("count", 1)
    assert number_check.unit_family("business acquired")[0] is None


def test_slip_is_a_shifted_decimal_not_a_near_miss() -> None:
    # 3.18 crore shares for 31.766 crore: the same digits one place out is a slip.
    assert number_check.slip_factor(Fraction("31800000"), Fraction("317662224"), "3.18") == -10
    # 253.64 crore against a real 2,552.20 crore is two different amounts, 0.6% away from being a 10x ratio.
    assert number_check.slip_factor(Fraction("2536400000"), Fraction("25522000000"), "253.64") is None
    # One significant figure cannot be judged: 0.05 crore against 5.48 crore is not evidence of anything.
    assert number_check.slip_factor(Fraction("500000"), Fraction("54800000"), "0.05") is None


def test_grouping() -> None:
    assert number_check.grouping_ok("3,41,79,459") is True       # Indian
    assert number_check.grouping_ok("34,179,459") is True        # Western
    assert number_check.grouping_ok("3,4,179,458") is False      # neither
    assert number_check.grouping_ok("3574") is None              # nothing to judge


# --- a ten-times unit slip in the answer text ---------------------------------------------------------
def test_unit_slip_against_the_numbers_list() -> None:
    row = {"qid": "SUNPHARMA-116", "status": "answered",
           "answer": "Sun Pharma bought 100% of Innovcare for a consideration of Rs 2,711.9m (about Rs 27 crore, "
                     "or Rs 2.71bn).",
           "numbers": [{"value": 2711.9, "unit": "INR mn", "period": "Q2FY27",
                        "source": "results note 9", "quote": ""}]}
    report = number_check.check_answer(row)
    assert report["ok"] is False
    assert "unit_slip" in codes(report)
    assert "2.7119e+09" in " ".join(f["detail"] for f in report["findings"])


def test_a_fall_between_two_share_counts() -> None:
    row = {"qid": "HDFCBANK-030", "status": "answered",
           "answer": "In share terms FPI holdings fell from 5,58,41,68,636 to 5,26,65,06,412 shares, a fall of "
                     "about 3.18 crore shares.",
           "numbers": [{"value": 5266506412, "unit": "shares FPI holding", "period": "Q2FY27",
                        "source": "shp_category fpi_total", "quote": ""}]}
    report = number_check.check_answer(row)
    assert report["ok"] is False
    assert "unit_slip" in codes(report)


# --- a stated working that does not hold --------------------------------------------------------------
def test_interest_cover_stated_in_the_text() -> None:
    row = {"qid": "INFY-019", "status": "answered",
           "answer": "in Q2 FY27 EBIT of Rs 11,178 crore covers finance cost of Rs 115 crore 101.6 times",
           "numbers": [{"value": 101.6, "unit": "times", "period": "Q2FY27", "source": "ratio_panel", "quote": ""},
                       {"value": 11178, "unit": "INR crore EBIT", "period": "Q2FY27", "source": "x", "quote": ""},
                       {"value": 115, "unit": "INR crore finance cost", "period": "Q2FY27", "source": "x",
                        "quote": ""}]}
    assert "stated_working" in codes(number_check.check_answer(row))


def test_percent_below_a_stated_base() -> None:
    row = {"qid": "BAJFINANCE-123", "status": "answered",
           "answer": "EPS about Rs 31.91 (10% below the Rs 34.88 trailing EPS).",
           "numbers": [{"value": 31.91, "unit": "Rs EPS on 90% PAT", "period": "FY28", "source": "x", "quote": ""}]}
    assert "stated_working" in codes(number_check.check_answer(row))


# --- formulas, quotes and old computed sources --------------------------------------------------------
def test_a_consistent_computed_source_passes() -> None:
    row = {"qid": "BAJFINANCE-121", "status": "answered",
           "answer": "FPIs held 1,231,954,447 shares, or 19.79%, worth about Rs 1,19,499.6 crore at Rs 970.",
           "numbers": [{"value": 119499.6, "unit": "Rs crore FPI holding value", "period": "2026-11-03",
                        "source": "computed: 1,231,954,447 x 970", "quote": ""}]}
    assert number_check.check_answer(row)["ok"] is True


def test_a_computed_source_that_does_not_recompute() -> None:
    row = {"qid": "SBILIFE-117", "status": "answered",
           "answer": "On LTM VoNB of about Rs 63.0 bn the multiple is 12.9x.",
           "numbers": [{"value": 63.0, "unit": "INR bn LTM VoNB", "period": "Q3FY26-Q2FY27",
                        "source": "computed: 22.9 + 16.3 + 14.1 + 18.6 (derived quarterly VoNB)", "quote": ""}]}
    assert "formula_mismatch" in codes(number_check.check_answer(row))


def test_formula_with_named_inputs() -> None:
    good = {"qid": "X", "answer": "", "numbers": [
        {"value": 23013, "unit": "INR crore", "period": "FY26", "source": "x",
         "formula": "revenue - pat", "inputs": {"revenue": "23506 crore", "pat": "493 crore"}}]}
    assert number_check.check_answer(good)["ok"] is True
    bad = {"qid": "Y", "answer": "", "numbers": [
        {"value": 21300, "unit": "INR crore", "period": "FY26", "source": "x",
         "formula": "revenue - pat", "inputs": {"revenue": "23506 crore", "pat": "493 crore"}}]}
    assert "formula_mismatch" in codes(number_check.check_answer(bad))


def test_quote_mismatch() -> None:
    # the value printed literally passes, whatever scale the unit word implies
    literal = {"qid": "Z", "answer": "", "numbers": [
        {"value": 2.9, "unit": "units", "period": "FY26", "source": "x", "quote": "volume of 2.9 million units"}]}
    assert codes(number_check.check_answer(literal)) == set()
    # a computed figure is not checked against its input quote
    computed = {"qid": "Z", "answer": "", "numbers": [
        {"value": 5.7, "unit": "pct", "period": "FY26", "source": "computed: 8,421/22,882",
         "quote": "market cap of Rs 8,421 crore"}]}
    assert "quote_mismatch" not in codes(number_check.check_answer(computed))
    # absent from a cut quote is a warning, never a block
    absent = {"qid": "Z", "answer": "", "numbers": [
        {"value": 3574, "unit": "Rs crore gross NPA", "period": "Q2FY27", "source": "x",
         "quote": "Gross NPAs were 35,736 crore"}]}
    assert codes(number_check.check_answer(absent)) == set()
    assert "quote_mismatch" in codes(number_check.check_answer(absent), severity="warn")
    # the same digits carrying a different value is the only scale failure
    scale = {"qid": "Z", "answer": "", "numbers": [
        {"value": 2.9, "unit": "INR lakh", "period": "FY26", "source": "x", "quote": "a value of 2.9 crore"}]}
    assert "quote_mismatch" in codes(number_check.check_answer(scale))
    conversion = {"qid": "Z", "answer": "", "numbers": [
        {"value": 14445.4, "unit": "Rs crore", "period": "FY26", "source": "x",
         "quote": "Profit after Tax of Rs 144,454 million"}]}
    assert codes(number_check.check_answer(conversion)) == set()

def test_record_refuses_a_failing_answer_then_takes_an_override() -> None:
    tmp_path = _tmp_dir()
    answer = {"qid": "T-1", "status": "answered", "answer": "a gross NPA of Rs 3,574 crore",
              "numbers": [{"value": 3574, "unit": "Rs crore gross NPA", "period": "Q2FY27",
                           "source": "computed: 3574 + 100", "quote": ""}]}
    path = tmp_path / "a.json"
    path.write_text(json.dumps(answer), encoding="utf-8")
    assert answer_record.record("DEMO", "answer", str(path), tmp_path) == 1
    recorded = [json.loads(line) for line in (tmp_path / "DEMO_answers.jsonl").read_text().splitlines()]
    assert recorded[0]["event"] == "check_failed" and recorded[0]["qid"] == "T-1"
    assert answer_record.record("DEMO", "start", "T-1", tmp_path) == 0
    answer["check_override"] = "the store's own row is one out; see T-072"
    path.write_text(json.dumps(answer), encoding="utf-8")
    assert answer_record.record("DEMO", "answer", str(path), tmp_path) == 0
    rows = [json.loads(line) for line in (tmp_path / "DEMO_answers.jsonl").read_text().splitlines()]
    assert [row["event"] for row in rows] == ["check_failed", "start", "answer"]
    assert rows[-1]["check_override"] and rows[-1]["check_failures"]


def test_an_answer_without_numbers_is_recorded() -> None:
    tmp_path = _tmp_dir()
    answer = {"qid": "T-2", "status": "not_found", "answer": "Not in the held documents.", "numbers": []}
    path = tmp_path / "b.json"
    path.write_text(json.dumps(answer), encoding="utf-8")
    assert answer_record.record("DEMO", "answer", str(path), tmp_path) == 0
    assert "T-2" in (tmp_path / "DEMO_answers.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize("bad", ["1/0", "__import__('os')"])
def test_bad_formulas_are_errors_never_guesses(bad: str) -> None:
    row = {"qid": "Q", "answer": "", "numbers": [
        {"value": 1, "unit": "INR crore", "period": "FY26", "source": "x", "formula": bad}]}
    report = number_check.check_answer(row)
    assert "formula_mismatch" in codes(report)   # the formula field must work; an error is a failure

def test_source_formula_is_read_whole() -> None:
    """A fragment is never checked: the root and the whole expression, or nothing."""
    cagr = {"qid": "S", "answer": "", "numbers": [
        {"value": 84.9, "unit": "pct CAGR", "period": "FY21-FY26", "source": "computed (647.1/30)^(1/5)-1"}]}
    assert codes(number_check.check_answer(cagr)) == set()
    unreadable = {"qid": "S", "answer": "", "numbers": [
        {"value": -41, "unit": "INR crore PAT change", "period": "FY26",
         "source": "computed: 455 - 496 (-(8.2/100))"}]}
    assert codes(number_check.check_answer(unreadable)) == set()
    assert "formula_mismatch" in codes(number_check.check_answer(unreadable), severity="warn")


def test_a_fraction_and_a_percent_are_compared_at_both_scales() -> None:
    rises = {"qid": "S", "answer": "", "numbers": [
        {"value": 18.4, "unit": "pct growth", "period": "FY26", "source": "computed: 6,975/6,016-1"}]}
    assert "formula_mismatch" in codes(number_check.check_answer(rises))
    share = {"qid": "S", "answer": "", "numbers": [
        {"value": 115, "unit": "pct of PAT", "period": "FY26", "source": "computed: 33,986 / 29,474"}]}
    assert codes(number_check.check_answer(share)) == set()


def test_dates_and_years_are_not_operands() -> None:
    row = {"qid": "D", "answer": "Between 4 August and 3 November the price moved, and 2025 to 2026 was flat.",
           "numbers": []}
    assert number_check.check_answer(row)["findings"] == []


def test_a_sum_is_read_the_same_way_on_both_sides() -> None:
    crores = {"qid": "S", "answer": "The three add to 6,300 + 3,546 + 2,872 = 12,718 crore in all.",
              "numbers": []}
    assert number_check.check_answer(crores)["findings"] == []


def test_a_mixed_chain_is_read_whole_or_skipped() -> None:
    row = {"qid": "S", "answer": "That is 178,650 less 141,688 plus 4,902 = 41,864 crore.", "numbers": []}
    assert codes(number_check.check_answer(row)) == set()


def test_the_endpoints_rounding_is_allowed() -> None:
    row = {"qid": "S", "answer": "The margin fell from 50.4% to 45.7%, a fall of 9.4%.", "numbers": []}
    assert codes(number_check.check_answer(row)) == set()


def test_two_significant_figures_are_not_evidence() -> None:
    chance = {"qid": "S", "answer": "It paid Rs 41 crore of tax.",
              "numbers": [{"value": 408, "unit": "INR crore tax", "period": "FY26", "source": "x"}]}
    assert codes(number_check.check_answer(chance)) == set()
    # ... unless the answer prints that entry exactly, nearby: the restatement case
    tied = {"qid": "S", "answer": "A consideration of Rs 2,711.9m (about Rs 27 crore).",
            "numbers": [{"value": 2711.9, "unit": "INR mn", "period": "Q2FY27", "source": "x"}]}
    assert "unit_slip" in codes(number_check.check_answer(tied))


def test_tsv_carries_the_qid() -> None:
    import shutil
    probe = Path(".tmp") / "test_number_check_tsv"
    shutil.rmtree(probe, ignore_errors=True)
    probe_answer = {"qid": "Q-9", "answer": "It paid Rs 41 crore of tax.",
                    "numbers": [{"value": 408, "unit": "INR crore tax", "period": "FY26", "source": "x"}]}
    answers = [number_check.check_answer(probe_answer)]
    findings = [{"file": "A_answers.jsonl", "qid": answer["qid"], **finding}
                for answer in answers for finding in answer["findings"]]
    assert findings, "the probe answer must produce at least one warning finding"
    out = probe / "findings.tsv"
    number_check.write_tsv(out, {"A_answers.jsonl": {"path": Path("A_answers.jsonl"), "answers": answers,
                                                    "findings": findings}})
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0].split("\t")[:2] == ["file", "qid"]
    assert lines[1].split("\t")[1] == "Q-9"
