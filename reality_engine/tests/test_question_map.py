"""The question map covers every bank question naming the 3 prototype companies, and only its script sets status."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAP_DIR = ROOT / "tasks" / "pilot60" / "question_map"


def _module():
    spec = importlib.util.spec_from_file_location("build_map", MAP_DIR / "build_map.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_bank_question_naming_them_has_a_rule_and_no_extras():
    module = _module()
    wanted = {row["mid"] for row in module.bank_rows()}
    mapped = set(module.load_rules())
    assert wanted - mapped == set(), "questions with no rule"
    assert mapped - wanted == set(), "rules for questions outside the map"


def test_rules_state_no_result():
    text = (MAP_DIR / "rules.py").read_text(encoding="utf-8")
    for word in ("INPUTS_HELD", "INPUTS_PARTIAL", "NOT_EXTRACTED"):
        assert word not in text


def test_status_comes_from_counts():
    status = _module().status_of
    assert status({"a": {"KEC": 3}, "b": {"KEC": 1}}) == "INPUTS_HELD"
    assert status({"a": {"KEC": 3}, "b": {"KEC": 0}}) == "INPUTS_PARTIAL"
    assert status({"a": {"KEC": 0}}) == "NOT_EXTRACTED"


def test_written_file_matches_a_fresh_check():
    module = _module()
    stored = {r["mid"]: r["status"] for r in map(json.loads, module.OUT.open(encoding="utf-8"))}
    assert stored == {r["mid"]: r["status"] for r in module.build()}, "a status was hand-edited or the stores moved: rerun build_map.py"
