#!/usr/bin/env python3
"""HP throughput bench + MCP start/read/cancel check (2026-10-31).

    python tasks/efficiency/hp_bench_run.py mcp-check
    python tasks/efficiency/hp_bench_run.py bench [--waves 1,3,5]

Bench: one shared ``C:\\RE\\repo`` checkout (one upload), the same tiny real
task, and 1/3/5 harness workers launched within seconds of each other on Go
account 1.  Free RAM, worker RSS and CPU are sampled once while the wave runs;
each worker's wall time is split into model wait vs local time from the
``at`` timestamps in its heartbeat status file (the raw event stream has no
timestamps).  Model use is deliberately small: one read + one short answer.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "plugins" / "dsh-worker" / "server"))

from reality_engine.scripts import hp_run, hp_worker  # noqa: E402

PY = r"%USERPROFILE%\AppData\Local\Programs\Python\Python314-arm64\python.exe"
REMOTE_REPO = hp_run.remote("repo")
BENCH_BRIEF_REMOTE = hp_run.remote("bench_brief.md")
OUT = REPO / "tasks" / "efficiency"

BENCH_BRIEF = """# Task — one-line repo fact

You are on a shared HP checkout. Do exactly this, then stop:
1. Read `reality_engine/config.py` (one read; do not read anything else).
2. Answer with the name of the first ALL_CAPS constant you saw and its line number,
   in one line: `NAME line N`.

Do not run tests, do not use MCP tools, do not explore other files, do not write files.
"""

MCP_BRIEF = """# Task — one-line repo fact

Read `reality_engine/config.py` in your checkout and write `BENCH_NOTE.md` at the
checkout root containing exactly one line: the name of the first ALL_CAPS constant
and its line number. Do not read any other file, run no tests, use no MCP tools, and stop
after writing the file.
"""

MCP_CANCEL_BRIEF = """# Task — long read (cancel test)

