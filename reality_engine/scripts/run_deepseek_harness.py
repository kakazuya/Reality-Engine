"""Run one task headlessly in DeepSeek Harness (dsh) on an OpenCode Go model, so a Claude orchestrator can use it
as a worker.

    python -m reality_engine.scripts.run_deepseek_harness --model beam-free \
        --task-file task.md --out-file out.md [--cwd DIR] [--timeout 900] [--account 1|2] [--permission read-only]

dsh is installed with bun (`bun add -g @deepseek-ai/dsh`, Shivam 2026-10-20: bun only, never npm). Go needs an
`x-opencode-session: <uuid>` header on every request (else 400 MissingSessionID). dsh's pi-ai provider route takes
`headers`, so each run writes a temporary `--patch` overlay that declares an `opencode-go` route with a stable session id
and selects the model. The key is read from the Windows user env (OPENCODE_GO_API_KEY or _2) and never printed.

The task goes in on stdin and the final answer goes to --out-file. dsh's stderr (reasoning, `dsh: <code>` errors) goes
to <out-file>.log. The exit code is dsh's (0 = task completed, 1 = failed), 124 = explicit hard timeout, 125 = heartbeat
supervision stopped after two unanswered status requests, 126 = heartbeat control could not be established, 1 also for a
refused setup (unknown/paid model, missing key), 2 = argparse usage error.

Heartbeat supervision (default): dsh runs with `--json`, and a per-run local Cordis plugin
(`dsh_heartbeat_control.mjs`) exposes a token-protected loopback mailbox bound to the same live agent. After 900 s
without committed worker activity the supervisor asks that same agent for a status update; it waits 900 s for any real
activity. Two consecutive unanswered requests stop the run. A real model/tool event resets the count. The local control
descriptor is <out-file>.control.json, the machine-readable supervision record is <out-file>.status.json, and the raw JSON
event stream is <out-file>.events.jsonl. `--timeout` is now an explicitly requested hard wall-clock cutoff, separate
from the heartbeat; omitting it no longer means "kill at 900 s". `--followup-wait N` opts into a bounded host-side
`agent/turn-stopping` wait for explicit same-conversation follow-ups; 0 (default) preserves ordinary one-shot exit.
A parent orchestrator can own the per-run control token by setting an environment variable and passing
`--control-token-env NAME`; it is never written to config/status/logs.

Model ids: beam-free, longcat-2.5-preview-free, minimax-m3.1-flash-free (free); deepseek-v4.1-flash is PAID on Go
and needs --allow-paid. `<id>~<effort>` sets reasoning effort (low/medium/high/xhigh/max); MiniMax defaults to
low because at default effort it can reason through its whole output budget and answer empty.
DeepSeek models always run at max (Shivam 2026-10-22; was xhigh until then), and only off-peak: peak is Mon-Fri
06:30-09:30 and 11:30-15:30 IST, everything else (weekends too) is off-peak. Outside off-peak a DeepSeek run is refused unless --peak-ok is passed after Shivam confirms the timing.
An explicitly authorized --smoke-test can override effort or disable reasoning, with an output cap of at most
1024 tokens. --max-output-tokens sets the main request cap and disables auxiliary LLM session titling.
"""
import argparse
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reality_engine.scripts.resource_watchdog import user_env
from reality_engine.scripts.go_session import session_id   # stable x-opencode-session (Shivam's rule 2026-10-20)
from reality_engine.scripts.dsh_heartbeat import (
    DEFAULT_IDLE_SECONDS,
    DEFAULT_MAX_UNANSWERED,
    DEFAULT_RESPONSE_WINDOW_SECONDS,
    HeartbeatConfig,
    resolve_control_token,
    run_supervised,
)

DSH = Path.home() / ".bun" / "bin" / "dsh.exe"
REPO = Path(__file__).resolve().parents[2]
BASE_URL = "https://opencode.ai/zen/go/v1"
FREE = {"beam-free", "longcat-2.5-preview-free", "minimax-m3.1-flash-free"}
PAID = {"deepseek-v4.1-flash"}
REASONING = {"minimax-m3.1-flash-free": "low", "deepseek-v4.1-flash": "max"}   # models that take reasoning_effort
FIXED_EFFORT = {m: "max" for m in REASONING if m.startswith("deepseek")}   # DeepSeek: max only (Shivam 2026-10-22)
IST = timezone(timedelta(hours=5, minutes=30))


