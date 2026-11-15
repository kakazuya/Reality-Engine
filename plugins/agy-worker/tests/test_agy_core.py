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


def test_model_allowlist_refuses_anything_else(tmp_path, monkeypatch):
    """T-205 round 13: start and resume take an allowlisted model, never a silent pin."""
    assert agy_core.MODELS["gemini-4-hydrogen-high"] and agy_core.MODELS["claude-opus-5-5-medium"]
    refused = agy_core.start("brief", use_worktree=False, model="gpt-9-ultra")
    assert refused["ok"] is False and "allowlisted" in refused["error"]
    assert agy_core.check_model(agy_core.MODEL) is None
    # Shivam 14 Nov: Argon high first (never xhigh/max), Hydrogen high after; 16 Nov: Flash 3.8 medium stays allowed
    assert agy_core.MODEL == "gemini-4-argon-high" and "gemini-4-hydrogen-high" in agy_core.MODELS
    assert agy_core.check_model("gemini-4-argon-medium") is not None and agy_core.check_model("gemini-4-hydrogen-xhigh") is not None
    assert agy_core.check_model("gemini-3.8-flash-medium") is None and agy_core.check_model("gemini-3.8-flash-high") is not None
    monkeypatch.setattr(agy_core, "RUNTIME", tmp_path / "rt_model")
    assert agy_core.current_model() == agy_core.MODEL                      # no file: the default
    assert agy_core.set_current_model("gpt-9-ultra") is not None and agy_core.current_model() == agy_core.MODEL
    assert agy_core.set_current_model("gemini-3.8-flash-medium") is None
    assert agy_core.current_model() == "gemini-3.8-flash-medium"           # the model Shivam named is used

    monkeypatch.setattr(agy_core, "RUNTIME", tmp_path / "runtime")
    job = agy_core.job_dir("20261113T000000Z-abcdef01")
    job.mkdir(parents=True)
    (job / "job.json").write_text(json.dumps({"job_id": "20261113T000000Z-abcdef01", "model": agy_core.MODEL}),
                                  encoding="utf-8")
    (job / "events.jsonl").write_text(json.dumps({"event": "init", "init": {"conversation_id": "c1"}}) + "\n",
                                      encoding="utf-8")
    (job / "exit.json").write_text(json.dumps({"outcome": "completed"}), encoding="utf-8")
    refused = agy_core.resume("20261113T000000Z-abcdef01", "more", model="gemini-9-nope")
    assert refused["ok"] is False and "allowlisted" in refused["error"]
