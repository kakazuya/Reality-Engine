"""The ticket tracker: ids, rows, lint, card, the done gate and the commit gate."""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from reality_engine.scripts import doc_gate, task_board

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(FIXTURES))

from dsh_worker_testenv import make_temp_dir, remove_tree  # noqa: E402


@pytest.fixture()
def tmp_path():
    """A sandbox-safe temp root: inherited ACL, unlike tempfile's mode-0700 dir."""
    path = make_temp_dir(REPO / ".tmp" / "task-board-tests", "board-")
    yield path
    remove_tree(path)


def _row(row_id="T-001", status="OPEN", priority="P2", title="a ticket",
         accept="python -c pass", source="test", opened="2026-10-30", tail=""):
    line = (f"- {row_id} | {status} | {priority} | {title} | accept: {accept} | "
            f"from: {source} | opened {opened}")
    return f"{line} | {tail}" if tail else line


def _board(root: Path, rows: dict[str, list[str]] | None = None, done: list[str] | None = None) -> Path:
    tasks = root / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    lines = ["# Tickets", "", "One row per line.", ""]
    for section in task_board.SECTIONS:
        lines.extend([f"## {section}", ""])
        lines.extend((rows or {}).get(section, []))
        lines.append("")
    (tasks / "TASKS.md").write_text("\n".join(lines), encoding="utf-8")
    (tasks / "TASKS_DONE.md").write_text(
        "# Done tickets\n" + "\n".join(done or []) + "\n", encoding="utf-8")
    return root


def _exit(code: int) -> str:
    return f'"{sys.executable}" -c "import sys; sys.exit({code})"'


def test_add_allocates_max_plus_one_inside_the_section(tmp_path):
    _board(tmp_path, {"Data": [_row("T-004")]}, done=[_row("T-009", "DONE", tail="done abcdef1 2026-10-30")])
    new_id = task_board.add(section="Data", title="next", accept=_exit(0), root=tmp_path)
    assert new_id == "T-010", "the id is the maximum across both files plus one"
    live, _done = task_board.load_rows(tmp_path)
    assert [row.id for row in live if row.section == "Data"] == ["T-004", "T-010"]
    task_board.set_status(new_id, "DOING", "Wolf", root=tmp_path)
    live, _done = task_board.load_rows(tmp_path)
    assert live[-1].section == "Data", "a row stays in its section"
    assert live[-1].status == "DOING Wolf"
    assert task_board.lint_problems(tmp_path) == []


def test_pipes_and_bad_status_are_refused(tmp_path):
    _board(tmp_path)
    with pytest.raises(task_board.BoardError, match="pipe"):
        task_board.add(section="Data", title="a | b", accept=_exit(0), root=tmp_path)
    with pytest.raises(task_board.BoardError):
        task_board.add(section="Nope", title="x", accept=_exit(0), root=tmp_path)
    with pytest.raises(task_board.BoardError):
        task_board.add(section="Data", title="x", accept=_exit(0), status="DOING", root=tmp_path)


