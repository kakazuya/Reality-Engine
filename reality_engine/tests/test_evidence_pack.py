import os
import tempfile
from reality_engine.answer import evidence_pack as ep
from reality_engine.answer import pack_recall as pr


def test_plan_kinds():
    for q, kind in [
        ("What was revenue in Q2FY27?", "fact"),
        ("What did management say about margins?", "statement"),
        ("List documents filed", "list"),
        ("What is the guidance for FY27?", "guidance"),
        ("Compute ROE", "compute"),
        ("Price reaction to results", "price"),
    ]:
        p = ep.plan(q, "2026-01-01")
        assert "kind" in p
        assert p["kind"] in ("fact", "statement", "list", "guidance", "compute", "price", "holding", "all")


def test_plan_periods():
    p = ep.plan("revenue in Q2FY27", "2026-11-11")
    assert "Q2FY27" in p["periods"]


def test_dedupe():
    items = [
        {"id": "a", "route": "semantic", "doc_key": "d1", "page": 1, "text": "hello"},
        {"id": "b", "route": "search", "doc_key": "d1", "page": 1, "text": "hello"},
    ]
    out = ep._dedupe(items)
    assert len(out) == 1


def test_asof_drop():
    items = [{"id": "a", "route": "semantic", "doc_key": "d1", "page": 1, "text": "x", "known_at": "2026-01-02"}]
    out = [it for it in items if ep._asof_ok(it.get("known_at"), "2026-01-01")]
    assert out == []


def test_quota():
    items = [{"id": f"i{i}", "route": "semantic", "doc_key": f"d{i}", "page": i, "text": "x"} for i in range(5)]
    out = ep._apply_quota(items, {"semantic": 2})
    assert len(out) == 2


def test_normalize_number():
    assert pr.normalize_number("1,234.50") == "1234.5"
    assert pr.normalize_number("100") == "100"


def test_truth_tokens():
    t = pr.truth_tokens('revenue was 1,234.5 crore and "strong growth"')
    assert "1234.5" in t["numbers"]
    assert "strong growth" in t["phrases"]