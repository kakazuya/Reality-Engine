"""T-112: agy-worker parses an agy stream-json log and agy-tools only runs allowlisted commands."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import agy_core  # noqa: E402
import agy_tools_mcp  # noqa: E402


def test_parse_events_counts_tools_tokens_and_final(tmp_path):
    rows = [
        {"event": "init", "init": {"model": "gemini-3.8-flash-medium"}},
        {"event": "step_update", "step_update": {"state": "DONE", "step_type": "tool", "tool_name": "view_file",
                                                 "tool_info": {"parameters": {"Path": "a.py"}}}},
        {"event": "step_update", "step_update": {"state": "DONE", "step_type": "tool", "tool_name": "call_mcp_tool",
                                                 "tool_info": {"parameters": {"ServerName": "agy-tools",
                                                                              "ToolName": "run_check"}}}},
        {"event": "step_update", "step_update": {"state": "DONE", "step_type": "agent_response",
                                                 "usage": {"input_tokens": 100, "output_tokens": 7}}},
        {"event": "step_update", "step_update": {"state": "DONE", "step_type": "agent_response",
                                                 "usage": {"input_tokens": 50, "output_tokens": 3}}},
        {"status": "SUCCESS", "response": "done", "usage": {"total_tokens": 160}},
    ]
    p = tmp_path / "events.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
    out = agy_core.parse_events(p)
    assert out["tool_calls"] == 2
    assert out["tool_calls_by_tool"] == {"view_file": 1, "mcp:agy-tools/run_check": 1}
    assert out["tokens"]["output_tokens"] == 10 and out["tokens"]["input_tokens"] == 150
    assert out["response"] == "done" and out["final_status"] == "SUCCESS"


def test_run_check_allowlist():
    assert agy_tools_mcp.allowed(["python", "-m", "pytest", "x"])
    assert agy_tools_mcp.allowed(["git", "diff"])
    assert not agy_tools_mcp.allowed(["python", "-c", "print(1)"])
    assert not agy_tools_mcp.allowed(["git", "push"])
    assert agy_tools_mcp.run_check("python -m pytest | rm x")["error"] == "not allowed"
    assert agy_tools_mcp.run_check("del x")["error"] == "not allowed"


def test_bad_job_id_rejected():
    try:
        agy_core.job_dir("../x")
    except ValueError:
        return
    raise AssertionError("path traversal accepted")


def test_runner_marks_job_json_ended(tmp_path):
    """T-200: job.json phase follows exit.json, so a watcher keyed on job.json sees the end."""
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
    import runner
    (tmp_path / "job.json").write_text(json.dumps({"job_id": "x", "phase": "running"}), encoding="utf-8")
    runner.mark_ended(tmp_path, {"outcome": "completed", "ended_at": "2026-11-12T18:00:00+00:00"})
    job = json.loads((tmp_path / "job.json").read_text(encoding="utf-8"))
    assert job["phase"] == "ended" and job["outcome"] == "completed"
