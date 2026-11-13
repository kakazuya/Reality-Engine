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
    assert answer["final_answer"] == "Revenue was 1,100.00 crore and grew 10 %."
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
