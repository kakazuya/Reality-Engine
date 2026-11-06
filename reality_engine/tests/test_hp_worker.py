"""Tests for the HP worker launcher. No network: ssh/scp are replaced by recorders."""
from __future__ import annotations

import json
import subprocess
import time
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
    assert "mcp-reality-data" in patch and "mcp-code-tools" in patch
    assert "C:/Users/zen7s/AppData/Local/Programs/Python/Python314-arm64/python.exe" in patch
    assert "C:/RE/jobs/hp-1/repo/plugins/code-tools/server.py" in patch
    assert 'REALITY_DATA_ROOT: "C:/RE/data"' in patch
    # every server needs the reconnect stanza or dsh gives up after one crash
    assert patch.count("maxAttempts: 40") == 2


def test_mcp_patch_without_a_pilot_db_leaves_the_env_unchanged():
    """Byte-for-byte the block that existed before --pilot-db (T-070)."""
    paths = hp_worker.job_parts("hp-1")
    patch = hp_worker.mcp_patch(r"C:\Users\zen7s", paths)
    assert "REALITY_PILOT3_DB" not in patch
    assert ("        env:\n"
            '          REALITY_DATA_ROOT: "C:/RE/data"\n'
            '          REALITY_DATA_REPO_ROOT: "C:/RE/jobs/hp-1/repo"\n'
            '          PYTHONUTF8: "1"\n') in patch


def test_mcp_patch_serves_the_pilot_db_from_the_copied_file():
    paths = hp_worker.job_parts("hp-1")
    patch = hp_worker.mcp_patch(r"C:\Users\zen7s", paths, pilot_db="pilot10.db")
    assert 'REALITY_PILOT3_DB: "C:/RE/data/pilot10.db"' in patch
    assert patch.count("REALITY_PILOT3_DB") == 1  # reality-data only, never code-tools
    assert 'REALITY_DATA_ROOT: "C:/RE/data"' in patch


def test_worker_command_carries_the_msi_model_and_launch_flags():
    paths = hp_worker.job_parts("hp-1")
    command = hp_worker.worker_command(paths, r"C:\Users\zen7s", permission="workspace-write",
                                       timeout=None, max_output_tokens=None)
    assert "--model deepseek-v4.1-flash" in command
    assert "--account 2" in command  # default: Go key 2 (OPENCODE_GO_API_KEY_2), key 1 at its limit
    assert "--allow-paid" in command
    assert "--no-refresh" in command
    assert "--extra-patch" in command and "hp_mcp.yml" in command
    assert "--cwd" in command and "hp-1\\repo" in command
    assert "--permission workspace-write" in command
    assert "--timeout" not in command and "--max-output-tokens" not in command


def test_worker_command_account_override():
    paths = hp_worker.job_parts("hp-1")
    command = hp_worker.worker_command(paths, r"C:\Users\zen7s", permission="read-only",
                                       timeout=None, max_output_tokens=None, account="2")
    assert "--account 2" in command
    with pytest.raises(SystemExit):
        hp_worker.worker_command(paths, r"C:\Users\zen7s", permission="read-only",
                                 timeout=None, max_output_tokens=None, account="9")


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
        hp_worker.cmd_start(Path("missing.md"), [], None, "HEAD", "workspace-write", None, None, False)


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


def test_sync_dbs_stages_and_stamps_a_path_outside_the_data_root(monkeypatch, tmp_path):
    """--pilot-db lives outside REALITY_DATA_ROOT and reuses stage_db + the meta stamp."""
    src = make_db(tmp_path / "pilot10.db")
    monkeypatch.setattr(hp_worker, "stage_db", lambda path: src)
    scripts, scps = [], []
    monkeypatch.setattr(hp_run, "ps", lambda script: scripts.append(script) or "")
    monkeypatch.setattr(hp_run, "_scp", fake_scp(scps))
    monkeypatch.setattr(hp_worker, "DATA_ROOT", tmp_path / "data")
    assert hp_worker.sync_dbs([], [src]) == ["pilot10.db:copied"]
    assert scps[0][0] == str(src)
    assert scps[0][1].endswith("C:/RE/data/pilot10.db")
    assert any(".meta.json" in s for s in scripts)


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


# --------------------------------------------------------------------------- #
# runtime record: what list_workers / worker_status / the pane read
# --------------------------------------------------------------------------- #
JOB_ID = "hp-20261031T000000-abc123"


def make_record(monkeypatch, tmp_path, *, phase="starting", status_extra=None,
                hp_extra=None, title="Bench: one-line repo fact"):
    monkeypatch.setattr(hp_worker, "runtime_dir", lambda: tmp_path)
    status = hp_worker.initial_status(JOB_ID, "2026-10-31T10:00:00+05:30",
                                      "zen7s@192.168.1.42", 1800, title=title)
    status["phase"] = phase
    if status_extra:
        status.update(status_extra)
    if hp_extra:
        status["hp"].update(hp_extra)
    paths = hp_worker.record_paths(JOB_ID)
    job = {
        "schema": 1, "job_id": JOB_ID, "host": "hp", "kind": "worker",
        "created_at": "2026-10-31T10:00:00+05:30", "workspace": r"C:\RE\jobs\\" + JOB_ID + r"\repo",
        "permission": "workspace-write", "model": "deepseek-v4.1-flash",
        "account": "1", "limits": {"hard_timeout_seconds": 1800},
        "hp": {"host": "zen7s@192.168.1.42", "remote": r"C:\RE\jobs\\" + JOB_ID},
        "paths": paths,
    }
    hp_worker.create_record(JOB_ID, meta=job, brief="# Task\n", status=status)
    return job, status


