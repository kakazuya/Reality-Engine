"""T-205 round 10: the answer step with the model mocked (no network, no store)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reality_engine.answer import answer_step as step  # noqa: E402

PACK = {
    "parts": [{"id": "p1", "text": "revenue in Q2FY27 and its growth over Q2FY26"}],
    "items": [
        {"id": "fin-1", "route": "fin", "doc_key": "results/q2.pdf", "page": 5,
         "text": "Revenue from operations 1,100.00 crore in Q2FY27"},
        {"id": "fin-2", "route": "fin", "doc_key": "results/q2.pdf", "page": 5,
         "text": "Revenue from operations 1,000.00 crore in Q2FY26"},
    ],
    "coverage": [{"part": "p1", "text": "revenue and growth", "status": "found",
                  "lookups": [{"route": "fin", "args": {"measure": "revenue", "period": "Q2FY27"},
                               "found": True, "items": ["fin-1", "fin-2"]}]}],
}
READING = ("QUESTION: revenue?\n\nPARTS:\n  p1: revenue and growth\n\nCOVERAGE:\n"
           "  p1 [found]\n    fin {...} -> found, 2 items\n\nITEMS\n"
           "[1] fin doc=results/q2.pdf p5\nRevenue from operations 1,100.00 crore in Q2FY27\n"
           "[2] fin doc=results/q2.pdf p5\nRevenue from operations 1,000.00 crore in Q2FY26")


def _answer(figures=None, final="{{growth}}", calcs=None, status="answered"):
    return {
        "parts": [{"part": "p1", "status": status,
                   "text": "Revenue was 1,100.00 crore in Q2FY27.",
                   "figures": figures if figures is not None else [
                       {"value": 1100.0, "unit": "crore", "period": "Q2FY27", "item_id": "fin-1",
                        "quote": "Revenue from operations 1,100.00 crore in Q2FY27"},
                       {"value": 1000.0, "unit": "crore", "period": "Q2FY26", "item_id": "fin-2",
                        "quote": "Revenue from operations 1,000.00 crore in Q2FY26"},
                   ]}],
        "calcs": calcs if calcs is not None else [
            {"name": "growth", "expression": "(a - b) / b * 100", "inputs": {"a": 0, "b": 1}}],
        "final_answer": "Revenue was 1,100.00 crore and grew " + final + ".",
    }


def _client(replies):
    queue = list(replies)

    def call(system, user, key):  # noqa: ARG001
        return {"content": queue.pop(0) if queue else ""}

    return call


def test_calc_is_computed_by_script_not_the_model():
    answer = step.write_answer("revenue?", "2026-11-11", READING, PACK["coverage"], "beam-free",
                               pack=PACK, client=_client([json.dumps(_answer())]))
    assert answer["calculations"][0]["result"] == pytest.approx(10.0)
    assert answer["final_answer"] == "Revenue was 1,100.00 crore and grew 10.00%."
    assert not answer["unverified"]
    # the model wrote no result anywhere: a "result" key it invents is ignored
    wrong = _answer()
    wrong["calcs"] = [{"name": "growth", "expression": "(a - b) / b * 100", "inputs": {"a": 0, "b": 1},
                       "result": 999}]
    second = step.write_answer("revenue?", "2026-11-11", READING, PACK["coverage"], "beam-free",
                               pack=PACK, client=_client([json.dumps(wrong)]))
    assert second["calculations"][0]["result"] == pytest.approx(10.0)


def test_figure_not_in_its_item_fails_and_repairs():
    bad = _answer([{"value": 123.92, "unit": "crore", "period": "Q2FY27", "item_id": "fin-1",
                    "quote": "Revenue from operations 1,100.00 crore in Q2FY27"}])
    calls = []

    def client(system, user, key):  # noqa: ARG001
        calls.append(user)
        return {"content": json.dumps(bad if len(calls) == 1 else _answer())}

    answer = step.write_answer("revenue?", "2026-11-11", READING, PACK["coverage"], "beam-free",
                               pack=PACK, client=client)
    assert len(calls) == 2                      # the first answer plus one repair
    assert answer["repair_used"] is True
    assert answer["unverified"] == []
    assert len(answer["_figures_flat"]) == 2


def test_unrepaired_figure_is_removed_and_listed_unverified():
    bad = _answer([{"value": 123.92, "unit": "crore", "period": "Q2FY27", "item_id": "fin-1",
                    "quote": "Revenue from operations 1,100.00 crore in Q2FY27"}])
    answer = step.write_answer("revenue?", "2026-11-11", READING, PACK["coverage"], "beam-free",
                               pack=PACK, client=_client([json.dumps(bad), json.dumps(bad)]))
    assert answer["unverified"]
    assert answer["unverified"][0]["kind"] == "figure"
    assert all(f.get("value") != 123.92 for f in answer["_figures_flat"])


def test_not_found_with_coverage_found_is_flagged():
    reply = {"parts": [{"part": "p1", "status": "not_found", "text": "data not found", "figures": []}],
             "calcs": [], "final_answer": "data not found"}
    answer = step.write_answer("revenue?", "2026-11-11", READING, PACK["coverage"], "beam-free",
                               pack=PACK, client=_client([json.dumps(reply)]))
    part = answer["parts"][0]
    assert part["status"] == "not_found"
    assert part["abstained_with_evidence"] is True
    assert "searched" in part["text"]


def test_expression_evaluator_rejects_anything_but_arithmetic():
    for expression in ("__import__('os')", "open('x')", "a.b", "a[0]", "lambda: 1", "abs(-1)"):
        with pytest.raises(ValueError):
            step.evaluate_expression(expression, {"a": 1})
    assert step.evaluate_expression("(a - b) / b * 100", {"a": 1100.0, "b": 1000.0}) == pytest.approx(10.0)


def test_plain_number_in_final_answer_must_be_a_figure():
    reply = _answer()
    reply["final_answer"] = reply["final_answer"] + " The margin was 12.34%."
    answer = step.write_answer("revenue?", "2026-11-11", READING, PACK["coverage"], "beam-free",
                               pack=PACK, client=_client([json.dumps(reply), json.dumps(reply)]))
    assert any(f.get("kind") == "number" for f in answer["check_failures"])
    assert "12.34" not in answer["final_answer"]
    assert "[unverified]" in answer["final_answer"]


def test_invalid_json_twice_is_a_named_unparseable():
    answer = step.write_answer("revenue?", "2026-11-11", READING, PACK["coverage"], "beam-free",
                               pack=PACK, client=_client(["not json", "still not json"]))
    assert answer["status"] == "unparseable"
    assert answer["model_calls"] == 2


def test_calc_written_inside_a_part_indexes_that_parts_figures():
    pack = {"plan": {"question": "revenue and ratio"},
            "parts": [{"id": "p1", "text": "revenue"}, {"id": "p2", "text": "ratio"}],
            "coverage": [{"part": "p1", "status": "found"},
                         {"part": "p2", "status": "found"}],
            "items": [{"id": "fin-1", "route": "fin", "text": "Revenue 1,100.00 crore in Q2FY27"},
                      {"id": "fin-2", "route": "fin", "text": "Cost 1,000.00 crore in Q2FY27"},
                      {"id": "fin-3", "route": "fin", "text": "Cost 500.00 crore in Q2FY26"}]}
    reply = {"parts": [
        {"part": "p1", "status": "answered", "text": "Revenue 1,100.00 crore.", "calcs": [],
         "figures": [{"value": 1100.0, "item_id": "fin-1", "quote": "Revenue 1,100.00 crore in Q2FY27"}]},
        {"part": "p2", "status": "answered", "text": "The ratio is {{ratio}}%.", "figures": [
            {"value": 1000.0, "item_id": "fin-2", "quote": "Cost 1,000.00 crore in Q2FY27"},
            {"value": 500.0, "item_id": "fin-3", "quote": "Cost 500.00 crore in Q2FY26"}],
         "calcs": [{"name": "ratio", "expression": "a / b * 100", "inputs": {"a": 0, "b": 1}}]}],
        "final_answer": "Ratio {{ratio}}%."}
    answer = step.write_answer("revenue?", "2026-11-11", "READING", pack["coverage"], "beam-free",
                               pack=pack, client=_client([json.dumps(reply)]))
    assert answer["calculations"][0]["result"] == pytest.approx(200.0)
    assert answer["final_answer"] == "Ratio 200.00%."
    assert "%%" not in answer["final_answer"]


def test_calc_input_must_be_a_figure_that_passed_the_check():
    pack = {"plan": {"question": "revenue"},
            "parts": [{"id": "p1", "text": "revenue"}],
            "coverage": [{"part": "p1", "status": "found"}],
            "items": [{"id": "fin-1", "route": "fin", "text": "Revenue 1,100.00 crore in Q2FY27"}]}
    reply = {"parts": [{"part": "p1", "status": "answered", "text": "Growth {{growth}}%.", "figures": [
        {"value": 99.9, "item_id": "fin-1", "quote": "Revenue 1,100.00 crore in Q2FY27"}],
        "calcs": [{"name": "growth", "expression": "a * 2", "inputs": {"a": 0}}]}],
        "final_answer": "Growth {{growth}}%."}
    answer = step.write_answer("revenue?", "2026-11-11", "READING", pack["coverage"], "beam-free",
                               pack=pack, client=_client([json.dumps(reply), json.dumps(reply)]))
    assert any(f.get("kind") == "calc" and "did not pass the check" in f["reason"]
               for f in answer["check_failures"])
    assert "{{growth}}" not in answer["final_answer"]


# --- round 12: unresolved calc message + script number formatting ------------------------------------
def test_unresolved_calc_names_the_input_and_the_existing_figures():
    bad = _answer(calcs=[{"name": "growth", "expression": "a / b * 100", "inputs": {"a": 0, "b": 4}}])
    answer = step.write_answer("revenue?", "2026-11-11", READING, PACK["coverage"], "beam-free",
                               pack=PACK, client=_client([json.dumps(bad), json.dumps(bad)]))
    failure = next(f for f in answer["check_failures"] if f.get("kind") == "calc")
    assert failure["input"] == "b" and failure["index"] == "4"
    assert "figures that exist: 0=" in failure["reason"] and "fin-1" in failure["reason"]
    assert "not computed (input missing: growth)" in answer["final_answer"]
    assert "[unverified]" not in answer["final_answer"]
    assert answer["parts"][0]["calc_unresolved"] is True


def test_figure_tokens_are_formatted_by_script_in_three_real_sentences():
    shares = "36.5% (75049043.0 shares) is 0.01 % percentage points above, with 24,200 shares more."
    price = ("closed at 1627.9 versus the prior close of 1673.0, a -2.70% reaction. "
             "Traded volume was 1496289.0, a 139.02 % change.")
    rupees = "cash flow from operations was Rs 1538100000 in FY26."
    formatted = step._format_figures(shares, [
        {"value": 36.5, "unit": "%"}, {"value": 75049043.0, "unit": "shares"},
        {"value": 0.01, "unit": "%"}, {"value": 24200.0, "unit": "shares"}])
    assert formatted == ("36.50% (75,049,043 shares) is 0.01 percentage points above, "
                         "with 24,200 shares more.")
    assert step._format_figures(price, [
        {"value": 1627.9, "unit": "inr"}, {"value": 1673.0, "unit": "inr"},
        {"value": -2.7, "unit": "%"}, {"value": 1496289.0, "unit": "shares"},
        {"value": 139.02, "unit": "%"}]) == (
        "closed at 1,627.9 versus the prior close of 1,673, a -2.70% reaction. "
        "Traded volume was 1,496,289, a 139.02% change.")
    assert step._format_figures(rupees, [{"value": 1538100000.0, "unit": "inr"}]) == (
        "cash flow from operations was Rs 153.81 crore in FY26.")
    assert step._fmt_result(16.531, "%") == "16.53%" and step._fmt_result(1673.0, "") == "1,673"


def test_answer_is_cached_by_reading_copy_and_model():
    import uuid
    calls = []

    def client(system, user, key):  # noqa: ARG001
        calls.append(1)
        return {"content": json.dumps(_answer())}

    cache = REPO_ROOT / ".tmp" / f"answer_cache_test_{uuid.uuid4().hex[:8]}"
    cache.mkdir(parents=True, exist_ok=True)
    first = step.write_answer("revenue?", "2026-11-11", READING, PACK["coverage"], "beam-free",
                              pack=PACK, client=client, cache_dir=cache)
    second = step.write_answer("revenue?", "2026-11-11", READING, PACK["coverage"], "beam-free",
                               pack=PACK, client=client, cache_dir=cache)
    assert len(calls) == 1
    assert second["cached"] is True and second["model_calls"] == 0
    assert first["final_answer"] == second["final_answer"]


# --- round 11: the id contract, non-figures, quote fallback, replies, gate ----------------------------
def test_item_id_is_tolerant_of_brackets_case_and_spaces():
    parts = step._parts_of(PACK, PACK["coverage"])
    for cited in ("fin-1", "[fin-1]", " FIN-1 ", "[ fin-1 ]"):
        reply = _answer()
        reply["parts"][0]["figures"][0]["item_id"] = cited
        _answer_obj, _figures, _calcs, failures = step._evaluate_reply(reply, parts, PACK)
        assert not [f for f in failures if f.get("kind") == "figure"], cited


def test_positional_id_is_removed_after_the_repair():
    bad = _answer()
    for figure in bad["parts"][0]["figures"]:
        figure["item_id"] = "12"
    answer = step.write_answer("revenue?", "2026-11-11", READING, PACK["coverage"], "beam-free",
                               pack=PACK, client=_client([json.dumps(bad), json.dumps(bad)]))
    assert answer["unverified"][0]["code"] == "item"
    assert answer["_figures_flat"] == []
    assert answer["figures_removed"] == 2


REAL_SENTENCES = [
    ("Blue Star's consolidated revenue from operations was ₹2,930.95 crore in Q2FY27 (quarter ended "
     "30 September 2026) and ₹2,422.37 crore in Q2FY26.", {2930.95, 2422.37}),
    ("Blue Star reported a net cash position of ₹289.43 crore as at 30 September 2026 and a net cash balance "
     "of ₹175.45 crore as at 31 March 2026.", {289.43, 175.45}),
    ("On the Q2FY27 call (30 October 2026), the Group CFO guided to a full-year capex of around Rs. 41 cr in FY26.",
     {41.0}),
    ("Capital employed was ₹3,258.41 crore as at 31 March 2026 and ₹2,427.28 crore as at 31 March 2025.",
     {3258.41, 2427.28}),
    ("Blue Star's consolidated debtor days were 60.32 at 31 Mar 2026 and 59.65 at 31 Mar 2025, while consolidated "
     "inventory days were 82.53 and 71.52 respectively.", {60.32, 59.65, 82.53, 71.52}),
]


def test_non_figure_numbers_are_not_checked_on_five_real_sentences():
    for sentence, expected in REAL_SENTENCES:
        assert step._nums(sentence) == expected, sentence
    assert step._nums("See p. 9 and the 1st table; the 12 stores opened in FY2025-26.") == {12.0}
    assert step._nums("See Table 2, Segment 1 and Tier-3; revenue 2,930.95 crore.") == {2930.95}
    assert step._nums("revenue 1,935.99 crore in 1935") == {1935.99}   # a decimal in the year range is a figure
    assert step._nums("target of 2,000 crore") == set()                # a bare 2000 is still a year-like token
    assert step._nums("a 1:1 bonus issue") == set()                    # a ratio label, not a figure
    assert step._value_in(2000, "target of Rs 2,000 crore", "crore")   # but the value is findable in an item
    assert step._nums("the 12 stores.", "How many of the 12 stores opened?") == set()
    text, removed = step._scrub("in Q2FY27 (30 September 2026) at p. 9, 1st week", set())
    assert text == "in Q2FY27 (30 September 2026) at p. 9, 1st week" and removed == []


def test_quote_whitespace_is_normalised_and_value_only_is_kept():
    parts = step._parts_of(PACK, PACK["coverage"])
    reply = _answer()
    reply["parts"][0]["figures"][0]["quote"] = "Revenue from operations\n   1,100.00 crore in Q2FY27"
    _answer_obj, _figures, _calcs, failures = step._evaluate_reply(reply, parts, PACK)
    assert not failures
    reply = _answer()
    reply["parts"][0]["figures"][0]["quote"] = "Revenue in Q2FY27 was 1,100 crore"
    answer, figures, _calcs, failures = step._evaluate_reply(reply, parts, PACK)
    assert not [f for f in failures if f.get("kind") == "figure"]
    assert figures[0].get("verified_value_only") is True


def test_quote_and_value_both_absent_is_removed():
    bad = _answer()
    bad["parts"][0]["figures"][0].update({"value": 123.92, "quote": "a sentence that is not in the item"})
    answer = step.write_answer("revenue?", "2026-11-11", READING, PACK["coverage"], "beam-free",
                               pack=PACK, client=_client([json.dumps(bad), json.dumps(bad)]))
    failure = next(f for f in answer["unverified"] if f.get("kind") == "figure")
    assert failure["code"] == "quote_value"
    assert answer["figures_removed"] == 1


def test_empty_or_cut_reply_is_retried_once_before_unparseable():
    prompts = []

    def client(system, user, key):  # noqa: ARG001
        prompts.append(user)
        if len(prompts) == 1:
            return {"content": "", "finish": "length"}
        return {"content": json.dumps(_answer())}

    answer = step.write_answer("revenue?", "2026-11-11", READING, PACK["coverage"], "beam-free",
                               pack=PACK, client=client)
    assert answer["model_calls"] == 2 and answer.get("status") != "unparseable"
    assert "cut off" in prompts[1]


def test_completion_limit_is_at_least_twice_the_longest_valid_round10_reply():
    assert step.MAX_TOKENS >= 2 * 2034          # longest valid round-10 reply, in output tokens


def test_resume_state_retries_unparseable_only_when_asked():
    assert step._resume_state({"status": "rate_limited"}, False) == "retry"
    assert step._resume_state({"status": "unparseable"}, False) == "keep"
    assert step._resume_state({"status": "unparseable"}, True) == "retry"
    assert step._resume_state({}, True) == "keep"


def test_gate_trips_when_more_than_twenty_percent_of_cited_figures_are_removed():
    rows = [{"figures_cited": 10, "figures_removed": 3}] * 10
    gate = step.first_ten_gate(rows)
    assert gate["tripped"] is True and gate["unverified_ratio"] == 0.3
    assert step.first_ten_gate([{"figures_cited": 10, "figures_removed": 2}] * 10)["tripped"] is False
    assert step.first_ten_gate([{"figures_cited": 10, "figures_removed": 9}] * 9)["tripped"] is False


def test_agy_model_routes_through_agy_call_and_records_tools(monkeypatch):
    """T-205 round 13 arm P: the same prompt over agy, and the answer file says whether the model left the pack."""
    seen = []

    def fake_client_for(model, **kwargs):
        def client(system, user, key=""):  # noqa: ARG001
            seen.append((model, "no tools" in system))
            return {"content": json.dumps(_answer()), "in_tok": 3, "out_tok": 4}

        client.tools = {"pilot3_fact": 2}
        client.data_tool_calls = {"data": 2}
        return client

    monkeypatch.setattr(step.agy_call, "client_for", fake_client_for)
    monkeypatch.setattr(step, "resolve_key", lambda: (_ for _ in ()).throw(AssertionError("a key on the agy route")))
    answer = step.write_answer("revenue?", "2026-11-11", READING, PACK["coverage"], "agy:gemini-4-hydrogen-high",
                               pack=PACK)
    assert seen and seen[0][0] == "agy:gemini-4-hydrogen-high" and seen[0][1] is True
    assert answer["model"] == "agy:gemini-4-hydrogen-high"
    assert answer["model_tools"] == {"pilot3_fact": 2} and answer["model_data_tool_calls"] == 2
    assert answer["in_tok"] == 3 and answer["out_tok"] == 4
    assert answer["calculations"][0]["result"] == pytest.approx(10.0)


def test_recheck_maps_old_positional_ids_without_a_model_call():
    import uuid
    root = REPO_ROOT / ".tmp" / f"recheck_test_{uuid.uuid4().hex[:8]}"
    packs, answers = root / "packs", root / "answers"
    packs.mkdir(parents=True, exist_ok=True)
    answers.mkdir(parents=True, exist_ok=True)
    pack = {"as_of": "2026-11-11", "plan": {"question": "revenue?"},
            "parts": [{"id": "p1", "text": "revenue"}],
            "items": [{"id": "fin-3", "route": "fin", "text": "Revenue 1,100.00 crore in Q2FY27"},
                      {"id": "fin-4", "route": "fin", "text": "Revenue 1,000.00 crore in Q2FY26"}]}
    (packs / "pack_Q1.json").write_text(json.dumps(pack), encoding="utf-8")
    reply = {"parts": [{"part": "p1", "status": "answered", "text": "revenue", "figures": [
        {"value": 1100.0, "item_id": "fin-1", "quote": "Revenue 1,100.00 crore in Q2FY27"},
        {"value": 1000.0, "item_id": "999", "quote": "Revenue 1,000.00 crore in Q2FY26"}]}],
        "calcs": [], "final_answer": "Revenue 1,100.00 crore and 1,000.00 crore."}
    (answers / "answer_Q1.json").write_text(json.dumps({"raw_replies": [json.dumps(reply)]}), encoding="utf-8")
    report = step.recheck_set(packs, answers)
    assert report["figures_cited"] == 2
    assert report["saved_by_id_contract"] == 1
    assert report["id_unmapped"] == 1
    assert report["removed_by_reason"] == {"item": 1}
