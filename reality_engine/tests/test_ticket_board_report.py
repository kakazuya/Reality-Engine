"""Shivam's Excel ticket board follows the tracker (8 Nov 2026)."""
import sys
from pathlib import Path

import openpyxl
import pytest

from reality_engine.scripts import ticket_board_report as tb

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from dsh_worker_testenv import make_temp_dir, remove_tree  # noqa: E402


@pytest.fixture()
def tmp_path():
    """A sandbox-safe temp root: inherited ACL, unlike pytest's mode-0700 dir."""
    path = make_temp_dir(REPO / ".tmp" / "ticket-board-report-tests", "report-")
    yield path
    remove_tree(path)


def test_groups():
    assert tb.group("OPEN") == "Open"
    assert tb.group("DOING Wolf") == "In progress"
    assert tb.group("WAITING Shivam") == "Pending a bottleneck"
    assert tb.group("LOOKING") == "Pending a bottleneck"
    assert tb.group("DONE") == "Closed (resolved)"
    assert tb.group("DROPPED merged 6 Nov") == "Closed (resolved)"
    assert tb.group("DROPPED Shivam 6 Nov: settled") == "Sidelined"


def test_write_matches_tracker(tmp_path):
    res = tb.write(out_dir=tmp_path)
    assert not res["failed"]
    wb = openpyxl.load_workbook(tmp_path / "ticket_board.xlsx")
    total = sum(wb[s].max_row - 1 for s in wb.sheetnames if s != "Summary")
    assert total == len(tb.rows()) == sum(res["groups"].values())
    assert (tmp_path / "ticket_board.html").read_text(encoding="utf-8").startswith("<!doctype html>")


def test_sync_can_be_turned_off(monkeypatch, tmp_path):
    monkeypatch.setenv("REALITY_TICKET_BOARD_SYNC", "0")
    monkeypatch.setattr(tb, "OUT_DIR", tmp_path)
    tb.sync_quietly()
    assert not list(tmp_path.iterdir())


def test_report_carries_why_close_when_owner_last_change_and_links(tmp_path):
    from reality_engine.scripts import task_board

    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "TASKS.md").write_text("# Tickets\n", encoding="utf-8")
    (tasks / "TASKS_DONE.md").write_text("# Done tickets\n", encoding="utf-8")
    task_board.add(section="Data", title="self-explaining ticket", accept="python -c pass",
                   why="the 30 Oct 2026 board run dropped a row with no reason",
                   close_when="the test passes", status="doing", owner="Wolf",
                   links=["tasks/handoff/board.md"], root=tmp_path)
    res = tb.write(root=tmp_path, out_dir=tmp_path / "out")
    assert not res["failed"]
    sheet = openpyxl.load_workbook(tmp_path / "out" / "ticket_board.xlsx")["In progress"]
    headers = [cell.value for cell in sheet[1]]
    for name in ("Why", "Close when", "Owner", "Last change", "Links"):
        assert name in headers, headers
    row = [cell.value for cell in sheet[2]]
    assert str(row[headers.index("Why")]).startswith("the 30 Oct 2026")
    assert str(row[headers.index("Close when")]) == "the test passes"
    assert str(row[headers.index("Owner")]) == "Wolf"
    assert str(row[headers.index("Links")]) == "tasks/handoff/board.md"
    page = (tmp_path / "out" / "ticket_board.html").read_text(encoding="utf-8")
    for name in ("Why", "Close when", "Owner", "Last change", "Links"):
        assert f"<th>{name}</th>" in page, name