def test_record_paths_live_under_the_runtime_jobs_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(hp_worker, "runtime_dir", lambda: tmp_path / "rt")
    paths = hp_worker.record_paths(JOB_ID)
    assert paths["job"].startswith(str(tmp_path / "rt" / "jobs" / JOB_ID))
    assert paths["status"].endswith("status.json")


def test_status_parser_keeps_activity_and_pid():
    row = hp_worker.parse_status(
        "hp-1|running||0|last|note\t10 passed\t2026-10-31T10:00:00+00:00\t4242\n")[0]
    assert row["note"] == "note"
    assert row["test"] == "10 passed"
    assert row["activity"] == "2026-10-31T10:00:00+00:00"
    assert row["pid"] == "4242"


def test_poll_once_marks_a_running_job_reachable(monkeypatch, tmp_path):
    make_record(monkeypatch, tmp_path)
    monkeypatch.setattr(hp_worker, "_remote_row", lambda job_id: {
        "job": job_id, "state": "running", "exit": "", "result": "0", "last": "",
        "note": "", "test": "", "activity": "2026-10-31T10:05:00+00:00", "pid": "4242",
    })
    status = hp_worker.poll_once(JOB_ID)
    assert status["phase"] == "running"
    assert status["hp"]["reachable"] is True
    assert status["hp"]["pid"] == 4242
    assert status["worker_activity_at"] == "2026-10-31T10:05:00+00:00"


def test_poll_once_fetches_the_result_and_enriches_a_finished_job(monkeypatch, tmp_path):
    make_record(monkeypatch, tmp_path)
    monkeypatch.setattr(hp_worker, "_remote_row", lambda job_id: {
        "job": job_id, "state": "done", "exit": "0", "result": "10", "last": "",
        "note": "", "test": "", "activity": "", "pid": "4242",
    })
    staged = tmp_path / "result.md"
    staged.write_text("done", encoding="utf-8")
    monkeypatch.setattr(hp_worker, "fetch_result", lambda job_id: ["result.md"])
    monkeypatch.setattr(hp_worker, "_enrich_from_status",
                        lambda job_id, status: status.update(
                            {"elapsed_seconds": 12.5,
                             "progress": {**status["progress"],
                                          "events": {"tool_calls": 3, "model_steps": 2}}}))
    status = hp_worker.poll_once(JOB_ID)
    assert status["phase"] == "finished"
    assert status["outcome"] == "ok"
    assert status["exit_code"] == 0
    assert status["progress"]["done"] is True
    assert status["progress"]["events"]["tool_calls"] == 3


def test_poll_once_keeps_final_state_when_the_result_fetch_fails(monkeypatch, tmp_path):
    """A finished job must land as finished even if scp times out.

    The old poll raised out of the loop before write_status, so a job whose
    job.log already held rc=0 stayed "running" in the cache for hours.
    """
    make_record(monkeypatch, tmp_path)
    monkeypatch.setattr(hp_worker, "_remote_row", lambda job_id: {
        "job": job_id, "state": "done", "exit": "0", "result": "0", "last": "",
        "note": "", "test": "", "activity": "", "pid": "4242",
    })

    def boom(job_id):
        raise subprocess.TimeoutExpired("scp", 15)

    monkeypatch.setattr(hp_worker, "fetch_result", boom)
    status = hp_worker.poll_once(JOB_ID)
    assert status["phase"] == "finished"
    assert status["exit_code"] == 0
    assert "result fetch failed" in status["progress"]["summary"]
    on_disk = hp_worker.read_status(JOB_ID)
    assert on_disk["phase"] == "finished"


def test_poll_once_unreachable_keeps_the_cache_and_returns_fast(monkeypatch, tmp_path):
    make_record(monkeypatch, tmp_path)

    def unreachable(job_id):
        raise subprocess.TimeoutExpired("ssh", 15)

    monkeypatch.setattr(hp_worker, "_remote_row", unreachable)
    t0 = time.monotonic()
    status = hp_worker.poll_once(JOB_ID)
    elapsed = time.monotonic() - t0
    assert elapsed < 3.0
    assert status["phase"] == "starting"  # not turned into a lie about the worker
    assert status["hp"]["reachable"] is False
    assert status["progress"]["summary"].startswith("HP unreachable, last seen")
    assert "TimeoutExpired" in status["hp"]["last_error"]


def test_poll_once_does_not_move_a_final_record(monkeypatch, tmp_path):
    make_record(monkeypatch, tmp_path, phase="finished")
    monkeypatch.setattr(hp_worker, "_remote_row",
                        lambda job_id: pytest.fail("final records must not poll the network"))
    assert hp_worker.poll_once(JOB_ID)["phase"] == "finished"


