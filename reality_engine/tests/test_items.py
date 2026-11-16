"""T-219: one view over tickets, ideas, rulings and store defects."""
from __future__ import annotations

import json

from reality_engine.scripts import items


def test_four_sources_read_into_one_shape_with_cross_links(tmp_path):
    (tmp_path / "t.jsonl").write_text(json.dumps({"id": "T-219", "status": "OPEN", "title": "Unified items",
                                                  "why": "from I-006", "section": "Workspace",
                                                  "priority": "P1", "opened": "2026-11-16"}) + "\n", encoding="utf-8")
    (tmp_path / "ideas.md").write_text(
        "## I-006: Typed replies\n- Created: 2026-11-12 22:00 IST, by Eagle\n- Purpose (what it is for): honest\n"
        "- Review trigger: stage `extraction-design`; review by 2026-11-16\n- Status: parked\n", encoding="utf-8")
    (tmp_path / "rules.md").write_text("## How we work\n- Tools local (16 Nov): see T-219.\n", encoding="utf-8")
    (tmp_path / "n.jsonl").write_text(json.dumps({"id": "R-005", "status": "fixed", "symptom": "lakh as crore",
                                                  "cause": "x", "fix": "under T-218", "part": "kpi",
                                                  "tags": ["unit"], "scope": "general"}) + "\n", encoding="utf-8")
    got = [*items.tickets(tmp_path / "t.jsonl"), *items.ideas(tmp_path / "ideas.md"),
           *items.rulings(tmp_path / "rules.md"), *items.defects(tmp_path / "n.jsonl")]
    by = {i.id: i for i in got}
    assert by["T-219"].links == ["I-006"] and by["T-219"].is_open
    assert by["I-006"].review_by == "2026-11-16" and by["I-006"].tags == ["extraction-design"]
    assert by["RUL-how-we-work-1"].links == ["T-219"] and by["RUL-how-we-work-1"].opened == "16 Nov"
    assert by["R-005"].links == ["T-218"] and not by["R-005"].is_open
    assert [i.id for i in items.due(got, "2026-11-16")] == ["I-006"]
    md, xlsx = items.render(got, tmp_path / "ITEMS.md", tmp_path / "items.xlsx")
    assert "**T-219** [open] Unified items — links: I-006 (parked)" in md.read_text(encoding="utf-8")
    assert xlsx.is_file()
