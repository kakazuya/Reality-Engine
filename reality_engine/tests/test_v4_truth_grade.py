"""The truth grade beside the contract count: one test per named answer-shape check.

The shape checks read the question text alone, so every fixture here is a graded row
(a dict shaped like ``GATE_RESULTS_v4_strict.jsonl``): the question, the Ask's results
and the contract's ``covered`` flag.  No database, no run.

A "good" variant accompanies every failure so the check is shown to fire on the named
defect and not on a correct answer of the same family.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tasks" / "answer_bench"))

import truth_grade as tg  # noqa: E402

ISIN = "INE000000001"
OTHER = "INE000000002"
AS_OF = "2026-10-19"


def result(  # noqa: PLR0913 - a fixture builder, one field per contract column
    *,
    part_index: int = 0,
    atom: str = "price.close",
    operator: str = "value_at",
    value=None,
    unit: str = "INR",
    period: str = "2026-09-30",
    isin: str = ISIN,
    dims: dict | None = None,
    answer_type: str = "measured",
    rule_used: str = "",
    numbers: dict | None = None,
    values: list | None = None,
    entities: list | None = None,
    shape: str = "scalar",
) -> dict:
    out = {"part_index": part_index, "atom": atom, "operator": operator,
           "answer_type": answer_type, "shape": shape, "unit": unit, "period": period,
           "isin": isin, "dims": dims or {}}
    if value is not None:
        out["value"] = value
    if rule_used:
        out["rule_used"] = rule_used
    if numbers:
        out["numbers"] = numbers
    if values:
        out["values"] = values
    if entities:
        out["entities"] = entities
    return out


def row(question: str, results: list[dict], covered: bool = True,
        mid: str = "MB0001", kind: str = "original", **extra) -> dict:
    out = {"mid": mid, "question": question, "as_of": AS_OF, "covered": covered,
           "real_answered": sum(1 for r in results
                                if r["answer_type"] in ("measured", "estimate")),
           "entity": ISIN, "answer": "", "kind": kind,
           "results": results, "reasons": [] if covered else ["a part is NOT IN DATA"]}
    out.update(extra)
    return out


# --- 1. a set/ranking ask answered from one entity -------------------------
def test_set_ask_answered_from_one_entity_fails():
    graded = row("Which stocks had the highest turnover on 4 June 2024?",
                 [result(atom="price.traded_value", value=163723.58)])
    assert "SHAPE_SET_ONE_ENTITY" in tg.shape_reasons(graded)


def test_set_ask_with_a_ranked_set_passes():
    graded = row("Rank the companies by public shareholding as of Sep 2026.",
                 [result(atom="hold.pct", operator="rank", answer_type="measured",
                         entities=[{"entity_id": ISIN, "value": 40.0},
                                   {"entity_id": OTHER, "value": 32.0}])])
    assert tg.shape_reasons(graded) == []


def test_set_ask_with_a_count_passes():
    graded = row("How many companies filed a director resignation in Sep 2026?",
                 [result(atom="event.count", operator="count", value=12)])
    assert tg.shape_reasons(graded) == []


# --- 2. a comparison missing a side ---------------------------------------
def test_compare_missing_a_side_fails():
    graded = row("Sun Pharma versus Cipla: which one is more exposed?",
                 [result(atom="fin.revenue", operator="growth", value=5883.6, isin=ISIN)])
    assert "SHAPE_COMPARE_ONE_SIDE" in tg.shape_reasons(graded)


def test_compare_with_both_sides_passes():
    graded = row("Sun Pharma versus Cipla: which one is more exposed?",
                 [result(part_index=0, atom="fin.revenue", value=100.0, isin=ISIN),
                  result(part_index=1, atom="fin.revenue", value=90.0, isin=OTHER)])
    assert "SHAPE_COMPARE_ONE_SIDE" not in tg.shape_reasons(graded)


def test_vs_stored_is_not_a_two_company_comparison():
    graded = row("P/B now vs stored", [result(atom="f.ratio", value=4.245)])
    assert "SHAPE_COMPARE_ONE_SIDE" not in tg.shape_reasons(graded)


# --- 3. a judgement ask with no rule output -------------------------------
def test_judgement_without_a_rule_fails():
    graded = row("RVNL had three delivery spikes in a month. Is that distribution or absorption?",
                 [result(atom="price.delivery_pct", operator="change", value=7.67)])
    assert "SHAPE_JUDGEMENT_NO_RULE" in tg.shape_reasons(graded)


def test_judgement_with_a_rule_passes():
    graded = row("RVNL had three delivery spikes in a month. Is that distribution or absorption?",
                 [result(atom="price.delivery_pct", operator="rule", value="absorption",
                         rule_used="delivery rises while price holds")])
    assert "SHAPE_JUDGEMENT_NO_RULE" not in tg.shape_reasons(graded)


# --- 4. a period-named change over the whole window ------------------------
def test_change_over_the_whole_window_when_the_ask_names_a_quarter_fails():
    graded = row("What was APLAPOLLO's delivery change in Q1FY27?",
                 [result(atom="price.delivery_pct", operator="change", value=14.28,
                         numbers={"from": "2025-04-01", "to": "2026-09-30"})])
    assert "SHAPE_CHANGE_OVER_WINDOW" in tg.shape_reasons(graded)


def test_change_inside_the_named_window_passes():
    graded = row("What was APLAPOLLO's delivery change in Q1FY27?",
                 [result(atom="price.delivery_pct", operator="change", value=14.28,
                         period="2026-06-30",
                         numbers={"from": "2026-04-01", "to": "2026-06-30"})])
    assert "SHAPE_CHANGE_OVER_WINDOW" not in tg.shape_reasons(graded)


# --- 5. two parts, one value under different labels -----------------------
def test_two_parts_one_value_under_different_labels_fails():
    graded = row("Bosch fell 9.65% on 28 Jul: what is the close, and what is the event close?",
                 [result(part_index=0, atom="price.close", value=41310.0),
                  result(part_index=1, atom="price.close", value=41310.0,
                         dims={"period_kind": "event"})])
    assert "SHAPE_DUPLICATE_VALUE" in tg.shape_reasons(graded)


def test_two_parts_with_two_values_pass():
    graded = row("Bosch fell 9.65% on 28 Jul: what is the close, and what is the event close?",
                 [result(part_index=0, atom="price.close", value=41310.0),
                  result(part_index=1, atom="price.close_prev", value=42259.0)])
    assert "SHAPE_DUPLICATE_VALUE" not in tg.shape_reasons(graded)


# --- 6. a list_distinct dump past its limit -------------------------------
def test_list_dump_over_a_stated_limit_fails():
    values = [{"entity_id": ISIN, "value": float(i)} for i in range(6)]
    graded = row("List the top 5 products by revenue.",
                 [result(atom="fin.products", operator="list_distinct", values=values)])
    assert "SHAPE_LIST_DUMP" in tg.shape_reasons(graded)


def test_list_dump_within_the_limit_passes():
    values = [{"entity_id": ISIN, "value": float(i)} for i in range(3)]
    graded = row("List the top 5 products by revenue.",
                 [result(atom="fin.products", operator="list_distinct", values=values)])
    assert "SHAPE_LIST_DUMP" not in tg.shape_reasons(graded)


def test_absurd_list_dump_without_a_stated_limit_fails():
    values = [{"entity_id": ISIN, "value": float(i)} for i in range(tg.ABSURD_DUMP + 1)]
    graded = row("US HRC 1,275: which price matters for an Indian tube maker?",
                 [result(atom="price.close", operator="list_distinct", values=values)])
    assert "SHAPE_LIST_DUMP" in tg.shape_reasons(graded)


# --- 7. a forecast answered with a spot price -----------------------------
def test_forecast_answered_with_a_spot_price_fails():
    graded = row("What will Reliance's share price be on Diwali 2027?",
                 [result(atom="price.close", value=1420.0, period="2026-10-19")])
    assert "SHAPE_FORECAST_SPOT" in tg.shape_reasons(graded)


def test_forecast_with_a_typed_estimate_passes():
    graded = row("What will Reliance's share price be on Diwali 2027?",
                 [result(atom="own.estimate", answer_type="estimate", value=1500.0,
                         period="2027-11-01")])
    assert "SHAPE_FORECAST_SPOT" not in tg.shape_reasons(graded)


# --- 8. the returned period is not the one asked --------------------------
def test_returned_period_that_is_not_the_asked_period_fails():
    graded = row("What is the promoter holding as of Sep 2026?",
                 [result(atom="hold.pct", value=32.84, period="2026-06-30")])
    assert "SHAPE_PERIOD_MISMATCH" in tg.shape_reasons(graded)


def test_correct_period_passes():
    graded = row("What is the promoter holding as of Sep 2026?",
                 [result(atom="hold.pct", value=32.84, period="2026-09-30")])
    assert tg.shape_reasons(graded) == []


def test_two_named_quarters_with_one_annual_reading_fail():
    graded = row("What did the data show about the OMC profit swing from Q4FY26 to Q1FY27?",
                 [result(atom="fin.pat", value=18046.89, period="2026-03-31")])
    assert "SHAPE_PERIOD_MISMATCH" in tg.shape_reasons(graded)


def test_range_extreme_taken_over_one_row_fails():
    graded = row("What was SUNPHARMA's YTD high price in 1 January-30 September 2026, "
                 "with the value and the date?",
                 [result(atom="price.high", operator="max_with_date", value=1863.6,
                         period="2026-09-30", numbers={"n": 1})])
    assert "SHAPE_PERIOD_MISMATCH" in tg.shape_reasons(graded)


def test_date_range_with_a_year_on_the_closing_date_only_is_parsed():
    periods = tg.asked_periods("the high in 1 January-30 September 2026")
    starts = {period["start"] for period in periods}
    # the leading date takes the closing date's year ("1 January" -> 2026-01-01);
    # the closing month is also a month period of its own, which is harmless.
    assert {"2026-01-01", "2026-09-30"} <= starts


# --- a clean row is never failed by any of the eight ----------------------
def test_a_plain_measured_answer_passes_every_shape_check():
    graded = row("What was NSE: OMMETALS (now OMINFRAL)'s YTD high price in 2026, "
                 "with the value and the date?",
                 [result(atom="price.high", operator="max_with_date", value=146.0,
                         period="2026-09-23")])
    assert tg.shape_reasons(graded) == []


def test_all_eight_named_reasons_are_reachable():
    """The committed reason list is exactly the eight the brief names."""
    assert tg.SHAPE_REASONS if hasattr(tg, "SHAPE_REASONS") else True
    produced = set()
    for graded in (
        row("Which stocks had the highest turnover on 4 June 2024?",
            [result(atom="price.traded_value", value=1.0)]),
        row("Sun Pharma versus Cipla: which one is more exposed?",
            [result(atom="fin.revenue", value=1.0)]),
        row("Is that distribution or absorption?",
            [result(atom="price.delivery_pct", value=1.0)]),
        row("What was the change in Q1FY27?",
            [result(atom="price.close", operator="change", value=1.0,
                    numbers={"from": "2025-01-01", "to": "2026-09-30"})]),
        row("What is the close, and what is the event close?",
            [result(part_index=0, atom="price.close", value=1.0),
             result(part_index=1, atom="price.close", value=1.0, dims={"period_kind": "event"})]),
        row("List the top 2 products.",
            [result(atom="fin.products", operator="list_distinct",
                    values=[{"value": 1.0}, {"value": 2.0}, {"value": 3.0}])]),
        row("What will the share price be on Diwali 2027?",
            [result(atom="price.close", value=1.0)]),
        row("What is the promoter holding as of Sep 2026?",
            [result(atom="hold.pct", value=1.0, period="2026-06-30")]),
    ):
        produced |= set(tg.shape_reasons(graded))
    assert produced == {
        "SHAPE_SET_ONE_ENTITY", "SHAPE_COMPARE_ONE_SIDE", "SHAPE_JUDGEMENT_NO_RULE",
        "SHAPE_CHANGE_OVER_WINDOW", "SHAPE_DUPLICATE_VALUE", "SHAPE_LIST_DUMP",
        "SHAPE_FORECAST_SPOT", "SHAPE_PERIOD_MISMATCH",
    }


# --- truth verdict --------------------------------------------------------
def test_unanswered_row_is_wrong_not_partial():
    graded = row("What is the promoter holding now?", [], covered=False)
    graded["reasons"] = ["no result for part 1 (hold.pct)"]
    verdict = tg.truth_verdict(graded)
    assert verdict["verdict"] == "WRONG" and verdict["reason"] == "TRUTH_NOT_ANSWERED"


def test_clean_covered_row_is_right():
    graded = row("What was OMMETALS's YTD high price in 2026, with the value and the date?",
                 [result(atom="price.high", operator="max_with_date", value=146.0,
                         period="2026-09-23")])
    assert tg.truth_verdict(graded)["verdict"] == "RIGHT"


def test_instance_still_naming_the_parent_company_is_wrong():
    parent = {"entities": [{"symbol": "OLAELEC", "isin": "INE0LXG01040",
                            "name": "Ola Electric Mobility Limited"}]}
    graded = row("Ola Electric after listing: did the price band widen?",
                 [result(atom="price.band", value=5.0)], mid="MB0903#L", kind="stock")
    verdict = tg.truth_verdict(graded, parent)
    assert verdict["verdict"] == "WRONG"
    assert verdict["reason"] == "TRUTH_ENTITY_TEXT_MISMATCH"


def test_a_part_for_another_company_is_wrong():
    graded = row("Dalmia Bharat: how many equity shares and what is the promoter holding?",
                 [result(part_index=0, atom="price.shares_out", value=20000, isin=OTHER),
                  result(part_index=1, atom="hold.pct", value=55.84, isin=ISIN)])
    verdict = tg.truth_verdict(graded)
    assert verdict["verdict"] == "WRONG"
    assert verdict["reason"] == "TRUTH_PART_OTHER_ENTITY"


def test_a_part_whose_rows_are_on_another_topic_is_wrong():
    graded = row("IDEA products",
                 [result(atom="claim.claim", value=None, dims={"topic": "products"},
                         values=[{"quote": "we generate cash", "topic": "production",
                                  "doc_id": 41464}])])
    verdict = tg.truth_verdict(graded)
    assert verdict["verdict"] == "WRONG"
    assert verdict["reason"] == "TRUTH_ROW_DIM_MISMATCH"


def test_a_part_whose_rows_match_the_topic_passes():
    graded = row("IDEA products",
                 [result(atom="claim.claim", value=None, dims={"topic": "products"},
                         values=[{"quote": "our products are", "topic": "products",
                                  "doc_id": 1}])])
    assert tg.row_dim_mismatch(graded) is None


def test_a_named_measure_with_no_part_is_partial():
    graded = row("DMart: what is revenue per square foot and inventory turns?",
                 [result(atom="fin.revenue", value=2947.87),
                  result(part_index=1, atom="fin.inventory", value=391.96)])
    verdict = tg.truth_verdict(graded)
    assert verdict["verdict"] == "PARTIAL"
    assert verdict["reason"] == "TRUTH_MEASURE_MISSING"


# --- periods, panel, interval --------------------------------------------
def test_asked_periods_map_to_indian_fiscal_windows():
    periods = tg.asked_periods("Q1FY27 revenue and FY26 profit and Sep 2026 holding")
    by_label = {period["label"]: period for period in periods}
    assert by_label["Q1FY27"]["end"] == "2026-06-30"
    assert by_label["FY26"]["end"] == "2026-03-31"
    assert by_label["Sep 2026"]["start"] == "2026-09-01"


def test_wilson_interval_brackets_the_rate():
    low, high = tg.wilson(3, 40)
    assert 0.0 <= low < 3 / 40 < high <= 1.0
    assert tg.wilson(0, 0) == (0.0, 0.0)


def test_panel_selection_is_reproducible_by_seed():
    pools = {("answered", "LARGE", "F1", "plain"):
             [{"mid": f"A{i}", "_group": "answered"} for i in range(60)],
             ("unanswered", "LARGE", "F1", "plain"):
             [{"mid": f"U{i}", "_group": "unanswered"} for i in range(60)]}
    first = [pick["mid"] for pick in tg._pick(pools, 20261031, 20)]
    again = [pick["mid"] for pick in tg._pick(pools, 20261031, 20)]
    other = [pick["mid"] for pick in tg._pick(pools, 20261032, 20)]
    assert first == again
    assert first != other


def test_rubric_without_steps_and_gold_cannot_judge():
    scored = tg.rubric_score(row("P/B now vs stored", [result(value=4.2)]),
                             {"required_steps": None, "ground_truth": None})
    assert scored["verdict"] is None


def test_rubric_scores_missing_steps_as_not_right():
    scored = tg.rubric_score(
        row("How are the liabilities accounted for, and do the assumptions flatter the loss?",
            [result(atom="fin.interest", value=21495.0)]),
        {"required_steps": "show the interest and amortisation lines -> compare with the "
                           "cash paid -> quote the auditor's going-concern paragraph",
         "forbidden": "comparing accounting interest with cash interest as if equal",
         "ground_truth": None})
    assert scored["verdict"] in ("PARTIAL", "WRONG")


def test_the_40_hand_verdicts_stay_parseable():
    """The corrected sample-40 doc still yields 40 verdicts, 3 of them RIGHT."""
    hand = tg._hand_verdicts()
    assert len(hand) == 40
    assert sorted(mid for mid, verdict in hand.items() if verdict == "RIGHT") == [
        "MB0005#MI", "MB0280#L", "MB0303#MS"]


GRADED = REPO / "tasks" / "answer_bench" / "GATE_RESULTS_v4_strict.jsonl"


@pytest.mark.skipif(not GRADED.exists(),
                    reason="the raw v4 gate output is gitignored; regenerate it first")
def test_no_hand_right_row_is_failed_by_a_shape_check():
    """Acceptance check: zero RIGHT rows wrongly failed (the raw run must be present)."""
    import json

    hand = tg._hand_verdicts()
    right = {mid for mid, verdict in hand.items() if verdict == "RIGHT"}
    rows = {}
    with GRADED.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if str(row.get("mid")) in right:
                rows[str(row["mid"])] = row
    assert right <= set(rows), f"graded run missing {right - set(rows)}"
    failed = {mid: tg.shape_reasons(rows[mid]) for mid in right if tg.shape_reasons(rows[mid])}
    assert failed == {}


def test_judge_refuses_without_a_key(monkeypatch):
    sys.path.insert(0, str(REPO / "tasks" / "answer_bench"))
    import truth_judge

    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_GO_API_KEY_2", raising=False)
    assert truth_judge.available() is False
    with pytest.raises(RuntimeError):
        truth_judge.judge({"mid": "T1", "question": "q", "answer": "a"})


def test_judge_reads_the_parent_rubric():
    import truth_judge

    bank = {"MB0001": {"rubric": {"required_steps": "a -> b", "ground_truth": "quoted"}}}
    text = truth_judge._rubric("MB0001", bank)
    assert "required_steps: a -> b" in text and "ground_truth: quoted" in text
    assert "no rubric" in truth_judge._rubric("MB9999", bank)


@pytest.mark.parametrize("question,bad_shape", [
    ("Which companies filed a director resignation in September 2026?", "set"),
    ("Sun Pharma versus Cipla: how much of revenue is US?", "compare"),
    ("Is that level still valid after the June bounce?", "judgement"),
    ("What will the share price be on Diwali 2027?", "forecast"),
])
def test_question_shapes_read_the_text_alone(question, bad_shape):
    shapes = tg.question_shapes(question)
    assert shapes[bad_shape], shapes
