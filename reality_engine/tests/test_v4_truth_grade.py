"""The truth grade beside the contract count: one test per named answer-shape check.

The shape checks read the question text alone, so every fixture here is a graded row
(a dict shaped like ``GATE_RESULTS_v4_strict.jsonl``): the question, the Ask's results
and the contract's ``covered`` flag.

The RIGHT branch now compares the answer with the pilot store, so the truth tests use
a small ``fact`` fixture in ``tmp_path`` — never a live DB.  The acceptance rows named
by the brief are here: a wrong value (MB0106#MI class), a half answer (MB0031#MS
class), a matching value that is RIGHT, and an ILL_POSED row that stays in the
denominator and is never RIGHT.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import uuid
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
    atom: str | None = "price.close",
    formula: str = "",
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
    out = {"part_index": part_index, "atom": atom or None, "operator": operator,
           "answer_type": answer_type, "shape": shape, "unit": unit, "period": period,
           "isin": isin, "dims": dims or {}}
    if formula:
        out["formula"] = formula
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


@pytest.fixture()
def workdir():
    """A writable scratch directory inside the checkout.

    ``tmp_path`` uses the machine temp root, which the worker sandbox cannot scan on
    this host; ``.tmp/`` is inside the writable workspace and works from pytest itself.
    """
    path = REPO / ".tmp" / f"truth_grade_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def fact_store(directory: Path, rows: list[tuple]) -> tg.StoreReader:
    """A nine-column ``fact`` table, the shape the pilot store serves."""
    database = directory / "fact_v4_pilot.db"
    con = sqlite3.connect(database)
    con.execute("CREATE TABLE fact (entity_id TEXT, atom TEXT, dims TEXT, "
                "period_start TEXT, period_end TEXT, value REAL, unit TEXT, "
                "known_at TEXT, source_ref TEXT)")
    con.executemany("INSERT INTO fact VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return tg.StoreReader(directory)


@pytest.fixture()
def store(workdir):
    return fact_store(workdir, [
        (ISIN, "price.close", "", "2026-10-16", "2026-10-16", 134.84, "INR",
         "2026-10-16", "market_state"),
        (ISIN, "price.close", "", "2026-09-30", "2026-09-30", 389.15, "INR",
         "2026-09-30", "market_state"),
        (ISIN, "price.close", "", "2023-09-29", "2023-09-29", 242.80, "INR",
         "2023-09-29", "market_state"),
        (ISIN, "price.close", "", "2023-10-03", "2023-10-03", 250.90, "INR",
         "2023-10-03", "market_state"),
        (ISIN, "hold.pct", "holder_class=promoter", "2026-09-30", "2026-09-30", 31.54,
         "%", "2026-10-19", "ownership"),
        (ISIN, "price.shares_out", "", "2026-10-19", "2026-10-19", 946500000.0,
         "shares", "2026-10-19", "market_state"),
    ])


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


def test_stored_vs_computed_is_one_entity_not_a_two_company_compare():
    graded = row("IDEA pb ratio stored vs computed",
                 [result(atom="f.ratio", value=4.245)])
    shapes = tg.question_shapes(graded["question"])
    assert shapes["measure_vs"] is True
    assert "SHAPE_COMPARE_ONE_SIDE" not in tg.shape_reasons(graded)


def test_stored_vs_computed_with_one_side_is_partial():
    graded = row("IDEA pb ratio stored vs computed",
                 [result(atom="f.ratio", value=4.245)])
    verdict = tg.truth_verdict(graded, store=None, audit={})
    assert verdict["verdict"] == "PARTIAL"
    assert verdict["reason"] == "TRUTH_MEASURE_MISSING"


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


# --- truth verdict: the acceptance checks ---------------------------------
def test_unanswered_row_is_wrong_not_partial():
    graded = row("What is the promoter holding now?", [], covered=False)
    graded["reasons"] = ["no result for part 1 (hold.pct)"]
    verdict = tg.truth_verdict(graded)
    assert verdict["verdict"] == "WRONG" and verdict["reason"] == "TRUTH_NOT_ANSWERED"


def test_matching_value_with_all_parts_is_right(store):
    graded = row("What was EDELWEISS's NSE close on 16 October 2026?",
                 [result(atom="price.close", value=134.84, period="2026-10-16")])
    verdict = tg.truth_verdict(graded, store=store, audit={})
    assert verdict["verdict"] == "RIGHT", verdict
    assert verdict["reason"] == "TRUTH_OK"


def test_mb0106_style_wrong_cagr_is_not_right(store):
    """15.80% starts at the 3 Oct 2023 close; the held 29 Sep close makes it 17.0%."""
    graded = row(
        "What was ASAHISONG's 3-year price CAGR to 30 September 2026, using split- "
        "and dividend-adjusted closes? State both endpoint dates.",
        [result(part_index=0, atom=None, formula="f.cagr", value=15.797359, unit="%",
                period="2026-09-30", dims={"event_kind": "split"}),
         result(part_index=1, atom="price.close", value=389.15, unit="INR",
                period="2026-09-30", dims={"basis": "adjusted"},
                values=[{"period": "2023-09-29", "value": 242.80},
                        {"period": "2026-09-30", "value": 389.15}])])
    graded["mid"] = "MB0106#MI"
    graded["real_answered"] = 2
    verdict = tg.truth_verdict(graded, store=store, audit={})
    assert verdict["verdict"] != "RIGHT", verdict
    assert verdict["reason"] == "TRUTH_VALUE_WRONG"
    assert "242.8" in verdict["detail"] or "17" in verdict["detail"]


def test_mb0031_style_half_answer_is_not_right(store):
    graded = row("What does Edelweiss make, and what was its NSE close on 16 October 2026?",
                 [result(atom="price.close", value=134.84, period="2026-10-16")])
    graded["mid"] = "MB0031#MS"
    verdict = tg.truth_verdict(graded, store=store, audit={})
    assert verdict["verdict"] != "RIGHT", verdict
    assert verdict["verdict"] == "PARTIAL"
    assert verdict["reason"] == "TRUTH_PART_MISSING"


def test_a_text_part_cannot_be_right(store):
    graded = row("IDEA Aug-2026 concall remark",
                 [result(atom="claim.claim", value=None, period="2026-08-18",
                         values=[{"quote": "demand remained strong"}])])
    verdict = tg.truth_verdict(graded, store=store, audit={})
    assert verdict["verdict"] == "PARTIAL"
    assert verdict["reason"] == "TRUTH_VALUE_UNVERIFIED"


def test_a_price_count_the_store_only_rounds_is_not_right(store):
    graded = row("EDELWEISS exact share count now",
                 [result(atom="price.shares_out", value=946500000.0, unit="shares",
                         period="2026-10-19")])
    verdict = tg.truth_verdict(graded, store=store, audit={})
    assert verdict["verdict"] == "PARTIAL"
    assert verdict["reason"] == "TRUTH_VALUE_UNVERIFIED"


def test_ill_posed_row_is_not_right(store):
    graded = row("SBI branch growth and the close on 16 October 2026",
                 [result(atom="price.close", value=134.84, period="2026-10-16")],
                 mid="MB1027#L", kind="stock")
    audit = {"MB1027#L": {"verdict": "false", "reason": "names_other_company",
                          "evidence": [{"value": "the question names SBI; the row is BAJFINANCE"}]}}
    verdict = tg.truth_verdict(graded, store=store, audit=audit)
    assert verdict["verdict"] == "ILL_POSED"
    assert verdict["reason"] == "ILL_POSED_PREMISE_FALSE"


def test_ill_posed_row_stays_in_the_denominator_and_is_never_right():
    panel_rows = [
        {"panel": "fixed", "mid": "MB1027#L", "contract": True, "verdict": "ILL_POSED",
         "reason": "ILL_POSED_PREMISE_FALSE"},
        {"panel": "fixed", "mid": "MB0031#MS", "contract": True, "verdict": "PARTIAL",
         "reason": "TRUTH_PART_MISSING"},
    ]
    summary = tg._panel_summary(panel_rows, {"rows": 2681, "answered": 361})
    block = summary["all"]
    assert block["answered"] == 2          # both rows stay in the denominator
    assert block["ill_posed"] == 1
    assert block["answered_right"] == 0
    assert block["ill_posed_mids"] == ["MB1027#L"]


def test_instance_still_naming_the_parent_company_is_ill_posed(store):
    parent = {"entities": [{"symbol": "OLAELEC", "isin": "INE0LXG01040",
                            "name": "Ola Electric Mobility Limited"}]}
    graded = row("Ola Electric after listing: did the price band widen?",
                 [result(atom="price.band", value=5.0)], mid="MB0903#L", kind="stock")
    verdict = tg.truth_verdict(graded, parent, store=store, audit={})
    assert verdict["verdict"] == "ILL_POSED"
    assert verdict["reason"] == "ILL_POSED_ENTITY_MISMATCH"


def test_a_part_for_another_company_is_wrong(store):
    graded = row("Dalmia Bharat: how many equity shares and what is the promoter holding?",
                 [result(part_index=0, atom="price.shares_out", value=20000, isin=OTHER),
                  result(part_index=1, atom="hold.pct", value=55.84, isin=ISIN,
                         dims={"holder_class": "promoter"})])
    verdict = tg.truth_verdict(graded, store=store, audit={})
    assert verdict["verdict"] == "WRONG"
    assert verdict["reason"] == "TRUTH_PART_OTHER_ENTITY"


def test_a_part_whose_rows_are_on_another_topic_is_wrong(store):
    graded = row("IDEA products",
                 [result(atom="claim.claim", value=None, dims={"topic": "products"},
                         values=[{"quote": "we generate cash", "topic": "production",
                                  "doc_id": 41464}])])
    verdict = tg.truth_verdict(graded, store=store, audit={})
    assert verdict["verdict"] == "WRONG"
    assert verdict["reason"] == "TRUTH_ROW_DIM_MISMATCH"


def test_a_part_whose_rows_match_the_topic_passes():
    graded = row("IDEA products",
                 [result(atom="claim.claim", value=None, dims={"topic": "products"},
                         values=[{"quote": "our products are", "topic": "products",
                                  "doc_id": 1}])])
    assert tg.row_dim_mismatch(graded) is None


def test_a_named_measure_with_no_part_is_wrong(store):
    graded = row("DMart: what is revenue per square foot and inventory turns?",
                 [result(atom="fin.revenue", value=2947.87),
                  result(part_index=1, atom="fin.inventory", value=391.96)])
    verdict = tg.truth_verdict(graded, store=store, audit={})
    assert verdict["verdict"] == "WRONG"
    assert verdict["reason"] == "TRUTH_MEASURE_MISSING"


def test_prose_gold_is_retired():
    graded = row("What was EDELWEISS's NSE close on 16 October 2026?",
                 [result(atom="price.close", value=134.84, period="2026-10-16")])
    parent = {"rubric": {"ground_truth": "a close near the NSE reading"}}
    # no store: the row is PARTIAL for the unverified value, but the prose gold did not
    # add a separate failure (the retired rubric no longer votes).
    verdict = tg.truth_verdict(graded, parent, audit={})
    assert verdict["reason"] == "TRUTH_VALUE_UNVERIFIED"


def test_numeric_gold_must_appear(store):
    graded = row("What was EDELWEISS's NSE close on 16 October 2026?",
                 [result(atom="price.close", value=134.84, period="2026-10-16")],
                 answer="close 999.99")
    parent = {"rubric": {"ground_truth": "134.84"}}
    verdict = tg.truth_verdict(graded, parent, store=store, audit={})
    assert verdict["verdict"] == "PARTIAL"
    assert verdict["reason"] == "TRUTH_GOLD_MISSING"


def test_panel_row_carries_answer_full(store):
    long_answer = "x" * 500
    graded = row("What was EDELWEISS's NSE close on 16 October 2026?",
                 [result(atom="price.close", value=134.84, period="2026-10-16")],
                 answer=long_answer)
    panel = tg._panel_row(graded, {}, "fixed", 1, store=store, audit={})
    assert len(panel["answer"]) == 400
    assert panel["answer_full"] == long_answer
    assert panel["verdict"] == "RIGHT"


def test_read_confusion_on_a_fixture(workdir, store):
    graded_path = workdir / "graded.jsonl"
    read_path = workdir / "read.jsonl"
    matched = row("What was EDELWEISS's NSE close on 16 October 2026?",
                  [result(atom="price.close", value=134.84, period="2026-10-16")],
                  mid="MB0031#MS")
    ill = row("SBI branch growth and the close on 16 October 2026",
              [result(atom="price.close", value=134.84, period="2026-10-16")],
              mid="MB1027#L", kind="stock")
    graded_path.write_text(json.dumps(matched) + "\n" + json.dumps(ill) + "\n",
                           encoding="utf-8")
    read_path.write_text(
        json.dumps({"mid": "MB0031#MS", "verdict": "RIGHT", "reason_code": "RIGHT"}) + "\n"
        + json.dumps({"mid": "MB1027#L", "verdict": "ILL_POSED",
                      "reason_code": "PREMISE_FALSE", "looked_up": "SBI vs BAJFINANCE"}) + "\n",
        encoding="utf-8")
    audit = {"MB1027#L": {"verdict": "false", "reason": "names_other_company",
                          "evidence": [{"value": "SBI vs BAJFINANCE"}]}}
    report = tg.read_confusion(graded_path, read_path, store=store, audit=audit)
    assert report["rows"] == 2
    assert report["table"]["RIGHT|RIGHT"] == 1
    assert report["table"]["ILL_POSED|ILL_POSED"] == 1
    assert report["false_right"] == []
    assert report["new_ill_posed"] == 1


def test_judgement_hold_question_without_a_rule_fails():
    graded = row("As of 24 Sep 2026, did the third retest hold on lower volume?",
                 [result(atom="price.volume", value=3088358.0, period="2026-09-24")])
    assert "SHAPE_JUDGEMENT_NO_RULE" in tg.shape_reasons(graded)


def test_named_sma_window_must_match(store):
    graded = row("Hindustan Unilever's 50-day is flattening into the 200-day. "
                 "What would a death cross actually change for a long-term holder?",
                 [result(atom="price.sma", value=1959.245, period="2026-09-24")])
    verdict = tg.truth_verdict(graded, store=store, audit={})
    assert verdict["verdict"] == "WRONG"
    assert verdict["reason"] in ("SHAPE_JUDGEMENT_NO_RULE", "TRUTH_MEASURE_MISSING")


def test_parent_acronym_in_instance_question_is_ill_posed(store):
    parent = {"entities": [{"symbol": "SBIN", "isin": "INE062A01020",
                            "name": "State Bank of India"}]}
    graded = row("SBI fell to a level that held in March. Is that level still valid?",
                 [result(atom="price.close", value=134.84, period="2026-10-16")],
                 mid="MB1027#L", kind="stock")
    graded["entity"] = "INE296A01032"
    verdict = tg.truth_verdict(graded, parent, store=store, audit={})
    assert verdict["verdict"] == "ILL_POSED"
    assert verdict["reason"] == "ILL_POSED_ENTITY_MISMATCH"


def test_panel_row_reports_a_premise_failure_not_the_judgement_shape(store):
    graded = row("SBI fell to a level that held in March. Is that level still valid?",
                 [result(atom="price.close", value=134.84, period="2026-10-16")],
                 mid="MB1027#L", kind="stock")
    audit = {"MB1027#L": {"verdict": "false", "reason": "names_other_company",
                          "evidence": [{"value": "the question names SBI"}]}}
    panel = tg._panel_row(graded, {}, "fixed", 1, store=store, audit=audit)
    assert panel["verdict"] == "ILL_POSED"
    assert panel["premise"]
    assert "SHAPE_JUDGEMENT_NO_RULE" not in panel["shape_failures"]


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
