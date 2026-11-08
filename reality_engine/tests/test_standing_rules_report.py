"""Shivam (8 Nov): a standing-rules sheet lists every ruling and how it is enforced."""
import openpyxl

from reality_engine.scripts import project_context
from reality_engine.scripts import standing_rules_report as sr


def test_every_ruling_is_listed_with_its_gate(tmp_path):
    sr.write(tmp_path)
    ws = openpyxl.load_workbook(tmp_path / "standing_rules.xlsx")["Rules"]
    rows = list(ws.iter_rows(values_only=True))[1:]
    text = (sr.ROOT / "tasks" / "RULINGS.md").read_text(encoding="utf-8")
    assert len(rows) == len(project_context.sections(text))
    tagged = [r for r in rows if "[check:" in r[2]]
    assert tagged and all(not r[6].startswith("none") for r in tagged)
    assert (tmp_path / "standing_rules.html").read_text(encoding="utf-8").startswith("<!doctype html>")
