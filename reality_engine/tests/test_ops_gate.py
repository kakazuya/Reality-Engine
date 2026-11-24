"""T-241 ops gate: Shivam's 24 Nov operating rules as checks."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from reality_engine.scripts import ops_gate as og
from reality_engine.scripts import session_hooks


@pytest.fixture()
def env(monkeypatch, tmp_path):
    rules = og.load_rules()
    rules["hy4"]["out_globs"] = [str(tmp_path / "*.db")]
    rules["ssd_only"]["root"] = str(tmp_path / "D")
    for acc in rules["quota"]["accounts"]:
        acc["config"] = str(tmp_path / acc["name"])
    monkeypatch.setattr(og.job_watch, "waiter_alive", lambda **kw: True)
    monkeypatch.setattr(og, "running_dsh", lambda: 1)
    monkeypatch.setattr(og, "running_agy", lambda: 0)
    return rules, tmp_path


WED_NIGHT = dt.datetime(2026, 11, 25, 22, 0)     # off-peak
TUE_NOON = dt.datetime(2026, 11, 24, 12, 0)      # DeepSeek peak
LOOP = ["bash .tmp/hy4_always.sh"]


def test_all_quiet_is_ok(env):
    rules, _ = env
    assert og.check(WED_NIGHT, rules, LOOP) == []


def test_heartbeat_and_hy4_loop_breaches(env, monkeypatch):
    rules, _ = env
    monkeypatch.setattr(og.job_watch, "waiter_alive", lambda **kw: False)
    lines = og.check(WED_NIGHT, rules, [])
    assert any(line.startswith("RULE heartbeat") for line in lines)
    assert any(line.startswith("RULE hy4") for line in lines)


def test_reportee_by_hour(env, monkeypatch):
    rules, _ = env
    monkeypatch.setattr(og, "running_dsh", lambda: 0)
    assert any("DeepSeek has no running job" in line for line in og.check(WED_NIGHT, rules, LOOP))
    assert any("Hydrogen has no running job" in line for line in og.check(TUE_NOON, rules, LOOP))
    monkeypatch.setattr(og, "running_agy", lambda: 1)
    assert not any("Hydrogen" in line for line in og.check(TUE_NOON, rules, LOOP))
    assert any("off-peak" in line for line in og.check(dt.datetime(2026, 11, 24, 10, 0), rules, LOOP) +
               og.check(WED_NIGHT, rules, LOOP))
    assert not og.in_peak(dt.datetime(2026, 11, 28, 12, 0), rules)        # Saturday


def test_ungraded_or_failed_checkpoint_is_a_breach(env):
    from reality_engine.v2 import read_gate
    rules, tmp = env
    (tmp / "obs.db").write_bytes(b"")
    d = read_gate.audit_dir(tmp / "obs.db")
    d.mkdir()
    (d / "ckpt_0001.jsonl").write_text("{}\n", encoding="utf-8")
    assert any("not graded" in line for line in og.check(WED_NIGHT, rules, LOOP))
    (d / "ckpt_0001.grade.json").write_text('{"verdict": "fail"}', encoding="utf-8")
    assert any("fail" in line for line in og.check(WED_NIGHT, rules, LOOP))
    (d / "ckpt_0001.grade.json").write_text('{"verdict": "pass"}', encoding="utf-8")
    assert og.check(WED_NIGHT, rules, LOOP) == []


def test_running_reader_out_is_watched_even_outside_the_globs(env, tmp_path):
    rules, _ = env
    other = tmp_path / "elsewhere" / "obs_394.db"
    cmds = LOOP + [f"python -m reality_engine.v2.observations --resume --out {other.as_posix()} --workers 30"]
    assert other.as_posix() in og.hy4_outputs(rules, cmds)


def test_quota_pace_and_five_hour(env):
    rules, tmp = env
    (tmp / "Wolf").mkdir()
    (tmp / "Wolf" / "usage_status.json").write_text(json.dumps(
        {"rate_limits": {"seven_day": {"used_percentage": 20}, "five_hour": {"used_percentage": 95}}}), encoding="utf-8")
    lines = og.check(WED_NIGHT, rules, LOOP)
    assert any("Wolf weekly at 20%" in line for line in lines)
    assert any("Wolf 5-hour window at 95%" in line for line in lines)


def test_db_on_hdd_outside_allowed_dirs(env):
    rules, tmp = env
    (tmp / "D" / "hy4_out").mkdir(parents=True)
    (tmp / "D" / "hy4_out" / "ok.db").write_bytes(b"x")
    (tmp / "D" / "newbuild").mkdir()
    (tmp / "D" / "newbuild" / "run" / "c01").mkdir(parents=True)
    (tmp / "D" / "newbuild" / "run" / "c01" / "bad.db-wal").write_bytes(b"x")
    lines = og.check(dt.datetime.now(), rules, LOOP)
    assert [line for line in lines if "ssd_only" in line and "bad.db-wal" in line]
    assert not [line for line in lines if "ok.db" in line]


def test_stop_hook_blocks_on_ops_lines():
    out = session_hooks.stop_output({}, [], ops=["RULE idle: x"])
    assert json.loads(out)["decision"] == "block"
    assert session_hooks.stop_output({"stop_hook_active": True}, [], ops=["RULE idle: x"]) == ""


def test_cached_check_reuses_recent_result(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(og, "safe_check", lambda: calls.append(1) or ["RULE x"])
    cache = tmp_path / "c.json"
    assert og.cached_check(cache) == ["RULE x"]
    assert og.cached_check(cache) == ["RULE x"]
    assert len(calls) == 1
    assert og.cached_check(cache, max_age=0) == ["RULE x"] and len(calls) == 2


def test_waiter_owner_separates_accounts(tmp_path):
    import os
    wait = tmp_path / "w"
    wait.mkdir()
    (wait / f"{os.getpid()}.json").write_text(json.dumps({"pid": os.getpid(), "owner": "c:/users/x/.claude-neo"}),
                                              encoding="utf-8")
    assert og.job_watch.waiter_alive(wait, owner="c:/users/x/.claude-neo")
    assert not og.job_watch.waiter_alive(wait, owner="c:/users/x/.claude")
    assert og.job_watch.waiter_alive(wait)


def test_data_jobs_are_not_code_workers(tmp_path, monkeypatch):
    for name, kind in (("a", "data_job"), ("b", None)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "status.json").write_text(json.dumps({"phase": "running", "kind": kind}), encoding="utf-8")
    monkeypatch.setattr(og.job_watch, "_recent_job_dirs", lambda root, now: [tmp_path / "a", tmp_path / "b"])
    monkeypatch.setattr(og.job_watch, "ACTIVE_PHASES", {"running"})
    assert og.running_dsh() == 1


def test_junction_to_the_ssd_is_not_an_hdd_write(env, tmp_path):
    import subprocess
    rules, _ = env
    ssd = tmp_path / "ssd" / "run" / "c01"
    ssd.mkdir(parents=True)
    (ssd / "c01.db").write_bytes(b"x")
    (tmp_path / "D").mkdir()
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(tmp_path / "D" / "tg_build"), str(tmp_path / "ssd")],
                       capture_output=True)
    if r.returncode != 0:
        pytest.skip("cannot make a junction here")
    assert not [line for line in og.check(dt.datetime.now(), rules, LOOP) if "ssd_only" in line]
