"""Tests for the HP worker launcher. No network: ssh/scp are replaced by recorders."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from reality_engine.scripts import hp_run, hp_worker


def fake_ssh(recorder, stdout=b"", code=0):
    def _f(argv, input_bytes=None):
        recorder.append((argv, input_bytes))
        return subprocess.CompletedProcess(argv, code, stdout, b"")
    return _f


def fake_scp(recorder, code=0):
    def _f(argv):
        recorder.append(argv)
        return subprocess.CompletedProcess(argv, code, b"", b"")
    return _f


def test_new_job_id_is_a_remote_safe_name():
    job_id = hp_worker.new_job_id()
    assert job_id.startswith("hp-")
    assert hp_worker.check_id(job_id) == job_id
    with pytest.raises(SystemExit):
        hp_worker.check_id("../escape")


def test_job_parts_are_all_under_the_job_dir():
    paths = hp_worker.job_parts("hp-1")
    assert paths["repo"] == paths["remote"] + "\\repo"
    assert paths["brief"] == paths["remote"] + "\\brief.md"
    assert paths["result"] == paths["remote"] + "\\result.md"


def test_mcp_patch_points_both_servers_at_the_job():
    home = r"C:\Users\zen7s"
    paths = hp_worker.job_parts("hp-1")
    patch = hp_worker.mcp_patch(home, paths)
    assert "mcp-reality-data" in patch and "mcp-code-intel" in patch
    assert "C:/Users/zen7s/AppData/Local/Programs/Python/Python314-arm64/python.exe" in patch
    assert "C:/RE/jobs/hp-1/repo/plugins/code-intel/server/server.py" in patch
    assert 'REALITY_DATA_ROOT: "C:/RE/data"' in patch
    # every server needs the reconnect stanza or dsh gives up after one crash
    assert patch.count("maxAttempts: 40") == 2


def test_worker_command_carries_the_msi_model_and_launch_flags():
    paths = hp_worker.job_parts("hp-1")
    command = hp_worker.worker_command(paths, r"C:\Users\zen7s", permission="workspace-write",
                                       timeout=None, max_output_tokens=None)
    assert "--model deepseek-v4.1-flash" in command
    assert "--account 2" in command
    assert "--allow-paid" in command
    assert "--no-refresh" in command
    assert "--extra-patch" in command and "hp_mcp.yml" in command
    assert "--cwd" in command and "hp-1\\repo" in command
    assert "--permission workspace-write" in command
    assert "--timeout" not in command and "--max-output-tokens" not in command


def test_worker_command_adds_the_optional_caps():
    command = hp_worker.worker_command(hp_worker.job_parts("hp-1"), r"C:\Users\zen7s",
                                       permission="read-only", timeout=600,
                                       max_output_tokens=4000)
    assert "--timeout 600" in command and "--max-output-tokens 4000" in command
    assert "--permission read-only" in command


def test_run_cmd_sets_the_hp_environment_and_runs_the_tests():
    paths = hp_worker.job_parts("hp-1")
    body = hp_worker.run_cmd("hp-1", paths, r"C:\Users\zen7s", permission="workspace-write",
                             timeout=None, max_output_tokens=None,
                             test_cmd="python -m pytest reality_engine/tests/test_hp_run.py -q")
    assert r'set "PATH=C:\Program Files\Git\cmd;C:\RE\node24\node-v24.22.2-win-arm64;%PATH%"' in body
    assert 'set "REALITY_DATA_ROOT=C:\\RE\\data"' in body
    assert 'set "DSH_WORKER_PROGRESS_NOTES=C:\\RE\\jobs\\hp-1\\repo\\PROGRESS_NOTES.md"' in body
    assert "reality_engine.scripts.run_deepseek_harness" in body
    assert "if not errorlevel 1" in body and "test.log" in body
    assert 'cd /d "C:\\RE\\jobs\\hp-1"' in body  # the wrapper owns the job dir


def test_compose_brief_carries_pack_header_facts_and_instruction():
    paths = hp_worker.job_parts("hp-1")
    text = hp_worker.compose_brief("# Task — demo\n", job_id="hp-1", paths=paths,
                                   dbs=["pilot.db"],
                                   test_cmd="python -m pytest reality_engine/tests/test_hp_run.py -q")
    assert "# Worker context pack (auto-attached)" in text
    assert "C:\\RE\\jobs\\hp-1\\CONTEXT.md" in text
    assert "C:\\RE\\jobs\\hp-1\\BRIEF_TEMPLATE.md" in text
    assert "Checkout to edit: C:\\RE\\jobs\\hp-1\\repo" in text
    assert "pilot.db" in text
    assert "# Task — demo" in text
    assert "Standing tool instruction" in text
    assert "Standing progress instruction" in text


def test_compose_brief_says_so_when_no_dbs_are_mounted():
    text = hp_worker.compose_brief("brief\n", job_id="hp-1", paths=hp_worker.job_parts("hp-1"),
                                   dbs=[], test_cmd=None)
    assert "No DBs are mounted" in text
    assert "No test command was supplied" in text


def test_peak_window_refuses_a_start(monkeypatch):
    monkeypatch.setattr(hp_worker, "off_peak", lambda: False)
    with pytest.raises(SystemExit, match="peak"):
        hp_worker.cmd_start("missing.md", [], None, "HEAD", "workspace-write", None, None, False)


def make_db(path):
    import sqlite3
    con = sqlite3.connect(str(path))
    con.execute("create table t (x integer)")
    con.commit()
    con.close()
    return path


def test_stage_db_is_a_consistent_sqlite_copy(tmp_path):
    src = make_db(tmp_path / "live.db")
    staged = hp_worker.stage_db(src)
    assert staged.is_file() and staged.stat().st_size == src.stat().st_size
    assert hp_worker.db_stamp(staged)["size"] > 0


def test_sync_dbs_keeps_an_up_to_date_copy(monkeypatch, tmp_path):
    make_db(tmp_path / "x.db")
    staged = make_db(tmp_path / "x-staged.db")
    monkeypatch.setattr(hp_worker, "stage_db", lambda path: staged)
    stamp = hp_worker.db_stamp(staged)
    scripts, scps = [], []
    monkeypatch.setattr(hp_run, "ps", lambda script: (
        scripts.append(script) or json.dumps(stamp) if "Get-Content -Raw" in script else ""))
    monkeypatch.setattr(hp_run, "_scp", fake_scp(scps))
    monkeypatch.setattr(hp_worker, "DATA_ROOT", tmp_path)
    assert hp_worker.sync_dbs(["x.db"]) == ["x.db:kept"]
    assert scps == []


def test_sync_dbs_copies_a_newer_db_and_marks_it_read_only(monkeypatch, tmp_path):
    src = make_db(tmp_path / "x.db")
    monkeypatch.setattr(hp_worker, "stage_db", lambda path: src)
    scripts, scps = [], []
    monkeypatch.setattr(hp_run, "ps", lambda script: scripts.append(script) or "")
    monkeypatch.setattr(hp_run, "_scp", fake_scp(scps))
    monkeypatch.setattr(hp_worker, "DATA_ROOT", tmp_path)
    assert hp_worker.sync_dbs(["x.db"]) == ["x.db:copied"]
    assert scps[0][0] == str(src)
    assert scps[0][1].endswith("C:/RE/data/x.db")
    assert any(".meta.json" in s for s in scripts)
    assert any("IsReadOnly = $true" in s for s in scripts)


def test_latest_patch_diffs_against_the_base_and_handles_empty(monkeypatch):
    calls = []
    monkeypatch.setattr(hp_run, "_ssh", fake_ssh(calls, stdout=b""))
    paths = hp_worker.job_parts("hp-1")
    assert hp_worker.latest_patch(paths, "abc123") == b""
    git = f'"{hp_worker.GIT}" -c "safe.directory=*" -C "{paths["repo"]}"'
    assert calls[0][0] == [f"{git} reset -q"]
    assert calls[1][0] == [f"{git} add -A"]
    assert calls[2][0] == [f"{git} diff --cached --binary abc123"]


def test_status_parser_keeps_progress_pipes():
    text = (
        "hp-1|done|0|120|run_deepseek_harness: rc=0|notes: still going|with pipes\t10 passed\n"
        "hp-2|running||0|thinking||\n"
        "\n"
    )
    rows = hp_worker.parse_status(text)
    assert [r["job"] for r in rows] == ["hp-1", "hp-2"]
    assert rows[0]["state"] == "done" and rows[0]["exit"] == "0"
    assert rows[0]["note"] == "notes: still going|with pipes"
    assert rows[0]["test"] == "10 passed"
    assert rows[1]["state"] == "running"


def test_result_fetches_every_known_artifact(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(hp_worker, "_fetch", lambda remote, dest: seen.append(remote) or False)
    monkeypatch.setattr(hp_worker, "JOBS", tmp_path)
    with pytest.raises(SystemExit, match="nothing to fetch"):
        hp_worker.cmd_result("hp-1")
    assert [Path(p).name for p in seen] == ["job.json", "result.md", "result.md.status.json",
                                            "result.md.log", "result.md.events.jsonl"]
