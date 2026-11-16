"""T-219: one view over tickets, ideas, rulings and store defects, and their GitHub Issues mirror."""
from __future__ import annotations

import json
from types import SimpleNamespace

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


class FakeRun:
    """A subprocess.run stand-in: records every argv list and answers with a fixed stdout."""

    def __init__(self, stdout: str = "[]") -> None:
        self.calls: list[list[str]] = []
        self.stdout = stdout

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        return SimpleNamespace(returncode=0, stdout=self.stdout, stderr="")


def _item(id="T-219", kind="ticket", status="open", title="Unified items", **fields):
    return items.Item(kind, id, status, title, **fields)


def _issue(item, number=7, state="OPEN", title=None, body=None):
    return {"number": number, "title": f"{item.id}: {item.title}" if title is None else title,
            "body": items.issue_body(item) if body is None else body, "state": state, "labels": []}


def test_plan_creates_one_issue_for_a_new_open_ticket():
    it = _item(why="four trackers become patchwork", tags=["workspace", "P1", ""],
               links=["I-006"], source="tasks/tickets.jsonl", opened="2026-11-16")
    assert items.github_plan([it], []) == [{
        "action": "create", "id": "T-219", "title": "T-219: Unified items", "body": items.issue_body(it),
        "labels": ["item:ticket"]}]
    body = items.issue_body(it)
    assert body.splitlines()[0] == "<!-- item:T-219 -->"
    assert "four trackers become patchwork" in body and "- Tags: workspace, P1" in body
    assert "- Links: I-006" in body and "- Source: tasks/tickets.jsonl" in body
    assert "- Opened: 2026-11-16" in body


def test_plan_is_empty_when_the_issue_already_matches():
    it = _item()
    assert items.github_plan([it], [_issue(it)]) == []


def test_plan_edits_a_retitled_issue():
    it = _item()
    plan = items.github_plan([it], [_issue(it, title="T-219: Old name")])
    assert plan == [{"action": "edit", "id": "T-219", "number": 7, "title": "T-219: Unified items",
                     "body": items.issue_body(it)}]


def test_plan_reopens_and_edits_a_closed_issue_whose_item_is_open():
    it = _item()
    plan = items.github_plan([it], [_issue(it, state="CLOSED")])
    assert plan == [{"action": "edit", "id": "T-219", "number": 7, "title": "T-219: Unified items",
                     "body": items.issue_body(it), "reopen": True}]


def test_plan_closes_issues_whose_item_is_done_or_missing():
    done = _item(status="done")
    old = _item(id="T-200", title="Old ticket")
    plan = items.github_plan([done], [_issue(done), _issue(old, number=12)])
    assert plan == [{"action": "close", "id": "T-219", "number": 7},
                    {"action": "close", "id": "T-200", "number": 12}]


def test_plan_never_mirrors_ideas_or_rulings():
    idea = _item(id="I-006", kind="idea", status="parked", title="Typed replies")
    ruling = _item(id="RUL-how-we-work-1", kind="ruling", status="active", title="Tools local")
    assert items.github_plan([idea, ruling], []) == []


def test_apply_creates_both_labels_first_then_runs_list_argv():
    defect = _item(id="R-005", kind="defect", title="Lakh as crore")
    plan = items.github_plan([_item(), defect], [])
    run = FakeRun()
    items.github_apply(plan, run)
    assert run.calls[:2] == [["gh", "label", "create", "item:ticket", "--force"],
                             ["gh", "label", "create", "item:defect", "--force"]]
    assert run.calls[2][:4] == ["gh", "issue", "create", "--title"]
    assert run.calls[2][4] == "T-219: Unified items"
    assert run.calls[2][-2:] == ["--label", "item:ticket"]
    assert run.calls[3][-1] == "item:defect"
    assert all(isinstance(call, list) for call in run.calls)


def test_apply_reopens_before_editing_and_closes():
    it = _item()
    plan = items.github_plan([it], [_issue(it, state="CLOSED")])
    plan.append({"action": "close", "id": "T-200", "number": 12})
    run = FakeRun()
    items.github_apply(plan, run)
    reopen = run.calls.index(["gh", "issue", "reopen", "7"])
    edited = run.calls.index(["gh", "issue", "edit", "7", "--title", "T-219: Unified items",
                              "--body", items.issue_body(it)])
    assert reopen < edited
    assert ["gh", "issue", "close", "12"] in run.calls


def test_github_dry_run_reads_the_list_and_applies_nothing(capsys):
    it = _item()
    run = FakeRun(stdout=json.dumps([_issue(it)]))
    assert items.github([it], run=run) == 0
    assert run.calls == [items.GH_LIST]
    assert "already mirrors" in capsys.readouterr().out

