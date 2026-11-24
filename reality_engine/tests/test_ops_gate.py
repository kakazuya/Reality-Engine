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
    rules["hy4"]["audit_glob"] = str(tmp_path / "*.audit")
    rules["ssd_only"]["root"] = str(tmp_path / "D")
    for acc in rules["quota"]["accounts"]:
        acc["config"] = str(tmp_path / acc["name"])
    monkeypatch.setattr(og.job_watch, "waiter_alive", lambda: True)
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
    monkeypatch.setattr(og.job_watch, "waiter_alive", lambda: False)
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


def test_ungraded_checkpoint_is_a_breach(env):
    rules, tmp = env
    d = tmp / "obs.db.audit"
    d.mkdir()
    (d / "ckpt_0001.jsonl").write_text("{}\n", encoding="utf-8")
    assert any("waits for a grade" in line for line in og.check(WED_NIGHT, rules, LOOP))
    (d / "ckpt_0001.grade.json").write_text("{}", encoding="utf-8")
    assert og.check(WED_NIGHT, rules, LOOP) == []


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
    (tmp / "D" / "newbuild" / "bad.db").write_bytes(b"x")
    lines = og.check(dt.datetime.now(), rules, LOOP)
    assert [line for line in lines if "ssd_only" in line and "bad.db" in line]
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
