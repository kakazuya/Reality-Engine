from pathlib import Path
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


def test_rulings_come_first_and_fit_the_hook_cap():
    text = build()
    assert text.startswith("# Shivam's rulings")
    assert len(text) <= LIMIT + 100
    assert "## Next action" in text, "STATE was cut off: shorten tasks/STATE.md or tasks/RULINGS.md"


def test_recent_decisions_returns_last_headings():
    log = "## one\nbody\n## two\n## three\n"
    assert recent_decisions(log, 2) == ["## two", "## three"]


def test_session_start_hook_also_fires_after_compaction():
    settings = (ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert "SessionStart" in settings and "compact" in settings and "load_context.py" in settings


def test_card_follows_state_and_the_limit_still_holds(tmp_path, monkeypatch):
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
    assert len(text) <= LIMIT + 100
