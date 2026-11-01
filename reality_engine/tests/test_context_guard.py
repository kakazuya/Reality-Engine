"""The 400k/440k wrap-up hook: one message per threshold, silent below, never fatal."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(FIXTURES))

from dsh_worker_testenv import make_temp_dir, remove_tree  # noqa: E402

from reality_engine.scripts import context_guard  # noqa: E402

SCRIPT = Path(context_guard.__file__)
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def tmp_path():
    """A sandbox-safe temp root: inherited ACL, unlike tempfile's mode-0700 dir."""
    path = make_temp_dir(REPO / ".tmp" / "context-guard-tests", "guard-")
    yield path
    remove_tree(path)


def _transcript(path: Path, *usages: tuple[int, int, int]) -> Path:
    lines = []
    for input_tokens, read_tokens, created_tokens in usages:
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"usage": {
                "input_tokens": input_tokens,
                "cache_read_input_tokens": read_tokens,
                "cache_creation_input_tokens": created_tokens,
            }},
        }))
    lines.append(json.dumps({"type": "user", "message": {"content": "next"}}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_silent_below_400k_and_fires_once_there(tmp_path):
    transcript = _transcript(tmp_path / "t.jsonl", (200_000, 199_999, 0))
    assert context_guard.last_token_usage(transcript) == 399_999
    assert context_guard.evaluate(399_999, "s1", tmp_path) is None
    transcript = _transcript(tmp_path / "t.jsonl", (200_000, 200_000, 0))
    first = context_guard.evaluate(400_000, "s1", tmp_path)
    assert first and "400,000" in first and "tasks/STATE.md" in first
    assert context_guard.evaluate(405_000, "s1", tmp_path) is None, "once per session"


def test_fires_once_more_at_440k(tmp_path):
    assert "400,000" in context_guard.evaluate(400_000, "s2", tmp_path)
    second = context_guard.evaluate(440_000, "s2", tmp_path)
    assert second and "440,000" in second
    assert context_guard.evaluate(445_000, "s2", tmp_path) is None


def test_a_session_first_seen_at_440k_gets_only_the_urgent_message(tmp_path):
    assert "440,000" in context_guard.evaluate(440_000, "s3", tmp_path)
    assert context_guard.evaluate(445_000, "s3", tmp_path) is None


def test_only_the_last_assistant_message_counts(tmp_path):
    transcript = _transcript(tmp_path / "t.jsonl", (900_000, 0, 0), (100, 200, 300))
    assert context_guard.last_token_usage(transcript) == 600


def test_missing_or_garbage_transcript_is_none(tmp_path):
    assert context_guard.last_token_usage(tmp_path / "missing.jsonl") is None
    garbage = tmp_path / "garbage.jsonl"
    garbage.write_text("not json\n{oops\n", encoding="utf-8")
    assert context_guard.last_token_usage(garbage) is None


def test_hook_exits_zero_and_prints_the_payload(tmp_path):
    transcript = _transcript(tmp_path / "t.jsonl", (380_000, 30_000, 10_000))
    hook = {"transcript_path": str(transcript), "session_id": "s4", "cwd": str(tmp_path)}
    completed = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(hook),
                               capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "wrap-up" in payload["hookSpecificOutput"]["additionalContext"].lower()


def test_hook_exits_zero_on_garbage_stdin():
    completed = subprocess.run([sys.executable, str(SCRIPT)], input="not json at all",
                               capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert completed.returncode == 0
    assert completed.stdout.strip() == ""


def test_hook_is_registered_without_a_matcher():
    settings = (Path(__file__).resolve().parents[2] / ".claude" / "settings.json").read_text(encoding="utf-8")
    hook = json.loads(settings)["hooks"]["PostToolUse"]
    assert "matcher" not in hook[0]
    assert "context_guard.py" in json.dumps(hook)
