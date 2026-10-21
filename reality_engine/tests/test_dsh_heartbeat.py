"""Deterministic heartbeat tests: fake clocks, fake transports, and fake workers.

No credentials, external inference, GPU, or project databases are touched.
The process tests launch a tiny local worker over pipes, which exercises the
JSON event parser, stdout/stderr drain, ping transport, and process teardown.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from reality_engine.scripts.dsh_heartbeat import (
    DEFAULT_IDLE_SECONDS,
    HEARTBEAT_EXIT,
    HARD_TIMEOUT_EXIT,
    ControlTransport,
    Delivery,
    HeartbeatConfig,
    HeartbeatSupervisor,
    parse_event_line,
    read_control_endpoint,
    resolve_control_token,
    run_supervised,
    wait_control_endpoint,
)
from reality_engine.scripts.run_deepseek_harness import DSH, build_patch


FAKE_WORKER = r'''
import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

scenario = json.loads(open(os.environ["FAKE_SCENARIO"], encoding="utf-8").read())
token = os.environ["DSH_HEARTBEAT_TOKEN"]
control_file = os.environ["FAKE_CONTROL_FILE"]
run_id = os.environ["DSH_HEARTBEAT_RUN_ID"]
ping_count = 0
reply_event = threading.Event()
stop_event = threading.Event()

def emit(event):
    print(json.dumps(event), flush=True)

def write_control(port):
    tmp = control_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"schema": "dsh-heartbeat-control/1", "state": "bound", "host": "127.0.0.1",
                   "port": port, "pid": os.getpid(), "run_id": run_id,
                   "session_id": "session-fake", "agent_status": "running"}, fh)
    os.replace(tmp, control_file)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_POST(self):
        global ping_count
        if self.path != "/ping" or self.headers.get("x-dsh-heartbeat-token") != token:
            self.send_response(401); self.end_headers(); return
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except ValueError:
            self.send_response(400); self.end_headers(); return
        if body.get("run_id") != run_id:
            self.send_response(403); self.end_headers(); return
        ping_count += 1
        with open(control_file + ".pings", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"sequence": body.get("sequence"), "message": body.get("message")}) + "\n")
        reply_event.set()
        payload = json.dumps({"ok": True, "queued": True, "worker_response": False,
                              "session_id": "session-fake", "agent_status": "running",
                              "ping_count": ping_count}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

server = None
if not scenario.get("no_control"):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    write_control(server.server_address[1])
    threading.Thread(target=server.serve_forever, daemon=True).start()

sys.stdin.read()
emit({"type": "session", "sessionId": "session-fake"})
emit({"type": "status", "phase": "turn_start"})

mode = scenario.get("mode", "healthy")
if mode == "fail":
    print("dsh: fatal: fake worker failure", file=sys.stderr, flush=True)
    time.sleep(0.1)
    sys.exit(1)
if mode == "crash_before_ready":
    sys.exit(1)

interval = float(scenario.get("interval", 0.2))
duration = float(scenario.get("duration", 1.0))
if scenario.get("partial"):
    emit({"type": "text", "text": "partial answer before interruption"})
if mode == "text_then_silent":
    emit({"type": "text", "text": scenario.get("final_text", "committed text before termination")})
    while not stop_event.wait(0.2):
        pass
    sys.exit(0)
if mode == "silent" or scenario.get("no_control"):
    while not stop_event.wait(0.2):
        pass
    sys.exit(0)
if mode == "reply":
    # Stay quiet long enough for the supervisor's idle timer to fire, then
    # acknowledge the real steering message and continue working.
    emit({"type": "text", "text": "working on the task"})
    if not reply_event.wait(duration):
        sys.exit(0)
    emit({"type": "text", "text": "status acknowledged; continuing"})
    reply_event.clear()

if scenario.get("no_final"):
    emit({"type": "text", "text": scenario.get("final_text", "partial no final")})
    emit({"type": "status", "phase": "turn_end", "reason": {"kind": "completed"}})
    sys.exit(0)

if scenario.get("bad_turn"):
    emit({"type": "text", "text": scenario.get("final_text", "truncated final")})
    emit({"type": "status", "phase": "turn_end", "reason": {"kind": "max-tokens"}})
    emit({"type": "final", "text": scenario.get("final_text", "truncated final")})
    sys.exit(0)

end = time.monotonic() + duration
replied = False
while time.monotonic() < end:
    if mode == "reply" and reply_event.is_set() and not replied:
        emit({"type": "text", "text": "status acknowledged; continuing"})
        replied = True
        reply_event.clear()
    emit({"type": "tool_call", "name": "fake_tool"})
    emit({"type": "tool_result", "name": "fake_tool", "ok": True})
    time.sleep(interval)
emit({"type": "text", "text": scenario.get("final_text", "fake final answer")})
emit({"type": "status", "phase": "turn_end", "reason": {"kind": "completed"}})
emit({"type": "final", "text": scenario.get("final_text", "fake final answer")})
if server is not None:
    server.shutdown()
'''


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class HeartbeatStateTests(unittest.TestCase):
    def config(self, **kwargs):
        values = dict(idle_seconds=10, response_window_seconds=10, max_unanswered=2)
        values.update(kwargs)
        return HeartbeatConfig(**values)

    def supervisor(self, clock, ping_fn, **kwargs):
        return HeartbeatSupervisor(
            self.config(**kwargs),
            run_id="run-test",
            clock=clock,
            wall_clock=lambda: 1_700_000_000 + clock.value,
            ping_fn=ping_fn,
        )

    def test_healthy_long_run_survives_repeated_intervals(self):
        clock = FakeClock(0)
        calls = []
        sup = self.supervisor(clock, lambda **kw: calls.append(kw) or Delivery(ok=True, queued=True))
        for now in range(0, 101, 5):
            clock.value = now
            if now:
                sup.note_activity("tool_call", now=now)
            self.assertNotEqual(sup.tick(now), "stop")
        self.assertEqual(calls, [])
        self.assertEqual(sup.consecutive_unanswered, 0)

    def test_two_fully_unanswered_requests_stop_after_two_windows(self):
        clock = FakeClock(0)
        calls = []
        sup = self.supervisor(clock, lambda **kw: calls.append(kw) or Delivery(ok=True, queued=True))
        self.assertEqual(sup.tick(10), "ping")
        sup.make_ping("ping one", now=10)
        self.assertEqual(sup.tick(19), "none")
        self.assertEqual(sup.tick(20), "ping")
        sup.make_ping("ping two", now=20)
        self.assertEqual(sup.tick(29), "none")
        self.assertEqual(sup.tick(30), "stop")
        self.assertEqual(sup.failure, "heartbeat_no_response")
        self.assertEqual(len(calls), 2)
        self.assertEqual([p.outcome for p in sup.pings], ["missed", "missed"])
        self.assertEqual(sup.consecutive_unanswered, 2)

    def test_transport_ack_does_not_reset_misses(self):
        clock = FakeClock(0)
        sup = self.supervisor(clock, lambda **kw: Delivery(ok=True, queued=True))
        sup.make_ping("ping one", now=10)
        self.assertEqual(sup.activity_count, 0)
        self.assertEqual(sup.tick(20), "ping")
        self.assertEqual(sup.consecutive_unanswered, 1)

    def test_real_same_worker_activity_resets_misses(self):
        clock = FakeClock(0)
        sup = self.supervisor(clock, lambda **kw: Delivery(ok=True, queued=True))
        sup.make_ping("ping one", now=10)
        clock.value = 15
        sup.note_activity("tool_result", now=15)
        self.assertEqual(sup.pings[0].outcome, "answered")
        self.assertEqual(sup.consecutive_unanswered, 0)
        self.assertEqual(sup.tick(20), "none")

    def test_activity_after_one_miss_resets_before_second_miss(self):
        clock = FakeClock(0)
        sup = self.supervisor(clock, lambda **kw: Delivery(ok=True, queued=True))
        sup.make_ping("ping one", now=10)
        self.assertEqual(sup.tick(20), "ping")
        self.assertEqual(sup.consecutive_unanswered, 1)
        sup.make_ping("ping two", now=20)
        clock.value = 21
        sup.note_activity("text", now=21)
        self.assertEqual(sup.consecutive_unanswered, 0)
        self.assertEqual(sup.tick(30), "none")

    def test_delivery_failures_are_distinguished(self):
        clock = FakeClock(0)
        sup = self.supervisor(clock, lambda **kw: Delivery(ok=False, queued=False, error="connection refused"))
        sup.make_ping("ping one", now=10)
        self.assertEqual(sup.tick(20), "ping")
        sup.make_ping("ping two", now=20)
        self.assertEqual(sup.tick(30), "stop")
        self.assertEqual(sup.failure, "heartbeat_no_delivery")
        self.assertFalse(sup.pings[0].delivery_ok)

    def test_explicit_hard_timeout_wins_over_heartbeat(self):
        clock = FakeClock(0)
        sup = self.supervisor(
            clock,
            lambda **kw: Delivery(ok=True, queued=True),
            idle_seconds=5,
            response_window_seconds=5,
            hard_timeout=25,
        )
        for now in range(0, 25, 5):
            clock.value = now
            if now:
                sup.note_activity("tool_call", now=now)
            self.assertNotEqual(sup.tick(now), "hard_timeout")
        clock.value = 25
        self.assertEqual(sup.tick(25), "hard_timeout")
        self.assertEqual(sup.failure, "hard_timeout")

    def test_deliberate_followup_wait_suppresses_idle_ping(self):
        clock = FakeClock(0)
        calls = []
        sup = self.supervisor(clock, lambda **kw: calls.append(kw) or Delivery(ok=True, queued=True))
        self.assertTrue(sup.set_awaiting_input(True, now=1))
        self.assertEqual(sup.tick(50), "none")
        self.assertEqual(calls, [])
        self.assertTrue(sup.snapshot()["heartbeat"]["awaiting_input"])
        # A normal end restarts the idle anchor; it does not count as activity.
        self.assertTrue(sup.set_awaiting_input(False, now=50))
        self.assertEqual(sup.tick(55), "none")
        self.assertEqual(sup.activity_count, 0)

    def test_expired_followup_lease_makes_ping_due_immediately(self):
        clock = FakeClock(0)
        sup = self.supervisor(clock, lambda **kw: Delivery(ok=True, queued=True))
        sup.set_awaiting_input(True, now=1)
        self.assertEqual(sup.tick(100), "none")
        # The supervisor backdates the anchor to the lease deadline when the
        # descriptor is stale, so a wedged wait cannot silence it forever.
        sup.set_awaiting_input(False, now=100, ended_at=10)
        self.assertEqual(sup.tick(100), "ping")
        self.assertEqual(sup.last_activity_kind, "start")

    def test_defaults_match_documented_schedule(self):
        self.assertEqual(DEFAULT_IDLE_SECONDS, 900)
        config = HeartbeatConfig()
        self.assertEqual(config.response_window_seconds, 900)
        self.assertEqual(config.max_unanswered, 2)
        self.assertIsNone(config.hard_timeout)

    def test_unparsed_stdout_is_not_activity(self):
        self.assertEqual(parse_event_line("not json")["type"], "unparsed_stdout")
        self.assertEqual(parse_event_line('{"type":"text","text":"ok"}')["type"], "text")

    def test_config_requires_two_misses(self):
        with self.assertRaises(ValueError):
            HeartbeatConfig(max_unanswered=1)


class ProcessHeartbeatTests(unittest.TestCase):
    """End-to-end supervisor tests using a local fake dsh-like worker."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="dsh-hb-test-")
        cls.root = Path(cls.tmp.name)
        cls.worker = cls.root / "fake_worker.py"
        cls.worker.write_text(textwrap.dedent(FAKE_WORKER), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_worker(self, name, scenario, heartbeat, *, hard_timeout=None, timeout=20, stale_control=False):
        base = self.root / name
        base.mkdir(parents=True, exist_ok=True)
        control = base / "run.control.json"
        scenario_path = base / "scenario.json"
        scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
        if stale_control:
            control.write_text(json.dumps({
                "schema": "dsh-heartbeat-control/1", "state": "bound", "host": "127.0.0.1",
                "port": 9, "pid": 1, "run_id": "stale", "session_id": "stale-session",
            }), encoding="utf-8")
        env = dict(os.environ)
        env.update({
            "FAKE_SCENARIO": str(scenario_path),
            "FAKE_CONTROL_FILE": str(control),
            "DSH_HEARTBEAT_TOKEN": "t" * 64,
            "DSH_HEARTBEAT_RUN_ID": name,
        })
        config = HeartbeatConfig(
            idle_seconds=heartbeat[0],
            response_window_seconds=heartbeat[1],
            max_unanswered=heartbeat[2],
            hard_timeout=hard_timeout,
        )
        return run_supervised(
            argv=[sys.executable, str(self.worker)],
            env=env,
            cwd=str(base),
            task_text="fake task",
            out_path=base / "out.md",
            log_path=base / "out.md.log",
            status_path=base / "out.md.status.json",
            control_path=control,
            heartbeat=config,
            control_token="t" * 64,
            run_id=name,
            metadata={"model": "fake", "effort": "xhigh", "account": "2", "permission": "read-only"},
            control_ready_timeout=timeout,
        )

    def test_healthy_run_completes_without_pings(self):
        result = self.run_worker("healthy", {"mode": "healthy", "interval": 0.15, "duration": 1.0},
                                 (0.5, 0.5, 2))
        self.assertEqual(result.rc, 0, result.detail)
        self.assertFalse(result.partial)
        self.assertEqual(result.out_text, "fake final answer")
        self.assertEqual(result.status["heartbeat"]["pings"], [])
        self.assertTrue(result.status["control"]["listener_closed"])
        self.assertTrue(result.events_path.exists())
        for path in (result.status_path, result.control_path, result.log_path):
            self.assertNotIn("t" * 64, path.read_text(encoding="utf-8", errors="replace"))

    def test_committed_text_is_persisted_before_termination(self):
        base = self.root / "text-terminated"
        base.mkdir(parents=True, exist_ok=True)
        control = base / "run.control.json"
        scenario_path = base / "scenario.json"
        scenario_path.write_text(json.dumps({
            "mode": "text_then_silent",
            "final_text": "committed answer survives termination",
        }), encoding="utf-8")
        out_path = base / "out.md"
        status_path = base / "out.md.status.json"
        env = dict(os.environ)
        env.update({
            "FAKE_SCENARIO": str(scenario_path),
            "FAKE_CONTROL_FILE": str(control),
            "DSH_HEARTBEAT_TOKEN": "t" * 64,
            "DSH_HEARTBEAT_RUN_ID": "text-terminated",
        })
        box: dict = {}

        def run():
            box["result"] = run_supervised(
                argv=[sys.executable, str(self.worker)],
                env=env,
                cwd=str(base),
                task_text="fake task",
                out_path=out_path,
                log_path=base / "out.md.log",
                status_path=status_path,
                control_path=control,
                heartbeat=HeartbeatConfig(idle_seconds=30, response_window_seconds=5, max_unanswered=2),
                control_token="t" * 64,
                run_id="text-terminated",
                metadata={"model": "fake", "effort": "xhigh", "account": "2",
                          "permission": "read-only"},
                control_ready_timeout=20,
            )

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 8.0
            persisted = ""
            while time.monotonic() < deadline:
                try:
                    persisted = out_path.read_text(encoding="utf-8")
                except OSError:
                    persisted = ""
                if "committed answer survives termination" in persisted:
                    break
                time.sleep(0.02)
            self.assertIn("committed answer survives termination", persisted)
            pid = None
            pid_deadline = time.monotonic() + 3.0
            while time.monotonic() < pid_deadline and pid is None:
                try:
                    candidate = json.loads(status_path.read_text(encoding="utf-8")).get("pid")
                except (OSError, ValueError):
                    candidate = None
                if isinstance(candidate, int):
                    pid = candidate
                else:
                    time.sleep(0.02)
            self.assertIsInstance(pid, int)
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            else:
                os.kill(pid, 15)
            thread.join(timeout=10)
        finally:
            if thread.is_alive():
                thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        result = box.get("result")
        self.assertIsNotNone(result)
        self.assertNotEqual(result.rc, 0)
        self.assertIn("committed answer survives termination", out_path.read_text(encoding="utf-8"))
        self.assertNotIn("thinking", out_path.read_text(encoding="utf-8"))

    def test_ping_gets_real_worker_response_and_resets(self):
        result = self.run_worker("reply", {"mode": "reply", "interval": 0.2, "duration": 1.6},
                                 (0.4, 0.6, 2))
        self.assertEqual(result.rc, 0, result.detail)
        pings = result.status["heartbeat"]["pings"]
        self.assertGreaterEqual(len(pings), 1)
        self.assertEqual(pings[0]["outcome"], "answered")
        self.assertEqual(result.status["heartbeat"]["consecutive_unanswered"], 0)
        self.assertIn("status acknowledged", result.events_path.read_text(encoding="utf-8"))

    def test_two_unanswered_requests_stop_and_preserve_partial(self):
        result = self.run_worker("silent", {"mode": "silent", "partial": True},
                                 (0.3, 0.3, 2))
        self.assertEqual(result.rc, HEARTBEAT_EXIT)
        self.assertEqual(result.status["failure"], "heartbeat_no_response")
        self.assertEqual(len(result.status["heartbeat"]["pings"]), 2)
        self.assertTrue(result.partial)
        self.assertIn("partial answer", result.out_text)
        self.assertTrue(result.status["control"]["listener_closed"])

    def test_explicit_hard_timeout(self):
        result = self.run_worker("hard", {"mode": "healthy", "interval": 0.15, "duration": 5.0},
                                 (5.0, 5.0, 2), hard_timeout=0.9)
        self.assertEqual(result.rc, HARD_TIMEOUT_EXIT)
        self.assertEqual(result.status["failure"], "hard_timeout")
        self.assertTrue(result.status["control"]["listener_closed"])

    def test_early_worker_failure_preserves_diagnostics(self):
        result = self.run_worker("fail", {"mode": "fail"}, (5.0, 5.0, 2))
        self.assertEqual(result.rc, 1)
        self.assertEqual(result.status["failure"], "dsh_exit_nonzero")
        self.assertIn("fake worker failure", result.status["stderr_tail"])

    def test_control_not_ready_is_a_clear_failure(self):
        result = self.run_worker("noctrl", {"mode": "silent", "no_control": True}, (5.0, 5.0, 2), timeout=0.8)
        self.assertEqual(result.rc, 126)
        self.assertEqual(result.status["failure"], "control_not_ready")
        self.assertIsNone(result.status["control"]["host"])

    def test_hard_timeout_before_control_ready(self):
        result = self.run_worker("noctrl-hard", {"mode": "silent", "no_control": True},
                                 (5.0, 5.0, 2), hard_timeout=0.5, timeout=5.0)
        self.assertEqual(result.rc, HARD_TIMEOUT_EXIT)
        self.assertEqual(result.status["failure"], "hard_timeout")

    def test_stale_control_descriptor_is_not_reused(self):
        result = self.run_worker("stale", {"mode": "healthy", "interval": 0.1, "duration": 0.7},
                                 (5.0, 5.0, 2), stale_control=True)
        self.assertEqual(result.rc, 0, result.detail)
        self.assertEqual(result.status["dsh_conversation_id"], "session-fake")
        self.assertNotEqual(result.status["control"]["session_id"], "stale-session")

    def test_missing_final_is_not_reported_as_success(self):
        result = self.run_worker(
            "nofinal",
            {"mode": "healthy", "no_final": True, "final_text": "partial no final"},
            (5.0, 5.0, 2),
        )
        self.assertEqual(result.rc, 1)
        self.assertEqual(result.status["failure"], "missing_final")
        self.assertTrue(result.partial)
        self.assertIn("partial no final", result.out_text)

    def test_noncompleted_turn_is_not_reported_as_success(self):
        result = self.run_worker(
            "badturn",
            {"mode": "healthy", "bad_turn": True, "final_text": "truncated final"},
            (5.0, 5.0, 2),
        )
        self.assertEqual(result.rc, 1)
        self.assertEqual(result.status["failure"], "turn_not_completed")
        self.assertIn("truncated final", result.out_text)

    def test_stdout_and_stderr_are_drained_without_deadlock(self):
        scenario = {"mode": "healthy", "interval": 0.01, "duration": 0.8}
        result = self.run_worker("drain", scenario, (5.0, 5.0, 2))
        self.assertEqual(result.rc, 0, result.detail)
        self.assertIn("fake final answer", result.out_text)
        self.assertGreater(result.status["counters"]["stdout_events"], 10)


class ControlTransportTests(unittest.TestCase):
    def test_read_control_endpoint_rejects_bad_schema_and_host(self):
        with tempfile.TemporaryDirectory(prefix="dsh-hb-endpoint-") as tmp:
            path = Path(tmp) / "control.json"
            path.write_text(json.dumps({"schema": "bad", "host": "127.0.0.1", "port": 1}), encoding="utf-8")
            self.assertIsNone(read_control_endpoint(path))
            path.write_text(json.dumps({"schema": "dsh-heartbeat-control/1", "host": "0.0.0.0", "port": 1}),
                            encoding="utf-8")
            self.assertIsNone(read_control_endpoint(path))

    def test_awaiting_descriptor_requires_a_live_absolute_deadline(self):
        with tempfile.TemporaryDirectory(prefix="dsh-hb-endpoint-") as tmp:
            path = Path(tmp) / "control.json"
            base = {
                "schema": "dsh-heartbeat-control/1",
                "state": "awaiting-input",
                "host": "127.0.0.1",
                "port": 1234,
                "session_id": "conv",
                "awaiting_input": True,
            }
            path.write_text(
                json.dumps({**base, "followup_deadline": "2000-01-01T00:00:00+00:00"}),
                encoding="utf-8",
            )
            expired = read_control_endpoint(path)
            self.assertIsNotNone(expired)
            self.assertFalse(expired.awaiting_input)
            path.write_text(json.dumps(base), encoding="utf-8")
            missing = read_control_endpoint(path)
            self.assertIsNotNone(missing)
            self.assertFalse(missing.awaiting_input)
            future = datetime.now(timezone.utc) + timedelta(minutes=1)
            path.write_text(
                json.dumps({**base, "followup_deadline": future.isoformat(timespec="seconds")}),
                encoding="utf-8",
            )
            live = read_control_endpoint(path)
            self.assertIsNotNone(live)
            self.assertTrue(live.awaiting_input)

    def test_transport_reports_unavailable_instead_of_acknowledging(self):
        with tempfile.TemporaryDirectory(prefix="dsh-hb-endpoint-") as tmp:
            path = Path(tmp) / "control.json"
            transport = ControlTransport(path, token="x" * 64, run_id="run")
            delivery = transport.ping(ping_id="p1", sequence=1, message="status", session_id=None)
            self.assertFalse(delivery.ok)
            self.assertFalse(delivery.queued)

    def test_parent_can_supply_control_token_via_named_environment_only(self):
        env = {"WORKER_CONTROL": "z" * 64}
        self.assertEqual(resolve_control_token(env, "WORKER_CONTROL"), "z" * 64)
        self.assertNotEqual(resolve_control_token(env, None), "z" * 64)
        with self.assertRaises(ValueError):
            resolve_control_token({}, "WORKER_CONTROL")
        with self.assertRaises(ValueError):
            resolve_control_token({"WORKER_CONTROL": "short"}, "WORKER_CONTROL")
        with self.assertRaises(ValueError):
            resolve_control_token(env, "not-a-name")


class FakeChatCompletions:
    """Tiny local OpenAI-compatible SSE endpoint; no external inference."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.heartbeat_seen = threading.Event()
        self.control_path: Path | None = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.requests.append(body)
                if "dsh-heartbeat status check" in json.dumps(body):
                    outer.heartbeat_seen.set()
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache")
                self.end_headers()
                if len(outer.requests) == 1:
                    if outer.control_path is not None:
                        # Release the first model step only once the supervisor's
                        # ping has really been delivered.  The committed
                        # tool_call then lands inside that ping's window instead
                        # of racing dsh startup and a fixed hold.
                        outer.wait_for_ping()
                    else:
                        # Direct-transport path: hold briefly for its explicit ping.
                        time.sleep(1.2)
                    self.chunk({
                        "role": "assistant",
                        "tool_calls": [{
                            "index": 0,
                            "id": "call_fake_1",
                            "type": "function",
                            "function": {"name": "working_directory", "arguments": ""},
                        }],
                    })
                    self.chunk({"tool_calls": [{"index": 0, "function": {"arguments": "{}"}}]})
                    self.chunk({}, finish="tool_calls")
                else:
                    self.chunk({"role": "assistant", "content": "status reply: still working; integration complete"})
                    self.chunk({}, finish="stop")
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

            def chunk(self, delta, finish=None):
                payload = {
                    "id": "chatcmpl-fake",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "beam-free",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
                self.wfile.flush()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def expect_ping_descriptor(self, path: Path) -> None:
        """Tie the first model step to a real delivered ping (no wall-clock race)."""
        self.control_path = Path(path)

    def wait_for_ping(self, timeout: float = 20.0) -> bool:
        """Wait until the control plugin has delivered its first status request."""
        assert self.control_path is not None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                state = json.loads(self.control_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                state = None
            if isinstance(state, dict):
                try:
                    delivered = int(state.get("pings") or 0)
                except (TypeError, ValueError):
                    delivered = 0
                if delivered >= 1:
                    return True
            time.sleep(0.02)
        return False

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


class MultiTurnFakeChatCompletions:
    """Local OpenAI-compatible endpoint that answers each request in order."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.last_user_messages: list[str] = []
        self.session_headers: list[str] = []
        self.heartbeat_seen = threading.Event()
        self.lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                with outer.lock:
                    outer.requests.append(body)
                    index = len(outer.requests)
                    outer.session_headers.append(str(self.headers.get("x-opencode-session") or ""))
                    messages = body.get("messages") if isinstance(body.get("messages"), list) else []
                    last_user = ""
                    for message in reversed(messages):
                        if not isinstance(message, dict) or message.get("role") != "user":
                            continue
                        content = message.get("content")
                        if isinstance(content, list):
                            last_user = "\n".join(
                                str(block.get("text") or "")
                                for block in content
                                if isinstance(block, dict) and block.get("type") == "text"
                            )
                        else:
                            last_user = str(content or "")
                        break
                    outer.last_user_messages.append(last_user)
                    if "dsh-heartbeat status check" in json.dumps(body):
                        outer.heartbeat_seen.set()
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache")
                self.end_headers()
                self.chunk({"role": "assistant", "content": f"answer-{index}"})
                self.chunk({}, finish="stop")
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

            def chunk(self, delta, finish=None):
                payload = {
                    "id": "chatcmpl-fake",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "beam-free",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
                self.wfile.flush()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


@unittest.skipUnless(DSH.exists(), "installed dsh is required for the local plugin integration test")
class RealDshControlIntegrationTests(unittest.TestCase):
    """Actual dsh + actual Cordis plugin + local fake model (no paid inference)."""

    @staticmethod
    def _kill_tree(process):
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        else:
            process.kill()

    def _wait_awaiting(self, control: Path, delivered: int, result_box: dict, timeout: float = 20.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            endpoint = read_control_endpoint(control)
            if endpoint is not None and endpoint.awaiting_input:
                try:
                    count = int(endpoint.raw.get("followups_delivered") or 0)
                except (TypeError, ValueError):
                    count = 0
                if count >= delivered:
                    return endpoint
            if result_box.get("done"):
                break
            time.sleep(0.02)
        self.fail(f"worker never reached awaiting-input after {delivered} delivered follow-up(s); "
                  f"result={result_box.get('result')}")

    def test_ten_followups_use_ten_requests_and_one_conversation(self):
        with tempfile.TemporaryDirectory(prefix="dsh-real-followups-") as tmp, \
                MultiTurnFakeChatCompletions() as fake:
            root = Path(tmp)
            control = root / "run.control.json"
            patch_path = root / "patch.yml"
            token = "f" * 64
            run_id = "real-followup-test"
            patch_path.write_text(
                build_patch(
                    "beam-free", "", "DSH_PLUGIN_TEST_KEY", 512, fake.base_url,
                    {"plugin": Path("reality_engine/scripts/dsh_heartbeat_control.mjs").resolve(),
                     "endpoint": control, "followup_wait": 10},
                ),
                encoding="utf-8",
            )
            env = dict(os.environ)
            env.update({
                "DSH_PLUGIN_TEST_KEY": "local-test-key",
                "DSH_PERMISSION_MODE": "read-only",
                "PATH": str(DSH.parent) + os.pathsep + env.get("PATH", ""),
            })
            result_box: dict = {}

            def run() -> None:
                try:
                    result_box["result"] = run_supervised(
                        argv=[str(DSH), "--profile", "headless", "--patch", str(patch_path), "--json", "-"],
                        env=env,
                        cwd=tmp,
                        task_text="Question 1: what is the capital of France?",
                        out_path=root / "out.md",
                        log_path=root / "out.md.log",
                        status_path=root / "out.md.status.json",
                        control_path=control,
                        heartbeat=HeartbeatConfig(
                            idle_seconds=20.0, response_window_seconds=5.0, max_unanswered=2
                        ),
                        control_token=token,
                        run_id=run_id,
                        metadata={"model": "beam-free", "effort": "", "account": "2",
                                  "permission": "read-only", "followup_wait_seconds": 4},
                        control_ready_timeout=25,
                    )
                finally:
                    result_box["done"] = True

            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            try:
                endpoint = wait_control_endpoint(control, process=None, timeout=25)
                self.assertIsNotNone(endpoint, "control plugin did not bind the live agent")
                assert endpoint is not None
                conversation = endpoint.session_id
                first = self._wait_awaiting(control, 0, result_box)
                self.assertEqual(first.session_id, conversation)
                # The latest committed answer is readable while awaiting input,
                # independent of the raw event stream and before Question 2.
                deadline = time.monotonic() + 5.0
                interim_text = ""
                while time.monotonic() < deadline:
                    try:
                        interim_text = (root / "out.md").read_text(encoding="utf-8")
                    except OSError:
                        interim_text = ""
                    if "answer-1" in interim_text:
                        break
                    time.sleep(0.02)
                self.assertIn("answer-1", interim_text, fake.last_user_messages)
                interim_status = {}
                status_deadline = time.monotonic() + 5.0
                while time.monotonic() < status_deadline:
                    try:
                        interim_status = json.loads(
                            (root / "out.md.status.json").read_text(encoding="utf-8")
                        )
                    except (OSError, ValueError):
                        interim_status = {}
                    if interim_status.get("interim_result"):
                        break
                    time.sleep(0.02)
                self.assertTrue(interim_status.get("interim_result"), interim_status)
                self.assertFalse(interim_status["partial"], interim_status)
                self.assertEqual(interim_status["result_kind"], "awaiting_input", interim_status)
                self.assertEqual(len(fake.requests), 1, fake.last_user_messages)
                # A deliberate wait outlasts the heartbeat idle interval and
                # must not manufacture a status request or model step.
                time.sleep(4.2)
                self.assertEqual(len(fake.requests), 1)
                self.assertFalse(fake.heartbeat_seen.is_set())

                transport = ControlTransport(control, token=token, run_id=run_id,
                                             session_id=conversation)
                sessions = {conversation}
                for number in range(2, 11):
                    delivery = transport.followup(
                        followup_id=f"{run_id}-followup-{number}",
                        sequence=number,
                        message=f"Question {number}: what is the capital?",
                    )
                    self.assertTrue(delivery.ok, delivery.error)
                    self.assertEqual(delivery.delivery_mode, "awaiting-turn")
                    self.assertFalse(delivery.awaiting_input and delivery.kind != "followup")
                    awaiting = self._wait_awaiting(control, number - 1, result_box)
                    sessions.add(awaiting.session_id)

                thread.join(timeout=30)
                self.assertFalse(thread.is_alive(), "worker did not exit after the bounded wait")
                result = result_box["result"]
                self.assertEqual(result.rc, 0, result.detail)
                self.assertIn("answer-10", result.out_text)
                self.assertEqual(len(fake.requests), 10, fake.last_user_messages)
                self.assertEqual(sessions, {conversation})
                self.assertEqual(len(set(fake.session_headers)), 1)
                self.assertFalse(fake.heartbeat_seen.is_set())
                self.assertEqual(result.status["dsh_conversation_id"], conversation)
                self.assertEqual(result.status["heartbeat"]["pings"], [])
                self.assertFalse(result.status["heartbeat"]["awaiting_input"])
                self.assertTrue(result.status["control"]["listener_closed"], result.status)
                # Each question was delivered into the single request stream.
                request_text = json.dumps(fake.requests)
                for number in range(1, 11):
                    self.assertIn(f"Question {number}:", request_text, number)
            finally:
                if thread.is_alive():
                    try:
                        status = json.loads((root / "out.md.status.json").read_text(encoding="utf-8"))
                        pid = status.get("pid")
                    except (OSError, ValueError):
                        pid = None
                    if isinstance(pid, int):
                        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                       capture_output=True, check=False)
                    thread.join(timeout=10)
                self.assertFalse(thread.is_alive())

    def test_plugin_steers_same_agent_and_cleans_up_listener(self):
        with tempfile.TemporaryDirectory(prefix="dsh-real-plugin-") as tmp, FakeChatCompletions() as fake:
            root = Path(tmp)
            control = root / "run.control.json"
            fake.expect_ping_descriptor(control)
            patch_path = root / "patch.yml"
            token = "k" * 64
            run_id = "real-plugin-test"
            patch_path.write_text(
                build_patch(
                    "beam-free", "", "DSH_PLUGIN_TEST_KEY", 512, fake.base_url,
                    {"plugin": Path("reality_engine/scripts/dsh_heartbeat_control.mjs").resolve(),
                     "endpoint": control},
                ),
                encoding="utf-8",
            )
            env = dict(os.environ)
            env.update({
                "DSH_PLUGIN_TEST_KEY": "local-test-key",
                "DSH_HEARTBEAT_TOKEN": token,
                "DSH_HEARTBEAT_RUN_ID": run_id,
                "DSH_PERMISSION_MODE": "read-only",
                "PATH": str(DSH.parent) + os.pathsep + env.get("PATH", ""),
            })
            process = subprocess.Popen(
                [str(DSH), "--profile", "headless", "--patch", str(patch_path), "--json", "-"],
                cwd=tmp,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            try:
                assert process.stdin is not None
                process.stdin.write("Run the local fake task.")
                process.stdin.close()
                endpoint = wait_control_endpoint(control, process=process, timeout=25)
                self.assertIsNotNone(endpoint, "control plugin did not bind the live agent")
                assert endpoint is not None
                transport = ControlTransport(control, token=token, run_id=run_id,
                                             session_id=endpoint.session_id)
                delivery = transport.ping(
                    ping_id=f"{run_id}-ping-1",
                    sequence=1,
                    message="Automated status check; continue working.",
                    session_id=endpoint.session_id,
                )
                self.assertTrue(delivery.ok, delivery.error)
                stdout, stderr = process.communicate(timeout=40)
            finally:
                self._kill_tree(process)
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()
            self.assertEqual(process.returncode, 0, stderr[-2000:])
            final_events = [json.loads(line) for line in stdout.splitlines()
                            if line.strip().startswith("{")]
            finals = [event.get("text", "") for event in final_events if event.get("type") == "final"]
            self.assertTrue(finals)
            self.assertIn("integration complete", finals[-1])
            self.assertTrue(fake.heartbeat_seen.is_set(), "steering message never reached the model request")
            self.assertGreaterEqual(len(fake.requests), 2)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.3)
                self.assertNotEqual(sock.connect_ex((endpoint.host, endpoint.port)), 0,
                                    "control listener survived process exit")

    def test_run_supervised_parses_real_dsh_events_and_answers_heartbeat(self):
        with tempfile.TemporaryDirectory(prefix="dsh-real-supervisor-") as tmp, FakeChatCompletions() as fake:
            root = Path(tmp)
            control = root / "run.control.json"
            fake.expect_ping_descriptor(control)
            patch_path = root / "patch.yml"
            token = "s" * 64
            run_id = "real-supervisor-test"
            patch_path.write_text(
                build_patch(
                    "beam-free", "", "DSH_PLUGIN_TEST_KEY", 512, fake.base_url,
                    {"plugin": Path("reality_engine/scripts/dsh_heartbeat_control.mjs").resolve(),
                     "endpoint": control},
                ),
                encoding="utf-8",
            )
            env = dict(os.environ)
            env.update({
                "DSH_PLUGIN_TEST_KEY": "local-test-key",
                "DSH_PERMISSION_MODE": "read-only",
                "PATH": str(DSH.parent) + os.pathsep + env.get("PATH", ""),
            })
            result = run_supervised(
                argv=[str(DSH), "--profile", "headless", "--patch", str(patch_path), "--json", "-"],
                env=env,
                cwd=tmp,
                task_text="Run the local fake task.",
                out_path=root / "out.md",
                log_path=root / "out.md.log",
                status_path=root / "out.md.status.json",
                control_path=control,
                heartbeat=HeartbeatConfig(idle_seconds=0.5, response_window_seconds=5.0, max_unanswered=2),
                control_token=token,
                run_id=run_id,
                metadata={"model": "beam-free", "effort": "", "account": "2", "permission": "read-only"},
                control_ready_timeout=25,
            )
            self.assertEqual(result.rc, 0, result.detail)
            self.assertIn("integration complete", result.out_text)
            self.assertTrue(result.status["control"]["listener_closed"], result.status)
            pings = result.status["heartbeat"]["pings"]
            self.assertGreaterEqual(len(pings), 1)
            self.assertEqual(
                pings[0]["outcome"], "answered",
                {"pings": pings, "events": result.status["heartbeat"]["events"][-8:]},
            )
            self.assertTrue(pings[0]["delivery_ok"], pings[0])
            self.assertIn(pings[0]["answered_by"],
                          {"thinking", "text", "tool_call", "tool_result", "final", "step_output"})
            self.assertTrue(fake.heartbeat_seen.is_set())
            saved = json.loads(result.status_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["exit_code"], 0)
            self.assertNotIn(token, result.status_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
