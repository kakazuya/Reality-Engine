"""Shivam (8 Nov): a standing-rules sheet lists every ruling and how it is enforced."""
import sys
from pathlib import Path

import openpyxl
import pytest

from reality_engine.scripts import project_context
from reality_engine.scripts import standing_rules_report as sr

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from dsh_worker_testenv import make_temp_dir, remove_tree  # noqa: E402


@pytest.fixture()
def tmp_path():
    """A sandbox-safe temp root: inherited ACL, unlike pytest's mode-0700 dir."""
    path = make_temp_dir(REPO / ".tmp" / "standing-rules-tests", "rules-")
    yield path
    remove_tree(path)


def test_every_ruling_is_listed_with_its_gate(tmp_path):
    sr.write(tmp_path)
    ws = openpyxl.load_workbook(tmp_path / "standing_rules.xlsx")["Rules"]
    rows = list(ws.iter_rows(values_only=True))[1:]
    text = (sr.ROOT / "tasks" / "RULINGS.md").read_text(encoding="utf-8")
    assert len(rows) == len(project_context.sections(text))
    tagged = [r for r in rows if "[check:" in str(r[2])]
    assert tagged and all(not str(r[6]).startswith("none") for r in tagged)
    assert (tmp_path / "standing_rules.html").read_text(encoding="utf-8").startswith("<!doctype html>")
