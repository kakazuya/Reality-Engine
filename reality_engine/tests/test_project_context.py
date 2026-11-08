"""Tests for the on-demand project context (T-125): rulings index/topic and the live state.

Run from the repo root:
    python -m pytest -q reality_engine/tests/test_project_context.py
"""
from pathlib import Path
import sys

import pytest

from reality_engine.scripts import project_context

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "reality_engine" / "tests" / "fixtures"
sys.path.insert(0, str(FIXTURES))

from dsh_worker_testenv import make_temp_dir, remove_tree  # noqa: E402

RULINGS = """# Shivam's rulings
## Scope
- Golden order: raw data, banks, schema.
  Then the pilot.
- Lean: nothing without a failure.

## Never
- Print or copy keys.
- Push without his OK.
"""

STATE = """# STATE
## Now
Live now.
## Next action
Do the thing.
## Merge recipe
Review by meaning.
## Big
""" + "x" * 7000 + "\n"


@pytest.fixture()
def tmp_path():
    """A sandbox-safe temp root: inherited ACL, unlike tempfile's mode-0700 dir."""
    path = make_temp_dir(ROOT / ".tmp" / "project-context-tests", "pc-")
    yield path
    remove_tree(path)


def write(root: Path, rulings: str = RULINGS, state: str = STATE) -> None:
    tasks = root / "tasks"
    tasks.mkdir()
    (tasks / "RULINGS.md").write_text(rulings, encoding="utf-8")
    (tasks / "STATE.md").write_text(state, encoding="utf-8")


def test_sections_one_item_per_bullet_with_its_continuation_lines(tmp_path):
    items = project_context.sections(RULINGS)
    assert [i["section"] for i in items] == ["Scope", "Scope", "Never", "Never"]
    assert items[0]["text"] == "Golden order: raw data, banks, schema.\nThen the pilot."
    assert items[3]["text"] == "Push without his OK."


def test_rules_topic_hit_returns_the_whole_bullet(tmp_path):
    write(tmp_path)
    out = project_context.rules("golden order", root=tmp_path)
    assert out["found"] is True
    assert len(out["rules"]) == 1
    assert out["rules"][0]["section"] == "Scope"
    assert out["rules"][0]["text"].endswith("Then the pilot."), "a matched bullet is never truncated"


def test_rules_topic_miss_returns_the_index(tmp_path):
    write(tmp_path)
    out = project_context.rules("nonexistent topic", root=tmp_path)
    assert out["found"] is False
    assert [s["name"] for s in out["sections"]] == ["Scope", "Never"]
    assert out["sections"][0]["items"][0].startswith("Golden order")


def test_rules_without_topic_is_the_section_index(tmp_path):
    write(tmp_path)
    out = project_context.rules(root=tmp_path)
    assert "found" not in out
    assert [s["name"] for s in out["sections"]] == ["Scope", "Never"]
    assert len(out["sections"][0]["items"]) == 2


def test_index_snippets_are_capped_at_120_characters(tmp_path):
    write(tmp_path, rulings="## Scope\n- " + "y" * 200 + "\n")
    out = project_context.rules(root=tmp_path)
    assert len(out["sections"][0]["items"][0]) == 120


def test_state_keeps_now_and_next_action_whole(tmp_path):
    write(tmp_path)
    out = project_context.state(tmp_path, max_chars=200)
    assert out["sections"]["Now"] == "Live now."
    assert out["sections"]["Next action"] == "Do the thing."
    assert out["sections"]["Merge recipe"] == "Review by meaning."
    assert out["dropped"] == ["Big"], "a section over the budget is named, never half-printed"
    assert isinstance(out["card"], str)


def test_missing_files_never_raise(tmp_path):
    out = project_context.rules("anything", root=tmp_path)
    assert out["found"] is False
    live = project_context.state(tmp_path)
    assert "Now" in live["sections"] and "UNREADABLE" in live["sections"]["Now"]
