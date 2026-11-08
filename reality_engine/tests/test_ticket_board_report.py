"""Shivam's Excel ticket board follows the tracker (8 Nov 2026)."""
import openpyxl

from reality_engine.scripts import ticket_board_report as tb


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
