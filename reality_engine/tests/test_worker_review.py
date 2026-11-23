"""Fixture tests for the worker-review log.

Builds tiny job directories and Claude transcripts in a temp tree and checks the parts
the log must not get wrong: Claude usage counted once per message id (and the two project
roots read once), a brief with no ``Budget:`` line, a job with no review shown as
``review due``, the thinking estimate labelled as one (and a provider reasoning count
winning over it), and the gap between the worker's self-reported call count and the
measured one.

Runs under ``python -m unittest`` and is collected unchanged by pytest.
"""
from __future__ import annotations

import json
import os
import shutil
import unittest
import uuid
from types import SimpleNamespace

from reality_engine.scripts import worker_review as W

REPO_NAME = "Info_Diffusion_Model"


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _events(self_report="≈9 tool calls total", thinking_chars=400):
    events = [
        {"type": "session", "sessionId": "s", "cwd": "c"},
        {"type": "thinking", "text": "x" * thinking_chars},
        {"type": "tool_call", "callId": "c1", "tool": "read",
         "input": {"file_path": "a.py"}},
        {"type": "tool_result", "callId": "c1", "status": "completed", "result": "ok"},
        {"type": "tool_call", "callId": "c2", "tool": "read",
         "input": {"file_path": "a.py"}},
        {"type": "tool_result", "callId": "c2", "status": "completed", "result": "ok"},
        {"type": "tool_call", "callId": "c3", "tool": "write",
         "input": {"file_path": "b.py", "content": "x"}},
        {"type": "tool_result", "callId": "c3", "status": "completed", "result": "ok"},
        {"type": "tool_call", "callId": "c4", "tool": "edit",
         "input": {"file_path": "a.py", "old_string": "a", "new_string": "b"}},
        {"type": "tool_result", "callId": "c4", "status": "completed", "result": "ok"},
        {"type": "tool_call", "callId": "c5", "tool": "grep", "input": {"pattern": "x"}},
        {"type": "tool_result", "callId": "c5", "status": "error", "result": "boom"},
        {"type": "final", "text": self_report},
    ]
    return events


def _job(root, name="20260101T000000Z-aaaaaaaa", budget="Budget: 90 tool calls in total, "
         "20 before the first edit.", provider_thinking=None, self_report="≈9 tool calls total",
         thinking_chars=400):
    job = os.path.join(root, "jobs", name)
    lines = "\n".join(json.dumps(e) for e in _events(self_report, thinking_chars)) + "\n"
    _write(os.path.join(job, "result.md.events.jsonl"), lines)
    _write(os.path.join(job, "result.md"), f"Done.\n\n5) **{self_report}**\n")
    _write(os.path.join(job, "status.json"), json.dumps({
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:30:00+00:00",
        "outcome": "completed", "tool_calls_before_first_edit": 2,
        "orientation_seconds": 12.5,
    }))
    _write(os.path.join(job, "job.json"), json.dumps({
        "host": "hp", "model": "deepseek-v4.1-flash", "effort": "max",
        "permission": "workspace-write", "write_scope": "workspace",
        "repo_root": os.path.join(root, REPO_NAME),
    }))
    progress = {"input_tokens": 1000, "cache_read_tokens": 5000, "output_tokens": 1000,
                "model_steps": 7, "tool_calls": 5, "tool_calls_before_first_edit": 2}
    if provider_thinking is not None:
        progress["reasoning_tokens"] = provider_thinking
    _write(os.path.join(job, "progress.jsonl"), json.dumps(progress) + "\n")
    brief = "Goal: measure the fleet.\nTicket: T-043\n"
    if budget:
        brief += budget + "\n"
    _write(os.path.join(job, "brief.md"), brief)
    return job


