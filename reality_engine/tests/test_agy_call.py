"""T-205 round 13: one agy run through agy_call, on a fake agy binary (the real one is never called in tests)."""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reality_engine.answer import agy_call  # noqa: E402

FAKE = textwrap.dedent('''
    import json, os, sys
    argv = sys.argv[1:]
    model = argv[argv.index("--model") + 1] if "--model" in argv else "?"
    mode = os.environ.get("FAKE_AGY_MODE", "ok")
    state = os.environ.get("FAKE_AGY_STATE")
    if mode != "ok":
        n = int(open(state).read() or "0") if state and os.path.exists(state) else 0
        if state:
            open(state, "w").write(str(n + 1))
        if mode == "flaky" and n == 0:
            sys.exit(3)
    print(json.dumps({"event": "init", "init": {"model": model, "conversation_id": "conv-1"}}))
    print(json.dumps({"event": "step_update", "step_update": {"state": "DONE", "step_type": "tool",
        "tool_name": "mcp_reality-data_pilot3_fact"}}))
    print(json.dumps({"event": "step_update", "step_update": {"state": "DONE", "step_type": "tool",
        "tool_name": "view_file"}}))
    print(json.dumps({"event": "step_update", "step_update": {"state": "DONE", "step_type": "agent_response",
        "usage": {"input_tokens": 100, "output_tokens": 7}}}))
    print(json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": "THE ANSWER"}}))
    if mode == "answer_then_fail":
        sys.exit(1)
''')


def _fake(tmp_path: Path) -> list[str]:
    script = tmp_path / "fake_agy.py"
    script.write_text(FAKE, encoding="utf-8")
    return [sys.executable, str(script)]


def test_run_agy_parses_text_tools_and_tokens(tmp_path, monkeypatch):
    out = agy_call.run_agy("hello", "gemini-4-hydrogen-high", cwd=tmp_path, agy=_fake(tmp_path),
                           log_path=tmp_path / "log.jsonl")
    assert out["ok"] and out["text"] == "THE ANSWER"
    assert out["tools"] == {"pilot3_fact": 1, "view_file": 1}
    assert out["data_tool_calls"] == 1
    assert out["tokens"]["input_tokens"] == 100 and out["attempts"] == 1
    assert Path(out["log"]).is_file() and out["status"] == "SUCCESS"


def test_retry_once_on_transport_error_then_succeed(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_MODE", "flaky")
    monkeypatch.setenv("FAKE_AGY_STATE", str(tmp_path / "state.txt"))
    out = agy_call.run_agy("hello", "gemini-4-hydrogen-high", cwd=tmp_path, agy=_fake(tmp_path),
                           log_path=tmp_path / "log.jsonl")
    assert out["ok"] and out["attempts"] == 2 and out["text"] == "THE ANSWER"


def test_a_model_answer_is_never_retried(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_AGY_MODE", "answer_then_fail")
    monkeypatch.setenv("FAKE_AGY_STATE", str(tmp_path / "state.txt"))
    out = agy_call.run_agy("hello", "gemini-4-hydrogen-high", cwd=tmp_path, agy=_fake(tmp_path),
                           log_path=tmp_path / "log.jsonl")
    assert out["ok"] and out["attempts"] == 1 and out["text"] == "THE ANSWER"
    assert Path(tmp_path / "state.txt").read_text() == "1"


def test_missing_binary_is_one_error_no_attempt(tmp_path):
    out = agy_call.run_agy("hello", "gemini-4-hydrogen-high", cwd=tmp_path, agy=tmp_path / "nope.exe")
    assert not out["ok"] and out["attempts"] == 0 and "agy not found" in out["error"]


def test_long_prompt_goes_to_a_file_and_leaves_a_pointer(tmp_path):
    prompt = "x" * (agy_call.MAX_PROMPT_CHARS + 100)
    fitted = agy_call._fit_prompt(prompt, tmp_path)
    assert len(fitted) < 1000 and "Read that file first" in fitted
    files = list((tmp_path / ".tmp" / "agy_prompts").glob("*.txt"))
    assert len(files) == 1 and files[0].read_text() == prompt


def test_client_merges_tools_and_raises_on_transport_error(tmp_path):
    def fake_run(prompt, model, **kwargs):
        return {"ok": True, "text": '{"answer": "x"}', "tools": {"pilot3_fin": 2}, "data_tool_calls": 2,
                "tokens": {"input_tokens": 5, "output_tokens": 1}, "status": "SUCCESS"}
    client = agy_call.client_for("agy:gemini-4-hydrogen-high", runner=fake_run)
    reply = client("sys", "user")
    assert reply["content"] == '{"answer": "x"}' and reply["in_tok"] == 5
    assert client.tools == {"pilot3_fin": 2} and client.data_tool_calls["data"] == 2

    def broken(*_a, **_k):
        return {"ok": False, "error": "agy exited 3 with no final response"}
    try:
        agy_call.client_for("agy:x", runner=broken)("s", "u")
    except RuntimeError as exc:
        assert "no final response" in str(exc)
    else:
        raise AssertionError("transport failure did not raise")


def test_last_json_reads_the_last_object(tmp_path):
    text = 'thinking... {"a": 1} then {"qid": "BS-1", "label": "A", "grade": "right", "note": "x {y}"}'
    assert agy_call.last_json(text) == {"qid": "BS-1", "label": "A", "grade": "right", "note": "x {y}"}
    assert agy_call.last_json("no json here") is None
    assert agy_call.model_id("agy:gemini-4-hydrogen-high") == "gemini-4-hydrogen-high"
    assert agy_call.is_agy_model("agy:x") and not agy_call.is_agy_model("gemini-4-hydrogen-high")
