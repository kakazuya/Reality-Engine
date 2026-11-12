from pathlib import Path
import re
import sys

import pytest

from reality_engine.scripts.load_context import LIMIT, build, recent_decisions

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "reality_engine" / "tests" / "fixtures"
sys.path.insert(0, str(FIXTURES))

from dsh_worker_testenv import make_temp_dir, remove_tree  # noqa: E402


@pytest.fixture()
def tmp_path():
    """A sandbox-safe temp root: inherited ACL, unlike tempfile's mode-0700 dir."""
    path = make_temp_dir(ROOT / ".tmp" / "load-context-tests", "ctx-")
    yield path
    remove_tree(path)


def test_rulings_come_first_and_are_never_cut():
    text = build()
    first = text.splitlines()[0]
    assert first.startswith("# Shivam's rulings") or first.startswith("RULINGS.md is "), first
    rulings = (ROOT / "tasks" / "RULINGS.md").read_text(encoding="utf-8")
    last_heading = re.findall(r"^## .*$", rulings, flags=re.M)[-1]
    assert last_heading in text, "the end of RULINGS.md was cut from the hook"


def test_over_budget_rulings_still_print_whole_with_one_warning_line(tmp_path, monkeypatch):
    from reality_engine.scripts import load_context

    tasks = tmp_path / "tasks"
    tasks.mkdir()
    bullets = "".join(f"- ruling {n}: " + "x" * 100 + "\n" for n in range(100))
    (tasks / "RULINGS.md").write_text(
        "# Shivam's rulings\n## Scope\n" + bullets + "## Agreed direction\n- last ruling\n",
        encoding="utf-8")
    (tasks / "STATE.md").write_text(
        "# STATE\n## Now\nnow text\n## Next action\nnext text\n", encoding="utf-8")
    monkeypatch.setattr(load_context, "ROOT", tmp_path)
    text = load_context.build()
    first = text.splitlines()[0]
    assert first.startswith("RULINGS.md is ") and "over its 8,000 budget" in first
    assert text.count("over its 8,000 budget") == 1
    assert "## Agreed direction" in text and "- last ruling" in text, "a ruling was cut"


def test_recent_decisions_returns_last_headings():
    log = "## one\nbody\n## two\n## three\n"
    assert recent_decisions(log, 2) == ["## two", "## three"]


def test_session_start_hook_also_fires_after_compaction():
    settings = (ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert "SessionStart" in settings and "compact" in settings and "load_context.py" in settings


def test_card_follows_state_even_when_the_hook_is_full(tmp_path, monkeypatch):
    from reality_engine.scripts import task_board

    tasks = tmp_path / "tasks"
    tasks.mkdir()
    rows = [
        f"- T-{n:03d} | OPEN | P2 | ticket {n} | accept: x | from: test | opened 2026-10-01"
        for n in range(1, 201)
    ]
    (tasks / "TASKS.md").write_text(
        "# Tickets\n\n## Workspace\n" + "\n".join(rows) + "\n", encoding="utf-8")
    (tasks / "TASKS_DONE.md").write_text("# Done tickets\n", encoding="utf-8")
    monkeypatch.setattr(task_board, "ROOT", tmp_path)
    text = build()
    assert "## Next action" in text, "a full tracker must never push STATE out"
    assert "python -m reality_engine.scripts.task_board list" in text
    assert text.index("## Next action") < text.index("task_board list"), "the card comes after STATE"
    assert len(text) <= LIMIT or "over its 8,000 budget" in text, "a long hook must say why"


def test_broken_tracker_never_costs_the_rulings(monkeypatch):
    import reality_engine.scripts.task_board as board
    from reality_engine.scripts import load_context

    def boom():
        raise RuntimeError("broken tracker")

    monkeypatch.setattr(board, "card", boom)
    text = load_context.build()
    assert "# Shivam's rulings" in text and "task card unavailable" in text


def test_due_ideas_lists_open_ideas_past_their_review_date():
    from reality_engine.scripts.load_context import due_ideas
    text = ("# Idea box\n\n## I-001: Old idea\n- Review trigger: stage `prediction`; review by 2026-01-01\n- Status: parked\n\n"
            "## I-002: Future idea\n- Review trigger: stage `maintenance`; review by 2099-01-01\n- Status: parked\n\n"
            "## I-003: Promoted idea\n- Review trigger: stage `maintenance`; review by 2026-01-01\n"
            "- Status: promoted to T-999 (2026-01-02)\n")
    due = due_ideas(text, "2026-06-01")
    assert len(due) == 1 and due[0].startswith("- I-001 Old idea") and "prediction" in due[0]
