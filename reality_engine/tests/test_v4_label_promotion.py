"""v4 label promotion — pure helpers, no live database and no network.

The Beam call itself is not exercised here (it would be a paid/remote call); the
driver is checked through its deterministic pieces: decision parsing, the strict
bank match, the sampled value evidence, the candidate ranking and the conservative
near-duplicate report.
"""
import json
from pathlib import Path

import reality_engine.query.v4.promote_vocab as pv


def test_decision_parser_accepts_only_declared_outcomes():
    labels = {"revenue", "pat"}
    buckets = {"signal", "section"}
    assert pv.normalize_decision("new_label:order_backlog — confirmed orders",
                                 labels, buckets) == ("new_label:order_backlog",
                                                      "confirmed orders")
    assert pv.normalize_decision("alias_of:Revenue", labels, buckets) == (
        "alias_of:revenue", "")
    assert pv.normalize_decision("bucket:signal", labels, buckets) == ("bucket:signal", "")
    assert pv.normalize_decision("meaningless", labels, buckets) == ("meaningless", "")
    # a new label that is already declared is an alias, not a second label
    assert pv.normalize_decision("new_label:revenue — the same", labels, buckets) == (
        "alias_of:revenue", "the same")
    # undeclared ids are rejected, never mapped
    assert pv.normalize_decision("alias_of:made_up", labels, buckets) is None
    assert pv.normalize_decision("bucket:made_up", labels, buckets) is None
    assert pv.normalize_decision("other", labels, buckets) is None


def test_answer_parser_is_tolerant_but_rejects_undeclared():
    text = ('{"0": "bucket:signal", "1": "alias_of:revenue", '
            '"2": "nonsense", "3": "new_label:foo - bar"')
    accepted, rejected = pv.parse_answers(
        text, {0: None, 1: None, 2: None, 3: None},
        {"revenue", "pat"}, {"signal", "section"})
    assert accepted[0] == ("bucket:signal", "")
    assert accepted[1] == ("alias_of:revenue", "")
    assert accepted[3] == ("new_label:foo", "bar")
    assert set(rejected) == {2}
    # a truncated body still yields the complete pairs
    got, bad = pv.parse_answers('{"0": "bucket:signal"', {0: None, 1: None},
                                {"revenue"}, {"signal"})
    assert got == {0: ("bucket:signal", "")} and set(bad) == {1}


def test_value_evidence_is_a_sample_not_a_claim_about_all_occurrences():
    ev = pv.value_evidence("revenue was 1,200 crore", "no number here")
    assert ev["ctx_n"] == 2 and ev["value_n"] == 1 and ev["unit_n"] == 1
    assert ev["value_share"] == 0.5
    empty = pv.value_evidence(None, None)
    assert empty["ctx_n"] == 0 and empty["value_share"] is None


def test_bank_match_keeps_rare_asked_terms_and_rejects_generic_single_tokens():
    base = Path(".tmp") / "v4_promotion_tests"
    base.mkdir(parents=True, exist_ok=True)
    path = base / "bank.jsonl"
    path.write_text("\n".join(json.dumps({"mid": mid, "question": q}) for mid, q in [
        ("MB1", "What was the return on capital, and why did it fall?"),
        ("MB2", "If the monsoon fails, which sectors are exposed?"),
        ("MB3", "What operations drove the margin?"),
        ("MB4", "Was there a credit rating action?"),
    ]), encoding="utf-8")
    questions = pv.load_questions(path)
    index = pv._question_index(questions)
    assert pv.bank_evidence("ROCE", questions, index)["q_named"] is True
    assert pv.bank_evidence("monsoon", questions, index)["q_named"] is True
    # a generic single token is never "named" merely because a question uses it
    generic = pv.bank_evidence("operations", questions, index)
    assert generic["q_token"] is True and generic["q_named"] is False
    assert pv.bank_evidence("credit rating", questions, index)["q_named"] is True


def test_coverage_reports_uses_and_company_spread():
    rows = [
        {"surface_id": 1, "n_occurrences": 10, "n_isins": 2},
        {"surface_id": 2, "n_occurrences": 30, "n_isins": 6},
        {"surface_id": 3, "n_occurrences": 60, "n_isins": 2},
    ]
    cov = pv.coverage(rows, {1}, {1, 2})
    assert cov["uses"] == 10 and cov["uses_pct"] == 10.0
    assert cov["isin_pairs"] == 2 and cov["isin_pairs_pct"] == 20.0
    assert cov["surfaces"] == 1 and cov["surfaces_pct"] == 100 / 3
    assert cov["head_labelled"] == 1 and cov["head_total"] == 2


def test_new_label_dedupe_is_conservative():
    new = {
        "exceptional_item": {"uses": 1, "definition": "one-off item"},
        "exceptional_items": {"uses": 2, "definition": "one-off items"},
        "environment": {"uses": 3, "definition": "environmental metrics"},
        "energy": {"uses": 4, "definition": "energy consumption"},
    }
    d = pv.dedupe_new_labels(new)
    assert d["raw"] == 4 and d["clusters"] == 3 and d["merged_away"] == 1
    assert d["groups"][0]["members"] == ["exceptional_item", "exceptional_items"]
    # `environment` and `energy` are NOT merged: no token-subset bridging
    assert all("energy" not in g["members"] for g in d["groups"])