def _transcript(projects_root, repo_root, session="dc906972-2832-4ba9-844d-38c4fcbc7b39"):
    """One API message split over three lines (same id) plus its tool results."""
    usage = {"input_tokens": 10, "cache_read_input_tokens": 100,
             "cache_creation_input_tokens": 50, "output_tokens": 40,
             "output_tokens_details": {"thinking_tokens": 7}}
    project = os.path.join(projects_root, W._encode_project(repo_root))

    def line(content):
        return {"type": "assistant", "timestamp": "2026-01-01T00:00:00+00:00",
                "message": {"id": "msg_1", "model": "claude-x", "usage": usage,
                            "content": content}}

    rows = [
        {"type": "custom-title", "customTitle": "neo-" + REPO_NAME,
         "sessionId": session},
        line([{"type": "text", "text": "hello"}]),
        line([{"type": "tool_use", "id": "t1", "name": "Read",
               "input": {"file_path": "a.py"}}]),
        line([{"type": "tool_use", "id": "t2", "name": "Grep",
               "input": {"pattern": "x"}}]),
        {"type": "user", "timestamp": "2026-01-01T00:01:00+00:00",
         "message": {"content": [
             {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
             {"type": "tool_result", "tool_use_id": "t2", "content": "ok"}]}},
    ]
    path = os.path.join(project, session + ".jsonl")
    _write(path, "\n".join(json.dumps(r) for r in rows) + "\n")
    return project


class WorkerReviewTest(unittest.TestCase):
    def setUp(self):
        # A plain directory under .tmp: tempfile.mkdtemp() writes a 0700 ACL that the
        # Windows sandbox refuses to descend into, so fixtures are made here instead.
        self.root = os.path.join(os.getcwd(), ".tmp",
                                 "worker_review_test_" + uuid.uuid4().hex)
        os.makedirs(self.root, exist_ok=True)
        self.repo = os.path.join(self.root, REPO_NAME)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_usage_counted_once_per_message_id(self):
        project = _transcript(os.path.join(self.root, "projects"), self.repo)
        projects_root = os.path.dirname(project)
        rows = W.read_claude_sessions([projects_root, projects_root], self.repo)
        self.assertEqual(len(rows), 1)                      # junction/file counted once
        row = rows[0]
        self.assertEqual(row["output_tokens"], 40)          # not 3 x 40
        self.assertEqual(row["input_tokens"], 10)
        self.assertEqual(row["cache_creation_tokens"], 50)
        self.assertEqual(row["steps"], 1)
        self.assertEqual(row["tool_calls_total"], 2)
        self.assertEqual(row["calls_read"], 1)
        self.assertEqual(row["calls_grep"], 1)
        self.assertEqual(row["account"], "neo")

    def test_job_without_budget_line(self):
        job = _job(self.root, budget="")
        row = W.read_job(job)
        self.assertIsNone(row["budget_total"])
        self.assertIsNone(row["budget_before_first_edit"])
        self.assertIsNone(row["over_budget_total"])
        self.assertIsNone(row["over_budget_before_first_edit"])

    def test_unreviewed_job_shows_review_due(self):
        job = _job(self.root)
        row = W.read_job(job)
        self.assertEqual(row["job_type"], "")
        rows = W.review_rows([row], [], {})
        self.assertEqual(rows[0]["review_status"], "review due")
        self.assertEqual(rows[0]["job_type"], "")

    def test_thinking_estimate_is_labelled(self):
        job = _job(self.root, thinking_chars=400)
        row = W.read_job(job)
        self.assertIsNone(row["thinking_tokens"])           # no provider count in the record
        self.assertEqual(row["thinking_tokens_est"], 100)   # 400 chars / 4
        self.assertEqual(row["output_tokens_excl_thinking_est"], 900)
        headers = [header for header, _ in W.WORKER_COLUMNS]
        self.assertIn("thinking_tokens_est", headers)
        self.assertEqual(row["calls_before_first_edit_events"], 2)  # the write is an edit
        self.assertEqual(row["calls_before_first_edit_status"], 2)

    def test_provider_reasoning_wins_over_estimate(self):
        job = _job(self.root, provider_thinking=55, thinking_chars=400)
        row = W.read_job(job)
        self.assertEqual(row["thinking_tokens"], 55)
        self.assertIsNone(row["thinking_tokens_est"])
        self.assertEqual(row["output_tokens_excl_thinking_est"], 945)

    def test_self_report_gap_is_computed(self):
        job = _job(self.root, self_report="≈9 tool calls total")
        row = W.read_job(job)
        self.assertEqual(row["tool_calls_actual"], 5)
        self.assertEqual(row["self_reported_tool_calls"], 9)
        self.assertEqual(row["self_report_gap"], -4)        # 5 measured - 9 reported

    def test_session_review_id_joins_the_bare_uuid(self):
        session = {"session_id": "abc", "model": "claude-x", "outcome": "",
                   "tool_calls_actual": 2, "calls_before_first_edit": 1,
                   "output_tokens": 10, "minutes": 1.0, "changed_files": None}
        rows = W.review_rows([], [session], {"session-abc": {"id": "session-abc",
                                                             "job_type": "review"}})
        self.assertEqual(len(rows), 1)                     # not an extra review-only row
        self.assertEqual(rows[0]["review_status"], "reviewed")
        self.assertEqual(rows[0]["job_type"], "review")

    def test_build_writes_the_four_sheets(self):
        job = _job(self.root)
        _transcript(os.path.join(self.root, "projects"), self.repo)
        reviews = os.path.join(self.root, "worker_reviews.jsonl")
        _write(reviews, json.dumps({"id": os.path.basename(job), "job_type": "measure",
                                    "prompt_change": "shorter"}) + "\n")
        out = os.path.join(self.root, "log.xlsx")
        W.build(SimpleNamespace(out=out, jobs_root=os.path.join(self.root, "jobs"),
                                reviews=reviews, repo_root=self.repo,
                                claude_roots=[os.path.join(self.root, "projects")]))
        from openpyxl import load_workbook
        book = load_workbook(out)
        self.assertEqual(book.sheetnames, ["Workers", "Claude", "Reviews", "Trends"])
        workers = list(book["Workers"].values)
        header = list(workers[0])
        self.assertEqual(workers[1][header.index("job_type")], "measure")
        reviews_sheet = list(book["Reviews"].values)
        self.assertEqual(reviews_sheet[1][list(reviews_sheet[0]).index("review_status")],
                         "reviewed")


if __name__ == "__main__":
    unittest.main()