def off_peak(now=None):
    """DeepSeek off-peak (OpenCode Go docs): peak is Mon-Fri 01:00-04:00 and 06:00-10:00 UTC = 06:30-09:30 and
    11:30-15:30 IST; every other hour, weekends included, is off-peak (half price). Peak never crosses midnight in UTC,
    Beijing or IST, so the weekday is the same in all three."""
    u = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return not (u.weekday() < 5 and (1 <= u.hour < 4 or 6 <= u.hour < 10))
EFFORTS = ("low", "medium", "high", "xhigh", "max")
KEY_ENV = {"1": "OPENCODE_GO_API_KEY", "2": "OPENCODE_GO_API_KEY_2"}


def build_patch(model, effort, key_env, max_tokens=None, base_url=BASE_URL, control=None, workspace=None):
    """YAML overlay with a stable session header, optional output cap, and heartbeat plugin."""
    if model in REASONING:
        efforts = "\n".join(f"              {e}: {e}" for e in EFFORTS)
        entry = f"          - id: {model}\n            reasoningEfforts:\n              off: null\n{efforts}"
    else:
        entry = f"          - id: {model}\n            reasoningEfforts: false"
    if max_tokens is not None:
        entry += f"\n            maxTokens: {max_tokens}"
    compat = ("        compat:\n          thinkingFormat: deepseek\n          supportsReasoningEffort: true\n"
              "          maxTokensField: max_tokens\n          supportsUsageInStreaming: true\n"
              if model.startswith("deepseek") else "")
    sel = f"    reasoningEffort: {effort}\n" if effort else ""
    retry = "        retryPolicy:\n          mode: normal\n          maxRetries: 0\n" if base_url != BASE_URL else ""
    title = "- id: session-title-llm\n  disabled: true\n" if max_tokens is not None else ""
    patch = (f"{title}- id: llm-pi-ai\n  config:\n    providers:\n      opencode-go:\n"
             f"        displayName: OpenCode Go\n        apiKeyEnv: {key_env}\n        api: openai-completions\n"
             f"        baseURL: {base_url}\n{compat}        headers:\n          x-opencode-session: {session_id("dsh", model, key_env)}\n"
             f"{retry}"
             f"        models:\n{entry}\n"
             f"- id: agent-default-model\n  config:\n    provider: opencode-go\n    model: {model}\n{sel}")
    if control:
        plugin = Path(control["plugin"]).resolve().as_uri()
        endpoint = Path(control["endpoint"]).resolve()
        patch += (
            "- insert:\n"
            "    - id: dsh-heartbeat-control\n"
            f"      name: {json.dumps(plugin)}\n"
            "      config:\n"
            f"        endpointFile: {json.dumps(endpoint.as_posix())}\n"
        )
        followup_wait = control.get("followup_wait") or 0
        if followup_wait:
            patch += f"        followupWaitSeconds: {float(followup_wait):g}\n"
    if workspace is not None and Path(workspace).resolve() != REPO.resolve():
        patch += code_intel_patch(workspace)
    return patch


