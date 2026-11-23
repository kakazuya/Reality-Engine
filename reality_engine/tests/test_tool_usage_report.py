"""Fixture test for the tool-usage report.

Builds one tiny transcript per source in a temp tree and checks the parts that are easy
to get wrong: one API message split over several lines (usage counted once, every
tool_use kept), shell classification by the first operation, and the OpenCode snapshot.

Runs under ``python -m unittest`` and is collected unchanged by pytest.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import unittest
import uuid

from reality_engine.scripts import tool_usage_report as R


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _fixture(root):
    dsh = os.path.join(root, "dsh")
    claude = os.path.join(root, "claude")
    oc = os.path.join(root, "opencode")
    codex = os.path.join(root, "codex")

    job = os.path.join(dsh, "20260101T000000Z-aaaaaaaa")
    events = [
        {"type": "session", "sessionId": "s", "cwd": "c"},
        {"type": "thinking", "text": "x" * 400},
        {"type": "tool_call", "callId": "c1", "tool": "pwsh",
         "input": {"command": "Get-Content notes.txt -Tail 5"}},
        {"type": "tool_call", "callId": "c2", "tool": "pwsh",
         "input": {"command": 'python -c "import sqlite3; print(1)"'}},
        {"type": "tool_result", "callId": "c1", "status": "completed", "result": "a" * 80},
        {"type": "tool_result", "callId": "c2", "status": "error", "result": "boom"},
        {"type": "thinking", "text": "y" * 100},
        {"type": "tool_call", "callId": "c3", "tool": "read",
         "input": {"file_path": "reality_engine/x.py"}},
        {"type": "tool_call", "callId": "c4", "tool": "edit",
         "input": {"file_path": "reality_engine/x.py", "old_string": "a", "new_string": "b"}},
        {"type": "tool_result", "callId": "c3", "status": "completed", "result": "1: x\n2: y\n"},
        {"type": "tool_result", "callId": "c4", "status": "completed", "result": "ok"},
        {"type": "final", "text": "done"},
    ]
    _write(os.path.join(job, "result.md.events.jsonl"),
           "\n".join(json.dumps(e) for e in events) + "\n")
    _write(os.path.join(job, "status.json"), json.dumps({
        "started_at": "2026-01-01T00:00:00+00:00", "finished_at": "2026-01-01T00:30:00+00:00",
        "outcome": "completed", "tool_calls_before_first_edit": 3,
        "first_edit_at": "2026-01-01T00:10:00+00:00"}))
    _write(os.path.join(job, "progress.jsonl"), json.dumps({
        "output_tokens": 1000, "model_steps": 4, "tool_calls": 4,
        "input_tokens": 2000, "cache_read_tokens": 50000, "batched_read_steps": 3,
        "tool_calls_before_first_edit": 3}) + "\n")

    ledger = os.path.join(root, "ledger.jsonl")
    _write(ledger, "\n".join(json.dumps(e) for e in (
        {"ts": "2026-01-01T00:05:00+00:00", "provider": "opencode-go",
         "model": "beam-free", "in_tok": 100, "out_tok": 10, "usd": 0.0,
         "purpose": "", "job_id": "", "caller": "nid_beam_preread"},
        {"ts": "2026-01-01T00:06:00+00:00", "provider": "opencode-go",
         "model": "deepseek-v4.1-flash", "in_tok": 300, "out_tok": 30, "usd": 0.01,
         "purpose": "", "job_id": "", "caller": "concall_pilot"},
    )) + "\n")

    lines = []
    # one API message over three lines with the same id: usage once, both tools kept
    for block in (
        {"type": "thinking", "thinking": ""},
        {"type": "tool_use", "id": "t1", "name": "Bash",
         "input": {"command": "cat a.log | head -3"}},
        {"type": "tool_use", "id": "t2", "name": "Read",
         "input": {"file_path": "reality_engine/y.py", "limit": 40, "offset": 1}},
    ):
        lines.append(json.dumps({
            "type": "assistant", "timestamp": "2026-01-02T00:00:00+00:00",
            "message": {"id": "msg_1", "model": "m", "role": "assistant",
                        "content": [block],
                        "usage": {"input_tokens": 10, "output_tokens": 100,
                                  "cache_read_input_tokens": 5000,
                                  "cache_creation_input_tokens": 20,
                                  "output_tokens_details": {"thinking_tokens": 40}}}}))
    lines.append(json.dumps({"type": "user", "timestamp": "2026-01-02T00:00:05+00:00",
                             "message": {"role": "user", "content": [
                                 {"type": "tool_result", "tool_use_id": "t1",
                                  "content": [{"type": "text", "text": "z" * 50}]},
                                 {"type": "tool_result", "tool_use_id": "t2",
                                  "content": "q" * 70, "is_error": False}]}}))
    lines.append(json.dumps({"type": "agent-name", "agentName": "sv-fixture"}))
    _write(os.path.join(claude, "proj", "sess.jsonl"), "\n".join(lines) + "\n")

    os.makedirs(oc, exist_ok=True)
    conn = sqlite3.connect(os.path.join(oc, "opencode.db"))
    conn.execute("create table session_v2 (id text, title text, model text, cost real,"
                 " tokens_input int, tokens_output int, tokens_reasoning int,"
                 " tokens_cache_read int, tokens_cache_write int, time_created int,"
                 " time_updated int, parent_id text, agent text)")
    conn.execute("create table session_message (id text, session_id text, type text,"
                 " seq int, time_created int, time_updated int, data text)")
    conn.execute("insert into session_v2 values ('s1','fixture','{\"id\":\"m\"}',0.01,"
                 "10,20,5,30,0,1767225600000,1767225660000,null,null)")
    conn.execute("insert into session_message values ('m1','s1','assistant',1,0,0,?)",
                 (json.dumps({"content": [{"type": "text", "text": "hi"}],
                              "tokens": {"output": 20, "reasoning": 5}}),))
    conn.commit()
    conn.close()
    return {"dsh": dsh, "claude": claude, "opencode": oc, "codex": codex}, ledger


class ClassifyTests(unittest.TestCase):
    def test_rules(self):
        cases = {
            "Get-Content a.log -Tail 3": R.SH_READ,
            "cat a.log | head -3": R.SH_READ,
            "Get-Content a.log | Select-String x": R.SH_SEARCH,
            "Get-ChildItem x -Recurse; Get-Content y": R.SH_LIST,
            'python -c "import sqlite3; print(1)"': R.PY_DB,
            "python -m unittest reality_engine.tests.test_x": R.TESTS,
            "python tasks/answer_bench/run_bench.py 1": R.BENCH,
            "cat >> notes.md <<'EOF'\nhi\nEOF": R.EDIT,
            "git status --short": R.GIT,
            "git grep -n x": R.SH_SEARCH,
            "Start-Sleep -Seconds 5; Get-Content a.log": R.SLEEP,
            "Get-Process python -ErrorAction SilentlyContinue": R.SH_LIST,
            "python -m py_compile a.py; @'\nimport sqlite3\n'@": R.TESTS,
        }
        for cmd, want in cases.items():
            self.assertEqual(R.classify_shell(cmd), want, cmd)

    def test_redaction(self):
        self.assertEqual(R.redact("key sk-abcdefgh12345678 Bearer abcdefghijklmnop"),
                         "key <redacted> <redacted>")


class ReportTests(unittest.TestCase):
    def test_fixture(self):
        os.makedirs(".tmp", exist_ok=True)
        # mkdtemp's restrictive DACL blocks child creation in this sandbox
        tmp = os.path.join(".tmp", "tur_" + uuid.uuid4().hex[:8])
        os.makedirs(tmp, exist_ok=True)
        try:
            roots, ledger = _fixture(tmp)
            rep = R.build(roots, None, tmp, None, set(), ledger)

            claude = rep["sources"]["claude"]
            # one message id over three lines: one step, usage once, both calls kept
            self.assertEqual(claude["steps"], 1)
            self.assertEqual(claude["calls_n"], 2)
            sess = rep["_raw"]["claude"]["sessions"]["proj/sess.jsonl"]
            self.assertEqual(sess["out"], 100)
            self.assertEqual(sess["cache_read"], 5000)
            self.assertEqual(sess["thinking"], 40)
            self.assertEqual(sess["name"], "sv-fixture")
            self.assertEqual(sorted(c["cls"] for c in sess["calls"]),
                             [R.PY_RANGED, R.SH_READ])
            self.assertEqual([c["chars"] for c in sess["calls"]], [50, 70])

            dsh = rep["sources"]["dsh"]
            self.assertEqual(dsh["calls_n"], 4)
            self.assertEqual(dsh["failures"], 1)
            self.assertEqual(dsh["provider_out"], 1000)
            # provider input split and the batching counter come from the digest
            self.assertEqual((dsh["provider_in"], dsh["cache_read"]), (2000, 50000))
            self.assertEqual(dsh["batched_read_steps"], 3)
            self.assertEqual(dsh["wall_seconds"], 1800.0)
            dsess = rep["_raw"]["dsh"]["sessions"]["20260101T000000Z-aaaaaaaa"]
            self.assertEqual([c["cls"] for c in dsess["calls"]],
                             [R.SH_READ, R.PY_DB, R.PY_WHOLE, R.EDIT])
            self.assertEqual(dsess["before_first_edit"], 3)
            self.assertEqual(dsess["seconds_to_first_edit"], 600)

            ledger_view = rep["ledger"]
            self.assertEqual(ledger_view["entries"], 2)
            self.assertEqual((ledger_view["in_tok"], ledger_view["out_tok"]), (400, 40))
            self.assertEqual(sorted(ledger_view["by_caller"]),
                             ["concall_pilot", "nid_beam_preread"])

            # --exclude-jobs leaves the job out; --until cuts by start time
            excluded = R.build(roots, None, tmp, None, {"20260101T000000Z-aaaaaaaa"}, ledger)
            self.assertEqual(excluded["sources"]["dsh"]["sessions_n"], 0)
            cut = R.build(roots, None, tmp, R._ts("2026-01-01T00:00:00+00:00"), set(), ledger)
            self.assertEqual(cut["sources"]["dsh"]["sessions_n"], 0)
            self.assertEqual(cut["ledger"]["entries"], 0)

            cmp = R.comparison(rep, rep)
            self.assertEqual(len(cmp["metrics"]), len(R.COMPARISON_METRICS))
            for row in cmp["metrics"]:
                if row["baseline"]:   # a zero baseline has no meaningful percentage
                    self.assertEqual(row["relative_delta"], 0.0)
            self.assertIsNone(R._rate(0, 0))

            oc = rep["sources"]["opencode"]
            self.assertEqual((oc["sessions_n"], oc["calls_n"]), (1, 0))
            self.assertEqual((oc["provider_out"], oc["thinking"]), (20, 5))
            self.assertFalse(rep["sources"]["codex"]["present"])

            self.assertEqual(rep["waste"]["b"]["count"], 2)   # `cat` + `Get-Content`
            self.assertEqual(rep["waste"]["c"]["count"], 1)   # inline sqlite query
            md = R.render_md({k: v for k, v in rep.items() if k != "_raw"})
            self.assertIn("Headline per source", md)
            self.assertIn("| codex | ABSENT |", md)
            self.assertIn("Direct API ledger", md)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