Read `tasks/worker_context/CONTEXT.md` and summarize every numbered section in your
final answer, one bullet per section. Take your time; do not stop early.
"""


def upload_text(remote: str, text: str) -> None:
    hp_run.ps(
        f"New-Item -ItemType Directory -Force -Path '{hp_run.ROOT}' | Out-Null\n"
        f"[IO.File]::WriteAllBytes('{remote}', "
        f"[Convert]::FromBase64String('{base64.b64encode(text.encode()).decode()}'))"
    )


def harness_command(name: str) -> str:
    job = hp_run.remote("jobs", name)
    py = PY.replace("%USERPROFILE%", "%USERPROFILE%")
    # ``hp_run``'s wrapper writes exit.txt in the *current* directory, so the
    # command must never ``cd`` away from the job dir: PYTHONPATH resolves the
    # managed module from the shared checkout instead (2026-10-31: ``cd`` sent
    # exit.txt to C:\RE\repo and the wave waited for a job that had finished).
    return (
        f'set "PYTHONPATH={REMOTE_REPO}"\r\n'
        f'"{py}" -m reality_engine.scripts.run_deepseek_harness '
        f"--model {hp_worker.MODEL} --task-file \"{BENCH_BRIEF_REMOTE}\" "
        f'--out-file "{job}\\result.md" --cwd "{REMOTE_REPO}" --account 1 '
        f'--permission read-only --allow-paid --no-refresh --timeout 600 '
        f'--status-file "{job}\\status.json" --max-output-tokens 4096'
    )


def resources() -> dict:
    script = (
        "$os = Get-CimInstance Win32_OperatingSystem\n"
        "$p = Get-Process -Name node,python,dsh -ErrorAction SilentlyContinue\n"
        "$rss = if ($p) { [math]::Round((($p | Measure-Object WorkingSet64 -Sum).Sum)/1MB) } else { 0 }\n"
        "$cpu = [math]::Round((Get-CimInstance Win32_Processor | "
        "Measure-Object -Property LoadPercentage -Average).Average, 1)\n"
        "[pscustomobject]@{ free_mb = [math]::Round($os.FreePhysicalMemory/1KB); "
        "total_mb = [math]::Round($os.TotalVisibleMemorySize/1KB); "
        "worker_procs = @($p).Count; worker_rss_mb = $rss; cpu_pct = $cpu } | ConvertTo-Json -Compress"
    )
    try:
        return json.loads(hp_run.ps(script, timeout=30))
    except (SystemExit, ValueError):
        return {}


def split_times(status: dict) -> dict:
    """Wall time split from the heartbeat events: startup, model wait, local.

    The gap that *ends* at a model-produced event (thinking/text/step_output/
    tool_call/final) is provider time: the model was deciding or writing.  The
    first such gap also contains dsh cold start, so it is reported separately
    as ``startup_seconds`` instead of inflating model wait.  Everything else
    (tool execution, harness teardown) is local.
    """
    hb = status.get("heartbeat") or {}
    events = []
    for event in hb.get("events") or []:
        try:
            events.append((datetime.fromisoformat(event["at"]), event.get("kind")))
        except (KeyError, TypeError, ValueError):
            continue
    try:
        started = datetime.fromisoformat(status["started_at"])
        ended = datetime.fromisoformat(status["ended_at"])
    except (KeyError, TypeError, ValueError):
        return {}
    model_kinds = {"thinking", "text", "step_output", "tool_call", "final"}
    startup = model = 0.0
    prev_at = started
    for index, (at, kind) in enumerate(events):
        gap = max(0.0, (at - prev_at).total_seconds())
        if kind in model_kinds:
            if index == 0:
                startup += gap
            else:
                model += gap
        prev_at = at
    wall = status.get("duration_seconds") or (ended - started).total_seconds()
    wall = float(wall)
    return {
        "wall_seconds": round(wall, 1),
        "startup_seconds": round(startup, 1),
        "model_wait_seconds": round(model, 1),
        "local_seconds": round(max(0.0, wall - startup - model), 1),
        "model_wait_share": round(model / wall, 3) if wall else None,
        "events": len(events),
        "exit_code": status.get("exit_code"),
        "state": status.get("state"),
    }


def run_wave(count: int) -> dict:
    upload_text(BENCH_BRIEF_REMOTE, BENCH_BRIEF)
    names = [f"bench{count}-{chr(ord('a') + i)}" for i in range(count)]
    for name in names:
        hp_run.cmd_run(name, harness_command(name), method="wmi")
    started = time.time()
    sample = None
    rows: dict[str, dict] = {}
    while time.time() - started < 900:
        rows = {r["name"]: r for r in hp_run.parse_status(hp_run.ps(hp_run.STATUS_SCRIPT))}
        mine = {name: rows[name] for name in names if name in rows}
        if sample is None and any(r["state"] == "running" for r in mine.values()):
            busy = sum(1 for r in rows.values() if r["state"] == "running")
            sample = {"at_seconds": round(time.time() - started, 1),
                      "running_at_sample": sum(1 for r in mine.values() if r["state"] == "running"),
                      "other_running_jobs": max(0, busy - sum(
                          1 for r in mine.values() if r["state"] == "running")),
                      **resources()}
        if len(mine) == len(names) and all(r["state"] == "done" for r in mine.values()):
            break
        time.sleep(5)
    results = []
    local = OUT / "hp_bench_raw"
    local.mkdir(parents=True, exist_ok=True)
    for name in names:
        job = hp_run.remote("jobs", name)
        status_path = local / f"{name}.status.json"
        result_path = local / f"{name}.result.md"
        hp_run._scp([f"{hp_run.HOST}:{job.replace(chr(92), '/')}/status.json", str(status_path)])
        hp_run._scp([f"{hp_run.HOST}:{job.replace(chr(92), '/')}/result.md", str(result_path)])
        status = {}
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        answer = ""
        try:
            answer = result_path.read_text(encoding="utf-8", errors="replace")[:300].strip()
        except OSError:
            pass
        row = {"job": name, **split_times(status), "answer": answer}
        results.append(row)
    problems = [r["job"] for r in results if not r.get("answer") or r.get("exit_code") != 0]
    wave = {"workers": count, "sample": sample, "jobs": results}
    if problems:
        wave["problems"] = problems
        print(f"WAVE {count}: jobs without a clean answer: {problems}", file=sys.stderr)
    return wave


# --------------------------------------------------------------------------- #
# MCP check: start, read and cancel an HP job through the real MCP tools
# --------------------------------------------------------------------------- #
def _payload(result) -> dict:
    data = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None)
    if data is None:
        for block in result.content:
            if getattr(block, "type", None) == "text":
                data = json.loads(block.text)
                break
    return data or {}


async def mcp_check() -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = os.environ.copy()
    env["DSH_WORKER_REPO_ROOT"] = str(REPO)
    env["DSH_WORKER_RUNTIME_DIR"] = str(hp_worker.runtime_dir())
    env.pop("REALITY_DATA_ROOT", None)
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(REPO / "plugins" / "dsh-worker" / "server" / "dsh_worker_mcp.py")],
        env=env,
        cwd=str(REPO),
    )

    async def call(session, name, arguments, timeout=300):
        return _payload(await session.call_tool(name, arguments,
                                                read_timeout_seconds=timeout))

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            schema = (tools["start_worker"].input_schema or {}).get("properties") or {}
            record = {"start_schema_has": [k for k in ("host", "dbs", "account") if k in schema]}

            start = await call(session, "start_worker", {
                "brief": MCP_BRIEF, "host": "hp", "permission": "workspace-write",
                "hard_timeout_seconds": 600,
            })
            record["start"] = start
            job_id = start.get("job_id")
            seen_running = False
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                status = await call(session, "worker_status", {"job_id": job_id})
                record.setdefault("status_samples", []).append(
                    {k: status.get(k) for k in ("phase", "host", "summary", "hp", "done")})
                if status.get("phase") in ("running", "starting"):
                    seen_running = True
                if status.get("done") or status.get("phase") in (
                        "finished", "failed", "cancelled", "lost"):
                    break
                await asyncio.sleep(3)
            record["seen_running"] = seen_running
            record["result"] = await call(session, "worker_result", {"job_id": job_id})
            listed = await call(session, "list_workers", {"limit": 20})
            record["listed_row"] = next(
                (r for r in listed.get("jobs", []) if r.get("job_id") == job_id), None)

            cancel_start = await call(session, "start_worker", {
                "brief": MCP_CANCEL_BRIEF, "host": "hp", "permission": "read-only",
                "hard_timeout_seconds": 900,
            })
            cancel_id = cancel_start.get("job_id")
            record["cancel_start"] = cancel_start
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                status = await call(session, "worker_status", {"job_id": cancel_id})
                if status.get("phase") == "running":
                    break
                await asyncio.sleep(3)
            refused = await call(session, "cancel_worker", {"job_id": cancel_id})
            record["cancel_without_confirm"] = refused
            cancelled = await call(session, "cancel_worker",
                                   {"job_id": cancel_id, "confirm": True})
            record["cancel_confirmed"] = cancelled
            record["cancel_final"] = await call(session, "worker_status",
                                                {"job_id": cancel_id})
            return record


def cancel_only() -> dict:
    """Start one real HP job and cancel it through Manager.cancel_worker."""
    import core  # noqa: PLC0415 - plugin module on sys.path above

    env = os.environ.copy()
    env["DSH_WORKER_REPO_ROOT"] = str(REPO)
    env["DSH_WORKER_RUNTIME_DIR"] = str(hp_worker.runtime_dir())
    manager = core.Manager(core.load_config(env))
    started = manager.start_worker(brief=MCP_CANCEL_BRIEF, host="hp", permission="read-only",
                                   permission="read-only", hard_timeout_seconds=900)
    job_id = started["job_id"]
    deadline = time.monotonic() + 180
    seen = None
    while time.monotonic() < deadline:
        seen = manager.get_status(job_id).get("phase")
        if seen == "running":
            break
        time.sleep(3)
    refused = manager.cancel_worker(job_id)
    done = manager.cancel_worker(job_id, confirm=True, reason="bench cancel check")
    final = manager.get_status(job_id)
    return {"job_id": job_id, "phase_before_cancel": seen,
            "cancel_without_confirm": refused, "cancel_confirmed": done,
            "final_phase": final.get("phase"), "final_done": final.get("done")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("mcp-check", "bench", "cancel-only"))
    ap.add_argument("--waves", default="1,3,5")
    args = ap.parse_args()
    if args.command == "cancel-only":
        record = cancel_only()
        (OUT / "hp_cancel_check.json").write_text(json.dumps(record, indent=2),
                                                  encoding="utf-8")
        print(json.dumps(record, indent=2))
        return 0
    if args.command == "mcp-check":
        record = asyncio.run(mcp_check())
        (OUT / "hp_mcp_check.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(json.dumps(record, indent=2)[:8000])
        return 0
    summary = {"when": datetime.now().isoformat(timespec="seconds"),
               "account": "1", "model": hp_worker.MODEL, "waves": []}
    for count in [int(x) for x in args.waves.split(",") if x.strip()]:
        wave = run_wave(count)
        summary["waves"].append(wave)
        print(json.dumps(wave, indent=2))
    (OUT / "hp_bench_results.json").write_text(json.dumps(summary, indent=2),
                                              encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