def code_intel_patch(workspace):
    """Point the profile's code-intel MCP server at the worker's own checkout.

    The headless profile pins CODE_INTEL_REPO_ROOT to the main checkout, so a
    worktree worker's lookups described main, not the files it was editing.
    The server script stays the main checkout's (worktrees cut from an older
    commit may predate the freshness fix); only the indexed root moves.
    """
    ws = Path(workspace).resolve().as_posix()
    server = (REPO / "plugins" / "code-intel" / "server" / "server.py").resolve().as_posix()
    return (
        "- id: mcp-code-intel\n"
        "  config:\n"
        "    serverName: code-intel\n"
        "    transport: stdio\n"
        f"    command: {json.dumps(Path(sys.executable).as_posix())}\n"
        f"    args:\n      - {json.dumps(server)}\n"
        f"    cwd: {json.dumps(ws)}\n"
        "    env:\n"
        f"      CODE_INTEL_REPO_ROOT: {json.dumps(ws)}\n"
        '      PYTHONUTF8: "1"\n'
        "    toolCallTimeoutMs: 60000\n"
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--model", required=True, help="Go model id, optionally <id>~<effort>")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--task-file")
    g.add_argument("--task", help="task text inline (one orchestrator call, no task file to write first)")
    ap.add_argument("--out-file", required=True)
    ap.add_argument("--cwd", default=str(REPO), help="workspace root the agent works in (default: repo root)")
    ap.add_argument("--timeout", type=int, default=None,
                    help="explicit hard wall-clock timeout in seconds (exit 124); omitted means no hard cutoff")
    ap.add_argument("--heartbeat-interval", type=float, default=DEFAULT_IDLE_SECONDS,
                    help=f"seconds of no committed worker activity before a status request (default {DEFAULT_IDLE_SECONDS})")
    ap.add_argument("--heartbeat-response-window", type=float, default=DEFAULT_RESPONSE_WINDOW_SECONDS,
                    help=f"seconds to wait for a response to each status request (default {DEFAULT_RESPONSE_WINDOW_SECONDS})")
    ap.add_argument("--heartbeat-misses", type=int, default=DEFAULT_MAX_UNANSWERED,
                    help=f"consecutive unanswered requests before stopping, 2-10 (default {DEFAULT_MAX_UNANSWERED})")
    ap.add_argument("--followup-wait", type=float, default=0,
                    help="bounded host-side wait after each answer for an explicit same-conversation follow-up "
                         "in seconds; 0 disables it and preserves ordinary one-shot exit (default 0)")
    ap.add_argument("--status-file", help="machine-readable supervision record (default: <out-file>.status.json)")
    ap.add_argument("--control-token-env",
                    help="name of an environment variable holding the per-run control token (default: generate one)")
    ap.add_argument("--account", choices=("1", "2"), default="2", help="which OpenCode Go key (default 2; account 1 is exhausted)")
    ap.add_argument("--permission", choices=("read-only", "workspace-write", "danger-full-access"),
                    default="read-only", help="dsh sandbox mode (default read-only: workers read, Claude writes)")
    ap.add_argument("--allow-paid", action="store_true", help="allow a paid Go model (needs Shivam's go-ahead)")
    ap.add_argument("--peak-ok", action="store_true",
                    help="run a DeepSeek model in peak hours (Mon-Fri 06:30-09:30, 11:30-15:30 IST) (only after Shivam confirms the timing)")
    ap.add_argument("--no-refresh", action="store_true", help="skip rebuilding the hotline context files")
    ap.add_argument("--max-output-tokens", type=int, help="positive per-request output-token cap")
    ap.add_argument("--reasoning", choices=("off", "on"), help="explicit reasoning toggle; off requires --smoke-test")
    ap.add_argument("--smoke-test", action="store_true", help="bounded connectivity probe; permits explicit effort overrides")
    ap.add_argument("--probe-base-url", help="localhost-only audit proxy; requires --smoke-test")
    a = ap.parse_args()

    model, _, effort = a.model.partition("~")
    if model not in FREE | PAID:
        sys.exit(f"unknown Go model {model!r}; known: {sorted(FREE | PAID)}")
    if model in PAID and not a.allow_paid:
        sys.exit(f"{model} is PAID on Go; pass --allow-paid only with Shivam's approval")
    if model in FIXED_EFFORT and effort and effort != FIXED_EFFORT[model] and not a.smoke_test:
        sys.exit(f"{model} always runs at {FIXED_EFFORT[model]} (Shivam's rule); drop ~{effort}")
    if model.startswith("deepseek") and not off_peak() and not a.peak_ok:
        sys.exit(f"{datetime.now(IST):%H:%M} IST is in DeepSeek peak hours (Mon-Fri 06:30-09:30, 11:30-15:30 IST); "
                 "ask Shivam, then pass --peak-ok if he confirms")
    if effort and (model not in REASONING or effort not in EFFORTS):
        sys.exit(f"effort {effort!r} not valid for {model}")
    effort = effort or REASONING.get(model)
    if a.reasoning == "off":
        if not a.smoke_test:
            sys.exit("reasoning off is approved only for an explicit --smoke-test")
        effort = "off"
    if a.max_output_tokens is not None and a.max_output_tokens <= 0:
        sys.exit("--max-output-tokens must be positive")
    if a.smoke_test and (a.max_output_tokens is None or a.max_output_tokens > 1024):
        sys.exit("--smoke-test requires --max-output-tokens between 1 and 1024")
    base_url = BASE_URL
    if a.probe_base_url:
        parsed = urlparse(a.probe_base_url)
        if not a.smoke_test or parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or parsed.username or parsed.password:
            sys.exit("--probe-base-url must be a credential-free localhost HTTP URL for --smoke-test")
        base_url = a.probe_base_url
    if a.timeout is not None and a.timeout <= 0:
        sys.exit("--timeout must be positive when supplied")
    if a.followup_wait < 0 or a.followup_wait > 3600:
        sys.exit("--followup-wait must be 0..3600 seconds")
    try:
        heartbeat = HeartbeatConfig(
            idle_seconds=a.heartbeat_interval,
            response_window_seconds=a.heartbeat_response_window,
            max_unanswered=a.heartbeat_misses,
            hard_timeout=a.timeout,
        )
    except ValueError as exc:
        sys.exit(f"heartbeat configuration: {exc}")
    task = a.task if a.task is not None else Path(a.task_file).read_text(encoding="utf-8")
    if not task.strip():
        sys.exit("task file is empty")
    if not DSH.exists():
        sys.exit(f"dsh not found at {DSH}; install with: bun add -g @deepseek-ai/dsh")

    env = user_env()
    # dsh requires the installed Node 24 runtime; Codex may prepend its bundled Node.
    node24 = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "nodejs"
    env["PATH"] = str(node24) + os.pathsep + str(DSH.parent) + os.pathsep + env.get("PATH", "")
    key_env = KEY_ENV[a.account]
    if not env.get(key_env):
        sys.exit(f"{key_env} is not set")
    env["DSH_PERMISSION_MODE"] = a.permission

    # hotline (Shivam 2026-10-20): refresh the shared context before every run, so the worker reads the whole
    # conversation (session_digest) and the live machine state (worker_context), not a stale or empty picture.
    # ~/.dsh/AGENTS.md tells dsh to read tasks/hotline/ first. Failures here never block the task.
    if not a.no_refresh:
        root = Path(__file__).resolve().parents[2]
        for mod in ("session_digest", "worker_context"):
            subprocess.run([sys.executable, "-m", f"reality_engine.scripts.{mod}"], cwd=root, capture_output=True,
                           timeout=300)

    out = Path(a.out_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    status_path = Path(a.status_file) if a.status_file else out.with_name(out.name + ".status.json")
    control_path = out.with_name(out.name + ".control.json")
    log = out.with_name(out.name + ".log")
    run_id = f"dsh-{datetime.now(IST):%Y%m%dT%H%M%S}-{secrets.token_hex(4)}"
    try:
        control_token = resolve_control_token(env, a.control_token_env)
    except ValueError as exc:
        sys.exit(f"control token: {exc}")
    env["DSH_HEARTBEAT_TOKEN"] = control_token
    env["DSH_HEARTBEAT_RUN_ID"] = run_id
    patch_info = {
        "plugin": Path(__file__).with_name("dsh_heartbeat_control.mjs"),
        "endpoint": control_path,
        "followup_wait": a.followup_wait,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as f:
        f.write(build_patch(model, effort, key_env, a.max_output_tokens, base_url, patch_info,
                                workspace=a.cwd))
        patch = f.name
    t0 = time.time()
    try:
        result = run_supervised(
            argv=[str(DSH), "--profile", "headless", "--patch", patch, "--json", "-"],
            env=env,
            cwd=a.cwd,
            task_text=task,
            out_path=out,
            log_path=log,
            status_path=status_path,
            control_path=control_path,
            heartbeat=heartbeat,
            control_token=control_token,
            run_id=run_id,
            metadata={
                "model": model,
                "effort": effort,
                "account": a.account,
                "permission": a.permission,
                "provider_session_id": session_id("dsh", model, key_env),
                "max_output_tokens": a.max_output_tokens,
                "smoke_test": a.smoke_test,
                "followup_wait_seconds": a.followup_wait,
                "cwd": a.cwd,
            },
        )
    finally:
        os.unlink(patch)
    secs = time.time() - t0
    rc = result.rc
    print(f"rc={rc} secs={secs:.0f} out={out} ({len(result.out_text)} chars) log={log} status={status_path}")
    if rc:
        stderr_tail = str(result.status.get("stderr_tail") or "")
        tail = [ln for ln in stderr_tail.splitlines() if ln.startswith(("dsh:", "run_deepseek_harness:"))
                and not ln.startswith("dsh: reasoning")]
        if result.detail:
            tail.append(f"run_deepseek_harness: {result.detail}")
        print("\n".join(tail[-3:]), file=sys.stderr)
    sys.exit(rc)


if __name__ == "__main__":
    main()
