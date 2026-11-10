"""The ruling intake command: append, caps, gate ticket, sheet warning, list (T-127)."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from reality_engine.scripts import ruling, task_board


@pytest.fixture()
def root(monkeypatch):
    """A temp repo root and reports dir; the real RULINGS.md, tracker and reports are untouched."""
    path = Path.cwd() / f"_ruling_test_{uuid.uuid4().hex[:12]}"
    path.mkdir()
    monkeypatch.setenv("REALITY_REPORTS_DIR", str(path / "reports"))
    monkeypatch.setenv("REALITY_TICKET_BOARD_SYNC", "0")
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _rulings(root: Path) -> Path:
    tasks = root / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    path = tasks / "RULINGS.md"
    path.write_text(
        "# Rulings\n"
        "## How we work\n"
        "- Claude reviews, workers build.\n"
        "- Close every branch in 24 hours.\n"
        "\n"
        "## Never\n"
        "- Touch his personal folders.\n",
        encoding="utf-8",
    )
    return path


def _board(root: Path) -> None:
    tasks = root / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    lines = ["# Tickets", ""]
    for section in task_board.SECTIONS:
        lines.extend([f"## {section}", ""])
    (tasks / "TASKS.md").write_text("\n".join(lines), encoding="utf-8")
    (tasks / "TASKS_DONE.md").write_text("# Done tickets\n", encoding="utf-8")


def test_add_appends_as_the_last_bullet_of_its_section(root):
    path = _rulings(root)
    result = ruling.add(section="How we work", text="Never park a branch.", check="doc_gate", root=root)
    text = path.read_text(encoding="utf-8")
    assert "- Never park a branch. [check: doc_gate]" in text
    section = text.split("## How we work", 1)[1].split("## Never", 1)[0]
    assert [line for line in section.splitlines() if line.startswith("- ")][-1] == \
        "- Never park a branch. [check: doc_gate]"
    assert result["ticket"] is None
    assert result["chars_left"] > 0 and result["lines_left"] > 0


def test_a_rule_without_a_check_opens_a_gate_ticket(root):
    _rulings(root)
    _board(root)
    result = ruling.add(section="How we work", text="Close every branch in 24 hours.", root=root)
    assert result["ticket"] == "T-001"
    live, _done = task_board.load_rows(root)
    row = next(item for item in live if item.id == "T-001")
    assert row.section == "Workspace"
    assert row.title == "Gate for ruling: Close every branch in 24 hours."
    assert row.accept == "Shivam: standing_rules.xlsx shows a code gate for it"
    assert row.close_when == "standing_rules.xlsx shows a code gate for it"
    assert row.why.startswith("ruling add on "), row.why
    assert row.source == "ruling intake"


def test_a_custom_ticket_title_is_used(root):
    _rulings(root)
    _board(root)
    ruling.add(section="How we work", text="A rule.", ticket_title="Gate: worker review", root=root)
    live, _done = task_board.load_rows(root)
    assert live[-1].title == "Gate: worker review"


def test_the_line_cap_refuses_without_writing(root):
    path = root / "tasks" / "RULINGS.md"
    path.parent.mkdir(parents=True)
    before = "# Rulings\n## How we work\n" + "".join(f"- rule {i}\n" for i in range(38))
    path.write_text(before, encoding="utf-8")
    _board(root)
    with pytest.raises(ValueError, match="1 lines over 40"):
        ruling.add(section="How we work", text="one more", check="doc_gate", root=root)
    assert path.read_text(encoding="utf-8") == before
    assert task_board.load_rows(root)[0] == [], "a refused ruling opens no ticket"


def test_the_character_cap_refuses_without_writing(root):
    path = root / "tasks" / "RULINGS.md"
    path.parent.mkdir(parents=True)
    before = "# Rulings\n## How we work\n"
    path.write_text(before, encoding="utf-8")
    with pytest.raises(ValueError, match="characters over 8000"):
        ruling.add(section="How we work", text="x" * 9000, check="doc_gate", root=root)
    assert path.read_text(encoding="utf-8") == before


def test_an_unknown_section_is_refused_naming_the_sections(root):
    _rulings(root)
    with pytest.raises(ValueError, match="no '## Data' section.*How we work, Never"):
        ruling.add(section="Data", text="A rule.", check="doc_gate", root=root)


def test_a_locked_sheet_is_a_warning_not_a_failed_ruling(root, monkeypatch, capsys):
    from reality_engine.scripts import standing_rules_report

    _rulings(root)

    def locked(*_args, **_kwargs):
        raise PermissionError("locked by Excel")

    monkeypatch.setattr(standing_rules_report, "write", locked)
    result = ruling.add(section="How we work", text="A rule.", check="doc_gate", root=root)
    assert result["sheet"] is None
    assert "locked by Excel" in capsys.readouterr().err


def test_list_summarizes_sections_and_the_room_left(root):
    _rulings(root)
    text = ruling.summary(root=root)
    assert "3 rulings in 2 sections" in text
    assert "## How we work: 2 bullets" in text
    assert "## Never: 1 bullet" in text
    assert "characters left (limit 8,000)" in text
    assert "lines left (limit 40)" in text


def test_the_t127_gate_tags_are_registered_for_the_sheet():
    from reality_engine.scripts import standing_rules_report

    assert {"worker_review", "merge_tests", "code_worker_limit"} <= set(standing_rules_report.CODE_GATES)


def test_cli_add_and_refusal_return_codes(root, monkeypatch, capsys):
    _rulings(root)
    monkeypatch.setattr(ruling, "ROOT", root)
    assert ruling.main(["add", "--section", "How we work", "--text", "A new rule.",
                        "--check", "doc_gate"]) == 0
    assert "characters and" in capsys.readouterr().out
    assert ruling.main(["list"]) == 0
    assert "rulings in" in capsys.readouterr().out
    assert ruling.main(["add", "--section", "No such section", "--text", "x"]) == 1
    assert "ruling:" in capsys.readouterr().err