def test_two_concurrent_adds_get_different_ids(tmp_path):
    _board(tmp_path)
    code = (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0, r'{REPO}'); "
        "from reality_engine.scripts import task_board as tb; "
        f"tb.ROOT = Path(r'{tmp_path}'); "
        "print(tb.add(section='Data', title=sys.argv[1], accept='x'))"
    )
    with task_board.file_lock(tmp_path):
        children = [
            subprocess.Popen([sys.executable, "-c", code, f"writer {n}"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for n in (1, 2)
        ]
        time.sleep(1.0)
        assert all(child.poll() is None for child in children), "add must wait for the id lock"
    ids = [child.communicate(timeout=60)[0].strip() for child in children]
    assert sorted(ids) == ["T-001", "T-002"], ids
    live, _done = task_board.load_rows(tmp_path)
    assert len(live) == 2 and len({row.id for row in live}) == 2


def test_done_refuses_when_the_accept_command_fails(tmp_path):
    _board(tmp_path, {"Data": [_row(accept=_exit(3))]})
    with pytest.raises(task_board.BoardError, match="exited 3"):
        task_board.done("T-001", root=tmp_path)
    live, done = task_board.load_rows(tmp_path)
    assert [row.id for row in live] == ["T-001"], "a failed accept closes nothing"
    assert done == []


def test_done_moves_the_row_with_head_hash(tmp_path):
    _board(tmp_path, {"Data": [_row(accept=_exit(0))]})
    task_board.done("T-001", root=tmp_path)
    live, done = task_board.load_rows(tmp_path)
    assert live == []
    assert done[0].status == "DONE"
    assert done[0].tail.startswith("done "), done[0].tail
    assert task_board.lint_problems(tmp_path) == []


def test_accept_shivam_closes_only_with_the_flag(tmp_path):
    _board(tmp_path, {"Data": [_row(accept="Shivam")]})
    with pytest.raises(task_board.BoardError, match="--shivam"):
        task_board.done("T-001", root=tmp_path)
    task_board.done("T-001", shivam=True, root=tmp_path)
    assert task_board.load_rows(tmp_path)[0] == []


def test_drop_needs_a_reason(tmp_path):
    _board(tmp_path, {"Data": [_row()]})
    with pytest.raises(task_board.BoardError):
        task_board.drop("T-001", "  ", root=tmp_path)
    task_board.drop("T-001", "merged into T-002", root=tmp_path)
    live, done = task_board.load_rows(tmp_path)
    assert live == [] and done[0].status == "DROPPED merged into T-002"


def test_lint_catches_each_defect(tmp_path):
    _board(tmp_path, {"Data": [_row("T-001", priority="P9")]})
    assert any("malformed row" in problem for problem in task_board.lint_problems(tmp_path))

    _board(tmp_path, {"Data": [_row("T-001")]},
           done=[_row("T-001", "DONE", tail="done abcdef1 2026-10-30")])
    assert any("appears in both" in problem for problem in task_board.lint_problems(tmp_path))

    _board(tmp_path, {"Data": [_row("T-001", "DONE", tail="done abcdef1 2026-10-30")]})
    assert any("move it to" in problem for problem in task_board.lint_problems(tmp_path))

    _board(tmp_path, done=[_row("T-001", "DONE")])
    assert any("no commit hash" in problem for problem in task_board.lint_problems(tmp_path))

    _board(tmp_path, done=[_row("T-001", "DROPPED", tail="dropped 2026-10-30")])
    assert any("no reason" in problem for problem in task_board.lint_problems(tmp_path))


def test_card_is_at_most_600_characters_with_200_rows(tmp_path):
    rows = {section: [] for section in task_board.SECTIONS}
    titles = [f"a very long ticket title that must be cut short before the card fills up {n}" for n in range(200)]
    rows["Workspace"] = [_row(f"T-{n:03d}", "DOING Wolf", title=titles[n], opened="2026-10-01")
                         for n in range(1, 31)]
    rows["Data"] = [_row(f"T-{n:03d}", title=titles[n - 1], opened="2026-10-01") for n in range(31, 171)]
    rows["Bank"] = [_row(f"T-{n:03d}", "WAITING Shivam", title=titles[n - 1], opened="2026-10-01")
                    for n in range(171, 201)]
    _board(tmp_path, rows)
    text = task_board.card(tmp_path)
    assert len(text) <= 600, f"{len(text)} characters"
    assert text.startswith("OPEN 200:"), text
    assert "task_board list" in text


def test_card_says_so_when_files_are_missing_or_malformed(tmp_path):
    missing = task_board.card(tmp_path)
    assert missing.count("\n") == 0 and "unavailable" in missing
    _board(tmp_path)
    (tmp_path / "tasks" / "TASKS.md").write_text("# Tickets\n- T-1 broken | row\n", encoding="utf-8")
    malformed = task_board.card(tmp_path)
    assert malformed.count("\n") == 0 and "unavailable" in malformed


def test_doc_gate_line_limit_covers_tasks_md():
    def lines(n):
        return lambda name: chr(10).join(["x"] * n)

    assert "limit 150" in (doc_gate.check(["tasks/TASKS.md"], branch="main", merging=False, read=lines(151)) or "")


def test_doc_gate_runs_the_tracker_lint(tmp_path):
    _board(tmp_path, {"Data": [_row("T-001", priority="P9")]})
    problem = doc_gate.check(["tasks/TASKS.md"], branch="main", merging=False, root=tmp_path)
    assert problem and "tracker lint failed" in problem
    _board(tmp_path)
    assert doc_gate.check(["tasks/TASKS.md"], branch="main", merging=False, root=tmp_path) is None


def test_commit_message_needs_a_ticket_on_main_only():
    assert doc_gate.check_message("fix the card", branch="main")
    assert doc_gate.check_message("T-014 fix the card", branch="main") is None
    assert doc_gate.check_message("fix the card\n\nNo-ticket: one-off typo", branch="main") is None
    assert doc_gate.check_message("fix the card", branch="dsh/20261101T000000Z-abc") is None


def _git_repo(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    for key, value in (("user.email", "t@example.invalid"), ("user.name", "T")):
        subprocess.run(["git", "config", key, value], cwd=tmp_path, check=True)
    scripts = tmp_path / "reality_engine" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(REPO / "reality_engine" / "scripts" / "doc_gate.py", scripts / "doc_gate.py")
    subprocess.run([sys.executable, str(scripts / "doc_gate.py"), "--install"],
                   cwd=tmp_path, check=True, capture_output=True)


def test_install_writes_both_hooks(tmp_path):
    _git_repo(tmp_path)
    hooks = tmp_path / ".git" / "hooks"
    assert "doc_gate.py" in (hooks / "pre-commit").read_text(encoding="utf-8")
    assert "--commit-msg" in (hooks / "commit-msg").read_text(encoding="utf-8")
    for name in ("pre-commit", "commit-msg"):
        assert "= main ]" in (hooks / name).read_text(encoding="utf-8"), f"{name} must be main-only"


def test_export_writes_both_files_into_one_sheet(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    _board(tmp_path, {"Data": [_row()]}, done=[_row("T-000", "DONE", tail="done abcdef1 2026-10-30")])
    target = tmp_path / "board.xlsx"
    assert task_board.export(str(target), root=tmp_path) == 2
    sheet = openpyxl.load_workbook(target).active
    assert [cell.value for cell in sheet[1]][0] == "id"
    assert sheet.max_row == 3