def test_start_writes_the_runtime_record(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(hp_worker, "runtime_dir", lambda: runtime)
    monkeypatch.setattr(hp_worker, "archive", lambda commit: (b"tar", "a" * 40))
    monkeypatch.setattr(hp_worker, "remote_home", lambda: r"C:\Users\zen7s")
    monkeypatch.setattr(hp_worker, "init_remote_repo", lambda paths, tar: "a" * 40)
    monkeypatch.setattr(hp_worker, "sync_dbs", lambda dbs, extra=(): [])
    monkeypatch.setattr(hp_worker, "context_pack_paths", lambda: [])
    monkeypatch.setattr(hp_worker.hp_run, "ps",
                        lambda script, timeout=600: "method=wmi pid=4321")
    monkeypatch.setattr(hp_worker.hp_run, "_scp",
                        lambda argv: subprocess.CompletedProcess(argv, 0, b"", b""))
    spawned = []
    monkeypatch.setattr(hp_worker, "spawn_poller", lambda job_id: spawned.append(job_id))
    brief = tmp_path / "brief.md"
    brief.write_text("# Task — bench\n", encoding="utf-8")

    job_id = hp_worker.start(brief, [], None, "HEAD", "workspace-write", 900, None, False)

    record = json.loads(Path(hp_worker.record_paths(job_id)["job"]).read_text(encoding="utf-8"))
    assert record["host"] == "hp"
    assert record["account"] == "2"
    assert record["limits"]["hard_timeout_seconds"] == 900
    status = hp_worker.read_status(job_id)
    assert status["phase"] == "running"
    assert status["hp"]["pid"] == 4321
    assert status["title"] == "# Task — bench"
    assert spawned == [job_id]
    assert (runtime / "jobs" / job_id / "brief.md").is_file()


def test_start_refuses_a_pilot_db_that_does_not_exist(monkeypatch, tmp_path):
    monkeypatch.setattr(hp_worker, "off_peak", lambda: True)
    brief = tmp_path / "brief.md"
    brief.write_text("# Task\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="pilot-db"):
        hp_worker.start(brief, [], None, "HEAD", "workspace-write", None, None, False,
                        pilot_db=tmp_path / "missing.db")


def test_start_copies_the_pilot_db_and_points_the_patch_at_it(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(hp_worker, "runtime_dir", lambda: runtime)
    monkeypatch.setattr(hp_worker, "off_peak", lambda: True)
    monkeypatch.setattr(hp_worker, "archive", lambda commit: (b"tar", "a" * 40))
    monkeypatch.setattr(hp_worker, "remote_home", lambda: r"C:\Users\zen7s")
    monkeypatch.setattr(hp_worker, "init_remote_repo", lambda paths, tar: "a" * 40)
    synced = []
    monkeypatch.setattr(hp_worker, "sync_dbs",
                        lambda dbs, extra=(): synced.append(list(dbs) + list(extra)) or [])
    monkeypatch.setattr(hp_worker, "context_pack_paths", lambda: [])
    monkeypatch.setattr(hp_worker.hp_run, "ps",
                        lambda script, timeout=600: "method=wmi pid=4321")
    monkeypatch.setattr(hp_worker.hp_run, "_scp",
                        lambda argv: subprocess.CompletedProcess(argv, 0, b"", b""))
    monkeypatch.setattr(hp_worker, "spawn_poller", lambda job_id: None)
    pilot = make_db(tmp_path / "pilot10.db")
    brief = tmp_path / "brief.md"
    brief.write_text("# Task\n", encoding="utf-8")

    job_id = hp_worker.start(brief, [], None, "HEAD", "workspace-write", 900, None, False,
                             pilot_db=pilot)

    assert synced == [[pilot]]
    local = Path(hp_worker.job_parts(job_id)["local"])
    patch = (local / "hp_mcp.yml").read_text(encoding="utf-8")
    assert 'REALITY_PILOT3_DB: "C:/RE/data/pilot10.db"' in patch
    meta = json.loads((local / "job.json").read_text(encoding="utf-8"))
    assert meta["pilot_db"] == str(pilot)


def test_ssh_retries_the_tailscale_address_when_the_lan_is_refused(monkeypatch):
    """The LAN can refuse while Tailscale is up; one retry, then stick to the path that worked."""
    calls = []

    def run(host, argv, input_bytes, timeout):
        calls.append(host)
        return subprocess.CompletedProcess(argv, 255 if len(calls) == 1 else 0, b"ok", b"")

    monkeypatch.setattr(hp_run, "_run_ssh", run)
    monkeypatch.setattr(hp_run, "HOST", "zen7s@192.168.1.42")
    monkeypatch.setattr(hp_run, "FALLBACK_HOST", "zen7s@100.78.87.112")

    result = hp_run._ssh(["status"])

    assert result.returncode == 0
    assert result.stdout == b"ok"
    assert calls == ["zen7s@192.168.1.42", "zen7s@100.78.87.112"]
    assert hp_run.HOST == "zen7s@100.78.87.112"

